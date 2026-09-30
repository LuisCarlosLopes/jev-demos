import argparse
import json
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from .config import Settings
from .decisions import build_request, parse_response
from .fake import fake_response
from .jev import JevClient, ProviderError, estimate_cost

ROOT = Path(__file__).resolve().parents[2]


class AdaptRequest(BaseModel):
    messages: list[str] = Field(min_length=1, max_length=12)

    @field_validator("messages")
    @classmethod
    def check_messages(cls, messages):
        if any(not m.strip() or len(m) > 400 for m in messages):
            raise ValueError("Cada mensagem deve ter entre 1 e 400 caracteres.")
        return [m.strip() for m in messages]


def create_app(settings, client=None):
    catalog = json.loads((ROOT / "data/products.json").read_text())
    jev = client or JevClient(settings)
    cache = OrderedDict()
    totals = {"requests": 0, "cache_hits": 0, "errors": 0, "simulated_requests": 0}
    started_at = time.time()

    @asynccontextmanager
    async def lifespan(app):
        yield
        await jev.aclose()

    app = FastAPI(title="Sport Live · Jev", lifespan=lifespan)

    @app.get("/api/catalog")
    async def get_catalog():
        return {
            "items": catalog,
            "simulated": settings.fake,
            "configured": settings.fake or bool(settings.api_key),
        }

    @app.get("/api/consumption")
    async def consumption():
        return {
            **totals,
            **jev.metrics,
            "started_at": started_at,
            "provider": settings.provider,
            "model": settings.model,
            "simulated": settings.fake,
        }

    @app.post("/api/adapt")
    async def adapt(body: AdaptRequest):
        totals["requests"] += 1
        started = time.perf_counter()
        key = tuple(body.messages)
        if key in cache:
            totals["cache_hits"] += 1
            cache.move_to_end(key)
            return {
                **cache[key],
                "telemetry": {
                    **cache[key]["telemetry"],
                    "cached": True,
                    "jev_ms": 0,
                    "cost_usd": 0,
                },
            }
        state, questions = build_request(body.messages, catalog)
        try:
            if settings.fake:
                totals["simulated_requests"] += 1
                data, elapsed = fake_response(body.messages, catalog), None
            else:
                data, elapsed = await jev.decide(state, questions)
            result = parse_response(data, catalog)
        except ProviderError as error:
            totals["errors"] += 1
            return JSONResponse({"error": str(error)}, status_code=502)
        result["simulated"] = settings.fake
        result["telemetry"] = {
            "questions": len(questions),
            "jev_ms": elapsed,
            "server_ms": round((time.perf_counter() - started) * 1000, 1),
            "cost_usd": None if settings.fake else estimate_cost(result["usage"]),
            "cached": False,
        }
        cache[key] = result
        if len(cache) > 128:
            cache.popitem(last=False)
        return result

    @app.get("/")
    async def index():
        return FileResponse(ROOT / "static/index.html")

    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
    return app


def main():
    parser = argparse.ArgumentParser(description="Sport Live: loja adaptativa com Jev")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--provider", choices=["typesafe", "openrouter"])
    parser.add_argument("--fake", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8780)
    args = parser.parse_args()
    try:
        settings = Settings.load(args.env_file, args.provider)
    except ValueError as error:
        parser.exit(2, f"Erro: {error}\n")
    if args.fake:
        settings = replace(settings, fake=True)
    import uvicorn

    uvicorn.run(create_app(settings), host=args.host, port=args.port)
