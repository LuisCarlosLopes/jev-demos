"""Ponta a ponta com navegador real e Jev simulado, contra a tela-alvo embutida (~10 s)."""

import ast

import httpx
import pytest

from screen_scout.cli import serve_sample
from screen_scout.config import Settings
from screen_scout.fake import fake_handler
from screen_scout.pipeline import Engine, Progress, explore


@pytest.fixture(scope="module")
def sample_url():
    url, server = serve_sample()
    yield url
    server.should_exit = True


def test_exploration_finds_the_planted_defects(sample_url, tmp_path):
    settings = Settings("typesafe", "", "jev-latest", 10, fake=True, concurrency=6)
    engine = Engine(settings, httpx.MockTransport(fake_handler))
    progress = Progress()
    try:
        report = engine.submit(explore(engine, sample_url, True, progress, out_dir=tmp_path)
                               ).result(timeout=180)
    except Exception as error:  # noqa: BLE001
        if "Executable doesn't exist" in str(error):
            pytest.skip("Chromium do Playwright não instalado (uv run playwright install chromium)")
        raise
    finally:
        engine.close()
    divergences = {d["title"] for d in report["findings"]["divergences"]}
    assert divergences == {
        "Recusar CPF com dígito verificador inválido",
        "Recusar CPF com todos os dígitos iguais",
        "Recusar salário base (R$) negativo",
    }
    assert not report["findings"]["uncertain"]
    assert all("error" not in (r["observation"] or {}) for r in report["results"])
    risky = {a["label"] for a in report["profile"]["actions"] if a["risky"]}
    assert risky == {"Sair", "Enviar para aprovação", "Excluir rascunho"}
    ast.parse(report["files"]["python"]["content"])
    folder = tmp_path / report["slug"]
    assert {p.name for p in folder.iterdir()} >= {
        "plano.md", "test_novo_colaborador.py", "novo-colaborador.spec.ts", "exploracao.json",
    }
    assert progress.snapshot()["status"] == "running"  # quem marca "done" é o chamador
