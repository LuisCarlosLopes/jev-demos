import json
import time

import httpx

from .config import Settings


class ProviderError(Exception):
    """Erro seguro para exibir; nunca inclui payloads, headers ou corpo remoto."""


class JevProvider:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self.transport = transport

    def evaluate(self, state: dict, questions: dict) -> dict:
        if not self.settings.api_key:
            raise ProviderError(f"Preencha {self.settings.provider.upper()}_API_KEY no .env.")
        payload = {"model": self.settings.model, "state": state, "questions": questions}
        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
        }
        if self.settings.provider == "openrouter":
            headers["X-Title"] = "Jev Skill Validator Demo"
        try:
            with httpx.Client(
                timeout=self.settings.timeout, transport=self.transport, follow_redirects=False
            ) as client:
                for attempt in range(3):
                    response = client.post(self.settings.endpoint, headers=headers, json=payload)
                    if response.status_code not in {429, 503, 529} or attempt == 2:
                        break
                    try:
                        delay = min(2.0, max(0.1, float(response.headers.get("Retry-After", "1"))))
                    except ValueError:
                        delay = 0.5 * (2**attempt)
                    time.sleep(delay)
        except httpx.TimeoutException:
            raise ProviderError("Timeout na API; avaliação semântica não concluída.") from None
        except (httpx.HTTPError, TypeError, ValueError):
            raise ProviderError(
                "Falha de conexão ou serialização; avaliação não concluída."
            ) from None
        if response.status_code >= 300:
            hints = {
                401: "Confira a API key do provedor selecionado.",
                403: "Confira as permissões da API key.",
                404: "Confira o modelo e a disponibilidade da API de decisões.",
                422: "O provedor rejeitou o contrato da requisição.",
                429: "Limite de requisições; tente novamente depois.",
            }
            hint = hints.get(response.status_code, "O provedor não concluiu a avaliação.")
            raise ProviderError(f"API HTTP {response.status_code}. {hint}")
        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError):
            raise ProviderError("A API retornou uma resposta que não é JSON válido.") from None
        if not isinstance(data, dict):
            raise ProviderError("Envelope inesperado na resposta da API.")
        return data
