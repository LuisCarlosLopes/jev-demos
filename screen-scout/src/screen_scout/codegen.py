"""Código de teste a partir dos casos: Python (pytest-playwright) e TypeScript (@playwright/test).

Os dois emissores leem a mesma representação intermediária de plan.py. Não há LLM aqui: os
localizadores são os que a exploração verificou, os valores vêm do catálogo e as asserções vêm
do que a tela mostrou (ou da convenção que ela usou nas outras sondagens).
"""

import json
import re

from .plan import slugify


def _py(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)


def _ts(text: str) -> str:
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n") + "'"


def _py_regex(pattern: str) -> str:
    if '"' not in pattern and not pattern.endswith("\\"):
        return f're.compile(r"{pattern}")'
    return f"re.compile({_py(pattern)})"


def _repeated(value: str) -> tuple[str, int] | None:
    if len(value) > 20 and len(set(value)) == 1:
        return value[0], len(value)
    return None


def py_locator(spec: dict) -> str:
    method, value = spec["method"], spec["value"]
    if method == "test_id":
        return f"page.get_by_test_id({_py(value)})"
    if method == "label":
        exact = ", exact=True" if spec.get("exact") else ""
        return f"page.get_by_label({_py(value)}{exact})"
    if method == "role":
        exact = ", exact=True" if spec.get("exact", True) else ""
        return f"page.get_by_role({_py(spec['role'])}, name={_py(value)}{exact})"
    if method == "placeholder":
        return f"page.get_by_placeholder({_py(value)}, exact=True)"
    if method == "text":
        return f"page.get_by_text({_py(value)}, exact=True)"
    return f"page.locator({_py(value)})"


def ts_locator(spec: dict) -> str:
    method, value = spec["method"], spec["value"]
    if method == "test_id":
        return f"page.getByTestId({_ts(value)})"
    if method == "label":
        exact = ", { exact: true }" if spec.get("exact") else ""
        return f"page.getByLabel({_ts(value)}{exact})"
    if method == "role":
        exact = ", exact: true" if spec.get("exact", True) else ""
        return f"page.getByRole({_ts(spec['role'])}, {{ name: {_ts(value)}{exact} }})"
    if method == "placeholder":
        return f"page.getByPlaceholder({_ts(value)}, {{ exact: true }})"
    if method == "text":
        return f"page.getByText({_ts(value)}, {{ exact: true }})"
    return f"page.locator({_ts(value)})"


def _names(cases: list[dict]) -> dict[str, str]:
    names: dict[str, str] = {}
    used: set[str] = set()
    for case in cases:
        base = "test_" + slugify(case["title"], "_")
        name, n = base, 2
        while name in used:
            name, n = f"{base}_{n}", n + 1
        used.add(name)
        names[case["number"]] = name
    return names


def automated(report: dict) -> list[dict]:
    return [c for c in report["cases"] if c["automated"] and c["steps"]]


def _fields(report: dict) -> list[dict]:
    keys = report["field_keys"]
    return [{**f, "key": keys[f["id"]]} for f in report["profile"]["fields"]
            if f["control"] != "file"]


def _submit(report: dict) -> dict | None:
    submit_id = report["profile"]["submit"]
    return next((a for a in report["profile"]["actions"] if a["id"] == submit_id), None)


def _header_lines(report: dict) -> list[str]:
    meta = report["meta"]
    return [
        f"Testes gerados pelo Screen Scout (Jev + Playwright) para “{report['screen']['name']}”.",
        "",
        f"Origem: {report['screen']['url']} · {meta['generated_at']} · plano: plano.md",
        "Localizadores verificados na exploração; massa de teste do catálogo do Screen Scout.",
        "Divergências encontradas na exploração falham até a tela ser corrigida.",
    ]


# --- Python ----------------------------------------------------------------------------------


def _py_value(value) -> str:
    if isinstance(value, bool):
        return "True" if value else "False"
    return _py(str(value))


def _py_step(step: dict) -> list[str]:
    op, target, value = step["op"], step.get("target"), step.get("value")
    loc = py_locator(target) if target else ""
    if op == "note":
        return [f"# {step['text']}"]
    if op == "fill_valid":
        if not value:
            return ["preencher(page)"]
        args = ", ".join(f"{key}={_py_value(v)}" for key, v in value.items())
        return [f"preencher(page, {args})"]
    if op == "submit":
        return ["salvar(page)"]
    if op == "click":
        return [f"{loc}.click()"]
    if op == "fill":
        repeated = _repeated(str(value))
        literal = f"{_py(repeated[0])} * {repeated[1]}" if repeated else _py(str(value))
        return [f"{loc}.fill({literal})"]
    if op == "expect_text":
        if step.get("extra", {}).get("regex"):
            return [f"expect(page.get_by_text({_py_regex(value)}).first).to_be_visible()"]
        return [f"expect(page.get_by_text({_py(value)}, exact=True).first).to_be_visible()"]
    if op == "expect_no_text":
        return [f"expect(page.get_by_text({_py_regex(value)}).first).not_to_be_visible()"]
    if op == "expect_invalid":
        return [f'expect({loc}).to_have_attribute("aria-invalid", "true")']
    if op == "expect_url":
        return [f"expect(page).to_have_url({_py_regex(value)})"]
    if op == "expect_dialog":
        name = f", name={_py(value)}" if value else ""
        return [f'expect(page.get_by_role("dialog"{name})).to_be_visible()']
    if op == "expect_value":
        control = step.get("extra", {}).get("control")
        if control in {"check", "radio"}:
            return [f"expect({loc}).{'to_be_checked' if value else 'not_to_be_checked'}()"]
        return [f"expect({loc}).to_have_value({_py(str(value))})"]
    if op == "expect_value_regex":
        return [f"expect({loc}).to_have_value({_py_regex(value)})"]
    if op == "expect_attr":
        attr = step.get("extra", {}).get("attr", "href")
        return [f"expect({loc}).to_have_attribute({_py(attr)}, {_py(str(value))})"]
    raise ValueError(f"Passo desconhecido: {op}")


def _fit(line: str, indent: str, width: int = 99) -> list[str]:
    """Quebra `expect(X).metodo(...)` longo em três linhas, no estilo do ruff/black."""
    if len(indent + line) <= width or not line.startswith("expect("):
        return [indent + line]
    depth = 0
    for index, char in enumerate(line):
        depth += {"(": 1, ")": -1}.get(char, 0)
        if depth == 0 and index > 6:
            inner, rest = line[7:index], line[index:]
            return [f"{indent}expect(", f"{indent}    {inner}", f"{indent}{rest}"]
    return [indent + line]


def _wrap(text: str, width: int = 92, prefix: str = "# ") -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        if current and len(current) + 1 + len(word) > width:
            lines.append(prefix + current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(prefix + current)
    return lines


def python_tests(report: dict) -> tuple[str, dict[str, str]]:
    """Devolve (código, {nome da função: número do caso})."""
    cases = automated(report)
    names = _names(cases)
    fields = _fields(report)
    submit = _submit(report)
    body: list[str] = []
    for case in cases:
        steps = [line for step in case["steps"] for line in _py_step(step)]
        uses_submit = any(s["op"] == "submit" for s in case["steps"])
        if uses_submit and not submit:
            continue
        body += ["", ""]
        if case["skip_reason"]:
            body.append(f"@pytest.mark.skip(reason={_py(case['skip_reason'][:180])})")
        body.append(f"def {names[case['number']]}(page: Page) -> None:")
        body.append(f'    """{case["number"]} · {case["priority"]} · {case["title"]}."""')
        if case["note"]:
            body += ["    " + line for line in _wrap(case["note"], 88)]
        body += [part for line in steps for part in _fit(line, "    ")]
    text = "\n".join(body)
    needs_re = "re.compile(" in text
    header = _header_lines(report)
    lines = ['"""' + header[0], *header[1:], '"""', "", "import os"]
    if needs_re:
        lines.append("import re")
    lines += ["", "import pytest", "from playwright.sync_api import Locator, Page, expect", ""]
    lines.append(f'URL = os.environ.get("SCREEN_SCOUT_URL", {_py(report["screen"]["url"])})')
    lines += ["", "MASSA_VALIDA: dict[str, str | bool] = {"]
    for f in fields:
        if f["valid"] is not None:
            lines.append(f"    {_py(f['key'])}: {_py_value(f['valid'])},")
    lines += ["}", "", "", "def campos(page: Page) -> dict[str, tuple[str, Locator]]:",
              '    """Localizadores verificados na exploração: um elemento por chave."""',
              "    return {"]
    for f in fields:
        action = {"select": "select", "check": "check", "radio": "check"}.get(f["control"], "fill")
        entry = f"        {_py(f['key'])}: ({_py(action)}, {py_locator(f['locator'])}),"
        if len(entry) > 99:
            entry = (f"        {_py(f['key'])}: (\n            {_py(action)}, "
                     f"{py_locator(f['locator'])}\n        ),")
        lines.append(entry)
    lines += [
        "    }",
        "",
        "",
        "def preencher(page: Page, **trocas: str | bool) -> None:",
        '    """Preenche a massa válida; cada troca substitui um campo (um fator por vez)."""',
        "    valores = {**MASSA_VALIDA, **trocas}",
        "    for chave, (acao, campo) in campos(page).items():",
        "        if chave not in valores:",
        "            continue",
        "        valor = valores[chave]",
        '        if acao == "select":',
        "            campo.select_option(str(valor))",
        '        elif acao == "check":',
        "            if valor:",
        "                campo.check()",
        "            else:",
        "                campo.uncheck()",
        "        else:",
        "            campo.fill(str(valor))",
    ]
    if submit:
        lines += ["", "", "def salvar(page: Page) -> None:",
                  f"    {py_locator(submit['locator'])}.click()"]
    if report["meta"].get("session"):
        lines += [
            "", "", '@pytest.fixture(scope="session")',
            "def browser_context_args(browser_context_args: dict) -> dict:",
            '    """Tela com login: usa a sessão salva pelo Screen Scout, se informada."""',
            '    estado = os.environ.get("SCREEN_SCOUT_STORAGE_STATE")',
            '    return {**browser_context_args, "storage_state": estado} if estado else (',
            "        browser_context_args",
            "    )",
        ]
    lines += ["", "", "@pytest.fixture(autouse=True)", "def abrir_tela(page: Page) -> None:",
              "    page.goto(URL)"]
    code = "\n".join(lines) + "\n" + text + "\n"
    return code, {name: number for number, name in names.items()}


# --- TypeScript ------------------------------------------------------------------------------


def _ts_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return _ts(str(value))


def _ts_step(step: dict) -> list[str]:
    op, target, value = step["op"], step.get("target"), step.get("value")
    loc = ts_locator(target) if target else ""
    if op == "note":
        return [f"// {step['text']}"]
    if op == "fill_valid":
        if not value:
            return ["await preencher(page);"]
        args = ", ".join(f"{key}: {_ts_value(v)}" for key, v in value.items())
        return [f"await preencher(page, {{ {args} }});"]
    if op == "submit":
        return ["await salvar(page);"]
    if op == "click":
        return [f"await {loc}.click();"]
    if op == "fill":
        repeated = _repeated(str(value))
        literal = (f"{_ts(repeated[0])}.repeat({repeated[1]})" if repeated
                   else _ts(str(value)))
        return [f"await {loc}.fill({literal});"]
    if op == "expect_text":
        if step.get("extra", {}).get("regex"):
            return [f"await expect(page.getByText(/{value}/).first()).toBeVisible();"]
        return [f"await expect(page.getByText({_ts(value)}, {{ exact: true }}).first())"
                ".toBeVisible();"]
    if op == "expect_no_text":
        return [f"await expect(page.getByText(/{value}/).first()).not.toBeVisible();"]
    if op == "expect_invalid":
        return [f"await expect({loc}).toHaveAttribute('aria-invalid', 'true');"]
    if op == "expect_url":
        return [f"await expect(page).toHaveURL(/{value}/);"]
    if op == "expect_dialog":
        name = f", {{ name: {_ts(value)} }}" if value else ""
        return [f"await expect(page.getByRole('dialog'{name})).toBeVisible();"]
    if op == "expect_value":
        control = step.get("extra", {}).get("control")
        if control in {"check", "radio"}:
            return [f"await expect({loc}).{'toBeChecked' if value else 'not.toBeChecked'}();"]
        return [f"await expect({loc}).toHaveValue({_ts(str(value))});"]
    if op == "expect_value_regex":
        return [f"await expect({loc}).toHaveValue(/{value}/);"]
    if op == "expect_attr":
        attr = step.get("extra", {}).get("attr", "href")
        return [f"await expect({loc}).toHaveAttribute({_ts(attr)}, {_ts(str(value))});"]
    raise ValueError(f"Passo desconhecido: {op}")


def typescript_tests(report: dict) -> str:
    cases = automated(report)
    fields = _fields(report)
    submit = _submit(report)
    header = _header_lines(report)
    lines = ["// " + header[0], *[("// " + h).rstrip() for h in header[1:]], "",
             "import { test, expect, type Locator, type Page } from '@playwright/test';", "",
             f"const URL = process.env.SCREEN_SCOUT_URL ?? {_ts(report['screen']['url'])};", "",
             "const MASSA_VALIDA: Record<string, string | boolean> = {"]
    for f in fields:
        if f["valid"] is not None:
            lines.append(f"  {f['key']}: {_ts_value(f['valid'])},")
    lines += ["};", "", "type Acao = 'fill' | 'select' | 'check';", "",
              "function campos(page: Page): Record<string, [Acao, Locator]> {",
              "  // Localizadores verificados na exploração: cada um resolve um único elemento.",
              "  return {"]
    for f in fields:
        action = {"select": "select", "check": "check", "radio": "check"}.get(f["control"], "fill")
        lines.append(f"    {f['key']}: [{_ts(action)}, {ts_locator(f['locator'])}],")
    lines += [
        "  };",
        "}",
        "",
        "// Preenche a massa válida; cada troca substitui um campo (um fator por vez).",
        "async function preencher(page: Page, trocas: Record<string, string | boolean> = {}) {",
        "  const valores = { ...MASSA_VALIDA, ...trocas };",
        "  for (const [chave, [acao, campo]] of Object.entries(campos(page))) {",
        "    if (!(chave in valores)) continue;",
        "    const valor = valores[chave];",
        "    if (acao === 'select') await campo.selectOption(String(valor));",
        "    else if (acao === 'check') await (valor ? campo.check() : campo.uncheck());",
        "    else await campo.fill(String(valor));",
        "  }",
        "}",
    ]
    if submit:
        lines += ["", "async function salvar(page: Page) {",
                  f"  await {ts_locator(submit['locator'])}.click();", "}"]
    if report["meta"].get("session"):
        lines += ["", "// Tela com login: sessão salva pelo Screen Scout.",
                  "test.use({ storageState: process.env.SCREEN_SCOUT_STORAGE_STATE });"]
    lines += ["", "test.beforeEach(async ({ page }) => {", "  await page.goto(URL);", "});"]
    current = None
    for case in cases:
        if any(s["op"] == "submit" for s in case["steps"]) and not submit:
            continue
        if case["group_label"] != current:
            if current is not None:
                lines.append("});")
            current = case["group_label"]
            lines += ["", f"test.describe({_ts(current)}, () => {{"]
        else:
            lines.append("")
        title = f"{case['number']} {case['title']}"
        lines.append(f"  test({_ts(title)}, async ({{ page }}) => {{")
        if case["skip_reason"]:
            lines.append(f"    test.skip(true, {_ts(case['skip_reason'][:180])});")
        if case["note"]:
            lines += ["    " + line for line in _wrap(case["note"], 88, "// ")]
        for step in case["steps"]:
            lines += [f"    {line}" for line in _ts_step(step)]
        lines.append("  });")
    if current is not None:
        lines.append("});")
    return "\n".join(lines) + "\n"


def file_names(report: dict) -> dict[str, str]:
    base = re.sub(r"-", "_", report["slug"])
    return {"python": f"test_{base}.py", "typescript": f"{report['slug']}.spec.ts",
            "plan": "plano.md"}
