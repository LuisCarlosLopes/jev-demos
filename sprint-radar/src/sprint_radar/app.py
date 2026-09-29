import asyncio
import json
import time
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse

from . import jev, model
from .ado import AdoClient, AdoError
from .config import Settings

ROOT = Path(__file__).resolve().parent
PROJECT_DIR = ROOT.parents[1]
CACHE_DIR = PROJECT_DIR / "cache"

try:
    # FastAPI recente exige escolher explicitamente se configura OpenTelemetry; não usamos.
    app = FastAPI(title="Sprint Radar · Jev", telemetry={"auto_configure": False})
except TypeError:
    app = FastAPI(title="Sprint Radar · Jev")
settings = Settings.load(PROJECT_DIR / ".env")
_snapshots: dict[str, dict] = {}


def _cache_path(iteration_id: str) -> Path:
    return CACHE_DIR / f"{iteration_id}.json"


def _today(value: str | None) -> date:
    if value:
        try:
            return date.fromisoformat(value)
        except ValueError:
            raise HTTPException(400, "today deve ser YYYY-MM-DD.") from None
    return date.today()


async def _load_snapshot(iteration_id: str, today: date, refresh: bool) -> dict:
    key = f"{iteration_id}:{today.isoformat()}"
    if not refresh and key in _snapshots:
        return _snapshots[key]
    raw = None if refresh else _read_cache(iteration_id)
    if raw is None:
        raw = await _fetch_raw(iteration_id)
        _write_cache(iteration_id, raw)
    snapshot = model.build_snapshot(
        raw["iteration"], raw["items"], raw["people"], raw["team_days_off"], today
    )
    model.attach_comments(snapshot, {int(k): v for k, v in raw.get("comments", {}).items()})
    snapshot["fetched_at"] = raw.get("fetched_at")
    _snapshots[key] = snapshot
    return snapshot


async def _fetch_raw(iteration_id: str) -> dict:
    try:
        ado = AdoClient(settings)
        iterations = await ado.list_iterations()
        iteration = next((it for it in iterations if it["id"] == iteration_id), None)
        if iteration is None:
            raise HTTPException(404, "Iteração não encontrada para o time.")
        ids, (people, team_off) = await asyncio.gather(
            ado.iteration_work_item_ids(iteration["path"]), ado.capacity(iteration_id)
        )
        items = await ado.work_items(ids)
        open_ids = [
            int(w["fields"]["System.Id"])
            for w in items
            if w.get("fields", {}).get("System.WorkItemType") == "Task"
            and w["fields"].get("System.State") in model.OPEN_STATES
        ]
        comments = await ado.comments(open_ids)
    except AdoError as error:
        raise HTTPException(502, str(error)) from None
    return {
        "iteration": iteration,
        "items": items,
        "people": people,
        "team_days_off": team_off,
        "comments": {str(k): v for k, v in comments.items()},
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def _read_cache(iteration_id: str) -> dict | None:
    path = _cache_path(iteration_id)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_cache(iteration_id: str, raw: dict) -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    _cache_path(iteration_id).write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")


def _public_snapshot(snapshot: dict) -> dict:
    nodes = {
        str(wid): {k: v for k, v in n.items() if k not in {"description", "acceptance"}}
        | {"has_description": bool(n["description"])}
        for wid, n in snapshot["nodes"].items()
    }
    return {k: v for k, v in snapshot.items() if k != "nodes"} | {"nodes": nodes}


@app.api_route("/", methods=["GET", "HEAD"])
async def index() -> FileResponse:
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/config")
async def config() -> dict:
    return {
        "provider": settings.provider,
        "model": settings.model,
        "has_jev_key": bool(settings.api_key),
        "has_ado_pat": bool(settings.ado_pat),
        "project": settings.ado_project,
        "team": settings.ado_team,
    }


@app.get("/api/sprints")
async def sprints() -> list[dict]:
    try:
        return await AdoClient(settings).list_iterations()
    except AdoError as error:
        cached = sorted(p.stem for p in CACHE_DIR.glob("*.json")) if CACHE_DIR.is_dir() else []
        if not cached:
            raise HTTPException(502, str(error)) from None
        out = []
        for iteration_id in cached:
            raw = _read_cache(iteration_id)
            if raw:
                out.append(raw["iteration"] | {"offline": True})
        return out


@app.get("/api/sprint/{iteration_id}")
async def sprint(
    iteration_id: str, refresh: bool = False, today: str | None = Query(default=None)
) -> dict:
    snapshot = await _load_snapshot(iteration_id, _today(today), refresh)
    return _public_snapshot(snapshot)


@app.get("/api/sprint/{iteration_id}/task/{task_id}/state")
async def task_state(iteration_id: str, task_id: int, today: str | None = None) -> dict:
    snapshot = await _load_snapshot(iteration_id, _today(today), False)
    task = snapshot["nodes"].get(task_id)
    if task is None or not task["is_task"]:
        raise HTTPException(404, "Task não encontrada nesta sprint.")
    return {
        "state": jev.build_state(task, snapshot),
        "questions": jev.build_questions(snapshot["sprint"]["finish"]),
    }


@app.get("/api/sprint/{iteration_id}/analyze")
async def analyze(iteration_id: str, today: str | None = None) -> StreamingResponse:
    snapshot = await _load_snapshot(iteration_id, _today(today), False)
    return StreamingResponse(_analyze_stream(snapshot), media_type="text/event-stream")


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _analyze_stream(snapshot: dict):
    tasks = [n for n in snapshot["nodes"].values() if n["open"]]
    questions = jev.build_questions(snapshot["sprint"]["finish"])
    client = jev.JevClient(settings)
    started = time.perf_counter()
    yield _sse(
        "start",
        {"total": len(tasks), "model": settings.model, "provider": settings.provider},
    )
    if not settings.api_key:
        yield _sse("fatal", {"message": f"{settings.provider.upper()}_API_KEY não configurada."})
        return

    results: dict[int, dict] = {}
    tokens_in = tokens_out = 0.0
    cost_reported = 0.0
    model_name = settings.model

    async def one(task: dict, http: object) -> tuple[dict, dict | None, str | None]:
        t0 = time.perf_counter()
        try:
            answer = await client.evaluate(http, jev.build_state(task, snapshot), questions)
        except jev.JevError as error:
            return task, None, str(error)
        answer["latency_ms"] = round((time.perf_counter() - t0) * 1000)
        return task, answer, None

    async with client.client() as http:
        pending = [asyncio.create_task(one(t, http)) for t in tasks]
        for finished in asyncio.as_completed(pending):
            task, answer, error = await finished
            if error:
                yield _sse("error", {"task_id": task["id"], "message": error})
                continue
            results[task["id"]] = answer
            usage = answer.get("usage", {})
            tokens_in += usage.get("input_tokens", 0)
            tokens_out += usage.get("output_tokens", 0)
            cost_reported += usage.get("cost", 0)
            model_name = answer.get("model") or model_name
            cost = cost_reported or jev.estimate_cost(tokens_in, tokens_out, model_name) or 0.0
            yield _sse(
                "result",
                {
                    "task_id": task["id"],
                    "answer": answer,
                    "progress": {
                        "done": len(results),
                        "elapsed_ms": round((time.perf_counter() - started) * 1000),
                        "input_tokens": tokens_in,
                        "output_tokens": tokens_out,
                        "cost_usd": cost,
                    },
                },
            )
    yield _sse(
        "done",
        {
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
            "analyzed": len(results),
            "total": len(tasks),
            "model": model_name,
            "input_tokens": tokens_in,
            "output_tokens": tokens_out,
            "cost_usd": cost_reported
            or jev.estimate_cost(tokens_in, tokens_out, model_name)
            or 0.0,
            "cost_source": "provider" if cost_reported else "estimated",
            "rollup": {str(k): v for k, v in model.rollup(snapshot, results).items()},
            "risk_labels": jev.RISK_LABELS,
        },
    )
