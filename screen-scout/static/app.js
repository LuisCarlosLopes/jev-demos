// Screen Scout: interface. Todo texto vindo da tela explorada é escapado antes de ir ao DOM.

const $ = (selector) => document.querySelector(selector);
const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const pct = (value) => (value == null ? "—" : `${Math.round(value * 100)}%`);
const num = (value, digits = 1) => value.toFixed(digits).replace(".", ",");
const fmtMs = (value) => (value == null ? "—" : value >= 1000 ? `${num(value / 1000)} s` : `${Math.round(value)} ms`);
const usd = (value) => `US$ ${(value || 0).toFixed(5).replace(".", ",")}`;
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const JEV_STEPS = new Set(["classify", "oracle"]);
const EXPECT_LABEL = { accept: "aceitar", reject: "recusar", observe: "observar", check: "verificar" };
const STATUS_TEXT = {
  ok: "✅ conforme", divergence: "❌ divergência", uncertain: "⚠️ revisar", observed: "🔎 observado",
  manual: "✋ manual", not_run: "⏸️ não executado", error: "💥 falhou",
};

let config = null;
let jobId = null;
let result = null;
let lang = "python";

// Escapa e depois mostra `trechos` como código (vêm dos textos do próprio demo).
const code = (text) => esc(text).replace(/`([^`]+)`/g, "<code>$1</code>");

function conf(value) {
  if (value == null) return "";
  return `<span class="conf" title="confiança ${pct(value)}"><i style="width:${Math.round(value * 100)}%"></i></span>`;
}

function isLocal(url) {
  try {
    const host = new URL(url).hostname;
    return host === "localhost" || host === "127.0.0.1" || host === "[::1]" || host.endsWith(".localhost") || host.endsWith(".test");
  } catch {
    return false;
  }
}

function updateSubmitHint() {
  const url = $("#url").value.trim();
  const local = isLocal(url);
  const hint = $("#submit-hint");
  if (!local && $("#allow-submit").checked) {
    hint.textContent = "Endereço não local: as sondagens vão gravar registros. Use só em ambiente de teste.";
    hint.className = "hint warn";
  } else if (!local) {
    hint.textContent = "Sem envio: só as verificações que não gravam (limites, limpar, navegação).";
    hint.className = "hint";
  } else {
    hint.textContent = $("#allow-submit").checked ? "Endereço local: as sondagens gravam registros de teste." : "";
    hint.className = "hint";
  }
  $("#open-target").href = url || "#";
}

// --- Etapas e sondagens ---------------------------------------------------------------------

function renderSteps(steps) {
  $("#steps").innerHTML = steps
    .map((step) => {
      const cls = ["step", step.status, JEV_STEPS.has(step.key) ? "jev" : ""].join(" ");
      const value = step.status === "done" ? fmtMs(step.ms) : step.status === "running" ? "…" : "—";
      let detail = step.detail || "";
      if (step.cached) detail += " · cache";
      return `<li class="${cls}"><div class="label">${esc(step.label.replace(" · Jev", ""))}</div>
        <div class="ms">${value}</div><div class="detail">${esc(detail)}</div></li>`;
    })
    .join("");
}

function renderTiles(probes, statuses = {}) {
  const grid = $("#probe-grid");
  if (!probes || !probes.items.length) {
    grid.innerHTML = "";
    $("#probe-count").textContent = "—";
    return;
  }
  $("#probe-count").textContent = `${probes.done}/${probes.total}`;
  grid.innerHTML = probes.items
    .map((item) => {
      const status = statuses[item.id] || (item.status === "done" ? "done" : item.status === "error" ? "error" : "");
      const title = `${item.title}${item.ms ? ` · ${fmtMs(item.ms)}` : ""}`;
      return `<span class="tile ${status}" title="${esc(title)}"></span>`;
    })
    .join("");
}

// --- Resultado ------------------------------------------------------------------------------

function showSummary(r) {
  const meta = r.meta;
  const found = r.findings;
  const automated = r.cases.filter((c) => c.automated).length;
  const stats = [
    { value: fmtMs(meta.total_ms), caption: `para explorar a tela · ${meta.probes} sondagens` },
    { value: meta.decisions, caption: `decisões do Jev em ${meta.jev_requests} requisições` },
    { value: meta.cost_label.replace("US$ ", "US$ "), caption: `${(meta.tokens || 0).toLocaleString("pt-BR")} tokens de entrada` },
    { value: `${r.cases.length}`, caption: `cenários no plano · ${automated} testes gerados` },
    {
      value: found.divergences.length,
      caption: found.divergences.length === 1 ? "divergência encontrada" : "divergências encontradas",
      cls: found.divergences.length ? "bad" : "ok",
    },
  ];
  $("#summary").innerHTML = stats
    .map((s) => `<div class="stat ${s.cls || ""}"><div class="value">${esc(s.value)}</div><div class="caption">${esc(s.caption)}</div></div>`)
    .join("");
  $("#summary").hidden = false;
}

function locatorText(spec) {
  if (!spec) return "sem localizador";
  const q = (v) => JSON.stringify(v);
  switch (spec.method) {
    case "label": return `get_by_label(${q(spec.value)}${spec.exact ? ", exact=True" : ""})`;
    case "role": return `get_by_role(${q(spec.role)}, name=${q(spec.value)}${spec.exact === false ? "" : ", exact=True"})`;
    case "placeholder": return `get_by_placeholder(${q(spec.value)})`;
    case "test_id": return `get_by_test_id(${q(spec.value)})`;
    case "text": return `get_by_text(${q(spec.value)})`;
    default: return `locator(${q(spec.value)})`;
  }
}

function elementInfo(r) {
  const fields = Object.fromEntries(r.profile.fields.map((f) => [f.id, f]));
  const actions = Object.fromEntries(r.profile.actions.map((a) => [a.id, a]));
  const skipped = Object.fromEntries(r.profile.skipped.map((s) => [s.id, s]));
  return r.screen.elements.map((element, index) => {
    const field = fields[element.id];
    const action = actions[element.id];
    let cls = element.kind === "field" ? "field" : "action";
    if (action && action.risky) cls = "risky";
    if ((field && field.uncertain) || (action && action.uncertain)) cls += " unsure";
    if (skipped[element.id] || (!field && !action)) cls = "skipped";
    return { element, field, action, skipped: skipped[element.id], cls, n: index + 1 };
  });
}

function showScreen(r) {
  const infos = elementInfo(r);
  const { width, height } = r.screen;
  const frame = $("#shot-frame");
  frame.innerHTML = r.screen.screenshot ? `<img alt="Captura da tela explorada" src="${r.screen.screenshot}">` : "";
  for (const info of infos) {
    const box = info.element.box;
    if (!box || !box.w) continue;
    const div = document.createElement("div");
    div.className = `box ${info.cls}`;
    div.dataset.id = info.element.id;
    div.style.left = `${(box.x / width) * 100}%`;
    div.style.top = `${(box.y / height) * 100}%`;
    div.style.width = `${(box.w / width) * 100}%`;
    div.style.height = `${(box.h / height) * 100}%`;
    div.innerHTML = `<span>${info.n}</span>`;
    div.title = info.element.name;
    frame.appendChild(div);
  }
  $("#element-list").innerHTML = infos
    .map((info) => {
      const chips = [];
      const { field, action } = info;
      if (field) {
        if (field.kind_label) {
          chips.push(field.kind_source === "jev"
            ? `<span class="chip jev">${esc(field.kind_label)} ${conf(field.kind_confidence)}</span>`
            : `<span class="chip dom">${esc(field.kind_label)} · HTML</span>`);
        } else {
          chips.push(`<span class="chip dom">${esc({ select: "lista", check: "caixa de seleção", radio: "opções" }[field.control] || field.control)}</span>`);
        }
        if (field.required_source === "dom") chips.push(`<span class="chip dom">obrigatório · HTML</span>`);
        else if (field.required_p != null) {
          chips.push(field.required
            ? `<span class="chip jev">obrigatório · Jev ${pct(field.required_p)}</span>`
            : `<span class="chip dom">opcional · Jev ${pct(field.required_p)}</span>`);
        }
        if (field.uncertain) chips.push(`<span class="chip warn">revisar</span>`);
      } else if (action) {
        chips.push(`<span class="chip jev">${esc(action.role_label)} ${conf(action.role_confidence)}</span>`);
        if (action.risky) chips.push(`<span class="chip bad" title="${esc(action.risky_reason)}">não clicado · risco ${pct(action.risk_p)}</span>`);
        else chips.push(`<span class="chip dom">risco ${pct(action.risk_p)}</span>`);
        if (r.profile.submit === action.id) chips.push(`<span class="chip ok">salva o formulário</span>`);
        if (action.uncertain) chips.push(`<span class="chip warn">revisar</span>`);
      } else {
        chips.push(`<span class="chip warn">${esc(info.skipped ? info.skipped.reason : "ignorado")}</span>`);
      }
      const value = field && field.valid != null
        ? `<div class="loc">massa válida: ${esc(field.valid === true ? "marcado" : field.valid)}</div>` : "";
      const spec = (field || action || {}).locator;
      return `<li class="element" data-id="${esc(info.element.id)}"><span class="n">${info.n}</span>
        <span class="name">${esc(info.element.name || "(sem nome)")}</span>
        <span class="facts">${chips.join("")}</span>
        <span class="loc">${esc(locatorText(spec))}</span>${value}</li>`;
    })
    .join("");
  const hover = (id, on) => {
    document.querySelectorAll(`[data-id="${CSS.escape(id)}"]`).forEach((el) => el.classList.toggle("hot", on));
  };
  document.querySelectorAll("#shot-frame .box, #element-list .element").forEach((el) => {
    el.addEventListener("mouseenter", () => hover(el.dataset.id, true));
    el.addEventListener("mouseleave", () => hover(el.dataset.id, false));
  });
}

function findingList(items, cls, empty) {
  if (!items.length) return `<p class="empty">${esc(empty)}</p>`;
  return items
    .map((item) => `<div class="finding ${cls}"><b>${esc(item.number ? `${item.number} ${item.title}` : item.title)}</b>${code(item.summary || "")}</div>`)
    .join("");
}

function showFindings(r) {
  const f = r.findings;
  const risky = r.profile.actions.filter((a) => a.risky)
    .map((a) => ({ title: `“${a.label}” · ${a.role_label}`, summary: `Não clicado: ${a.risky_reason}. Fica como teste manual no plano.` }));
  $("#findings-count").textContent = f.divergences.length ? f.divergences.length : "";
  $("#findings").innerHTML = `
    <section><h3>Divergências (a tela não fez o esperado)</h3>${findingList(f.divergences, "bad", "Nenhuma divergência.")}</section>
    <section><h3>Para revisar (o Jev ou a observação não foram conclusivos)</h3>${findingList(f.uncertain, "warn", "Nada para revisar.")}</section>
    <section><h3>Comportamentos observados (confirmar com o PO)</h3>${findingList(f.observed, "info", "Nenhum.")}</section>
    <section><h3>Acessibilidade</h3>${findingList(f.accessibility.map((t) => ({ title: "Achado determinístico", summary: t })), "a11y", "Nada encontrado.")}</section>
    <section><h3>Ações de risco</h3>${findingList(risky, "", "Nenhuma ação de risco.")}</section>`;
}

function showProbes(r) {
  const labels = Object.fromEntries(r.profile.fields.map((f) => [f.id, f.label]));
  labels.general = "geral";
  labels.none = "—";
  const rows = r.results.map((item) => {
    const obs = item.observation || {};
    const lines = (obs.new_text || []).slice(0, 3).map((l) => `<li>“${esc(l)}”</li>`).join("");
    const outcome = item.outcome_label
      ? `${esc(item.outcome_label)} ${conf(item.outcome_confidence)}`
      : `<span class="muted">${esc(item.summary)}</span>`;
    const value = item.value === "" || item.value === false ? "(vazio)" : item.value == null ? "" : String(item.value);
    const shown = value.length > 40 ? `${value.slice(0, 40)}…` : value;
    return `<tr><td class="num">${esc(item.id)}</td><td>${esc(item.title)}${lines ? `<ul class="lines">${lines}</ul>` : ""}</td>
      <td><code>${esc(shown)}</code></td><td>${esc(EXPECT_LABEL[item.expect] || item.expect)}</td>
      <td>${outcome}</td><td>${esc(item.blame ? labels[item.blame] || item.blame : "")}</td>
      <td><span class="status ${esc(item.status)}">${esc(STATUS_TEXT[item.status])}</span></td>
      <td class="num">${fmtMs(item.ms)}</td></tr>`;
  });
  $("#probe-table").innerHTML = `<thead><tr><th>#</th><th>Sondagem</th><th>Valor</th><th>Esperado</th>
    <th>Oráculo (Jev)</th><th>Campo apontado</th><th>Veredicto</th><th>Tempo</th></tr></thead><tbody>${rows.join("")}</tbody>`;
}

function showPlan(r) {
  const groups = [];
  for (const c of r.cases) {
    if (!groups.length || groups[groups.length - 1].label !== c.group_label) groups.push({ label: c.group_label, cases: [] });
    groups[groups.length - 1].cases.push(c);
  }
  $("#plan").innerHTML = groups
    .map((g) => `<section class="plan-group"><h3>${esc(g.cases[0].number.split(".")[0])}. ${esc(g.label)}</h3>${g.cases.map(renderCase).join("")}</section>`)
    .join("");
  $("#download-plan").href = `/api/jobs/${jobId}/files/plan`;
}

function renderCase(c) {
  const items = [];
  for (const step of c.steps) {
    if (step.op.startsWith("expect")) {
      if (!items.length) items.push({ text: "Verificar", expects: [] });
      items[items.length - 1].expects.push(step.text);
    } else {
      items.push({ text: step.text, expects: [] });
    }
  }
  const steps = items.length
    ? `<ol>${items.map((i) => `<li>${esc(i.text)}${i.expects.length ? `<ul>${i.expects.map((e) => `<li>esperado: ${esc(e)}</li>`).join("")}</ul>` : ""}</li>`).join("")}</ol>`
    : c.expects.length ? `<ul>${c.expects.map((e) => `<li>esperado: ${esc(e)}</li>`).join("")}</ul>` : "";
  const auto = c.automated ? (c.skip_reason ? " · gerado com skip" : " · automatizado") : " · só no plano";
  return `<article class="case"><div class="case-head"><span class="num">${esc(c.number)}</span>
      <span class="title">${esc(c.title)}</span><span class="prio ${esc(c.priority)}">${esc(c.priority)}</span>
      <span class="status ${esc(c.status)}">${esc(STATUS_TEXT[c.status])}</span></div>
    <div class="obs">${esc(c.observed)}${esc(auto)}</div>
    ${c.note ? `<div class="note">${esc(c.note)}</div>` : ""}${steps}</article>`;
}

function highlight(code, language) {
  const keywords = language === "python"
    ? "def|return|import|from|if|elif|else|for|in|not|and|or|None|True|False|with|as|assert"
    : "import|from|const|function|async|await|return|if|else|for|of|in|type|test|true|false";
  const comment = language === "python" ? "#[^\\n]*" : "\\/\\/[^\\n]*";
  const token = new RegExp(`(${comment})|("""[\\s\\S]*?"""|"(?:[^"\\\\\\n]|\\\\.)*"|'(?:[^'\\\\\\n]|\\\\.)*')|\\b(${keywords})\\b`, "g");
  let out = "";
  let last = 0;
  for (const match of code.matchAll(token)) {
    out += esc(code.slice(last, match.index));
    const cls = match[1] ? "c" : match[2] ? "s" : "k";
    out += `<span class="${cls}">${esc(match[0])}</span>`;
    last = match.index + match[0].length;
  }
  return out + esc(code.slice(last));
}

function showCode() {
  if (!result) return;
  const file = result.files[lang];
  $("#code").innerHTML = highlight(file.content, lang);
  $("#download-code").href = `/api/jobs/${jobId}/files/${lang}`;
  $("#download-code").textContent = `Baixar ${file.name}`;
  document.querySelectorAll(".segmented button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === lang)));
}

function showCost(r) {
  const timings = r.meta.timings || [];
  const total = Math.max(1, ...timings.map((t) => t.ms || 0));
  const bars = timings
    .map((t) => `<div class="bar-row"><span>${esc(t.label)}</span><span class="bar"><i class="${JEV_STEPS.has(t.key) ? "jev" : ""}" style="width:${Math.max(1, ((t.ms || 0) / total) * 100)}%"></i></span><span class="v">${fmtMs(t.ms)}</span></div>`)
    .join("");
  const requests = timings.filter((t) => JEV_STEPS.has(t.key) && t.questions);
  const jevMs = requests.reduce((sum, t) => sum + (t.jev_ms || 0), 0);
  const probes = timings.find((t) => t.key === "probes");
  const rows = requests
    .map((t) => `<tr><td>${esc(t.label.replace(" · Jev", ""))}</td><td class="num">${t.questions}</td><td class="num">${(t.tokens || 0).toLocaleString("pt-BR")}</td><td class="num">${t.cached ? "cache" : fmtMs(t.jev_ms)}</td><td class="num">${usd(t.cost)}</td></tr>`)
    .join("");
  const aria = r.meta.aria_tokens;
  $("#cost").innerHTML = `
    <div class="card"><h3>Onde foi o tempo</h3>${bars}
      <p class="muted small">As duas etapas do Jev somam ${fmtMs(jevMs)} de ${fmtMs(r.meta.total_ms)}. O resto é navegador:
      ${r.meta.probes} sondagens em ${r.meta.concurrency} páginas paralelas (${fmtMs(probes ? probes.ms : null)}).</p></div>
    <div class="card"><h3>Requisições ao Jev</h3>
      <div class="table-wrap"><table class="grid"><thead><tr><th>Etapa</th><th>Perguntas</th><th>Tokens</th><th>Tempo</th><th>Custo</th></tr></thead><tbody>${rows}</tbody></table></div>
      <p>Cada requisição avalia todas as perguntas em paralelo sobre o mesmo estado: dezenas de decisões custam uma ida e volta.
      Saída não é cobrada; o custo é só de entrada (US$ 0,042 por milhão de tokens).</p>
      <p class="muted small">Referência: o snapshot ARIA desta tela tem cerca de ${(aria || 0).toLocaleString("pt-BR")} tokens (estimativa: caracteres ÷ 4).
      No fluxo plan → generate → heal com um LLM, o agente relê um snapshot a cada ação e gera texto a cada passo, um cenário por vez.
      Aqui as ${r.meta.decisions} decisões saíram em ${r.meta.jev_requests} requisições, e o texto do plano e do código vem do catálogo, sem geração.</p>
      <p class="muted small">Modelo: ${esc(r.meta.model)} · navegador: ${esc(r.meta.browser)}${r.meta.simulated ? " · <b>simulado</b>" : ""}</p></div>`;
}

function showResult(r) {
  result = r;
  const statuses = Object.fromEntries(r.results.map((item) => [item.id, item.status]));
  renderSteps(r.meta.timings);
  renderTiles({ total: r.results.length, done: r.results.length, items: r.results.map((i) => ({ id: i.id, title: i.title, ms: i.ms, status: "done" })) }, statuses);
  showSummary(r);
  showScreen(r);
  showFindings(r);
  showProbes(r);
  showPlan(r);
  showCode();
  showCost(r);
  $("#run-result").hidden = true;
  $("#results").hidden = false;
}

// --- Fluxo ------------------------------------------------------------------------------------

async function explore(event) {
  event.preventDefault();
  const url = $("#url").value.trim();
  $("#error").hidden = true;
  $("#explore").disabled = true;
  $("#explore").textContent = "Explorando…";
  $("#summary").hidden = true;
  $("#results").hidden = true;
  renderTiles(null);
  try {
    const response = await fetch("/api/explore", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url,
        allow_submit: $("#allow-submit").checked,
        confidence: Number($("#confidence").value),
        risk: Number($("#risk").value),
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Não foi possível iniciar a exploração.");
    jobId = data.id;
    while (true) {
      const snap = await (await fetch(`/api/jobs/${jobId}`)).json();
      renderSteps(snap.steps);
      renderTiles(snap.probes);
      if (snap.status === "done") {
        const full = await (await fetch(`/api/jobs/${jobId}?full=1`)).json();
        showResult(full.result);
        refreshSession();
        break;
      }
      if (snap.status === "error") throw new Error(snap.error);
      await sleep(120);
    }
  } catch (error) {
    $("#error").textContent = error.message;
    $("#error").hidden = false;
  } finally {
    $("#explore").disabled = false;
    $("#explore").textContent = "Explorar tela";
  }
}

async function runTests() {
  const button = $("#run-tests");
  const box = $("#run-result");
  const total = result.cases.filter((c) => c.automated).length;
  button.disabled = true;
  button.textContent = "Rodando…";
  box.hidden = false;
  box.innerHTML = `<span class="muted">Rodando ${total} testes com pytest-playwright num processo separado. Os que falham esperam o timeout de 5 s do expect.</span>`;
  try {
    const response = await fetch(`/api/jobs/${jobId}/run`, { method: "POST" });
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.detail || data.error || "Falha ao rodar os testes.");
    const s = data.summary;
    const cases = Object.fromEntries(result.cases.map((c) => [c.number, c]));
    const order = { failed: 0, error: 0, skipped: 1, passed: 2 };
    const tests = [...data.tests].sort((a, b) => order[a.status] - order[b.status]);
    box.innerHTML = `<div class="totals"><span class="pass">${s.passed} passaram</span><span class="fail">${s.failed + s.error} falharam</span>
        <span class="skip">${s.skipped} pulados</span><span class="muted">${fmtMs(data.ms)} · ${esc(data.folder)}</span></div>
      <ul>${tests.map((t) => {
        const c = cases[t.case];
        const icon = t.status === "passed" ? `<span class="pass">✓</span>` : t.status === "skipped" ? `<span class="skip">↷</span>` : `<span class="fail">✗</span>`;
        const label = c ? `${c.number} ${c.title}` : t.name;
        const why = t.status === "passed" ? "" : ` <small>${esc(t.message)}</small>`;
        const hint = t.status === "failed" && c && c.status === "divergence" ? ` <small>(divergência prevista na exploração)</small>` : "";
        return `<li>${icon} ${esc(label)} <small>${fmtMs(t.ms)}</small>${hint}${why}</li>`;
      }).join("")}</ul>`;
  } catch (error) {
    box.innerHTML = `<span class="fail">${esc(error.message)}</span>`;
  } finally {
    button.disabled = false;
    button.textContent = "Rodar testes Python";
  }
}

// --- Sessão (telas com login) ----------------------------------------------------------------

let sessionTimer = null;

async function refreshSession() {
  const url = $("#url").value.trim();
  const state = $("#session-state");
  if (!/^https?:\/\//.test(url)) {
    state.textContent = "";
    return;
  }
  try {
    const info = await (await fetch(`/api/session?url=${encodeURIComponent(url)}`)).json();
    if (info.exists) {
      const until = info.expires_at ? ` · expira ${info.expires_at}` : "";
      state.textContent = info.expired
        ? `sessão de ${info.host} expirada: entre de novo`
        : `sessão salva para ${info.host} (${info.saved_at}${until})`;
      state.className = info.expired ? "hint warn" : "hint ok";
      $("#login").textContent = "Entrar de novo…";
    } else {
      state.textContent = "sem sessão: telas com login param na página de login";
      state.className = "hint";
      $("#login").textContent = "Entrar…";
    }
    $("#forget").hidden = !info.exists;
  } catch {
    state.textContent = "";
  }
}

async function login() {
  const url = $("#url").value.trim();
  const button = $("#login");
  const state = $("#session-state");
  button.disabled = true;
  state.className = "hint warn";
  state.textContent = "Janela do navegador aberta: faça o login nela. A sessão é salva quando a tela carregar (até 5 min).";
  try {
    const response = await fetch("/api/session/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Não foi possível salvar a sessão.");
    await refreshSession();
  } catch (error) {
    state.className = "hint warn";
    state.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

async function forget() {
  const url = $("#url").value.trim();
  await fetch(`/api/session?url=${encodeURIComponent(url)}`, { method: "DELETE" });
  await refreshSession();
}

function selectTab(name) {
  document.querySelectorAll(".tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
  document.querySelectorAll(".tab").forEach((panel) => { panel.hidden = panel.dataset.panel !== name; });
}

async function init() {
  config = await (await fetch("/api/config")).json();
  $("#url").value = config.sample_url;
  $("#simulated").hidden = !config.simulated;
  $("#unconfigured").hidden = config.configured;
  $("#badges").innerHTML = [
    `modelo <b>${esc(config.model)}</b>`, `navegador <b>${esc(config.browser)}</b>`, `paralelo <b>${config.concurrency}</b>`,
  ].map((t) => `<span class="badge">${t}</span>`).join("");
  renderSteps([
    ["browser", "Navegador"], ["capture", "Captura da tela"], ["classify", "Classificação · Jev"],
    ["probes", "Sondagens · Playwright"], ["oracle", "Oráculo · Jev"], ["generate", "Plano e testes"],
  ].map(([key, label]) => ({ key, label, status: "pending" })));
  updateSubmitHint();
  $("#explore-form").addEventListener("submit", explore);
  $("#url").addEventListener("input", () => {
    $("#allow-submit").checked = isLocal($("#url").value.trim());
    updateSubmitHint();
    clearTimeout(sessionTimer);
    sessionTimer = setTimeout(refreshSession, 300);
  });
  $("#login").addEventListener("click", login);
  $("#forget").addEventListener("click", forget);
  // A sessão pode ter sido salva por outra aba ou pela CLI.
  window.addEventListener("focus", refreshSession);
  refreshSession();
  $("#allow-submit").addEventListener("change", updateSubmitHint);
  for (const id of ["confidence", "risk"]) {
    $(`#${id}`).addEventListener("input", () => { $(`#${id}-out`).textContent = pct(Number($(`#${id}`).value)); });
  }
  document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => selectTab(b.dataset.tab)));
  document.querySelectorAll(".segmented button").forEach((b) => b.addEventListener("click", () => { lang = b.dataset.lang; showCode(); }));
  $("#run-tests").addEventListener("click", runTests);
}

init();
