import base64
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import Settings

API = "7.1"

STORY_FIELDS = [
    "System.Id",
    "System.Title",
    "System.State",
    "System.IterationPath",
    "System.AreaPath",
    "System.Tags",
    "System.AssignedTo",
    "System.Description",
    "Microsoft.VSTS.Common.AcceptanceCriteria",
    "Custom.SR_TAMANHO",
]


class AdoError(Exception):
    """Erro seguro para exibir; não inclui headers nem o PAT."""


@dataclass
class Iteration:
    id: str
    name: str
    path: str
    start: str | None
    finish: str | None
    timeframe: str | None


@dataclass
class Story:
    id: int
    title: str
    state: str
    iteration: str
    tags: list[str] = field(default_factory=list)
    assigned_to: str | None = None
    description_html: str = ""
    acceptance_html: str = ""
    size: str | None = None

    @property
    def url(self) -> str:
        return f"https://dev.azure.com/{{org}}/{{project}}/_workitems/edit/{self.id}"


class AdoClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        if not settings.ado_pat:
            raise AdoError("Preencha AZURE_DEVOPS_PAT no .env.")
        self.s = settings
        token = base64.b64encode(f":{settings.ado_pat}".encode()).decode()
        self._client = httpx.AsyncClient(
            base_url=f"https://dev.azure.com/{settings.ado_org}",
            headers={"Authorization": f"Basic {token}", "Accept": "application/json"},
            timeout=30,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    def item_url(self, item_id: int) -> str:
        return (
            f"https://dev.azure.com/{self.s.ado_org}/{self.s.ado_project}/_workitems/edit/{item_id}"
        )

    async def _request(self, method: str, url: str, **kw: Any) -> Any:
        try:
            r = await self._client.request(method, url, params={"api-version": API}, **kw)
        except httpx.HTTPError:
            raise AdoError("Falha de conexão com o Azure DevOps.") from None
        if r.status_code == 401:
            raise AdoError("Azure DevOps recusou o PAT (401). Confira validade e escopo.")
        if r.status_code == 403:
            raise AdoError("PAT sem permissão para esta operação (403).")
        if r.status_code >= 300:
            raise AdoError(f"Azure DevOps respondeu HTTP {r.status_code}.")
        return r.json()

    async def team_iterations(self) -> list[Iteration]:
        data = await self._request(
            "GET", f"/{self.s.ado_project}/{self.s.ado_team}/_apis/work/teamsettings/iterations"
        )
        out = []
        for it in data.get("value", []):
            attrs = it.get("attributes", {})
            out.append(
                Iteration(
                    id=it["id"],
                    name=it["name"],
                    path=it["path"],
                    start=attrs.get("startDate"),
                    finish=attrs.get("finishDate"),
                    timeframe=attrs.get("timeFrame"),
                )
            )
        return out

    async def story_ids(self, iteration_path: str, only_unsized: bool = True) -> list[int]:
        # Sem `UNDER` para não puxar stories de sub-iterações inexistentes; caminho literal.
        path = iteration_path.replace("'", "''")
        clauses = [
            f"[System.TeamProject] = '{self.s.ado_project}'",
            "[System.WorkItemType] = 'User Story'",
            f"[System.IterationPath] = '{path}'",
            "[System.State] NOT IN ('Removed', 'Dropped')",
        ]
        if only_unsized:
            clauses.append("[Custom.SR_TAMANHO] = ''")
        wiql = "SELECT [System.Id] FROM WorkItems WHERE " + " AND ".join(clauses)
        wiql += " ORDER BY [System.State], [System.Id]"
        data = await self._request(
            "POST", f"/{self.s.ado_project}/_apis/wit/wiql", json={"query": wiql}
        )
        return [w["id"] for w in data.get("workItems", [])]

    async def stories(self, ids: list[int]) -> list[Story]:
        out: list[Story] = []
        for start in range(0, len(ids), 150):
            chunk = ids[start : start + 150]
            data = await self._request(
                "POST",
                f"/{self.s.ado_project}/_apis/wit/workitemsbatch",
                json={"ids": chunk, "fields": STORY_FIELDS},
            )
            for item in data.get("value", []):
                f = item["fields"]
                assigned = f.get("System.AssignedTo")
                assigned_name = assigned.get("displayName") if isinstance(assigned, dict) else None
                out.append(
                    Story(
                        id=item["id"],
                        title=f.get("System.Title", ""),
                        state=f.get("System.State", ""),
                        iteration=f.get("System.IterationPath", ""),
                        tags=[t.strip() for t in (f.get("System.Tags") or "").split(";") if t],
                        assigned_to=assigned_name,
                        description_html=f.get("System.Description") or "",
                        acceptance_html=f.get("Microsoft.VSTS.Common.AcceptanceCriteria") or "",
                        size=f.get("Custom.SR_TAMANHO") or None,
                    )
                )
        return out

    async def child_hours(self, story_ids: list[int]) -> dict[int, dict]:
        """Soma CompletedWork/OriginalEstimate das tasks filhas, por story."""
        out: dict[int, dict] = {
            sid: {"completed": 0.0, "original": 0.0, "tasks": 0} for sid in story_ids
        }
        for start in range(0, len(story_ids), 100):
            chunk = ", ".join(str(i) for i in story_ids[start : start + 100])
            wiql = (
                "SELECT [System.Id] FROM WorkItems WHERE "
                f"[System.TeamProject] = '{self.s.ado_project}' AND "
                "[System.WorkItemType] = 'Task' AND "
                "[System.State] NOT IN ('Removed', 'Dropped') AND "
                f"[System.Parent] IN ({chunk})"
            )
            data = await self._request(
                "POST", f"/{self.s.ado_project}/_apis/wit/wiql", json={"query": wiql}
            )
            ids = [w["id"] for w in data.get("workItems", [])]
            for t0 in range(0, len(ids), 150):
                batch = await self._request(
                    "POST",
                    f"/{self.s.ado_project}/_apis/wit/workitemsbatch",
                    json={
                        "ids": ids[t0 : t0 + 150],
                        "fields": [
                            "System.Parent",
                            "Microsoft.VSTS.Scheduling.CompletedWork",
                            "Microsoft.VSTS.Scheduling.OriginalEstimate",
                        ],
                    },
                )
                for item in batch.get("value", []):
                    f = item["fields"]
                    parent = f.get("System.Parent")
                    if parent in out:
                        out[parent]["completed"] += float(
                            f.get("Microsoft.VSTS.Scheduling.CompletedWork") or 0
                        )
                        out[parent]["original"] += float(
                            f.get("Microsoft.VSTS.Scheduling.OriginalEstimate") or 0
                        )
                        out[parent]["tasks"] += 1
        return out

    async def set_size(self, item_id: int, size: str, field_name: str) -> None:
        if not self.s.allow_write:
            raise AdoError("Escrita desligada: defina ALLOW_WRITE=true no .env.")
        patch = [{"op": "add", "path": f"/fields/{field_name}", "value": size}]
        await self._request(
            "PATCH",
            f"/{self.s.ado_project}/_apis/wit/workitems/{item_id}",
            json=patch,
            headers={"Content-Type": "application/json-patch+json"},
        )
