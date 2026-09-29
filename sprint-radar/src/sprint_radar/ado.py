"""Cliente REST mínimo do Azure DevOps. Só leitura; nunca ecoa corpo remoto em erros."""

import asyncio
import base64
from urllib.parse import quote

import httpx

from .config import Settings

API = "7.1"
FIELDS = [
    "System.Id",
    "System.WorkItemType",
    "System.Title",
    "System.State",
    "System.AssignedTo",
    "System.Tags",
    "System.Parent",
    "System.CreatedDate",
    "System.ChangedDate",
    "System.Description",
    "Microsoft.VSTS.Common.AcceptanceCriteria",
    "Microsoft.VSTS.Common.ActivatedDate",
    "Microsoft.VSTS.Common.StateChangeDate",
    "Microsoft.VSTS.Scheduling.OriginalEstimate",
    "Microsoft.VSTS.Scheduling.CompletedWork",
    "Microsoft.VSTS.Scheduling.RemainingWork",
]


class AdoError(Exception):
    """Erro seguro para exibir; sem headers, PAT ou corpo da resposta."""


class AdoClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        if not settings.ado_pat:
            raise AdoError("Preencha AZURE_DEVOPS_PAT no .env ou no ambiente.")
        self.settings = settings
        token = base64.b64encode(f":{settings.ado_pat}".encode()).decode()
        self._headers = {"Authorization": f"Basic {token}", "Accept": "application/json"}
        self._transport = transport
        self.org_url = f"https://dev.azure.com/{quote(settings.ado_org)}"
        self.project_url = f"{self.org_url}/{quote(settings.ado_project)}"
        self.team_url = f"{self.project_url}/{quote(settings.ado_team)}"
        self._semaphore = asyncio.Semaphore(8)

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers=self._headers, timeout=30, transport=self._transport, follow_redirects=False
        )

    async def _request(self, client: httpx.AsyncClient, method: str, url: str, **kwargs) -> dict:
        async with self._semaphore:
            try:
                response = await client.request(method, url, **kwargs)
            except httpx.TimeoutException:
                raise AdoError("Timeout ao consultar o Azure DevOps.") from None
            except httpx.HTTPError:
                raise AdoError("Falha de conexão com o Azure DevOps.") from None
        if response.status_code == 401:
            raise AdoError("Azure DevOps recusou o PAT (401). Confira AZURE_DEVOPS_PAT.")
        if response.status_code == 203:
            # O ADO responde 203 com HTML de login quando o PAT é inválido.
            raise AdoError("Azure DevOps devolveu página de login; o PAT parece inválido.")
        if response.status_code >= 300:
            raise AdoError(f"Azure DevOps respondeu HTTP {response.status_code} em {method} {url}.")
        try:
            data = response.json()
        except ValueError:
            raise AdoError("Azure DevOps devolveu uma resposta que não é JSON.") from None
        if not isinstance(data, dict):
            raise AdoError("Envelope inesperado na resposta do Azure DevOps.")
        return data

    async def list_iterations(self) -> list[dict]:
        async with self._client() as client:
            data = await self._request(
                client,
                "GET",
                f"{self.team_url}/_apis/work/teamsettings/iterations",
                params={"api-version": API},
            )
        items = []
        for it in data.get("value", []):
            attrs = it.get("attributes") or {}
            items.append(
                {
                    "id": it.get("id"),
                    "name": it.get("name"),
                    "path": it.get("path"),
                    "start": attrs.get("startDate"),
                    "finish": attrs.get("finishDate"),
                    # A REST devolve "past"/"current"/"future"; normalizamos para 0/1/2.
                    "timeframe": {"past": 0, "current": 1, "future": 2}.get(
                        attrs.get("timeFrame"), attrs.get("timeFrame")
                    ),
                }
            )
        return items

    async def capacity(self, iteration_id: str) -> tuple[list[dict], list[dict]]:
        """Capacidade por pessoa e days off do time inteiro para a iteração."""
        base = f"{self.team_url}/_apis/work/teamsettings/iterations/{iteration_id}"
        async with self._client() as client:
            members, team_off = await asyncio.gather(
                self._request(client, "GET", f"{base}/capacities", params={"api-version": API}),
                self._request(client, "GET", f"{base}/teamdaysoff", params={"api-version": API}),
            )
        people = []
        for member in members.get("teamMembers") or members.get("value") or []:
            identity = member.get("teamMember") or {}
            per_day = sum(
                float(a.get("capacityPerDay") or 0) for a in member.get("activities") or []
            )
            people.append(
                {
                    "name": identity.get("displayName") or "?",
                    "email": identity.get("uniqueName") or "",
                    "capacity_per_day": per_day,
                    "days_off": [
                        {"start": d.get("start"), "end": d.get("end")}
                        for d in member.get("daysOff") or []
                    ],
                }
            )
        return people, [
            {"start": d.get("start"), "end": d.get("end")} for d in team_off.get("daysOff") or []
        ]

    async def iteration_work_item_ids(self, iteration_path: str) -> list[int]:
        path = iteration_path.replace("'", "''")
        wiql = (
            "SELECT [System.Id] FROM WorkItems "
            f"WHERE [System.TeamProject] = @project AND [System.IterationPath] UNDER '{path}' "
            "ORDER BY [System.WorkItemType], [System.Id]"
        )
        async with self._client() as client:
            data = await self._request(
                client,
                "POST",
                f"{self.project_url}/_apis/wit/wiql",
                params={"api-version": API, "$top": 500},
                json={"query": wiql},
            )
        return [int(w["id"]) for w in data.get("workItems", []) if "id" in w]

    async def work_items(self, ids: list[int]) -> list[dict]:
        if not ids:
            return []
        async with self._client() as client:
            batches = [ids[i : i + 200] for i in range(0, len(ids), 200)]
            results = await asyncio.gather(
                *(
                    self._request(
                        client,
                        "POST",
                        f"{self.project_url}/_apis/wit/workitemsbatch",
                        params={"api-version": API},
                        json={"ids": batch, "fields": FIELDS},
                    )
                    for batch in batches
                )
            )
        items = []
        for data in results:
            items.extend(w for w in data.get("value", []) if isinstance(w, dict))
        return items

    async def comments(self, work_item_ids: list[int], top: int = 3) -> dict[int, list[dict]]:
        """Últimos comentários por work item, do mais recente para o mais antigo."""

        async def one(client: httpx.AsyncClient, wid: int) -> tuple[int, list[dict]]:
            data = await self._request(
                client,
                "GET",
                f"{self.project_url}/_apis/wit/workItems/{wid}/comments",
                params={"api-version": "7.1-preview.4", "$top": top, "order": "desc"},
            )
            out = []
            for c in data.get("comments", []):
                author = (c.get("createdBy") or {}).get("displayName") or "?"
                out.append(
                    {"author": author, "date": c.get("createdDate"), "text": c.get("text") or ""}
                )
            return wid, out

        async with self._client() as client:
            pairs = await asyncio.gather(*(one(client, wid) for wid in work_item_ids))
        return dict(pairs)
