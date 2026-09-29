import json
import os
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

import yaml

from .models import Finding, Snapshot
from .secrets import scan_secrets
from .yaml_utils import load_yaml

OPTIONAL_FIELDS = {"license", "compatibility", "metadata", "allowed-tools"}
LINK = re.compile(r"\[[^\]\n]*\]\(\s*(<[^>]+>|[^\s)]+)(?:\s+[^)]*)?\)")
RESOURCE = re.compile(r"(?<![\w/])(?:scripts|references|assets|agents)/[\w./-]+")


def inspect_skill(root: Path, policy: dict, known_secrets: tuple[str, ...] = ()) -> Snapshot:
    snapshot = Snapshot(str(root.absolute()))

    def finding(rule, message, path=None, line=None, severity="error"):
        snapshot.findings.append(Finding(rule, severity, message, path, line))

    if root.is_symlink() or not root.is_dir():
        finding("structure.root", "Informe uma pasta de skill existente, sem symlink.")
        return snapshot
    root = root.resolve()
    total = 0
    count = 0
    stopped = False

    def walk_error(error):
        finding("scan.unreadable", "Não foi possível inspecionar parte da pasta.")

    for directory, dirs, filenames in os.walk(root, followlinks=False, onerror=walk_error):
        dirs.sort()
        for name in list(dirs):
            path = Path(directory) / name
            if path.is_symlink():
                finding(
                    "scan.symlink",
                    "Symlink não é inspecionado nem enviado.",
                    path.relative_to(root).as_posix(),
                )
                dirs.remove(name)
        for name in sorted(filenames):
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            snapshot.inventory.append(relative)
            count += 1
            if count > policy["max_files"]:
                finding("scan.file_limit", "Limite de arquivos excedido; inspeção incompleta.")
                stopped = True
                break
            if path.is_symlink() or not path.is_file():
                finding("scan.symlink", "Arquivo especial ou symlink não é inspecionado.", relative)
                continue
            try:
                with path.open("rb") as file:
                    raw = file.read(policy["max_file_bytes"] + 1)
            except OSError:
                finding("scan.unreadable", "Arquivo não pôde ser lido.", relative)
                continue
            if len(raw) > policy["max_file_bytes"]:
                finding("scan.file_size", "Arquivo excede o limite; inspeção incompleta.", relative)
                continue
            total += len(raw)
            if total > policy["max_total_bytes"]:
                finding("scan.total_size", "Limite total de leitura excedido; inspeção incompleta.")
                stopped = True
                break
            # Padrões também são procurados em binários, sem enviá-los ao modelo.
            text = raw.decode("utf-8", errors="replace")
            snapshot.findings.extend(scan_secrets(text, relative, known_secrets))
            try:
                decoded = raw.decode("utf-8")
            except UnicodeDecodeError:
                finding(
                    "scan.binary",
                    "Binário: padrões escaneados; conteúdo fora da avaliação Jev.",
                    relative,
                    severity="warning",
                )
                continue
            if "\x00" in decoded:
                finding(
                    "scan.binary",
                    "Binário: padrões escaneados; conteúdo fora da avaliação Jev.",
                    relative,
                    severity="warning",
                )
                continue
            snapshot.files[relative] = decoded
        if stopped:
            break

    for required in policy["required_paths"]:
        candidate = root / required
        if not candidate.exists():
            finding(
                "structure.required_path", "Path obrigatório pela policy não encontrado.", required
            )

    if "SKILL.md" not in snapshot.files:
        finding("structure.manifest", "SKILL.md UTF-8 é obrigatório na raiz.", "SKILL.md")
        return snapshot
    text = snapshot.files["SKILL.md"]
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        finding(
            "frontmatter.missing",
            "SKILL.md deve começar com frontmatter delimitado por ---.",
            "SKILL.md",
            1,
        )
        return snapshot
    closing = next((i for i in range(1, len(lines)) if lines[i] == "---"), None)
    if closing is None:
        finding("frontmatter.unclosed", "Frontmatter sem delimitador final ---.", "SKILL.md", 1)
        return snapshot
    try:
        metadata = load_yaml("\n".join(lines[1:closing]))
    except (yaml.YAMLError, ValueError, RecursionError):
        finding(
            "frontmatter.yaml",
            "YAML inválido, duplicado ou com aliases não suportados.",
            "SKILL.md",
            2,
        )
        return snapshot
    if not isinstance(metadata, dict):
        finding("frontmatter.mapping", "Frontmatter deve ser um mapa YAML.", "SKILL.md", 2)
        return snapshot
    snapshot.frontmatter = json.loads(json.dumps(metadata, default=str))
    snapshot.body = "\n".join(lines[closing + 1 :]).strip()
    name = metadata.get("name")
    valid_name = (
        isinstance(name, str)
        and 1 <= len(name) <= 64
        and not name.startswith("-")
        and not name.endswith("-")
        and "--" not in name
        and all(c == "-" or (c.isalnum() and c == c.lower()) for c in name)
    )
    if not valid_name:
        finding(
            "frontmatter.name",
            "name: 1–64 caracteres alfanuméricos minúsculos e hífens simples.",
            "SKILL.md",
        )
    elif name != root.name:
        finding(
            "frontmatter.name_directory", "name deve corresponder ao nome da pasta.", "SKILL.md"
        )
    description = metadata.get("description")
    if not isinstance(description, str) or not description.strip() or len(description) > 1024:
        finding(
            "frontmatter.description",
            "description deve ser string não vazia de até 1024 caracteres.",
            "SKILL.md",
        )
    if not snapshot.body:
        finding("body.empty", "Instruções após o frontmatter não podem ser vazias.", "SKILL.md")
    if len(lines[closing + 1 :]) > 500:
        finding(
            "body.length",
            "Mais de 500 linhas: considere referências para detalhes condicionais.",
            "SKILL.md",
            severity="warning",
        )
    for key in OPTIONAL_FIELDS - {"metadata"}:
        if key in metadata and (not isinstance(metadata[key], str) or not metadata[key].strip()):
            finding("frontmatter.optional_type", f"{key} deve ser string não vazia.", "SKILL.md")
    compatibility = metadata.get("compatibility")
    if isinstance(compatibility, str) and len(compatibility) > 500:
        finding(
            "frontmatter.compatibility", "compatibility tem limite de 500 caracteres.", "SKILL.md"
        )
    if "metadata" in metadata and (
        not isinstance(metadata["metadata"], dict)
        or any(
            not isinstance(k, str) or not isinstance(v, str)
            for k, v in metadata["metadata"].items()
        )
    ):
        finding("frontmatter.metadata", "metadata deve mapear strings para strings.", "SKILL.md")
    if set(metadata) - {"name", "description"} - OPTIONAL_FIELDS:
        finding(
            "frontmatter.extension",
            "Campos extras fora do perfil Agent Skills deste demo.",
            "SKILL.md",
            severity="warning",
        )

    # Links Markdown e paths convencionais em documentos. Não busca regex em scripts.
    for relative, content in snapshot.files.items():
        if not relative.lower().endswith(".md"):
            continue
        links = list(LINK.finditer(content))
        targets = [(m.group(1).strip("<>"), m.start(), False) for m in links]
        targets += [
            (m.group(0).rstrip("."), m.start(), True)
            for m in RESOURCE.finditer(content)
            if not any(link.start() <= m.start() < link.end() for link in links)
        ]
        checked = set()
        for target, start, from_root in targets:
            if (target, from_root) in checked:
                continue
            checked.add((target, from_root))
            try:
                parsed = urlsplit(target)
            except ValueError:
                finding(
                    "reference.invalid",
                    "Referência com formato inválido.",
                    relative,
                    content.count("\n", 0, start) + 1,
                )
                continue
            if parsed.scheme or target.startswith(("#", "//")):
                continue
            target_path = unquote(parsed.path)
            if not target_path:
                continue
            base = root if from_root else (root / relative).parent
            candidate = (base / target_path).resolve()
            line = content.count("\n", 0, start) + 1
            if not candidate.is_relative_to(root):
                finding(
                    "reference.outside", "Referência local sai da pasta da skill.", relative, line
                )
            elif not candidate.exists():
                finding("reference.missing", "Referência local não encontrada.", relative, line)
    return snapshot
