import math
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values


@dataclass(frozen=True)
class Settings:
    provider: str
    api_key: str = field(repr=False)
    model: str
    timeout: float
    known_secrets: tuple[str, ...] = field(default=(), repr=False)

    @property
    def endpoint(self) -> str:
        if self.provider == "typesafe":
            return "https://api.typesafe.ai/v1/systemone"
        return "https://openrouter.ai/api/alpha/decisions"

    @classmethod
    def load(cls, env_file: Path, provider: str | None = None) -> "Settings":
        if not env_file.is_file():
            raise ValueError(f"Arquivo .env não encontrado: {env_file}")
        # Ambiente do processo prevalece; não alteramos os.environ.
        env = {**dotenv_values(env_file), **os.environ}
        provider = provider or env.get("JEV_PROVIDER", "typesafe")
        if provider not in {"typesafe", "openrouter"}:
            raise ValueError("JEV_PROVIDER deve ser typesafe ou openrouter.")
        prefix = provider.upper()
        key = (env.get(f"{prefix}_API_KEY") or "").strip()
        defaults = {"typesafe": "jev-latest", "openrouter": "typesafe/jev-1.13"}
        model = (env.get(f"{prefix}_MODEL") or defaults[provider]).strip()
        try:
            timeout = float(env.get("JEV_TIMEOUT_SECONDS") or "30")
        except ValueError:
            raise ValueError("JEV_TIMEOUT_SECONDS deve ser um número positivo.") from None
        if not math.isfinite(timeout) or not 0 < timeout <= 120:
            raise ValueError("JEV_TIMEOUT_SECONDS deve estar entre 0 e 120 segundos.")
        known = tuple(
            value.strip()
            for name in ("TYPESAFE_API_KEY", "OPENROUTER_API_KEY")
            if (value := env.get(name)) and len(value.strip()) >= 8
        )
        return cls(provider, key, model, timeout, known)
