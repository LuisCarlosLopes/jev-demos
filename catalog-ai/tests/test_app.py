import json

import httpx
from fastapi.testclient import TestClient

from catalog_ai.app import create_app
from catalog_ai.config import Settings
from catalog_ai.jev import JevClient


def client_for(settings, catalog, handler):
    jev = JevClient(settings, httpx.MockTransport(handler))
    return TestClient(create_app(settings, catalog, jev))


def test_search_sends_one_request_and_reports_telemetry(settings, catalog, jev_response):
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        assert request.headers["Authorization"] == "Bearer test-key"
        if "ping" in calls[-1]["questions"]:
            return httpx.Response(200, json={"model": "jev", "answers": {}})
        return httpx.Response(200, json=jev_response)

    with client_for(settings, catalog, handler) as client:
        response = client.post("/api/search", json={"query": "  code   review "})
        assert response.status_code == 200
        body = response.json()
        searches = [c for c in calls if "ping" not in c["questions"]]
        assert len(searches) == 1
        assert searches[0]["state"]["request"] == "code review"
        assert body["relevance"] == {"a": 0.91, "b": 0.07}
        telemetry = body["telemetry"]
        assert telemetry["questions"] == 7
        assert telemetry["cached"] is False
        assert telemetry["input_tokens"] == 1200
        assert abs(telemetry["cost_usd"] - 1200 * 0.042 / 1e6) < 1e-12

        again = client.post("/api/search", json={"query": "Code Review"}).json()
        assert again["telemetry"]["cached"] is True
        assert again["telemetry"]["cost_usd"] == 0
        assert again["telemetry"]["first_jev_ms"] == telemetry["jev_ms"]
        assert len([c for c in calls if "ping" not in c["questions"]]) == 1


def test_provider_errors_do_not_leak_remote_body(settings, catalog):
    def handler(request):
        return httpx.Response(401, text="segredo-remoto")

    with client_for(settings, catalog, handler) as client:
        response = client.post("/api/search", json={"query": "code review"})
    assert response.status_code == 502
    assert "401" in response.json()["error"]
    assert "segredo" not in response.text


def test_missing_key_is_reported(catalog):
    settings = Settings("typesafe", "", "jev-latest", 5)
    with client_for(settings, catalog, lambda r: httpx.Response(500)) as client:
        response = client.post("/api/search", json={"query": "code review"})
        assert response.status_code == 502
        assert "TYPESAFE_API_KEY" in response.json()["error"]
        assert client.get("/api/catalog").json()["configured"] is False


def test_fake_mode_answers_every_artifact(catalog):
    settings = Settings("typesafe", "", "jev-latest", 5, fake=True)
    with TestClient(create_app(settings, catalog)) as client:
        body = client.post("/api/search", json={"query": "review pull requests"}).json()
        assert body["simulated"] is True
        assert body["relevance"]["a"] > body["relevance"]["b"]
        assert client.get("/api/catalog").json()["simulated"] is True


def test_rejects_oversized_query(settings, catalog):
    with client_for(settings, catalog, lambda r: httpx.Response(500)) as client:
        assert client.post("/api/search", json={"query": "x" * 301}).status_code == 422
