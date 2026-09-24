"""Contract sections: the named work streams of a contract (e.g. Acme -> Ingest, Archive Export), used as time tags."""
from __future__ import annotations

from typing import Any


def contract_sections(meta: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalise a contract's `sections:` (strings or {name, budget_hours, match}) into dicts.
    `match` lists external tag names (e.g. Toggl tags) that map to the section."""
    out = []
    for s in meta.get("sections") or []:
        if isinstance(s, str):
            s = {"name": s}
        if not isinstance(s, dict) or not s.get("name"):
            continue
        match = s.get("match") or []
        if isinstance(match, str):
            match = [match]
        out.append({"name": str(s["name"]), "budget_hours": s.get("budget_hours"), "match": [str(m) for m in match]})
    return out


def section_for_tag(sections: list[dict[str, Any]], tag: str) -> str | None:
    t = tag.strip().lower()
    for s in sections:
        if t == s["name"].lower() or t in (m.lower() for m in s["match"]):
            return s["name"]
    return None
