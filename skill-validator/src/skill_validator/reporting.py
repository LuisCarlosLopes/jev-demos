import json
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .models import Report

STATUS = {
    "passed": "APROVADA",
    "failed": "REPROVADA",
    "review": "REVISÃO",
    "error": "ERRO",
    "local_only": "SOMENTE LOCAL",
}


def cost_text(usage: dict) -> str:
    suffix = " (estimado)" if usage.get("cost_source") == "estimated" else ""
    return f"US$ {usage['cost']:.8f}{suffix}"


def render_console(report: Report) -> None:
    console = Console(markup=False)
    console.print(f"Skill Validator · {STATUS[report.status]}")
    console.print(report.skill)
    for reason in report.reasons:
        console.print(f"• {reason}")
    if report.quality_score is not None:
        console.print(
            f"Qualidade: {report.quality_score:.1f}/100 · {report.provider} · {report.model}"
        )
        table = Table("Dimensão", "Nota / 100", "Confiança", "Peso")
        for d in report.dimensions.values():
            table.add_row(
                d["label"],
                f"{100 * d['normalized']:.1f}",
                f"{d['confidence']:.2f}",
                f"{d['weight']:.0%}",
            )
        console.print(table)
        if "cost" in report.usage:
            console.print(f"Custo: {cost_text(report.usage)}")
        for risk in report.risks.values():
            console.print(f"Risco · {risk['label']}: p={risk['probability']:.2f}")
    if report.findings:
        table = Table("Severidade", "Regra", "Local", "Mensagem")
        for f in report.findings:
            location = (f.path or "—") + (f":{f.line}" if f.line else "")
            table.add_row(f.severity, f.rule, location, f.message)
        console.print(table)
    console.print(f"Local: {report.local_status} · Jev: {report.semantic_status}")


def markdown(report: Report) -> str:
    def cell(value) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ").replace("`", "'")

    lines = [
        "# Skill Validator",
        "",
        f"**Status:** {STATUS[report.status]}",
        "",
        f"**Skill:** `{cell(report.skill)}`",
        "",
    ]
    lines.extend(f"- {cell(reason)}" for reason in report.reasons)
    lines.extend(["", f"Local: **{report.local_status}** · Jev: **{report.semantic_status}**", ""])
    if report.quality_score is not None:
        lines.extend(
            [
                f"Qualidade: **{report.quality_score:.1f}/100**",
                "",
                f"Provedor: {cell(report.provider)} · Modelo: {cell(report.model)}",
                "",
                *([f"Custo: {cost_text(report.usage)}", ""] if "cost" in report.usage else []),
                "| Dimensão | Nota / 100 | Confiança | Peso |",
                "|---|---:|---:|---:|",
            ]
        )
        for d in report.dimensions.values():
            lines.append(
                f"| {cell(d['label'])} | {100 * d['normalized']:.1f} | "
                f"{d['confidence']:.2f} | {d['weight']:.0%} |"
            )
        lines.extend(["", "| Risco | Probabilidade |", "|---|---:|"])
        lines.extend(
            f"| {cell(r['label'])} | {r['probability']:.2f} |" for r in report.risks.values()
        )
    lines.extend(["", "| Severidade | Regra | Local | Mensagem |", "|---|---|---|---|"])
    for f in report.findings:
        location = (f.path or "—") + (f":{f.line}" if f.line else "")
        lines.append(f"| {f.severity} | {cell(f.rule)} | {cell(location)} | {cell(f.message)} |")
    lines.extend(
        [
            "",
            "Nota e confiança são sinais do modelo, não garantias de correção.",
            "O scanner usa heurísticas e não prova ausência de segredos.",
            "",
        ]
    )
    return "\n".join(lines)


def write_reports(report: Report, json_path: Path | None, markdown_path: Path | None) -> None:
    for path, content in (
        (json_path, json.dumps(report.to_dict(), indent=2, ensure_ascii=False)),
        (markdown_path, markdown(report)),
    ):
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content + "\n", encoding="utf-8")
