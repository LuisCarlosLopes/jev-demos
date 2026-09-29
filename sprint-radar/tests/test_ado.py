import json

import httpx
import pytest

from sprint_radar.ado import AdoClient, AdoError
from sprint_radar.config import Settings


def settings(pat="pat"):
    return Settings("exemplo-org", "Projeto Demo", "Team-demo", pat)


async def test_urls_auth_and_batching():
    seen = []

    def handler(request):
        seen.append(request)
        assert request.headers["Authorization"].startswith("Basic ")
        url = str(request.url)
        if url.endswith("/iterations?api-version=7.1"):
            assert "/Projeto%20Demo/Team-demo/_apis/work/" in url
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "a",
                            "name": "Sprint06",
                            "path": "p",
                            "attributes": {"startDate": "s", "finishDate": "f", "timeFrame": 1},
                        }
                    ]
                },
            )
        if "/wiql" in url:
            query = json.loads(request.content)["query"]
            assert "UNDER 'Projeto Demo\\Team-demo\\Sprint06'" in query
            return httpx.Response(200, json={"workItems": [{"id": i} for i in range(250)]})
        if "/workitemsbatch" in url:
            ids = json.loads(request.content)["ids"]
            assert len(ids) <= 200
            return httpx.Response(200, json={"value": [{"id": i, "fields": {}} for i in ids]})
        if "/capacities" in url:
            return httpx.Response(
                200,
                json={
                    "teamMembers": [
                        {
                            "teamMember": {"displayName": "Ana", "uniqueName": "ana@x"},
                            "activities": [{"capacityPerDay": 6}],
                            "daysOff": [],
                        }
                    ]
                },
            )
        if "/teamdaysoff" in url:
            return httpx.Response(200, json={"daysOff": [{"start": "x", "end": "y"}]})
        if "/comments" in url:
            assert request.url.params["order"] == "desc"
            return httpx.Response(
                200,
                json={
                    "comments": [
                        {"text": "hi", "createdBy": {"displayName": "M"}, "createdDate": "d"}
                    ]
                },
            )
        return httpx.Response(404)

    ado = AdoClient(settings(), httpx.MockTransport(handler))
    assert (await ado.list_iterations())[0]["name"] == "Sprint06"
    ids = await ado.iteration_work_item_ids("Projeto Demo\\Team-demo\\Sprint06")
    assert len(ids) == 250
    assert len(await ado.work_items(ids)) == 250
    people, off = await ado.capacity("a")
    assert people[0]["capacity_per_day"] == 6 and off == [{"start": "x", "end": "y"}]
    comments = await ado.comments([1, 2])
    assert comments[1][0]["author"] == "M"


async def test_errors_are_safe():
    ado = AdoClient(settings(), httpx.MockTransport(lambda _: httpx.Response(401, text="pat-leak")))
    with pytest.raises(AdoError) as error:
        await ado.list_iterations()
    assert "401" in str(error.value) and "pat-leak" not in str(error.value)


def test_missing_pat():
    with pytest.raises(AdoError, match="AZURE_DEVOPS_PAT"):
        AdoClient(settings(pat=""))
