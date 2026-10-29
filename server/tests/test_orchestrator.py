import json
from pathlib import Path

import pytest

from hive.graph import Graph
from hive.notify import toast_xml
from hive.orchestrator import Orchestrator, ensure_area_hubs


@pytest.fixture
def setup(vault, tmp_path):
    watch = tmp_path / "Downloads"
    (watch / "deep" / "a" / "b" / "c").mkdir(parents=True)
    (watch / "16S Pipeline Explorer.md").write_text("---\ntags: [pipeline]\n---\n# 16S pipeline\nDADA2 steps")
    (watch / "results.csv").write_text("sample,shannon\nA,3.1\n")
    (watch / "obgyn_visit_summary.md").write_text("PRIVATE")              # personal by name
    (watch / "Family" ).mkdir()
    (watch / "Family" / "plan.md").write_text("PRIVATE")                  # personal by folder
    (watch / "photo.jpg").write_bytes(b"x")                               # not a work type
    (watch / "deep" / "a" / "b" / "c" / "too_deep.md").write_text("x")    # beyond max depth
    o = Orchestrator(vault)
    cfg = o.config()
    cfg["watch"] = [str(watch)]
    o._save("config", cfg)
    vault.write("projects/Acme Data Analysis.md", {"type": "project"}, "")
    ensure_area_hubs(vault)
    return o, watch


def test_scan_skips_personal_without_recording_names(setup, vault):
    o, watch = setup
    res = o.scan()
    assert sorted(res["names"]) == ["16S Pipeline Explorer.md", "results.csv"] and res["personal_skipped"] == 2
    blob = "".join(p.read_text() for p in (vault.root / ".hive" / "orchestrator").glob("*.json"))
    assert "obgyn" not in blob and "plan.md" not in blob  # never stored by name
    assert o.scan()["new"] == 0  # unchanged files aren't re-proposed


def test_classify_then_file_copy_and_move(setup, vault):
    o, watch = setup
    o.scan()
    ps = {p["name"]: p for p in o.proposals()}
    seen_prompt = {}

    def fake_agent(prompt):
        seen_prompt["p"] = prompt
        return {"kind": "result", "text": json.dumps([
            {"id": ps["16S Pipeline Explorer.md"]["id"], "area": "Research", "home": None, "topic": "Genomics",
             "kind": "method", "summary": "16S method", "confidence": 0.9, "question": None},
            {"id": ps["results.csv"]["id"], "area": "Consulting", "home": "Acme Data Analysis",
             "topic": "Acme Data", "kind": "result", "summary": "diversity table", "confidence": 0.5,
             "question": {"text": "Is this Acme data?", "options": ["Yes", "No"]}}])}
    out = o.classify(Graph.build(vault.load_all()), fake_agent)
    assert out["classified"] == 2 and "DADA2 steps" in seen_prompt["p"] and "PRIVATE" not in seen_prompt["p"]
    ps = {p["name"]: p for p in o.proposals()}
    assert ps["results.csv"]["question"]["options"] == ["Yes", "No"]

    md = o.decide(ps["16S Pipeline Explorer.md"]["id"], "copy")
    note = vault.read(md["filed_to"])
    assert md["filed_to"] == "library/Research/Genomics/16S Pipeline Explorer.md"
    assert note.meta["area"] == "[[Research]]" and "pipeline" in note.tags and (watch / "16S Pipeline Explorer.md").exists()

    csv = o.decide(ps["results.csv"]["id"], "move")
    assert csv["filed_to"] == "documents/Consulting/Acme Data/results.csv" and not (watch / "results.csv").exists()
    stubs = list((vault.root / "library" / "Consulting" / "Acme Data").glob("*.md"))
    assert stubs and "[[Acme Data Analysis]]" in stubs[0].read_text(encoding="utf-8")


def test_agent_marks_personal_and_name_is_scrubbed(setup, vault):
    o, _ = setup
    o.scan()
    p = next(p for p in o.proposals() if p["name"] == "results.csv")
    o.apply_classification([{"id": p["id"], "area": "personal"}])
    q = next(x for x in o.proposals() if x["id"] == p["id"])
    assert q["status"] == "personal" and q["name"] == "(personal file)" and q["path"] == ""


def test_bad_area_and_missing_source_rejected(setup, vault):
    o, watch = setup
    o.scan()
    p = next(p for p in o.proposals() if p["name"] == "results.csv")
    with pytest.raises(ValueError):
        o.decide(p["id"], "copy", area="Nope")
    (watch / "results.csv").unlink()
    with pytest.raises(FileNotFoundError):
        o.decide(p["id"], "copy", area="Research", topic="x")


def test_medical_names_and_office_lock_files_skipped(vault, tmp_path):
    w = tmp_path / "Inbox"
    w.mkdir()
    for n in ("thyroid 09-Sep-2026.pdf", "MRI report.pdf", "~$draft.docx", "Project plan.docx"):
        (w / n).write_text("x")
    o = Orchestrator(vault)
    cfg = o.config()
    cfg["watch"] = [str(w)]
    o._save("config", cfg)
    res = o.scan()
    assert res["names"] == ["Project plan.docx"] and res["personal_skipped"] == 2


def test_bulk_files_only_confident_unquestioned(setup, vault):
    o, _ = setup
    o.scan()
    ps = {p["name"]: p for p in o.proposals()}
    o.apply_classification([
        {"id": ps["16S Pipeline Explorer.md"]["id"], "area": "Research", "topic": "Genomics", "confidence": 0.9},
        {"id": ps["results.csv"]["id"], "area": "Consulting", "topic": "Acme", "confidence": 0.95,
         "question": {"text": "Acme?", "options": ["Yes", "No"]}}])
    res = o.bulk(0.8)
    assert res == {"filed": 1, "errors": []}
    st = {p["name"]: p["status"] for p in o.proposals()}
    assert st == {"16S Pipeline Explorer.md": "filed", "results.csv": "proposed"}  # the one with a question waits


def test_cli_orchestrate_respects_lock_and_sync_runs_once(vault, monkeypatch):
    from hive import __main__ as cli
    from hive import pipeline
    lock = vault.root / ".hive" / "orchestrate.lock"
    lock.write_text("busy")
    assert "in progress" in cli.orchestrate(vault)["skipped"]
    calls = []
    monkeypatch.setattr(pipeline, "sync", lambda v, **k: calls.append(1) or {"steps": []})
    monkeypatch.setattr(cli, "load_settings", lambda: type("S", (), {"vault": vault.root})())
    assert cli.main(["sync"]) == 0 and calls == [1]


def test_toast_xml_escapes():
    x = toast_xml('A & "B"', "<b>", "http://127.0.0.1:8787/#orchestrator")
    assert "&amp;" in x and "&lt;b&gt;" in x and 'launch="http://127.0.0.1:8787/#orchestrator"' in x
