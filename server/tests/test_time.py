import datetime as dt

import pytest

from hive.graph import Graph
from hive.timetrack import TimeTracker


def test_add_update_delete(vault):
    tt = TimeTracker(vault)
    e = tt.add("2026-09-22", {"contract": "Acme Platform", "start": "09:00", "end": "10:30", "description": "x"})
    assert e["minutes"] == 90 and e["contract"] == "[[Acme Platform]]" and e["status"] == "confirmed"
    tt.update(e["id"], {"end": "11:00"})
    assert tt.all_entries()[0]["minutes"] == 120
    switched = tt.update(e["id"], {"start": None, "end": None, "minutes": 45})
    assert switched["minutes"] == 45 and "start" not in switched
    moved = tt.update(e["id"], {"date": "2026-09-23"})
    assert moved["date"] == "2026-09-23" and [x["date"] for x in tt.all_entries()] == ["2026-09-23"]
    tt.delete(e["id"])
    assert tt.all_entries() == []


def test_entry_needs_duration(vault):
    with pytest.raises(ValueError):
        TimeTracker(vault).add("2026-09-22", {"contract": "X"})


def test_day_file_is_readable_markdown(vault):
    TimeTracker(vault).add("2026-09-22", {"contract": "Acme", "minutes": 30, "description": "a|b"})
    text = (vault.root / "time/2026-09-22.md").read_text(encoding="utf-8")
    assert "type: timelog" in text and "| 0.50 | Acme | a/b |" in text


def test_timer(vault):
    tt = TimeTracker(vault)
    t0 = dt.datetime(2026, 9, 22, 9, 0)
    tt.start_timer("Acme", "deep work", now=t0)
    with pytest.raises(ValueError):
        tt.start_timer("Acme")
    e = tt.stop_timer(now=t0 + dt.timedelta(minutes=47))
    assert e["minutes"] == 47 and e["source"] == "timer" and tt.timer() is None
    tt.start_timer("Acme", now=t0)
    assert tt.stop_timer(now=t0 + dt.timedelta(seconds=20)) is None  # < 1 min discarded


def test_gap_detection_apply_and_reject(crm_vault):
    tt = TimeTracker(crm_vault)
    g = Graph.build(crm_vault.load_all())
    today = dt.date(2026, 9, 24)
    gaps = tt.detect_gaps(g, today=today)
    assert len(gaps) == 1
    gap = gaps[0]
    assert gap["date"] == "2026-09-22" and gap["contract"] == "contracts/Acme Platform.md" and gap["minutes"] == 15

    tt_add = tt.add("2026-09-22", {"contract": "Acme Platform", "minutes": 60})
    assert tt.detect_gaps(Graph.build(crm_vault.load_all()), today=today) == []  # logged -> no gap
    tt.delete(tt_add["id"])

    import hive.timetrack as mod
    orig = mod.TimeTracker.detect_gaps
    mod.TimeTracker.detect_gaps = lambda self, graph, days=14, today=None: orig(self, graph, days, dt.date(2026, 9, 24))
    try:
        added = tt.apply_gaps(Graph.build(crm_vault.load_all()))
        assert len(added) == 1 and added[0]["status"] == "suggested" and added[0]["gap"] == gap["id"]
        tt.reject(added[0]["id"])
        assert tt.all_entries() == []
        assert tt.apply_gaps(Graph.build(crm_vault.load_all())) == []  # dismissed stays dismissed
    finally:
        mod.TimeTracker.detect_gaps = orig


def test_summary_excludes_suggested(crm_vault):
    tt = TimeTracker(crm_vault)
    tt.add("2026-09-22", {"contract": "Acme Platform", "minutes": 120})
    tt.add("2026-09-23", {"contract": "Acme Platform", "minutes": 60, "status": "suggested"})
    s = tt.summary(Graph.build(crm_vault.load_all()), today=dt.date(2026, 9, 24))
    assert s["by_contract"]["contracts/Acme Platform.md"]["week"] == 2.0
    assert s["week_total"] == 2.0
