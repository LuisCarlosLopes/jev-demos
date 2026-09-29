"""Monta a hierarquia da sprint e calcula os fatos numéricos. Nada aqui chama o Jev."""

import html
import re
from datetime import date, datetime

from .workdays import business_days

OPEN_STATES = {"New", "Active", "Review"}
DONE_STATES = {"Closed", "Resolved", "Done"}
OUT_STATES = {"Removed", "Dropped"}
STREAMS = ("Stream A", "Stream B", "Stream C", "Stream D")
DESCRIPTION_CHARS = 2500
COMMENT_CHARS = 1500

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t\r\f\v]+")
_NL = re.compile(r"\n{3,}")


def clean_text(value: str | None, limit: int) -> str:
    """Remove HTML, normaliza espaços e trunca. Texto do ADO é dado, não instrução."""
    if not value:
        return ""
    text = _TAG.sub(" ", value.replace("<br>", "\n").replace("</p>", "\n").replace("</li>", "\n"))
    text = html.unescape(text)
    text = _NL.sub("\n\n", _WS.sub(" ", text)).strip()
    if len(text) > limit:
        return text[:limit].rstrip() + " […truncado]"
    return text


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    base = value.rstrip("Z").split(".")[0]
    try:
        return datetime.strptime(base, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None


def parse_date(value: str | None) -> date | None:
    dt = parse_dt(value)
    return dt.date() if dt else None


def owner_name(value) -> str:
    if isinstance(value, dict):
        return value.get("displayName") or ""
    if isinstance(value, str):
        return value.split("<")[0].strip()
    return ""


def _hours(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _tags(value) -> list[str]:
    return [t.strip() for t in (value or "").split(";") if t.strip()]


def _days_off_in(ranges: list[dict], window: list[date]) -> set[date]:
    off = set()
    for r in ranges:
        start, end = parse_date(r.get("start")), parse_date(r.get("end"))
        if not start or not end:
            continue
        off |= {d for d in window if start <= d <= end}
    return off


def build_snapshot(
    iteration: dict,
    items: list[dict],
    people: list[dict],
    team_days_off: list[dict],
    today: date,
) -> dict:
    start = parse_date(iteration.get("start")) or today
    finish = parse_date(iteration.get("finish")) or today
    all_days = business_days(start, finish)
    elapsed = [d for d in all_days if d <= today]
    left = [d for d in all_days if d >= today]

    nodes: dict[int, dict] = {}
    for raw in items:
        f = raw.get("fields") or {}
        wid = int(f.get("System.Id") or raw.get("id"))
        state = f.get("System.State") or ""
        nodes[wid] = {
            "id": wid,
            "type": f.get("System.WorkItemType") or "",
            "title": f.get("System.Title") or "",
            "state": state,
            "owner": owner_name(f.get("System.AssignedTo")),
            "tags": _tags(f.get("System.Tags")),
            "parent": f.get("System.Parent"),
            "estimate_h": _hours(f.get("Microsoft.VSTS.Scheduling.OriginalEstimate")),
            "logged_h": _hours(f.get("Microsoft.VSTS.Scheduling.CompletedWork")),
            "remaining_h": 0.0
            if state in DONE_STATES | OUT_STATES
            else _hours(f.get("Microsoft.VSTS.Scheduling.RemainingWork")),
            "created": f.get("System.CreatedDate"),
            "changed": f.get("System.ChangedDate"),
            "activated": f.get("Microsoft.VSTS.Common.ActivatedDate"),
            "state_changed": f.get("Microsoft.VSTS.Common.StateChangeDate"),
            "description": clean_text(f.get("System.Description"), DESCRIPTION_CHARS),
            "acceptance": clean_text(
                f.get("Microsoft.VSTS.Common.AcceptanceCriteria"), DESCRIPTION_CHARS
            ),
            "children": [],
            "comments": [],
        }

    for node in nodes.values():
        parent = node["parent"]
        if parent in nodes:
            nodes[parent]["children"].append(node["id"])
    roots = [n["id"] for n in nodes.values() if n["parent"] not in nodes]

    def stream_of(node: dict) -> str:
        seen = set()
        current = node
        while current and current["id"] not in seen:
            seen.add(current["id"])
            for tag in current["tags"]:
                if tag in STREAMS:
                    return tag
            current = nodes.get(current["parent"])
        return ""

    for node in nodes.values():
        node["stream"] = stream_of(node)
        node["stream_inherited"] = bool(node["stream"]) and node["stream"] not in node["tags"]
        node["is_task"] = node["type"] == "Task"
        node["open"] = node["is_task"] and node["state"] in OPEN_STATES
        node["days_since_changed"] = _age(node["changed"], today)
        node["days_since_activated"] = (
            _age(node["activated"] or node["state_changed"], today)
            if node["state"] == "Active"
            else None
        )

    team_off = _days_off_in(team_days_off, left)
    capacity: dict[str, dict] = {}
    for person in people:
        off = _days_off_in(person.get("days_off", []), left) | team_off
        days = len(left) - len(off)
        capacity[person["name"]] = {
            "name": person["name"],
            "capacity_per_day": person["capacity_per_day"],
            "days_off_in_window": len(off),
            "remaining_capacity_h": round(max(days, 0) * person["capacity_per_day"], 2),
            "remaining_h": 0.0,
            "open_tasks": 0,
        }

    open_tasks = [n for n in nodes.values() if n["open"]]
    unassigned_h = 0.0
    for task in open_tasks:
        person = capacity.get(task["owner"])
        if person is None:
            if task["owner"]:
                capacity[task["owner"]] = person = {
                    "name": task["owner"],
                    "capacity_per_day": 0.0,
                    "days_off_in_window": 0,
                    "remaining_capacity_h": 0.0,
                    "remaining_h": 0.0,
                    "open_tasks": 0,
                    "outside_team": True,
                }
            else:
                unassigned_h += task["remaining_h"]
                continue
        person["remaining_h"] = round(person["remaining_h"] + task["remaining_h"], 2)
        person["open_tasks"] += 1
    for person in capacity.values():
        cap = person["remaining_capacity_h"]
        person["load_ratio"] = round(person["remaining_h"] / cap, 2) if cap else None

    tasks_in_scope = [n for n in nodes.values() if n["is_task"] and n["state"] not in OUT_STATES]
    totals = {
        "scope_h": round(sum(t["estimate_h"] for t in tasks_in_scope), 2),
        "closed_h": round(
            sum(t["estimate_h"] for t in tasks_in_scope if t["state"] in DONE_STATES), 2
        ),
        "remaining_h": round(sum(t["remaining_h"] for t in open_tasks), 2),
        "logged_h": round(sum(t["logged_h"] for t in tasks_in_scope), 2),
        "capacity_h": round(
            sum(p["remaining_capacity_h"] for p in capacity.values()), 2
        ),
        "unassigned_h": round(unassigned_h, 2),
        "open_tasks": len(open_tasks),
        "tasks": len(tasks_in_scope),
        "items": len(nodes),
    }
    cap = totals["capacity_h"]
    totals["load_ratio"] = round(totals["remaining_h"] / cap, 2) if cap else None

    return {
        "sprint": {
            "id": iteration.get("id"),
            "name": iteration.get("name"),
            "path": iteration.get("path"),
            "start": start.isoformat(),
            "finish": finish.isoformat(),
            "today": today.isoformat(),
            "business_days": len(all_days),
            "days_elapsed": len(elapsed),
            "days_left": len(left),
        },
        "totals": totals,
        "people": sorted(capacity.values(), key=lambda p: -(p["remaining_h"])),
        "roots": roots,
        "nodes": nodes,
    }


def _age(value: str | None, today: date) -> int | None:
    d = parse_date(value)
    return (today - d).days if d else None


def attach_comments(snapshot: dict, comments: dict[int, list[dict]]) -> None:
    for wid, entries in comments.items():
        node = snapshot["nodes"].get(wid)
        if node is None:
            continue
        node["comments"] = [
            {
                "author": c.get("author") or "?",
                "date": (c.get("date") or "")[:10],
                "text": clean_text(c.get("text"), COMMENT_CHARS),
            }
            for c in entries
            if clean_text(c.get("text"), 50)
        ]


def rollup(snapshot: dict, results: dict[int, dict]) -> dict[int, dict]:
    """Probabilidade ponderada pelas horas restantes, subindo de Task para US e Feature."""
    nodes = snapshot["nodes"]
    memo: dict[int, dict] = {}

    def visit(wid: int) -> dict | None:
        if wid in memo:
            return memo[wid]
        node = nodes[wid]
        if node["is_task"]:
            r = results.get(wid)
            if r is None:
                return None
            weight = max(node["remaining_h"], 1.0)
            out = {
                "p": r["will_close"],
                "weight": weight,
                "tasks": 1,
                "at_risk": r["will_close"] < 0.5,
            }
        else:
            parts = [v for c in node["children"] if (v := visit(c))]
            if not parts:
                return None
            weight = sum(p["weight"] for p in parts)
            out = {
                "p": round(sum(p["p"] * p["weight"] for p in parts) / weight, 3),
                "weight": weight,
                "tasks": sum(p["tasks"] for p in parts),
                "at_risk": sum(1 for p in parts if p["at_risk"]),
            }
        memo[wid] = out
        return out

    for wid in nodes:
        visit(wid)
    return {wid: v for wid, v in memo.items() if not nodes[wid]["is_task"]}
