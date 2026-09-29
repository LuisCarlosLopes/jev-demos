import html
import re
from html.parser import HTMLParser

from .ado import Story

_TITLE_RE = re.compile(
    r"^\s*\[(?P<sprint>[^\]-]+?)\s*-\s*(?P<stream>Stream\s+\w+)\]\s*-?\s*(?P<rest>.*)$"
)


class _TextExtractor(HTMLParser):
    """Converte o HTML do ADO em texto, preservando quebras e marcadores de lista."""

    BLOCK = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "tr", "table", "pre"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "li":
            self.parts.append("\n- ")
        elif tag in self.BLOCK:
            self.parts.append("\n")
        elif tag == "td":
            self.parts.append(" | ")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def html_to_text(raw: str) -> str:
    if not raw:
        return ""
    parser = _TextExtractor()
    parser.feed(raw)
    text = html.unescape("".join(parser.parts))
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_title(title: str) -> dict:
    m = _TITLE_RE.match(title)
    if not m:
        return {"stream": None, "short_title": title.strip()}
    return {"stream": m.group("stream"), "short_title": m.group("rest").strip()}


def estimate_tokens(text: str) -> int:
    # Português tokeniza pior que inglês; 3,5 chars/token é conservador.
    return int(len(text) / 3.5) + 1


def build_state(story: Story, policy: dict) -> tuple[dict, dict]:
    """Monta o `state` enviado ao Jev e metadados sobre truncamento."""
    meta = parse_title(story.title)
    description = html_to_text(story.description_html)
    acceptance = html_to_text(story.acceptance_html)
    stream = meta["stream"] or next((t for t in story.tags if t.lower().startswith("stream")), None)

    budget = policy["max_state_chars"]
    fixed = len(story.title) + len(acceptance) + 400
    truncated = False
    if fixed + len(description) > budget:
        keep = max(policy["description_min_chars"], budget - fixed)
        if len(description) > keep:
            description = description[:keep] + "\n[... descrição truncada ...]"
            truncated = True

    state = {
        "story": {
            "id": story.id,
            "title": story.title,
            "stream": stream,
            "state": story.state,
            "description": description or "(sem descrição)",
            "acceptance_criteria": acceptance or "(sem critérios de aceite)",
        }
    }
    info = {
        "stream": stream,
        "short_title": meta["short_title"],
        "description_chars": len(description),
        "acceptance_chars": len(acceptance),
        "has_acceptance": bool(acceptance),
        "truncated": truncated,
        "estimated_tokens": estimate_tokens(description + acceptance + story.title),
    }
    return state, info
