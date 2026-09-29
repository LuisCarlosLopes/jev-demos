import pytest

from brand_live.config import Settings


def choice(value, options, confidence=0.9):
    rest = [o for o in options if o != value]
    probabilities = {value: confidence, **{o: (1 - confidence) / len(rest) for o in rest}}
    return {
        "type": "choice",
        "choice": value,
        "confidence": confidence,
        "probabilities": probabilities,
    }


@pytest.fixture
def brand():
    return {
        "vertical": "saas_b2b",
        "background": "white",
        "primary": "blue",
        "text": "auto",
        "accent": "indigo",
        "font": "sans",
        "layout": "split",
        "tone": 2,
        "sections": ["features", "pricing", "email", "social"],
    }


@pytest.fixture
def jev_response():
    return {
        "model": "jev-1.13.0",
        "answers": {
            "is_command": {"type": "noul", "noul": 0.95},
            "intent": choice("change_color", ["change_color", "change_tone", "none"]),
            "target": choice("background", ["background", "primary", "not_mentioned"]),
            "color": choice("red", ["red", "orange", "not_mentioned"], 0.86),
            "vertical": choice("not_mentioned", ["coffee", "not_in_catalog", "not_mentioned"]),
            "tone": {"type": "score", "score": 2.0, "confidence": 0.7},
            "layout": choice("not_mentioned", ["split", "not_mentioned"]),
            "font": choice("not_mentioned", ["serif", "not_mentioned"]),
            "section": choice("not_mentioned", ["email", "not_mentioned"]),
            "out_of_catalog": {"type": "noul", "noul": 0.04},
        },
        "usage": {"input_tokens": 1500, "output_tokens": 40},
    }


@pytest.fixture
def settings():
    return Settings("typesafe", "test-key", "jev-latest", 5)


@pytest.fixture
def fake_settings():
    return Settings("typesafe", "", "jev-latest", 5, fake=True)
