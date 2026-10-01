"""Da exploração ao plano: veredicto de cada sondagem, convenções da tela e casos de teste.

Tudo aqui é determinístico. As decisões semânticas já vieram do Jev (classificação e oráculo);
este módulo só as combina com o que foi observado e com o catálogo. O resultado é uma lista
de casos numa representação intermediária (passos tipados), da qual saem o plano em Markdown
(formato do planner do Playwright) e o código em codegen.py.
"""

import re
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime

from .capture import strip_label
from .catalog import ACTION_ROLES, OUTCOMES, data_kinds
from .probes import ProbeRun
from .profile import FieldProfile, Profile

STATUS_LABELS = {
    "ok": "✅ conforme",
    "divergence": "❌ divergência",
    "uncertain": "⚠️ revisar",
    "observed": "🔎 observado",
    "manual": "✋ manual",
    "not_run": "⏸️ não executado",
    "error": "💥 falhou",
}

GROUPS = [
    ("happy", "Caminho feliz"),
    ("required", "Campos obrigatórios"),
    ("format", "Validação de formato"),
    ("limits", "Limites"),
    ("actions", "Ações da tela"),
    ("navigation", "Navegação"),
    ("observe", "Comportamentos a confirmar"),
    ("manual", "Ações de risco (manual)"),
]

MANUAL_EXPECTS = {
    "delete": "a tela pede confirmação antes de excluir; depois de confirmar, o registro some",
    "send": "o envio fica registrado, a tela confirma e o destinatário recebe",
    "logout": "a sessão termina e a tela de acesso aparece",
    "export": "o arquivo é gerado com os dados da tela",
    "submit_save": "o registro é salvo e a tela confirma",
}


def slugify(text: str, sep: str = "-") -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", sep, text).strip(sep) or "caso"


def regex_escape(text: str) -> str:
    """Escape comum a Python e JavaScript (o de `re.escape` escapa espaço, o que polui o TS)."""
    return re.sub(r"([\\^$.|?*+()\[\]{}/])", r"\\\1", text)


def stable_pattern(text: str) -> str:
    """Mensagem com números variáveis (matrícula, protocolo, hora) vira regex com \\d+."""
    parts = re.split(r"(\d+)", text)
    return "".join(r"\d+" if p.isdigit() else regex_escape(p) for p in parts)


@dataclass
class Step:
    op: str
    text: str  # passo em linguagem de usuário, para o plano
    target: dict | None = None
    value: object = None
    extra: dict = field(default_factory=dict)


@dataclass
class Case:
    number: str
    group: str
    group_label: str
    title: str
    slug: str
    priority: str
    status: str
    automated: bool
    steps: list[Step]
    expects: list[str]
    observed: str
    probe_id: str | None = None
    confidence: float | None = None
    skip_reason: str = ""
    note: str = ""

    def to_dict(self) -> dict:
        data = asdict(self)
        data["status_label"] = STATUS_LABELS[self.status]
        return data


@dataclass
class Result:
    probe: ProbeRun
    status: str
    summary: str
    outcome: str | None = None
    outcome_confidence: float | None = None
    blame: str | None = None
    blame_confidence: float | None = None

    def to_dict(self) -> dict:
        return {
            **self.probe.to_dict(),
            "status": self.status,
            "status_label": STATUS_LABELS[self.status],
            "summary": self.summary,
            "outcome": self.outcome,
            "outcome_label": OUTCOMES[self.outcome][0] if self.outcome else None,
            "outcome_confidence": self.outcome_confidence,
            "blame": self.blame,
            "blame_confidence": self.blame_confidence,
        }


@dataclass
class Conventions:
    """O que a exploração aprendeu sobre como esta tela responde."""

    success: list[str] = field(default_factory=list)  # linhas que confirmam o salvamento
    error_summary: list[str] = field(default_factory=list)  # linhas comuns às recusas
    aria_invalid: bool = False  # a tela marca o campo recusado com aria-invalid
    field_messages: dict[str, list[str]] = field(default_factory=dict)


def _quote(text: str, size: int = 90) -> str:
    return f"“{text if len(text) <= size else text[: size - 1] + '…'}”"


def evaluate(profile: Profile, probes: list[ProbeRun], oracle: dict | None) -> list[Result]:
    verdicts = (oracle or {}).get("probes", {})
    minimum = profile.thresholds.confidence
    labels = {f.element.id: f.label for f in profile.fields}
    results: list[Result] = []
    happy_ok: bool | None = None
    for probe in probes:
        observation = probe.observation or {}
        if "error" in observation:
            results.append(Result(probe, "error", f"A sondagem falhou: {observation['error']}"))
            continue
        if probe.kind == "maxlength":
            limit = profile.field(probe.field_id).element.maxlength
            ok = observation["length"] <= limit
            summary = (f"Com {observation['typed']} caracteres digitados, o campo ficou com "
                       f"{observation['length']}.")
            results.append(Result(probe, "ok" if ok else "divergence", summary))
            continue
        if probe.kind == "clear":
            action = next(a for a in profile.actions if a.element.id == probe.action_id)
            scope = [f for f in profile.fields_in_scope(action) if f.initial is not None]
            values = observation.get("values", {})
            wrong = [labels[f.element.id] for f in scope
                     if f.element.id in values and values[f.element.id] != f.initial]
            if not scope:
                results.append(Result(probe, "uncertain", "Não há campos no mesmo grupo da "
                                      "ação; não dá para saber o que ela limpa."))
                continue
            grupo = "da tela" if len(scope) == len(profile.fields) else "do grupo"
            summary = (f"Os {len(scope)} campos {grupo} voltaram ao valor inicial." if not wrong
                       else "Não voltaram ao valor inicial: " + ", ".join(wrong) + ".")
            results.append(Result(probe, "divergence" if wrong else "ok", summary))
            continue
        if probe.kind == "cancel":
            moved = observation.get("url_changed")
            summary = (f"Foi para {observation['path']}." if moved
                       else "Permaneceu na mesma tela.")
            results.append(Result(probe, "ok" if moved else "uncertain", summary))
            continue
        if probe.kind == "panel":
            dialog = observation.get("dialog")
            if dialog:
                summary = f"Abriu o diálogo {_quote(dialog['name'])}." if dialog["name"] else (
                    "Abriu um diálogo.")
                results.append(Result(probe, "ok", summary))
            elif observation.get("new_text"):
                results.append(Result(probe, "ok", "Mostrou: " + _quote(
                    observation["new_text"][0])))
            else:
                results.append(Result(probe, "uncertain", "Nada visível mudou."))
            continue
        verdict = verdicts.get(probe.id)
        if not verdict or "outcome" not in verdict:
            results.append(Result(probe, "uncertain", "Sem veredicto do oráculo."))
            continue
        outcome = verdict["outcome"]["value"]
        confidence = verdict["outcome"]["confidence"]
        blame = verdict.get("blame", {}).get("value")
        blame_confidence = verdict.get("blame", {}).get("confidence")
        shown = observation.get("new_text") or []
        said = f" ({_quote(shown[0])})" if shown else ""
        result = Result(probe, "ok", "", outcome, confidence, blame, blame_confidence)
        if probe.expect == "accept":
            if outcome == "accepted":
                result.summary = f"A tela aceitou{said}."
            elif outcome == "rejected":
                result.status = "divergence"
                result.summary = (f"A tela recusou a massa válida{said}. Revise a massa ou a "
                                  "regra.")
            elif outcome == "server_error":
                result.status = "divergence"
                result.summary = f"Erro do sistema ao salvar{said}."
            else:
                result.status = "uncertain"
                result.summary = "Nenhum retorno visível depois de salvar."
            happy_ok = outcome == "accepted"
        elif probe.expect == "reject":
            value = f" {_quote(str(probe.value), 40)}" if probe.value not in ("", False) else ""
            if outcome == "rejected":
                if blame in {probe.field_id, "general"} or blame is None:
                    result.summary = f"A tela recusou{said}."
                else:
                    result.status = "uncertain"
                    result.summary = (f"A tela recusou, mas a mensagem aponta para "
                                      f"{labels.get(blame, blame)}{said}.")
            elif outcome == "accepted":
                result.status = "divergence"
                result.summary = f"A tela aceitou{value}{said}."
                field_profile = profile.field(probe.field_id)
                if (probe.kind == "required" and field_profile.required_source == "jev"
                        and (field_profile.required_p or 0) < 0.8):
                    # A obrigatoriedade veio de um palpite do Jev, não do HTML: sem certeza,
                    # a discordância com a tela é uma pergunta, não um defeito.
                    result.status = "uncertain"
                    result.summary = (f"O Jev estimou {round(field_profile.required_p * 100)}% "
                                      f"de ser obrigatório, mas a tela aceitou vazio{said}. "
                                      "Confirme a regra.")
            elif outcome == "server_error":
                result.status = "divergence"
                result.summary = f"Erro do sistema em vez de validação{said}."
            else:
                result.status = "divergence"
                result.summary = "Nenhum retorno visível: o usuário não sabe o que houve."
        else:
            result.status = "observed"
            verb = {"accepted": "aceitou", "rejected": "recusou"}.get(outcome, "não confirmou")
            result.summary = f"A tela {verb}{said}."
        if result.status in {"ok", "divergence"} and confidence < minimum:
            result.status = "uncertain"
            result.summary += f" Confiança do Jev baixa ({round(confidence * 100)}%)."
        results.append(result)
    if happy_ok is False:
        # Sem o caminho feliz confirmado, uma recusa pode ter sido causada por outro campo.
        for result in results:
            if result.probe.expect == "reject" and result.status == "ok":
                result.status = "uncertain"
                result.summary += " Caminho feliz não confirmado."
    return results


def learn(profile: Profile, results: list[Result]) -> Conventions:
    conventions = Conventions()
    rejected = [r for r in results if r.outcome == "rejected" and r.probe.observation]
    happy = next((r for r in results if r.probe.kind == "happy" and r.outcome == "accepted"), None)
    counts = Counter(line for r in rejected for line in set(r.probe.observation["new_text"]))
    fields_per_line: dict[str, set] = {}
    for r in rejected:
        for line in r.probe.observation["new_text"]:
            fields_per_line.setdefault(line, set()).add(r.probe.field_id)
    if len(rejected) >= 2:
        # Resumo de erro: aparece na maioria das recusas e para campos diferentes
        # ("Data inválida." em dois campos de data não é resumo, é mensagem de campo).
        conventions.error_summary = [
            line for line, n in counts.most_common()
            if n >= max(2, 0.6 * len(rejected)) and len(fields_per_line[line]) >= 2
        ][:2]
    if happy:
        rejected_lines = set(counts)
        conventions.success = [
            line for line in happy.probe.observation["new_text"] if line not in rejected_lines
        ][:2]
    for r in rejected:
        field_id = r.probe.field_id
        if field_id and field_id in r.probe.observation.get("invalid", []):
            conventions.aria_invalid = True
        specific = [
            line for line in r.probe.observation["new_text"]
            if line not in conventions.error_summary
        ]
        if field_id and specific:
            conventions.field_messages.setdefault(field_id, specific[:2])
    return conventions


# --- Casos de teste ---------------------------------------------------------------------------


def _priority(group: str, profile: Profile, field_profile: FieldProfile | None = None) -> str:
    high = profile.criticality >= 1.5 or profile.personal_data >= 0.5
    if group == "happy":
        return "P1"
    if group == "required":
        return "P1" if high else "P2"
    if group == "format":
        sensitive = bool(field_profile and field_profile.kind
                         and data_kinds()[field_profile.kind].sensitive)
        return "P1" if high and sensitive else "P2"
    if group == "manual":
        return "P2"
    if group == "actions":
        return "P2"
    return "P3"


def _field_key(field_profile: FieldProfile, keys: dict[str, str]) -> str:
    return keys[field_profile.element.id]


def field_keys(profile: Profile) -> dict[str, str]:
    """Chave legível e única de cada campo, usada no plano e como argumento no código."""
    keys: dict[str, str] = {}
    used: set[str] = set()
    for f in profile.fields:
        base = slugify(f.label, "_")
        while len(base) > 32 and "_" in base:
            base = base.rsplit("_", 1)[0]
        if base[0].isdigit():
            base = f"campo_{base}"
        key, n = base, 2
        while key in used:
            key, n = f"{base}_{n}", n + 1
        used.add(key)
        keys[f.element.id] = key
    return keys


def _submit_steps(profile: Profile) -> list[Step]:
    submit = profile.submit
    return [Step("submit", f"Clicar em “{submit.label}”", submit.element.locator)]


def _reject_expectations(
    profile: Profile, result: Result, conventions: Conventions
) -> tuple[list[Step], list[str]]:
    """Asserções de recusa: o que a tela mostrou, ou a convenção aprendida quando ela aceitou."""
    field_profile = profile.field(result.probe.field_id)
    steps: list[Step] = []
    expects: list[str] = []
    observation = result.probe.observation or {}
    if result.status in {"ok", "observed"} and result.outcome == "rejected":
        for line in observation.get("new_text", [])[:3]:
            steps.append(Step("expect_text", f"mensagem {_quote(line)} visível", value=line))
            expects.append(f"mensagem {_quote(line)} visível")
        if field_profile and field_profile.element.id in observation.get("invalid", []):
            steps.append(Step("expect_invalid", f"“{field_profile.label}” marcado como inválido",
                              field_profile.element.locator))
            expects.append(f"“{field_profile.label}” marcado como inválido")
        return steps, expects
    # A tela não recusou (divergência): o teste exige o comportamento esperado, usando a
    # forma como esta tela sinaliza recusas nas outras sondagens.
    if conventions.aria_invalid and field_profile:
        steps.append(Step("expect_invalid", f"“{field_profile.label}” marcado como inválido",
                          field_profile.element.locator))
        expects.append(f"“{field_profile.label}” marcado como inválido")
    for line in conventions.error_summary[:1]:
        steps.append(Step("expect_text", f"mensagem {_quote(line)} visível", value=line))
        expects.append(f"mensagem {_quote(line)} visível")
    if not steps and conventions.success:
        pattern = stable_pattern(conventions.success[0])
        steps.append(Step("expect_no_text", "a confirmação de salvamento não aparece",
                          value=pattern))
        expects.append("a confirmação de salvamento não aparece")
    return steps, expects


def build_cases(profile: Profile, results: list[Result], conventions: Conventions,
                allow_submit: bool) -> list[Case]:
    keys = field_keys(profile)
    by_group: dict[str, list[Case]] = {key: [] for key, _ in GROUPS}
    group_labels = dict(GROUPS)
    submit = profile.submit

    def case(group: str, title: str, status: str, steps: list[Step], expects: list[str],
             observed: str, result: Result | None = None, field_profile=None,
             automated: bool = True, skip_reason: str = "", note: str = "") -> None:
        by_group[group].append(Case(
            number="", group=group, group_label=group_labels[group], title=title,
            slug=slugify(title), priority=_priority(group, profile, field_profile),
            status=status, automated=automated, steps=steps, expects=expects,
            observed=observed, probe_id=result.probe.id if result else None,
            confidence=result.outcome_confidence if result else None,
            skip_reason=skip_reason, note=note,
        ))

    for result in results:
        probe = result.probe
        field_profile = profile.field(probe.field_id) if probe.field_id else None
        if result.status == "error":
            group = {"happy": "happy", "required": "required", "format": "format",
                     "observe": "observe", "maxlength": "limits"}.get(probe.kind, "actions")
            case(group, probe.title, "error", [], [], result.summary, result, field_profile,
                 automated=False)
            continue
        skip = f"Revisar antes de ativar: {result.summary}" if result.status == "uncertain" else ""
        if probe.kind == "happy":
            steps = [Step("fill_valid", "Preencher todos os campos com a massa válida"),
                     *_submit_steps(profile)]
            expects = []
            for line in conventions.success[:1]:
                shown = _quote(re.sub(r"\d", "#", line))
                steps.append(Step("expect_text", f"mensagem {shown} visível",
                                  value=stable_pattern(line), extra={"regex": True}))
                expects.append(f"mensagem {shown} visível")
            if not expects:
                skip = skip or "Revisar: a exploração não identificou a confirmação de sucesso."
            case("happy", probe.title, result.status, steps, expects, result.summary, result,
                 skip_reason=skip)
        elif probe.kind in {"required", "format", "observe"}:
            key = _field_key(field_profile, keys)
            if probe.kind == "required":
                verb = "desmarcar" if field_profile.control == "check" else "deixar"
                how = {"select": "sem seleção", "check": ""}.get(field_profile.control, "vazio")
                text = f"{verb} “{field_profile.label}” {how}".strip()
            else:
                text = f"preencher “{field_profile.label}” com {_quote(str(probe.value), 60)}"
            steps = [
                Step("fill_valid", f"Preencher os demais campos com a massa válida; {text}",
                     value={key: probe.value}),
                *_submit_steps(profile),
            ]
            more, expects = _reject_expectations(profile, result, conventions)
            if probe.kind == "observe" and result.outcome == "accepted":
                more, expects = [], []
                for line in (probe.observation or {}).get("new_text", [])[:1]:
                    shown = _quote(re.sub(r"\d", "#", line))
                    more.append(Step("expect_text", f"mensagem {shown} visível",
                                     value=stable_pattern(line), extra={"regex": True}))
                    expects.append(f"mensagem {shown} visível")
            steps += more
            note = ""
            if result.status == "divergence":
                note = (f"Na exploração: {result.summary} O teste exige a recusa e falha até a "
                        "tela ser corrigida.")
            elif probe.kind == "observe":
                note = ("Comportamento registrado como está (teste de caracterização). "
                        "Confirme com o PO se é o esperado.")
            if not more:
                skip = skip or "Revisar: sem forma de verificar a recusa nesta tela."
            group = {"required": "required", "format": "format", "observe": "observe"}[
                probe.kind]
            case(group, probe.title, result.status, steps, expects, result.summary, result,
                 field_profile, skip_reason=skip, note=note)
        elif probe.kind == "maxlength":
            limit = field_profile.element.maxlength
            steps = [
                Step("fill", f"Digitar {limit + 10} caracteres em “{field_profile.label}”",
                     field_profile.element.locator, "x" * (limit + 10)),
                Step("expect_value_regex", f"o campo fica com {limit} caracteres",
                     field_profile.element.locator, f"^x{{{limit}}}$"),
            ]
            case("limits", probe.title, result.status, steps,
                 [f"o campo fica com {limit} caracteres"], result.summary, result, field_profile)
        elif probe.kind == "clear":
            action = next(a for a in profile.actions if a.element.id == probe.action_id)
            toggles = probe.value if isinstance(probe.value, dict) else {}
            fill = "Preencher todos os campos com a massa válida"
            if toggles:
                marked = ", ".join(f"“{profile.field(i).label}”" for i in toggles)
                fill += f"; marcar {marked}"
            steps = [Step("fill_valid", fill,
                          value={keys[i]: True for i in toggles} or None),
                     Step("click", f"Clicar em “{action.label}”", action.element.locator)]
            expects = []
            for f in profile.fields_in_scope(action):
                if f.initial is None:
                    continue
                if f.control in {"check", "radio"}:
                    text = f"“{f.label}” {'marcado' if f.initial else 'desmarcado'}"
                elif f.initial == "":
                    empty = "sem seleção" if f.control == "select" else "vazio"
                    text = f"“{f.label}” {empty}"
                else:
                    text = f"“{f.label}” com {_quote(str(f.initial), 40)}"
                steps.append(Step("expect_value", text, f.element.locator, f.initial,
                                  {"control": f.control}))
                expects.append(text)
            case("actions", probe.title, result.status, steps, expects, result.summary, result,
                 skip_reason=skip)
        elif probe.kind == "cancel":
            action = next(a for a in profile.actions if a.element.id == probe.action_id)
            path = (probe.observation or {}).get("path")
            steps = [Step("click", f"Clicar em “{action.label}”", action.element.locator)]
            expects = []
            if (probe.observation or {}).get("url_changed") and path:
                steps.append(Step("expect_url", f"a tela vai para {path}",
                                  value=regex_escape(path) + "$"))
                expects.append(f"a tela vai para {path}")
            case("actions", probe.title, result.status, steps, expects, result.summary, result,
                 skip_reason=skip or ("" if expects else "Revisar: não saiu da tela."))
        elif probe.kind == "panel":
            action = next(a for a in profile.actions if a.element.id == probe.action_id)
            dialog = (probe.observation or {}).get("dialog")
            steps = [Step("click", f"Clicar em “{action.label}”", action.element.locator)]
            expects = []
            if dialog:
                name = dialog.get("name") or ""
                text = f"diálogo {_quote(name)} visível" if name else "um diálogo visível"
                steps.append(Step("expect_dialog", text, value=name))
                expects.append(text)
            elif (probe.observation or {}).get("new_text"):
                line = probe.observation["new_text"][0]
                steps.append(Step("expect_text", f"texto {_quote(line)} visível", value=line))
                expects.append(f"texto {_quote(line)} visível")
            case("actions", probe.title, result.status, steps, expects, result.summary, result,
                 skip_reason=skip)

    links = [a for a in profile.actions if a.role == "navigate" and a.element.href
             and a.element.href_attr]
    if links:
        checks = [Step("expect_attr", f"“{a.label}” aponta para {a.element.href_attr}",
                       a.element.locator, a.element.href_attr, {"attr": "href"}) for a in links]
        steps = [Step("note", "Conferir o destino dos links do menu, sem clicar"), *checks]
        case("navigation", "Links de navegação apontam para as telas certas", "ok", steps,
             [s.text for s in checks], "Verificado pelo DOM, sem clicar.")

    for action in profile.actions:
        if not action.risky:
            continue
        expect_text = MANUAL_EXPECTS.get(action.role, "o efeito esperado acontece")
        case("manual", f"{ACTION_ROLES[action.role].label}: “{action.label}”", "manual",
             [Step("click", f"Em ambiente controlado, clicar em “{action.label}”",
                   action.element.locator)],
             [expect_text], f"Não clicado na exploração ({action.risky_reason}).",
             automated=False)

    if not allow_submit or submit is None:
        reason = ("Envio desligado nesta exploração." if not allow_submit
                  else profile.submit_note or "Nenhuma ação de salvar identificada.")
        for f in profile.fields:
            if f.required:
                case("required", f"Recusar sem preencher {f.label}", "not_run", [], [],
                     reason, field_profile=f, automated=False)

    cases: list[Case] = []
    number = 0
    for key, _ in GROUPS:
        items = by_group[key]
        if not items:
            continue
        number += 1
        for index, item in enumerate(items, start=1):
            item.number = f"{number}.{index}"
            cases.append(item)
    return cases


def findings(profile: Profile, results: list[Result], cases: list[Case]) -> dict:
    divergences = [c for c in cases if c.status == "divergence"]
    uncertain = [c for c in cases if c.status == "uncertain"]
    observed = [c for c in cases if c.status == "observed"]
    a11y = []
    orphans = [f for f in profile.fields if not f.element.label and f.element.visual_label]
    for f in orphans:
        where = f"#{f.element.html_id}" if f.element.html_id else f.element.id
        a11y.append(
            f"“{strip_label(f.element.visual_label)}” ({where}): o texto está num `<label>` que "
            "não rotula o campo (o rótulo vai para outro elemento dentro dele, como um "
            "`<output>`); leitores de tela anunciam o campo sem nome."
        )
    unlabeled = [f.label for f in profile.fields
                 if not f.element.label and not f.element.visual_label]
    if unlabeled:
        a11y.append(f"Campos sem rótulo acessível: {', '.join(unlabeled)}.")
    visual_only = [f.label for f in profile.fields
                   if f.required and f.required_source == "jev" and f.control != "radio"]
    if visual_only:
        a11y.append(
            f"{len(visual_only)} campos obrigatórios só pelo “*” do rótulo, sem `required` nem "
            f"`aria-required`: leitores de tela não anunciam a obrigatoriedade "
            f"({', '.join(visual_only)})."
        )
    return {
        "divergences": [{"number": c.number, "title": c.title, "summary": c.observed}
                        for c in divergences],
        "uncertain": [{"number": c.number, "title": c.title, "summary": c.observed}
                      for c in uncertain] + (
            [{"number": "", "title": "Sondagens que salvam não rodaram",
              "summary": profile.submit_note}]
            if profile.submit is None and profile.submit_note else []),
        "observed": [{"number": c.number, "title": c.title, "summary": c.observed}
                     for c in observed],
        "accessibility": a11y,
        "skipped_elements": profile.skipped,
    }


# --- Plano em Markdown -----------------------------------------------------------------------


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{round(value * 100)}%"


def plan_markdown(report: dict) -> str:
    """Plano no formato do planner do Playwright (seed, scenarios, steps, expect)."""
    screen = report["screen"]
    profile = report["profile"]
    meta = report["meta"]
    slug = report["slug"]
    lines = [
        f"# {screen['name']} — plano de testes",
        "",
        f"> Gerado pelo Screen Scout em {meta['generated_at']} a partir de <{screen['url']}>.",
        f"> Exploração: {meta['probes']} sondagens em {meta['total_s']} s · "
        f"{meta['jev_requests']} requisições ao Jev · {meta['decisions']} decisões · "
        f"{meta['cost_label']}.",
        "",
        "## Application Overview",
        "",
    ]
    fields = profile["fields"]
    actions = profile["actions"]
    overview = (
        f"Tela de **{profile['kind_label'].lower()}** (Jev {_pct(profile['kind_confidence'])}) "
        f"com {len(fields)} campos e {len(actions)} ações. Criticidade "
        f"**{profile['criticality_label'].lower()}**."
    )
    if profile["personal_data"] >= 0.5:
        overview += " Coleta dados pessoais (LGPD): use apenas massa sintética."
    lines += [overview, ""]
    submit = next((a for a in actions if a["id"] == profile["submit"]), None)
    if submit:
        lines.append(f"Ação de salvar: “{submit['label']}”.")
    elif profile.get("submit_note"):
        lines.append(profile["submit_note"])
    risky = [a["label"] for a in actions if a["risky"]]
    if risky:
        lines.append("Ações de risco não clicadas: " + ", ".join(f"“{r}”" for r in risky) + ".")
    lines += ["", "### Massa válida", "", "| Campo | Tipo | Obrigatório | Valor |",
              "|---|---|---|---|"]
    for f in fields:
        kind = f["kind_label"] or {"select": "Lista", "check": "Caixa de seleção",
                                   "radio": "Opções"}.get(f["control"], "—")
        if f["kind_source"] == "jev" and f["kind_confidence"] is not None:
            kind += f" (Jev {_pct(f['kind_confidence'])})"
        required = "não"
        if f["required"]:
            required = "sim (HTML)" if f["required_source"] == "dom" else (
                f"sim (Jev {_pct(f['required_p'])})")
        value = f["valid"]
        shown = "—" if value is None else ("marcado" if value is True else f"`{value}`")
        lines.append(f"| {f['label']} | {kind} | {required} | {shown} |")
    found = report["findings"]
    if found["divergences"]:
        lines += ["", "### Divergências encontradas", ""]
        lines += [f"- ❌ **{d['number']} {d['title']}** — {d['summary']}"
                  for d in found["divergences"]]
    if found["uncertain"]:
        lines += ["", "### Para revisar", ""]
        lines += [f"- ⚠️ **{d['number']} {d['title']}** — {d['summary']}"
                  for d in found["uncertain"]]
    if found["accessibility"]:
        lines += ["", "### Acessibilidade", ""]
        lines += [f"- {item}" for item in found["accessibility"]]
    lines += ["", "## Test Scenarios", ""]
    current = None
    for case in report["cases"]:
        if case["group"] != current:
            current = case["group"]
            group_number = case["number"].split(".")[0]
            lines += [f"### {group_number}. {case['group_label']}", "",
                      "**Seed:** `tests/seed.spec.ts`", ""]
        lines += [
            f"#### {case['number']}. {case['slug']}",
            "",
            f"**File:** `tests/{slug}/{case['slug']}.spec.ts`",
            "",
            f"**Título:** {case['title']} · **Prioridade:** {case['priority']} · "
            f"**Exploração:** {case['status_label']} — {case['observed']}",
            "",
        ]
        if case["note"]:
            lines += [f"> {case['note']}", ""]
        if case["steps"]:
            lines.append("**Steps:**")
            number = 0
            for step in case["steps"]:
                if step["op"].startswith("expect"):
                    lines.append(f"    - expect: {step['text']}")
                else:
                    number += 1
                    lines.append(f"  {number}. {step['text']}")
            lines.append("")
        elif case["expects"]:
            lines += ["**Expect:**", *[f"    - expect: {e}" for e in case["expects"]], ""]
    return "\n".join(lines).rstrip() + "\n"


def screen_name(profile: Profile) -> str:
    screen = profile.screen
    return screen.headings[0] if screen.headings else (screen.title or "Tela")


def refine(results: list[Result], conventions: Conventions) -> None:
    """Cita a mensagem do campo ("Informe o CPF.") no lugar do resumo genérico da tela."""
    generic = set(conventions.error_summary)
    for result in results:
        shown = (result.probe.observation or {}).get("new_text") or []
        if result.outcome != "rejected" or not shown or shown[0] not in generic:
            continue
        specific = next((line for line in shown if line not in generic), None)
        if specific:
            result.summary = result.summary.replace(_quote(shown[0]), _quote(specific), 1)


def build_report(profile: Profile, probes: list[ProbeRun], oracle: dict | None,
                 allow_submit: bool, meta: dict) -> dict:
    results = evaluate(profile, probes, oracle)
    conventions = learn(profile, results)
    refine(results, conventions)
    cases = build_cases(profile, results, conventions, allow_submit)
    name = screen_name(profile)
    report = {
        "screen": {
            "name": name,
            "title": profile.screen.title,
            "url": profile.screen.url,
            "width": profile.screen.width,
            "height": profile.screen.height,
            "elements": [
                {"id": e.id, "kind": e.kind, "name": e.name, "box": e.box, "tag": e.tag}
                for e in profile.screen.elements
            ],
        },
        "slug": slugify(name),
        "profile": profile.to_dict(),
        "field_keys": field_keys(profile),
        "results": [r.to_dict() for r in results],
        "conventions": asdict(conventions),
        "cases": [c.to_dict() for c in cases],
        "allow_submit": allow_submit,
        "meta": {"generated_at": datetime.now().strftime("%d/%m/%Y %H:%M"), **meta},
    }
    report["findings"] = findings(profile, results, cases)
    return report
