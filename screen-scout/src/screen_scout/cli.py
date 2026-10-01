"""CLI: explora uma tela e grava plano e testes em disco, sem interface web.

    uv run screen-scout-cli exemplo --run
    uv run screen-scout-cli http://localhost:4200/cadastro --no-submit

`exemplo` sobe a tela-alvo embutida numa porta livre, só durante a execução.
"""

import argparse
import json
import socket
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

import httpx

from . import auth
from .app import GENERATED, ROOT, is_local
from .config import Settings
from .pipeline import Engine, Progress, explore
from .profile import Thresholds
from .runner import run_tests


def serve_sample() -> tuple[str, object]:
    import uvicorn
    from fastapi import FastAPI

    from .sample import router

    app = FastAPI()
    app.include_router(router)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    return f"http://127.0.0.1:{port}/alvo/colaborador", server


def _line(label: str, value: str) -> None:
    print(f"  {label:<24} {value}")


def main() -> None:
    # Saída redirecionada no Windows usa cp1252 e quebra nos símbolos do resumo.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Explora uma tela e gera plano e testes.")
    parser.add_argument("url", help="Endereço da tela, ou 'exemplo' / 'exemplo-abas' para as "
                        "telas embutidas.")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--provider", choices=["typesafe", "openrouter"])
    parser.add_argument("--fake", action="store_true", help="Jev simulado (heurística local).")
    parser.add_argument("--no-submit", action="store_true",
                        help="Não salva o formulário (padrão fora de endereços locais).")
    parser.add_argument("--submit", action="store_true",
                        help="Permite salvar o formulário mesmo num endereço não local.")
    parser.add_argument("--out", type=Path, default=GENERATED)
    parser.add_argument("--run", action="store_true", help="Roda os testes Python gerados.")
    parser.add_argument("--json", action="store_true", help="Imprime o relatório em JSON.")
    parser.add_argument("--login", action="store_true",
                        help="Abre uma janela para você entrar no sistema e salva a sessão.")
    parser.add_argument("--confidence", type=float, default=0.60)
    parser.add_argument("--risk", type=float, default=0.35)
    args = parser.parse_args()
    try:
        settings = Settings.load(args.env_file, args.provider)
    except ValueError as error:
        parser.exit(2, f"Erro: {error}\n")
    if args.fake:
        settings = replace(settings, fake=True)
    if not (settings.api_key or settings.fake):
        parser.exit(2, f"Erro: preencha {settings.provider.upper()}_API_KEY no .env ou use "
                       "--fake.\n")
    server = None
    url = args.url
    if url in {"exemplo", "exemplo-abas"}:
        url, server = serve_sample()
        if args.url == "exemplo-abas":
            url = url.replace("/alvo/colaborador", "/alvo/fornecedor")
    allow_submit = (is_local(url) or args.submit) and not args.no_submit
    transport = None
    if settings.fake:
        from .fake import fake_handler

        transport = httpx.MockTransport(fake_handler)
    engine = Engine(settings, transport)
    if args.login:
        print("Uma janela do navegador vai abrir: faça o login nela. A sessão é salva quando a "
              "tela pedida carregar (até 5 min).")
        try:
            info = engine.submit(engine.login(url)).result(timeout=330)
        except Exception as error:  # noqa: BLE001
            engine.close()
            parser.exit(1, f"Erro: {str(error).splitlines()[0] if str(error) else error}\n")
        print(f"Sessão salva para {info['host']} ({info['cookies']} cookies).")
    progress = Progress()
    try:
        report = engine.submit(
            explore(engine, url, allow_submit, progress,
                    Thresholds(confidence=args.confidence, risk=args.risk), args.out)
        ).result(timeout=300)
    except Exception as error:  # noqa: BLE001
        engine.close()
        parser.exit(1, f"Erro: {str(error).splitlines()[0] if str(error) else error}\n")
    folder = args.out / report["slug"]
    test_file = folder / report["files"]["python"]["name"]
    session = auth.storage_state_for(url)
    outcome = run_tests(test_file, settings, url, storage_state=session) if args.run else None
    engine.close()
    if server is not None:
        server.should_exit = True
    if args.json:
        slim = {k: v for k, v in report.items() if k != "files"}
        slim["screen"] = {k: v for k, v in report["screen"].items() if k != "screenshot"}
        slim["tests_run"] = outcome
        json.dump(slim, sys.stdout, ensure_ascii=False, indent=2)
        print()
        return
    meta = report["meta"]
    print(f"\n{report['screen']['name']}  ·  {url}")
    if meta["simulated"]:
        print("  (Jev simulado: probabilidades e tempos não representam o modelo)")
    for step in meta["timings"]:
        ms = "—" if step["ms"] is None else f"{step['ms']:>7.0f} ms"
        _line(step["label"], f"{ms}  {step['detail']}")
    _line("Total", f"{meta['total_ms']:>7.0f} ms")
    requests = meta["jev_requests"]
    _line("Jev", f"{requests} {'requisição' if requests == 1 else 'requisições'} · "
                 f"{meta['decisions']} decisões · {meta['tokens']} tokens · {meta['cost_label']}")
    found = report["findings"]
    automated = sum(1 for c in report["cases"] if c["automated"])
    _line("Plano", f"{len(report['cases'])} cenários · {automated} automatizados")
    for item in found["divergences"]:
        print(f"  ❌ {item['number']} {item['title']}: {item['summary']}")
    for item in found["uncertain"]:
        print(f"  ⚠️  {item['number']} {item['title']}: {item['summary']}")
    for item in found["accessibility"]:
        print(f"  ♿ {item}")
    print(f"\n  Arquivos em {folder}")
    if outcome:
        s = outcome.get("summary", {})
        print(f"  Testes: {s.get('passed', 0)} passaram · {s.get('failed', 0)} falharam · "
              f"{s.get('skipped', 0)} pulados · {outcome.get('ms', 0) / 1000:.1f} s")
        for test in outcome.get("tests", []):
            if test["status"] in {"failed", "error"}:
                print(f"    ✗ {test['name']}: {test['message'][:140]}")


if __name__ == "__main__":
    main()
