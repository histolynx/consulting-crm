"""Draft invoices from confirmed, billable, un-invoiced time (or completed fixed-fee milestones)."""
from __future__ import annotations

import datetime as dt
import re
from typing import Any

from .sections import contract_sections
from .graph import Graph
from .timetrack import TimeTracker, _link_target
from .vault import Vault

STATUSES = ("draft", "sent", "paid", "void")


def profile(graph: Graph) -> dict[str, Any]:
    for n in graph.notes.values():
        if n.type == "profile":
            return n.meta
    return {}


def _money(x: float) -> float:
    return round(x + 1e-9, 2)


def next_number(graph: Graph, prefix: str, year: int) -> str:
    pat = re.compile(rf"^{re.escape(prefix)}-{year}-(\d+)$")
    nums = [int(m.group(1)) for n in graph.notes.values() if n.type == "invoice"
            for m in [pat.match(str(n.meta.get("number", "")))] if m]
    return f"{prefix}-{year}-{(max(nums) + 1) if nums else 1:03d}"


def generate(vault: Vault, graph: Graph, tracker: TimeTracker, contract_path: str,
             start: str, end: str, issued: dt.date | None = None) -> dict[str, Any]:
    c = graph.notes.get(contract_path)
    if not c or c.type != "contract":
        raise ValueError(f"not a contract: {contract_path}")
    issued = issued or dt.date.today()
    s, f = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    rate = float(c.meta.get("rate") or 0)
    unit = str(c.meta.get("rate_unit", "hour"))
    currency = str(c.meta.get("currency", "USD"))
    lines: list[dict[str, Any]] = []
    timesheet: list[dict[str, Any]] = []
    entry_ids: list[str] = []

    if unit in ("hour", "day"):
        if rate <= 0:
            raise ValueError(f"contract {c.title} has no `rate` set")
        hpd = float(c.meta.get("hours_per_day", 8))
        section_hours: dict[str, float] = {}
        for e in sorted(tracker.all_entries(), key=lambda x: (x["date"], str(x.get("start") or ""))):
            if e.get("status") == "suggested" or not e.get("billable", True) or e.get("invoice"):
                continue
            if not e.get("contract_name") or graph.resolve(e["contract_name"]) != contract_path:
                continue
            d = dt.date.fromisoformat(e["date"])
            if not (s <= d <= f):
                continue
            hours = e["minutes"] / 60
            sec = e.get("section") or "Consulting services"
            section_hours[sec] = section_hours.get(sec, 0.0) + hours
            timesheet.append({"date": e["date"], "section": sec, "description": e.get("description") or "",
                              "hours": round(hours, 2)})
            entry_ids.append(e["id"])
        # one invoice line per contract section (SOW-style); the dated timesheet carries the detail
        order = [x["name"] for x in contract_sections(c.meta)]
        for sec in sorted(section_hours, key=lambda x: (order.index(x) if x in order else 99, x)):
            hrs = section_hours[sec]
            qty = round(hrs if unit == "hour" else hrs / hpd, 2)
            lines.append({"date": f"{start} → {end}", "description": sec, "qty": qty, "unit": unit,
                          "rate": rate, "amount": _money(qty * rate)})
    elif unit == "fixed":
        for m in c.meta.get("milestones") or []:
            if m.get("status") == "complete" and not m.get("invoice"):
                lines.append({"date": str(m.get("due", issued)), "description": m.get("name", "Milestone"),
                              "qty": 1, "unit": "milestone", "rate": float(m["amount"]), "amount": _money(float(m["amount"]))})
    else:
        raise ValueError(f"unknown rate_unit {unit!r} (use hour, day or fixed)")

    if not lines:
        raise ValueError("nothing billable in that period (only confirmed, billable, un-invoiced time counts)")

    prof = profile(graph)
    prefix = str(prof.get("invoice_prefix", "INV"))
    number = next_number(graph, prefix, issued.year)
    terms = int(c.meta.get("payment_terms_days", prof.get("default_terms_days", 30)))
    total = _money(sum(x["amount"] for x in lines))
    raw_client = _link_target(c.meta.get("client")) or ""
    client_path = graph.resolve(raw_client) if raw_client else None
    client_title = graph.notes[client_path].title if client_path in graph.notes else raw_client
    meta = {
        "type": "invoice", "number": number, "status": "draft",
        "client": f"[[{client_title}]]" if client_title else None, "contract": f"[[{c.title}]]",
        "issued": issued.isoformat(), "due": (issued + dt.timedelta(days=terms)).isoformat(),
        "period_start": start, "period_end": end, "currency": currency, "total": total,
        "lines": lines, "timesheet": timesheet or None, "entries": entry_ids, "tags": ["invoice"],
    }
    meta = {k: v for k, v in meta.items() if v is not None}
    body = render_body(meta)
    rel = f"invoices/{number}.md"
    vault.write(rel, meta, body, actor="ui", action="invoice-generate")

    for eid in entry_ids:
        tracker.update(eid, {"invoice": f"[[{number}]]"}, actor="invoice")
    if unit == "fixed":
        ms = c.meta.get("milestones") or []
        for m in ms:
            if m.get("status") == "complete" and not m.get("invoice"):
                m["invoice"] = f"[[{number}]]"
        cm = dict(c.meta)
        cm["milestones"] = ms
        vault.write(contract_path, cm, c.body, actor="invoice", action="milestones-invoiced")
    return {"path": rel, **meta}


def render_body(meta: dict[str, Any]) -> str:
    cur = meta.get("currency", "USD")
    out = [f"# Invoice {meta['number']}", "",
           f"Issued {meta['issued']} · Due {meta['due']} · Period {meta['period_start']} → {meta['period_end']}", "",
           "| Date | Description | Qty | Rate | Amount |", "|---|---|---:|---:|---:|"]
    for x in meta["lines"]:
        out.append(f"| {x['date']} | {str(x['description']).replace('|', '/')} | {x['qty']} {x['unit']} | {x['rate']:,.2f} | {x['amount']:,.2f} |")
    out += ["", f"**Total: {cur} {meta['total']:,.2f}**", ""]
    if meta.get("timesheet"):
        out += ["## Timesheet", "", "| Date | Section | Description | Hours |", "|---|---|---|---:|"]
        for t in meta["timesheet"]:
            out.append(f"| {t['date']} | {t['section']} | {str(t['description']).replace('|', '/')} | {t['hours']:.2f} |")
        out += ["", f"**Total hours: {sum(t['hours'] for t in meta['timesheet']):.2f}**", ""]
    return "\n".join(out)


def set_status(vault: Vault, graph: Graph, path: str, status: str, tracker: TimeTracker | None = None) -> dict[str, Any]:
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    n = graph.notes.get(path)
    if not n or n.type != "invoice":
        raise ValueError(f"not an invoice: {path}")
    meta = dict(n.meta)
    meta["status"] = status
    if status == "sent":
        meta.setdefault("sent", dt.date.today().isoformat())
    if status == "paid":
        meta["paid"] = dt.date.today().isoformat()
    if status == "void" and tracker is not None:
        # release the time so it can be billed again
        for eid in meta.get("entries") or []:
            try:
                tracker.update(eid, {"invoice": None}, actor="invoice-void")
            except KeyError:
                pass  # entry was deleted since; nothing to release
    vault.write(path, meta, n.body, actor="ui", action=f"invoice-{status}")
    return {"path": path, **meta}


def summary(graph: Graph, today: dt.date | None = None) -> dict[str, Any]:
    today = today or dt.date.today()
    outstanding = overdue = paid_ytd = 0.0
    items = []
    for p, n in graph.notes.items():
        if n.type != "invoice":
            continue
        total = float(n.meta.get("total") or 0)
        st = n.meta.get("status", "draft")
        due = str(n.meta.get("due", ""))
        is_overdue = st == "sent" and due and dt.date.fromisoformat(due[:10]) < today
        if st == "sent":
            outstanding += total
            if is_overdue:
                overdue += total
        if st == "paid" and str(n.meta.get("paid", ""))[:4] == str(today.year):
            paid_ytd += total
        items.append({"path": p, **n.meta, "overdue": bool(is_overdue)})
    items.sort(key=lambda x: str(x.get("issued", "")), reverse=True)
    return {"outstanding": _money(outstanding), "overdue": _money(overdue), "paid_ytd": _money(paid_ytd), "items": items}
