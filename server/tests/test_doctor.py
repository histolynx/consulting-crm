import datetime as dt

from hive import doctor


def test_check_tasks_flags_old_paths_and_missing_tasks(tmp_path):
    """After the repo moved, the tasks kept the old absolute path and the hourly sync just stopped."""
    root = tmp_path / "repo"
    (root / "server").mkdir(parents=True)
    tasks = [{"name": "HIVE Server", "state": "Running", "dir": str(root / "server")},
             {"name": "HIVE Sync", "state": "Ready", "dir": str(root)},
             {"name": "HIVE Orchestrator", "state": "Ready", "dir": str(tmp_path / "old-place")}]
    res = {c["check"]: c for c in doctor.check_tasks(tasks, root)}
    assert res["HIVE Server"]["ok"] and res["HIVE Sync"]["ok"]
    assert not res["HIVE Orchestrator"]["ok"] and "re-run the install script" in res["HIVE Orchestrator"]["detail"]
    assert not res["HIVE Brief"]["ok"] and "not registered" in res["HIVE Brief"]["detail"]
    assert doctor.check_tasks(None, root) == [{"check": "scheduled tasks", "ok": False, "detail": "could not query Windows scheduled tasks"}]


def test_check_sync_age_and_failed_steps(vault):
    now = dt.datetime(2026, 11, 3, 12, 0)
    assert doctor.check_sync(vault, now)["ok"]  # never synced: nothing to complain about yet
    vault.set_state("last_sync", {"finished": "2026-11-03T11:30:00", "steps": [{"step": "fetch", "ok": True}]})
    assert doctor.check_sync(vault, now)["ok"]
    vault.set_state("last_sync", {"finished": "2026-11-03T06:00:00", "steps": [{"step": "fetch", "ok": True}]})
    stale = doctor.check_sync(vault, now)
    assert not stale["ok"] and "stale" in stale["detail"] and stale["detail"].startswith("6.0 h ago")
    vault.set_state("last_sync", {"finished": "2026-11-03T11:30:00", "steps": [{"step": "ingest", "ok": False, "error": "x"}]})
    failed = doctor.check_sync(vault, now)
    assert not failed["ok"] and "ingest" in failed["detail"]
