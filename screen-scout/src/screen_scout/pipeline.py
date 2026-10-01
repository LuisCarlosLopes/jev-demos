"""Orquestração: captura → classificação (Jev) → sondagens → oráculo (Jev) → plano e código.

O `Engine` mantém um loop asyncio próprio numa thread, com o navegador e a conexão com o Jev
abertos entre uma exploração e outra: a segunda tela não paga a subida do Chromium nem o
handshake TLS. O mesmo pipeline roda na CLI (sem thread) e na interface web.
"""

import asyncio
import base64
import copy
import json
import sys
import threading
import time
from concurrent.futures import Future
from pathlib import Path

import httpx
from playwright.async_api import Browser, Playwright, async_playwright

from . import auth
from .capture import SETTLE_SCRIPT, cache_call_stack, capture, wait_ready
from .codegen import file_names, python_tests, typescript_tests
from .config import Settings
from .decisions import (
    classification_request,
    oracle_request,
    parse_classification,
    parse_oracle,
)
from .jev import JevClient, estimate_cost
from .plan import build_report, plan_markdown
from .probes import VIEWPORT, oracle_inputs, plan_probes, run_probes
from .profile import Thresholds, build_profile

STEPS = [
    ("browser", "Navegador"),
    ("capture", "Captura da tela"),
    ("classify", "Classificação · Jev"),
    ("probes", "Sondagens · Playwright"),
    ("oracle", "Oráculo · Jev"),
    ("generate", "Plano e testes"),
]


class Progress:
    """Estado de uma exploração, lido pela interface enquanto a thread do engine escreve."""

    def __init__(self):
        self._lock = threading.Lock()
        self.status = "running"
        self.error: str | None = None
        self.steps = {key: {"key": key, "label": label, "status": "pending", "ms": None,
                            "detail": ""} for key, label in STEPS}
        self.probes = {"total": 0, "done": 0, "items": []}
        self.result: dict | None = None
        self._started: dict[str, float] = {}

    def start(self, key: str, detail: str = "") -> None:
        with self._lock:
            self._started[key] = time.perf_counter()
            self.steps[key].update(status="running", detail=detail)

    def done(self, key: str, detail: str = "", **info) -> float:
        with self._lock:
            ms = round((time.perf_counter() - self._started.get(key, time.perf_counter()))
                       * 1000, 1)
            self.steps[key].update(status="done", ms=ms, detail=detail, **info)
            return ms

    def fail(self, message: str) -> None:
        with self._lock:
            self.status = "error"
            self.error = message
            for step in self.steps.values():
                if step["status"] == "running":
                    step["status"] = "error"

    def plan(self, probes) -> None:
        with self._lock:
            self.probes = {"total": len(probes), "done": 0,
                           "items": [{"id": p.id, "title": p.title, "kind": p.kind,
                                      "status": "pending", "ms": None} for p in probes]}

    def probe_done(self, probe) -> None:
        with self._lock:
            self.probes["done"] += 1
            for item in self.probes["items"]:
                if item["id"] == probe.id:
                    failed = "error" in (probe.observation or {})
                    item.update(status="error" if failed else "done", ms=probe.ms)

    def finish(self, result: dict) -> None:
        with self._lock:
            self.result = result
            self.status = "done"

    def snapshot(self, include_result: bool = True) -> dict:
        with self._lock:
            data = {
                "status": self.status,
                "error": self.error,
                "steps": [copy.deepcopy(self.steps[key]) for key, _ in STEPS],
                "probes": copy.deepcopy(self.probes),
            }
            if include_result and self.result is not None:
                data["result"] = self.result
            return data


class Engine:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self.transport = transport
        # Proactor no Windows: o Playwright precisa de subprocessos no loop.
        self.loop = asyncio.ProactorEventLoop() if sys.platform == "win32" else (
            asyncio.new_event_loop())
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._jev: JevClient | None = None
        self._browser_lock: asyncio.Lock | None = None

    def submit(self, coroutine) -> Future:
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop)

    def jev(self) -> JevClient:
        if self._jev is None:
            self._jev = JevClient(self.settings, self.transport)
        return self._jev

    async def browser(self) -> tuple[Browser, bool]:
        """Devolve (navegador, se precisou abrir agora)."""
        if self._browser_lock is None:
            self._browser_lock = asyncio.Lock()
        async with self._browser_lock:
            if self._browser is not None and self._browser.is_connected():
                return self._browser, False
            if self._playwright is None:
                self._playwright = await async_playwright().start()
            options: dict = {"headless": self.settings.headless}
            if self.settings.browser_channel in {"msedge", "chrome"}:
                options["channel"] = self.settings.browser_channel
            self._browser = await self._playwright.chromium.launch(**options)
            return self._browser, True

    async def warm(self) -> None:
        """Abre o navegador e a conexão com o Jev antes da primeira exploração."""
        await self.browser()
        if self.settings.api_key and not self.settings.fake:
            ping = {"ping": {"type": "noul", "instructions": "Is `state` a greeting?"}}
            try:
                await self.jev().decide("hello", ping)
            except Exception:  # noqa: BLE001 - aquecimento é opcional
                pass

    async def login(self, url: str) -> dict:
        """Janela visível para você entrar no sistema; a sessão fica salva em .auth/."""
        if self._playwright is None:
            self._playwright = await async_playwright().start()
        return await auth.login(self._playwright, url, self.settings.browser_channel)

    async def aclose(self) -> None:
        if self._jev is not None:
            await self._jev.aclose()
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()

    def close(self) -> None:
        try:
            self.submit(self.aclose()).result(timeout=10)
        except Exception:  # noqa: BLE001 - encerramento de melhor esforço
            pass
        self.loop.call_soon_threadsafe(self.loop.stop)


def _usage(decision) -> dict:
    usage = decision.data.get("usage", {}) if isinstance(decision.data, dict) else {}
    tokens = usage.get("input_tokens")
    cost = 0.0 if decision.cached else estimate_cost(usage)
    return {"tokens": tokens, "cost": cost, "cached": decision.cached,
            "questions": decision.questions, "requests": decision.requests,
            "jev_ms": round(decision.ms, 1)}


def _asked(decision) -> str:
    where = ("numa requisição" if decision.requests == 1
             else f"em {decision.requests} requisições paralelas")
    return f"{decision.questions} decisões {where}"


def _money(value: float) -> str:
    return f"US$ {value:.5f}".replace(".", ",")


async def explore(engine: Engine, url: str, allow_submit: bool, progress: Progress,
                  thresholds: Thresholds | None = None, out_dir: Path | None = None) -> dict:
    started = time.perf_counter()
    cache_call_stack()
    settings = engine.settings
    progress.start("browser")
    browser, launched = await engine.browser()
    progress.done("browser", "aberto agora" if launched else "já aberto (aquecido)")

    progress.start("capture", url)
    session = auth.storage_state_for(url)
    context = await browser.new_context(locale="pt-BR", viewport=VIEWPORT,
                                        storage_state=session)
    context.set_default_timeout(15000)
    try:
        await context.add_init_script(SETTLE_SCRIPT)
        page = await context.new_page()
        response = await page.goto(url, wait_until="load")
        if response is not None and response.status >= 400:
            raise RuntimeError(f"A tela respondeu HTTP {response.status}.")
        ready = await wait_ready(page)
        # Nunca explora outro sistema: um redirecionamento para outro host é quase sempre o
        # login (SSO), e digitar lá, mesmo massa sintética, não é papel do explorador.
        if other := auth.redirected_to(url, page.url):
            hint = ("A sessão salva expirou: entre de novo." if session
                    else "Faça login com “Entrar…” (interface) ou --login (linha de comando) "
                    "para salvar a sessão.")
            raise RuntimeError(f"A tela redirecionou para {other}, provavelmente o login. {hint}")
        screen = await capture(page)
    finally:
        await context.close()
    detail = f"{len(screen.fields)} campos · {len(screen.actions)} ações"
    if session:
        detail += " · com sessão"
    if not ready:
        detail += " · tela não estabilizou em 15 s"
    progress.done("capture", detail, elements=len(screen.elements))

    jev = engine.jev()
    progress.start("classify")
    state, questions = classification_request(screen)
    decision = await jev.decide(state, questions)
    classification = parse_classification(decision.data, questions)
    profile = build_profile(screen, classification, thresholds)
    classify_usage = _usage(decision)
    progress.done("classify", _asked(decision), **classify_usage)

    probes = plan_probes(profile, allow_submit)
    progress.plan(probes)
    progress.start("probes", f"{len(probes)} sondagens · {settings.concurrency} em paralelo")
    await run_probes(browser, url, profile, probes, settings.concurrency, progress.probe_done,
                     storage_state=session)
    failed = sum(1 for p in probes if "error" in (p.observation or {}))
    detail = f"{len(probes)} sondagens" + (f" · {failed} falharam" if failed else "")
    progress.done("probes", detail, count=len(probes), failed=failed)

    oracle = None
    oracle_usage = None
    items = oracle_inputs(profile, probes)
    progress.start("oracle")
    if items:
        state, questions = oracle_request(screen, items)
        decision = await jev.decide(state, questions)
        oracle = parse_oracle(decision.data, questions, screen)
        oracle_usage = _usage(decision)
        progress.done("oracle", _asked(decision), **oracle_usage)
    else:
        progress.done("oracle", "nada a julgar (envio desligado)", questions=0, tokens=0, cost=0)

    progress.start("generate")
    usages = [u for u in (classify_usage, oracle_usage) if u]
    cost = sum(u["cost"] or 0 for u in usages)
    tokens = sum(u["tokens"] or 0 for u in usages)
    decisions = sum(u["questions"] for u in usages)
    total_s = round(time.perf_counter() - started, 1)
    meta = {
        "probes": len(probes),
        "total_s": str(total_s).replace(".", ","),
        "jev_requests": sum(u["requests"] for u in usages),
        "decisions": decisions,
        "tokens": tokens,
        "cost": cost,
        "cost_label": ("custo zero (cache)" if usages and all(u["cached"] for u in usages)
                       else _money(cost)),
        "model": "simulado" if settings.fake else classification["model"],
        "simulated": settings.fake,
        "concurrency": settings.concurrency,
        "browser": settings.browser_channel or "chromium",
        "session": bool(session),
        # Referência: o snapshot ARIA é o que um agente LLM relê a cada passo da exploração.
        "aria_tokens": round(screen.aria_chars / 4),
    }
    report = build_report(profile, probes, oracle, allow_submit, meta)
    code_py, test_map = python_tests(report)
    code_ts = typescript_tests(report)
    markdown = plan_markdown(report)
    names = file_names(report)
    report["files"] = {
        "python": {"name": names["python"], "content": code_py, "tests": test_map},
        "typescript": {"name": names["typescript"], "content": code_ts},
        "plan": {"name": names["plan"], "content": markdown},
    }
    if screen.screenshot:
        report["screen"]["screenshot"] = "data:image/jpeg;base64," + base64.b64encode(
            screen.screenshot).decode()
    progress.done("generate", f"{sum(1 for c in report['cases'] if c['automated'])} testes · "
                  f"{len(report['cases'])} cenários")
    report["meta"]["timings"] = progress.snapshot(include_result=False)["steps"]
    report["meta"]["total_ms"] = round((time.perf_counter() - started) * 1000, 1)
    if out_dir is not None:
        save(report, out_dir, screen.screenshot)
    return report


def save(report: dict, out_dir: Path, screenshot: bytes | None = None) -> Path:
    folder = out_dir / report["slug"]
    folder.mkdir(parents=True, exist_ok=True)
    for item in report["files"].values():
        (folder / item["name"]).write_text(item["content"], encoding="utf-8")
    slim = {k: v for k, v in report.items() if k != "files"}
    slim["screen"] = {k: v for k, v in report["screen"].items() if k != "screenshot"}
    (folder / "exploracao.json").write_text(
        json.dumps(slim, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if screenshot:
        (folder / "tela.jpg").write_bytes(screenshot)
    return folder
