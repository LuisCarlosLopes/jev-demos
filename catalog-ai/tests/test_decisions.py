import copy

import pytest

from catalog_ai.decisions import (
    DESCRIPTION_CHARS,
    NOT_MENTIONED,
    build_request,
    parse_response,
)
from catalog_ai.jev import ProviderError


def test_one_request_carries_facets_and_one_noul_per_artifact(catalog):
    state, questions, keymap = build_request("revisar PR em C#", {"team": "Backend"}, catalog)
    assert state["request"] == "revisar PR em C#"
    assert state["user_profile"] == {"team": "Backend", "technologies": []}
    assert set(keymap.values()) == {item["id"] for item in catalog}
    for facet in ("technology", "artifact_type", "purpose", "team"):
        assert questions[facet]["type"] == "choice"
        assert NOT_MENTIONED in questions[facet]["criteria"]
    assert questions["incomplete"]["type"] == "noul"
    assert len(questions) == 5 + len(catalog)


def test_long_descriptions_are_trimmed(catalog):
    item = {**catalog[0], "description": "palavra " * 200}
    _, questions, _ = build_request("x", {}, [item])
    description = questions["r_0"]["instructions"]["artifact"]["description"]
    assert len(description) <= DESCRIPTION_CHARS + 1
    assert description.endswith("…")


def test_parse_maps_keys_back_to_catalog(catalog, jev_response):
    _, _, keymap = build_request("code review", {}, catalog)
    result = parse_response(jev_response, keymap)
    assert result["facets"]["technology"]["value"] == "C#/.NET"
    assert result["facets"]["artifact_type"]["value"] is None
    assert result["facets"]["purpose"]["value"] == "code-review"
    assert result["relevance"] == {"a": 0.91, "b": 0.07}
    assert result["usage"] == {"input_tokens": 1200, "output_tokens": 30}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r["answers"].pop("r_1"),
        lambda r: r["answers"]["r_0"].update(noul=1.4),
        lambda r: r["answers"]["technology"].update(choice="cobol"),
        lambda r: r["answers"]["team"]["probabilities"].update(produto=0.9),
        lambda r: r.pop("model"),
    ],
)
def test_malformed_answers_are_rejected(catalog, jev_response, mutate):
    _, _, keymap = build_request("code review", {}, catalog)
    broken = copy.deepcopy(jev_response)
    mutate(broken)
    with pytest.raises(ProviderError):
        parse_response(broken, keymap)
