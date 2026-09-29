import json

import httpx
import pytest

from skill_validator.config import Settings
from skill_validator.providers import JevProvider, ProviderError
from skill_validator.validator import validate


@pytest.mark.parametrize(
    "provider_name, model, endpoint",
    [
        ("typesafe", "jev-latest", "https://api.typesafe.ai/v1/systemone"),
        ("openrouter", "typesafe/jev-1.13", "https://openrouter.ai/api/alpha/decisions"),
    ],
)
def test_provider_contract(provider_name, model, endpoint, skill, policy, response):
    calls = []
    settings = Settings(provider_name, "test-key", model, 10)

    def handler(request):
        calls.append(request)
        assert str(request.url) == endpoint
        assert request.headers["Authorization"] == "Bearer test-key"
        payload = json.loads(request.content)
        assert payload["model"] == model
        assert set(payload) == {"model", "state", "questions"}
        assert payload["state"]["skill"]["frontmatter"]["name"] == "example-skill"
        assert set(payload["questions"]) == set(policy["dimensions"]) | set(policy["risks"])
        assert "untrusted" in payload["questions"]["trigger_precision"]["instructions"]
        return httpx.Response(200, json=response)

    provider = JevProvider(settings, httpx.MockTransport(handler))
    report = validate(skill, policy, settings, provider=provider)
    assert len(calls) == 1
    assert report.status == "passed"
    assert report.quality_score == 100
    assert report.model == "jev-1.13.0"


def test_remote_error_body_not_echoed(settings):
    transport = httpx.MockTransport(lambda _: httpx.Response(401, text="PRIVATE BODY test-key"))
    with pytest.raises(ProviderError) as error:
        JevProvider(settings, transport).evaluate({}, {})
    assert "401" in str(error.value)
    assert "PRIVATE" not in str(error.value)
    assert "test-key" not in str(error.value)


def test_timeout_produces_incomplete_report(skill, policy, settings):
    def handler(request):
        raise httpx.ReadTimeout("private payload", request=request)

    report = validate(
        skill, policy, settings, provider=JevProvider(settings, httpx.MockTransport(handler))
    )
    assert report.status == "error"
    assert report.semantic_status == "error"
    assert report.quality_score is None
    assert "private payload" not in json.dumps(report.to_dict())


def test_retry_is_bounded(settings, monkeypatch):
    monkeypatch.setattr("skill_validator.providers.time.sleep", lambda _: None)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "1"})

    with pytest.raises(ProviderError):
        JevProvider(settings, httpx.MockTransport(handler)).evaluate({}, {})
    assert len(calls) == 3


def test_redirect_is_not_followed(settings):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(307, headers={"Location": "https://other.example"})

    with pytest.raises(ProviderError):
        JevProvider(settings, httpx.MockTransport(handler)).evaluate({}, {})
    assert len(calls) == 1


def test_no_key_makes_no_http_request():
    settings = Settings("typesafe", "", "jev-latest", 10)
    calls = []
    transport = httpx.MockTransport(lambda request: calls.append(request))
    with pytest.raises(ProviderError, match="TYPESAFE_API_KEY"):
        JevProvider(settings, transport).evaluate({}, {})
    assert not calls
