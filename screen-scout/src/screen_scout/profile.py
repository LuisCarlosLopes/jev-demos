"""Perfil da tela: fatos do DOM + decisões do Jev + limiares, num formato só.

Os limiares ficam aqui, em código: o Jev devolve probabilidades e quem decide o que fazer com
elas é o demo. Abaixo da confiança mínima a decisão continua valendo, mas o elemento aparece
no plano como "revisar", em vez de virar certeza.
"""

from dataclasses import dataclass, field
from datetime import date

from .capture import Element, Screen, strip_label
from .catalog import ACTION_ROLES, CRITICALITY_LABELS, RISKY_WORDS, SCREEN_KINDS, data_kinds
from .decisions import DOM_KINDS

# Nome de um campo sem rótulo nenhum, para o plano e os achados.
ROLE_NAMES = {
    "slider": "controle deslizante", "checkbox": "caixa de seleção", "radio": "opção",
    "combobox": "lista", "listbox": "lista", "searchbox": "campo de busca",
    "spinbutton": "campo numérico", "textbox": "campo de texto", "switch": "chave",
}


@dataclass(frozen=True)
class Thresholds:
    confidence: float = 0.60  # abaixo disso a decisão vai para "revisar"
    required: float = 0.50  # Noul de obrigatoriedade
    risk: float = 0.35  # conservador: na dúvida, não clica


@dataclass
class FieldProfile:
    element: Element
    control: str  # fill | select | check | radio
    kind: str | None = None
    kind_confidence: float | None = None
    kind_top: list[dict] = field(default_factory=list)
    kind_source: str = "jev"  # jev | dom
    required: bool = False
    required_source: str = "none"  # dom | jev | none
    required_p: float | None = None
    valid: str | bool | None = None
    initial: str | bool | None = None
    uncertain: bool = False

    @property
    def label(self) -> str:
        element = self.element
        text = strip_label(element.label or element.name)
        if text:
            return text
        kind = ROLE_NAMES.get(element.role, "campo")
        return f"{kind} #{element.html_id}" if element.html_id else f"{kind} {element.id}"

    def to_dict(self) -> dict:
        return {
            "id": self.element.id,
            "label": self.label,
            "control": self.control,
            "kind": self.kind,
            "kind_label": data_kinds()[self.kind].label if self.kind else None,
            "kind_confidence": self.kind_confidence,
            "kind_top": self.kind_top,
            "kind_source": self.kind_source,
            "required": self.required,
            "required_source": self.required_source,
            "required_p": self.required_p,
            "valid": self.valid,
            "uncertain": self.uncertain,
            "locator": self.element.locator,
        }


@dataclass
class ActionProfile:
    element: Element
    role: str
    role_confidence: float
    role_top: list[dict]
    risk_p: float
    risky: bool
    risky_reason: str
    uncertain: bool

    @property
    def label(self) -> str:
        return self.element.name or self.element.id

    def to_dict(self) -> dict:
        return {
            "id": self.element.id,
            "label": self.label,
            "role": self.role,
            "role_label": ACTION_ROLES[self.role].label,
            "role_confidence": self.role_confidence,
            "role_top": self.role_top,
            "risk_p": self.risk_p,
            "risky": self.risky,
            "risky_reason": self.risky_reason,
            "uncertain": self.uncertain,
            "href": self.element.href,
            "same_origin": self.element.same_origin,
            "locator": self.element.locator,
        }


@dataclass
class Profile:
    screen: Screen
    kind: str
    kind_confidence: float
    criticality: float
    personal_data: float
    fields: list[FieldProfile]
    actions: list[ActionProfile]
    submit: ActionProfile | None
    thresholds: Thresholds
    skipped: list[dict]
    # Por que não há ação de salvar para as sondagens (vazio quando há).
    submit_note: str = ""

    @property
    def criticality_label(self) -> str:
        return CRITICALITY_LABELS[min(3, max(0, round(self.criticality)))]

    def field(self, element_id: str) -> FieldProfile | None:
        return next((f for f in self.fields if f.element.id == element_id), None)

    def fields_in_scope(self, action: "ActionProfile") -> list[FieldProfile]:
        """Campos do mesmo grupo (formulário, seção, barra lateral) que a ação.

        Um "Limpar" numa barra de filtros limpa os filtros, não a busca do topo da tela.
        """
        scopes = action.element.scopes
        if not scopes:
            return self.fields
        return [f for f in self.fields if scopes[0] in f.element.scopes]

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "kind_label": SCREEN_KINDS[self.kind][0],
            "kind_confidence": self.kind_confidence,
            "criticality": self.criticality,
            "criticality_label": self.criticality_label,
            "personal_data": self.personal_data,
            "fields": [f.to_dict() for f in self.fields],
            "actions": [a.to_dict() for a in self.actions],
            "submit": self.submit.element.id if self.submit else None,
            "submit_note": self.submit_note,
            "thresholds": self.thresholds.__dict__,
            "skipped": self.skipped,
        }


def _control(element: Element) -> str:
    if element.tag == "select":
        return "select"
    if element.type == "checkbox" or element.role in {"checkbox", "switch"}:
        return "check"
    if element.type == "radio":
        return "radio"
    if element.type == "file":
        return "file"  # upload fica fora das sondagens e do código gerado
    return "fill"


def _valid_value(element: Element, kind: str | None, today: date) -> str | None:
    kinds = data_kinds(today)
    if element.type == "date":
        return "1990-03-15" if kind == "birth_date" else today.isoformat()
    if element.type == "number":
        numeric = {"money": "4500", "percentage": "12.5", "quantity": "10"}
        return numeric.get(kind or "", "10")
    if kind is None:
        return None
    value = kinds[kind].valid
    if element.maxlength and len(value) > element.maxlength:
        value = value[: element.maxlength]
    return value


def _risky_word(text: str) -> str | None:
    lowered = text.lower()
    return next((w for w in RISKY_WORDS if w in lowered), None)


def build_profile(
    screen: Screen,
    classification: dict,
    thresholds: Thresholds | None = None,
    today: date | None = None,
) -> Profile:
    thresholds = thresholds or Thresholds()
    today = today or date.today()
    decided = classification["elements"]
    fields: list[FieldProfile] = []
    actions: list[ActionProfile] = []
    skipped: list[dict] = []
    seen_groups: set[str] = set()
    for element in screen.elements:
        if element.disabled or element.readonly:
            skipped.append({"id": element.id, "label": element.name, "reason": "desabilitado"})
            continue
        if element.locator is None or not element.locator.get("unique"):
            skipped.append(
                {"id": element.id, "label": element.name, "reason": "sem localizador estável"}
            )
            continue
        info = decided.get(element.id, {})
        if element.kind == "field":
            if element.type == "radio":
                if element.group in seen_groups:
                    continue
                seen_groups.add(element.group)
            profile = FieldProfile(element, _control(element))
            if element.text_input:
                if element.type in DOM_KINDS:
                    profile.kind, profile.kind_source = DOM_KINDS[element.type], "dom"
                    profile.kind_confidence = 1.0
                elif element.type == "date":
                    profile.kind, profile.kind_source, profile.kind_confidence = "date", "dom", 1.0
                elif "kind" in info:
                    profile.kind = info["kind"]["value"]
                    profile.kind_confidence = info["kind"]["confidence"]
                    profile.kind_top = info["kind"]["top"]
            if element.required:
                profile.required, profile.required_source = True, "dom"
            elif "required" in info:
                profile.required_p = info["required"]
                if profile.required_p >= thresholds.required:
                    profile.required, profile.required_source = True, "jev"
            if profile.control == "select":
                options = [o for o in element.options if o["value"]] or element.options
                profile.valid = options[0]["value"] if options else None
                profile.initial = element.value if element.value is not None else (
                    element.options[0]["value"] if element.options else None)
            elif profile.control in {"check", "radio"}:
                profile.initial = bool(element.checked)
                profile.valid = True if profile.required or profile.control == "radio" else None
            elif profile.control == "fill":
                profile.valid = _valid_value(element, profile.kind, today)
                profile.initial = element.value or ""
            profile.uncertain = (
                profile.kind_confidence is not None
                and profile.kind_confidence < thresholds.confidence
            ) or (
                profile.required_p is not None
                and abs(profile.required_p - thresholds.required) < 0.15
            )
            fields.append(profile)
        else:
            if "role" not in info:
                continue
            role = info["role"]["value"]
            risk_p = info.get("risk", 1.0)
            reasons = []
            # Um reset nativo do formulário não sai da tela, diga o rótulo o que disser.
            native_reset = element.tag in {"button", "input"} and element.type == "reset"
            word = None if native_reset else _risky_word(element.name)
            if role == "submit_save":
                # Salvar o formulário em teste é o objetivo das sondagens, e o Noul dá 45–60%
                # para qualquer "Gravar": só um risco muito alto ou uma palavra de risco barram.
                # Sem isso, "Pagar selecionados" (classificado como salvar) viraria o botão
                # usado em todas as sondagens.
                if risk_p >= 0.8:
                    reasons.append(f"Jev: risco {round(risk_p * 100)}%")
            else:
                if ACTION_ROLES[role].risky:
                    reasons.append(f"papel: {ACTION_ROLES[role].label.lower()}")
                if risk_p >= thresholds.risk:
                    reasons.append(f"Jev: risco {round(risk_p * 100)}%")
            if word:
                reasons.append(f"palavra de risco: “{word}”")
            if element.href and element.same_origin is False:
                reasons.append("sai do sistema")
            if element.target == "_blank":
                reasons.append("abre outra aba")
            actions.append(
                ActionProfile(
                    element,
                    role,
                    info["role"]["confidence"],
                    info["role"]["top"],
                    risk_p,
                    bool(reasons),
                    "; ".join(reasons),
                    info["role"]["confidence"] < thresholds.confidence,
                )
            )
    submit, submit_note = _pick_submit(actions)
    screen_info = classification["screen"]
    return Profile(
        screen=screen,
        kind=screen_info["kind"]["value"],
        kind_confidence=screen_info["kind"]["confidence"],
        criticality=screen_info["criticality"]["value"],
        personal_data=screen_info["personal_data"],
        fields=fields,
        actions=actions,
        submit=submit,
        thresholds=thresholds,
        skipped=skipped,
        submit_note=submit_note,
    )


def _pick_submit(actions: list[ActionProfile]) -> tuple[ActionProfile | None, str]:
    """A ação que salva o formulário: papel decidido pelo Jev, desempate pelo DOM."""
    native = [a for a in actions if a.element.submit]
    if native and all(a.risky for a in native):
        # Se o envio nativo do formulário é de risco, outro botão ("Salvar rascunho") não o
        # substitui: rascunhos costumam pular a validação e as sondagens mentiriam.
        names = ", ".join(f"“{a.label}”" for a in native)
        return None, (f"O envio do formulário ({names}) foi barrado como ação de risco; as "
                      "sondagens que salvam não rodaram.")
    candidates = [a for a in actions if a.role == "submit_save" and not a.risky]
    # Dentro de um <form> primeiro; fora dele só quando não há outro (SPAs sem <form>).
    candidates = [a for a in candidates if a.element.in_form] or candidates
    if not candidates:
        return None, "Nenhuma ação de salvar identificada."

    def weight(action: ActionProfile) -> tuple:
        p = next((t["p"] for t in action.role_top if t["key"] == "submit_save"), 0)
        return (action.element.submit, action.element.in_form, p)

    return max(candidates, key=weight), ""
