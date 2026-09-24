"""Import Toggl Track CSV exports into HIVE's time log.

Needs the **Detailed report** export (Reports → Detailed → Export → CSV), which carries start/end dates.
The Summary export has no dates, so it's refused with an explanation rather than guessed at.

Mapping:
  Toggl project → HIVE contract : contract frontmatter `toggl_projects: ["Acme contract"]`, or an explicit map
  Toggl tag     → contract section: section `match: ["3.Archive"]` or a tag equal to the section name
Re-importing is safe: each row gets a stable `toggl_id` (hash of start, duration, project, description) and
duplicates are skipped. Exact durations are kept in `seconds`, so totals match Toggl to the second.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
from collections import defaultdict
from typing import Any

from .sections import contract_sections, section_for_tag
from .graph import Graph
from .timetrack import TimeTracker


class ImportError_(ValueError):
    pass


ALIASES = {
    "start date": "start_date", "start time": "start_time", "end date": "end_date", "end time": "end_time",
    "duration": "duration", "description": "description", "project": "project", "tags": "tags",
    "billable": "billable", "client": "client", "task": "task",
}


def _secs(d: str) -> int:
    parts = [int(p) for p in d.strip().split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, s = parts
    return h * 3600 + m * 60 + s


def _date(s: str) -> str:
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%d.%m.%Y"):
        try:
            return dt.datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    raise ImportError_(f"unrecognised date {s!r}")


def parse(csv_text: str) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(csv_text.lstrip("﻿")))
    if not reader.fieldnames:
        raise ImportError_("empty CSV")
    cols = {f: ALIASES.get(f.strip().lower()) for f in reader.fieldnames}
    have = set(cols.values())
    if "start_date" not in have:
        raise ImportError_(
            "This looks like a Toggl *Summary* export: it has no dates, so HIVE can't place hours on days or invoice by month. "
            "In Toggl: Reports → Detailed → pick the date range → Export → Download CSV, and import that file.")
    if "duration" not in have:
        raise ImportError_("CSV has no Duration column")
    rows = []
    for raw in reader:
        r = {cols[k]: (v or "").strip() for k, v in raw.items() if k in cols and cols[k]}
        secs = _secs(r.get("duration") or "0")
        if secs <= 0:
            continue
        rows.append({**r, "seconds": secs, "date": _date(r["start_date"]),
                     "end_date_iso": _date(r["end_date"]) if r.get("end_date") else None})
    return rows


def toggl_id(r: dict[str, Any]) -> str:
    key = "|".join([r["date"], r.get("start_time", ""), str(r["seconds"]), r.get("project", ""), r.get("description", "")])
    return "tg_" + hashlib.sha1(key.encode()).hexdigest()[:12]


def plan(csv_text: str, graph: Graph, tracker: TimeTracker, project_map: dict[str, str] | None = None) -> dict[str, Any]:
    """Dry run: what would be imported, where, and what can't be mapped."""
    rows = parse(csv_text)
    project_map = dict(project_map or {})
    for p, n in graph.notes.items():  # remembered mappings from contract frontmatter
        if n.type == "contract":
            for tp in n.meta.get("toggl_projects") or []:
                project_map.setdefault(str(tp), p)
    existing = {e.get("toggl_id") for e in tracker.all_entries() if e.get("toggl_id")}
    items, dupes = [], 0
    unmapped_projects: dict[str, float] = defaultdict(float)
    unmapped_tags: dict[str, float] = defaultdict(float)
    by_bucket: dict[str, float] = defaultdict(float)
    for r in rows:
        tid = toggl_id(r)
        if tid in existing:
            dupes += 1
            continue
        proj = r.get("project", "")
        cpath = project_map.get(proj)
        if proj and cpath not in graph.notes:
            cpath = None
        hours = r["seconds"] / 3600
        section = None
        tags = [t.strip() for t in (r.get("tags") or "").split(",") if t.strip()]
        if cpath:
            secs = contract_sections(graph.notes[cpath].meta)
            for t in tags:
                section = section_for_tag(secs, t)
                if section:
                    break
            if tags and not section:
                section = tags[0]
                unmapped_tags[tags[0]] += hours
        else:
            unmapped_projects[proj or "(no project)"] += hours
        title = graph.notes[cpath].title if cpath else None
        by_bucket[f"{title or '(no contract)'} · {section or '(no section)'}"] += hours
        items.append({"toggl_id": tid, "date": r["date"], "contract_path": cpath, "contract": title, "section": section,
                      "description": r.get("description") or (section or "Toggl entry"),
                      "start": (r.get("start_time") or "")[:5] or None,
                      "end": (r.get("end_time") or "")[:5] if r.get("end_date_iso") == r["date"] else None,
                      "seconds": r["seconds"],
                      "billable": (r.get("billable", "Yes").lower() not in ("no", "false", "0")),
                      "tags": tags})
    dates = sorted(i["date"] for i in items)
    return {"rows": len(rows), "new": len(items), "duplicates": dupes,
            "hours": round(sum(i["seconds"] for i in items) / 3600, 2),
            "first_date": dates[0] if dates else None, "last_date": dates[-1] if dates else None,
            "by_bucket": {k: round(v, 2) for k, v in sorted(by_bucket.items())},
            "unmapped_projects": {k: round(v, 2) for k, v in unmapped_projects.items()},
            "unmapped_tags": {k: round(v, 2) for k, v in unmapped_tags.items()},
            "items": items}


def run(csv_text: str, graph: Graph, tracker: TimeTracker, project_map: dict[str, str] | None = None,
        remember: bool = True) -> dict[str, Any]:
    p = plan(csv_text, graph, tracker, project_map)
    if p["unmapped_projects"]:
        raise ImportError_(f"Map these Toggl projects to a contract first: {', '.join(p['unmapped_projects'])}")
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for i in p["items"]:
        e = {"contract": f"[[{i['contract']}]]", "section": i["section"], "description": i["description"],
             "seconds": i["seconds"], "minutes": round(i["seconds"] / 60, 4), "billable": i["billable"],
             "status": "confirmed", "source": "toggl", "toggl_id": i["toggl_id"]}
        if i["start"] and i["end"]:
            e.update(start=i["start"], end=i["end"])
        by_day[i["date"]].append(e)
    added = tracker.add_many(by_day, actor="toggl-import")
    if remember and project_map:
        for proj, cpath in project_map.items():
            n = graph.notes.get(cpath)
            if n and proj not in (n.meta.get("toggl_projects") or []):
                meta = dict(n.meta)
                meta["toggl_projects"] = [*(meta.get("toggl_projects") or []), proj]
                tracker.vault.write(cpath, meta, n.body, actor="toggl-import", action="remember-mapping")
    tracker.vault.audit("toggl-import", "import", f"{added} entries", hours=p["hours"], duplicates=p["duplicates"])
    return {**{k: v for k, v in p.items() if k != "items"}, "imported": added}
