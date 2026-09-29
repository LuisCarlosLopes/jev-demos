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
from pydantic import BaseModel, Field

from .config import Settings
from .decisions import build_request, parse_response, taxonomy
from .jev import JevClient, ProviderError, estimate_cost

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "static"
CACHE_SIZE = 256


class Persona(BaseModel):
    team: str | None = Field(default=None, max_length=40)
    technologies: list[str] = Field(default_factory=list, max_length=12)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=300)
    persona: Persona = Field(default_factory=Persona)


def load_catalog(path: Path) -> list[dict]:
    catalog = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(catalog, list) or not catalog:
        raise ValueError(f"Catálogo vazio ou inválido: {path}")
    # Choice aceita até 255 opções e o contexto é de 64k tokens; acima disso seria
    # preciso um pré-filtro antes do Jev.
    if len(catalog) > 250:
        raise ValueError("Catálogo com mais de 250 artefatos exige pré-filtro.")
    return catalog


def create_app(settings: Settings, catalog: list[dict], client: JevClient | None = None) -> FastAPI:
    jev = client or JevClient(settings)
    cache: OrderedDict[str, dict] = OrderedDict()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # Aquece a conexão TLS com uma decisão mínima (~60 tokens), para a primeira
        # busca da demo não pagar o handshake. Falhas aqui não impedem a subida.
        if settings.api_key and not settings.fake:
            warm = {"ping": {"type": "noul", "instructions": "Is `state` a greeting?"}}
            try:
                await jev.decide("hello", warm)
            except ProviderError:
                pass
        yield
        await jev.aclose()

    # Sem exportação automática de telemetria: a demo não envia dados a coletores externos.
    app = FastAPI(
        title="Catalog AI · Jev", lifespan=lifespan, telemetry={"auto_configure": False}
    )

    @app.get("/api/catalog")
    async def get_catalog():
        return {
            "items": catalog,
            "taxonomy": taxonomy(),
            "simulated": settings.fake,
            "model": "simulado" if settings.fake else settings.model,
            "configured": bool(settings.api_key) or settings.fake,
        }

    @app.post("/api/search")
    async def search(body: SearchRequest):
        started = time.perf_counter()
        query = " ".join(body.query.split())
        persona = body.persona.model_dump()
        key = json.dumps([query.lower(), persona], sort_keys=True, ensure_ascii=False)
        if key in cache:
            cache.move_to_end(key)
            hit = cache[key]
            server_ms = (time.perf_counter() - started) * 1000
            telemetry = {
                **hit["telemetry"],
                "cached": True,
                "jev_ms": 0,
                "first_jev_ms": hit["telemetry"]["jev_ms"],
                "server_ms": round(server_ms, 1),
                "cost_usd": 0,
            }
            return {**hit, "telemetry": telemetry}
        state, questions, keymap = build_request(query, persona, catalog)
        try:
            data, jev_ms = await jev.decide(state, questions)
            result = parse_response(data, keymap)
        except ProviderError as error:
            return JSONResponse({"error": str(error)}, status_code=502)
        server_ms = (time.perf_counter() - started) * 1000
        result["telemetry"] = {
            "cached": False,
            "questions": len(questions),
            "jev_ms": round(jev_ms, 1),
            "server_ms": round(server_ms, 1),
            "input_tokens": result["usage"].get("input_tokens"),
            "cost_usd": estimate_cost(result["usage"]),
        }
        result["simulated"] = settings.fake
        cache[key] = result
        if len(cache) > CACHE_SIZE:
            cache.popitem(last=False)
        return result

    @app.get("/")
    async def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Catálogo de artefatos de IA com Jev.")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--provider", choices=["typesafe", "openrouter"])
    parser.add_argument("--catalog", type=Path, default=ROOT / "data" / "catalog.json")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument(
        "--fake", action="store_true", help="Jev simulado (heurística local), para testar a tela."
    )
    args = parser.parse_args()
    try:
        settings = Settings.load(args.env_file, args.provider)
        if args.fake:
            settings = replace(settings, fake=True)
        catalog = load_catalog(args.catalog)
    except ValueError as error:
        parser.exit(2, f"Erro: {error}\n")
    import uvicorn

    uvicorn.run(create_app(settings, catalog), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
