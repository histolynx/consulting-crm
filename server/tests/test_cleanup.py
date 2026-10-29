import os
import time

import pytest

from hive.cleanup import HOLDING, PROCESSED, Cleanup
from hive.orchestrator import Orchestrator


@pytest.fixture
def env(vault, tmp_path):
    dl = tmp_path / "Downloads"
    dl.mkdir()
    drive = tmp_path / "Drive" / "Work"
    (dl / "report.pdf").write_bytes(b"same-bytes")
    (dl / "report (1).pdf").write_bytes(b"same-bytes")          # exact duplicate
    old = time.time() - 3600
    os.utime(dl / "report (1).pdf", (old, old))
    (dl / "notes.md").write_text("# method")                    # filed into HIVE already
    (dl / "bylaws.docx").write_bytes(b"bylaws")                 # confident proposal → organize
    (dl / "mystery.txt").write_text("?")                        # unclassified → ask
    (dl / "obgyn_visit_summary.md").write_text("PRIVATE")      # personal → never listed
    (dl / PROCESSED).mkdir()
    (dl / PROCESSED / "old.md").write_text("x")                 # already processed folder is ignored
    o = Orchestrator(vault)
    cfg = o.config()
    cfg.update(watch=[str(dl)], drive_root=str(drive))
    o._save("config", cfg)
    o._set_proposals([
        {"id": "p1", "key": "k1", "path": str(dl / "notes.md"), "name": "notes.md", "status": "filed", "filed_to": "library/Research/x/notes.md"},
        {"id": "p2", "key": "k2", "path": str(dl / "bylaws.docx"), "name": "bylaws.docx", "status": "proposed",
         "suggestion": {"area": "MSU", "topic": "Advisory Board", "confidence": 0.9, "summary": "bylaws"}},
    ])
    return Cleanup(vault), dl, drive


def test_plan_categorizes_without_touching_anything(env):
    c, dl, drive = env
    plan = c.plan(str(dl))
    kinds = {o["name"]: o["kind"] for o in plan["ops"]}
    assert kinds == {"report.pdf": "ask", "report (1).pdf": "duplicate", "notes.md": "processed",
                     "bylaws.docx": "organize", "mystery.txt": "ask"}
    assert plan["personal_skipped"] == 1 and "obgyn" not in str(plan)
    dst = {o["name"]: o["dst"] for o in plan["ops"]}
    assert dst["bylaws.docx"] == str(drive / "MSU" / "Advisory Board" / "bylaws.docx")
    assert all((dl / n).exists() for n in kinds)  # planning moved nothing


def test_apply_only_ticked_ops_then_undo(env):
    c, dl, drive = env
    plan = c.plan(str(dl))
    ids = {o["name"]: o["id"] for o in plan["ops"]}
    run = c.apply(plan["id"], [ids["report (1).pdf"], ids["notes.md"], ids["bylaws.docx"]])
    assert len(run["moved"]) == 3 and run["errors"] == []
    assert (dl / PROCESSED / "notes.md").exists() and (drive / "MSU" / "Advisory Board" / "bylaws.docx").exists()
    assert list((dl / HOLDING).rglob("report (1).pdf")) and (dl / "report.pdf").exists() and (dl / "mystery.txt").exists()
    # orchestrator proposal follows the moved file so 'Copy in' still works
    p2 = next(p for p in c.orch.proposals() if p["id"] == "p2")
    assert p2["path"] == str(drive / "MSU" / "Advisory Board" / "bylaws.docx")
    back = c.undo(plan["id"])
    assert back["restored"] == 3 and (dl / "notes.md").exists() and (dl / "bylaws.docx").exists() and (dl / "report (1).pdf").exists()
    assert next(p for p in c.orch.proposals() if p["id"] == "p2")["path"] == str(dl / "bylaws.docx")
    with pytest.raises(ValueError):
        c.undo(plan["id"])


def test_never_overwrites_existing_destination(env):
    c, dl, drive = env
    (dl / PROCESSED / "notes.md").write_text("already here")
    plan = c.plan(str(dl))
    op = next(o for o in plan["ops"] if o["name"] == "notes.md")
    c.apply(plan["id"], [op["id"]])
    assert (dl / PROCESSED / "notes.md").read_text() == "already here" and (dl / PROCESSED / "notes (2).md").exists()
