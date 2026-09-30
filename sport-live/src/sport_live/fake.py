"""Explicitly simulated lexical transport, never presented as Jev inference."""

import re
import unicodedata

from .decisions import FOLLOWUPS, SCENES


def normalized(text):
    return "".join(
        c for c in unicodedata.normalize("NFD", text.lower()) if not unicodedata.combining(c)
    )


def fake_response(messages, catalog):
    text = normalized(" ".join(messages))
    scene = "general"
    vocab = {
        "travel": ["chile", "viajar", "viagem", "mala"],
        "snow": ["neve", "inverno", "frio", "esqui"],
        "hiking": ["trilha", "trekking", "acampar", "patagonia"],
        "football": ["futebol", "society", "futsal", "chuteira", "pelada"],
        "running": ["correr", "corrida", "5 km", "5km", "maratona", "running"],
        "fitness": ["academia", "musculacao", "yoga"],
        "gym": [
            "aparelho",
            "montar academia",
            "academia em casa",
            "esteira",
            "ergometrica",
            "spinning",
            "eliptico",
            "estacao de musculacao",
            "rack",
        ],
        "combat": [
            "luta",
            "boxe",
            "boxing",
            "muay thai",
            "jiu-jitsu",
            "jiu jitsu",
            "judo",
            "artes marciais",
            "saco de pancada",
        ],
        "swimming": ["nadar", "natacao", "piscina"],
    }
    # Most recent explicit goal wins; short refinements keep the previous goal.
    for message in messages:
        current = normalized(message)
        for candidate, words in vocab.items():
            if any(word in current for word in words):
                scene = candidate
    followup = "none"
    if scene == "travel" and not any(w in text for w in ["verao", "inverno", "cidade", "trilha"]):
        followup = "season"
    if scene == "football" and not any(w in text for w in ["society", "futsal", "campo"]):
        followup = "surface"
    if scene in {"running", "fitness"} and not any(
        w in text for w in ["iniciante", "comec", "vezes"]
    ):
        followup = "experience"
    disciplines = {
        "boxing": ["boxe", "boxing"],
        "muay_thai": ["muay thai"],
        "jiu_jitsu": ["jiu-jitsu", "jiu jitsu", "grappling"],
        "judo": ["judo"],
    }
    discipline = None
    for message in messages:
        for key, words in disciplines.items():
            if any(word in normalized(message) for word in words):
                discipline = key
    if scene == "combat" and discipline is None:
        followup = "discipline"
    answers = {}
    for key, value, options in [("scene", scene, SCENES), ("followup", followup, FOLLOWUPS)]:
        answers[key] = {
            "type": "choice",
            "choice": value,
            "confidence": 0.88,
            "probabilities": {
                k: 0.88 if k == value else 0.12 / (len(options) - 1) for k in options
            },
        }
    for item in catalog:
        relevance = 0.9 if scene in item["scenes"] else 0.08
        if scene == "combat" and discipline:
            compatible = {"all", discipline}
            if discipline == "muay_thai":
                compatible.add("boxing")
            if item.get("discipline", "all") not in compatible:
                relevance = 0.03
        surface = next((w for w in ["society", "futsal", "campo"] if w in text), None)
        if scene == "football" and surface and item["surface"] not in ["all", surface]:
            relevance = 0.03
        if any(
            re.search(r"(ja tenho|nao quero|sem)\s+(?:uma?\s+)?" + word, text)
            for word in item["exclude_words"]
        ):
            relevance = 0.02
        answers[item["id"]] = {"type": "noul", "noul": relevance}
    return {"model": "simulado · heurística local", "answers": answers, "usage": {}}
