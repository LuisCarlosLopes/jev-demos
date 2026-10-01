"""Jev simulado (`--fake` ou JEV_FAKE=1): heurística lexical em português.

Serve para desenvolver a interface sem chave e como linha de base "sem Jev" no script de
avaliação. Não representa a qualidade nem a latência do Jev; a tela avisa quando está ativo.
"""

import json
import re
import unicodedata

import httpx

_KIND_WORDS = [
    ("cpf", ("cpf",)),
    ("cnpj", ("cnpj",)),
    ("email", ("e-mail", "email")),
    ("phone", ("celular", "telefone", "fone", "whatsapp")),
    ("cep", ("cep",)),
    ("birth_date", ("nascimento",)),
    ("money", ("salario", "valor", "preco", "r$", "remuneracao")),
    ("percentage", ("percentual", "%", "taxa")),
    ("quantity", ("quantidade", "qtd", "idade", "dias")),
    ("date", ("data", "admissao", "inicio", "vencimento", "dd/mm")),
    ("password", ("senha",)),
    ("search", ("buscar", "pesquisar")),
    ("url", ("site", "url")),
    ("code", ("codigo", "matricula")),
    ("person_name", ("nome",)),
    ("free_text", ("observa", "descri", "coment", "endereco", "motivo")),
]
_ROLE_WORDS = [
    ("submit_save", ("salvar", "gravar", "cadastrar", "confirmar")),
    ("send", ("enviar", "aprovacao", "transmitir")),
    ("delete", ("excluir", "remover", "apagar", "descartar")),
    ("clear", ("limpar",)),
    ("cancel_back", ("cancelar", "voltar")),
    ("logout", ("sair", "logout")),
    ("search_filter", ("buscar", "pesquisar", "filtrar")),
    ("export", ("exportar", "baixar", "imprimir")),
    ("open_panel", ("ajuda", "detalhes", "abrir", "mais")),
]
_ERROR_WORDS = ("invalid", "informe", "obrigat", "revise", "erro", "deve ", "selecione")
_SUCCESS_WORDS = ("sucesso", "salvo", "cadastrad", "concluid", "registrad")
_RISKY_ROLES = {"send", "delete", "logout", "export"}


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text).lower())
    return text.encode("ascii", "ignore").decode()


def _choice(options: list[str], value: str, confidence: float = 0.86) -> dict:
    rest = [o for o in options if o != value]
    share = (1 - confidence) / len(rest) if rest else 0
    probabilities = {value: confidence if rest else 1.0, **{o: share for o in rest}}
    return {"type": "choice", "choice": value, "confidence": confidence,
            "probabilities": probabilities}


def _first(text: str, table) -> str | None:
    return next((key for key, words in table if any(w in text for w in words)), None)


def _element_text(element: dict) -> str:
    parts = [element.get(k, "") for k in ("label", "placeholder", "help", "text", "section")]
    return _normalize(" ".join(str(p) for p in parts if p))


def _answer(key: str, question: dict, state: dict) -> dict:
    instructions = question.get("instructions")
    info = instructions if isinstance(instructions, dict) else {}
    options = list(question.get("criteria") or [])
    element = info.get("element", {})
    if key == "screen_kind":
        heads = _normalize(" ".join(state["screen"].get("headings", [])))
        kind = ("form_edit" if "editar" in heads else
                "form_create" if any(w in heads for w in ("novo", "cadastro", "nova")) else
                "search_list" if any(w in heads for w in ("pesquisa", "lista")) else
                "login" if "entrar" in heads or "login" in heads else "other")
        return _choice(options, kind)
    if key == "criticality":
        return {"type": "score", "score": 2.0, "confidence": 0.7}
    if key == "personal_data":
        text = _normalize(" ".join(state["screen"].get("visible_text", [])))
        hit = any(w in text for w in ("cpf", "e-mail", "nascimento", "salario"))
        return {"type": "noul", "noul": 0.9 if hit else 0.2}
    prefix = key.split("_", 1)[0]
    if prefix == "kind":
        return _choice(options, _first(_element_text(element), _KIND_WORDS) or "other")
    if prefix == "req":
        label = str(element.get("label", ""))
        required = label.rstrip().endswith("*") or "obrigat" in _normalize(label)
        return {"type": "noul", "noul": 0.9 if required else 0.1}
    if prefix == "role":
        text = _element_text(element)
        role = _first(text, _ROLE_WORDS)
        if role is None:
            role = "navigate" if element.get("link_to") else "other"
        if element.get("submits_form") and role in {None, "other"}:
            role = "submit_save"
        return _choice(options, role)
    if prefix == "risk":
        role = _first(_element_text(element), _ROLE_WORDS)
        return {"type": "noul", "noul": 0.9 if role in _RISKY_ROLES else 0.05}
    observed = info.get("observed", {})
    text = _normalize(" ".join(observed.get("new_text", [])))
    rejected = bool(observed.get("fields_marked_invalid")) or any(w in text for w in _ERROR_WORDS)
    if prefix == "out":
        if rejected:
            outcome = "rejected"
        elif observed.get("http_errors"):
            outcome = "server_error"
        elif any(w in text for w in _SUCCESS_WORDS) or observed.get("form_was_cleared"):
            outcome = "accepted"
        else:
            outcome = "no_feedback"
        return _choice(options, outcome)
    if prefix == "blame":
        criteria = question.get("criteria") or {}
        for label in observed.get("fields_marked_invalid", []):
            match = next((k for k, v in criteria.items() if f"'{label}'" in v), None)
            if match:
                return _choice(options, match)
        return _choice(options, "general" if rejected else "none")
    raise ValueError(f"Pergunta desconhecida no modo simulado: {key}")


def fake_handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    state = body["state"]
    answers = {key: _answer(key, q, state) for key, q in body["questions"].items()}
    tokens = len(re.sub(r"\s+", " ", request.content.decode())) // 4
    return httpx.Response(
        200,
        json={"model": "simulado", "answers": answers,
              "usage": {"input_tokens": tokens, "output_tokens": 0}},
    )
