"use strict";

// O servidor devolve só as probabilidades do Jev. A política (limiares, filtros,
// ordenação) roda aqui, para que mexer num limiar não exija nova inferência.

const DEBOUNCE_MS = 220;
const MIN_CHARS = 3;
const INCOMPLETE_AT = 0.7;
const EXAMPLES = [
  "code review",
  "preciso revisar PRs de um serviço em C#",
  "sou do front e quero testar telas em React",
  "algo que leia os work items do Azure DevOps",
  "documentar as APIs da Aurora Cloud",
  "quero criar uma skill nova para o meu time",
  "uma skill para fazer café",
];
const FACET_LABELS = { artifact_type: "Tipo", technology: "Tecnologia", team: "Time", purpose: "Finalidade" };
// Time e finalidade só ordenam: "sou do front" descreve quem busca, não o dono do artefato.
const HARD_FACETS = ["artifact_type", "technology"];
const SOFT_FACETS = ["team", "purpose"];
const NEUTRAL_TECH = ["Git/GitHub"];

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const pct = (p) => `${Math.round(p * 100)}%`;
const norm = (s) => s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
const money = (v) => `US$ ${v < 0.01 ? v.toFixed(5).replace(".", ",") : v.toFixed(4).replace(".", ",")}`;

const state = {
  catalog: [],
  taxonomy: null,
  byId: new Map(),
  persona: { team: null, technologies: [] },
  manual: { type: new Set(), technology: new Set(), team: new Set(), purpose: new Set() },
  dismissed: new Set(),
  jev: null,          // última resposta válida {query, result}
  note: "",
  pending: null,      // {controller, seq, started}
  seq: 0,
  error: "",
  timer: null,
  thresholds: { rel: 0.6, facet: 0.7 },
  session: { searches: 0, decisions: 0, ms: 0, cost: 0 },
};

async function init() {
  const data = await (await fetch("/api/catalog")).json();
  state.catalog = data.items;
  state.taxonomy = data.taxonomy;
  state.catalog.forEach((item) => state.byId.set(item.id, item));
  $("simulated").hidden = !data.simulated;
  $("unconfigured").hidden = data.configured;
  state.configured = data.configured;

  $("examples").innerHTML = EXAMPLES.map((q) => `<button type="button">${esc(q)}</button>`).join("");
  $("examples").addEventListener("click", (e) => {
    if (e.target.tagName !== "BUTTON") return;
    $("q").value = e.target.textContent;
    onInput(true);
    $("q").focus();
  });

  const team = $("persona-team");
  state.taxonomy.teams.forEach((t) => team.insertAdjacentHTML("beforeend", `<option>${esc(t)}</option>`));
  team.addEventListener("change", () => { state.persona.team = team.value || null; onInput(true); });
  $("persona-tech").innerHTML = state.taxonomy.technologies
    .map((t) => `<button type="button" aria-pressed="false" data-tech="${esc(t)}">${esc(t)}</button>`).join("");
  $("persona-tech").addEventListener("click", (e) => {
    const tech = e.target.dataset?.tech;
    if (!tech) return;
    const list = state.persona.technologies;
    const on = !list.includes(tech);
    state.persona.technologies = on ? [...list, tech] : list.filter((t) => t !== tech);
    e.target.setAttribute("aria-pressed", String(on));
    onInput(true);
  });

  $("q").addEventListener("input", () => onInput(false));
  $("q").addEventListener("keydown", (e) => { if (e.key === "Enter") onInput(true); });
  for (const [id, key] of [["rel", "rel"], ["facet", "facet"]]) {
    $(id).addEventListener("input", (e) => {
      state.thresholds[key] = Number(e.target.value);
      $(`${id}-out`).textContent = pct(state.thresholds[key]);
      render();
    });
  }
  $("clear-filters").addEventListener("click", () => {
    Object.values(state.manual).forEach((s) => s.clear());
    render();
  });
  $("filter-groups").addEventListener("change", (e) => {
    const { group, value } = e.target.dataset;
    if (!group) return;
    e.target.checked ? state.manual[group].add(value) : state.manual[group].delete(value);
    render();
  });
  $("chips").addEventListener("click", (e) => {
    const key = e.target.dataset?.dismiss;
    if (!key) return;
    state.dismissed.has(key) ? state.dismissed.delete(key) : state.dismissed.add(key);
    render();
  });
  $("grid").addEventListener("click", (e) => {
    const cmd = e.target.dataset?.copy;
    if (cmd) navigator.clipboard?.writeText(cmd).then(() => toast("Comando copiado"));
  });
  $("empty").addEventListener("click", (e) => {
    if (e.target.dataset?.action === "clear") {
      Object.values(state.manual).forEach((s) => s.clear());
      HARD_FACETS.forEach((k) => {
        const f = state.jev?.result.facets[k];
        if (f?.value) state.dismissed.add(`${k}:${f.value}`);
      });
      render();
    }
    if (e.target.dataset?.action === "request") {
      toast("Demo: aqui abriria um pedido de novo artefato com a sua descrição.");
    }
  });
  render();
}

// --- Busca --------------------------------------------------------------------------

function onInput(immediate) {
  clearTimeout(state.timer);
  const q = $("q").value.trim();
  if (q.length < MIN_CHARS) {
    abortPending();
    state.jev = null;
    state.note = "";
    render();
    return;
  }
  render();
  if (!state.configured) return;
  state.timer = setTimeout(() => search(q), immediate ? 0 : DEBOUNCE_MS);
}

function abortPending() {
  if (state.pending) state.pending.controller.abort();
  state.pending = null;
  $("pulse").hidden = true;
}

async function search(query) {
  abortPending();
  const seq = ++state.seq;
  const controller = new AbortController();
  state.pending = { controller, seq, started: performance.now() };
  $("pulse").hidden = false;
  tick();
  render();
  try {
    const response = await fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, persona: state.persona }),
      signal: controller.signal,
    });
    const body = await response.json();
    if (seq !== state.seq) return; // resposta atrasada: outra busca já foi pedida
    state.pending = null;
    $("pulse").hidden = true;
    if (!response.ok) {
      state.error = body.error || `HTTP ${response.status}`;
      render();
      return;
    }
    state.error = "";
    account(body.telemetry);
    const previous = state.jev;
    if (body.incomplete >= INCOMPLETE_AT && previous) {
      // Ainda digitando: o Jev avisa, a tela mantém o último resultado útil.
      state.note = `Jev: consulta incompleta (${pct(body.incomplete)}), mantendo o resultado de “${previous.query}”.`;
      state.lastTelemetry = body.telemetry;
    } else {
      if (!previous || facetSignature(previous.result) !== facetSignature(body)) state.dismissed.clear();
      state.jev = { query, result: body };
      state.lastTelemetry = body.telemetry;
      state.note = body.incomplete >= INCOMPLETE_AT ? `Jev: consulta incompleta (${pct(body.incomplete)}).` : "";
    }
    render();
  } catch (err) {
    if (err.name === "AbortError") return;
    if (seq !== state.seq) return;
    state.pending = null;
    $("pulse").hidden = true;
    state.error = "Falha ao contatar o servidor.";
    render();
  }
}

function tick() {
  if (!state.pending) return;
  $("pulse-ms").textContent = `${Math.round(performance.now() - state.pending.started)} ms`;
  requestAnimationFrame(tick);
}

function account(t) {
  if (t.cached) return;
  const s = state.session;
  s.searches += 1;
  s.decisions += t.questions;
  s.ms += t.jev_ms;
  s.cost += t.cost_usd || 0;
  $("s-searches").textContent = s.searches;
  $("s-decisions").textContent = s.decisions.toLocaleString("pt-BR");
  $("s-avg").textContent = `${Math.round(s.ms / s.searches)} ms`;
  $("s-cost").textContent = money(s.cost);
}

const facetSignature = (r) => Object.entries(r.facets).map(([k, f]) => `${k}=${f.value}`).join("|");

// --- Política de decisão ------------------------------------------------------------

function activeFacets(result) {
  const out = {};
  if (!result) return out;
  for (const [key, f] of Object.entries(result.facets)) {
    const confident = f.value && f.confidence >= state.thresholds.facet;
    out[key] = { ...f, confident, applied: confident && HARD_FACETS.includes(key) && !state.dismissed.has(`${key}:${f.value}`) };
  }
  return out;
}

function passesFacets(item, facets) {
  const f = facets;
  if (f.artifact_type?.applied && item.type !== f.artifact_type.value) return false;
  // Artefato sem stack declarada é genérico e continua compatível. Git é ferramenta,
  // não stack: uma skill de PR marcada com Git/GitHub serve a qualquer linguagem.
  if (f.technology?.applied) {
    const stack = item.technologies.filter((t) => !NEUTRAL_TECH.includes(t));
    if (stack.length && !item.technologies.includes(f.technology.value)) return false;
  }
  return true;
}

function passesManual(item, skip) {
  const m = state.manual;
  if (skip !== "type" && m.type.size && !m.type.has(item.type)) return false;
  if (skip !== "team" && m.team.size && !m.team.has(item.team)) return false;
  if (skip !== "purpose" && m.purpose.size && !m.purpose.has(item.purpose)) return false;
  if (skip !== "technology" && m.technology.size && !item.technologies.some((t) => m.technology.has(t))) return false;
  return true;
}

function localMatches(q) {
  const words = norm(q).split(/[^a-z0-9#+.]+/).filter((w) => w.length >= MIN_CHARS);
  if (!words.length) return [];
  return state.catalog
    .map((item) => {
      const text = norm(`${item.name} ${item.description} ${item.technologies.join(" ")}`);
      const hits = words.filter((w) => text.includes(w)).length;
      return { item, rel: hits / words.length };
    })
    .filter((r) => r.rel > 0)
    .sort((a, b) => b.rel - a.rel || b.item.installs - a.item.installs);
}

function compute() {
  const q = $("q").value.trim();
  if (q.length < MIN_CHARS) {
    const rows = state.catalog.map((item) => ({ item, rel: null })).sort((a, b) => b.item.installs - a.item.installs);
    return { mode: "all", rows, pool: rows, facets: {} };
  }
  if (!state.jev) {
    const rows = localMatches(q);
    return { mode: "local", rows, pool: rows, facets: {} };
  }
  const { result } = state.jev;
  const facets = activeFacets(result);
  const p = state.persona;
  const scored = state.catalog.map((item) => {
    const rel = result.relevance[item.id] ?? 0;
    const techHit = facets.technology?.confident && item.technologies.includes(facets.technology.value);
    const purposeHit = facets.purpose?.confident && item.purpose === facets.purpose.value;
    const team = p.team || (facets.team?.confident ? facets.team.value : null);
    const bonus = 0.05 * techHit + 0.04 * purposeHit
      + 0.02 * (team === item.team) + 0.02 * item.technologies.some((t) => p.technologies.includes(t));
    return { item, rel, score: rel + bonus, techHit, purposeHit };
  });
  const relevant = scored.filter((r) => r.rel >= state.thresholds.rel);
  const pool = relevant.filter((r) => passesFacets(r.item, facets));
  const rows = pool.filter((r) => passesManual(r.item)).sort((a, b) => b.score - a.score);
  return { mode: "jev", rows, pool, facets, hidden: relevant.length - rows.length, result };
}

// --- Renderização -------------------------------------------------------------------

function render() {
  const view = compute();
  renderChips(view);
  renderTelemetry();
  renderFilters(view);
  renderResults(view);
  renderLog(view);
}

function renderChips(view) {
  const box = $("chips");
  if (view.mode !== "jev") {
    box.innerHTML = view.mode === "local"
      ? `<span class="chip-note">Filtro local por palavras enquanto o Jev responde…</span>` : "";
    return;
  }
  const chips = [];
  for (const key of ["artifact_type", "technology", "team", "purpose"]) {
    const f = view.facets[key];
    if (!f?.confident) continue;
    const label = key === "purpose" ? state.taxonomy.purposes[f.value] : key === "artifact_type" ? state.taxonomy.types[f.value] : f.value;
    if (SOFT_FACETS.includes(key)) {
      chips.push(`<span class="chip soft" title="Interpretação: ordena, não filtra">${FACET_LABELS[key]}: <b>${esc(label)}</b> <span class="conf">${pct(f.confidence)}</span></span>`);
      continue;
    }
    const id = `${key}:${f.value}`;
    const off = state.dismissed.has(id);
    chips.push(`<span class="chip${off ? " off" : ""}" title="Filtro inferido pelo Jev">${FACET_LABELS[key]}: <b>${esc(label)}</b> <span class="conf">${pct(f.confidence)}</span><button type="button" data-dismiss="${esc(id)}" aria-label="${off ? "Reaplicar" : "Remover"} filtro">${off ? "↺" : "×"}</button></span>`);
  }
  if (!chips.length) chips.push(`<span class="chip-note">Nenhum filtro com confiança ≥ ${pct(state.thresholds.facet)}; ranking só por relevância.</span>`);
  if (state.note) chips.push(`<span class="chip-note">${esc(state.note)}</span>`);
  box.innerHTML = chips.join("");
}

function renderTelemetry() {
  const box = $("telemetry");
  if (state.error) { box.innerHTML = `<span class="err">${esc(state.error)}</span>`; return; }
  const t = state.lastTelemetry;
  if (!t || !state.jev && !state.note) { box.innerHTML = ""; return; }
  if (t.cached) {
    box.innerHTML = `<span class="fast">cache · ${t.server_ms} ms</span><span>sem custo</span><span>1ª resposta do Jev: ${Math.round(t.first_jev_ms)} ms · ${t.questions} decisões</span>`;
    return;
  }
  box.innerHTML = [
    `<span class="fast">⚡ ${Math.round(t.jev_ms)} ms no Jev</span>`,
    `<span>${t.questions} decisões</span>`,
    t.input_tokens != null ? `<span>${t.input_tokens.toLocaleString("pt-BR")} tokens</span>` : "",
    t.cost_usd != null ? `<span>${money(t.cost_usd)}</span>` : "",
    `<span title="Tempo total no servidor, incluindo montagem e validação">servidor ${Math.round(t.server_ms)} ms</span>`,
  ].join("");
}

function renderFilters(view) {
  const tax = state.taxonomy;
  const groups = [
    ["type", "Tipo", Object.entries(tax.types), (i) => [i.type], "artifact_type"],
    ["technology", "Tecnologia", tax.technologies.map((t) => [t, t]), (i) => i.technologies, "technology"],
    ["team", "Time dono", tax.teams.map((t) => [t, t]), (i) => [i.team], "team"],
    ["purpose", "Finalidade", Object.entries(tax.purposes), (i) => [i.purpose], "purpose"],
  ];
  $("filter-groups").innerHTML = groups.map(([group, title, options, values, facetKey]) => {
    const base = view.pool.filter((r) => passesManual(r.item, group));
    const jevValue = view.facets[facetKey]?.confident ? view.facets[facetKey].value : null;
    const rows = options.map(([value, label]) => {
      const count = base.filter((r) => values(r.item).includes(value)).length;
      if (!count && !state.manual[group].has(value)) return "";
      const checked = state.manual[group].has(value) ? "checked" : "";
      const jev = value === jevValue ? " jev" : "";
      return `<label class="${jev}" title="${jev ? "Inferido pelo Jev" : ""}"><input type="checkbox" data-group="${group}" data-value="${esc(value)}" ${checked}>${esc(label)}<span class="count">${count}</span></label>`;
    }).join("");
    return rows ? `<div class="group"><h3>${title}</h3>${rows}</div>` : "";
  }).join("");
}

function renderResults(view) {
  const grid = $("grid");
  const q = $("q").value.trim();
  grid.classList.toggle("preview", view.mode === "local" || Boolean(state.pending && state.jev));
  const titles = {
    all: `Todos os artefatos (${view.rows.length})`,
    local: `Prévia local: ${view.rows.length} com palavras em comum`,
    jev: `${view.rows.length} relevantes para “${state.jev?.query ?? q}”`,
  };
  $("results-title").textContent = titles[view.mode];
  $("results-note").innerHTML = view.mode === "jev" && view.hidden > 0
    ? `${view.hidden} relevantes ocultos pelos filtros` : "";

  const empty = $("empty");
  const rows = view.mode === "all" ? view.rows.filter((r) => passesManual(r.item)) : view.rows.filter((r) => view.mode === "jev" || passesManual(r.item));
  if (view.mode === "jev" && !rows.length) {
    empty.hidden = false;
    empty.innerHTML = view.hidden > 0
      ? `<h3>Os filtros esconderam todos os resultados</h3><p>${view.hidden} artefatos relevantes não passam nos filtros atuais.</p><button type="button" data-action="clear">Remover filtros</button>`
      : `<h3>Nenhum artefato do catálogo atende</h3><p>Nenhum passou da relevância mínima de ${pct(state.thresholds.rel)}. Decidir que não há resposta também é uma decisão.</p><button type="button" data-action="request">Solicitar criação de um artefato</button>`;
  } else if (view.mode === "local" && !rows.length) {
    empty.hidden = false;
    empty.innerHTML = state.configured
      ? `<h3>Nenhuma palavra em comum</h3><p>O Jev avalia pelo significado; aguarde a resposta.</p>`
      : `<h3>Nenhuma palavra em comum</h3><p>Configure a API key para a busca por significado.</p>`;
  } else {
    empty.hidden = true;
  }

  const topRel = Math.max(0.7, state.thresholds.rel);
  grid.innerHTML = rows.slice(0, 60).map((r, index) => card(r, index, view.mode === "jev" && index === 0 && r.rel >= topRel, view)).join("");
}

function card(r, index, top, view) {
  const i = r.item;
  const facets = view.facets || {};
  const techTags = i.technologies.map((t) => {
    const hit = (facets.technology?.confident && facets.technology.value === t) || state.persona.technologies.includes(t);
    return `<span class="tag${hit ? " hit" : ""}">${esc(t)}</span>`;
  }).join("");
  const teamHit = state.persona.team === i.team || (facets.team?.confident && facets.team.value === i.team);
  const purposeHit = facets.purpose?.confident && facets.purpose.value === i.purpose;
  const rel = r.rel == null ? "" : `<div class="rel"><span>${view.mode === "jev" ? "relevância" : "palavras"}</span><div class="bar"><i style="width:${pct(r.rel)}"></i></div><b>${pct(r.rel)}</b></div>`;
  const link = i.url ? `<a href="${esc(i.url)}" target="_blank" rel="noopener noreferrer">ver</a>` : "";
  return `<article class="card${top ? " best" : ""}" style="--delay:${Math.min(index, 12) * 18}ms">
    ${top ? `<span class="ribbon">Recomendado para instalar</span>` : ""}
    <div class="card-head"><span class="type ${esc(i.type)}">${esc(state.taxonomy.types[i.type] || i.type)}</span><h3>${esc(i.name)}</h3></div>
    <p>${esc(i.description)}</p>
    <div class="meta">
      <span class="tag${teamHit ? " hit" : ""}">Time ${esc(i.team)}</span>
      <span class="tag${purposeHit ? " hit" : ""}">${esc(state.taxonomy.purposes[i.purpose] || i.purpose)}</span>
      ${techTags}
    </div>
    ${rel}
    <div class="install"><code title="${esc(i.install)}">${esc(i.install)}</code><button type="button" data-copy="${esc(i.install)}">copiar</button>${link}</div>
    <span class="origin">${esc(i.origin)}${i.installs ? ` · ${i.installs.toLocaleString("pt-BR")} instalações` : ""}</span>
  </article>`;
}

function renderLog(view) {
  const log = $("log");
  if (view.mode !== "jev") { log.hidden = true; return; }
  log.hidden = false;
  const { result } = view;
  const rels = Object.entries(result.relevance).sort((a, b) => b[1] - a[1]);
  $("log-title").textContent = `Decisões desta busca (${result.telemetry.questions}): ${Object.keys(result.facets).length} Choice + ${rels.length + 1} Noul`;

  const facetRows = Object.entries(result.facets).map(([key, f]) => {
    const top = Object.entries(f.probabilities).sort((a, b) => b[1] - a[1]).slice(0, 3)
      .map(([k, p]) => `${esc(key === "purpose" ? state.taxonomy.purposes[k] || k : key === "artifact_type" ? state.taxonomy.types[k] || k : k)} ${pct(p)}`).join(" · ");
    return `<tr><td>${FACET_LABELS[key]}</td><td>${top}</td><td class="num">${pct(f.confidence)}</td></tr>`;
  }).join("");

  const bins = Array(10).fill(0);
  rels.forEach(([, p]) => { bins[Math.min(9, Math.floor(p * 10))] += 1; });
  const max = Math.max(...bins, 1);
  const histo = bins.map((n, b) => `<div title="${b * 10}–${b * 10 + 10}%: ${n}" style="height:${(n / max) * 100}%"></div>`).join("");

  const topRows = rels.slice(0, 12).map(([id, p]) =>
    `<tr><td>${esc(state.byId.get(id)?.name ?? id)}</td><td class="barcell"><div class="bar"><i style="width:${pct(p)}"></i></div></td><td class="num">${pct(p)}</td></tr>`).join("");
  const below = rels.filter(([, p]) => p < 0.1).length;

  $("log-body").innerHTML = `
    <h4>Filtros inferidos (Choice) · top 3 da distribuição · confiança</h4>
    <table>${facetRows}<tr><td>Consulta incompleta</td><td>Noul</td><td class="num">${pct(result.incomplete)}</td></tr></table>
    <h4>Relevância de ${rels.length} artefatos (Noul) · distribuição</h4>
    <div class="histo">${histo}</div><div class="histo-axis"><span>0%</span><span>50%</span><span>100%</span></div>
    <h4>Mais relevantes</h4>
    <table>${topRows}</table>
    <p class="hint">${below} artefatos ficaram abaixo de 10%. Modelo: ${esc(result.model)}.</p>`;
}

let toastTimer;
function toast(text) {
  const el = $("toast");
  el.textContent = text;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 2200);
}

init();
