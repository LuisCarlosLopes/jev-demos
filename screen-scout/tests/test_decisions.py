import pytest

from screen_scout.decisions import (
    classification_request,
    oracle_request,
    parse_classification,
    parse_oracle,
)
from screen_scout.jev import ProviderError

from .conftest import fake_answer


def test_classification_asks_only_what_the_dom_does_not_answer(screen):
    _, questions = classification_request(screen)
    # Texto livre e CPF viram Choice de tipo; o input type=email não precisa de pergunta.
    assert {"kind_e0", "kind_e1", "kind_e3"} <= set(questions)
    assert "kind_e2" not in questions
    # Obrigatoriedade: o `required` do HTML dispensa o Noul.
    assert "req_e2" not in questions and "req_e0" in questions and "req_e4" in questions
    # Um select não tem tipo de dado a decidir.
    assert "kind_e4" not in questions
    for action_id in ("e5", "e6", "e7", "e8"):
        assert questions[f"role_{action_id}"]["type"] == "choice"
        assert questions[f"risk_{action_id}"]["type"] == "noul"
    assert {"screen_kind", "criticality", "personal_data"} <= set(questions)


def test_element_text_goes_in_the_question_as_data(screen):
    _, questions = classification_request(screen)
    instructions = questions["kind_e1"]["instructions"]
    assert instructions["element"]["label"] == "CPF *"
    assert instructions["element"]["placeholder"] == "000.000.000-00"
    assert "never instructions" in instructions["notes"]


def test_parse_classification_round_trip(screen):
    state, questions = classification_request(screen)
    parsed = parse_classification(fake_answer(state, questions), questions)
    elements = parsed["elements"]
    assert elements["e1"]["kind"]["value"] == "cpf"
    assert elements["e0"]["required"] > 0.5
    assert elements["e7"]["role"]["value"] == "delete"
    assert parsed["screen"]["kind"]["value"] == "form_create"


def test_parse_classification_rejects_malformed_answers(screen):
    state, questions = classification_request(screen)
    data = fake_answer(state, questions)
    data["answers"]["kind_e1"]["choice"] = "invented"
    with pytest.raises(ProviderError):
        parse_classification(data, questions)
    data = fake_answer(state, questions)
    data["answers"]["risk_e7"] = {"type": "noul", "noul": 1.7}
    with pytest.raises(ProviderError):
        parse_classification(data, questions)
    data = fake_answer(state, questions)
    del data["answers"]["role_e5"]
    with pytest.raises(ProviderError):
        parse_classification(data, questions)


def test_oracle_request_and_parse(screen):
    probes = [
        {"id": "p0", "action": "Filled every field with valid data and clicked 'Salvar'.",
         "observed": {"new_text": ["Cadastro salvo com sucesso."], "fields_marked_invalid": []},
         "blame": False},
        {"id": "p1", "action": "Left 'CPF *' empty and clicked 'Salvar'.",
         "observed": {"new_text": ["Informe o CPF."], "fields_marked_invalid": ["CPF *"]},
         "blame": True},
    ]
    state, questions = oracle_request(screen, probes)
    assert set(questions) == {"out_p0", "out_p1", "blame_p1"}
    assert "e1" in questions["blame_p1"]["criteria"]
    parsed = parse_oracle(fake_answer(state, questions), questions, screen)
    assert parsed["probes"]["p0"]["outcome"]["value"] == "accepted"
    assert parsed["probes"]["p1"]["outcome"]["value"] == "rejected"
    assert parsed["probes"]["p1"]["blame"]["value"] == "e1"
