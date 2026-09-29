"""Orquestra ADO + Jev. Usado pela CLI e pela API HTTP."""

import asyncio
from dataclasses import asdict

from .ado import AdoClient, AdoError, Story
from .config import Settings, load_policy
from .jev import JevClient, JevError, build_questions
from .normalize import build_state
from .scoring import interpret


def story_summary(story: Story, ado: AdoClient, policy: dict, tasks: dict | None = None) -> dict:
    _, info = build_state(story, policy)
    tasks = tasks or {"tasks": 0, "original": 0.0, "completed": 0.0}
    return {
        "tasks": tasks["tasks"],
        "tasks_estimate_hours": tasks["original"],
        "tasks_completed_hours": tasks["completed"],
        "id": story.id,
        "title": story.title,
        "short_title": info["short_title"],
        "stream": info["stream"],
        "state": story.state,
        "assigned_to": story.assigned_to,
        "size": story.size,
        "url": ado.item_url(story.id),
        "description_chars": info["description_chars"],
        "acceptance_chars": info["acceptance_chars"],
        "has_acceptance": info["has_acceptance"],
        "estimated_tokens": info["estimated_tokens"],
    }


async def size_story(story: Story, jev: JevClient, policy: dict, questions: dict) -> dict:
    state, info = build_state(story, policy)
    try:
        data = await jev.evaluate(state, questions)
        result = interpret(data["answers"], data.get("usage", {}), data["_elapsed_ms"], policy)
        result["model"] = data.get("model")
        result["error"] = None
    except JevError as exc:
        result = {"error": str(exc)}
    result["id"] = story.id
    result["input"] = info
    result["state_sent"] = state["story"]
    return result


async def size_stories(stories: list[Story], settings: Settings, policy: dict) -> list[dict]:
    questions = build_questions(policy)
    jev = JevClient(settings)
    try:
        return await asyncio.gather(*(size_story(s, jev, policy, questions) for s in stories))
    finally:
        await jev.aclose()


async def load_sprint_stories(
    settings: Settings, iteration_path: str, only_unsized: bool = True
) -> list[Story]:
    ado = AdoClient(settings)
    try:
        ids = await ado.story_ids(iteration_path, only_unsized=only_unsized)
        return await ado.stories(ids) if ids else []
    finally:
        await ado.aclose()


__all__ = [
    "AdoClient",
    "AdoError",
    "Story",
    "asdict",
    "load_policy",
    "load_sprint_stories",
    "size_stories",
    "story_summary",
]
