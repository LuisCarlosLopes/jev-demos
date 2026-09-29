import argparse
from pathlib import Path

import yaml

from .config import Settings
from .policy import load_policy
from .reporting import render_console, write_reports
from .validator import validate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Valide uma Agent Skill com regras locais e avaliação semântica pelo Jev."
    )
    parser.add_argument("skill", type=Path, help="Pasta da skill ou seu SKILL.md")
    parser.add_argument("--provider", choices=("typesafe", "openrouter"))
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--policy", type=Path, default=Path("policy.yaml"))
    parser.add_argument("--local-only", action="store_true", help="Não chama a API")
    parser.add_argument("--json", type=Path, dest="json_path", help="Salvar relatório JSON")
    parser.add_argument(
        "--markdown", type=Path, dest="markdown_path", help="Salvar relatório Markdown"
    )
    args = parser.parse_args(argv)
    root = args.skill.parent if args.skill.name == "SKILL.md" else args.skill
    try:
        # Os relatórios não podem sobrescrever a skill, a policy ou o arquivo de credenciais.
        resolved_root = root.resolve()
        outputs = [path.resolve() for path in (args.json_path, args.markdown_path) if path]
        if len(set(outputs)) != len(outputs):
            raise ValueError("Use paths diferentes para JSON e Markdown.")
        for path in outputs:
            if path.is_relative_to(resolved_root) or path in {
                args.env_file.resolve(),
                args.policy.resolve(),
            }:
                raise ValueError("Salve os relatórios fora da skill, da policy e do .env.")
        policy = load_policy(args.policy)
        settings = None
        if not args.local_only or args.env_file.is_file():
            settings = Settings.load(args.env_file, args.provider)
        report = validate(root, policy, settings, local_only=args.local_only)
        render_console(report)
        write_reports(report, args.json_path, args.markdown_path)
    except (OSError, ValueError, yaml.YAMLError, RecursionError):
        # Não ecoa exceções de parsers que podem conter trechos sensíveis.
        parser.exit(
            2, "Erro de configuração/arquivo. Confira os paths, o .env e o schema de policy.yaml.\n"
        )
    return {"passed": 0, "local_only": 0, "failed": 1, "review": 2, "error": 3}[report.status]
