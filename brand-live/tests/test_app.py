import json

import httpx
import pytest
from fastapi.testclient import TestClient

from brand_live.app import create_app
from brand_live.jev import JevClient


def client_with(settings, handler):
    jev = JevClient(settings, httpx.MockTransport(handler))
    return TestClient(create_app(settings, jev))


def test_catalog_endpoint(fake_settings):
    with TestClient(create_app(fake_settings)) as client:
        data = client.get("/api/catalog").json()
    assert data["simulated"] is True and data["configured"] is True
    assert "saas_b2b" in data["verticals"] and "red" in data["colors"]


def test_command_returns_decisions_and_telemetry(settings, brand, jev_response):
    seen = {}

    def handler(request):
        seen["payload"] = json.loads(request.content)
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(200, json=jev_response)

    with client_with(settings, handler) as client:
        body = {"utterance": "  fundo   vermelho ", "partial": True, "brand": brand,
                "recent": ["oi"]}
        first = client.post("/api/command", json=body).json()
        second = client.post("/api/command", json=body).json()
    assert seen["payload"]["state"]["utterance"] == "fundo vermelho"
    assert seen["payload"]["state"]["recent_utterances"] == ["oi"]
    assert first["partial"] is True
    assert first["decisions"]["color"]["value"] == "red"
    assert first["telemetry"]["questions"] == 10
    assert first["telemetry"]["cost_usd"] == pytest.approx(1500 * 0.042 / 1_000_000)
    assert second["telemetry"]["cached"] is True and second["telemetry"]["cost_usd"] == 0


def test_provider_failure_is_a_safe_502(settings, brand):
    def handler(_):
        return httpx.Response(500, json={"secret": "do not leak"})

    with client_with(settings, handler) as client:
        response = client.post("/api/command", json={"utterance": "x", "brand": brand})
    assert response.status_code == 502
    assert "leak" not in response.text and "500" in response.json()["error"]


def test_invalid_brand_is_rejected(fake_settings):
    with TestClient(create_app(fake_settings)) as client:
        response = client.post("/api/command", json={"utterance": "x", "brand": {"tone": 9}})
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("utterance", "intent", "facet", "value"),
    [
        ("fundo vermelho", "change_color", "color", "red"),
        ("quero vender café", "change_vertical", "vertical", "coffee"),
        ("deixa mais leve", "change_tone", None, None),
        ("tira o e-mail", "hide_section", "section", "email"),
        ("volta", "undo", None, None),
        ("quero vender foguetes", "change_vertical", "vertical", "not_in_catalog"),
        ("hmm deixa eu ver", "none", None, None),
    ],
)
def test_fake_mode_covers_the_demo_script(fake_settings, brand, utterance, intent, facet, value):
    with TestClient(create_app(fake_settings)) as client:
        data = client.post("/api/command", json={"utterance": utterance, "brand": brand}).json()
    d = data["decisions"]
    assert data["simulated"] is True
    assert d["intent"]["value"] == intent
    if facet:
        assert d[facet]["value"] == value
    if intent == "change_tone":
        assert d["tone"]["value"] > brand["tone"]
    if intent == "none":
        assert d["is_command"] < 0.5
