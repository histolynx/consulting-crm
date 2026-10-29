"""HIVE Orchestrator, phase 1: watch work folders → classify → propose filing → owner approves → file into the graph.

Privacy rules (enforced here, not left to the model):
  * Personal files are filtered by NAME/FOLDER ONLY, before any content is read. They are never stored by name:
    the state keeps only a salted hash so they aren't re-examined, and stats count them.
  * Only small excerpts of plain-text work files go to the agent; PDFs/Office files are classified by name alone.
  * Nothing is moved, copied or deleted without an explicit approve. Approve = copy by default (originals stay).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import secrets
import shutil
from pathlib import Path
from typing import Any

from .graph import Graph
from .vault import Vault, slugify, split_frontmatter

AREAS = ["Consulting", "Committee of 100", "Yale", "MSU", "Research", "Career"]
WORK_EXT = {".md", ".txt", ".pdf", ".docx", ".doc", ".pptx", ".xlsx", ".csv", ".ipynb", ".py", ".r", ".rmd", ".qmd", ".json",
            ".yaml", ".yml", ".sh", ".tex", ".bib"}
TEXT_EXT = {".md", ".txt", ".csv", ".ipynb", ".py", ".r", ".rmd", ".qmd", ".json", ".yaml", ".yml", ".sh", ".tex", ".bib"}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".cache", "$recycle.bin", "appdata"}
PERSONAL = re.compile(
    r"(obgyn|ob-gyn|gyn|thyroid|endocrin|cardiolog|dermatolog|radiolog|mri|x-?ray|ultrasound|mammogra|bloodwork|blood[_ -]?test|biopsy|vaccin|immuniz|covid[_ -]?test|patient[_ -]?portal|appointment|clinic|hospital[_ -]?bill|explanation[_ -]?of[_ -]?benefits|pediatric[ -]?visit|visit[_ -]?summary|medical|doctor|dentist|prescription|pharmacy|lab[_ -]?results?|"
    r"health[_ -]?record|therapy|insurance[_ -]?(card|claim|eob)|\beob\b|tax(es)?[_ -]?\d{4}|\bw-?2\b|\b1099\b|1040|bank|statement|"
    r"mortgage|lease|rent[_ -]?receipt|passport|birth[_ -]?cert|driver'?s?[_ -]?licen[cs]e|ssn|social[_ -]?security|family|kids?|"
    r"wedding|vacation|recipe|personal|private|diary|journal)", re.I)
MAX_EXCERPT = 1500
MAX_DEPTH = 3


class Orchestrator:
    def __init__(self, vault: Vault):
        self.vault = vault
        self.dir = vault.root / ".hive" / "orchestrator"
        self.dir.mkdir(parents=True, exist_ok=True)

    # ---------- persistent state ----------
    def _load(self, name: str, default: Any) -> Any:
        f = self.dir / f"{name}.json"
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else default

    def _save(self, name: str, data: Any) -> None:
        (self.dir / f"{name}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")

    def config(self) -> dict[str, Any]:
        home = Path.home()
        cfg = self._load("config", {})
        cfg.setdefault("watch", [str(home / "Downloads"), str(home / "Desktop")])
        cfg.setdefault("exclude", [str(self.vault.root)])
        cfg.setdefault("salt", secrets.token_hex(8))
        self._save("config", cfg)
        return cfg

    def proposals(self) -> list[dict[str, Any]]:
        return self._load("proposals", [])

    def _set_proposals(self, ps: list[dict[str, Any]]) -> None:
        self._save("proposals", ps)

    # ---------- scanning (no AI, no content reads) ----------
    @staticmethod
    def is_personal(path: Path, root: Path | None = None) -> bool:
        """Name/folder-only test. Only folders INSIDE the watched root count (a parent like "Personal Projects"
        above the watch root must not hide everything)."""
        inner = path.parent.relative_to(root).parts if root and root in path.parents else path.parent.parts[-1:]
        return bool(PERSONAL.search(path.name) or any(PERSONAL.search(p) for p in inner))

    def _key(self, path: Path, salt: str) -> str:
        return hashlib.sha256(f"{salt}|{path}".lower().encode()).hexdigest()[:20]

    def scan(self) -> dict[str, Any]:
        cfg = self.config()
        seen: dict[str, Any] = self._load("seen", {})
        excludes = [Path(x).resolve() for x in cfg["exclude"]]
        ps = self.proposals()
        known = {p["key"] for p in ps}
        new, personal = [], 0
        for root in cfg["watch"]:
            base = Path(root)
            if not base.exists():
                continue
            for dirpath, dirnames, filenames in os.walk(base):
                d = Path(dirpath)
                depth = len(d.relative_to(base).parts)
                dirnames[:] = [x for x in dirnames if x.lower() not in SKIP_DIRS and not x.startswith(".") and depth < MAX_DEPTH
                               and not any((d / x).resolve() == e or e in (d / x).resolve().parents for e in excludes)]
                for fn in filenames:
                    p = d / fn
                    if p.suffix.lower() not in WORK_EXT or fn.startswith("~$"):  # ~$ = Office lock/temp files
                        continue
                    key = self._key(p, cfg["salt"])
                    try:
                        st = p.stat()
                    except OSError:
                        continue
                    sig = f"{int(st.st_mtime)}:{st.st_size}"
                    if seen.get(key) == sig:
                        continue
                    seen[key] = sig
                    if self.is_personal(p, base):
                        personal += 1  # counted, never recorded by name
                        continue
                    if key in known:
                        continue
                    new.append({"id": "p_" + secrets.token_hex(4), "key": key, "path": str(p), "name": p.name,
                                "ext": p.suffix.lower(), "size": st.st_size,
                                "modified": dt.datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
                                "found": dt.datetime.now().isoformat(timespec="seconds"), "status": "new"})
        self._save("seen", seen)
        if new:
            self._set_proposals(ps + new)
        stats = self._load("stats", {"personal_skipped": 0})
        stats["personal_skipped"] = stats.get("personal_skipped", 0) + personal
        stats["last_scan"] = dt.datetime.now().isoformat(timespec="seconds")
        self._save("stats", stats)
        return {"new": len(new), "personal_skipped": personal, "names": [n["name"] for n in new]}

    # ---------- classification (agent) ----------
    def excerpt(self, p: dict[str, Any]) -> str:
        if p["ext"] not in TEXT_EXT:
            return ""
        try:
            return Path(p["path"]).read_text(encoding="utf-8", errors="replace")[:MAX_EXCERPT]
        except OSError:
            return ""

    def build_prompt(self, batch: list[dict[str, Any]], graph: Graph) -> str:
        homes = sorted(n.title for n in graph.notes.values() if n.type in ("contract", "project", "opportunity"))
        items = [{"id": p["id"], "name": p["name"], "folder": str(Path(p["path"]).parent.name), "excerpt": self.excerpt(p)} for p in batch]
        return (
            "Classify each file the owner's computer produced into the HIVE knowledge graph. Areas: " + ", ".join(AREAS) + ".\n"
            "Rules: methods/reusable technical knowledge go to the Research area under a topic; client deliverables, data and results "
            "stay with the client's project in Consulting. Job-search material (resumes, cover letters, applications) is Career. "
            "Committee of 100, Yale and MSU are volunteer areas. If a file looks personal (health, family, finances), set area to "
            "'personal' and say nothing else about it. If unsure, set confidence below 0.6 and add a question with 2-4 options.\n"
            f"Existing homes (contracts/projects/opportunities): {json.dumps(homes)}\n"
            f"Files: {json.dumps(items)}\n"
            "Reply with ONLY a JSON array, one object per file: "
            '{"id": ..., "area": ..., "home": "<existing home title or null>", "topic": "<short folder name>", '
            '"kind": "method|result|deliverable|reference|career|admin", "summary": "<one sentence>", "confidence": 0-1, '
            '"question": null | {"text": ..., "options": [..]}}'
        )

    @staticmethod
    def parse_reply(text: str) -> list[dict[str, Any]]:
        m = re.search(r"\[.*\]", text, re.S)
        if not m:
            raise ValueError("agent reply had no JSON array")
        data = json.loads(m.group(0))
        if not isinstance(data, list):
            raise ValueError("agent reply JSON is not a list")
        return data

    def apply_classification(self, results: list[dict[str, Any]]) -> int:
        ps = self.proposals()
        by_id = {p["id"]: p for p in ps}
        n = 0
        for r in results:
            p = by_id.get(r.get("id"))
            if not p or p["status"] != "new":
                continue
            if str(r.get("area", "")).lower() == "personal":
                p.update(status="personal", name="(personal file)", path="", suggestion=None)  # scrub the name
                continue
            area = r.get("area") if r.get("area") in AREAS else "Consulting"
            p["suggestion"] = {"area": area, "home": r.get("home"), "topic": slugify(r.get("topic") or "General"),
                               "kind": r.get("kind"), "summary": r.get("summary"), "confidence": float(r.get("confidence") or 0)}
            q = r.get("question")
            if isinstance(q, dict) and q.get("text") and q.get("options"):
                p["question"] = {"text": str(q["text"]), "options": [str(o) for o in q["options"]][:4]}
            p["status"] = "proposed"
            n += 1
        self._set_proposals(ps)
        return n

    def classify(self, graph: Graph, agent_run, batch_size: int = 15) -> dict[str, Any]:
        pending = [p for p in self.proposals() if p["status"] == "new"]
        done = 0
        for i in range(0, len(pending), batch_size):
            batch = pending[i:i + batch_size]
            res = agent_run(self.build_prompt(batch, graph))
            if res.get("kind") == "error":
                raise RuntimeError(f"classification failed: {res.get('text')}")
            done += self.apply_classification(self.parse_reply(res.get("text") or ""))
        return {"classified": done, "pending": len(pending)}

    # ---------- owner decisions ----------
    def decide(self, pid: str, action: str, area: str | None = None, topic: str | None = None,
               home: str | None = None, answer: str | None = None) -> dict[str, Any]:
        ps = self.proposals()
        p = next((x for x in ps if x["id"] == pid), None)
        if not p:
            raise KeyError(pid)
        if action == "answer":
            p.setdefault("answers", []).append({"q": (p.get("question") or {}).get("text"), "a": answer})
            p.pop("question", None)
            self._set_proposals(ps)
            return p
        if action == "reject":
            p["status"] = "rejected"
            p["decided"] = dt.datetime.now().isoformat(timespec="seconds")
            self._set_proposals(ps)
            self.vault.audit("orchestrator", "reject", p["name"])
            return p
        if action not in ("copy", "move"):
            raise ValueError("action must be copy, move, reject or answer")
        s = dict(p.get("suggestion") or {})
        if area:
            s["area"] = area
        if topic:
            s["topic"] = slugify(topic)
        if home is not None:
            s["home"] = home or None
        if s.get("area") not in AREAS:
            raise ValueError(f"area must be one of {AREAS}")
        src = Path(p["path"])
        if not src.exists():
            raise FileNotFoundError(f"source no longer exists: {src}")
        rel = self._file_into_vault(src, s, p)
        if action == "move":
            src.unlink()  # only after a successful copy into the vault; never for anything else
        p.update(status="filed", filed_to=rel, method=action, suggestion=s,
                 decided=dt.datetime.now().isoformat(timespec="seconds"))
        self._set_proposals(ps)
        self.vault.audit("orchestrator", f"file-{action}", rel, source=str(src))
        return p

    def _file_into_vault(self, src: Path, s: dict[str, Any], p: dict[str, Any]) -> str:
        area_dir, topic = slugify(s["area"]), s.get("topic") or "General"
        today = dt.date.today().isoformat()
        if src.suffix.lower() == ".md":
            rel = self.vault.unique_path(f"library/{area_dir}/{topic}", src.stem)
            meta, body = split_frontmatter(src.read_text(encoding="utf-8", errors="replace"))
            meta = {"type": "note", **{k: v for k, v in meta.items() if k != "type"}, "area": f"[[{s['area']}]]",
                    "topic": topic, "kind": s.get("kind"), "source": str(src), "imported": today}
            if s.get("home"):
                meta["project"] = f"[[{s['home']}]]"
            meta["tags"] = sorted(set((meta.get("tags") or []) + ["imported", slugify(s["area"]).lower().replace(" ", "-")]))
            meta = {k: v for k, v in meta.items() if v not in (None, "")}
            self.vault.write(rel, meta, body, actor="orchestrator", action="import-note")
            return rel
        rel = f"documents/{area_dir}/{topic}/{src.name}"
        dest = self.vault.safe_path(rel)
        if dest.exists():
            dest = dest.with_name(f"{dest.stem} ({today}){dest.suffix}")
            rel = dest.relative_to(self.vault.root).as_posix()
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        stub = self.vault.unique_path(f"library/{area_dir}/{topic}", f"{src.stem} (file)")
        meta = {"type": "note", "area": f"[[{s['area']}]]", "topic": topic, "kind": s.get("kind"), "file": rel,
                "source": str(src), "imported": today, "tags": ["imported", "file"]}
        if s.get("home"):
            meta["project"] = f"[[{s['home']}]]"
        body = f"# {src.name}\n\n{s.get('summary') or ''}\n\n[Open the file](../../../{rel.replace(' ', '%20')})\n"
        self.vault.write(stub, {k: v for k, v in meta.items() if v not in (None, "")}, body, actor="orchestrator", action="import-file")
        return rel

    def bulk(self, min_confidence: float = 0.8, area: str | None = None, action: str = "copy") -> dict[str, Any]:
        """File every confident proposal (no open question) in one go; optional area filter. Errors are reported, not hidden."""
        done, errors = [], []
        for p in [x for x in self.proposals() if x["status"] == "proposed"]:
            s = p.get("suggestion") or {}
            if p.get("question") or float(s.get("confidence") or 0) < min_confidence or (area and s.get("area") != area):
                continue
            try:
                done.append(self.decide(p["id"], action)["filed_to"])
            except (ValueError, FileNotFoundError, OSError) as e:
                errors.append(f"{p['name']}: {e}")
        return {"filed": len(done), "errors": errors}

    def summary(self) -> dict[str, Any]:
        ps = self.proposals()
        visible = [p for p in ps if p["status"] in ("new", "proposed")]
        return {"open": visible, "recent": [p for p in ps if p["status"] in ("filed", "rejected")][-15:][::-1],
                "stats": {**self._load("stats", {}), "open": len(visible),
                          "personal_skipped": self._load("stats", {}).get("personal_skipped", 0) + sum(p["status"] == "personal" for p in ps),
                          "filed": sum(p["status"] == "filed" for p in ps)},
                "config": {k: v for k, v in self.config().items() if k != "salt"}, "areas": AREAS}


def ensure_area_hubs(vault: Vault) -> list[str]:
    made = []
    blurbs = {"Consulting": "Client consulting work: contracts, projects, deliverables.",
              "Committee of 100": "Volunteer work with the Committee of 100.", "Yale": "Volunteer work with Yale.",
              "MSU": "Volunteer work with MSU.", "Research": "Reusable methods and knowledge, e.g. genomics pipelines.",
              "Career": "Job search: applications, resumes, cover letters, interviews."}
    for a in AREAS:
        rel = f"areas/{a}.md"
        if not (vault.root / rel).exists():
            vault.write(rel, {"type": "area", "tags": ["area"]}, f"# {a}\n\n{blurbs[a]}\n", actor="orchestrator", action="area-hub")
            made.append(rel)
    return made

