import json
from copy import deepcopy

import httpx
import pytest
from fastapi.testclient import TestClient

from sport_live.app import ROOT, create_app
from sport_live.config import Settings
from sport_live.decisions import parse_response
from sport_live.fake import fake_response
from sport_live.jev import JevClient, ProviderError

CATALOG = json.loads((ROOT / "data/products.json").read_text())


def decide(messages):
    return parse_response(fake_response(messages, CATALOG), CATALOG)


def test_chile_does_not_assume_snow():
    result = decide(["Quero viajar para o Chile"])
    assert result["facets"]["scene"]["value"] == "travel"
    assert result["facets"]["followup"]["value"] == "season"
    assert result["relevance"]["p01"] < 0.55
    assert result["relevance"]["p04"] > 0.55


def test_refinements_and_owned_products():
    result = decide(["Quero viajar para o Chile", "Vou no inverno", "Já tenho bota"])
    assert result["relevance"]["p01"] > 0.55
    assert result["relevance"]["p03"] < 0.55
    assert decide(["Quero fazer trilha", "Já tenho mochila"])["relevance"]["p04"] < 0.55


@pytest.mark.parametrize(
    ("surface", "wanted", "rejected"),
    [
        ("society", "p09", "p10"),
        ("campo", "p10", "p11"),
        ("futsal", "p11", "p09"),
    ],
)
def test_football_surface(surface, wanted, rejected):
    result = decide(["Quero jogar futebol", f"Vou jogar {surface}"])
    assert result["relevance"][wanted] > 0.55
    assert result["relevance"][rejected] < 0.55


@pytest.mark.parametrize("bad", [True, float("nan"), -1, 1.1, "0.9"])
def test_reject_invalid_probability(bad):
    data = deepcopy(fake_response(["Quero correr"], CATALOG))
    data["answers"]["p01"]["noul"] = bad
    with pytest.raises(ProviderError):
        parse_response(data, CATALOG)


def test_http_contract_cache_and_validation():
    def handler(request):
        payload = json.loads(request.content)
        assert request.headers["Authorization"] == "Bearer test-secret"
        assert len(payload["questions"]) == len(CATALOG) + 2
        assert payload["state"]["shopper_messages"] == ["Quero jogar futebol"]
        return httpx.Response(200, json=fake_response(["Quero jogar futebol"], CATALOG))

    settings = Settings("typesafe", "test-secret", "jev-latest", 10)
    jev = JevClient(settings, transport=httpx.MockTransport(handler))
    with TestClient(create_app(settings, jev)) as client:
        response = client.post("/api/adapt", json={"messages": ["Quero jogar futebol"]})
        assert response.status_code == 200
        assert "test-secret" not in response.text
        cached = client.post("/api/adapt", json={"messages": ["Quero jogar futebol"]}).json()
        assert cached["telemetry"]["cached"] is True
        assert cached["telemetry"]["cost_usd"] == 0
        assert client.post("/api/adapt", json={"messages": [" "]}).status_code == 422
        assert client.post("/api/adapt", json={"messages": ["x" * 401]}).status_code == 422
        assert client.get("/static/app.js").status_code == 200


def test_expanded_catalog():
    assert len(CATALOG) == 60
    assert len({p["id"] for p in CATALOG}) == 60
    for product in CATALOG:
        assert (ROOT / product["image"].lstrip("/")).is_file()
    gym = decide(["Quero montar uma academia em casa"])
    assert gym["facets"]["scene"]["value"] == "gym"
    assert gym["relevance"]["p25"] > 0.55
    assert gym["relevance"]["p37"] < 0.55
    running = decide(["Quero treinar para uma maratona"])
    assert running["facets"]["scene"]["value"] == "running"
    assert running["relevance"]["p52"] > 0.55


def test_combat_refinement():
    combat = decide(["Quero começar a treinar luta"])
    assert combat["facets"]["followup"]["value"] == "discipline"
    boxing = decide(["Quero começar a treinar luta", "Quero treinar boxe"])
    assert boxing["relevance"]["p37"] > 0.55
    assert boxing["relevance"]["p43"] < 0.55
    muay = decide(["Quero treinar muay thai"])
    assert muay["relevance"]["p37"] > 0.55
    assert muay["relevance"]["p41"] > 0.55


def test_consumption_counts_cache_and_provider_usage():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 2:
            return httpx.Response(503)
        data = fake_response(["Quero jogar futebol"], CATALOG)
        data["usage"] = {"input_tokens": 1234, "output_tokens": 15, "cost": 0.0001}
        return httpx.Response(200, json=data)

    settings = Settings("openrouter", "test-secret", "test-model", 10)
    jev = JevClient(settings, transport=httpx.MockTransport(handler))
    with TestClient(create_app(settings, jev)) as client:
        assert client.get("/api/consumption").json()["requests"] == 0
        for query in ["Quero jogar futebol", "Quero jogar futebol", "Quero correr"]:
            assert client.post("/api/adapt", json={"messages": [query]}).status_code == 200
        usage = client.get("/api/consumption").json()
        assert usage["requests"] == 3
        assert usage["cache_hits"] == 1
        assert usage["provider_requests"] == 3  # Two decisions plus a retry.
        assert usage["input_tokens"] == 2468
        assert usage["output_tokens"] == 30
        assert usage["cost_usd"] == 0.0002
        assert usage["cost_reports"] == 2
        assert "test-secret" not in str(usage)
        client.post("/api/adapt", json={"messages": [" "]})
        assert client.get("/api/consumption").json()["requests"] == 3


def test_consumption_missing_usage_is_not_invented():
    settings = Settings("openrouter", "test", "test-model", 10)
    jev = JevClient(
        settings,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=fake_response(["Quero correr"], CATALOG))
        ),
    )
    with TestClient(create_app(settings, jev)) as client:
        client.post("/api/adapt", json={"messages": ["Quero correr"]})
        usage = client.get("/api/consumption").json()
        assert usage["provider_requests"] == 1
        assert usage["usage_reports"] == 0
        assert usage["cost_reports"] == 0
