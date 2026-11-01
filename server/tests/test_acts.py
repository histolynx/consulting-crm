import json
from pathlib import Path

import pytest

from hive.acts import ActsImport, iso_date, parse_byline, topics_for
from hive.graph import Graph
from hive.orchestrator import AREAS

HEAD = "Act {n} of the Regular Session\nState of Acmeland\n\n{by}\n\nFor An Act To Be Entitled\n\n{title}\n"


def act(n, by, title, subtitle="", approved="2/18/25", body="SECTION 1. The law concerning widgets is amended to add a new rule. More."):
    return {"act_number": n, "bill_number": f"SB{n}", "chamber": "Senate", "title": title, "subtitle": subtitle,
            "popular_name": "", "approved_date": approved, "body_text": body, "senators": [], "representatives": [],
            "committees": [], "full_text": HEAD.format(n=n, by=by, title=title)}


@pytest.fixture
def parsed(tmp_path: Path) -> Path:
    d = tmp_path / "law" / "parsed_acts"
    d.mkdir(parents=True)
    acts = [
        act(1, "By: Joint Budget Committee", "AN ACT TO MAKE AN APPROPRIATION FOR THE DEPARTMENT OF EDUCATION"),
        act(2, "By: Senator J. Doe\nBy: Representatives Roe, K.\nSmith, Beaty Jr.", "AN ACT CONCERNING FIREARM SAFETY", approved=""),
        act(3, "By: Representative Roe\nBy: Senator J. Doe", "AN ACT TO RENAME A BRIDGE"),
    ]
    for a in acts:
        (d / f"ACT{a['act_number']:04d}.json").write_text(json.dumps(a), encoding="utf-8")
    pdfs = tmp_path / "law" / "raw_pdfs"
    pdfs.mkdir()
    (pdfs / "ACT0001.pdf").write_bytes(b"%PDF")
    return d


def test_byline_joins_wrapped_names_and_reads_committees():
    by = parse_byline(HEAD.format(n=2, by="By: Senator J. Doe\nBy: Representatives Roe, K.\nSmith, Beaty Jr.", title="X"))
    assert by == {"senators": ["J. Doe"], "representatives": ["Roe", "K. Smith", "Beaty Jr."], "committees": []}
    assert parse_byline(HEAD.format(n=1, by="By: House Management", title="X"))["committees"] == ["House Management"]
    assert parse_byline("no byline here") == {"senators": [], "representatives": [], "committees": []}


def test_topics_and_dates():
    assert topics_for({"title": "AN ACT TO AMEND THE LAW CONCERNING POLLUTION OF STATE WATERS"}) == ["Environment"]
    assert set(topics_for({"title": "AN APPROPRIATION FOR PUBLIC SCHOOL FUNDING"})) == {"Appropriations", "Education"}
    assert topics_for({"title": "AN ACT TO RENAME A BRIDGE"}) == ["Uncategorized"]
    assert iso_date("1/16/25") == "2025-01-16" and iso_date("12/1/2025") == "2025-12-01" and iso_date("") is None


def test_import_builds_typed_graph(vault, parsed):
    out = ActsImport(vault, parsed, parsed.parent / "raw_pdfs", state="Acmeland", abbr="AC").run(parsed.parent)
    assert out["acts"] == 3 and out["idea_created"]
    assert out["by_type"] == {"act": 3, "legislator": 4, "committee": 1, "topic": 4}
    assert "Ideas" in AREAS and (vault.root / "areas" / "Ideas.md").exists()

    base = "library/Ideas/Acmeland 2025 Acts"
    a2 = vault.read(f"{base}/acts/Act 2 of 2025.md")
    assert a2.type == "act" and a2.meta["senators"] == ["[[Sen. J. Doe (AC)]]"]
    assert a2.meta["representatives"] == ["[[Rep. Roe (AC)]]", "[[Rep. K. Smith (AC)]]", "[[Rep. Beaty Jr. (AC)]]"]
    assert "approved" not in a2.meta and "[!question]" in a2.body
    a1 = vault.read(f"{base}/acts/Act 1 of 2025.md")
    assert a1.meta["approved"] == "2025-02-18" and a1.meta["pdf"].endswith("ACT0001.pdf")
    assert a1.meta["committees"] == ["[[Joint Budget Committee (AC)]]"]

    g = Graph.build(vault.load_all())
    roe = g.resolve("Rep. Roe (AC)")
    sponsored = {e["source"] for e in g.backlinks(roe) if e["label"] == "representatives"}
    assert sponsored == {f"{base}/acts/Act 2 of 2025.md", f"{base}/acts/Act 3 of 2025.md"}
    idea = g.resolve("Acmeland 2025 Acts")
    assert idea == f"{base}/Acmeland 2025 Acts.md"
    assert any(e["target"] == "areas/Ideas.md" and e["label"] == "area" for e in g.outlinks(idea))
    lens = g.ego(idea, depth=3)
    assert g.resolve("Act 2 of 2025") in lens and roe in lens            # idea -> topic -> act -> legislator
    assert not any(n["type"] == "ghost" for n in g.nodes.values())        # every generated link resolves

    note = vault.read(f"{base}/Acmeland 2025 Acts.md")
    assert str(parsed) in note.body and "raw_pdfs" in note.body and "Acts with no parsed approval date: 2" in note.body


def test_ideas_listing_and_add(vault, parsed):
    from hive.ideas import add_idea, ideas
    ActsImport(vault, parsed, state="Acmeland", abbr="AC").run(parsed.parent)
    vault.write("knowledge/Unrelated.md", {"type": "note", "area": "[[Research]]"}, "# Unrelated\n")
    rel = add_idea(vault, "Side hustle", "A small idea.\n\n## Use\nSomething.", tags=["#MCP", "womens health"])
    assert rel == "library/Ideas/Side hustle/Side hustle.md"
    assert add_idea(vault, "Side hustle", "again") == "library/Ideas/Side hustle/Side hustle 2.md"   # never overwrites
    with pytest.raises(ValueError):
        add_idea(vault, "", "  ")
    n = vault.read(rel)
    assert n.meta["area"] == "[[Ideas]]" and n.meta["tags"] == ["idea", "mcp", "womens-health"]

    out = {i["path"]: i for i in ideas(Graph.build(vault.load_all()))}
    assert set(out) == {"library/Ideas/Acmeland 2025 Acts/Acmeland 2025 Acts.md", rel, "library/Ideas/Side hustle/Side hustle 2.md"}
    acts = out["library/Ideas/Acmeland 2025 Acts/Acmeland 2025 Acts.md"]
    assert acts["counts"] == {"act": 3, "legislator": 4, "committee": 1, "topic": 4}
    assert acts["source"] == str(parsed.parent) and acts["summary"].startswith("Every act enacted")
    assert acts["topics"][0]["count"] >= acts["topics"][-1]["count"]
    assert out[rel]["summary"] == "A small idea." and out[rel]["status"] == "idea"


def test_rerun_is_idempotent_and_keeps_idea_edits(vault, parsed):
    imp = ActsImport(vault, parsed, state="Acmeland", abbr="AC")
    imp.run()
    idea = vault.root / "library/Ideas/Acmeland 2025 Acts/Acmeland 2025 Acts.md"
    idea.write_text(idea.read_text(encoding="utf-8") + "\nMy own notes.\n", encoding="utf-8")
    out = imp.run()
    assert out["written"] == 0 and out["unchanged"] == 12 and not out["idea_created"]
    assert "My own notes." in idea.read_text(encoding="utf-8")


def test_empty_folder_is_an_error(vault, tmp_path):
    with pytest.raises(FileNotFoundError):
        ActsImport(vault, tmp_path).run()
