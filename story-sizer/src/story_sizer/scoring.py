"""Transforma as respostas tipadas do Jev em uma sugestão explicável. Sem texto livre."""

from .jev import PRICE_INPUT_PER_MTOK, JevError, option_key


def _num(v, lo: float, hi: float) -> bool:
    return isinstance(v, int | float) and lo <= v <= hi


def interpret(answers: dict, usage: dict, elapsed_ms: int, policy: dict) -> dict:
    size = answers.get("size")
    if not isinstance(size, dict) or size.get("type") != "choice":
        raise JevError("Resposta Choice de tamanho ausente.")
    raw = size.get("probabilities")
    order = policy["order"]
    keys = {option_key(policy["sizes"][k], k): k for k in order}
    if (
        not isinstance(raw, dict)
        or set(raw) != set(keys)
        or any(not _num(p, 0, 1) for p in raw.values())
    ):
        raise JevError("Distribuição de tamanhos inválida.")
    # Volta das chaves em horas para os nomes PP..GG.
    probs = {keys[k]: raw[k] for k in keys}
    if not _num(size.get("confidence"), 0, 1):
        raise JevError("Confiança inválida na resposta de tamanho.")

    ranked = sorted(order, key=lambda k: probs[k], reverse=True)
    top, second = ranked[0], ranked[1]
    confidence = float(size["confidence"])
    bands = policy["confidence"]
    if confidence >= bands["firm"]:
        band = "firm"
    elif confidence >= bands["tentative"]:
        band = "tentative"
    else:
        band = "review"

    # Esforço esperado ponderado pela distribuição: mais estável que o ponto médio do vencedor.
    expected_days = sum(probs[k] * policy["sizes"][k]["days"] for k in order)

    factors = {}
    for key, spec in policy["factors"].items():
        a = answers.get(key)
        maximum = len(spec["criteria"]) - 1
        if (
            not isinstance(a, dict)
            or a.get("type") != "score"
            or not _num(a.get("score"), 0, maximum)
            or not _num(a.get("confidence"), 0, 1)
        ):
            raise JevError(f"Resposta Score inválida: {key}.")
        factors[key] = {
            "label": spec["label"],
            "score": round(float(a["score"]), 2),
            "max": maximum,
            "level": spec["criteria"][round(a["score"])],
            "confidence": round(float(a["confidence"]), 3),
        }

    flags = {}
    for key, spec in policy["flags"].items():
        a = answers.get(key)
        if not isinstance(a, dict) or a.get("type") != "noul" or not _num(a.get("noul"), 0, 1):
            raise JevError(f"Resposta Noul inválida: {key}.")
        flags[key] = {
            "label": spec["label"],
            "probability": round(float(a["noul"]), 3),
            "raised": a["noul"] >= spec["review_at"],
        }

    input_tokens = usage.get("input_tokens") if isinstance(usage, dict) else None
    cost = (
        round(input_tokens * PRICE_INPUT_PER_MTOK / 1_000_000, 8)
        if _num(input_tokens, 0, 1e12)
        else None
    )
    return {
        "suggested": top,
        "second": second,
        "confidence": round(confidence, 3),
        "band": band,
        "probabilities": {k: round(float(probs[k]), 4) for k in order},
        "expected_days": round(expected_days, 2),
        "factors": factors,
        "flags": flags,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": usage.get("output_tokens") if isinstance(usage, dict) else None,
            "cost_usd": cost,
            "elapsed_ms": elapsed_ms,
        },
    }
