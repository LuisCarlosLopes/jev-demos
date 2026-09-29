import time
from pathlib import Path

from .config import Settings
from .local import inspect_skill
from .models import Report
from .providers import JevProvider, ProviderError
from .semantic import build_request, decide, parse_response, with_cost


def validate(
    root: Path,
    policy: dict,
    settings: Settings | None = None,
    local_only: bool = False,
    provider: JevProvider | None = None,
) -> Report:
    started = time.perf_counter()
    snapshot = inspect_skill(root, policy, settings.known_secrets if settings else ())
    local_failed = any(f.severity == "error" for f in snapshot.findings)
    report = Report(
        skill=snapshot.root,
        status="failed" if local_failed else "local_only",
        reasons=["Falhas locais bloquearam a avaliação Jev."]
        if local_failed
        else ["Somente inspeção local concluída; qualidade semântica não avaliada."],
        findings=snapshot.findings,
        local_status="failed" if local_failed else "passed",
        semantic_status="skipped",
        # Snapshot da policy permite recalcular pesos/limites sem nova inferência.
        policy=policy,
    )
    if not local_failed and not local_only:
        report.provider = settings.provider if settings else None
        try:
            if settings is None:
                raise ProviderError("Configuração do provedor ausente.")
            state, questions = build_request(snapshot, policy)
            response = (provider or JevProvider(settings)).evaluate(state, questions)
            dimensions, risks, usage, model = parse_response(response, policy)
            report.dimensions, report.risks = dimensions, risks
            report.usage, report.model = with_cost(usage, model), model
            report.status, report.reasons, report.quality_score = decide(dimensions, risks, policy)
            report.semantic_status = "completed"
        except ProviderError as error:
            report.status = "error"
            report.semantic_status = "error"
            report.reasons = [str(error)]
    report.elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    return report
