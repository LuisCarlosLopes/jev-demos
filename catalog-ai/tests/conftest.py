import pytest

from catalog_ai.config import Settings


def choice(value, options):
    rest = [o for o in options if o != value]
    probabilities = {value: 0.9, **{o: 0.1 / len(rest) for o in rest}}
    return {"type": "choice", "choice": value, "confidence": 0.9, "probabilities": probabilities}


@pytest.fixture
def catalog():
    base = {"type": "skill", "technologies": [], "team": "Plataforma", "installs": 0}
    return [
        {**base, "id": "a", "name": "code-review", "purpose": "code-review",
         "description": "Review pull requests.", "install": "npx skills add x@a"},
        {**base, "id": "b", "name": "make-coffee", "purpose": "produtividade",
         "description": "Brew coffee.", "install": "npx skills add x@b"},
    ]


@pytest.fixture
def jev_response():
    return {
        "model": "jev-1.13.0",
        "answers": {
            "technology": choice("dotnet", ["dotnet", "react", "not_mentioned"]),
            "artifact_type": choice("not_mentioned", ["skill", "mcp", "not_mentioned"]),
            "purpose": choice("code_review", ["code_review", "testes", "not_mentioned"]),
            "team": choice("not_mentioned", ["plataforma", "not_mentioned"]),
            "incomplete": {"type": "noul", "noul": 0.05},
            "r_0": {"type": "noul", "noul": 0.91},
            "r_1": {"type": "noul", "noul": 0.07},
        },
        "usage": {"input_tokens": 1200, "output_tokens": 30},
    }


@pytest.fixture
def settings():
    return Settings("typesafe", "test-key", "jev-latest", 5)
