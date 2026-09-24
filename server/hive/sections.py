"""Contract sections: the named work streams of a contract (e.g. Acme -> Ingest, Archive Export), used as time tags.

Section fields (all optional except name):
  budget_hours  hours the SOW allows for this line
  match         external tag names (e.g. Toggl tags) that map to this section
  bill_as       invoice this section's hours under another section's line (time detail stays on the timesheet)
  overflow_as   hours beyond budget_hours (cumulative across invoices) go on a separate line with this name
"""
from __future__ import annotations

from typing import Any


def contract_sections(meta: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for s in meta.get("sections") or []:
        if isinstance(s, str):
            s = {"name": s}
        if not isinstance(s, dict) or not s.get("name"):
            continue
        match = s.get("match") or []
        if isinstance(match, str):
            match = [match]
        out.append({"name": str(s["name"]), "budget_hours": s.get("budget_hours"), "match": [str(m) for m in match],
                    "bill_as": str(s["bill_as"]) if s.get("bill_as") else None,
                    "overflow_as": str(s["overflow_as"]) if s.get("overflow_as") else None})
    return out


def section_for_tag(sections: list[dict[str, Any]], tag: str) -> str | None:
    t = tag.strip().lower()
    for s in sections:
        if t == s["name"].lower() or t in (m.lower() for m in s["match"]):
            return s["name"]
    return None


def billing_line(sections: list[dict[str, Any]], section: str | None) -> str:
    """Which invoice line a section's hours roll into (follows bill_as one hop)."""
    name = section or "Consulting services"
    for s in sections:
        if s["name"] == name and s.get("bill_as"):
            return s["bill_as"]
    return name
