import datetime as dt

import pytest

from hive import crm, invoices
from hive.graph import Graph
from hive.timetrack import TimeTracker


def G(v):
    return Graph.build(v.load_all())


def test_hourly_invoice_marks_entries_and_skips_suggested(crm_vault):
    tt = TimeTracker(crm_vault)
    a = tt.add("2026-09-10", {"contract": "Acme Platform", "minutes": 90, "description": "Design"})
    tt.add("2026-09-11", {"contract": "Acme Platform", "minutes": 60, "status": "suggested"})
    tt.add("2026-09-12", {"contract": "Acme Platform", "minutes": 60, "billable": False})
    tt.add("2026-10-02", {"contract": "Acme Platform", "minutes": 60})  # outside period
    inv = invoices.generate(crm_vault, G(crm_vault), tt, "contracts/Acme Platform.md", "2026-09-01", "2026-09-30",
                            issued=dt.date(2026, 9, 30))
    assert inv["number"] == "INV-2026-001" and inv["total"] == 225.0 and inv["due"] == "2026-10-15"
    assert inv["client"] == "[[Acme]]" and inv["entries"] == [a["id"]]
    assert [e for e in tt.all_entries() if e["id"] == a["id"]][0]["invoice"] == "[[INV-2026-001]]"
    with pytest.raises(ValueError, match="nothing billable"):
        invoices.generate(crm_vault, G(crm_vault), tt, "contracts/Acme Platform.md", "2026-09-01", "2026-09-30")


def test_numbering_and_status(crm_vault):
    tt = TimeTracker(crm_vault)
    tt.add("2026-09-10", {"contract": "Acme Platform", "minutes": 60})
    tt.add("2026-09-20", {"contract": "Acme Platform", "minutes": 60})
    i1 = invoices.generate(crm_vault, G(crm_vault), tt, "contracts/Acme Platform.md", "2026-09-01", "2026-09-15", issued=dt.date(2026, 9, 15))
    i2 = invoices.generate(crm_vault, G(crm_vault), tt, "contracts/Acme Platform.md", "2026-09-16", "2026-09-30", issued=dt.date(2026, 9, 30))
    assert (i1["number"], i2["number"]) == ("INV-2026-001", "INV-2026-002")
    invoices.set_status(crm_vault, G(crm_vault), i1["path"], "sent")
    s = invoices.summary(G(crm_vault), today=dt.date(2026, 10, 20))
    assert s["outstanding"] == 150.0 and s["overdue"] == 150.0
    with pytest.raises(ValueError):
        invoices.set_status(crm_vault, G(crm_vault), i1["path"], "bogus")


def test_void_releases_time(crm_vault):
    tt = TimeTracker(crm_vault)
    tt.add("2026-09-10", {"contract": "Acme Platform", "minutes": 60})
    inv = invoices.generate(crm_vault, G(crm_vault), tt, "contracts/Acme Platform.md", "2026-09-01", "2026-09-30")
    invoices.set_status(crm_vault, G(crm_vault), inv["path"], "void", tt)
    assert "invoice" not in tt.all_entries()[0]
    again = invoices.generate(crm_vault, G(crm_vault), tt, "contracts/Acme Platform.md", "2026-09-01", "2026-09-30")
    assert again["total"] == 150.0 and again["number"].endswith("-002")


def test_day_rate(crm_vault):
    tt = TimeTracker(crm_vault)
    tt.add("2026-09-10", {"contract": "Globex Graph", "minutes": 240})
    inv = invoices.generate(crm_vault, G(crm_vault), tt, "contracts/Globex Graph.md", "2026-09-01", "2026-09-30")
    assert inv["lines"][0]["qty"] == 0.5 and inv["total"] == 500.0


def test_fixed_fee_milestones(crm_vault):
    crm_vault.write("contracts/Fixed.md", {"type": "contract", "client": "[[Acme]]", "rate_unit": "fixed",
                    "milestones": [{"name": "M1", "amount": 5000, "status": "complete"}, {"name": "M2", "amount": 5000, "status": "planned"}]}, "")
    tt = TimeTracker(crm_vault)
    inv = invoices.generate(crm_vault, G(crm_vault), tt, "contracts/Fixed.md", "2026-09-01", "2026-09-30")
    assert inv["total"] == 5000.0
    ms = crm_vault.read("contracts/Fixed.md").meta["milestones"]
    assert ms[0]["invoice"] == f"[[{inv['number']}]]" and "invoice" not in ms[1]


def test_future_meeting_is_not_a_touch(crm_vault):
    crm_vault.write("meetings/2026-10-30 Sync.md", {"type": "meeting", "date": "2026-10-30", "attendees": ["[[Hank Scorpio]]"]}, "")
    people = {c["path"]: c for c in crm.contacts(G(crm_vault), today=dt.date(2026, 9, 24))}
    assert people["contacts/Hank Scorpio.md"]["last_contact"] == "2026-01-01"


def test_dashboard_kpis(crm_vault):
    tt = TimeTracker(crm_vault)
    tt.add("2026-09-22", {"contract": "Acme Platform", "minutes": 540})
    d = crm.dashboard(G(crm_vault), tt, today=dt.date(2026, 9, 24))
    k = d["kpis"]
    assert k["active_contracts"] == 1 and k["active_value"] == 30000
    assert k["pipeline_weighted"] == 12000.0  # negotiating default probability 0.6
    assert k["unbilled_value"] == 1350.0
    assert [c["path"] for c in d["over_budget"]] == ["contracts/Acme Platform.md"]  # 9h of 10h budget
    assert [c["path"] for c in d["ending_soon"]] == ["contracts/Acme Platform.md"]
    assert [c["path"] for c in d["cold_contacts"]] == ["contacts/Hank Scorpio.md"]
    assert [t["text"] for t in d["tasks_due"]] == ["Send SOW 📅 2026-09-25"]
