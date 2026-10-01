import argparse
import asyncio
import ipaddress
import re
import uuid
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import auth
from .config import Settings
from .pipeline import Engine, Progress, explore, save
from .profile import Thresholds
from .runner import run_tests
from .sample import router as sample_router

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "static"
GENERATED = ROOT / "generated"
MAX_JOBS = 20


class SessionRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2000)


class ExploreRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2000)
    # Sondagens que salvam o formulário. Padrão: só em endereços locais.
    allow_submit: bool | None = None
    confidence: float = Field(default=0.60, ge=0, le=1)
    risk: float = Field(default=0.35, ge=0, le=1)


def is_local(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".test"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def create_app(settings: Settings, engine: Engine | None = None,
               port: int = 8785) -> FastAPI:
    if engine is None:
        transport = None
        if settings.fake:
            from .fake import fake_handler

            transport = httpx.MockTransport(fake_handler)
        engine = Engine(settings, transport)
    jobs: OrderedDict[str, dict] = OrderedDict()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # Aquece navegador e conexão com o Jev sem segurar a subida do servidor.
        engine.submit(engine.warm())
        yield
        await asyncio.to_thread(engine.close)

    # Sem exportação automática de telemetria: o demo não envia dados a coletores externos.
    app = FastAPI(title="Screen Scout · Jev + Playwright", lifespan=lifespan,
                  telemetry={"auto_configure": False})
    app.include_router(sample_router)

    @app.middleware("http")
    async def no_cache(request, call_next):
        response = await call_next(request)
        if not request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/api/config")
    async def config():
        return {
            "simulated": settings.fake,
            "model": "simulado" if settings.fake else settings.model,
            "configured": bool(settings.api_key) or settings.fake,
            "sample_url": f"http://127.0.0.1:{port}/alvo/colaborador",
            "concurrency": settings.concurrency,
            "browser": settings.browser_channel or "chromium",
        }

    @app.post("/api/explore")
    async def start(body: ExploreRequest):
        url = body.url.strip()
        if not re.match(r"^https?://", url):
            raise HTTPException(422, "Informe um endereço http:// ou https://.")
        if not (settings.api_key or settings.fake):
            raise HTTPException(
                400, f"Preencha {settings.provider.upper()}_API_KEY no .env ou use --fake."
            )
        allow_submit = is_local(url) if body.allow_submit is None else body.allow_submit
        job_id = uuid.uuid4().hex[:10]
        progress = Progress()
        thresholds = Thresholds(confidence=body.confidence, risk=body.risk)

        async def job():
            try:
                result = await explore(engine, url, allow_submit, progress, thresholds)
                progress.finish(result)
            except Exception as error:  # noqa: BLE001 - a interface mostra a mensagem
                progress.fail(str(error).splitlines()[0][:300] or type(error).__name__)

        jobs[job_id] = {"progress": progress, "url": url}
        while len(jobs) > MAX_JOBS:
            jobs.popitem(last=False)
        engine.submit(job())
        return {"id": job_id, "allow_submit": allow_submit}

    def _checked(url: str) -> str:
        url = url.strip()
        if not re.match(r"^https?://", url):
            raise HTTPException(422, "Informe um endereço http:// ou https://.")
        return url

    @app.get("/api/session")
    async def session(url: str):
        return auth.session_info(_checked(url))

    @app.post("/api/session/login")
    async def login(body: SessionRequest):
        # Abre uma janela visível nesta máquina; quem digita a senha é a pessoa, não o demo.
        url = _checked(body.url)
        try:
            return await asyncio.wrap_future(engine.submit(engine.login(url)))
        except Exception as error:  # noqa: BLE001 - a interface mostra a mensagem
            raise HTTPException(400, str(error).splitlines()[0][:300]) from None

    @app.delete("/api/session")
    async def logout(url: str):
        return {"removed": auth.forget(_checked(url)), **auth.session_info(url)}

    def _job(job_id: str) -> dict:
        if job_id not in jobs:
            raise HTTPException(404, "Exploração não encontrada.")
        return jobs[job_id]

    @app.get("/api/jobs/{job_id}")
    async def status(job_id: str, full: bool = False):
        return _job(job_id)["progress"].snapshot(include_result=full)

    def _result(job_id: str) -> dict:
        result = _job(job_id)["progress"].result
        if result is None:
            raise HTTPException(409, "A exploração ainda não terminou.")
        return result

    @app.get("/api/jobs/{job_id}/files/{kind}")
    async def download(job_id: str, kind: str):
        files = _result(job_id)["files"]
        if kind not in files:
            raise HTTPException(404, "Arquivo desconhecido.")
        item = files[kind]
        return PlainTextResponse(
            item["content"],
            headers={"Content-Disposition": f'attachment; filename="{item["name"]}"'},
        )

    @app.post("/api/jobs/{job_id}/run")
    async def run(job_id: str):
        result = _result(job_id)
        folder = save(result, GENERATED / job_id)
        test_file = folder / result["files"]["python"]["name"]
        url = result["screen"]["url"]
        outcome = await asyncio.to_thread(run_tests, test_file, settings, url, 300,
                                          auth.storage_state_for(url))
        mapping = result["files"]["python"]["tests"]
        for test in outcome.get("tests", []):
            test["case"] = mapping.get(test["name"])
        outcome["folder"] = str(folder.relative_to(ROOT))
        return JSONResponse(outcome)

    @app.get("/")
    async def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Explora uma tela com Playwright, decide com o Jev e gera plano e testes."
    )
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--provider", choices=["typesafe", "openrouter"])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8785)
    parser.add_argument("--fake", action="store_true",
                        help="Jev simulado (heurística local), para testar a tela sem chave.")
    parser.add_argument("--headed", action="store_true", help="Mostra o navegador.")
    parser.add_argument("--channel", choices=["chromium", "msedge", "chrome"],
                        help="Navegador: Chromium do Playwright ou o Edge/Chrome instalado.")
    args = parser.parse_args()
    try:
        settings = Settings.load(args.env_file, args.provider)
    except ValueError as error:
        parser.exit(2, f"Erro: {error}\n")
    if args.fake:
        settings = replace(settings, fake=True)
    if args.headed:
        settings = replace(settings, headless=False)
    if args.channel:
        settings = replace(settings, browser_channel="" if args.channel == "chromium"
                           else args.channel)
    import uvicorn

    uvicorn.run(create_app(settings, port=args.port), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
