import json

import httpx
import pytest

from screen_scout.capture import Element, Screen
from screen_scout.fake import fake_handler


def field(id_, label, **kw) -> Element:
    base = {"tag": "input", "type": "text", "role": "textbox", "name": label, "label": label,
            "kind": "field", "path": f"#{id_}", "html_id": id_,
            "locator": {"method": "label", "value": label.rstrip(" *"), "exact": False,
                        "unique": True}}
    return Element(id=id_, **{**base, **kw})


def action(id_, name, **kw) -> Element:
    base = {"tag": "button", "type": "", "role": "button", "name": name, "label": "",
            "kind": "action", "in_form": True,
            "locator": {"method": "role", "role": "button", "value": name, "unique": True}}
    return Element(id=id_, **{**base, **kw})


@pytest.fixture
def screen() -> Screen:
    elements = [
        field("e0", "Nome *"),
        field("e1", "CPF *", placeholder="000.000.000-00"),
        field("e2", "E-mail", type="email", required=True),
        field("e3", "Observações", tag="textarea", maxlength=10),
        field("e4", "Cargo *", tag="select", type="", role="combobox",
              options=[{"value": "", "label": "Selecione"}, {"value": "dev", "label": "Dev"}]),
        action("e5", "Salvar", submit=True),
        action("e6", "Limpar"),
        action("e7", "Excluir rascunho"),
        action("e8", "Início", tag="a", role="link", href="http://x.test/inicio",
               href_attr="/inicio", same_origin=True,
               locator={"method": "role", "role": "link", "value": "Início", "unique": True}),
    ]
    return Screen(url="http://x.test/cadastro", title="Cadastro", lang="pt-BR",
                  headings=["Novo cadastro"],
                  lines=["Novo cadastro", "Campos com * são obrigatórios."],
                  elements=elements, width=1280, height=900)


def fake_answer(state: dict, questions: dict) -> dict:
    """Resposta simulada bem-formada, como a do Jev, para uma requisição."""
    request = httpx.Request("POST", "http://jev.test", json={"model": "x", "state": state,
                                                             "questions": questions})
    return json.loads(fake_handler(request).content)


def choice(value: str, options, confidence: float = 0.9) -> dict:
    rest = [o for o in options if o != value]
    probabilities = {value: confidence, **{o: (1 - confidence) / len(rest) for o in rest}}
    return {"type": "choice", "choice": value, "confidence": confidence,
            "probabilities": probabilities}
