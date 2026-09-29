import json

import pytest

from brand_live.decisions import (
    COLORS,
    NOT_IN_CATALOG,
    NOT_MENTIONED,
    VERTICALS,
    build_request,
    catalog,
    parse_response,
)
from brand_live.jev import ProviderError


def test_request_has_every_question_and_context(brand):
    state, questions = build_request("fundo vermelho", brand, ["a", "b", "c", "d"])
    assert state["utterance"] == "fundo vermelho"
    assert state["recent_utterances"] == ["b", "c", "d"]
    assert state["brand"] == brand
    assert set(questions) == {
        "is_command", "intent", "target", "color", "vertical", "tone", "layout", "font",
        "section", "out_of_catalog",
    }
    assert set(questions["color"]["criteria"]) == {*COLORS, NOT_MENTIONED}
    assert set(questions["vertical"]["criteria"]) == {*VERTICALS, NOT_MENTIONED, NOT_IN_CATALOG}
    assert questions["tone"]["type"] == "score" and len(questions["tone"]["criteria"]) == 5


def test_request_stays_within_jev_state_budget(brand):
    # 32k tokens para estado + maior pergunta; ~4 chars por token.
    state, questions = build_request("x" * 400, brand, ["y" * 400] * 3)
    largest = max(len(json.dumps(q)) for q in questions.values())
    assert len(json.dumps(state)) + largest < 32_000 * 4
    assert len(json.dumps({"state": state, "questions": questions})) < 64_000 * 4


def test_catalog_is_consistent():
    data = catalog()
    for key, vertical in data["verticals"].items():
        theme = vertical["theme"]
        assert theme["primary"] in data["colors"], key
        assert theme["background"] in data["colors"], key
        assert theme["accent"] in data["colors"], key
        assert theme["font"] in data["fonts"], key
        assert theme["layout"] in data["layouts"], key
        assert 0 <= theme["tone"] <= data["tone_levels"] - 1, key
        assert set(vertical["copy"]) == {"formal", "casual"}
        for voice in vertical["copy"].values():
            assert set(voice) == {"headline", "sub", "cta", "email_subject", "email_body", "social"}
        assert len(vertical["features"]) == 3
        assert "describe" not in vertical
    assert len(data["colors"]) + 1 <= 255


def test_parse_response_returns_typed_facets(jev_response):
    result = parse_response(jev_response)
    d = result["decisions"]
    assert result["model"] == "jev-1.13.0"
    assert d["is_command"] == 0.95
    assert d["intent"]["value"] == "change_color"
    assert d["color"] == {
        "value": "red",
        "confidence": 0.86,
        "top": [{"key": "red", "p": 0.86}, {"key": "orange", "p": 0.07},
                {"key": "not_mentioned", "p": 0.07}],
    }
    assert d["vertical"]["value"] is None
    assert d["tone"] == {"value": 2.0, "confidence": 0.7}
    assert result["usage"] == {"input_tokens": 1500, "output_tokens": 40}


def test_not_in_catalog_is_preserved(jev_response):
    jev_response["answers"]["vertical"]["choice"] = NOT_IN_CATALOG
    assert parse_response(jev_response)["decisions"]["vertical"]["value"] == NOT_IN_CATALOG


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r["answers"].pop("intent"),
        lambda r: r["answers"]["color"].update(choice="hex_ff0000"),
        lambda r: r["answers"]["color"]["probabilities"].update(red=0.2),
        lambda r: r["answers"]["tone"].update(score=7),
        lambda r: r["answers"]["is_command"].update(noul=1.5),
        lambda r: r.pop("model"),
    ],
)
def test_malformed_answers_are_rejected(jev_response, mutate):
    mutate(jev_response)
    with pytest.raises(ProviderError):
        parse_response(jev_response)
