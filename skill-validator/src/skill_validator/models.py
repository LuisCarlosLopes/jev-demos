from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    path: str | None = None
    line: int | None = None


@dataclass
class Snapshot:
    root: str
    frontmatter: dict[str, Any] = field(default_factory=dict)
    body: str = ""
    files: dict[str, str] = field(default_factory=dict)
    inventory: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)


@dataclass
class Report:
    skill: str
    status: str
    reasons: list[str]
    findings: list[Finding]
    local_status: str
    semantic_status: str
    provider: str | None = None
    model: str | None = None
    policy: dict[str, Any] = field(default_factory=dict)
    quality_score: float | None = None
    dimensions: dict[str, Any] = field(default_factory=dict)
    risks: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)
    elapsed_ms: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
