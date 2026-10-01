from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from screen_scout.app import create_app, is_local
from screen_scout.config import Settings


class IdleEngine:
    """Engine que não abre navegador: os testes de rota não exploram nada."""

    settings = None

    def submit(self, coroutine):
        coroutine.close()

    async def warm(self):
        pass

    def close(self):
        pass


@pytest.fixture
def client():
    settings = Settings("typesafe", "", "jev-latest", 10, fake=True)
    engine = IdleEngine()
    engine.settings = settings
    with TestClient(create_app(settings, engine=engine)) as test_client:
        yield test_client


def test_config_reports_simulated_mode(client):
    data = client.get("/api/config").json()
    assert data["simulated"] is True and data["configured"] is True
    assert data["sample_url"].endswith("/alvo/colaborador")


def test_explore_validates_url(client):
    assert client.post("/api/explore", json={"url": "ftp://x"}).status_code == 422
    response = client.post("/api/explore", json={"url": "http://127.0.0.1:1/x"})
    assert response.status_code == 200
    assert response.json()["allow_submit"] is True
    external = client.post("/api/explore", json={"url": "https://example.com/form"})
    assert external.json()["allow_submit"] is False


def test_unknown_job(client):
    assert client.get("/api/jobs/nope").status_code == 404


def test_sample_screen_and_api(client):
    page = client.get("/alvo/colaborador")
    assert page.status_code == 200 and "Novo colaborador" in page.text
    saved = client.post("/alvo/api/colaboradores", json={"nome": "Maria Souza"})
    assert saved.status_code == 201 and saved.json()["matricula"].isdigit()
    assert "Maria Souza" in client.get("/alvo/colaboradores").text


def test_is_local():
    assert is_local("http://localhost:4200/x") and is_local("http://127.0.0.1/x")
    assert is_local("http://app.test/x") and not is_local("https://example.com")


def test_settings_reject_bad_values(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("SCOUT_CONCURRENCY=99\n")
    with pytest.raises(ValueError):
        Settings.load(env)
