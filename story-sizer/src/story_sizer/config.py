import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    ado_org: str
    ado_project: str
    ado_team: str
    ado_pat: str = field(repr=False)
    jev_api_key: str = field(repr=False)
    jev_model: str
    jev_timeout: float
    jev_concurrency: int
    allow_write: bool
    provider: str = "typesafe"

    @property
    def jev_endpoint(self) -> str:
        if self.provider == "typesafe":
            return "https://api.typesafe.ai/v1/systemone"
        return "https://openrouter.ai/api/alpha/decisions"

    @classmethod
    def load(cls, env_file: Path | None = None, provider: str | None = None) -> "Settings":
        env_file = env_file or ROOT / ".env"
        # Ambiente do processo prevalece; não alteramos os.environ.
        env = {**(dotenv_values(env_file) if env_file.is_file() else {}), **os.environ}
        provider = (provider or env.get("JEV_PROVIDER") or "typesafe").strip()
        if provider not in {"typesafe", "openrouter"}:
            raise ValueError("JEV_PROVIDER deve ser typesafe ou openrouter.")
        prefix = provider.upper()
        defaults = {"typesafe": "jev-1.13.0", "openrouter": "typesafe/jev-1.13"}
        pat = (env.get("AZURE_DEVOPS_PAT") or env.get("ADO_PAT") or "").strip()
        timeout = float(env.get("JEV_TIMEOUT_SECONDS") or "30")
        if not 0 < timeout <= 120:
            raise ValueError("JEV_TIMEOUT_SECONDS deve estar entre 0 e 120 segundos.")
        return cls(
            ado_org=(env.get("ADO_ORG") or "exemplo-org").strip(),
            ado_project=(env.get("ADO_PROJECT") or "Projeto Demo").strip(),
            ado_team=(env.get("ADO_TEAM") or "Team-demo").strip(),
            ado_pat=pat,
            jev_api_key=(env.get(f"{prefix}_API_KEY") or "").strip(),
            jev_model=(env.get(f"{prefix}_MODEL") or defaults[provider]).strip(),
            jev_timeout=timeout,
            jev_concurrency=max(1, int(env.get("JEV_MAX_CONCURRENCY") or "8")),
            allow_write=(env.get("ALLOW_WRITE") or "false").strip().lower() == "true",
            provider=provider,
        )


def load_policy(path: Path | None = None) -> dict:
    path = path or ROOT / "policy.yaml"
    policy = yaml.safe_load(path.read_text(encoding="utf-8"))
    sizes = policy["sizes"]
    missing = [s for s in policy["order"] if s not in sizes]
    if missing:
        raise ValueError(f"policy.yaml: tamanhos em `order` sem definição: {missing}")
    for name, spec in policy["factors"].items():
        if not 2 <= len(spec["criteria"]) <= 10:
            raise ValueError(f"policy.yaml: fator {name} precisa de 2 a 10 níveis.")
    return policy
