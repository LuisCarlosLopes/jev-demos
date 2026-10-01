"""Sondagens: exploração da tela com Playwright, em paralelo e sem LLM.

Cada sondagem abre um contexto isolado do mesmo navegador, preenche a massa válida trocando
um único valor (um fator por vez), aciona a tela e registra o que mudou: texto novo, campos
marcados como inválidos, URL, diálogos do navegador e erros HTTP. Quem interpreta o que foi
observado é o Jev, numa única requisição depois que todas terminam (o oráculo).

Ações de risco (excluir, enviar, sair, exportar) nunca são clicadas.
"""

import asyncio
import re
import time
from dataclasses import asdict, dataclass

from playwright.async_api import Browser, BrowserContext, Page

from .capture import SETTLE_SCRIPT, cache_call_stack, resolve, settle, visible_lines
from .catalog import data_kinds
from .profile import ActionProfile, FieldProfile, Profile

VIEWPORT = {"width": 1280, "height": 900}

# Estado de todos os campos marcados, lido numa única ida ao navegador.
STATE_SCRIPT = """
() => {
  const out = {};
  for (const el of document.querySelectorAll("[data-scout-id]")) {
    out[el.dataset.scoutId] = {
      value: el.type === "checkbox" || el.type === "radio" ? el.checked : el.value,
      invalid: el.getAttribute("aria-invalid") === "true"
        || (el.matches(":invalid") && el.closest("form:not([novalidate])") !== null),
    };
  }
  const dialog = [...document.querySelectorAll("dialog[open], [role=dialog], [role=alertdialog]")]
    .find((d) => d.checkVisibility ? d.checkVisibility() : d.offsetParent !== null);
  let dialogName = null;
  if (dialog) {
    const by = dialog.getAttribute("aria-labelledby");
    dialogName = (by && document.getElementById(by)?.textContent)
      || dialog.getAttribute("aria-label") || dialog.querySelector("h1,h2,h3")?.textContent || "";
    dialogName = dialogName.replace(/\\s+/g, " ").trim();
  }
  return { fields: out, dialog: dialog ? { name: dialogName } : null };
}
"""


@dataclass
class ProbeRun:
    id: str
    kind: str  # happy | required | format | observe | maxlength | clear | cancel | panel
    title: str
    expect: str  # accept | reject | observe | check
    field_id: str | None = None
    action_id: str | None = None
    value: str | bool | None = None
    needs_oracle: bool = False
    blame: bool = False
    observation: dict | None = None
    ms: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def _scenario(template: str, label: str) -> str:
    """'{campo} incompleto' → 'CPF incompleto' / 'celular incompleto' (siglas ficam)."""
    text = template.replace("{campo}", label)
    return text[:1].lower() + text[1:] if text[1:2].islower() else text


def plan_probes(profile: Profile, allow_submit: bool, today=None) -> list[ProbeRun]:
    kinds = data_kinds(today)
    probes: list[ProbeRun] = []

    def add(**kwargs) -> None:
        probes.append(ProbeRun(id=f"p{len(probes)}", **kwargs))

    submit = profile.submit
    if submit and allow_submit:
        add(kind="happy", title="Salvar com todos os campos válidos", expect="accept",
            needs_oracle=True)
        for field in profile.fields:
            element = field.element
            if field.required:
                empty = _empty_value(field)
                if empty is not None:
                    verb = {"select": "sem selecionar", "check": "sem marcar"}.get(
                        field.control, "sem preencher"
                    )
                    add(kind="required", title=f"Recusar {verb} {field.label}", expect="reject",
                        field_id=element.id, value=empty, needs_oracle=True, blame=True)
            if field.control != "fill" or not field.kind or element.type in {"date"}:
                continue
            for probe in kinds[field.kind].invalid:
                if element.type == "number" and not re.fullmatch(r"-?[\d.,]+", probe.value):
                    continue  # o navegador não deixa digitar letras num input numérico
                if element.maxlength and len(probe.value) > element.maxlength:
                    continue
                title = _scenario(probe.title, field.label)
                add(
                    kind="format" if probe.expect == "reject" else "observe",
                    title=f"Recusar {title}" if probe.expect == "reject"
                    else f"Comportamento com {title}",
                    expect=probe.expect,
                    field_id=element.id,
                    value=probe.value,
                    needs_oracle=True,
                    blame=True,
                )
    for field in profile.fields:
        maxlength = field.element.maxlength
        if field.control == "fill" and maxlength and maxlength <= 5000:
            add(kind="maxlength", title=f"{field.label} limitado a {maxlength} caracteres",
                expect="check", field_id=field.element.id, value="x" * (maxlength + 10))
    for action in profile.actions:
        if action.risky or action.uncertain:
            continue
        name = action.label
        if action.role == "clear":
            # Marca até três caixas opcionais do grupo, para o "Limpar" ter o que desfazer.
            toggles = {f.element.id: True for f in profile.fields_in_scope(action)
                       if f.control == "check" and not f.initial and f.valid is None}
            add(kind="clear", title=f"“{name}” limpa o formulário", expect="check",
                action_id=action.element.id, value=dict(list(toggles.items())[:2]) or None)
        elif action.role == "cancel_back":
            add(kind="cancel", title=f"“{name}” sai sem salvar", expect="check",
                action_id=action.element.id)
        elif action.role == "open_panel":
            add(kind="panel", title=f"“{name}” abre o painel", expect="check",
                action_id=action.element.id)
    return probes


def _empty_value(field: FieldProfile) -> str | bool | None:
    if field.control == "select":
        has_empty = any(o["value"] == "" for o in field.element.options)
        return "" if has_empty else None
    if field.control == "check":
        return False
    if field.control in {"radio", "file"}:
        return None  # radio não volta a "nenhum" pela interface; upload fica de fora
    return ""


class Signals:
    """Sinais que a página não mostra no texto: diálogos do navegador, HTTP e console."""

    def __init__(self, page: Page):
        self.dialogs: list[str] = []
        self.http_errors: list[str] = []
        self.console_errors: list[str] = []
        page.on("dialog", self._dialog)
        page.on("response", self._response)
        page.on("console", self._console)
        page.on("pageerror", lambda error: self.console_errors.append(str(error)[:200]))

    async def _dialog(self, dialog) -> None:
        self.dialogs.append(dialog.message[:200])
        await dialog.dismiss()

    def _response(self, response) -> None:
        kind = response.request.resource_type
        if response.status >= 400 and kind in {"fetch", "xhr", "document"}:
            path = re.sub(r"^[a-z]+://[^/]+", "", response.url)[:120]
            self.http_errors.append(f"HTTP {response.status} {path}")

    def _console(self, message) -> None:
        if message.type == "error":
            self.console_errors.append(message.text[:200])


TAG_SCRIPT = """
(pairs) => {
  for (const [id, path] of pairs) {
    const el = path && document.querySelector(path);
    if (el) el.setAttribute("data-scout-id", id);
  }
}
"""


async def _tag(page: Page, profile: Profile) -> None:
    """Marca os campos numa única ida ao navegador, para ler o estado deles depois."""
    pairs = [[f.element.id, f.element.path] for f in profile.fields]
    await page.evaluate(TAG_SCRIPT, pairs)


async def fill_form(page: Page, profile: Profile, override: tuple[str, object] | None = None):
    for field in profile.fields:
        value = field.valid
        if override and override[0] == field.element.id:
            value = override[1]
        await set_value(page, field, value)


async def set_value(page: Page, field: FieldProfile, value) -> None:
    if value is None or field.control == "file":
        return
    locator = resolve(page, field.element.locator)
    if field.control == "select":
        await locator.select_option(value=str(value))
    elif field.control in {"check", "radio"}:
        await (locator.check() if value else locator.uncheck())
    else:
        await locator.fill(str(value))


async def _state(page: Page) -> dict:
    try:
        return await page.evaluate(STATE_SCRIPT)
    except Exception:  # noqa: BLE001 - página em navegação
        return {"fields": {}, "dialog": None}


def _path(url: str) -> str:
    return re.sub(r"^[a-z]+://[^/]+", "", url) or "/"


async def _observe(page: Page, before: list[str], signals: Signals, start_url: str,
                   settled: bool, filled: dict) -> dict:
    after = await visible_lines(page)
    seen = set(before)
    state = await _state(page)
    fields = state["fields"]
    cleared = bool(filled) and all(
        not fields.get(fid, {}).get("value") for fid, value in filled.items() if value
    ) and bool(fields)
    return {
        "new_text": [line for line in after if line not in seen][:10],
        "invalid": [fid for fid, info in fields.items() if info["invalid"]],
        "url": page.url,
        "url_changed": page.url.split("#")[0] != start_url.split("#")[0],
        "path": _path(page.url),
        "dialog": state["dialog"],
        "browser_dialogs": signals.dialogs[:3],
        "http_errors": signals.http_errors[:5],
        "console_errors": signals.console_errors[:5],
        "settled": settled,
        "cleared": cleared,
        "values": {fid: info["value"] for fid, info in fields.items()},
    }


def _action(profile: Profile, action_id: str) -> ActionProfile:
    return next(a for a in profile.actions if a.element.id == action_id)


async def _run(context: BrowserContext, url: str, profile: Profile, probe: ProbeRun) -> dict:
    page = await context.new_page()
    try:
        signals = Signals(page)
        await page.goto(url, wait_until="load")
        # Numa SPA o `load` vem antes da tela: espera o primeiro campo (ou o botão) aparecer.
        anchor = next((f.element for f in profile.fields), None) or (
            profile.submit.element if profile.submit else None)
        if anchor is not None:
            await resolve(page, anchor.locator).wait_for(state="visible", timeout=15000)
        await settle(page)
        await _tag(page, profile)
        if probe.kind == "maxlength":
            field = profile.field(probe.field_id)
            locator = resolve(page, field.element.locator)
            await locator.fill(str(probe.value))
            value = await locator.input_value()
            return {"typed": len(str(probe.value)), "length": len(value)}
        filled: dict = {}
        if probe.kind in {"happy", "required", "format", "observe", "clear"}:
            override = (probe.field_id, probe.value) if probe.field_id else None
            await fill_form(page, profile, override)
        if probe.kind == "clear" and isinstance(probe.value, dict):
            for field_id in probe.value:
                field = profile.field(field_id)
                try:
                    await resolve(page, field.element.locator).check(timeout=1500)
                except Exception:  # noqa: BLE001 - a lista pode ter se redesenhado
                    pass
            filled = {
                f.element.id: (probe.value if f.element.id == probe.field_id else f.valid)
                for f in profile.fields
                if f.control == "fill"
            }
        target = profile.submit if probe.action_id is None else _action(profile, probe.action_id)
        before = await visible_lines(page)
        start_url = page.url
        await resolve(page, target.element.locator).click()
        settled = await settle(page)
        return await _observe(page, before, signals, start_url, settled, filled)
    finally:
        await page.close()


async def run_probes(browser: Browser, url: str, profile: Profile, probes: list[ProbeRun],
                     concurrency: int = 6, on_done=None, storage_state: str | None = None) -> None:
    """Um contexto por worker, página nova por sondagem.

    A página nova zera o DOM e o JavaScript da tela; o contexto reaproveitado mantém o cache
    HTTP e os cookies, o que pesa numa SPA de vários MB. localStorage também persiste entre as
    sondagens de um mesmo worker.
    """
    queue: asyncio.Queue[ProbeRun] = asyncio.Queue()
    for probe in probes:
        queue.put_nowait(probe)

    async def worker() -> None:
        cache_call_stack()
        context = await browser.new_context(locale="pt-BR", viewport=VIEWPORT,
                                            storage_state=storage_state)
        # 5 s por ação: um elemento que mudou de rótulo não trava a sondagem por 30 s.
        context.set_default_timeout(5000)
        try:
            await context.add_init_script(SETTLE_SCRIPT)
            while not queue.empty():
                probe = queue.get_nowait()
                started = time.perf_counter()
                try:
                    probe.observation = await asyncio.wait_for(
                        _run(context, url, profile, probe), timeout=30
                    )
                except Exception as error:  # noqa: BLE001 - uma sondagem não derruba as outras
                    text = str(error)
                    probe.observation = {
                        "error": text.splitlines()[0][:200] if text else type(error).__name__
                    }
                probe.ms = round((time.perf_counter() - started) * 1000, 1)
                if on_done:
                    on_done(probe)
        finally:
            await context.close()

    await asyncio.gather(*(worker() for _ in range(min(concurrency, len(probes)) or 1)))


def oracle_inputs(profile: Profile, probes: list[ProbeRun]) -> list[dict]:
    """Descrição de cada sondagem para o oráculo: a ação feita e o que foi observado."""
    labels = {f.element.id: f.element.label or f.label for f in profile.fields}
    submit = profile.submit.label if profile.submit else "?"
    items = []
    for probe in probes:
        observation = probe.observation or {}
        if not probe.needs_oracle or "error" in observation:
            continue
        if probe.kind == "happy":
            action = f"Filled every field with valid data and clicked '{submit}'."
        elif probe.kind == "required":
            field = profile.field(probe.field_id)
            how = {"select": "left unselected", "check": "left unticked"}.get(
                field.control, "left empty"
            )
            action = (f"Filled every field with valid data, except '{labels[probe.field_id]}', "
                      f"which was {how}, and clicked '{submit}'.")
        else:
            action = (f"Filled every field with valid data, except '{labels[probe.field_id]}' "
                      f"= '{probe.value}', and clicked '{submit}'.")
        observed = {
            "new_text": observation.get("new_text", []),
            "fields_marked_invalid": [labels.get(i, i) for i in observation.get("invalid", [])],
            "form_was_cleared": observation.get("cleared", False),
            "navigated_to": observation.get("path") if observation.get("url_changed") else None,
            "browser_dialog": (observation.get("browser_dialogs") or [None])[0],
            "http_errors": observation.get("http_errors", []),
        }
        items.append({"id": probe.id, "action": action, "observed": observed,
                      "blame": probe.blame})
    return items
