"""Captura determinística da tela com Playwright: inventário, localizadores e observação.

Nada aqui chama o Jev. O inventário sai de um único `evaluate` no navegador; os localizadores
são verificados com o próprio Playwright (cada um precisa resolver exatamente o elemento
capturado), e o mesmo formato é usado nas sondagens e no código gerado.
"""

import asyncio
import inspect
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from playwright.async_api import Locator, Page

# Injetado em cada página antes de qualquer script dela: marca a última mutação do DOM e conta
# requisições em andamento, para saber quando a tela "assentou" depois de um clique.
SETTLE_SCRIPT = """
(() => {
  if (window.__scout) return;
  window.__scout = { mut: performance.now(), pending: 0 };
  const touch = () => { window.__scout.mut = performance.now(); };
  const start = () => {
    new MutationObserver(touch).observe(document, {
      subtree: true, childList: true, attributes: true, characterData: true,
    });
  };
  start();
  const originalFetch = window.fetch;
  if (originalFetch) {
    window.fetch = function (...args) {
      window.__scout.pending += 1;
      return originalFetch.apply(this, args).finally(() => {
        window.__scout.pending -= 1;
        touch();
      });
    };
  }
  const send = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function (...args) {
    window.__scout.pending += 1;
    this.addEventListener("loadend", () => { window.__scout.pending -= 1; touch(); });
    return send.apply(this, args);
  };
})();
"""

INVENTORY_SCRIPT = """
() => {
  const norm = (s) => (s || "").replace(/\\s+/g, " ").trim();
  const shown = (el) => {
    if (el.closest("[hidden], [aria-hidden='true']")) return false;
    if (el.checkVisibility && !el.checkVisibility({ visibilityProperty: true })) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const textWithout = (node) => {
    const clone = node.cloneNode(true);
    // <output> dentro do rótulo mostra um valor ("60%"), não faz parte do nome.
    clone.querySelectorAll("input, select, textarea, button, output")
      .forEach((n) => n.remove());
    return norm(clone.textContent);
  };
  const byIds = (ids) =>
    norm((ids || "").split(/\\s+/).filter(Boolean)
      .map((id) => document.getElementById(id)?.textContent || "").join(" "));
  const labelOf = (el) => {
    const labelled = byIds(el.getAttribute("aria-labelledby"));
    if (labelled) return labelled;
    const aria = norm(el.getAttribute("aria-label"));
    if (aria) return aria;
    if (el.labels && el.labels.length) return norm([...el.labels].map(textWithout).join(" "));
    return norm(el.getAttribute("title"));
  };
  const roleOf = (el) => {
    const explicit = norm(el.getAttribute("role")).split(" ")[0];
    if (explicit) return explicit;
    const tag = el.tagName.toLowerCase();
    if (tag === "a") return "link";
    if (tag === "button" || tag === "summary") return "button";
    if (tag === "select") return el.multiple || el.size > 1 ? "listbox" : "combobox";
    if (tag === "textarea") return "textbox";
    const type = (el.getAttribute("type") || "text").toLowerCase();
    return {
      button: "button", submit: "button", reset: "button", image: "button",
      checkbox: "checkbox", radio: "radio", range: "slider", number: "spinbutton",
      search: "searchbox",
    }[type] || "textbox";
  };
  const sectionOf = (el) => {
    const legend = el.closest("fieldset")?.querySelector(":scope > legend");
    if (legend) return norm(legend.textContent);
    const region = el.closest("dialog, nav, header, footer, aside, section, [role=region], form");
    if (!region) return "";
    const named = norm(region.getAttribute("aria-label"))
      || byIds(region.getAttribute("aria-labelledby"));
    const tag = region.tagName.toLowerCase();
    const kind = { nav: "navigation", header: "header", footer: "footer", aside: "sidebar",
                   dialog: "dialog" }[tag];
    if (kind) return named ? `${kind}: ${named}` : kind;
    if (named) return named;
    const heading = region.querySelector("h1, h2, h3, h4");
    return heading ? norm(heading.textContent) : "";
  };
  const helpOf = (el) => {
    let text = byIds(el.getAttribute("aria-describedby"));
    const box = el.parentElement;
    // Um <label> que envolve o campo é o próprio rótulo, não texto de ajuda.
    if (!text && box && box.tagName !== "LABEL"
        && box.querySelectorAll("input, select, textarea").length === 1) {
      const clone = box.cloneNode(true);
      clone.querySelectorAll("label, input, select, textarea").forEach((n) => n.remove());
      text = norm(clone.textContent);
    }
    return text.slice(0, 120);
  };
  const num = (v) => (v === null || v === "" || isNaN(Number(v)) ? null : Number(v));
  // Caminho CSS único no DOM inicial: só para a exploração reencontrar o elemento numa página
  // nova com uma única ida ao navegador. Os testes gerados usam os localizadores verificados.
  const pathOf = (el) => {
    const parts = [];
    for (let node = el; node && node.nodeType === 1 && node !== document.documentElement;
         node = node.parentElement) {
      if (node.id && document.querySelectorAll(`#${CSS.escape(node.id)}`).length === 1) {
        parts.unshift(`#${CSS.escape(node.id)}`);
        break;
      }
      const index = [...node.parentElement.children].indexOf(node) + 1;
      parts.unshift(`${node.tagName.toLowerCase()}:nth-child(${index})`);
    }
    return parts.join(" > ");
  };

  // Grupos da tela (formulário, seção, barra lateral…): definem o alcance de um "Limpar".
  const SCOPES = "form, fieldset, [role=search], [role=form], [role=group], dialog, aside, "
    + "section, [role=region], [role=dialog]";
  const scopeIds = new Map();
  const scopesOf = (el) => {
    const out = [];
    for (let c = el.parentElement?.closest(SCOPES); c; c = c.parentElement?.closest(SCOPES)) {
      if (!scopeIds.has(c)) scopeIds.set(c, `s${scopeIds.size}`);
      out.push(scopeIds.get(c));
    }
    return out;
  };

  const selector = [
    "input:not([type=hidden])", "select", "textarea", "button", "a[href]", "summary",
    "[role=button]", "[role=link]", "[role=tab]", "[role=checkbox]", "[role=radio]",
    "[role=switch]", "[role=combobox]", "[role=textbox]", "[role=menuitem]",
  ].join(", ");
  const elements = [];
  let index = 0;
  for (const el of document.querySelectorAll(selector)) {
    if (!shown(el)) continue;
    const id = `e${index++}`;
    el.setAttribute("data-scout-id", id);
    const tag = el.tagName.toLowerCase();
    const type = tag === "input" ? (el.getAttribute("type") || "text").toLowerCase()
      : tag === "button" ? (el.getAttribute("type") || "submit").toLowerCase() : "";
    const role = roleOf(el);
    const isField = ["input", "select", "textarea"].includes(tag)
      && !["button", "submit", "reset", "image"].includes(type)
      || ["textbox", "combobox", "checkbox", "radio", "switch", "searchbox"].includes(role)
        && !["button", "a"].includes(tag);
    const rect = el.getBoundingClientRect();
    const label = isField ? labelOf(el) : "";
    // Texto de um <label> que envolve o campo mas não o rotula (o rótulo foi para outro
    // elemento, como um <output> antes do input): visível para quem vê, mudo para leitor de tela.
    const wrapping = isField && !label ? el.closest("label") : null;
    const visualLabel = wrapping ? textWithout(wrapping) : "";
    const name = isField
      ? label || norm(el.getAttribute("placeholder")) || visualLabel
      : norm(el.getAttribute("aria-label")) || norm(el.innerText) || norm(el.value)
        || norm(el.getAttribute("title"));
    let href = null;
    let hrefAttr = null;
    let sameOrigin = null;
    if (tag === "a") {
      href = el.href;
      hrefAttr = el.getAttribute("href");
      try {
        sameOrigin = new URL(el.href).origin === location.origin;
      } catch {
        sameOrigin = false;
      }
    }
    elements.push({
      id, tag, type, role, name, label,
      kind: isField ? "field" : "action",
      placeholder: norm(el.getAttribute("placeholder")),
      required: el.required === true || el.getAttribute("aria-required") === "true",
      maxlength: el.maxLength > 0 ? el.maxLength : null,
      minlength: el.minLength > 0 ? el.minLength : null,
      min: num(el.getAttribute("min")),
      max: num(el.getAttribute("max")),
      pattern: el.getAttribute("pattern") || "",
      inputmode: el.getAttribute("inputmode") || "",
      autocomplete: el.getAttribute("autocomplete") || "",
      group: type === "radio" ? el.name || "" : "",
      options: tag === "select"
        ? [...el.options].slice(0, 30).map((o) => ({ value: o.value, label: norm(o.text) }))
        : [],
      checked: type === "checkbox" || type === "radio" ? el.checked : null,
      value: isField && type !== "checkbox" && type !== "radio" && type !== "file"
        ? String(el.value ?? "").slice(0, 200) : null,
      visual_label: visualLabel,
      scopes: scopesOf(el),
      disabled: el.disabled === true || el.getAttribute("aria-disabled") === "true",
      readonly: el.readOnly === true,
      submit: (tag === "button" && (el.getAttribute("type") || "submit") === "submit"
        || tag === "input" && type === "submit") && !!el.form,
      in_form: !!el.closest("form"),
      href, href_attr: hrefAttr, same_origin: sameOrigin,
      target: el.getAttribute("target") || "",
      popup: el.getAttribute("aria-haspopup") || "",
      section: sectionOf(el),
      help: isField ? helpOf(el) : "",
      testid: el.getAttribute("data-testid") || el.getAttribute("data-test-id") || "",
      html_id: el.id || "",
      path: pathOf(el),
      box: { x: rect.left + scrollX, y: rect.top + scrollY, w: rect.width, h: rect.height },
    });
  }
  const headings = [...document.querySelectorAll("h1, h2, h3")]
    .filter(shown).map((h) => norm(h.textContent)).filter(Boolean).slice(0, 10);
  return {
    url: location.href,
    title: document.title,
    lang: document.documentElement.lang || "",
    headings,
    elements,
    page: {
      width: document.documentElement.scrollWidth,
      height: document.documentElement.scrollHeight,
    },
  };
}
"""

# Linhas de texto visíveis: base do "antes/depois" de cada sondagem (qualquer texto novo conta).
LINES_SCRIPT = """
() => {
  const seen = new Set();
  const lines = [];
  for (const raw of (document.body?.innerText || "").split("\\n")) {
    const line = raw.replace(/\\s+/g, " ").trim();
    if (line && !seen.has(line)) { seen.add(line); lines.push(line.slice(0, 160)); }
  }
  return lines;
}
"""

# Contexto da tela para o Jev: títulos, instruções e avisos, sem os rótulos dos campos. Com o
# innerText, rótulos vizinhos viram uma linha só ("Colaborador * Matrícula …") e o asterisco
# de um parece ser do outro; cada campo já leva o próprio rótulo na sua pergunta.
CONTEXT_SCRIPT = """
() => {
  const skip = "label, button, a, select, option, textarea, [role=button], [role=link]";
  const blocks = "h1, h2, h3, h4, h5, h6, p, legend, caption, li, dt, dd, small, th, "
    + "[role=alert], [role=status], [role=note], [role=heading]";
  const seen = new Set();
  const lines = [];
  for (const el of document.querySelectorAll(blocks)) {
    if (el.closest(skip) || (el.checkVisibility && !el.checkVisibility())) continue;
    const line = (el.innerText || "").replace(/\\s+/g, " ").trim().slice(0, 160);
    if (line && !seen.has(line)) { seen.add(line); lines.push(line); }
  }
  return lines;
}
"""


@dataclass
class Element:
    id: str
    tag: str
    type: str
    role: str
    name: str
    label: str
    kind: str
    placeholder: str = ""
    required: bool = False
    maxlength: int | None = None
    minlength: int | None = None
    min: float | None = None
    max: float | None = None
    pattern: str = ""
    inputmode: str = ""
    autocomplete: str = ""
    group: str = ""
    options: list[dict] = field(default_factory=list)
    checked: bool | None = None
    value: str | None = None  # valor inicial (campos de texto e listas)
    visual_label: str = ""  # texto de um <label> que não rotula o campo
    scopes: list[str] = field(default_factory=list)  # grupos que contêm o elemento
    disabled: bool = False
    readonly: bool = False
    submit: bool = False
    in_form: bool = False
    href: str | None = None
    href_attr: str | None = None
    same_origin: bool | None = None
    target: str = ""
    popup: str = ""
    section: str = ""
    help: str = ""
    testid: str = ""
    html_id: str = ""
    path: str = ""
    box: dict = field(default_factory=dict)
    locator: dict | None = None

    @property
    def text_input(self) -> bool:
        return self.kind == "field" and self.tag in {"input", "textarea"} and self.type not in {
            "checkbox", "radio", "range", "color", "file",
        }

    def describe(self) -> dict[str, Any]:
        """Descrição compacta para o Jev: só o que ajuda a decidir, sem ids internos."""
        keys = ("label", "placeholder", "type", "inputmode", "autocomplete", "section", "help",
                "pattern", "maxlength", "min", "max")
        info: dict[str, Any] = {"tag": self.tag}
        if self.kind == "action":
            info["text"] = self.name
            if self.role not in {"button", "link"}:
                info["aria_role"] = self.role  # tab, menuitem, combobox: diz o que o clique faz
            if self.href:
                info["link_to"] = _path(self.href) if self.same_origin else "external site"
            if self.submit:
                info["submits_form"] = True
            if self.type == "reset":
                info["resets_form"] = True
            if self.popup:
                info["opens_popup"] = self.popup
            if self.section:
                info["section"] = self.section
            return info
        for key in keys:
            value = getattr(self, key)
            if value not in (None, "", False):
                info[key] = value
        if self.visual_label and not self.label:
            info["unassociated_label_text"] = self.visual_label
        if self.options:
            info["options"] = [o["label"] for o in self.options[:8]]
        return info


@dataclass
class Screen:
    url: str
    title: str
    lang: str
    headings: list[str]
    lines: list[str]
    elements: list[Element]
    width: int
    height: int
    screenshot: bytes | None = None
    aria_chars: int = 0

    @property
    def fields(self) -> list[Element]:
        return [e for e in self.elements if e.kind == "field"]

    @property
    def actions(self) -> list[Element]:
        return [e for e in self.elements if e.kind == "action"]

    def to_dict(self) -> dict:
        data = asdict(self)
        data.pop("screenshot")
        return data


def _path(url: str) -> str:
    match = re.match(r"^[a-z]+://[^/]+(/[^?#]*)?", url)
    return (match.group(1) if match else url) or "/"


def strip_label(label: str) -> str:
    """'Nome completo *' → 'Nome completo': o localizador fica legível e não depende do '*'."""
    return re.sub(r"[\s*:]+$", "", label).strip()


_STACK: list | None = None


def cache_call_stack() -> None:
    """Evita o `inspect.stack()` que o Playwright faz a cada chamada da API assíncrona.

    Esse stack serve para metadados de tracing e para o prefixo das mensagens de erro, e custa
    um `os.stat` por frame: no Windows era cerca de 60% da CPU das sondagens. A API síncrona do
    próprio Playwright usa o mesmo atalho (`__pw_stack__` na tarefa); o atributo vale por tarefa,
    então cada tarefa criada por `gather` chama esta função no início.
    """
    global _STACK
    task = asyncio.current_task()
    if task is None or getattr(task, "__pw_stack__", None):
        return
    if _STACK is None:
        _STACK = inspect.stack(0)[:1]
    task.__pw_stack__ = _STACK


# --- Localizadores -------------------------------------------------------------------------
# Um localizador é um dicionário simples, traduzido para Playwright aqui e para código Python
# ou TypeScript em codegen.py. Assim o que foi verificado é exatamente o que vai para o teste.


def resolve(page: Page, spec: dict) -> Locator:
    method = spec["method"]
    if method == "test_id":
        return page.get_by_test_id(spec["value"])
    if method == "label":
        return page.get_by_label(spec["value"], exact=spec.get("exact", False))
    if method == "role":
        return page.get_by_role(spec["role"], name=spec["value"], exact=spec.get("exact", True))
    if method == "placeholder":
        return page.get_by_placeholder(spec["value"], exact=True)
    if method == "text":
        return page.get_by_text(spec["value"], exact=True)
    return page.locator(spec["value"])


def without_count(text: str) -> str | None:
    """'Skill103' → 'Skill', 'Filtros (3)' → 'Filtros': contadores mudam com os dados."""
    match = re.fullmatch(r"(.*?[^\d\s(])\s*\(?\d+\)?", text.strip())
    return match.group(1).strip() if match and len(match.group(1).strip()) >= 2 else None


FIELD_ROLES = {"combobox", "listbox", "textbox", "searchbox", "spinbutton", "slider", "switch",
               "checkbox", "radio"}


def candidates(element: Element) -> list[dict]:
    specs: list[dict] = []
    if element.testid:
        specs.append({"method": "test_id", "value": element.testid})
    if element.kind == "field":
        if element.label:
            short = strip_label(element.label)
            if short and (stable := without_count(short)):
                specs.append({"method": "label", "value": stable, "exact": False})
            if short:
                specs.append({"method": "label", "value": short, "exact": False})
            specs.append({"method": "label", "value": element.label, "exact": True})
        if element.placeholder:
            specs.append({"method": "placeholder", "value": element.placeholder})
        # Lista ou caixa customizada (div com role e aria-label, sem <label>).
        if element.name and element.role in FIELD_ROLES:
            specs.append({"method": "role", "role": element.role, "value": element.name})
    elif element.name and element.role in {"button", "link", "tab", "menuitem", "checkbox",
                                           "combobox", "switch", "radio", "option"}:
        if stable := without_count(element.name):
            specs.append({"method": "role", "role": element.role, "value": stable,
                          "exact": False})
        specs.append({"method": "role", "role": element.role, "value": element.name})
        # innerText vem com o text-transform do CSS ("NOME"), o nome acessível não ("Nome"):
        # sem `exact` a comparação ignora maiúsculas.
        specs.append({"method": "role", "role": element.role, "value": element.name,
                      "exact": False})
    if element.html_id and re.fullmatch(r"[A-Za-z][\w-]*", element.html_id):
        specs.append({"method": "css", "value": f"#{element.html_id}"})
    specs.append({"method": "css", "value": f'[data-scout-id="{element.id}"]', "fragile": True})
    return specs


async def _verify(page: Page, element: Element) -> dict | None:
    cache_call_stack()
    for spec in candidates(element):
        if spec.get("fragile"):
            # Só serve para a própria exploração: o atributo não existe na aplicação real.
            return {**spec, "unique": False}
        locator = resolve(page, spec)
        try:
            if await locator.count() != 1:
                continue
            if await locator.get_attribute("data-scout-id") != element.id:
                continue
        except Exception:  # noqa: BLE001 - seletor inválido para esta página
            continue
        return {**spec, "unique": True}
    return None


async def capture(page: Page, screenshot: bool = True) -> Screen:
    cache_call_stack()
    raw = await page.evaluate(INVENTORY_SCRIPT)
    lines = await page.evaluate(CONTEXT_SCRIPT)
    if not lines:
        # Tela montada só com div/span: sem blocos semânticos, fica o texto visível inteiro.
        lines = await page.evaluate(LINES_SCRIPT)
    elements = [Element(**item) for item in raw["elements"]]
    # Verificação em paralelo: cada count() é uma ida e volta ao navegador.
    locators = await asyncio.gather(*(_verify(page, e) for e in elements))
    for element, spec in zip(elements, locators, strict=True):
        element.locator = spec
    shot = await page.screenshot(full_page=True, type="jpeg", quality=72) if screenshot else None
    try:
        aria_chars = len(await page.locator("body").aria_snapshot())
    except Exception:  # noqa: BLE001 - métrica de referência, não bloqueia a captura
        aria_chars = 0
    return Screen(
        url=raw["url"],
        title=raw["title"],
        lang=raw["lang"],
        headings=raw["headings"],
        lines=lines[:60],
        elements=elements,
        width=raw["page"]["width"],
        height=raw["page"]["height"],
        screenshot=shot,
        aria_chars=aria_chars,
    )


async def visible_lines(page: Page) -> list[str]:
    return await page.evaluate(LINES_SCRIPT)


# Tela "pronta": algo interativo visível e nenhum indicador de carregamento na tela. Uma SPA
# dispara o `load` antes de buscar a configuração e desenhar; capturar nesse momento dá um
# screenshot em branco e zero elementos.
READY_SCRIPT = """
() => {
  const visible = (el) => el.checkVisibility ? el.checkVisibility() : el.offsetParent !== null;
  const busy = [...document.querySelectorAll(
    "[aria-busy=true], [role=progressbar], .spinner, .loading, .loader, [class*=skeleton]"
  )].some(visible);
  const interactive = [...document.querySelectorAll(
    "input:not([type=hidden]), select, textarea, button, a[href], [role=button]"
  )].filter(visible).length;
  return { busy, interactive, text: (document.body?.innerText || "").trim().length };
}
"""


async def wait_ready(page: Page, timeout_ms: int = 15000) -> bool:
    """Espera a tela desenhar de verdade: DOM quieto, URL estável e conteúdo visível."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_ms / 1000
    url = page.url
    while loop.time() < deadline:
        left = max(500, int((deadline - loop.time()) * 1000))
        await settle(page, quiet_ms=400, timeout_ms=min(left, 8000))
        if page.url != url:  # redirecionamento por script (SSO, rota da SPA)
            url = page.url
            continue
        try:
            state = await page.evaluate(READY_SCRIPT)
        except Exception:  # noqa: BLE001 - navegou no meio da leitura
            continue
        if state["interactive"] > 0 and not state["busy"]:
            return True
        await page.wait_for_timeout(250)
    return False


async def settle(page: Page, quiet_ms: int = 120, timeout_ms: int = 4000) -> bool:
    """Espera o DOM ficar quieto e as requisições terminarem. False se não assentou."""
    for _ in range(2):
        try:
            await page.wait_for_function(
                "q => window.__scout && window.__scout.pending === 0"
                " && performance.now() - window.__scout.mut > q",
                arg=quiet_ms,
                timeout=timeout_ms,
                polling=50,
            )
            return True
        except Exception:  # noqa: BLE001 - navegação troca o contexto de execução
            try:
                await page.wait_for_load_state("load", timeout=timeout_ms)
            except Exception:  # noqa: BLE001
                return False
    return False
