"""Mede a assertividade das decisões: Jev x heurística lexical (o modo --fake), com gabarito.

    uv run python scripts/eval_decisions.py --env-file ../skill-validator/.env

Captura as telas de evals/screens com o Playwright (sem servidor: set_content), faz a mesma
requisição de classificação ao Jev e à heurística, e compara com evals/gabarito.json. O oráculo
é avaliado com casos de mensagens reais de ERP. Grava o detalhe em evals/resultado.md.
"""

import argparse
import asyncio
import json
import sys
from dataclasses import replace
from pathlib import Path

import httpx
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from screen_scout.capture import Element, Screen, capture, strip_label  # noqa: E402
from screen_scout.config import Settings  # noqa: E402
from screen_scout.decisions import (  # noqa: E402
    classification_request,
    oracle_request,
    parse_classification,
    parse_oracle,
)
from screen_scout.fake import fake_handler  # noqa: E402
from screen_scout.jev import JevClient, estimate_cost  # noqa: E402
from screen_scout.profile import build_profile  # noqa: E402

EVALS = ROOT / "evals"


class Score:
    def __init__(self):
        self.hits = 0
        self.total = 0
        self.misses: list[str] = []

    def add(self, ok: bool, detail: str) -> None:
        self.total += 1
        self.hits += ok
        if not ok:
            self.misses.append(detail)

    def __str__(self) -> str:
        return f"{self.hits}/{self.total}" if self.total else "—"


def _conf(value) -> str:
    return "" if value is None else f" ({round(value * 100)}%)"


def _server(html: str):
    async def serve(route) -> None:
        await route.fulfill(body=html, content_type="text/html; charset=utf-8")

    return serve


async def classify(client: JevClient, screens: list[tuple[dict, Screen]]):
    scores = {k: Score() for k in ("kind", "required", "role", "risky", "screen")}
    low_conf_misses = 0
    calls = []
    risks = []
    for truth, screen in screens:
        state, questions = classification_request(screen)
        decision = await client.decide(state, questions)
        calls.append((decision, len(questions)))
        profile = build_profile(screen, parse_classification(decision.data, questions))
        name = truth["file"]
        kind = profile.kind in truth["screen_kind"]
        scores["screen"].add(kind, f"{name}: tela {profile.kind}{_conf(profile.kind_confidence)}")
        fields = {strip_label(f.element.name): f for f in profile.fields}
        for label, expected in truth["fields"].items():
            got = fields.get(strip_label(label))
            if got is None:
                scores["kind"].add(False, f"{name}: “{label}” não capturado")
                continue
            if "kind" in expected and got.kind_source == "jev":
                ok = got.kind in expected["kind"]
                scores["kind"].add(ok, f"{name}: “{label}” → {got.kind}{_conf(got.kind_confidence)}"
                                   f", esperado {'/'.join(expected['kind'])}")
                if not ok and (got.kind_confidence or 1) < profile.thresholds.confidence:
                    low_conf_misses += 1
            if "required" in expected:
                ok = got.required == expected["required"]
                scores["required"].add(ok, f"{name}: “{label}” obrigatório={got.required}"
                                       f"{_conf(got.required_p)}, esperado {expected['required']}")
        actions = {a.element.name: a for a in profile.actions}
        for label, expected in truth["actions"].items():
            got = actions.get(label)
            if got is None:
                scores["role"].add(False, f"{name}: “{label}” não capturado")
                continue
            ok = got.role in expected["role"]
            scores["role"].add(ok, f"{name}: “{label}” → {got.role}{_conf(got.role_confidence)}, "
                               f"esperado {'/'.join(expected['role'])}")
            if not ok and got.role_confidence < profile.thresholds.confidence:
                low_conf_misses += 1
            risks.append((name, label, expected["risky"], got.risk_p, got.risky))
            if expected["risky"] is not None:
                ok = got.risky == expected["risky"]
                reason = got.risky_reason or "—"
                scores["risky"].add(ok, f"{name}: “{label}” não clicar={got.risky} "
                                    f"(risco {round(got.risk_p * 100)}%; {reason}), "
                                    f"esperado {expected['risky']}")
    return scores, calls, low_conf_misses, risks


async def oracle(client: JevClient, truth: dict):
    fields = [
        Element(id=f"f{i}", tag="input", type="text", role="textbox", name=label, label=label,
                kind="field", locator={"method": "label", "value": label, "unique": True})
        for i, label in enumerate(truth["fields"])
    ]
    screen = Screen(url="http://eval.test", title=truth["title"], lang="pt-BR",
                    headings=[truth["title"]], lines=[], elements=fields, width=0, height=0)
    ids = {f.label: f.id for f in fields}
    items = []
    for index, case in enumerate(truth["cases"]):
        observed = {
            "new_text": case["new_text"],
            "fields_marked_invalid": case.get("fields_marked_invalid", []),
            "form_was_cleared": case.get("form_was_cleared", False),
            "navigated_to": case.get("navigated_to"),
            "browser_dialog": case.get("browser_dialog"),
            "http_errors": case.get("http_errors", []),
        }
        items.append({"id": f"c{index}", "action": "Filled the form and clicked 'Gravar'.",
                      "observed": observed, "blame": True})
    state, questions = oracle_request(screen, items)
    decision = await client.decide(state, questions)
    verdicts = parse_oracle(decision.data, questions, screen)["probes"]
    outcome, blame = Score(), Score()
    low_conf_misses = 0
    for index, case in enumerate(truth["cases"]):
        got = verdicts[f"c{index}"]
        text = " / ".join(case["new_text"]) or case.get("browser_dialog") or str(
            case.get("http_errors") or case.get("fields_marked_invalid") or "(nada)")
        ok = got["outcome"]["value"] in case["outcome"]
        outcome.add(ok, f"“{text}” → {got['outcome']['value']}{_conf(got['outcome']['confidence'])}"
                    f", esperado {'/'.join(case['outcome'])}")
        if not ok and got["outcome"]["confidence"] < 0.6:
            low_conf_misses += 1
        if case["blame"] is not None:
            accepted = case["blame"] if isinstance(case["blame"], list) else [case["blame"]]
            expected = {ids.get(b, b) for b in accepted}
            value = got["blame"]["value"]
            shown = next((label for label, i in ids.items() if i == value), value)
            blame.add(value in expected, f"“{text}” → campo {shown}"
                      f"{_conf(got['blame']['confidence'])}, esperado {'/'.join(accepted)}")
    return outcome, blame, (decision, len(questions)), low_conf_misses


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    settings = Settings.load(args.env_file)
    if not settings.api_key:
        sys.exit("Preencha a chave do Jev no .env (ou passe --env-file).")
    truth = json.loads((EVALS / "gabarito.json").read_text(encoding="utf-8"))
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        screens = []
        for item in truth["screens"]:
            page = await browser.new_page()
            html = (EVALS / "screens" / item["file"]).read_text(encoding="utf-8")
            # Origem de verdade (http://eval.test): com set_content todo link pareceria externo.
            await page.route("http://eval.test/**", _server(html))
            await page.goto(f"http://eval.test/{item['file']}")
            screens.append((item, await capture(page, screenshot=False)))
            await page.close()
        await browser.close()
    jev = JevClient(settings)
    fake = JevClient(replace(settings, fake=True), httpx.MockTransport(fake_handler))
    report = [
        "# Assertividade das decisões: Jev x heurística lexical",
        "",
        "Gerado por `scripts/eval_decisions.py`. **Desenvolvimento**: telas e casos usados para "
        "ajustar as perguntas e a captura. **Validação**: gabarito escrito antes de rodar o Jev "
        "nessas telas, sem ajustes depois.",
        "",
    ]
    sets = {}
    for set_name in ("desenvolvimento", "validacao"):
        chosen = [s for s in screens if s[0]["set"] == set_name]
        groups = [g for g in truth["oracle"] if g["set"] == set_name]
        table = {}
        risk_rows = {}
        for label, client in (("Jev", jev), ("Heurística", fake)):
            scores, calls, low_c, risks = await classify(client, chosen)
            o_score, b_score = Score(), Score()
            for group in groups:
                o, b, o_call, low_o = await oracle(client, group)
                for mine, theirs in ((o_score, o), (b_score, b)):
                    mine.hits += theirs.hits
                    mine.total += theirs.total
                    mine.misses += theirs.misses
                calls.append(o_call)
                low_c += low_o
            table[label] = (scores, o_score, b_score, calls, low_c)
            risk_rows[label] = risks
        sets[set_name] = (table, risk_rows, chosen, groups)
    await jev.aclose()
    await fake.aclose()
    rows = [
        ("Tipo de dado (campos de texto)", lambda t: t[0]["kind"]),
        ("Obrigatoriedade", lambda t: t[0]["required"]),
        ("Papel da ação", lambda t: t[0]["role"]),
        ("Portão de risco (não clicar)", lambda t: t[0]["risky"]),
        ("Tipo de tela", lambda t: t[0]["screen"]),
        ("Oráculo: desfecho", lambda t: t[1]),
        ("Oráculo: campo apontado", lambda t: t[2]),
    ]
    for set_name, (table, risk_rows, chosen, groups) in sets.items():
        files = ", ".join(s[0]["file"] for s in chosen)
        cases = sum(len(g["cases"]) for g in groups)
        title = "Desenvolvimento" if set_name == "desenvolvimento" else "Validação"
        report += [f"## {title}", "", f"Telas: {files} · {cases} casos de oráculo.", "",
                   "| Decisão | Jev | Heurística |", "|---|---:|---:|"]
        for name, pick in rows:
            report.append(f"| {name} | {pick(table['Jev'])} | {pick(table['Heurística'])} |")
        jev_calls = table["Jev"][3]
        tokens = sum(d.data.get("usage", {}).get("input_tokens", 0) for d, _ in jev_calls)
        cost = sum(estimate_cost(d.data.get("usage", {})) or 0 for d, _ in jev_calls)
        latencies = ", ".join(f"{round(d.ms)} ms ({n} perguntas)" for d, n in jev_calls)
        wrong = sum(len(pick(table["Jev"]).misses) for _, pick in rows)
        report += ["", f"Jev: {len(jev_calls)} requisições · {latencies} · {tokens} tokens · "
                   f"US$ {cost:.5f}.",
                   f"Erros do Jev com confiança abaixo de 60% (iriam para “revisar”): "
                   f"{table['Jev'][4]} de {wrong}.", ""]
        for label in ("Jev", "Heurística"):
            report.append(f"### Erros · {label}")
            report.append("")
            misses = [f"- {name}: {miss}"
                      for name, pick in rows for miss in pick(table[label]).misses]
            report += misses or ["- nenhum"]
            report.append("")
        report += ["### Risco estimado por ação (Jev)", "",
                   "| Tela | Ação | Deve evitar? | Risco (Noul) | Barrada |",
                   "|---|---|---|---:|---|"]
        for screen_name, label, expected, risk_p, risky in risk_rows["Jev"]:
            wanted = "—" if expected is None else ("sim" if expected else "não")
            report.append(f"| {screen_name} | {label} | {wanted} | {round(risk_p * 100)}% | "
                          f"{'sim' if risky else 'não'} |")
        report.append("")
    text = "\n".join(report)
    (EVALS / "resultado.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    asyncio.run(main())
