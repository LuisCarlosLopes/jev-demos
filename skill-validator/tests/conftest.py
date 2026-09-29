import copy
from pathlib import Path

import pytest

from skill_validator.config import Settings
from skill_validator.policy import load_policy

PROJECT = Path(__file__).resolve().parents[1]


@pytest.fixture
def policy():
    return copy.deepcopy(load_policy(PROJECT / "policy.yaml"))


@pytest.fixture
def skill(tmp_path):
    root = tmp_path / "example-skill"
    root.mkdir()
    (root / "SKILL.md").write_text(
        "---\nname: example-skill\ndescription: Summarize supplied meeting notes.\n---\n"
        "Read supplied notes and return decisions and actions in a Markdown table.\n",
        encoding="utf-8",
    )
    return root


@pytest.fixture
def settings():
    return Settings("typesafe", "test-key", "jev-latest", 10)


@pytest.fixture
def response(policy):
    answers = {}
    for key, dimension in policy["dimensions"].items():
        maximum = len(dimension["criteria"]) - 1
        answers[key] = {
            "type": "score",
            "score": maximum,
            "confidence": 1,
            "probabilities": {str(i): int(i == maximum) for i in range(maximum + 1)},
            "legend": {str(i): text for i, text in enumerate(dimension["criteria"])},
        }
    for key in policy["risks"]:
        answers[key] = {"type": "noul", "noul": 0.01}
    return {
        "model": "jev-1.13.0",
        "answers": answers,
        "usage": {"input_tokens": 1000, "output_tokens": 100},
    }
