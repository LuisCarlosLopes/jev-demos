import math
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values


@dataclass(frozen=True)
class Settings:
    ado_org: str
    ado_project: str
    ado_team: str
    ado_pat: str = field(repr=False)
    provider: str = "typesafe"
    api_key: str = field(default="", repr=False)
    model: str = "jev-latest"
    timeout: float = 30.0
    concurrency: int = 16

    @property
    def endpoint(self) -> str:
        if self.provider == "typesafe":
            return "https://api.typesafe.ai/v1/systemone"
        return "https://openrouter.ai/api/alpha/decisions"

    @classmethod
    def load(cls, env_file: Path | None = None) -> "Settings":
        # Ambiente do processo prevalece sobre o .env; não alteramos os.environ.
        file_values = dotenv_values(env_file) if env_file and env_file.is_file() else {}
        env = {**file_values, **os.environ}
        provider = (env.get("JEV_PROVIDER") or "typesafe").strip()
        if provider not in {"typesafe", "openrouter"}:
            raise ValueError("JEV_PROVIDER deve ser typesafe ou openrouter.")
        prefix = provider.upper()
        defaults = {"typesafe": "jev-latest", "openrouter": "typesafe/jev-1.13"}
        try:
            timeout = float(env.get("JEV_TIMEOUT_SECONDS") or "30")
            concurrency = int(env.get("JEV_CONCURRENCY") or "16")
        except ValueError:
            raise ValueError("JEV_TIMEOUT_SECONDS e JEV_CONCURRENCY devem ser números.") from None
        if not math.isfinite(timeout) or not 0 < timeout <= 120:
            raise ValueError("JEV_TIMEOUT_SECONDS deve estar entre 0 e 120 segundos.")
        if not 1 <= concurrency <= 64:
            raise ValueError("JEV_CONCURRENCY deve estar entre 1 e 64.")
        return cls(
            ado_org=(env.get("ADO_ORG") or "senior-sistemas").strip(),
            ado_project=(env.get("ADO_PROJECT") or "IA - Senior").strip(),
            ado_team=(env.get("ADO_TEAM") or "Speed").strip(),
            ado_pat=(env.get("AZURE_DEVOPS_PAT") or "").strip(),
            provider=provider,
            api_key=(env.get(f"{prefix}_API_KEY") or "").strip(),
            model=(env.get(f"{prefix}_MODEL") or defaults[provider]).strip(),
            timeout=timeout,
            concurrency=concurrency,
        )
