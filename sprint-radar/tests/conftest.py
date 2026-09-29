from datetime import date

import pytest

from sprint_radar import model

ITERATION = {
    "id": "it-6",
    "name": "Sprint06",
    "path": "Projeto Demo\\Speed\\Sprint06",
    "start": "2026-09-21T00:00:00Z",
    "finish": "2026-10-02T00:00:00Z",
}


def wi(wid, wtype, title, state, owner=None, parent=None, tags="", est=0, done=0, rem=0, **extra):
    fields = {
        "System.Id": wid,
        "System.WorkItemType": wtype,
        "System.Title": title,
        "System.State": state,
        "System.Tags": tags,
        "System.Parent": parent,
        "System.ChangedDate": "2026-09-28T10:00:00.5Z",
        "Microsoft.VSTS.Scheduling.OriginalEstimate": est,
        "Microsoft.VSTS.Scheduling.CompletedWork": done,
        "Microsoft.VSTS.Scheduling.RemainingWork": rem,
    }
    if owner:
        fields["System.AssignedTo"] = {"displayName": owner, "uniqueName": f"{owner}@x"}
    fields.update(extra)
    return {"id": wid, "fields": fields}


@pytest.fixture
def items():
    return [
        wi(1, "Feature", "S6 - Stream B", "Active", "Ana", parent=999, tags="Stream B"),
        wi(10, "User Story", "CTX-2", "New", "Ana", parent=1),
        wi(
            100,
            "Task",
            "CTX-2.2 catálogo",
            "Active",
            "Ana",
            parent=10,
            est=6,
            done=15.65,
            rem=6,
            **{
                "System.Description": "<p>Revisar &amp; documentar</p>",
                "Microsoft.VSTS.Common.ActivatedDate": "2026-09-28T11:45:00Z",
            },
        ),
        wi(101, "Task", "CTX-2.3 instalação", "New", "Ana", parent=10, est=4, rem=4),
        wi(102, "Task", "CTX-2.7 node", "Closed", "Ana", parent=10, est=2, done=2),
        wi(103, "Task", "CTX-2.4 removida", "Removed", "Ana", parent=10, est=1, rem=1),
        wi(11, "User Story", "PW-1", "Review", "Luis", parent=1, tags="Stream A"),
        wi(110, "Task", "PW-1.2 orquestrador", "Active", "Luis", parent=11, est=10, rem=10),
        wi(111, "Task", "sem dono", "New", None, parent=11, est=3, rem=3),
    ]


@pytest.fixture
def people():
    return [
        {"name": "Ana", "email": "ana@x", "capacity_per_day": 6, "days_off": []},
        {
            "name": "Luis",
            "email": "luis@x",
            "capacity_per_day": 6,
            "days_off": [{"start": "2026-09-28T00:00:00Z", "end": "2026-10-02T00:00:00Z"}],
        },
    ]


@pytest.fixture
def snapshot(items, people):
    return model.build_snapshot(ITERATION, items, people, [], date(2026, 9, 29))


@pytest.fixture
def jev_response():
    probs = {
        "on_track": 0.05,
        "owner_overloaded": 0.1,
        "blocked_external": 0.05,
        "dependency_open": 0.1,
        "not_started_large": 0.05,
        "scope_unclear": 0.05,
        "done_not_closed": 0.6,
    }
    return {
        "model": "jev-1.13.0",
        "answers": {
            "will_close": {"type": "noul", "noul": 0.81},
            "risk_driver": {
                "type": "choice",
                "choice": "done_not_closed",
                "confidence": 0.7,
                "probabilities": probs,
            },
            "blocked_external": {"type": "noul", "noul": 0.1},
            "done_not_closed": {"type": "noul", "noul": 0.9},
        },
        "usage": {"input_tokens": 2100, "output_tokens": 40},
    }
