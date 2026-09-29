"""Jev simulado (`--fake` ou JEV_FAKE=1): heurística lexical em português.

Serve só para desenvolver e testar a tela sem chave. Não representa a qualidade nem
a latência do Jev; a interface exibe um aviso enquanto estiver ativo.
"""

import json
import re
import unicodedata

import httpx

from .decisions import NOT_IN_CATALOG, NOT_MENTIONED, TONE_LEVELS

_COLOR_WORDS = {
    "branco": "white", "branca": "white", "off white": "off_white", "creme": "off_white",
    "preto": "black", "preta": "black", "cinza escuro": "dark_gray", "cinza claro": "light_gray",
    "cinza": "gray", "vermelho": "red", "vermelha": "red", "vinho": "dark_red", "bordo": "dark_red",
    "laranja": "orange", "ambar": "amber", "amarelo": "yellow", "amarela": "yellow",
    "limao": "lime", "verde escuro": "dark_green", "verde": "green", "petroleo": "teal",
    "ciano": "cyan", "azul claro": "sky", "azul marinho": "navy", "marinho": "navy",
    "azul": "blue", "indigo": "indigo", "roxo": "purple", "roxa": "purple", "violeta": "violet",
    "rosa": "pink", "magenta": "magenta", "marrom": "brown", "bege": "beige", "dourado": "gold",
}
_VERTICAL_WORDS = {
    "rh": "hr_consulting", "recursos humanos": "hr_consulting", "pessoas": "hr_consulting",
    "ia": "ai_consulting", "inteligencia artificial": "ai_consulting", "agentes": "ai_consulting",
    "tenis": "sneakers", "calcado": "sneakers", "sapato": "sneakers",
    "cafe": "coffee", "cafeteria": "coffee",
    "banco": "fintech", "fintech": "fintech", "pagamento": "fintech", "cartao": "fintech",
    "dentista": "dental", "odonto": "dental", "clinica": "dental",
    "advocacia": "law", "advogado": "law", "juridic": "law",
    "academia": "fitness", "treino": "fitness", "crossfit": "fitness",
    "saas": "saas_b2b", "software": "saas_b2b", "sistema": "saas_b2b",
    "imove": "real_estate", "imobiliaria": "real_estate", "apartamento": "real_estate",
    "restaurante": "restaurant", "pizza": "restaurant", "hamburguer": "restaurant",
    "curso": "education", "escola": "education", "educacao": "education",
}
_LAYOUT_WORDS = {"centraliz": "centered", "centro": "centered", "lado": "split",
                 "duas colunas": "split", "dividid": "split", "minimal": "minimal",
                 "limpo": "minimal"}
_FONT_WORDS = {"serif": "serif", "classic": "serif", "elegante": "serif", "display": "display",
               "grossa": "display", "impacto": "display", "mono": "mono", "codigo": "mono",
               "sans": "sans", "moderna": "sans"}
_SECTION_WORDS = {"diferencia": "features", "cards": "features", "plano": "pricing",
                  "preco": "pricing", "email": "email", "e mail": "email", "post": "social",
                  "social": "social", "instagram": "social"}
_INTENT_RULES = [
    ("undo", ("volta", "desfaz", "desfazer", "anterior")),
    ("reset", ("reset", "do zero", "recomec", "zera")),
    ("hide_section", ("tira", "esconde", "remove", "some com")),
    ("show_section", ("mostra", "adiciona", "coloca", "traz")),
    ("change_tone", ("leve", "serio", "seria", "formal", "descontra", "engracad", "tom", "sobrio")),
    ("change_layout", tuple(_LAYOUT_WORDS)),
    ("change_font", ("fonte", "tipografia", "letra", *_FONT_WORDS)),
    ("change_vertical", ("vender", "vende", "empresa de", "virar", "segmento", "negocio")),
]


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return re.sub(r"[^a-z0-9 ]+", " ", text.encode("ascii", "ignore").decode())


def _find(text: str, table: dict[str, str]) -> str | None:
    # Chaves mais longas primeiro: "azul marinho" antes de "azul".
    for word in sorted(table, key=len, reverse=True):
        if word in text:
            return table[word]
    return None


def _choice(options: list[str], value: str, confidence: float = 0.88) -> dict:
    rest = [o for o in options if o != value]
    probabilities = {value: confidence, **{o: (1 - confidence) / len(rest) for o in rest}}
    return {"type": "choice", "choice": value, "confidence": confidence,
            "probabilities": probabilities}


def fake_handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    text = _normalize(body["state"]["utterance"])
    brand = body["state"].get("brand") or {}
    questions = body["questions"]
    color = _find(text, _COLOR_WORDS)
    vertical = _find(text, _VERTICAL_WORDS)
    intent = next((name for name, words in _INTENT_RULES if any(w in text for w in words)), None)
    if intent is None and color:
        intent = "change_color"
    if intent is None and vertical:
        intent = "change_vertical"
    if intent == "change_vertical" and vertical is None:
        vertical = NOT_IN_CATALOG
    if intent is None:
        intent = "none"
    target = "background" if "fundo" in text else ("text" if "texto" in text else None)
    if target is None and color:
        target = "primary"
    current_tone = float(brand.get("tone", 2))
    if any(w in text for w in ("leve", "descontra", "engracad")):
        tone = min(4, current_tone + 1.5)
    elif any(w in text for w in ("serio", "seria", "formal", "sobrio")):
        tone = max(0, current_tone - 1.5)
    else:
        tone = current_tone

    def pick(key: str, value: str | None) -> dict:
        options = list(questions[key]["criteria"])
        return _choice(options, value if value in options else NOT_MENTIONED)

    answers = {
        "is_command": {"type": "noul", "noul": 0.08 if intent == "none" else 0.93},
        "intent": pick("intent", intent),
        "target": pick("target", target),
        "color": pick("color", color),
        "vertical": pick("vertical", vertical),
        "tone": {"type": "score", "score": round(tone, 2), "confidence": 0.8},
        "layout": pick("layout", _find(text, _LAYOUT_WORDS)),
        "font": pick("font", _find(text, _FONT_WORDS)),
        "section": pick("section", _find(text, _SECTION_WORDS)),
        "out_of_catalog": {"type": "noul",
                           "noul": 0.9 if re.search(r"#[0-9a-f]{3,6}|imagem|foto", text) else 0.05},
    }
    assert len(TONE_LEVELS) == 5
    tokens = len(request.content) // 4
    return httpx.Response(
        200, json={"model": "fake-jev", "answers": answers, "usage": {"input_tokens": tokens}}
    )
