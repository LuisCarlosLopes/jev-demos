"""Passo 0: mede a latência real do Jev antes de apresentar a demo.

Envia a mesma consulta com N artefatos do catálogo (N perguntas Noul + 5 facetas) e
repete cada tamanho algumas vezes. Usa a chave do .env; custa frações de centavo.

    uv run python scripts/bench_latency.py --sizes 10 50 110 --runs 5
"""

import argparse
import asyncio
import statistics
from pathlib import Path

from catalog_ai.app import load_catalog
from catalog_ai.config import Settings
from catalog_ai.decisions import build_request
from catalog_ai.jev import JevClient, ProviderError, estimate_cost

ROOT = Path(__file__).resolve().parents[1]


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", type=int, nargs="+", default=[10, 50, 110])
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--query", default="preciso revisar PRs de um serviço em C#")
    parser.add_argument("--provider", choices=["typesafe", "openrouter"])
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    args = parser.parse_args()

    settings = Settings.load(args.env_file, args.provider)
    if settings.fake:
        parser.exit(2, "Desative JEV_FAKE para medir o Jev de verdade.\n")
    catalog = load_catalog(ROOT / "data" / "catalog.json")
    client = JevClient(settings)
    try:
        # Primeira chamada abre a conexão TLS; fica fora da estatística.
        state, questions, _ = build_request(args.query, {}, catalog[:1])
        await client.decide(state, questions)
        print(f"{settings.provider} · {settings.model}\n")
        header = ("artefatos", "perguntas", "p50 ms", "p95 ms", "tokens", "US$")
        print("{:>9} {:>9} {:>8} {:>8} {:>8} {:>10}".format(*header))
        for size in args.sizes:
            state, questions, _ = build_request(args.query, {}, catalog[:size])
            timings, tokens = [], 0
            for _ in range(args.runs):
                data, elapsed = await client.decide(state, questions)
                timings.append(elapsed)
                tokens = data.get("usage", {}).get("input_tokens", 0)
            timings.sort()
            p95 = timings[min(len(timings) - 1, round(0.95 * (len(timings) - 1)))]
            cost = estimate_cost({"input_tokens": tokens}) or 0
            print(
                f"{size:>9} {len(questions):>9} {statistics.median(timings):>8.0f} "
                f"{p95:>8.0f} {tokens:>8} {cost:>10.6f}"
            )
    except ProviderError as error:
        parser.exit(3, f"Erro: {error}\n")
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
