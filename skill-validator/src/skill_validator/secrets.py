import math
import re
from collections import Counter

from .models import Finding

# Heurísticas locais, não verificação de validade junto ao emissor.
PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----"),
    "openrouter_key": re.compile(r"\bsk-or-v1-[A-Za-z0-9_-]{20,}\b"),
    "api_key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    "github_token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    "credential_url": re.compile(r"[a-z][a-z0-9+.-]*://[^\s/:]+:[^\s/@]+@", re.I),
}
ASSIGNMENT = re.compile(
    r"\b[\w.-]*(?:api[_-]?key|secret|password|passwd|token|credential)[\w.-]*"
    r"[\"']?\s*[:=]\s*[\"']?([^\s\"'`,;#]+)",
    re.I,
)


def placeholder(value: str) -> bool:
    lower = value.lower()
    return (
        value.startswith(("${", "$", "<", "{{"))
        or lower in {"none", "null", "true", "false", "changeme", "example", "placeholder"}
        or lower.startswith(("your_", "your-", "example_", "example-", "replace_", "replace-"))
    )


def entropy(value: str) -> float:
    return -sum((n / len(value)) * math.log2(n / len(value)) for n in Counter(value).values())


def scan_secrets(text: str, path: str, known_secrets: tuple[str, ...] = ()) -> list[Finding]:
    hits: set[tuple[str, int]] = set()
    for rule, pattern in PATTERNS.items():
        for match in pattern.finditer(text):
            hits.add((rule, text.count("\n", 0, match.start()) + 1))
    for match in ASSIGNMENT.finditer(text):
        value = match.group(1)
        if not placeholder(value) and len(value) >= 8:
            if entropy(value) >= 3 or "password" in match.group(0).lower():
                hits.add(("credential_assignment", text.count("\n", 0, match.start()) + 1))
    for secret in known_secrets:
        start = text.find(secret)
        if start >= 0:
            hits.add(("configured_api_key", text.count("\n", 0, start) + 1))
    return [
        Finding(f"secret.{rule}", "error", "Possível segredo detectado; valor omitido.", path, line)
        for rule, line in sorted(hits)
    ]
