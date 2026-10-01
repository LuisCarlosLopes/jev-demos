import ast

from screen_scout.codegen import py_locator, python_tests, ts_locator, typescript_tests
from screen_scout.plan import build_report

from .test_plan import _run

META = {"probes": 1, "total_s": "1,0", "jev_requests": 2, "decisions": 10,
        "cost_label": "US$ 0,00001"}


def _report(screen):
    profile, probes, oracle = _run(screen)
    return build_report(profile, probes, oracle, True, META)


def test_python_output_is_valid_and_uses_verified_locators(screen):
    code, tests = python_tests(_report(screen))
    tree = ast.parse(code)
    names = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    assert "preencher" in names and "salvar" in names
    assert "test_recusar_cpf_com_digito_verificador_invalido" in names
    assert set(tests) <= set(names)
    assert 'page.get_by_label("CPF")' in code
    assert 'page.get_by_role("button", name="Salvar", exact=True).click()' in code
    assert 'preencher(page, cpf="529.982.247-26")' in code
    assert 'to_have_attribute("aria-invalid", "true")' in code
    assert "Protocolo \\d+" in code
    # A ação de risco não vira teste automatizado.
    assert "Excluir" not in code
    assert max(len(line) for line in code.splitlines()) <= 100


def test_typescript_output(screen):
    code = typescript_tests(_report(screen))
    assert "import { test, expect, type Locator, type Page } from '@playwright/test';" in code
    assert "test.describe('Validação de formato', () => {" in code
    assert "await preencher(page, { cpf: '529.982.247-26' });" in code
    assert "toHaveAttribute('aria-invalid', 'true')" in code
    # Cada describe fecha no fim; o outro "});" de coluna zero é o do beforeEach.
    assert code.count("test.describe(") + 1 == code.count("\n});")


def test_counts_are_dropped_from_locators():
    from screen_scout.capture import without_count

    assert without_count("Skill103") == "Skill"
    assert without_count("Filtros (3)") == "Filtros"
    assert without_count("CPF") is None and without_count("Top 10 produtos") is None
    spec = {"method": "role", "role": "button", "value": "Skill", "exact": False}
    assert py_locator(spec) == 'page.get_by_role("button", name="Skill")'
    assert ts_locator(spec) == "page.getByRole('button', { name: 'Skill' })"


def test_locators_in_both_languages():
    spec = {"method": "role", "role": "button", "value": "Ir d'água"}
    assert py_locator(spec) == 'page.get_by_role("button", name="Ir d\'água", exact=True)'
    assert ts_locator(spec) == "page.getByRole('button', { name: 'Ir d\\'água', exact: true })"
    label = {"method": "label", "value": "CPF *", "exact": True}
    assert py_locator(label) == 'page.get_by_label("CPF *", exact=True)'
    assert ts_locator(label) == "page.getByLabel('CPF *', { exact: true })"
