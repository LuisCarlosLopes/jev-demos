import asyncio
import json
import time

import httpx

from .config import Settings

# USD por milhão de tokens, conforme https://docs.typesafe.ai/models (set/2026).
# Jev cobra apenas entrada; tokens de saída são gratuitos.
PRICE_INPUT_PER_MTOK = 0.042


class ProviderError(Exception):
    """Erro seguro para exibir; nunca inclui payloads, headers ou corpo remoto."""


def estimate_cost(usage: dict) -> float | None:
    if "cost" in usage:
        return float(usage["cost"])
    if "input_tokens" in usage:
        return usage["input_tokens"] * PRICE_INPUT_PER_MTOK / 1_000_000
    return None


class JevClient:
    """Cliente com uma conexão reaproveitada: sem novo handshake TLS a cada frase."""

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self.client = httpx.AsyncClient(
            timeout=settings.timeout,
            transport=transport,
            follow_redirects=False,
            limits=httpx.Limits(max_keepalive_connections=10, keepalive_expiry=120),
        )

    async def aclose(self) -> None:
        await self.client.aclose()

    async def decide(self, state: dict, questions: dict) -> tuple[dict, float]:
        """Devolve (resposta, latência em ms da ida e volta ao provedor)."""
        if not self.settings.api_key and not self.settings.fake:
            raise ProviderError(f"Preencha {self.settings.provider.upper()}_API_KEY no .env.")
        payload = {"model": self.settings.model, "state": state, "questions": questions}
        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
        }
        if self.settings.provider == "openrouter":
            headers["X-Title"] = "Jev Brand Live Demo"
        try:
            # Interativo: no máximo uma nova tentativa; a próxima frase já pede outra decisão.
            for attempt in range(2):
                started = time.perf_counter()
                response = await self.client.post(
                    self.settings.endpoint, headers=headers, json=payload
                )
                elapsed = (time.perf_counter() - started) * 1000
                if response.status_code not in {429, 503, 529} or attempt == 1:
                    break
                await asyncio.sleep(0.3)
        except httpx.TimeoutException:
            raise ProviderError("Timeout na API do Jev.") from None
        except (httpx.HTTPError, TypeError, ValueError):
            raise ProviderError("Falha de conexão ou serialização com a API do Jev.") from None
        if response.status_code >= 300:
            hints = {
                401: "Confira a API key do provedor selecionado.",
                403: "Confira as permissões da API key.",
                404: "Confira o modelo e a disponibilidade da API de decisões.",
                422: "O provedor rejeitou o contrato da requisição.",
                429: "Limite de requisições; tente novamente em instantes.",
            }
            hint = hints.get(response.status_code, "O provedor não concluiu a avaliação.")
            raise ProviderError(f"API HTTP {response.status_code}. {hint}")
        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError):
            raise ProviderError("A API retornou uma resposta que não é JSON válido.") from None
        if not isinstance(data, dict):
            raise ProviderError("Envelope inesperado na resposta da API.")
        return data, elapsed
