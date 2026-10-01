import re
from datetime import date

from screen_scout.catalog import ACTION_ROLES, CNPJ_VALID, CPF_VALID, data_kinds


def _cpf_ok(digits: str) -> bool:
    if len(set(digits)) == 1:
        return False
    for size in (9, 10):
        total = sum(int(d) * w for d, w in zip(digits[:size], range(size + 1, 1, -1), strict=True))
        if (total * 10) % 11 % 10 != int(digits[size]):
            return False
    return True


def test_valid_cpf_and_cnpj_have_correct_check_digits():
    assert CPF_VALID == "52998224725"
    assert _cpf_ok(CPF_VALID)
    assert CNPJ_VALID == "11222333000181"


def test_invalid_cpf_probes_really_are_invalid():
    cpf = data_kinds()["cpf"]
    assert _cpf_ok(re.sub(r"\D", "", cpf.valid))
    for probe in cpf.invalid:
        digits = re.sub(r"\D", "", probe.value)
        assert len(digits) != 11 or not _cpf_ok(digits), probe.key


def test_every_kind_has_a_valid_value_and_scenario_templates():
    for key, kind in data_kinds().items():
        assert kind.valid, key
        for probe in kind.invalid:
            assert "{campo}" in probe.title, (key, probe.key)
            assert probe.expect in {"reject", "observe"}


def test_dates_depend_on_today():
    kinds = data_kinds(date(2024, 2, 29))
    future = next(p for p in kinds["birth_date"].invalid if p.key == "future")
    assert future.value == "28/02/2025"
    assert kinds["date"].valid == "29/02/2024"


def test_risky_roles_are_the_ones_never_clicked():
    risky = {key for key, role in ACTION_ROLES.items() if role.risky}
    assert risky == {"send", "delete", "logout", "export"}
