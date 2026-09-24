"""Built-in time tracker. One markdown file per day: vault/time/YYYY-MM-DD.md.

Entry shape (frontmatter `entries:` list):
  id, contract: "[[Contract]]", start: "HH:MM", end: "HH:MM", minutes, description,
  billable: bool, status: confirmed|suggested, source: manual|timer|hive-gap|agent, invoice: "[[INV-...]]"

Suggested entries are written automatically by gap detection but never invoiced until confirmed.
"""
from __future__ import annotations

import datetime as dt
import math
import secrets
from collections import defaultdict
from typing import Any

from .graph import Graph
from .vault import WIKILINK, Vault

EMAIL_MINUTES = 15
MEETING_MINUTES = 60


def _link_target(v: Any) -> str | None:
    if not isinstance(v, str):
        return None
    m = WIKILINK.search(v)
    return m.group(1).strip() if m else (v.strip() or None)


def _minutes(e: dict[str, Any]) -> float:
    if e.get("seconds") is not None:  # exact duration from an import (e.g. Toggl), keeps totals to the second
        return round(float(e["seconds"]) / 60, 4)
    if e.get("start") and e.get("end"):
        s = dt.datetime.strptime(str(e["start"]), "%H:%M")
        f = dt.datetime.strptime(str(e["end"]), "%H:%M")
        mins = int((f - s).total_seconds() // 60)
        return mins if mins >= 0 else mins + 24 * 60
    return int(e.get("minutes") or 0)


def day_path(date: str) -> str:
    return f"time/{date}.md"


def _render_body(date: str, entries: list[dict[str, Any]]) -> str:
    lines = [f"# Time log: {date}", "", "| Start | End | Hours | Contract | Description | Status |", "|---|---|---|---|---|---|"]
    total = 0
    for e in entries:
        m = _minutes(e)
        total += m
        where = " · ".join(x for x in (_link_target(e.get("contract")), e.get("section")) if x)
        lines.append(f"| {e.get('start','')} | {e.get('end','')} | {m/60:.2f} | {where} "
                     f"| {str(e.get('description','')).replace('|','/')} | {e.get('status','confirmed')} |")
    lines += ["", f"**Total:** {total/60:.2f} h", ""]
    return "\n".join(lines)


class TimeTracker:
    def __init__(self, vault: Vault):
        self.vault = vault

    # ---------- storage ----------
    def _load_day(self, date: str) -> list[dict[str, Any]]:
        p = self.vault.root / day_path(date)
        if not p.exists():
            return []
        return list(self.vault.read(day_path(date)).meta.get("entries") or [])

    def _save_day(self, date: str, entries: list[dict[str, Any]], actor: str) -> None:
        entries = sorted(entries, key=lambda e: (str(e.get("start") or "99:99"), e["id"]))
        meta = {"type": "timelog", "date": date, "tags": ["time"], "entries": entries}
        self.vault.write(day_path(date), meta, _render_body(date, entries), actor=actor, action="time")

    def all_entries(self) -> list[dict[str, Any]]:
        out = []
        tdir = self.vault.root / "time"
        if not tdir.exists():
            return out
        for p in sorted(tdir.glob("????-??-??.md")):
            date = p.stem
            for e in self._load_day(date):
                out.append({**e, "date": date, "minutes": _minutes(e), "contract_name": _link_target(e.get("contract"))})
        return out

    # ---------- CRUD ----------
    def add(self, date: str, entry: dict[str, Any], actor: str = "ui") -> dict[str, Any]:
        dt.date.fromisoformat(date)  # validate
        e = {k: v for k, v in entry.items() if v not in (None, "")}
        e.setdefault("billable", True)
        e.setdefault("status", "confirmed")
        e.setdefault("source", "manual")
        if e.get("contract") and "[[" not in str(e["contract"]):
            e["contract"] = f"[[{e['contract']}]]"
        if not (e.get("start") and e.get("end")) and not e.get("minutes"):
            raise ValueError("entry needs start+end or minutes")
        e["id"] = "t_" + secrets.token_hex(4)
        if e.get("start") and e.get("end"):
            e["minutes"] = _minutes(e)
        entries = self._load_day(date)
        entries.append(e)
        self._save_day(date, entries, actor)
        return {**e, "date": date}

    def add_many(self, by_day: dict[str, list[dict[str, Any]]], actor: str = "import") -> int:
        """Batch insert (one write per day file). Entries must already carry a duration."""
        n = 0
        for date, new in by_day.items():
            dt.date.fromisoformat(date)
            entries = self._load_day(date)
            for e in new:
                e = {k: v for k, v in e.items() if v not in (None, "")}
                if not (e.get("start") and e.get("end")) and not e.get("minutes") and not e.get("seconds"):
                    raise ValueError(f"entry on {date} has no duration")
                e["id"] = "t_" + secrets.token_hex(4)
                entries.append(e)
                n += 1
            self._save_day(date, entries, actor)
        return n

    def _find(self, entry_id: str) -> tuple[str, list[dict[str, Any]], int]:
        for p in (self.vault.root / "time").glob("????-??-??.md"):
            entries = self._load_day(p.stem)
            for i, e in enumerate(entries):
                if e.get("id") == entry_id:
                    return p.stem, entries, i
        raise KeyError(entry_id)

    def update(self, entry_id: str, patch: dict[str, Any], actor: str = "ui") -> dict[str, Any]:
        date, entries, i = self._find(entry_id)
        new_date = patch.pop("date", None)
        if any(k in patch for k in ("start", "end", "minutes")):
            entries[i].pop("seconds", None)  # a manual duration edit supersedes the imported exact duration
        for k, v in patch.items():
            if k == "id":
                continue
            if v is None:
                entries[i].pop(k, None)
            else:
                entries[i][k] = v
        if entries[i].get("start") and entries[i].get("end"):
            entries[i]["minutes"] = _minutes(entries[i])
        if new_date and new_date != date:
            moved = entries.pop(i)
            self._save_day(date, entries, actor)
            target = self._load_day(new_date)
            target.append(moved)
            self._save_day(new_date, target, actor)
            return {**moved, "date": new_date}
        self._save_day(date, entries, actor)
        return {**entries[i], "date": date}

    def delete(self, entry_id: str, actor: str = "ui") -> None:
        date, entries, i = self._find(entry_id)
        entries.pop(i)
        self._save_day(date, entries, actor)

    # ---------- timer ----------
    def timer(self) -> dict[str, Any] | None:
        return self.vault.state("timer")

    def start_timer(self, contract: str | None, description: str = "", now: dt.datetime | None = None,
                    section: str | None = None, billable: bool = True) -> dict[str, Any]:
        if self.timer():
            raise ValueError("a timer is already running; stop it first")
        now = now or dt.datetime.now()
        t = {"started": now.isoformat(timespec="seconds"), "contract": contract, "description": description,
             "section": section, "billable": billable}
        self.vault.set_state("timer", t)
        self.vault.audit("ui", "timer-start", contract or "")
        return t

    def stop_timer(self, now: dt.datetime | None = None) -> dict[str, Any] | None:
        t = self.timer()
        if not t:
            return None
        now = now or dt.datetime.now()
        started = dt.datetime.fromisoformat(t["started"])
        (self.vault.root / ".hive" / "timer.json").unlink()
        if (now - started).total_seconds() < 60:
            self.vault.audit("ui", "timer-discard", t.get("contract") or "", reason="< 1 minute")
            return None
        common = {"contract": t.get("contract"), "section": t.get("section"), "description": t.get("description"),
                  "billable": t.get("billable", True), "source": "timer"}
        if started.date() != now.date():
            # split across midnight is rare for consulting work: log as minutes on the start day
            mins = int((now - started).total_seconds() // 60)
            return self.add(started.date().isoformat(), {**common, "minutes": mins})
        return self.add(started.date().isoformat(), {**common, "start": started.strftime("%H:%M"), "end": now.strftime("%H:%M")})

    # ---------- analysis ----------
    def summary(self, graph: Graph, today: dt.date | None = None) -> dict[str, Any]:
        today = today or dt.date.today()
        week_start = today - dt.timedelta(days=today.weekday())
        month_start = today.replace(day=1)
        entries = self.all_entries()
        by_contract: dict[str, dict[str, float]] = defaultdict(lambda: {"week": 0.0, "month": 0.0, "total": 0.0, "unbilled": 0.0})
        week_grid: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        by_section: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for e in entries:
            if e.get("status") == "suggested":
                continue
            d = dt.date.fromisoformat(e["date"])
            h = e["minutes"] / 60
            path = graph.resolve(e["contract_name"]) if e.get("contract_name") else None
            key = path or "(no contract)"
            by_contract[key]["total"] += h
            by_section[key][e.get("section") or "(unsectioned)"] += h
            if d >= week_start:
                by_contract[key]["week"] += h
                week_grid[key][e["date"]] += h
            if d >= month_start:
                by_contract[key]["month"] += h
            if e.get("billable", True) and not e.get("invoice"):
                by_contract[key]["unbilled"] += h
        return {"by_contract": {k: {kk: round(vv, 2) for kk, vv in v.items()} for k, v in by_contract.items()},
                "by_section": {k: {kk: round(vv, 2) for kk, vv in v.items()} for k, v in by_section.items()},
                "week_start": week_start.isoformat(),
                "week_grid": {k: dict(v) for k, v in week_grid.items()},
                "week_total": round(sum(v["week"] for v in by_contract.values()), 2),
                "month_total": round(sum(v["month"] for v in by_contract.values()), 2)}

    def detect_gaps(self, graph: Graph, days: int = 14, today: dt.date | None = None) -> list[dict[str, Any]]:
        """Days where the graph shows client activity (emails, meetings) but no time was logged."""
        today = today or dt.date.today()
        window_start = today - dt.timedelta(days=days)
        dismissed = set(self.vault.state("dismissed_gaps", []))

        contracts = {p: n for p, n in graph.notes.items()
                     if n.type == "contract" and str(n.meta.get("status", "active")) in ("active", "negotiating", "proposal")}
        client_of: dict[str, str | None] = {}
        related: dict[str, set[str]] = {}
        for cp, cn in contracts.items():
            client = graph.resolve(_link_target(cn.meta.get("client")) or "") if cn.meta.get("client") else None
            client_of[cp] = client
            rel = {cp}
            if client:
                rel.add(client)
                rel |= {v for v in graph.adj.get(client, ()) if graph.nodes.get(v, {}).get("type") == "contact"}
            related[cp] = rel

        logged: set[tuple[str, str]] = set()
        for e in self.all_entries():
            p = graph.resolve(e["contract_name"]) if e.get("contract_name") else None
            if p:
                logged.add((e["date"], p))

        buckets: dict[tuple[str, str], dict[str, Any]] = {}
        for ap, an in graph.notes.items():
            if an.type not in ("email", "meeting"):
                continue
            raw_date = str(an.meta.get("date") or "")[:10]
            try:
                d = dt.date.fromisoformat(raw_date)
            except ValueError:
                continue
            if not (window_start <= d <= today):
                continue
            neigh = graph.adj.get(ap, set())
            direct = [cp for cp in contracts if cp in neigh]
            matches = direct or [cp for cp in contracts if neigh & related[cp]]
            if not matches:
                continue
            cp = sorted(matches)[0]
            key = (d.isoformat(), cp)
            b = buckets.setdefault(key, {"minutes": 0, "evidence": []})
            b["minutes"] += int(an.meta.get("duration") or MEETING_MINUTES) if an.type == "meeting" else EMAIL_MINUTES
            b["evidence"].append(ap)

        out = []
        for (date, cp), b in sorted(buckets.items()):
            gid = f"{date}|{cp}"
            if (date, cp) in logged or gid in dismissed:
                continue
            mins = max(15, int(math.ceil(b["minutes"] / 15.0)) * 15)
            out.append({"id": gid, "date": date, "contract": cp, "contract_name": graph.nodes[cp]["title"],
                        "minutes": mins, "evidence": b["evidence"],
                        "reason": f"{len(b['evidence'])} email/meeting note(s) linked to this contract, no time logged"})
        return out

    def apply_gaps(self, graph: Graph, days: int = 14, actor: str = "hive-gap") -> list[dict[str, Any]]:
        """Auto-add each detected gap as a *suggested* entry (not billable until confirmed)."""
        added = []
        for g in self.detect_gaps(graph, days):
            e = self.add(g["date"], {"contract": f"[[{graph.notes[g['contract']].title}]]", "minutes": g["minutes"],
                                     "description": f"Suggested by HIVE: {g['reason']}", "status": "suggested",
                                     "source": "hive-gap", "gap": g["id"], "evidence": [f"[[{graph.notes[p].title}]]" for p in g["evidence"]]},
                         actor=actor)
            added.append(e)
        return added

    def confirm(self, entry_id: str, actor: str = "ui") -> dict[str, Any]:
        return self.update(entry_id, {"status": "confirmed"}, actor)

    def reject(self, entry_id: str, actor: str = "ui") -> None:
        """Delete a suggested entry and remember not to suggest that day/contract again."""
        date, entries, i = self._find(entry_id)
        gap = entries[i].get("gap")
        self.delete(entry_id, actor)
        if gap:
            self.dismiss_gap(gap)

    def dismiss_gap(self, gap_id: str) -> None:
        d = self.vault.state("dismissed_gaps", [])
        if gap_id not in d:
            d.append(gap_id)
        self.vault.set_state("dismissed_gaps", d)
