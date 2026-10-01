// Tela-alvo do demo: um cadastro com validações reais e dois defeitos plantados.
// O Screen Scout não conhece este arquivo; ele descobre o comportamento explorando a tela.
//
// Defeitos de propósito (é o que a exploração deve encontrar):
//   1. CPF: só confere a máscara, não os dígitos verificadores.
//   2. Salário: aceita valor negativo ou zero.

const form = document.getElementById("form");
const resumo = document.getElementById("resumo");
const toast = document.getElementById("toast");

const onlyDigits = (value) => value.replace(/\D/g, "");

function mask(input, format) {
  input.addEventListener("input", () => {
    input.value = format(onlyDigits(input.value));
  });
}

mask(document.getElementById("cpf"), (d) => {
  d = d.slice(0, 11);
  return d
    .replace(/^(\d{3})(\d)/, "$1.$2")
    .replace(/^(\d{3})\.(\d{3})(\d)/, "$1.$2.$3")
    .replace(/\.(\d{3})(\d{1,2})$/, ".$1-$2");
});
mask(document.getElementById("cep"), (d) => d.slice(0, 8).replace(/^(\d{5})(\d)/, "$1-$2"));
mask(document.getElementById("celular"), (d) => {
  d = d.slice(0, 11);
  if (d.length <= 2) return d.length ? `(${d}` : "";
  const tail = d.slice(2);
  const split = tail.length > 8 ? 5 : 4;
  return `(${d.slice(0, 2)}) ${tail.slice(0, split)}${tail.length > split ? "-" : ""}${tail.slice(split)}`;
});
for (const id of ["nascimento", "admissao"]) {
  mask(document.getElementById(id), (d) =>
    d.slice(0, 8).replace(/^(\d{2})(\d)/, "$1/$2").replace(/^(\d{2})\/(\d{2})(\d)/, "$1/$2/$3"),
  );
}

function parseDate(text) {
  const match = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(text);
  if (!match) return null;
  const [, dd, mm, yyyy] = match.map(Number);
  const date = new Date(yyyy, mm - 1, dd);
  const valid = date.getFullYear() === yyyy && date.getMonth() === mm - 1 && date.getDate() === dd;
  return valid ? date : null;
}

function parseMoney(text) {
  const normalized = text.trim().replace(/\./g, "").replace(",", ".");
  if (!/^-?\d+(\.\d{1,2})?$/.test(normalized)) return null;
  return Number(normalized);
}

const rules = {
  nome: (v) => {
    if (!v.trim()) return "Informe o nome completo.";
    if (v.trim().split(/\s+/).length < 2) return "Informe nome e sobrenome.";
    return "";
  },
  cpf: (v) => {
    if (!v) return "Informe o CPF.";
    // Defeito 1: falta validar os dígitos verificadores.
    if (!/^\d{3}\.\d{3}\.\d{3}-\d{2}$/.test(v)) return "CPF deve ter 11 dígitos.";
    return "";
  },
  nascimento: (v) => {
    if (!v) return "Informe a data de nascimento.";
    const date = parseDate(v);
    if (!date) return "Data inválida.";
    if (date > new Date()) return "A data de nascimento não pode estar no futuro.";
    const limit = new Date();
    limit.setFullYear(limit.getFullYear() - 14);
    if (date > limit) return "O colaborador deve ter pelo menos 14 anos.";
    return "";
  },
  email: (v) => {
    if (!v.trim()) return "Informe o e-mail corporativo.";
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v.trim())) return "E-mail inválido.";
    return "";
  },
  celular: (v) => (v && !/^\(\d{2}\) \d{4,5}-\d{4}$/.test(v) ? "Celular inválido." : ""),
  cep: (v) => (v && !/^\d{5}-\d{3}$/.test(v) ? "CEP inválido." : ""),
  admissao: (v) => {
    if (!v) return "Informe a data de admissão.";
    return parseDate(v) ? "" : "Data inválida.";
  },
  cargo: (v) => (v ? "" : "Selecione o cargo."),
  centro: (v) => (v ? "" : "Selecione o centro de custo."),
  salario: (v) => {
    if (!v.trim()) return "Informe o salário base.";
    // Defeito 2: falta exigir valor maior que zero.
    return parseMoney(v) === null ? "Valor inválido." : "";
  },
};

function clearErrors() {
  resumo.hidden = true;
  resumo.textContent = "";
  for (const id of Object.keys(rules)) {
    const input = document.getElementById(id);
    input.removeAttribute("aria-invalid");
    input.removeAttribute("aria-describedby");
    document.getElementById(`${id}-erro`).textContent = "";
  }
}

function validate() {
  clearErrors();
  let errors = 0;
  for (const [id, rule] of Object.entries(rules)) {
    const input = document.getElementById(id);
    const message = rule(input.value);
    if (message) {
      errors += 1;
      input.setAttribute("aria-invalid", "true");
      input.setAttribute("aria-describedby", `${id}-erro`);
      document.getElementById(`${id}-erro`).textContent = message;
    }
  }
  if (errors) {
    resumo.hidden = false;
    resumo.textContent =
      errors === 1 ? "Revise o campo destacado." : `Revise os ${errors} campos destacados.`;
  }
  return errors === 0;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  toast.textContent = "";
  if (!validate()) return;
  const data = Object.fromEntries(new FormData(form));
  const response = await fetch("/alvo/api/colaboradores", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!response.ok) {
    toast.textContent = "Não foi possível salvar agora. Tente novamente.";
    return;
  }
  const { matricula } = await response.json();
  toast.textContent = `Colaborador ${data.nome.trim()} cadastrado com sucesso. Matrícula ${matricula}.`;
  form.reset();
});

document.getElementById("limpar").addEventListener("click", () => {
  form.reset();
  clearErrors();
  toast.textContent = "";
});

const dialog = document.getElementById("dlg-ajuda");
document.getElementById("ajuda").addEventListener("click", () => dialog.showModal());
document.getElementById("fechar-ajuda").addEventListener("click", () => dialog.close());

document.getElementById("aprovacao").addEventListener("click", async () => {
  if (!validate()) return;
  await fetch("/alvo/api/aprovacoes", { method: "POST" });
  toast.textContent = "Cadastro enviado para aprovação do gestor.";
});

document.getElementById("excluir").addEventListener("click", () => {
  if (confirm("Excluir este rascunho? Esta ação não pode ser desfeita.")) {
    form.reset();
    clearErrors();
    toast.textContent = "Rascunho excluído.";
  }
});
