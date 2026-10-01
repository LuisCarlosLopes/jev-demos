import asyncio
import json

import httpx
import pytest

from screen_scout.config import Settings
from screen_scout.jev import JevClient, ProviderError, split

SETTINGS = Settings("typesafe", "test-key", "jev-latest", 10)


def _questions(n: int, size: int = 900) -> dict:
    return {f"q{i}": {"type": "noul", "instructions": "x" * size} for i in range(n)}


def test_split_respects_the_budget_and_keeps_every_question():
    questions = _questions(250)
    chunks = split({"screen": "s"}, questions, limit=20_000)
    assert len(chunks) > 1
    assert sum(len(c) for c in chunks) == 250
    assert [k for c in chunks for k in c] == list(questions)
    for chunk in chunks:
        assert len(json.dumps({"state": {"screen": "s"}, "questions": chunk})) <= 20_000
    assert split("s", _questions(3)) == [_questions(3)]


def test_big_request_is_split_and_merged():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(len(body["questions"]))
        answers = {key: {"type": "noul", "noul": 0.1} for key in body["questions"]}
        return httpx.Response(200, json={"model": "jev-1.13.0", "answers": answers,
                                         "usage": {"input_tokens": 100}})

    async def run():
        client = JevClient(SETTINGS, httpx.MockTransport(handler))
        try:
            return await client.decide({"screen": "s"}, _questions(250))
        finally:
            await client.aclose()

    decision = asyncio.run(run())
    assert len(calls) == decision.requests > 1 and sum(calls) == 250
    assert len(decision.data["answers"]) == 250
    assert decision.data["usage"]["input_tokens"] == 100 * len(calls)


def test_token_limit_error_is_explained_without_echoing_the_body():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"detail": {"error_type": "max_tokens_exceeded",
                                                    "secret": "nao-mostrar"}})

    async def run():
        client = JevClient(SETTINGS, httpx.MockTransport(handler))
        try:
            await client.decide({"screen": "s"}, _questions(2))
        finally:
            await client.aclose()

    with pytest.raises(ProviderError) as error:
        asyncio.run(run())
    assert "limite de tokens" in str(error.value)
    assert "nao-mostrar" not in str(error.value)
