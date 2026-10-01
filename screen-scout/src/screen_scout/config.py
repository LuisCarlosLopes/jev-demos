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
    # Transporte simulado para desenvolver sem chave; a tela avisa quando ativo.
    fake: bool = False
    # Canal do navegador: vazio usa o Chromium do Playwright; "msedge" ou "chrome" usam o
    # navegador instalado, sem download.
    browser_channel: str = ""
    headless: bool = True
    # Sondagens em paralelo: cada uma abre um contexto isolado do mesmo navegador.
    concurrency: int = 6

    @property
    def endpoint(self) -> str:
        if self.provider == "typesafe":
            return "https://api.typesafe.ai/v1/systemone"
        return "https://openrouter.ai/api/alpha/decisions"

    @classmethod
    def load(cls, env_file: Path, provider: str | None = None) -> "Settings":
        # Ambiente do processo prevalece; não alteramos os.environ.
        env = {**(dotenv_values(env_file) if env_file.is_file() else {}), **os.environ}
        provider = provider or env.get("JEV_PROVIDER", "typesafe")
        if provider not in {"typesafe", "openrouter"}:
            raise ValueError("JEV_PROVIDER deve ser typesafe ou openrouter.")
        prefix = provider.upper()
        key = (env.get(f"{prefix}_API_KEY") or "").strip()
        defaults = {"typesafe": "jev-latest", "openrouter": "typesafe/jev-1.13"}
        model = (env.get(f"{prefix}_MODEL") or defaults[provider]).strip()
        try:
            timeout = float(env.get("JEV_TIMEOUT_SECONDS") or "30")
            concurrency = int(env.get("SCOUT_CONCURRENCY") or "6")
        except ValueError:
            raise ValueError("JEV_TIMEOUT_SECONDS e SCOUT_CONCURRENCY devem ser números.") from None
        if not math.isfinite(timeout) or not 0 < timeout <= 120:
            raise ValueError("JEV_TIMEOUT_SECONDS deve estar entre 0 e 120 segundos.")
        if not 1 <= concurrency <= 16:
            raise ValueError("SCOUT_CONCURRENCY deve estar entre 1 e 16.")
        truthy = {"1", "true", "yes"}
        fake = (env.get("JEV_FAKE") or "").strip().lower() in truthy
        channel = (env.get("SCOUT_BROWSER_CHANNEL") or "").strip()
        if channel not in {"", "chromium", "msedge", "chrome"}:
            raise ValueError("SCOUT_BROWSER_CHANNEL deve ser vazio, chromium, msedge ou chrome.")
        headless = (env.get("SCOUT_HEADED") or "").strip().lower() not in truthy
        return cls(provider, key, model, timeout, fake, channel, headless, concurrency)
