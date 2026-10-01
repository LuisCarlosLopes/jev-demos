from screen_scout.capture import Screen
from screen_scout.decisions import classification_request, parse_classification
from screen_scout.profile import build_profile

from .conftest import action, fake_answer, field


def _profile(elements):
    screen = Screen(url="http://x.test/f", title="Férias", lang="pt-BR", headings=["Férias"],
                    lines=["Campos com * são obrigatórios."], elements=elements, width=1, height=1)
    state, questions = classification_request(screen)
    return build_profile(screen, parse_classification(fake_answer(state, questions), questions))


def test_risky_native_submit_is_not_replaced_by_another_button():
    profile = _profile([
        field("e0", "Dias *"),
        action("e1", "Enviar solicitação", submit=True),
        action("e2", "Salvar rascunho"),
    ])
    assert profile.submit is None
    assert "Enviar solicitação" in profile.submit_note


def test_save_outside_a_form_is_used_only_without_one_inside():
    profile = _profile([
        field("e0", "Nome *"),
        action("e1", "Salvar", in_form=False),
        action("e2", "Gravar", in_form=True),
    ])
    assert profile.submit.element.id == "e2"


def test_clear_only_answers_for_fields_in_its_group():
    from screen_scout.plan import evaluate
    from screen_scout.probes import plan_probes

    profile = _profile([
        field("e0", "Buscar", type="search", role="searchbox", scopes=[]),
        field("e1", "Python", type="checkbox", role="checkbox", checked=False, scopes=["s1"]),
        field("e2", "Relevância", type="range", role="slider", value="0.6", scopes=["s1"]),
        action("e3", "limpar", scopes=["s1"], in_form=False),
    ])
    clear = next(a for a in profile.actions if a.role == "clear")
    assert [f.element.id for f in profile.fields_in_scope(clear)] == ["e1", "e2"]
    probe = next(p for p in plan_probes(profile, allow_submit=False) if p.kind == "clear")
    assert probe.value == {"e1": True}  # marca a caixa para o "limpar" ter o que desfazer
    # A busca, fora do grupo, continua preenchida: não é divergência.
    probe.observation = {"values": {"e0": "Maria", "e1": False, "e2": "0.6"}}
    (result,) = evaluate(profile, [probe], None)
    assert result.status == "ok", result.summary
    probe.observation = {"values": {"e0": "", "e1": True, "e2": "0.6"}}
    (result,) = evaluate(profile, [probe], None)
    assert result.status == "divergence" and "Python" in result.summary


def _decided(role: str, risk: float) -> dict:
    return {"role": {"value": role, "confidence": 0.9, "top": [{"key": role, "p": 0.9}]},
            "risk": risk}


def test_risky_words_apply_to_save_but_not_to_a_native_reset():
    elements = [
        field("e0", "Nome *"),
        action("e1", "Salvar", submit=True),
        action("e2", "Descartar alterações", type="reset"),
        action("e3", "Pagar selecionados", in_form=False),
    ]
    screen = Screen(url="http://x.test/f", title="T", lang="pt-BR", headings=[], lines=[],
                    elements=elements, width=1, height=1)
    classification = {
        "screen": {"kind": {"value": "form_create", "confidence": 0.9, "top": []},
                   "criticality": {"value": 1.0, "confidence": 0.9}, "personal_data": 0.1},
        "elements": {
            "e1": _decided("submit_save", 0.55),
            # Reset nativo com palavra de risco no rótulo: continua clicável.
            "e2": _decided("clear", 0.15),
            # "Salvar" para o Jev, mas com palavra de risco: barrado e fora das sondagens.
            "e3": _decided("submit_save", 0.6),
        },
    }
    profile = build_profile(screen, classification)
    risky = {a.element.name: a.risky for a in profile.actions}
    assert risky == {"Salvar": False, "Descartar alterações": False, "Pagar selecionados": True}
    assert profile.submit.element.name == "Salvar"
