import json

import httpx
import pytest

from story_sizer.ado import Story
from story_sizer.cli import actual_size
from story_sizer.config import Settings, load_policy
from story_sizer.jev import JevClient, JevError, build_questions
from story_sizer.normalize import build_state, html_to_text, parse_title
from story_sizer.scoring import interpret


@pytest.fixture
def policy() -> dict:
    return load_policy()


def test_html_to_text_keeps_bullets_and_strips_tags():
    raw = "<p>Como PO, quero <b>x</b>.</p><ul><li>um</li><li>dois &amp; tr&ecirc;s</li></ul>"
    text = html_to_text(raw)
    assert "Como PO, quero x." in text
    assert "- um" in text and "- dois & três" in text
    assert "<" not in text


def test_parse_title_extracts_stream():
    meta = parse_title("[Sprint 6 - Stream A] - MBO-0 · Fundação")
    assert meta == {"stream": "Stream A", "short_title": "MBO-0 · Fundação"}
    assert parse_title("Sem padrão")["stream"] is None


def test_build_state_truncates_description_but_keeps_acceptance(policy):
    story = Story(
        id=1,
        title="[Sprint 6 - Stream B] - X",
        state="New",
        iteration="",
        description_html="<p>" + "a" * 80000 + "</p>",
        acceptance_html="<p>AC</p>",
    )
    state, info = build_state(story, policy)
    assert info["truncated"] is True
    assert len(state["story"]["description"]) <= policy["max_state_chars"]
    assert state["story"]["acceptance_criteria"] == "AC"
    assert state["story"]["stream"] == "Stream B"


def test_questions_cover_policy(policy):
    q = build_questions(policy)
    assert q["size"]["type"] == "choice"
    assert set(q["size"]["criteria"]) == {policy["sizes"][k].get("key", k) for k in policy["order"]}
    assert all(q[k]["type"] == "score" for k in policy["factors"])
    assert all(q[k]["type"] == "noul" for k in policy["flags"])


def _answers(probs: dict, conf: float, policy: dict | None = None) -> dict:
    if policy:  # traduz PP..GG para as chaves em horas que o Jev devolve
        probs = {policy["sizes"][k].get("key", k): v for k, v in probs.items()}
    a = {"size": {"type": "choice", "choice": "M", "confidence": conf, "probabilities": probs}}
    for k in ("scope", "complexity", "uncertainty"):
        a[k] = {"type": "score", "score": 1.5, "confidence": 0.8, "probabilities": {}}
    a["vague_criteria"] = {"type": "noul", "noul": 0.7}
    a["should_split"] = {"type": "noul", "noul": 0.1}
    return a


def test_interpret_bands_and_flags(policy):
    probs = {"PP": 0.0, "P": 0.1, "M": 0.6, "G": 0.3, "GG": 0.0}
    r = interpret(_answers(probs, 0.5, policy), {"input_tokens": 1000}, 400, policy)
    assert r["suggested"] == "M" and r["second"] == "G"
    assert r["band"] == "tentative"
    assert r["flags"]["vague_criteria"]["raised"] is True
    assert r["flags"]["should_split"]["raised"] is False
    assert r["usage"]["cost_usd"] == pytest.approx(1000 * 0.042 / 1e6)
    assert r["expected_days"] == pytest.approx(0.1 * 1.5 + 0.6 * 4 + 0.3 * 7.5)
    reported = interpret(
        _answers(probs, 0.5, policy), {"input_tokens": 1000, "cost": 0.00012}, 400, policy
    )
    assert reported["usage"]["cost_usd"] == pytest.approx(0.00012)


def test_interpret_rejects_bad_distribution(policy):
    with pytest.raises(JevError):
        interpret(_answers({"PP": 1.0}, 0.9), {}, 0, policy)


def test_actual_size_bands(policy):
    assert actual_size(4, policy) == "PP"
    assert actual_size(16, policy) == "P"
    assert actual_size(40, policy) == "M"
    assert actual_size(80, policy) == "G"
    assert actual_size(200, policy) == "GG"


async def test_jev_client_retries_and_hides_body():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(500, text="secret body")

    settings = Settings("o", "p", "t", "pat", "key", "jev-1.13.0", 5, 2, False)
    client = JevClient(settings, transport=httpx.MockTransport(handler))
    with pytest.raises(JevError) as exc:
        await client.evaluate({"story": {}}, {})
    await client.aclose()
    assert len(calls) == 2
    assert "secret" not in str(exc.value)
    assert "key" not in str(exc.value)


def test_env_selects_openrouter(tmp_path, monkeypatch):
    for name in (
        "JEV_PROVIDER",
        "OPENROUTER_API_KEY",
        "OPENROUTER_MODEL",
        "TYPESAFE_API_KEY",
        "TYPESAFE_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("JEV_PROVIDER=openrouter\nOPENROUTER_API_KEY=fake-key-from-file\n")
    settings = Settings.load(env_file)
    assert settings.provider == "openrouter"
    assert settings.jev_model == "typesafe/jev-1.13"
    assert settings.jev_api_key == "fake-key-from-file"
    assert settings.jev_api_key not in repr(settings)
    assert settings.jev_endpoint == "https://openrouter.ai/api/alpha/decisions"
    overridden = Settings.load(env_file, provider="typesafe")
    assert overridden.provider == "typesafe"
    assert overridden.jev_model == "jev-1.13.0"
    assert overridden.jev_endpoint == "https://api.typesafe.ai/v1/systemone"


async def test_openrouter_client_sends_title_and_model():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["title"] = request.headers.get("X-Title")
        seen["model"] = json.loads(request.content)["model"]
        return httpx.Response(200, json={"model": "typesafe/jev-1.13", "answers": {}})

    settings = Settings(
        "o", "p", "t", "pat", "or-key", "typesafe/jev-1.13", 5, 2, False, "openrouter"
    )
    client = JevClient(settings, transport=httpx.MockTransport(handler))
    data = await client.evaluate({"story": {}}, {"size": {"type": "choice"}})
    await client.aclose()
    assert data["answers"] == {}
    assert seen == {
        "url": "https://openrouter.ai/api/alpha/decisions",
        "title": "Jev Story Sizer Demo",
        "model": "typesafe/jev-1.13",
    }
