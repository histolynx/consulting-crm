"""Import a legislative session's enacted acts (one parsed JSON file per act) as a knowledge graph in the Ideas area.

Nodes: one `act` note per act, plus `legislator`, `committee` and `topic` hubs, all under
library/Ideas/<collection>/. Edges are typed by frontmatter key: senators, representatives, committees, topics.
Topics link to the collection's idea note, so a Lens on that note walks idea -> topics -> acts -> sponsors.
Acts do not link the idea note or the area directly: 1,000+ edges would make them the biggest hubs in the CRM graph.

Generated act/legislator/committee/topic notes are owned by the importer and rewritten when their content changes.
The idea note is written only if missing, so the owner's edits survive a re-run.
Sponsor bylines are re-parsed from the bill text ("By: Senator X" / "By: Representatives A, B,\\nC" / "By: House
Management"), because the parsed JSON keeps only the first line of a multi-line byline.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from .orchestrator import ensure_area_hubs
from .vault import Vault, render_note, slugify

ACT_TYPES = ("act", "legislator", "committee", "topic")

# Matched against the act's title, subtitle and popular name (the body is boilerplate-heavy: every act "declares an
# emergency" or names a fiscal year). Prefix matches on purpose: \bpollut catches pollution/polluter.
TOPICS: list[tuple[str, str]] = [
    ("Appropriations", r"\bappropriation"),
    ("Taxation", r"\btax"),
    ("Education", r"\beducat|\bschool|\bstudent|\buniversit|\bcollege|\bteacher|\btechnical institute"),
    ("Criminal law", r"\bcriminal|\bfelon|\bmisdemeanor|\boffense|\bsentenc"),
    ("Healthcare", r"\bhealth|\bmedic|\bhospital|\bphysician|\bnurs|\bpharmac|\bpatient|\btreatment|\blong-term care"),
    ("Insurance", r"\binsur"),
    ("Employment", r"\bemploy|\bwage|\blabor\b|\bworkers?\b"),
    ("Children and families", r"\bchild|\bminors?\b|\bjuvenile|\bfoster|\badopt"),
    ("Property", r"\bproperty|\breal estate|\bland\b"),
    ("Elections", r"\belection|\bvot(e|er|ing)|\bballot|\binitiative|\breferend|\bpetition"),
    ("Environment", r"\benviron|\bpollut|\bwildlife|\bwater\b|\bgame and fish|\bforest"),
    ("Firearms", r"\bfirearm|\bweapon|\bhandgun|\bguns?\b"),
    ("Reproductive health", r"\babortion|\bunborn|\bpregnan"),
    ("Transportation", r"\bvehicle|\bdriv(er|ing)|\btraffic|\bhighway|\broads?\b"),
    ("Drug policy", r"\bcannabis|\bmarijuana|\bcontrolled substance|\bdrug"),
    ("Housing", r"\bhousing|\btenant|\blandlord|\brental"),
    ("Corrections", r"\bprison|\bincarcerat|\bcorrection|\bprobation|\bparole|\binmate"),
    ("Banking and finance", r"\bbank|\bcredit|\bloan|\bfinancial institution|\bsecurities"),
    ("Agriculture", r"\bagricultur|\bfarm|\bcrop|\blivestock"),
    ("Military and veterans", r"\bmilitary|\bnational guard|\bveteran"),
    ("Public safety", r"\blaw enforcement|\bpolice|\bsheriff|\bpublic safety|\bfirefight"),
    ("Local government", r"\bcounty|\bcounties|\bmunicipal|\bcity\b|\bcities|\bzoning"),
    ("Courts and civil law", r"\bcourt|\bjudg|\bliabilit|\bcivil action|\bcivil procedure"),
    ("Government transparency", r"\bfreedom of information|\bpublic record|\bopen meeting|\btransparen"),
    ("Technology and data", r"\binternet|\bdigital|\bcyber|\btechnolog|\bdata\b|\bartificial intelligence|\bsocial media|\bonline"),
    ("Professional licensing", r"\blicens"),
    ("Energy and utilities", r"\benergy|\butilit|\belectric|\boil\b|\bnatural gas|\bbrine|\blithium"),
    ("Alcohol", r"\balcohol|\bliquor|\bbeer\b|\bwine"),
    ("State government", r"\bprocurement|\bcivil service|\bstate agenc|\bstate employee|\bfunds?\b"),
]
UNCATEGORIZED = "Uncategorized"


def parse_byline(full_text: str) -> dict[str, list[str]]:
    """Senators, representatives and committees from the bill's 'By:' lines (they wrap; a blank line ends them)."""
    head = full_text[: full_text.find("For An Act")] if "For An Act" in full_text else full_text[:3000]
    out: dict[str, list[str]] = {"senators": [], "representatives": [], "committees": []}
    for clause in re.findall(r"By:(.*?)(?=\n\s*By:|\n\s*\n|$)", head, re.S):
        text = re.sub(r"\s+", " ", clause).strip()
        m = re.match(r"(Senators?|Representatives?)\s+(.*)", text)
        if not m:
            if text and not re.search(r"\d|\*", text):
                out["committees"].append(text)
            continue
        key = "senators" if m.group(1).startswith("Senator") else "representatives"
        for name in re.split(r",|\band\b", m.group(2)):
            name = name.strip()
            if name and not re.search(r"\d|\*", name) and name not in out[key]:
                out[key].append(name)
    return out


def topics_for(act: dict[str, Any]) -> list[str]:
    text = " ".join(str(act.get(k) or "") for k in ("title", "subtitle", "popular_name")).lower()
    found = [label for label, pat in TOPICS if re.search(pat, text)]
    return found or [UNCATEGORIZED]


def iso_date(us: str) -> str | None:
    """'1/16/25' or '1/16/2025' -> '2025-01-16'; anything else -> None."""
    for fmt in ("%m/%d/%y", "%m/%d/%Y"):
        try:
            return dt.datetime.strptime(us.strip(), fmt).date().isoformat()
        except (ValueError, AttributeError):
            continue
    return None


def first_section_sentence(body: str) -> str:
    m = re.search(r"SECTION\s+1\.\s+(.+?)(?:\n\s*\n|$)", body or "", re.S)
    if not m:
        return ""
    s = re.sub(r"\s+", " ", m.group(1)).strip()
    end = s.find(".", 40)
    return s[: end + 1] if end != -1 else s[:400]


class ActsImport:
    def __init__(self, vault: Vault, parsed_dir: Path, pdf_dir: Path | None = None, state: str = "Arkansas",
                 abbr: str = "AR", year: int = 2025, session: str = "95th General Assembly, Regular Session 2025"):
        self.vault, self.parsed_dir, self.pdf_dir = vault, Path(parsed_dir), Path(pdf_dir) if pdf_dir else None
        self.state, self.abbr, self.year, self.session = state, abbr, year, session
        self.collection = f"{state} {year} Acts"
        self.base = f"library/Ideas/{self.collection}"

    # ---------- names (filenames are identities, so every hub carries the state to avoid colliding with CRM notes) ----------
    def act_name(self, n: int) -> str:
        return f"Act {n} of {self.year}"

    def legislator_name(self, name: str, chamber: str) -> str:
        return f"{'Sen.' if chamber == 'senators' else 'Rep.'} {name} ({self.abbr})"

    def committee_name(self, name: str) -> str:
        return f"{name} ({self.abbr})"

    def topic_name(self, label: str) -> str:
        return f"{label} ({self.abbr} acts)"

    # ---------- build ----------
    def load(self) -> list[dict[str, Any]]:
        acts = []
        for f in sorted(self.parsed_dir.glob("*.json")):
            acts.append(json.loads(f.read_text(encoding="utf-8")))
        if not acts:
            raise FileNotFoundError(f"no parsed act JSON files in {self.parsed_dir}")
        return sorted(acts, key=lambda a: int(a["act_number"]))

    def notes(self, acts: list[dict[str, Any]]) -> dict[str, tuple[dict[str, Any], str]]:
        """rel path -> (frontmatter, body) for every generated note except the idea note."""
        out: dict[str, tuple[dict[str, Any], str]] = {}
        sponsors: dict[str, Counter] = {"senators": Counter(), "representatives": Counter()}
        committees, topics = Counter(), Counter()
        link = lambda name: f"[[{name}]]"  # noqa: E731
        for a in acts:
            n = int(a["act_number"])
            by = parse_byline(a.get("full_text") or "")
            tps = topics_for(a)
            for k in sponsors:
                sponsors[k].update(by[k])
            committees.update(by["committees"])
            topics.update(tps)
            meta: dict[str, Any] = {
                "type": "act", "act": n, "bill": a.get("bill_number"), "chamber": a.get("chamber"),
                "approved": iso_date(a.get("approved_date") or ""), "session": self.session,
                "senators": [link(self.legislator_name(s, "senators")) for s in by["senators"]],
                "representatives": [link(self.legislator_name(r, "representatives")) for r in by["representatives"]],
                "committees": [link(self.committee_name(c)) for c in by["committees"]],
                "topics": [link(self.topic_name(t)) for t in tps],
                "aliases": [f"{self.year} {a.get('bill_number')}"] if a.get("bill_number") else [],
            }
            pdf = self.pdf_dir / f"ACT{n:04d}.pdf" if self.pdf_dir else None
            if pdf and pdf.exists():
                meta["pdf"] = str(pdf)
            meta = {k: v for k, v in meta.items() if v not in (None, "", [])}
            body = [f"# {self.act_name(n)} ({a.get('bill_number', '')})", "", f"**{(a.get('title') or '').strip()}**", ""]
            if (a.get("popular_name") or "").strip():
                body += [f"> Popular name: {a['popular_name'].strip()}", ""]
            sub = (a.get("subtitle") or "").strip()
            if sub and sub.upper() != (a.get("title") or "").strip().upper():
                body += [f"Subtitle: {sub}", ""]
            if s1 := first_section_sentence(a.get("body_text") or ""):
                body += [f"Section 1: {s1}", ""]
            if not meta.get("approved"):
                body += ["> [!question] Approval date missing from the parsed bill text.", ""]
            if "pdf" in meta:
                body += [f"[Open the act PDF]({pdf.as_uri()})", ""]
            out[f"{self.base}/acts/{self.act_name(n)}.md"] = (meta, "\n".join(body))

        for chamber, counts in sponsors.items():
            house = "Senate" if chamber == "senators" else "House of Representatives"
            for name, c in counts.items():
                title = self.legislator_name(name, chamber)
                out[f"{self.base}/legislators/{slugify(title)}.md"] = (
                    {"type": "legislator", "name": name, "chamber": house, "state": self.state, "acts": c},
                    f"# {title}\n\n{self.state} {house}, {self.session}. Named in the byline of {c} enacted act(s); "
                    f"see backlinks. The name is as printed on the bill (usually a surname, sometimes with an initial).\n")
        for name, c in committees.items():
            title = self.committee_name(name)
            out[f"{self.base}/committees/{slugify(title)}.md"] = (
                {"type": "committee", "name": name, "state": self.state, "acts": c},
                f"# {title}\n\nSponsoring committee for {c} enacted act(s) in the {self.session}; see backlinks.\n")
        patterns = dict(TOPICS)
        for label, c in topics.items():
            title = self.topic_name(label)
            rule = (f"title matches `{patterns[label]}`" if label in patterns else "no topic keyword matched the title")
            out[f"{self.base}/topics/{slugify(title)}.md"] = (
                {"type": "topic", "collection": link(self.collection), "acts": c},
                f"# {title}\n\n{c} act(s) of the {self.session} where the {rule}. Topics are keyword matches on the "
                f"title and subtitle, not a legal classification; an act can carry several.\n")
        return out

    def idea_note(self, acts: list[dict[str, Any]], generated: dict[str, tuple[dict[str, Any], str]],
                  project_dir: Path | None) -> tuple[dict[str, Any], str]:
        count = lambda t: sum(1 for m, _ in generated.values() if m["type"] == t)  # noqa: E731
        top = lambda t, k=8: sorted(((m["acts"], p) for p, (m, _) in generated.items() if m["type"] == t), reverse=True)[:k]  # noqa: E731
        stem = lambda p: Path(p).stem  # noqa: E731
        rows = []
        if project_dir and project_dir.exists():
            rows.append(f"| Project folder | `{project_dir}` |")
            for child in sorted(project_dir.iterdir()):
                if child.name.startswith((".", "__")):
                    continue
                what = (f"{sum(1 for _ in child.iterdir())} items" if child.is_dir() else "script" if child.suffix == ".py" else "file")
                rows.append(f"| {child.name}{'/' if child.is_dir() else ''} | `{child}` ({what}) |")
        else:
            rows += [f"| Parsed JSON | `{self.parsed_dir}` |"] + ([f"| Act PDFs | `{self.pdf_dir}` |"] if self.pdf_dir else [])
        missing = [int(a["act_number"]) for a in acts if not iso_date(a.get("approved_date") or "")]
        meta = {"type": "note", "area": "[[Ideas]]", "topic": self.collection, "kind": "reference",
                "source": str(project_dir or self.parsed_dir), "imported": dt.date.today().isoformat(),
                "tags": ["idea", "dataset", "legislation"]}
        body = "\n".join([
            f"# {self.collection}", "",
            f"Every act enacted in the {self.state} {self.session} ({len(acts)} acts), downloaded as PDFs, parsed to "
            "JSON, and imported here as a knowledge graph. Start from this note's Lens in the Graph view.", "",
            "## Where the files are", "", "| What | Location |", "|---|---|", *rows, "",
            "## The graph", "",
            f"- {count('act')} `act` notes in `acts/`: bill, chamber of origin, approval date, sponsors, topics, PDF link.",
            f"- {count('legislator')} `legislator` notes, {count('committee')} `committee` notes, {count('topic')} `topic` notes.",
            "- Edges: `senators`, `representatives`, `committees`, `topics` (act to hub); topic notes link back here as `collection`.",
            f"- Rebuild after re-parsing: `python -m hive acts \"{self.parsed_dir}\"` (rewrites generated notes, never this one).", "",
            "## Biggest hubs", "",
            "Topics: " + ", ".join(f"[[{stem(p)}]] ({c})" for c, p in top("topic")), "",
            "Sponsors: " + ", ".join(f"[[{stem(p)}]] ({c})" for c, p in top("legislator")), "",
            "## Caveats", "",
            "- Sponsor names are as printed on the bill (mostly surnames), so two legislators sharing a printed name would merge.",
            "- Topics are keyword matches on titles, not a legal classification.",
            f"- Acts with no parsed approval date: {', '.join(map(str, missing)) or 'none'}.",
            "",
            "## Ideas to explore", "",
            "- Ask HIVE which topics or sponsors overlap with consulting or Research work.",
            "- Co-sponsorship network: which legislators appear together most often.",
            "- Track the 2027 session the same way and diff topics between sessions.", "",
        ])
        return meta, body

    # ---------- write ----------
    def run(self, project_dir: Path | None = None) -> dict[str, Any]:
        acts = self.load()
        ensure_area_hubs(self.vault)
        generated = self.notes(acts)
        written = unchanged = 0
        for rel, (meta, body) in generated.items():
            p = self.vault.safe_path(rel)
            text = render_note(meta, body)
            if p.exists() and p.read_text(encoding="utf-8") == text:
                unchanged += 1
                continue
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
            written += 1
        idea_rel = f"{self.base}/{self.collection}.md"
        idea_created = not self.vault.safe_path(idea_rel).exists()
        if idea_created:
            meta, body = self.idea_note(acts, generated, project_dir)
            self.vault.safe_path(idea_rel).write_text(render_note(meta, body), encoding="utf-8")
        by_type = Counter(m["type"] for m, _ in generated.values())
        out = {"acts": len(acts), "written": written, "unchanged": unchanged, "idea_note": idea_rel,
               "idea_created": idea_created, "by_type": dict(by_type)}
        self.vault.audit("acts-import", "import", self.base, **{k: v for k, v in out.items() if k != "idea_note"})
        return out
