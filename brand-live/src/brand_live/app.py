import argparse
import json
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import Settings
from .decisions import build_request, catalog, parse_response
from .jev import JevClient, ProviderError, estimate_cost

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "static"
CACHE_SIZE = 256


class Brand(BaseModel):
    vertical: str = Field(max_length=40)
    background: str = Field(max_length=40)
    primary: str = Field(max_length=40)
    text: str = Field(max_length=40)
    accent: str = Field(max_length=40)
    font: str = Field(max_length=40)
    layout: str = Field(max_length=40)
    tone: float = Field(ge=0, le=4)
    sections: list[str] = Field(default_factory=list, max_length=8)


class CommandRequest(BaseModel):
    utterance: str = Field(min_length=1, max_length=400)
    # Transcrição intermediária da voz: a frase ainda pode mudar.
    partial: bool = False
    brand: Brand
    recent: list[str] = Field(default_factory=list, max_length=5)


def create_app(settings: Settings, client: JevClient | None = None) -> FastAPI:
    if client is None:
        transport = None
        if settings.fake:
            from .fake import fake_handler

            transport = httpx.MockTransport(fake_handler)
        client = JevClient(settings, transport)
    jev = client
    cache: OrderedDict[str, dict] = OrderedDict()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # Aquece a conexão TLS com uma decisão mínima, para a primeira frase da demo
        # não pagar o handshake. Falhas aqui não impedem a subida.
        if settings.api_key and not settings.fake:
            warm = {"ping": {"type": "noul", "instructions": "Is `state` a greeting?"}}
            try:
                await jev.decide("hello", warm)
            except ProviderError:
                pass
        yield
        await jev.aclose()

    # Sem exportação automática de telemetria: a demo não envia dados a coletores externos.
    app = FastAPI(title="Brand Live · Jev", lifespan=lifespan, telemetry={"auto_configure": False})

    @app.middleware("http")
    async def no_cache(request, call_next):
        # A demo é editada ao vivo: o navegador sempre revalida HTML, CSS e JS.
        response = await call_next(request)
        if not request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/api/catalog")
    async def get_catalog():
        return {
            **catalog(),
            "simulated": settings.fake,
            "model": "simulado" if settings.fake else settings.model,
            "configured": bool(settings.api_key) or settings.fake,
        }

    @app.post("/api/command")
    async def command(body: CommandRequest):
        started = time.perf_counter()
        utterance = " ".join(body.utterance.split())
        brand = body.brand.model_dump()
        # A voz repete a mesma parcial várias vezes; o cache evita pagar duas vezes.
        key = json.dumps([utterance.lower(), brand], sort_keys=True, ensure_ascii=False)
        if key in cache:
            cache.move_to_end(key)
            hit = cache[key]
            telemetry = {
                **hit["telemetry"],
                "cached": True,
                "jev_ms": 0,
                "first_jev_ms": hit["telemetry"]["jev_ms"],
                "server_ms": round((time.perf_counter() - started) * 1000, 1),
                "cost_usd": 0,
            }
            return {**hit, "telemetry": telemetry, "partial": body.partial}
        state, questions = build_request(utterance, brand, body.recent)
        try:
            data, jev_ms = await jev.decide(state, questions)
            result = parse_response(data)
        except ProviderError as error:
            return JSONResponse({"error": str(error)}, status_code=502)
        result["utterance"] = utterance
        result["telemetry"] = {
            "cached": False,
            "questions": len(questions),
            "jev_ms": round(jev_ms, 1),
            "server_ms": round((time.perf_counter() - started) * 1000, 1),
            "input_tokens": result["usage"].get("input_tokens"),
            "cost_usd": estimate_cost(result["usage"]),
        }
        result["simulated"] = settings.fake
        cache[key] = result
        if len(cache) > CACHE_SIZE:
            cache.popitem(last=False)
        return {**result, "partial": body.partial}

    @app.get("/")
    async def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Brand que reage à voz com decisões do Jev.")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--provider", choices=["typesafe", "openrouter"])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8775)
    parser.add_argument(
        "--fake", action="store_true", help="Jev simulado (heurística local), para testar a tela."
    )
    args = parser.parse_args()
    try:
        settings = Settings.load(args.env_file, args.provider)
        if args.fake:
            settings = replace(settings, fake=True)
    except ValueError as error:
        parser.exit(2, f"Erro: {error}\n")
    import uvicorn

    uvicorn.run(create_app(settings), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
