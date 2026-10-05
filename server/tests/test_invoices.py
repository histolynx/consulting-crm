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


def test_record_external_invoice_stamps_entries_and_reconciles(crm_vault):
    tt = TimeTracker(crm_vault)
    a = tt.add("2026-09-10", {"contract": "Acme Platform", "section": "Build", "minutes": 120})
    b = tt.add("2026-09-11", {"contract": "Acme Platform", "section": "Export", "minutes": 90})
    c = tt.add("2026-09-12", {"contract": "Acme Platform", "section": "Build", "minutes": 60})  # deliberately left off
    inv = invoices.record(crm_vault, G(crm_vault), tt, "contracts/Acme Platform.md", "INV-ACME-001", "2026-09-30",
                          [{"description": "Build", "qty": 2, "rate": 150}, {"description": "Export", "qty": 1, "rate": 150}],
                          [a["id"], b["id"]], status="sent", sent_to="ap@acme.test",
                          unbilled=[{"section": "Export", "hours": 0.5, "reason": "over estimate"}])
    assert inv["total"] == 450.0 and inv["due"] == "2026-10-15" and inv["sent"] == "2026-09-30" and inv["source"] == "recorded"
    assert inv["reconciliation"] == {"line_hours": 3.0, "entry_hours": 3.5, "unbilled_hours": 0.5, "difference": 0.0}
    stamped = {e["id"]: e.get("invoice") for e in tt.all_entries()}
    assert stamped[a["id"]] == stamped[b["id"]] == "[[INV-ACME-001]]" and stamped[c["id"]] is None
    with pytest.raises(ValueError, match="already exists"):
        invoices.record(crm_vault, G(crm_vault), tt, "contracts/Acme Platform.md", "INV-ACME-001", "2026-09-30",
                        [{"description": "x", "qty": 1, "rate": 1}], [c["id"]])
    with pytest.raises(ValueError, match="already on"):
        invoices.record(crm_vault, G(crm_vault), tt, "contracts/Acme Platform.md", "INV-ACME-002", "2026-09-30",
                        [{"description": "x", "qty": 1, "rate": 1}], [a["id"]])
    # paid on a specific date with a reference; attach the PDF
    paid = invoices.set_status(crm_vault, G(crm_vault), inv["path"], "paid", tt, date="2026-10-20", reference="ACH 4471")
    assert paid["paid"] == "2026-10-20" and paid["payment_reference"] == "ACH 4471"
    att = invoices.attach_document(crm_vault, G(crm_vault), inv["path"], "acme sept invoice.pdf", b"%PDF-1.4 x")
    assert att["document"] == "documents/Acme/invoices/acme sept invoice.pdf"
    assert (crm_vault.root / att["document"]).read_bytes() == b"%PDF-1.4 x"
    s = invoices.summary(G(crm_vault), today=dt.date(2026, 10, 25))
    assert s["paid_ytd"] == 450.0 and s["outstanding"] == 0


def test_record_rejects_malformed_payload(crm_vault):
    with pytest.raises(ValueError, match="entry_ids"):
        invoices.record(crm_vault, G(crm_vault), TimeTracker(crm_vault), "contracts/Acme Platform.md", "X-1", "2026-09-30",
                        [{"description": "x", "qty": 1, "rate": 1}], [{"value": "t_1"}])


def test_sent_date_can_be_backdated(crm_vault):
    tt = TimeTracker(crm_vault)
    tt.add("2026-09-10", {"contract": "Acme Platform", "minutes": 60})
    inv = invoices.generate(crm_vault, G(crm_vault), tt, "contracts/Acme Platform.md", "2026-09-01", "2026-09-30")
    assert invoices.set_status(crm_vault, G(crm_vault), inv["path"], "sent", date="2026-09-30")["sent"] == "2026-09-30"


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
