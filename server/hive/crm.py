"""CRM views derived from the graph: contacts, clients, contracts/pipeline, tasks, dashboard."""
from __future__ import annotations

import datetime as dt
from typing import Any

from . import invoices
from .graph import Graph
from .sections import contract_sections, section_for_tag  # noqa: F401 (re-exported)
from .timetrack import TimeTracker, _link_target

PIPELINE = ["lead", "proposal", "negotiating", "active", "paused", "complete", "lost"]
DEFAULT_PROBABILITY = {"lead": 0.1, "proposal": 0.3, "negotiating": 0.6}
COLD_AFTER_DAYS = 21


def _date(v: Any) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def _title(graph: Graph, path: str | None) -> str | None:
    return graph.nodes[path]["title"] if path and path in graph.nodes else None


def last_touch(graph: Graph, path: str, today: dt.date | None = None) -> dt.date | None:
    """Latest *past* dated email/meeting linked to the node (or explicit `last_contact`).
    Upcoming meetings don't count: a scheduled call isn't contact yet."""
    today = today or dt.date.today()
    dates = [_date(graph.notes[path].meta.get("last_contact"))] if path in graph.notes else []
    for nb in graph.adj.get(path, ()):
        n = graph.notes.get(nb)
        if n and n.type in ("email", "meeting"):
            dates.append(_date(n.meta.get("date")))
    dates = [d for d in dates if d and d <= today]
    return max(dates) if dates else None


def contacts(graph: Graph, today: dt.date | None = None) -> list[dict[str, Any]]:
    today = today or dt.date.today()
    out = []
    for p, n in graph.notes.items():
        if n.type != "contact":
            continue
        org = graph.resolve(_link_target(n.meta.get("org")) or "") if n.meta.get("org") else None
        lt = last_touch(graph, p, today)
        out.append({
            "path": p, "name": n.meta.get("name") or n.title, "org": _title(graph, org) or _link_target(n.meta.get("org")),
            "org_path": org, "role": n.meta.get("role"), "email": n.meta.get("email"), "phone": n.meta.get("phone"),
            "tags": n.tags, "last_contact": lt.isoformat() if lt else None,
            "days_since": (today - lt).days if lt else None, "demo": bool(n.meta.get("demo")),
            "relationship": n.meta.get("relationship"), "degree": len(graph.adj.get(p, ())),
        })
    out.sort(key=lambda c: (c["days_since"] is None, c["days_since"] or 0))
    return out


def clients(graph: Graph) -> list[dict[str, Any]]:
    out = []
    for p, n in graph.notes.items():
        if n.type != "client":
            continue
        nbs = graph.adj.get(p, set())
        out.append({"path": p, "name": n.title, "industry": n.meta.get("industry"), "website": n.meta.get("website"),
                    "status": n.meta.get("status"), "contacts": sum(1 for v in nbs if graph.nodes[v]["type"] == "contact"),
                    "contracts": sum(1 for v in nbs if graph.nodes[v]["type"] == "contract"), "demo": bool(n.meta.get("demo"))})
    return sorted(out, key=lambda c: c["name"].lower())


def _section_rollup(secs: list[dict[str, Any]], hours_by: dict[str, float]) -> list[dict[str, Any]]:
    """Per-section hours plus `billed_hours`: own hours + sections that bill_as this one. Burn uses billed hours."""
    out = []
    for s in secs:
        own = hours_by.get(s["name"], 0.0)
        feeders = [x["name"] for x in secs if x.get("bill_as") == s["name"]]
        billed = own + sum(hours_by.get(n, 0.0) for n in feeders)
        budget = float(s["budget_hours"]) if s.get("budget_hours") else None
        out.append({**s, "hours": round(own, 2), "billed_hours": round(billed, 2), "includes": feeders,
                    "burn": round(billed / budget, 3) if budget else None,
                    "over_hours": round(max(0.0, billed - budget), 2) if budget else 0.0})
    return out


def contracts(graph: Graph, tracker: TimeTracker, today: dt.date | None = None) -> list[dict[str, Any]]:
    today = today or dt.date.today()
    tsums = tracker.summary(graph, today)
    tsum, tsec = tsums["by_contract"], tsums["by_section"]
    inv = invoices.summary(graph, today)["items"]
    out = []
    for p, n in graph.notes.items():
        if n.type != "contract":
            continue
        m = n.meta
        status = str(m.get("status", "active"))
        client = graph.resolve(_link_target(m.get("client")) or "") if m.get("client") else None
        hours = tsum.get(p, {})
        budget = float(m.get("budget_hours") or 0)
        end = _date(m.get("end"))
        value = float(m.get("value") or 0)
        prob = float(m.get("probability") if m.get("probability") is not None else DEFAULT_PROBABILITY.get(status, 1.0 if status == "active" else 0))
        invoiced = sum(float(i.get("total") or 0) for i in inv if graph.resolve(_link_target(i.get("contract")) or "") == p and i.get("status") != "void")
        out.append({
            "path": p, "name": n.title, "status": status, "client": _title(graph, client) or _link_target(m.get("client")),
            "client_path": client, "value": value, "probability": prob, "weighted": round(value * prob, 2),
            "rate": m.get("rate"), "rate_unit": m.get("rate_unit", "hour"), "currency": m.get("currency", "USD"),
            "start": m.get("start"), "end": m.get("end"), "days_left": (end - today).days if end else None,
            "budget_hours": budget or None, "hours_total": hours.get("total", 0.0), "hours_week": hours.get("week", 0.0),
            "unbilled_hours": hours.get("unbilled", 0.0),
            "burn": round(hours.get("total", 0.0) / budget, 3) if budget else None,
            "invoiced": round(invoiced, 2), "next_step": m.get("next_step"), "expected_close": m.get("expected_close"),
            "tags": n.tags, "demo": bool(m.get("demo")),
            "sections": _section_rollup(contract_sections(m), tsec.get(p, {})),
            "unsectioned_hours": round(tsec.get(p, {}).get("(unsectioned)", 0.0), 2),
            "toggl_projects": m.get("toggl_projects") or [],
        })
    out.sort(key=lambda c: (PIPELINE.index(c["status"]) if c["status"] in PIPELINE else 99, c["name"].lower()))
    return out


def tasks(graph: Graph, include_done: bool = False) -> list[dict[str, Any]]:
    out = []
    for p, n in graph.notes.items():
        for t in n.tasks:
            if t.done and not include_done:
                continue
            out.append({"path": p, "note": n.title, "text": t.text, "done": t.done, "due": t.due, "line": t.line,
                        "demo": bool(n.meta.get("demo"))})
    out.sort(key=lambda t: (t["due"] is None, t["due"] or ""))
    return out


def dashboard(graph: Graph, tracker: TimeTracker, today: dt.date | None = None) -> dict[str, Any]:
    today = today or dt.date.today()
    cs = contracts(graph, tracker, today)
    ppl = contacts(graph, today)
    ts = tasks(graph)
    inv = invoices.summary(graph, today)
    tsum = tracker.summary(graph, today)
    active = [c for c in cs if c["status"] == "active"]
    pipeline = [c for c in cs if c["status"] in DEFAULT_PROBABILITY]
    unbilled_value = 0.0
    for c in active:
        if c["rate"] and c["rate_unit"] == "hour":
            unbilled_value += c["unbilled_hours"] * float(c["rate"])
        elif c["rate"] and c["rate_unit"] == "day":
            unbilled_value += c["unbilled_hours"] / 8 * float(c["rate"])
    horizon = (today + dt.timedelta(days=7)).isoformat()
    return {
        "today": today.isoformat(),
        "kpis": {
            "active_contracts": len(active),
            "active_value": round(sum(c["value"] for c in active), 2),
            "pipeline_count": len(pipeline),
            "pipeline_weighted": round(sum(c["weighted"] for c in pipeline), 2),
            "hours_week": tsum["week_total"], "hours_month": tsum["month_total"],
            "unbilled_value": round(unbilled_value, 2),
            "outstanding": inv["outstanding"], "overdue": inv["overdue"], "paid_ytd": inv["paid_ytd"],
        },
        "tasks_due": [t for t in ts if t["due"] and t["due"] <= horizon][:15],
        "tasks_open": len(ts),
        "cold_contacts": [c for c in ppl if c["days_since"] is not None and c["days_since"] >= COLD_AFTER_DAYS][:8],
        "ending_soon": [c for c in active if c["days_left"] is not None and c["days_left"] <= 30],
        "over_budget": [c for c in active if c["burn"] and c["burn"] >= 0.8],
        "suggested_time": [e for e in tracker.all_entries() if e.get("status") == "suggested"],
        "graph": graph.stats(),
    }
