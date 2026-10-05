"""Draft invoices from confirmed, billable, un-invoiced time (or completed fixed-fee milestones)."""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Any

from .sections import billing_line, contract_sections
from .graph import Graph
from .timetrack import TimeTracker, _link_target
from .vault import Vault, slugify

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
        secs = contract_sections(c.meta)
        by_name = {x["name"]: x for x in secs}
        line_hours: dict[str, float] = {}
        prior: dict[str, float] = {}  # hours already on earlier invoices, per line (for overflow budgets)
        for e in sorted(tracker.all_entries(), key=lambda x: (x["date"], str(x.get("start") or ""))):
            if e.get("status") == "suggested" or not e.get("billable", True):
                continue
            if not e.get("contract_name") or graph.resolve(e["contract_name"]) != contract_path:
                continue
            hours = e["minutes"] / 60
            line = billing_line(secs, e.get("section"))
            if e.get("invoice"):
                prior[line] = prior.get(line, 0.0) + hours
                continue
            d = dt.date.fromisoformat(e["date"])
            if not (s <= d <= f):
                continue
            line_hours[line] = line_hours.get(line, 0.0) + hours
            timesheet.append({"date": e["date"], "section": e.get("section") or "Consulting services",
                              "description": e.get("description") or "", "hours": round(hours, 2)})
            entry_ids.append(e["id"])

        def add_line(desc: str, hrs: float) -> None:
            qty = round(hrs if unit == "hour" else hrs / hpd, 2)
            if qty > 0:
                lines.append({"date": f"{start} → {end}", "description": desc, "qty": qty, "unit": unit,
                              "rate": rate, "amount": _money(qty * rate)})

        # one invoice line per billing line (SOW-style); bill_as rolls sections together, overflow_as splits
        # hours past the budget onto their own line; the dated timesheet keeps the per-section detail
        order = [x["name"] for x in secs]
        for line in sorted(line_hours, key=lambda x: (order.index(x) if x in order else 99, x)):
            hrs = line_hours[line]
            sec = by_name.get(line, {})
            budget, overflow = sec.get("budget_hours"), sec.get("overflow_as")
            if budget and overflow:
                remaining = max(0.0, float(budget) - prior.get(line, 0.0))
                inside = min(hrs, remaining)
                add_line(line, inside)
                add_line(overflow, hrs - inside)
            else:
                add_line(line, hrs)
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


def record(vault: Vault, graph: Graph, tracker: TimeTracker, contract_path: str, number: str, issued: str,
           lines: list[dict[str, Any]], entry_ids: list[str], due: str | None = None, status: str = "sent",
           sent: str | None = None, sent_to: str | None = None, unbilled: list[dict[str, Any]] | None = None,
           notes: str | None = None) -> dict[str, Any]:
    """Record an invoice that was produced/sent outside HIVE's generator, exactly as sent.

    `lines` are the invoice's own lines (description, qty, rate[, amount]); `entry_ids` are the time entries
    it covers, which get stamped so they're never billed twice. `unbilled` notes hours deliberately left off
    (e.g. a capped overrun). Line hours vs entry hours are reconciled and stored, never silently forced equal."""
    c = graph.notes.get(contract_path)
    if not c or c.type != "contract":
        raise ValueError(f"not a contract: {contract_path}")
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    number = number.strip()
    if not number:
        raise ValueError("invoice number required")
    if any(n.type == "invoice" and str(n.meta.get("number")) == number for n in graph.notes.values()):
        raise ValueError(f"invoice {number} already exists in HIVE")
    issued_d = dt.date.fromisoformat(issued)
    all_e = {e["id"]: e for e in tracker.all_entries()}
    covered = []
    if not isinstance(entry_ids, list) or not all(isinstance(x, str) for x in entry_ids):
        raise ValueError("entry_ids must be a list of time-entry id strings")
    if not isinstance(lines, list) or not all(isinstance(x, dict) for x in lines):
        raise ValueError("lines must be a list of {description, qty, rate} objects")
    for eid in entry_ids:
        e = all_e.get(eid)
        if not e:
            raise ValueError(f"unknown time entry {eid}")
        if not e.get("contract_name") or graph.resolve(e["contract_name"]) != contract_path:
            raise ValueError(f"entry {eid} belongs to a different contract")
        if e.get("invoice"):
            raise ValueError(f"entry {eid} ({e['date']}) is already on {e['invoice']}")
        if e.get("status") == "suggested":
            raise ValueError(f"entry {eid} is an unconfirmed suggestion")
        covered.append(e)
    clean_lines = []
    for x in lines:
        qty, rate = float(x["qty"]), float(x["rate"])
        clean_lines.append({"date": x.get("date") or "", "description": str(x["description"]), "qty": round(qty, 2),
                            "unit": x.get("unit", "hour"), "rate": rate,
                            "amount": _money(float(x["amount"]) if x.get("amount") is not None else qty * rate)})
    if not clean_lines:
        raise ValueError("an invoice needs at least one line")
    covered.sort(key=lambda e: (e["date"], str(e.get("start") or "")))
    timesheet = [{"date": e["date"], "section": e.get("section") or "Consulting services",
                  "description": e.get("description") or "", "hours": round(e["minutes"] / 60, 2)} for e in covered]
    entry_hours = round(sum(e["minutes"] for e in covered) / 60, 2)
    line_hours = round(sum(x["qty"] for x in clean_lines if x["unit"] == "hour"), 2)
    unbilled_h = round(sum(float(u.get("hours", 0)) for u in unbilled or []), 2)
    prof = profile(graph)
    terms = int(c.meta.get("payment_terms_days", prof.get("default_terms_days", 30)) or 30)
    raw_client = _link_target(c.meta.get("client")) or ""
    client_path = graph.resolve(raw_client) if raw_client else None
    client_title = graph.notes[client_path].title if client_path in graph.notes else raw_client
    meta = {
        "type": "invoice", "number": number, "status": status, "source": "recorded",
        "client": f"[[{client_title}]]" if client_title else None, "contract": f"[[{c.title}]]",
        "issued": issued_d.isoformat(), "due": due or (issued_d + dt.timedelta(days=terms)).isoformat(),
        "sent": (sent or issued_d.isoformat()) if status in ("sent", "paid") else None, "sent_to": sent_to,
        "period_start": timesheet[0]["date"] if timesheet else issued_d.isoformat(),
        "period_end": timesheet[-1]["date"] if timesheet else issued_d.isoformat(),
        "currency": str(c.meta.get("currency", "USD")), "total": _money(sum(x["amount"] for x in clean_lines)),
        "lines": clean_lines, "timesheet": timesheet or None, "entries": [e["id"] for e in covered],
        "reconciliation": {"line_hours": line_hours, "entry_hours": entry_hours, "unbilled_hours": unbilled_h,
                           "difference": round(entry_hours - line_hours - unbilled_h, 2)},
        "unbilled": unbilled or None, "notes": notes, "tags": ["invoice"],
    }
    meta = {k: v for k, v in meta.items() if v is not None}
    body = render_body(meta)
    if unbilled:
        body += "\n## Hours not billed on this invoice\n" + "\n".join(
            f"- {u.get('section', '?')}: {float(u.get('hours', 0)):.2f} h ({u.get('reason', '')})" for u in unbilled) + "\n"
    rel = f"invoices/{slugify(number)}.md"
    vault.write(rel, meta, body, actor="ui", action="invoice-record")
    for e in covered:
        tracker.update(e["id"], {"invoice": f"[[{slugify(number)}]]"}, actor="invoice")
    return {"path": rel, **meta}


def attach_document(vault: Vault, graph: Graph, path: str, filename: str, data: bytes) -> dict[str, Any]:
    """Store the invoice as sent (e.g. the PDF) under documents/<client>/invoices/ and link it from the note."""
    n = graph.notes.get(path)
    if not n or n.type != "invoice":
        raise ValueError(f"not an invoice: {path}")
    client = slugify(_link_target(n.meta.get("client")) or "Unassigned")
    safe = slugify(Path(filename).stem) + (Path(filename).suffix.lower() or ".pdf")
    rel = f"documents/{client}/invoices/{safe}"
    dest = vault.safe_path(rel)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    meta = dict(n.meta)
    meta["document"] = rel
    vault.write(path, meta, n.body, actor="ui", action="invoice-attach")
    return {"path": path, "document": rel}


def set_status(vault: Vault, graph: Graph, path: str, status: str, tracker: TimeTracker | None = None,
               date: str | None = None, reference: str | None = None) -> dict[str, Any]:
    """Change status. `date` records when it actually happened (sent/paid), defaulting to today."""
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    n = graph.notes.get(path)
    if not n or n.type != "invoice":
        raise ValueError(f"not an invoice: {path}")
    when = dt.date.fromisoformat(date).isoformat() if date else dt.date.today().isoformat()
    meta = dict(n.meta)
    meta["status"] = status
    if status == "sent":
        meta["sent"] = when if date else meta.get("sent", when)
    if status == "paid":
        meta["paid"] = when
        meta.setdefault("sent", meta.get("issued"))
        if reference:
            meta["payment_reference"] = reference
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
