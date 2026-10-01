"""Catálogo de peças que o Jev escolhe: tipos de dado, papéis de ação, tipos de tela e desfechos.

O Jev não gera texto nem código. Ele escolhe uma opção deste catálogo para cada elemento da
tela, e cada opção já traz a massa de teste (valores válidos e inválidos) e o texto do plano.
É isso que torna a geração determinística: o mesmo conjunto de decisões produz sempre o mesmo
plano e o mesmo código.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta


def _cpf_digits(base: str) -> str:
    """Acrescenta os dois dígitos verificadores a 9 dígitos de CPF."""
    digits = [int(c) for c in base]
    for size in (9, 10):
        total = sum(d * w for d, w in zip(digits, range(size + 1, 1, -1), strict=True))
        rest = (total * 10) % 11
        digits.append(0 if rest == 10 else rest)
    return "".join(map(str, digits))


def _cnpj_digits(base: str) -> str:
    """Acrescenta os dois dígitos verificadores a 12 dígitos de CNPJ."""
    digits = [int(c) for c in base]
    for weights in ([5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]):
        rest = sum(d * w for d, w in zip(digits, weights, strict=True)) % 11
        digits.append(0 if rest < 2 else 11 - rest)
    return "".join(map(str, digits))


def _fmt_cpf(d: str) -> str:
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"


def _fmt_cnpj(d: str) -> str:
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


def _wrong_last_digit(digits: str) -> str:
    return digits[:-1] + str((int(digits[-1]) + 1) % 10)


def _br(day: date) -> str:
    return day.strftime("%d/%m/%Y")


def _next_year(today: date) -> date:
    try:
        return today.replace(year=today.year + 1)
    except ValueError:  # 29/02
        return today + timedelta(days=365)


CPF_VALID = _cpf_digits("529982247")
CNPJ_VALID = _cnpj_digits("112223330001")


@dataclass(frozen=True)
class Probe:
    """Um valor de sondagem para um tipo de dado."""

    key: str
    value: str
    title: str  # nome do cenário; {campo} vira o rótulo do campo
    # reject: a tela deveria recusar · observe: não há regra universal, só registramos
    expect: str = "reject"


@dataclass(frozen=True)
class DataKind:
    label: str
    describe: str  # critério em inglês para o Choice do Jev
    valid: str
    invalid: tuple[Probe, ...] = ()
    # Validar este tipo pesa mais quando a tela lida com dados pessoais ou dinheiro.
    sensitive: bool = False
    # Valores dependentes da data de hoje ficam em funções, resolvidas na hora da exploração.
    dynamic: dict = field(default_factory=dict)


def data_kinds(today: date | None = None) -> dict[str, DataKind]:
    today = today or date.today()
    return {
        "person_name": DataKind(
            "Nome de pessoa",
            "A person's name: full name, first name, surname or social name.",
            "Maria Aparecida Souza",
            (Probe("single_word", "Maria", "{campo} com uma palavra só", "observe"),),
        ),
        "cpf": DataKind(
            "CPF",
            "Brazilian individual taxpayer number (CPF): 11 digits, usually 000.000.000-00.",
            _fmt_cpf(CPF_VALID),
            (
                Probe("check_digit", _fmt_cpf(_wrong_last_digit(CPF_VALID)),
                      "{campo} com dígito verificador inválido"),
                Probe("repeated", "111.111.111-11", "{campo} com todos os dígitos iguais"),
                Probe("incomplete", "529.982.247", "{campo} incompleto"),
            ),
            sensitive=True,
        ),
        "cnpj": DataKind(
            "CNPJ",
            "Brazilian company registration number (CNPJ): 14 digits, 00.000.000/0000-00.",
            _fmt_cnpj(CNPJ_VALID),
            (
                Probe("check_digit", _fmt_cnpj(_wrong_last_digit(CNPJ_VALID)),
                      "{campo} com dígito verificador inválido"),
                Probe("incomplete", "11.222.333/0001", "{campo} incompleto"),
            ),
            sensitive=True,
        ),
        "email": DataKind(
            "E-mail",
            "An e-mail address.",
            "maria.souza@empresa.com.br",
            (
                Probe("no_domain", "maria.souza@", "{campo} sem domínio"),
                Probe("space", "maria souza@empresa.com.br", "{campo} com espaço"),
            ),
            sensitive=True,
        ),
        "phone": DataKind(
            "Telefone",
            "A phone or mobile number.",
            "(47) 99876-5432",
            (Probe("incomplete", "(47) 9987", "{campo} incompleto"),),
        ),
        "cep": DataKind(
            "CEP",
            "Brazilian postal code (CEP): 8 digits, 00000-000.",
            "89010-000",
            (Probe("incomplete", "8901", "{campo} incompleto"),),
        ),
        "birth_date": DataKind(
            "Data no passado",
            "A date of birth, or another date that must be in the past.",
            "15/03/1990",
            (
                Probe("impossible", "31/02/1990", "{campo} com data inexistente"),
                Probe("future", _br(_next_year(today)), "{campo} no futuro"),
            ),
            sensitive=True,
        ),
        "date": DataKind(
            "Data",
            "A calendar date that may be in the past or future: admission, start, end or due date.",
            _br(today),
            (Probe("impossible", f"31/02/{today.year}", "{campo} com data inexistente"),),
        ),
        "money": DataKind(
            "Valor em reais",
            "A monetary amount in reais: salary, price, fee, limit or balance.",
            "4.500,00",
            (
                Probe("negative", "-1.500,00", "{campo} negativo"),
                Probe("letters", "abc", "{campo} com letras"),
                Probe("zero", "0,00", "{campo} zero", "observe"),
            ),
            sensitive=True,
        ),
        "quantity": DataKind(
            "Número inteiro",
            "A whole number: quantity, count, age, number of items or days.",
            "10",
            (
                Probe("negative", "-1", "{campo} negativo"),
                Probe("letters", "abc", "{campo} com letras"),
            ),
        ),
        "percentage": DataKind(
            "Percentual",
            "A percentage or rate between 0 and 100.",
            "12,5",
            (
                Probe("over_100", "150", "{campo} acima de 100"),
                Probe("negative", "-5", "{campo} negativo"),
            ),
        ),
        "free_text": DataKind(
            "Texto livre",
            "Free text: notes, description, comments, reason or an address line.",
            "Contratação para a equipe de tecnologia.",
        ),
        "password": DataKind(
            "Senha",
            "A password or secret.",
            "Senha@Forte2026",
            (Probe("short", "123", "{campo} curta", "observe"),),
        ),
        "search": DataKind(
            "Termo de busca",
            "A search or filter term.",
            "Maria",
        ),
        "url": DataKind(
            "Endereço web",
            "A web address (URL).",
            "https://www.exemplo.com.br",
            (Probe("no_scheme", "exemplo com br", "{campo} sem formato de endereço"),),
        ),
        "code": DataKind(
            "Código",
            "An internal code or identifier: registration number, product code, ID.",
            "12345",
        ),
        "other": DataKind("Outro", "None of the above.", "Teste"),
    }


# Tipos que só existem para campos de texto: select, checkbox e radio se resolvem pelo DOM.
TEXT_ROLES = {"textbox", "searchbox", "spinbutton", "combobox_input"}


@dataclass(frozen=True)
class ActionRole:
    label: str
    describe: str
    # Nunca clicado numa exploração sem supervisão; vira teste manual no plano.
    risky: bool = False


ACTION_ROLES: dict[str, ActionRole] = {
    "submit_save": ActionRole(
        "Salvar / enviar formulário",
        "Saves or submits the form data on this screen: Salvar, Gravar, Cadastrar, Confirmar.",
    ),
    "send": ActionRole(
        "Enviar para outros",
        "Sends the record to other people or systems: approval workflow, e-mail, integration "
        "or government submission.",
        risky=True,
    ),
    "delete": ActionRole(
        "Excluir",
        "Deletes, removes, discards or irreversibly cancels a record or draft.",
        risky=True,
    ),
    "clear": ActionRole("Limpar", "Clears or resets the form fields without saving."),
    "cancel_back": ActionRole(
        "Cancelar / voltar",
        "Leaves the current editing without saving and goes back: Cancelar, Voltar.",
    ),
    "navigate": ActionRole(
        "Navegação", "Goes to another screen or menu area of the application."
    ),
    "logout": ActionRole("Sair", "Ends the user's session: Sair, Logout.", risky=True),
    "open_panel": ActionRole(
        "Abrir painel",
        "Opens a dialog, help, tab, menu or expandable section on the same screen.",
    ),
    "search_filter": ActionRole("Buscar / filtrar", "Runs a search or applies list filters."),
    "export": ActionRole(
        "Exportar", "Exports, downloads, prints or generates a file.", risky=True
    ),
    "other": ActionRole("Outra", "None of the above."),
}

SCREEN_KINDS: dict[str, tuple[str, str]] = {
    "form_create": ("Cadastro", "A form to register a new record."),
    "form_edit": ("Edição", "A form to edit an existing record."),
    "search_list": ("Pesquisa / lista", "A search or list screen with filters and results."),
    "detail": ("Detalhe", "A read-only detail view of one record."),
    "dashboard": ("Painel", "A dashboard with indicators or charts."),
    "login": ("Login", "A sign-in or authentication screen."),
    "wizard": ("Assistente", "One step of a multi-step wizard."),
    "settings": ("Configuração", "A settings or preferences screen."),
    "other": ("Outra", "None of the above."),
}

CRITICALITY_LEVELS = [
    "Low impact: informational or cosmetic; mistakes are easy to notice and undo.",
    "Moderate: routine operational data; mistakes cause rework.",
    "High: personal, contractual or financial data; mistakes affect people or money.",
    "Critical: legal or tax obligations, payroll or payments; mistakes cause fines or losses.",
]
CRITICALITY_LABELS = ["Baixa", "Moderada", "Alta", "Crítica"]

OUTCOMES: dict[str, tuple[str, str]] = {
    "accepted": (
        "Aceitou",
        "The system accepted the submission: a success or confirmation message, or it moved "
        "on to a saved or next state.",
    ),
    "rejected": (
        "Recusou",
        "The system refused the submission: a validation or error message says an input is "
        "missing or wrong.",
    ),
    "server_error": (
        "Erro do sistema",
        "An unexpected failure: server error, exception or 'try again later', not tied to a "
        "specific input.",
    ),
    "no_feedback": ("Sem retorno", "Nothing visible indicates success or failure."),
}

# Rede de segurança determinística para o portão de risco: mesmo que o Jev erre,
# nada com estas palavras é clicado sem supervisão.
RISKY_WORDS = (
    "excluir", "exclua", "deletar", "apagar", "remover", "descartar", "desligar", "demitir",
    "enviar", "transmitir", "aprovar", "reprovar", "pagar", "estornar", "sair", "logout",
    "encerrar", "delete", "remove", "send", "submit for", "pay", "sign out", "log out",
)
