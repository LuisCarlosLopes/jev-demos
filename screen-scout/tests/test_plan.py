from datetime import date

from screen_scout.decisions import classification_request, parse_classification
from screen_scout.plan import (
    build_report,
    evaluate,
    learn,
    plan_markdown,
    regex_escape,
    stable_pattern,
)
from screen_scout.probes import plan_probes
from screen_scout.profile import build_profile

from .conftest import fake_answer

SUMMARY = "Revise os campos destacados."
SUCCESS = "Cadastro salvo com sucesso. Protocolo 000123."


def _profile(screen):
    state, questions = classification_request(screen)
    classification = parse_classification(fake_answer(state, questions), questions)
    return build_profile(screen, classification, today=date(2026, 9, 30))


def _observe(probe, profile):
    """Simula a tela: recusa vazios e CPF incompleto, mas aceita CPF com dígito errado."""
    field_id, value = probe.field_id, probe.value
    if probe.kind == "maxlength":
        return {"typed": len(value), "length": 10}
    if probe.kind == "clear":
        return {"values": {f.element.id: f.initial for f in profile.fields}, "new_text": []}
    rejected = probe.kind == "required" or (field_id == "e1" and value == "529.982.247")
    rejected = rejected or (probe.kind == "observe" and field_id == "e0")
    if rejected:
        return {"new_text": [SUMMARY, f"Campo {field_id} inválido."], "invalid": [field_id],
                "url_changed": False, "cleared": False}
    return {"new_text": [SUCCESS], "invalid": [], "url_changed": False, "cleared": True}


def verdict(value: str, confidence: float = 0.95) -> dict:
    """Veredicto já validado, no formato de parse_oracle."""
    return {"value": value, "confidence": confidence, "top": [{"key": value, "p": confidence}]}


def _oracle(probes):
    verdicts = {}
    for probe in probes:
        if not probe.needs_oracle:
            continue
        rejected = SUMMARY in probe.observation["new_text"]
        verdicts[probe.id] = {"outcome": verdict("rejected" if rejected else "accepted")}
        if probe.blame:
            verdicts[probe.id]["blame"] = verdict(probe.field_id if rejected else "none", 0.9)
    return {"probes": verdicts}


def _run(screen):
    profile = _profile(screen)
    probes = plan_probes(profile, allow_submit=True, today=date(2026, 9, 30))
    for probe in probes:
        probe.observation = _observe(probe, profile)
    return profile, probes, _oracle(probes)


def test_risky_action_is_never_probed(screen):
    profile, probes, _ = _run(screen)
    risky = {a.element.id for a in profile.actions if a.risky}
    assert "e7" in risky
    assert all(p.action_id not in risky for p in probes)
    assert profile.submit.element.id == "e5"


def test_verdicts_and_conventions(screen):
    profile, probes, oracle = _run(screen)
    results = {r.probe.title: r for r in evaluate(profile, probes, oracle)}
    assert results["Salvar com todos os campos válidos"].status == "ok"
    assert results["Recusar sem preencher CPF"].status == "ok"
    assert results["Recusar CPF com dígito verificador inválido"].status == "divergence"
    assert results["Recusar CPF incompleto"].status == "ok"
    assert results["Comportamento com nome com uma palavra só"].status == "observed"
    assert results["Observações limitado a 10 caracteres"].status == "ok"
    conventions = learn(profile, list(results.values()))
    assert conventions.error_summary == [SUMMARY]
    assert conventions.success == [SUCCESS]
    assert conventions.aria_invalid is True


def test_low_confidence_and_guessed_required_become_review(screen):
    profile, probes, oracle = _run(screen)
    happy = next(p for p in probes if p.kind == "happy")
    oracle["probes"][happy.id]["outcome"] = verdict("accepted", 0.4)
    results = {r.probe.id: r for r in evaluate(profile, probes, oracle)}
    assert results[happy.id].status == "uncertain"
    # Um "obrigatório" que só o Jev estimou e a tela aceitou vazio vira pergunta, não defeito.
    field = profile.field("e0")
    field.required_p = 0.62
    required = next(p for p in probes if p.kind == "required" and p.field_id == "e0")
    required.observation = {"new_text": [SUCCESS], "invalid": [], "cleared": True}
    oracle["probes"][required.id]["outcome"] = verdict("accepted")
    results = {r.probe.id: r for r in evaluate(profile, probes, oracle)}
    assert results[required.id].status == "uncertain"


def test_divergence_case_asserts_the_learned_convention(screen):
    profile, probes, oracle = _run(screen)
    report = build_report(profile, probes, oracle, True, {
        "probes": len(probes), "total_s": "1,0", "jev_requests": 2, "decisions": 10,
        "cost_label": "US$ 0,00001"})
    case = next(c for c in report["cases"] if c["title"] == "Recusar CPF com dígito verificador "
                "inválido")
    ops = [s["op"] for s in case["steps"]]
    assert ops == ["fill_valid", "submit", "expect_invalid", "expect_text"]
    assert case["steps"][0]["value"] == {"cpf": "529.982.247-26"}
    assert case["steps"][3]["value"] == SUMMARY
    assert report["findings"]["divergences"][0]["title"] == case["title"]
    happy = report["cases"][0]
    assert happy["steps"][-1]["extra"] == {"regex": True}
    assert happy["steps"][-1]["value"].endswith(r"Protocolo \d+\.")
    manual = [c for c in report["cases"] if c["status"] == "manual"]
    assert [c["automated"] for c in manual] == [False]
    markdown = plan_markdown(report)
    assert "## Test Scenarios" in markdown and "**Seed:** `tests/seed.spec.ts`" in markdown
    assert "- expect: “CPF” marcado como inválido" in markdown
    assert "### Divergências encontradas" in markdown


def test_regex_helpers():
    assert stable_pattern("Matrícula 001234 criada.") == r"Matrícula \d+ criada\."
    assert regex_escape("a/b (c)") == r"a\/b \(c\)"
