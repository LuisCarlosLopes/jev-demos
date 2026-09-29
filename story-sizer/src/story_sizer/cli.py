import argparse
import asyncio
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .ado import AdoClient, AdoError
from .config import Settings, load_policy
from .jev import JevError
from .service import load_sprint_stories, size_stories

console = Console()


def _settings(args) -> Settings:
    return Settings.load(Path(args.env_file) if args.env_file else None, provider=args.provider)


async def cmd_sprints(args) -> int:
    ado = AdoClient(_settings(args))
    try:
        its = await ado.team_iterations()
    finally:
        await ado.aclose()
    table = Table("Nome", "Início", "Fim", "Janela", "Path")
    for it in its:
        table.add_row(
            it.name, (it.start or "")[:10], (it.finish or "")[:10], str(it.timeframe or ""), it.path
        )
    console.print(table)
    return 0


async def cmd_stories(args) -> int:
    settings = _settings(args)
    stories = await load_sprint_stories(settings, args.sprint, only_unsized=not args.all)
    table = Table("Id", "Estado", "Tam.", "Desc", "AC", "Título")
    for s in stories:
        table.add_row(
            str(s.id),
            s.state,
            s.size or "—",
            str(len(s.description_html)),
            str(len(s.acceptance_html)),
            s.title[:90],
        )
    console.print(table)
    console.print(f"{len(stories)} stories")
    return 0


def _bar(probs: dict, order: list[str], width: int = 24) -> str:
    cells = []
    for k in order:
        n = round(probs[k] * width)
        cells.append(f"[bold]{k}[/bold]{'█' * n}")
    return " ".join(cells)


async def cmd_size(args) -> int:
    settings = _settings(args)
    policy = load_policy(Path(args.policy) if args.policy else None)
    stories = await load_sprint_stories(settings, args.sprint, only_unsized=not args.all)
    if args.ids:
        wanted = {int(x) for x in args.ids.split(",")}
        stories = [s for s in stories if s.id in wanted]
    if args.limit:
        stories = stories[: args.limit]
    if not stories:
        console.print("Nenhuma story para classificar.")
        return 0
    console.print(f"Classificando {len(stories)} stories com {settings.jev_model}...")
    results = await size_stories(stories, settings, policy)

    by_id = {s.id: s for s in stories}
    total_tokens = total_cost = 0.0
    for r in results:
        s = by_id[r["id"]]
        console.rule(f"[bold]{s.id}[/bold] {r['input']['short_title'][:80]}")
        if r.get("error"):
            console.print(f"[red]{r['error']}[/red]")
            continue
        u = r["usage"]
        total_tokens += u["input_tokens"] or 0
        total_cost += u["cost_usd"] or 0
        band_color = {"firm": "green", "tentative": "yellow", "review": "grey50"}[r["band"]]
        console.print(
            f"Sugestão: [{band_color} bold]{r['suggested']}[/] "
            f"(conf {r['confidence']:.2f}, {r['band']}; 2ª opção {r['second']}) · "
            f"≈{r['expected_days']} dias · {u['input_tokens']} tokens · "
            f"US$ {u['cost_usd']:.6f} · {u['elapsed_ms']} ms"
        )
        console.print(_bar(r["probabilities"], policy["order"]))
        console.print(
            "  ".join(f"{f['label']} {f['score']:.1f}/{f['max']}" for f in r["factors"].values())
        )
        raised = [
            f"{f['label']} ({f['probability']:.2f})" for f in r["flags"].values() if f["raised"]
        ]
        if raised:
            console.print("[yellow]Alertas:[/yellow] " + ", ".join(raised))
        if r["input"]["truncated"]:
            console.print("[yellow]Descrição truncada.[/yellow]")
    console.rule()
    console.print(f"Total: {int(total_tokens)} tokens · US$ {total_cost:.6f}")
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        console.print(f"JSON salvo em {out}")
    return 0


def actual_size(hours: float, policy: dict) -> str:
    days = hours / policy["validation"]["hours_per_day"]
    upper = policy["validation"]["upper_days"]
    for name in policy["order"]:
        if name in upper and days <= upper[name]:
            return name
    return policy["order"][-1]


async def cmd_validate(args) -> int:
    """Compara a sugestão do Jev com as horas apontadas nas tasks filhas de stories fechadas."""
    settings = _settings(args)
    policy = load_policy(Path(args.policy) if args.policy else None)
    ado = AdoClient(settings)
    try:
        ids = await ado.story_ids(args.sprint, only_unsized=False)
        stories = [s for s in await ado.stories(ids) if s.state in {"Closed", "Resolved"}]
        hours = await ado.child_hours([s.id for s in stories])
    finally:
        await ado.aclose()
    # Referência limpa: descarta fechadas sem horas e apontamentos parciais
    # (menos da metade da estimativa), que distorcem mais do que ensinam.
    min_ratio = policy["validation"].get("min_completed_ratio", 0.5)
    discarded = [
        s.id
        for s in stories
        if hours[s.id]["completed"] <= 0
        or hours[s.id]["completed"] < min_ratio * hours[s.id]["original"]
    ]
    stories = [s for s in stories if s.id not in discarded]
    if discarded:
        console.print(f"[grey50]Descartadas por apontamento ausente/parcial: {discarded}[/grey50]")
    if args.limit:
        stories = stories[: args.limit]
    if not stories:
        console.print("Nenhuma story fechada com horas apontadas nesta sprint.")
        return 0
    console.print(f"Validando {len(stories)} stories fechadas com horas apontadas...")
    results = {r["id"]: r for r in await size_stories(stories, settings, policy)}

    order = policy["order"]
    # `completed` mede o realizado; `original` mede o julgamento do time ao planejar,
    # que é o que uma sugestão feita a partir do texto tenta reproduzir.
    field = "completed" if args.target == "realizado" else "original"
    table = Table("Id", "Título", "Horas", "Real", "Jev", "Conf", "Δ", "Distribuição")
    exact = within_one = 0
    confusion = {a: dict.fromkeys(order, 0) for a in order}
    rows = []
    for s in stories:
        r = results[s.id]
        if r.get("error"):
            table.add_row(str(s.id), s.title[:50], "", "", f"[red]{r['error']}[/red]", "", "", "")
            continue
        h = hours[s.id][field]
        real, jev = actual_size(h, policy), r["suggested"]
        delta = order.index(jev) - order.index(real)
        exact += delta == 0
        within_one += abs(delta) <= 1
        confusion[real][jev] += 1
        color = "green" if delta == 0 else ("yellow" if abs(delta) == 1 else "red")
        table.add_row(
            str(s.id),
            r["input"]["short_title"][:50],
            f"{h:.0f}",
            real,
            f"[{color}]{jev}[/{color}]",
            f"{r['confidence']:.2f}",
            f"{delta:+d}",
            _bar(r["probabilities"], order, 10),
        )
        rows.append(
            {
                "id": s.id,
                "hours": h,
                "actual": real,
                "jev": jev,
                "delta": delta,
                "confidence": r["confidence"],
                "probabilities": r["probabilities"],
            }
        )
    console.print(table)
    n = len(rows)
    if n:
        console.print(
            f"Acerto exato: {exact}/{n} ({100 * exact / n:.0f}%) · "
            f"dentro de ±1 tamanho: {within_one}/{n} ({100 * within_one / n:.0f}%)"
        )
        # Baseline trivial: sem isso, um acerto de 40% parece bom quando não é.
        counts = {k: sum(1 for x in rows if x["actual"] == k) for k in order}
        mode = max(order, key=counts.get)
        b_exact = counts[mode]
        b_w1 = sum(1 for x in rows if abs(order.index(x["actual"]) - order.index(mode)) <= 1)
        console.print(
            f"[grey50]Baseline 'sempre {mode}': {100 * b_exact / n:.0f}% exato · "
            f"{100 * b_w1 / n:.0f}% ±1 (alvo: {args.target})[/grey50]"
        )
        cm = Table("real \\ jev", *order, title="Matriz de confusão")
        for a in order:
            cm.add_row(a, *(str(confusion[a][b]) for b in order))
        console.print(cm)
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {"sprint": args.sprint, "rows": rows, "confusion": confusion},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        console.print(f"JSON salvo em {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Sugestão de tamanho de User Stories com Jev.")
    p.add_argument("--env-file")
    p.add_argument("--provider", choices=("typesafe", "openrouter"))
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sprints", help="Lista as iterações do time.")
    ps = sub.add_parser("stories", help="Lista stories de uma sprint.")
    ps.add_argument("--sprint", required=True, help="Nome da iteração, ex.: Sprint06")
    ps.add_argument("--all", action="store_true", help="Incluir stories já dimensionadas.")
    pz = sub.add_parser("size", help="Classifica stories de uma sprint.")
    pz.add_argument("--sprint", required=True)
    pz.add_argument("--ids", help="Ids separados por vírgula.")
    pz.add_argument("--limit", type=int)
    pz.add_argument("--all", action="store_true")
    pz.add_argument("--policy")
    pz.add_argument("--json", help="Salvar resultado completo em JSON.")
    pv = sub.add_parser("validate", help="Compara Jev com horas reais de stories fechadas.")
    pv.add_argument("--sprint", required=True)
    pv.add_argument("--limit", type=int)
    pv.add_argument("--policy")
    pv.add_argument("--json")
    pv.add_argument(
        "--target",
        choices=["estimativa", "realizado"],
        default="estimativa",
        help="Comparar com a estimativa das tasks (padrão) ou com as horas apontadas.",
    )
    args = p.parse_args(argv)

    handlers = {
        "sprints": cmd_sprints,
        "stories": cmd_stories,
        "size": cmd_size,
        "validate": cmd_validate,
    }
    try:
        return asyncio.run(handlers[args.cmd](args))
    except (AdoError, JevError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        return 2


if __name__ == "__main__":
    sys.exit(main())
