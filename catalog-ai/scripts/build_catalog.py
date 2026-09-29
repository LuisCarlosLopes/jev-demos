"""Gera data/catalog.json a partir do registro público de skills (skills.sh).

É o mesmo registro que a skill `find-skills` consulta com `npx skills find`. O script
busca uma lista de temas, deduplica, baixa a descrição completa de cada skill e
acrescenta as tags do catálogo (tecnologia, finalidade, time dono). Times são
fictícios: representam a organização de exemplo do demo.

    uv run python scripts/build_catalog.py
"""

import asyncio
import hashlib
import json
import re
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
SEARCH = "https://skills.sh/api/search"
CACHE = ROOT / "scripts" / ".cache"
PER_QUERY = 8
TARGET = 100
# O registro limita requisições por IP: uma por vez, com intervalo e backoff em 429.
INTERVAL = 0.6

# (consulta no registro, finalidade atribuída aos resultados)
QUERIES = [
    ("code review", "code-review"),
    ("pull request review", "code-review"),
    ("unit testing", "testes"),
    ("e2e testing playwright", "testes"),
    ("tdd", "testes"),
    ("documentation writing", "documentacao"),
    ("readme api docs", "documentacao"),
    ("react", "frontend"),
    ("nextjs", "frontend"),
    ("tailwind ui design", "design"),
    ("frontend design", "design"),
    ("dotnet csharp", "backend"),
    ("rest api backend", "backend"),
    ("python", "backend"),
    ("sql database postgres", "dados"),
    ("data analysis", "dados"),
    ("docker kubernetes", "devops"),
    ("github actions ci", "devops"),
    ("azure", "devops"),
    ("security audit", "seguranca"),
    ("architecture refactoring", "arquitetura"),
    ("debugging", "arquitetura"),
    ("mcp server", "agentes-ia"),
    ("skill creator agent", "agentes-ia"),
    ("prompt engineering llm", "agentes-ia"),
    ("git commit", "produtividade"),
    ("project planning prd", "gestao"),
]

TEAM_BY_PURPOSE = {
    "code-review": "Plataforma",
    "testes": "Qualidade",
    "documentacao": "Produto",
    "frontend": "Frontend",
    "design": "Frontend",
    "backend": "Backend",
    "dados": "Dados & IA",
    "devops": "DevOps",
    "seguranca": "Plataforma",
    "arquitetura": "Plataforma",
    "agentes-ia": "Dados & IA",
    "produtividade": "Plataforma",
    "gestao": "Produto",
}

TECH_PATTERNS = {
    "React": r"\breact\b|\bjsx\b|\bnext\.?js\b|react native",
    "TypeScript/JavaScript": r"typescript|javascript|\bnode(\.js)?\b|\bnpm\b|\bvite\b",
    "C#/.NET": r"c#|\.net\b|dotnet|asp\.net|\bcsharp\b|blazor|entity framework",
    "Python": r"\bpython\b|\bpytest\b|django|fastapi|flask|pandas",
    "Java": r"\bjava\b|spring|kotlin|gradle|maven",
    "SQL/Bancos": r"\bsql\b|postgres|mysql|sqlite|database|supabase|prisma",
    "Cloud/Azure": r"\bazure\b|\baws\b|\bgcp\b|cloudflare|vercel",
    "Docker/Kubernetes": r"docker|kubernetes|\bk8s\b|helm|container",
    "Git/GitHub": r"\bgit\b|github|pull request|\bpr\b|commit",
    "Web/CSS": r"\bcss\b|tailwind|\bhtml\b|shadcn|accessibility|a11y",
}


PURPOSE_PATTERNS = {
    "code-review": r"code review|review (the |a |my )?(code|changes|pr|pull request|branch|diff)",
    "testes": r"tests?|testing|tdd|playwright|jest|vitest|pytest|e2e",
    "documentacao": r"documentation|docs|readme|technical writing|changelog",
    "frontend": r"react|next\.?js|frontend|vue|svelte|component",
    "design": r"ui|ux|design system|visual design|tailwind|typography|landing page",
    "backend": r"backend|api|endpoint|server-side|microservice|sdk",
    "dados": r"data|analytics|sql|database|spreadsheet|etl|dashboard",
    "devops": r"deploy|ci|pipeline|docker|kubernetes|infrastructure|terraform|github actions",
    "seguranca": r"security|vulnerab|secret|owasp|threat|auth(entication)?",
    "arquitetura": r"architecture|refactor|debug|codebase design|technical debt",
    "agentes-ia": r"agents?|llm|mcp|prompt|skills?|claude",
    "produtividade": r"git|commit|workflow automation|productivity|terminal",
    "gestao": r"prd|planning|roadmap|backlog|user stor|sprint|requirements",
}


def purpose_of(text: str, fallback: str) -> str:
    """Finalidade pelo conteúdo; a consulta que trouxe a skill só desempata."""
    low = text.lower()
    hits = {k: len(re.findall(p, low)) for k, p in PURPOSE_PATTERNS.items()}
    best = max(hits.values())
    if best == 0 or hits[fallback] == best:
        return fallback
    return max(hits, key=hits.get)


def tech_tags(text: str) -> list[str]:
    low = text.lower()
    return [tech for tech, pattern in TECH_PATTERNS.items() if re.search(pattern, low)]


def description_from(html: str) -> str:
    for raw in re.findall(r'"description":"((?:[^"\\]|\\.)*)"', html):
        try:
            text = json.loads(f'"{raw}"')
        except json.JSONDecodeError:
            continue
        if text and not text.startswith("Discover and install skills"):
            return " ".join(text.split())
    match = re.search(r'<meta name="description" content="([^"]*)"', html)
    return match.group(1).replace("&#x27;", "'").replace("&quot;", '"') if match else ""


async def fetch(client: httpx.AsyncClient, url: str, params: dict | None = None) -> str | None:
    """GET com cache em disco; None para 404. Reexecuções não repetem requisições."""
    key = hashlib.sha256(f"{url}?{sorted((params or {}).items())}".encode()).hexdigest()[:24]
    cached = CACHE / key
    if cached.is_file():
        return cached.read_text(encoding="utf-8")
    for attempt in range(6):
        await asyncio.sleep(INTERVAL)
        response = await client.get(url, params=params)
        if response.status_code == 429:
            await asyncio.sleep(float(response.headers.get("Retry-After") or 5 * (attempt + 1)))
            continue
        if response.status_code == 404:
            return None
        response.raise_for_status()
        CACHE.mkdir(parents=True, exist_ok=True)
        cached.write_text(response.text, encoding="utf-8")
        return response.text
    raise RuntimeError(f"Registro continua limitando requisições: {url}")


async def search(client: httpx.AsyncClient, query: str) -> list[dict]:
    body = await fetch(client, SEARCH, {"q": query, "limit": 30})
    return json.loads(body).get("skills", []) if body else []


async def main() -> None:
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        results = [await search(client, q) for q, _ in QUERIES]
        picked: dict[str, dict] = {}
        # Rodízio entre consultas para manter a diversidade de finalidades.
        for rank in range(30):
            for (query, purpose), hits in zip(QUERIES, results, strict=True):
                taken = sum(1 for p in picked.values() if p["query"] == query)
                if rank >= len(hits) or taken >= PER_QUERY or len(picked) >= TARGET:
                    continue
                hit = hits[rank]
                if hit["id"] not in picked:
                    picked[hit["id"]] = {**hit, "query": query, "purpose": purpose}

        async def enrich(hit: dict) -> dict | None:
            page = await fetch(client, f"https://skills.sh/{hit['id']}")
            description = description_from(page) if page else ""
            if not description:
                return None
            text = f"{hit['name']} {description}"
            purpose = purpose_of(text, hit["purpose"])
            return {
                "id": hit["id"].replace("/", "__"),
                "name": hit["name"],
                "type": "skill",
                "source": hit["source"],
                "url": f"https://skills.sh/{hit['id']}",
                "install": f"npx skills add {hit['source']}@{hit['skillId']}",
                "description": description,
                "purpose": purpose,
                "technologies": tech_tags(text),
                "team": TEAM_BY_PURPOSE[purpose],
                "installs": hit.get("installs", 0),
                "origin": "skills.sh",
            }

        items = []
        for number, hit in enumerate(picked.values(), 1):
            if item := await enrich(hit):
                items.append(item)
            print(f"\r{number}/{len(picked)} páginas", end="", flush=True)
        print()

    internal = json.loads((ROOT / "data" / "internal.json").read_text(encoding="utf-8"))
    catalog = sorted(items, key=lambda i: -i["installs"]) + internal
    out = ROOT / "data" / "catalog.json"
    out.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(items)} skills do registro + {len(internal)} internos -> {out}")


if __name__ == "__main__":
    asyncio.run(main())
