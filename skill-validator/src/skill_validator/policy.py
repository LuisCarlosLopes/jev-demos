import math
from pathlib import Path, PurePosixPath
from typing import Any

from .yaml_utils import load_yaml


def number(value: Any, low: float, high: float) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and low <= value <= high
    )


def load_policy(path: Path) -> dict[str, Any]:
    policy = load_yaml(path.read_text(encoding="utf-8"))
    expected = {
        "version",
        "min_quality",
        "min_confidence",
        "risk_review",
        "risk_block",
        "required_paths",
        "max_files",
        "max_file_bytes",
        "max_total_bytes",
        "max_state_chars",
        "dimensions",
        "risks",
    }
    optional = {"allowed_binary_extensions"}
    if not isinstance(policy, dict) or not expected <= set(policy) <= expected | optional:
        raise ValueError("A policy deve conter os campos definidos em policy.yaml.")
    # Binários com estas extensões são escaneados e inventariados, sem gerar aviso.
    extensions = policy.setdefault("allowed_binary_extensions", [])
    if not isinstance(extensions, list) or any(
        not isinstance(x, str) or not x.startswith(".") or len(x) < 2 for x in extensions
    ):
        raise ValueError("allowed_binary_extensions deve listar extensões como '.png'.")
    policy["allowed_binary_extensions"] = [x.lower() for x in extensions]
    if not isinstance(policy["version"], str) or not policy["version"].strip():
        raise ValueError("policy.version deve ser uma string não vazia.")
    for key, high in (
        ("min_quality", 100),
        ("min_confidence", 1),
        ("risk_review", 1),
        ("risk_block", 1),
    ):
        if not number(policy[key], 0, high):
            raise ValueError(f"policy.{key} deve estar entre 0 e {high}.")
    if policy["risk_review"] >= policy["risk_block"]:
        raise ValueError("risk_review deve ser menor que risk_block.")
    for key in ("max_files", "max_file_bytes", "max_total_bytes", "max_state_chars"):
        if type(policy[key]) is not int or policy[key] <= 0:
            raise ValueError(f"policy.{key} deve ser inteiro positivo.")
    if not isinstance(policy["required_paths"], list):
        raise ValueError("required_paths deve ser uma lista de paths relativos.")
    for item in policy["required_paths"]:
        if (
            not isinstance(item, str)
            or not item
            or "\\" in item
            or PurePosixPath(item).is_absolute()
            or ".." in PurePosixPath(item).parts
        ):
            raise ValueError("required_paths aceita somente paths relativos dentro da skill.")
    dimensions = policy["dimensions"]
    risks = policy["risks"]
    if not isinstance(dimensions, dict) or not dimensions or not isinstance(risks, dict):
        raise ValueError("dimensions deve ser um mapa não vazio; risks deve ser um mapa.")
    if set(dimensions) & set(risks):
        raise ValueError("IDs de dimensions e risks não podem colidir.")
    for key, dimension in dimensions.items():
        if not isinstance(dimension, dict) or set(dimension) != {
            "label",
            "weight",
            "instructions",
            "criteria",
        }:
            raise ValueError(f"Dimensão inválida: {key}.")
        if not number(dimension["weight"], 0.000001, 1):
            raise ValueError(f"Peso inválido: {key}.")
        levels = dimension["criteria"]
        if (
            not isinstance(levels, list)
            or not 2 <= len(levels) <= 10
            or any(not isinstance(x, str) or not x.strip() for x in levels)
        ):
            raise ValueError(f"A dimensão {key} precisa de 2 a 10 níveis descritivos.")
    if not math.isclose(sum(x["weight"] for x in dimensions.values()), 1, abs_tol=1e-6):
        raise ValueError("A soma dos pesos das dimensões deve ser 1.")
    for key, risk in risks.items():
        if (
            not isinstance(risk, dict)
            or set(risk) != {"label", "instructions", "criteria"}
            or not isinstance(risk["criteria"], dict)
            or set(risk["criteria"]) != {"true", "false"}
            or any(not isinstance(x, str) or not x.strip() for x in risk["criteria"].values())
        ):
            raise ValueError(f"Risco inválido: {key}.")
    for item in [*dimensions.values(), *risks.values()]:
        if any(
            not isinstance(item[k], str) or not item[k].strip() for k in ("label", "instructions")
        ):
            raise ValueError("label e instructions devem ser strings não vazias.")
    return policy
