import asyncio
import hashlib
import json
import time
from collections import OrderedDict
from dataclasses import dataclass

import httpx

from .config import Settings

# USD por milhão de tokens, conforme https://docs.typesafe.ai/models (set/2026).
# Jev cobra apenas entrada; tokens de saída são gratuitos.
PRICE_INPUT_PER_MTOK = 0.042
CACHE_SIZE = 128
# O Jev aceita até 64k tokens por requisição (estado + todas as perguntas). Medido: ~3
# caracteres de JSON por token. Acima de ~80 mil caracteres (~27k tokens) as perguntas são
# divididas em requisições paralelas com o mesmo estado; a latência quase não muda.
MAX_REQUEST_CHARS = 80_000


class ProviderError(Exception):
    """Erro seguro para exibir; nunca inclui payloads, headers ou corpo remoto."""


def _error_type(response: httpx.Response) -> str | None:
    """Só o código de erro documentado (`detail.error_type`), nunca o corpo inteiro."""
    try:
        detail = response.json().get("detail")
    except (json.JSONDecodeError, ValueError, AttributeError):
        return None
    value = detail.get("error_type") if isinstance(detail, dict) else None
    return value if isinstance(value, str) and value.isidentifier() else None


def estimate_cost(usage: dict) -> float | None:
    if "cost" in usage:
        return float(usage["cost"])
    if "input_tokens" in usage:
        return usage["input_tokens"] * PRICE_INPUT_PER_MTOK / 1_000_000
    return None


@dataclass
class Decision:
    data: dict
    ms: float
    cached: bool
    questions: int
    requests: int = 1


def _size(value) -> int:
    return len(json.dumps(value, ensure_ascii=False))


def split(state, questions: dict, limit: int = MAX_REQUEST_CHARS) -> list[dict]:
    """Divide as perguntas em blocos que cabem, cada um com o mesmo estado."""
    budget = max(limit - _size(state) - 200, 1)
    chunks: list[dict] = [{}]
    used = 0
    for key, question in questions.items():
        size = _size({key: question})
        if chunks[-1] and used + size > budget:
            chunks.append({})
            used = 0
        chunks[-1][key] = question
        used += size
    return chunks


class JevClient:
    """Conexão reaproveitada e cache por conteúdo: a mesma tela não paga duas vezes."""

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self.client = httpx.AsyncClient(
            timeout=settings.timeout,
            transport=transport,
            follow_redirects=False,
            limits=httpx.Limits(max_keepalive_connections=4, keepalive_expiry=120),
        )
        self.cache: OrderedDict[str, dict] = OrderedDict()

    async def aclose(self) -> None:
        await self.client.aclose()

    async def decide(self, state, questions: dict) -> Decision:
        """Uma requisição por bloco de perguntas; os blocos vão em paralelo e voltam juntos."""
        chunks = split(state, questions)
        if len(chunks) == 1:
            return await self._decide(state, questions)
        parts = await asyncio.gather(*(self._decide(state, chunk) for chunk in chunks))
        answers: dict = {}
        tokens = 0
        for part in parts:
            answers.update(part.data.get("answers") or {})
            usage = part.data.get("usage") if isinstance(part.data.get("usage"), dict) else {}
            tokens += usage.get("input_tokens") or 0
        data = {"model": parts[0].data.get("model"), "answers": answers,
                "usage": {"input_tokens": tokens}}
        return Decision(data, max(p.ms for p in parts), all(p.cached for p in parts),
                        len(questions), len(parts))

    async def _decide(self, state, questions: dict) -> Decision:
        if not self.settings.api_key and not self.settings.fake:
            raise ProviderError(f"Preencha {self.settings.provider.upper()}_API_KEY no .env.")
        payload = {"model": self.settings.model, "state": state, "questions": questions}
        key = hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        if key in self.cache:
            self.cache.move_to_end(key)
            return Decision(self.cache[key], 0.0, True, len(questions))
        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
        }
        if self.settings.provider == "openrouter":
            headers["X-Title"] = "Jev Screen Scout Demo"
        try:
            for attempt in range(3):
                started = time.perf_counter()
                response = await self.client.post(
                    self.settings.endpoint, headers=headers, json=payload
                )
                elapsed = (time.perf_counter() - started) * 1000
                if response.status_code not in {429, 503, 529} or attempt == 2:
                    break
                try:
                    delay = min(2.0, max(0.1, float(response.headers.get("Retry-After", "0.5"))))
                except ValueError:
                    delay = 0.5 * (2**attempt)
                await asyncio.sleep(delay)
        except httpx.TimeoutException:
            raise ProviderError("Timeout na API do Jev.") from None
        except (httpx.HTTPError, TypeError, ValueError):
            raise ProviderError("Falha de conexão ou serialização com a API do Jev.") from None
        if response.status_code >= 300:
            if _error_type(response) == "max_tokens_exceeded":
                raise ProviderError(
                    "A requisição passou do limite de tokens do Jev (64k por requisição)."
                )
            hints = {
                400: "O provedor recusou a requisição.",
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
        self.cache[key] = data
        if len(self.cache) > CACHE_SIZE:
            self.cache.popitem(last=False)
        return Decision(data, elapsed, False, len(questions))
