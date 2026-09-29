import asyncio
import json
import re
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
    """Cliente com uma conexão reaproveitada: sem novo handshake TLS a cada tecla."""

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        if transport is None and settings.fake:
            transport = httpx.MockTransport(fake_handler)
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
            headers["X-Title"] = "Jev Catalog AI Demo"
        try:
            # Interativo: no máximo uma nova tentativa; a próxima tecla já pede outra busca.
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


# --- Modo simulado (JEV_FAKE=1) -------------------------------------------------------
# Heurística lexical só para desenvolver a interface sem chave. Não representa a
# qualidade nem a latência do Jev; a tela exibe um aviso enquanto estiver ativo.

_WORDS = re.compile(r"[a-z0-9#+.]{3,}")


def _words(value) -> set[str]:
    return set(_WORDS.findall(json.dumps(value, ensure_ascii=False).lower()))


def fake_handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    query = _words(body["state"]["request"])
    answers = {}
    for key, question in body["questions"].items():
        if question["type"] == "noul" and key == "incomplete":
            answers[key] = {"type": "noul", "noul": 0.9 if len(query) < 1 else 0.1}
        elif question["type"] == "noul":
            overlap = len(query & _words(question["instructions"]["artifact"]))
            answers[key] = {"type": "noul", "noul": round(min(0.95, 0.04 + 0.3 * overlap), 3)}
        else:
            options = list(question["criteria"])
            scores = [len(query & _words([o, question["criteria"][o]])) for o in options[:-1]]
            best = max(scores, default=0)
            choice = options[scores.index(best)] if best else options[-1]
            probabilities = {o: (0.8 if o == choice else 0.2 / (len(options) - 1)) for o in options}
            answers[key] = {
                "type": "choice",
                "choice": choice,
                "confidence": 0.8,
                "probabilities": probabilities,
            }
    tokens = len(request.content) // 4
    return httpx.Response(
        200, json={"model": "fake-jev", "answers": answers, "usage": {"input_tokens": tokens}}
    )
