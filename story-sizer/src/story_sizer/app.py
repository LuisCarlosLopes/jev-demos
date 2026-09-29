"""API HTTP mínima + página estática. Rode com `uv run story-sizer-web`."""

import asyncio
import json

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from .ado import AdoClient, AdoError
from .config import ROOT, Settings, load_policy
from .jev import JevClient, JevError, build_questions
from .service import size_story, story_summary

app = FastAPI(title="Jev Story Sizer", telemetry={"auto_configure": False})
WEB = ROOT / "web"


def _settings() -> Settings:
    return Settings.load()


def _policy() -> dict:
    return load_policy()


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


@app.get("/api/config")
async def config() -> dict:
    s, p = _settings(), _policy()
    return {
        "model": s.jev_model,
        "team": s.ado_team,
        "project": s.ado_project,
        "allow_write": s.allow_write,
        "field": p["field"],
        "order": p["order"],
        "sizes": {
            k: {"label": v["label"], "effort": v["effort"], "days": v["days"]}
            for k, v in p["sizes"].items()
        },
        "confidence": p["confidence"],
        "validation": p.get("validation"),
        "factors": {k: v["label"] for k, v in p["factors"].items()},
        "flags": {k: v["label"] for k, v in p["flags"].items()},
    }


@app.get("/api/sprints")
async def sprints() -> list[dict]:
    try:
        ado = AdoClient(_settings())
    except AdoError as exc:
        raise HTTPException(500, str(exc)) from None
    try:
        its = await ado.team_iterations()
    except AdoError as exc:
        raise HTTPException(502, str(exc)) from None
    finally:
        await ado.aclose()
    return [
        {
            "id": i.id,
            "name": i.name,
            "path": i.path,
            "start": i.start,
            "finish": i.finish,
            "timeframe": i.timeframe,
        }
        for i in its
        if i.start  # ignora iterações sem datas (ex.: SP0)
    ]


@app.get("/api/stories")
async def stories(sprint: str, all: bool = False) -> dict:
    s, p = _settings(), _policy()
    try:
        ado = AdoClient(s)
    except AdoError as exc:
        raise HTTPException(500, str(exc)) from None
    try:
        ids = await ado.story_ids(sprint, only_unsized=not all)
        items = await ado.stories(ids) if ids else []
        # Horas das tasks filhas: o card mostra a estimativa do time ao lado do Jev.
        tasks = await ado.child_hours(ids) if ids else {}
        return {
            "sprint": sprint,
            "stories": [story_summary(st, ado, p, tasks.get(st.id)) for st in items],
        }
    except AdoError as exc:
        raise HTTPException(502, str(exc)) from None
    finally:
        await ado.aclose()


class SizeRequest(BaseModel):
    ids: list[int]


@app.post("/api/size")
async def size(req: SizeRequest) -> StreamingResponse:
    """Devolve NDJSON: uma linha por story, na ordem em que o Jev responde."""
    s, p = _settings(), _policy()
    if not req.ids:
        raise HTTPException(400, "Informe ids.")
    try:
        ado = AdoClient(s)
        jev = JevClient(s)
    except (AdoError, JevError) as exc:
        raise HTTPException(500, str(exc)) from None
    try:
        items = await ado.stories(req.ids[:200])
    except AdoError as exc:
        await jev.aclose()
        raise HTTPException(502, str(exc)) from None
    finally:
        await ado.aclose()
    questions = build_questions(p)

    async def gen():
        tasks = [asyncio.create_task(size_story(st, jev, p, questions)) for st in items]
        try:
            for done in asyncio.as_completed(tasks):
                result = await done
                yield json.dumps(result, ensure_ascii=False) + "\n"
        finally:
            await jev.aclose()

    return StreamingResponse(gen(), media_type="application/x-ndjson")


class ApplyRequest(BaseModel):
    id: int
    size: str


@app.post("/api/apply")
async def apply(req: ApplyRequest) -> dict:
    s, p = _settings(), _policy()
    if req.size not in p["order"]:
        raise HTTPException(400, "Tamanho inválido.")
    if not s.allow_write:
        raise HTTPException(403, "Escrita desligada (ALLOW_WRITE=false).")
    try:
        ado = AdoClient(s)
        await ado.set_size(req.id, req.size, p["field"])
    except AdoError as exc:
        raise HTTPException(502, str(exc)) from None
    finally:
        await ado.aclose()
    return {"ok": True, "id": req.id, "size": req.size}


def main() -> None:
    import uvicorn

    uvicorn.run("story_sizer.app:app", host="127.0.0.1", port=8765, reload=False)


if __name__ == "__main__":
    main()
