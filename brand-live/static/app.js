/* Brand Live: a voz vira uma frase, a frase vira decisões tipadas do Jev, e o navegador
   aplica as decisões ao brand. Limiares moram aqui, não no servidor. */

const $ = (id) => document.getElementById(id);
const canvas = $("canvas");
const decisionsList = $("decisions");

let CATALOG = null;
let brand = null;
// A página começa em branco e só aparece depois da primeira mudança aplicada.
let blank = true;
const history = [];
const recent = [];
const totals = { count: 0, ms: 0, cost: 0 };
let lastApplied = { utterance: "", key: "" };

const thresholds = {
  get apply() {
    return parseFloat($("apply").value);
  },
  get ask() {
    return parseFloat($("ask").value);
  },
};
for (const id of ["apply", "ask"]) {
  $(id).addEventListener("input", () => {
    $(`${id}-out`).textContent = thresholds[id].toFixed(2);
  });
}

// --- Brand: estado e renderização ------------------------------------------------------

function normalize(text) {
  return text
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9 ]+/g, " ")
    .trim();
}

function brandFromVertical(key) {
  const v = CATALOG.verticals[key];
  return {
    vertical: key,
    background: v.theme.background,
    primary: v.theme.primary,
    text: "auto",
    accent: v.theme.accent,
    font: v.theme.font,
    layout: v.theme.layout,
    tone: v.theme.tone,
    sections: ["features", "pricing", "email", "social"],
  };
}

function luminance(hex) {
  const n = parseInt(hex.slice(1), 16);
  const [r, g, b] = [n >> 16, (n >> 8) & 255, n & 255].map((c) => {
    c /= 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
const hex = (key) => CATALOG.colors[key].hex;
const onColor = (key) => (luminance(hex(key)) > 0.4 ? "#0b0b0f" : "#ffffff");

function render(changed = []) {
  const v = CATALOG.verticals[brand.vertical];
  const voice = brand.tone >= 2.5 ? "casual" : "formal";
  const copy = v.copy[voice];
  const s = canvas.style;
  s.setProperty("--bg", hex(brand.background));
  s.setProperty("--primary", hex(brand.primary));
  s.setProperty("--accent", hex(brand.accent));
  s.setProperty("--text", brand.text === "auto" ? onColor(brand.background) : hex(brand.text));
  s.setProperty("--on-primary", onColor(brand.primary));
  s.setProperty("--radius", `${Math.round(2 + brand.tone * 6)}px`);
  canvas.dataset.layout = brand.layout;
  canvas.dataset.font = brand.font;
  canvas.classList.toggle("is-blank", blank);

  const initial = v.name[0].toUpperCase();
  const set = (id, text) => {
    $(id).textContent = text;
  };
  set("wordmark", v.name);
  set("eyebrow", v.label);
  set("headline", copy.headline);
  set("sub", copy.sub);
  set("cta", copy.cta);
  set("nav-cta", copy.cta);
  set("email-cta", copy.cta);
  v.features.forEach((f, i) => set(`f${i}`, f));
  set("email-from", v.name);
  set("email-avatar", initial);
  set("email-subject", copy.email_subject);
  set("email-body", copy.email_body);
  set("social-from", v.name);
  set("social-avatar", initial);
  set("social-body", copy.social);

  for (const el of canvas.querySelectorAll("[data-section]")) {
    el.classList.toggle("hidden", !brand.sections.includes(el.dataset.section));
  }
  for (const sel of changed) {
    for (const el of canvas.querySelectorAll(sel)) {
      el.classList.remove("changed");
      void el.offsetWidth;
      el.classList.add("changed");
    }
  }
}

// --- Interpretação: de probabilidades para uma mudança (ou uma pergunta) ---------------

const FACET_FOR = {
  change_color: "color",
  change_vertical: "vertical",
  change_layout: "layout",
  change_font: "font",
  show_section: "section",
  hide_section: "section",
};

function interpret(d) {
  const intent = d.intent;
  // A intenção é o gate principal; `is_command` só desempata quando ela vem fraca.
  if (intent.value === "none") return { status: "ignorado", why: "não é um comando", intent };
  if (intent.confidence < thresholds.ask) return { status: "ignorado", why: "sem intenção clara", intent };
  if (intent.confidence < thresholds.apply && d.is_command < 0.3) {
    return { status: "ignorado", why: "não parece um comando", intent };
  }
  if (d.out_of_catalog >= 0.7) return { status: "fora do catálogo", blocked: true, intent };
  if (intent.value === "undo" || intent.value === "reset")
    return { status: "aplicar", intent, change: { kind: intent.value } };
  if (intent.value === "change_tone") {
    return { status: "aplicar", intent, change: { kind: "tone", value: d.tone.value } };
  }
  const facetKey = FACET_FOR[intent.value];
  const facet = d[facetKey];
  if (facet.value === "not_in_catalog") return { status: "fora do catálogo", blocked: true, intent, facet };
  if (facet.value === null) return { status: "aguardando", why: `falta ${facetKey}`, intent, facet };
  const change = { kind: intent.value, facet: facetKey, value: facet.value };
  if (intent.value === "change_color") change.target = d.target.value || "primary";
  if (facet.confidence >= thresholds.apply) return { status: "aplicar", intent, facet, change };
  if (facet.confidence >= thresholds.ask) {
    const options = facet.top
      .filter((o) => o.key !== "not_mentioned" && o.key !== "not_in_catalog")
      .slice(0, 2);
    return { status: "perguntar", intent, facet, change, options };
  }
  return { status: "ignorado", why: "confiança baixa", intent, facet };
}

function changeKey(c) {
  return [c.kind, c.facet, c.target, c.value].join("|");
}

function apply(change) {
  const wasBlank = blank;
  history.push({ brand: JSON.parse(JSON.stringify(brand)), blank });
  blank = false;
  let flash = [];
  switch (change.kind) {
    case "undo":
      history.pop();
      if (history.length) ({ brand, blank } = history.pop());
      else blank = wasBlank;
      flash = [".page"];
      break;
    case "reset":
      // Recomeçar volta para a página em branco.
      brand = brandFromVertical("saas_b2b");
      blank = true;
      break;
    case "tone":
      brand.tone = Math.max(0, Math.min(4, change.value));
      flash = [".headline", ".sub", ".btn-primary"];
      break;
    case "change_color":
      brand[change.target] = change.value;
      flash = {
        background: [".page"],
        primary: [".btn-primary", ".wordmark"],
        text: [".headline"],
        accent: [".eyebrow", ".feature-n"],
      }[change.target];
      break;
    case "change_vertical":
      brand = { ...brandFromVertical(change.value), sections: brand.sections };
      flash = [".hero", ".mocks"];
      break;
    case "change_layout":
      brand.layout = change.value;
      flash = [".hero"];
      break;
    case "change_font":
      brand.font = change.value;
      flash = [".headline", ".wordmark"];
      break;
    case "show_section":
      if (!brand.sections.includes(change.value)) brand.sections.push(change.value);
      flash = [`[data-section="${change.value}"]`];
      break;
    case "hide_section":
      brand.sections = brand.sections.filter((s) => s !== change.value);
      break;
  }
  render(flash);
}

// --- Rede -----------------------------------------------------------------------------

let inflight = null;

async function decide(utterance, partial) {
  if (inflight) inflight.abort();
  inflight = new AbortController();
  const body = { utterance, partial, brand, recent: recent.slice(-3) };
  const response = await fetch("/api/command", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: inflight.signal,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

// --- Painel ---------------------------------------------------------------------------

const LABELS = {
  intent: (k) => CATALOG.intents[k],
  color: (k) => CATALOG.colors[k]?.label,
  vertical: (k) => CATALOG.verticals[k]?.label ?? (k === "not_in_catalog" ? "fora do catálogo" : k),
  layout: (k) => CATALOG.layouts[k],
  font: (k) => CATALOG.fonts[k],
  section: (k) => CATALOG.sections[k],
  target: (k) => CATALOG.targets[k],
};
const label = (facet, key) => (key === "not_mentioned" ? "—" : (LABELS[facet]?.(key) ?? key));

function chip(name, facet, opts = {}) {
  const value = facet.value ?? "not_mentioned";
  const swatch =
    name === "color" && facet.value ? `<i class="swatch" style="background:${hex(facet.value)}"></i>` : "";
  return `<span class="chip ${opts.dim ? "dim" : ""}" title="${facet.top?.map((o) => `${label(name, o.key)} ${(o.p * 100).toFixed(0)}%`).join(" · ") ?? ""}">
    <b>${name}</b>${swatch}${label(name, value)} <span class="p">${(facet.confidence * 100).toFixed(0)}%</span>
    <span class="bar" style="width:${facet.confidence * 100}%"></span></span>`;
}

function fmtCost(usd) {
  return usd == null ? "–" : `$${usd.toFixed(6)}`;
}

function renderRow(row, data, verdict) {
  const d = data.decisions;
  const status = {
    aplicar: ["applied", "aplicado"],
    perguntar: ["ask", "quis dizer?"],
    "fora do catálogo": ["blocked", "fora do catálogo"],
    aguardando: ["", "aguardando…"],
    ignorado: ["", `ignorado · ${verdict.why ?? ""}`],
    "já aplicado": ["", "já aplicado"],
  }[verdict.status];
  const t = data.telemetry;
  const chips = [];
  if (verdict.intent) chips.push(chip("intent", verdict.intent));
  if (verdict.facet)
    chips.push(
      chip(
        (verdict.change?.facet ?? Object.keys(FACET_FOR).includes(verdict.intent.value))
          ? FACET_FOR[verdict.intent.value]
          : "vertical",
        verdict.facet,
      ),
    );
  if (verdict.change?.target)
    chips.push(
      chip("target", d.target.value ? d.target : { value: "primary", confidence: 1, top: [] }, {
        dim: !d.target.value,
      }),
    );
  if (verdict.change?.kind === "tone")
    chips.push(
      `<span class="chip"><b>tom</b>${d.tone.value.toFixed(1)} / 4 <span class="p">${(d.tone.confidence * 100).toFixed(0)}%</span><span class="bar" style="width:${d.tone.confidence * 100}%"></span></span>`,
    );
  chips.push(`<span class="chip dim"><b>comando</b>${(d.is_command * 100).toFixed(0)}%</span>`);
  if (d.out_of_catalog >= 0.3)
    chips.push(
      `<span class="chip dim"><b>fora do catálogo</b>${(d.out_of_catalog * 100).toFixed(0)}%</span>`,
    );
  const ask =
    verdict.status === "perguntar"
      ? `<div class="ask-buttons">${verdict.options.map((o) => `<button data-key="${o.key}">${label(verdict.change.facet, o.key)} · ${(o.p * 100).toFixed(0)}%</button>`).join("")}</div>`
      : "";
  row.className = `row ${data.partial ? "partial" : ""}`;
  row.innerHTML = `
    <div class="row-top"><span class="utt">${escapeHtml(data.utterance)}</span><span class="status ${status[0]}">${status[1]}</span></div>
    <div class="chips">${chips.join("")}</div>${ask}
    <div class="meta"><span class="ms">${t.cached ? "cache" : `${t.jev_ms} ms`}</span><span>${t.questions ?? "–"} perguntas</span><span>${t.input_tokens ?? "–"} tokens</span><span>${fmtCost(t.cost_usd)}</span></div>`;
  row.querySelectorAll(".ask-buttons button").forEach((btn) => {
    btn.addEventListener("click", () => {
      apply({ ...verdict.change, value: btn.dataset.key });
      row.querySelector(".status").className = "status applied";
      row.querySelector(".status").textContent = "aplicado";
      row.querySelector(".ask-buttons").remove();
    });
  });
}

function escapeHtml(s) {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
}

function updateStats(t) {
  if (t.cached) return;
  totals.count += 1;
  totals.ms += t.jev_ms;
  totals.cost += t.cost_usd ?? 0;
  $("stat-count").textContent = totals.count;
  $("stat-ms").textContent = Math.round(totals.ms / totals.count);
  $("stat-cost").textContent = fmtCost(totals.cost);
}

// Uma linha por segmento de fala: as parciais atualizam a mesma linha até a frase fechar.
function newRow() {
  const row = document.createElement("li");
  row.className = "row partial";
  row.innerHTML = `<div class="row-top"><span class="utt">…</span><span class="status">ouvindo</span></div>`;
  decisionsList.prepend(row);
  return row;
}

async function handle(utterance, partial, row) {
  row.querySelector(".utt").textContent = utterance;
  let data;
  try {
    data = await decide(utterance, partial);
  } catch (error) {
    if (error.name === "AbortError") return;
    row.className = "row error";
    row.innerHTML = `<div class="row-top"><span class="utt">${escapeHtml(utterance)}</span><span class="status blocked">erro</span></div><div class="meta">${escapeHtml(error.message)}</div>`;
    return;
  }
  updateStats(data.telemetry);
  const verdict = interpret(data.decisions);
  if (verdict.status === "aplicar") {
    const key = changeKey(verdict.change);
    const norm = normalize(utterance);
    const repeat =
      key === lastApplied.key &&
      (norm.startsWith(lastApplied.utterance) || lastApplied.utterance.startsWith(norm));
    if (repeat) verdict.status = "já aplicado";
    else {
      apply(verdict.change);
      lastApplied = { utterance: norm, key };
    }
  }
  if (!partial) {
    recent.push(utterance);
    if (recent.length > 5) recent.shift();
  }
  renderRow(row, data, verdict);
  return verdict;
}

// --- Entrada por texto -----------------------------------------------------------------

$("form").addEventListener("submit", (event) => {
  event.preventDefault();
  const text = $("input").value.trim();
  if (!text) return;
  $("input").value = "";
  handle(text, false, newRow());
});

// --- Entrada por voz (Web Speech API, pt-BR, resultados parciais) ----------------------

const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
const mic = $("mic");
let recognition = null;
let listening = false;
let debounce = null;
let lastPartial = "";
// O Chrome mantém a fala contínua num único segmento que só cresce. Depois que um trecho
// vira uma mudança aplicada, só as palavras novas vão ao Jev; senão a segunda ordem da
// mesma respiração nunca seria ouvida.
let segment = { row: null, handled: 0 };

if (!SR) {
  mic.disabled = true;
  $("live-text").textContent = "reconhecimento de voz indisponível neste navegador (use Chrome/Edge)";
}

function onSpeechResult(event) {
  for (let i = event.resultIndex; i < event.results.length; i += 1) {
    const result = event.results[i];
    const text = result[0].transcript.trim();
    if (!text) continue;
    $("live-text").textContent = text;
    const words = text.split(/\s+/);
    const piece = words.slice(segment.handled).join(" ");
    if (result.isFinal) {
      clearTimeout(debounce);
      const { row } = segment;
      segment = { row: null, handled: 0 };
      lastPartial = "";
      if (piece) handle(piece, false, row ?? newRow());
      else row?.remove();
    } else if (piece && normalize(piece) !== lastPartial) {
      lastPartial = normalize(piece);
      clearTimeout(debounce);
      if (!segment.row) segment.row = newRow();
      // Espera a fala assentar um instante: cada parcial custa uma decisão.
      const current = segment;
      debounce = setTimeout(async () => {
        const verdict = await handle(piece, true, current.row);
        if (verdict && (verdict.status === "aplicar" || verdict.status === "já aplicado")) {
          // Trecho consumido: as próximas palavras começam uma ordem nova, em outra linha.
          current.handled = words.length;
          current.row = null;
        }
      }, 350);
    }
  }
}

function startListening() {
  recognition = new SR();
  recognition.lang = "pt-BR";
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.onresult = onSpeechResult;
  recognition.onerror = (event) => {
    $("live-text").textContent = `erro do microfone: ${event.error}`;
  };
  recognition.onend = () => {
    if (listening) recognition.start();
  };
  recognition.start();
  listening = true;
  mic.setAttribute("aria-pressed", "true");
  $("live").classList.add("on");
  $("live-text").textContent = "ouvindo…";
}

function stopListening() {
  listening = false;
  recognition?.stop();
  mic.setAttribute("aria-pressed", "false");
  $("live").classList.remove("on");
  $("live-text").textContent = "microfone parado";
}

mic.addEventListener("click", () => (listening ? stopListening() : startListening()));
document.addEventListener("keydown", (e) => {
  if (e.code === "Space" && document.activeElement !== $("input") && !mic.disabled) {
    e.preventDefault();
    mic.click();
  }
});

// --- Boot -----------------------------------------------------------------------------

(async () => {
  CATALOG = await (await fetch("/api/catalog")).json();
  const badge = $("model-badge");
  badge.textContent = CATALOG.simulated ? "Jev simulado" : CATALOG.model;
  badge.classList.toggle("sim", CATALOG.simulated);
  if (!CATALOG.configured) badge.textContent = "sem API key";
  brand = brandFromVertical("saas_b2b");
  render();
})();
