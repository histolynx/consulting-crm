import datetime as dt

import pytest
from fastapi.testclient import TestClient

from hive import crm, invoices, toggl
from hive.app import create_app
from hive.graph import Graph
from hive.timetrack import TimeTracker

H = {"X-Hive": "1"}

SUMMARY = "Description,Duration,Hours (decimal),Member,Project,Tags\nPlanning,0:26:16,0.4378,Me,AC contract,project mngmnt\n"
DETAILED = """User,Email,Client,Project,Task,Description,Billable,Start date,Start time,End date,End time,Duration,Tags
Me,me@x.test,,AC contract,,planning search,Yes,2026-09-21,17:00:10,2026-09-21,20:09:58,03:09:48,1.1Search
Me,me@x.test,,AC contract,,Archive downloads,Yes,2026-09-22,09:00:00,2026-09-22,09:26:16,00:26:16,3.Archive
Me,me@x.test,,AC contract,,Vendor mtg,Yes,2026-09-22,10:00:00,2026-09-22,11:15:00,01:15:00,meeting
Me,me@x.test,,AC contract,,late night,No,2026-09-22,23:30:00,2026-09-23,00:30:00,01:00:00,
Me,me@x.test,,Other proj,,x,Yes,2026-09-23,09:00:00,2026-09-23,09:10:00,00:10:00,
Me,me@x.test,,,,,Yes,2026-09-23,09:00:00,2026-09-23,09:00:00,00:00:00,
"""


@pytest.fixture
def sym(vault):
    vault.write("clients/Acme.md", {"type": "client"}, "")
    vault.write("contracts/Acme SOW.md", {
        "type": "contract", "client": "[[Acme]]", "status": "active", "rate": 150, "rate_unit": "hour",
        "toggl_projects": ["AC contract"],
        "sections": [{"name": "1.1 Search Rebuild", "budget_hours": 72, "match": ["1.1Search"]},
                     {"name": "3 Archive Export", "budget_hours": 18, "match": ["3.Archive"]},
                     "Meetings"]}, "")
    return vault


def test_summary_export_is_refused_with_instructions(sym):
    with pytest.raises(ValueError, match="Detailed"):
        toggl.parse(SUMMARY)


def test_plan_maps_projects_tags_and_flags_unknowns(sym):
    g, tt = Graph.build(sym.load_all()), TimeTracker(sym)
    p = toggl.plan(DETAILED, g, tt)
    assert p["rows"] == 5 and p["new"] == 5  # zero-duration row dropped
    assert p["unmapped_projects"] == {"Other proj": 0.17}
    assert p["unmapped_tags"] == {"meeting": 1.25}  # no section matches "meeting" (section is "Meetings")
    by = {i["description"]: i for i in p["items"]}
    assert by["planning search"]["section"] == "1.1 Search Rebuild"
    assert by["Archive downloads"]["section"] == "3 Archive Export" and by["Archive downloads"]["seconds"] == 1576
    assert by["late night"]["end"] is None and by["late night"]["billable"] is False  # crosses midnight


def test_run_requires_mapping_then_imports_exactly_and_dedupes(sym):
    g, tt = Graph.build(sym.load_all()), TimeTracker(sym)
    with pytest.raises(ValueError, match="Other proj"):
        toggl.run(DETAILED, g, tt)
    out = toggl.run(DETAILED, g, tt, project_map={"Other proj": "contracts/Acme SOW.md"})
    assert out["imported"] == 5
    es = tt.all_entries()
    assert round(sum(e["minutes"] for e in es) / 60, 4) == round((11388 + 1576 + 4500 + 3600 + 600) / 3600, 4)
    assert all(e["source"] == "toggl" and e["toggl_id"] for e in es)
    # mapping remembered on the contract, and a re-import adds nothing
    g2 = Graph.build(sym.load_all())
    assert "Other proj" in g2.notes["contracts/Acme SOW.md"].meta["toggl_projects"]
    again = toggl.run(DETAILED, g2, tt)
    assert again["imported"] == 0 and again["duplicates"] == 5


def test_sections_rollup_and_invoice_groups_by_section(sym):
    g, tt = Graph.build(sym.load_all()), TimeTracker(sym)
    toggl.run(DETAILED, g, tt, project_map={"Other proj": "contracts/Acme SOW.md"})
    g = Graph.build(sym.load_all())
    c = [x for x in crm.contracts(g, tt, today=dt.date(2026, 9, 24)) if x["path"] == "contracts/Acme SOW.md"][0]
    secs = {s["name"]: s for s in c["sections"]}
    assert secs["3 Archive Export"]["hours"] == 0.44 and secs["3 Archive Export"]["budget_hours"] == 18
    assert secs["1.1 Search Rebuild"]["burn"] == round(3.1633 / 72, 3)
    inv = invoices.generate(sym, g, tt, "contracts/Acme SOW.md", "2026-09-01", "2026-09-30", issued=dt.date(2026, 10, 1))
    names = [l["description"] for l in inv["lines"]]
    assert names[:2] == ["1.1 Search Rebuild", "3 Archive Export"]  # contract's section order first
    assert "meeting" in names  # unmapped tag kept as its own line, nothing lost
    assert len(inv["timesheet"]) == 4 and inv["timesheet"][0]["date"] == "2026-09-21"  # non-billable row excluded
    body = (sym.root / inv["path"]).read_text(encoding="utf-8")
    assert "## Timesheet" in body


def test_timer_carries_section(vault):
    tt = TimeTracker(vault)
    t0 = dt.datetime(2026, 9, 24, 9, 0)
    tt.start_timer("Acme SOW", "export", now=t0, section="3 Archive Export", billable=False)
    e = tt.stop_timer(now=t0 + dt.timedelta(minutes=30))
    assert e["section"] == "3 Archive Export" and e["billable"] is False and e["minutes"] == 30


def test_editing_imported_duration_drops_exact_seconds(sym):
    g, tt = Graph.build(sym.load_all()), TimeTracker(sym)
    toggl.run(DETAILED, g, tt, project_map={"Other proj": "contracts/Acme SOW.md"})
    e = [x for x in tt.all_entries() if x["description"] == "Archive downloads"][0]
    out = tt.update(e["id"], {"start": "09:00", "end": "10:00"})
    assert out["minutes"] == 60 and "seconds" not in out


def test_api_section_crud_and_import(sym):
    c = TestClient(create_app(sym.root))
    r = c.post("/api/contracts/section", json={"path": "contracts/Acme SOW.md", "name": "Ingest pipeline",
                                              "budget_hours": 56, "match": ["1.Ingest"]}, headers=H).json()
    assert {"name": "Ingest pipeline", "budget_hours": 56.0, "match": ["1.Ingest"]} in r["sections"]
    r = c.post("/api/contracts/section", json={"path": "contracts/Acme SOW.md", "name": "Meetings", "remove": True}, headers=H).json()
    assert all(s["name"] != "Meetings" for s in r["sections"])
    bad = c.post("/api/time/import/preview", json={"csv": SUMMARY}, headers=H)
    assert bad.status_code == 400 and "Summary" in bad.json()["detail"]
    pv = c.post("/api/time/import/preview", json={"csv": DETAILED}, headers=H).json()
    assert pv["new"] == 5 and "Other proj" in pv["unmapped_projects"] and len(pv["sample"]) == 5
    ok = c.post("/api/time/import", json={"csv": DETAILED, "project_map": {"Other proj": "contracts/Acme SOW.md"}}, headers=H).json()
    assert ok["imported"] == 5
    st = c.post("/api/timer/start", json={"contract": "Acme SOW", "section": "3 Archive Export", "description": "x"}, headers=H).json()
    assert st["section"] == "3 Archive Export"
