"""Folder cleanup: the AI proposes, a deterministic executor applies only what the owner ticks, and every run can be undone.

Plan categories (per file, in one watched folder such as Downloads):
  processed  - already copied into HIVE              → <folder>/Processed/
  organize   - work file with a confident area/topic → <drive_root>/<Area>/<Topic>/
  duplicate  - byte-identical copy of another file    → <folder>/_HIVE_Holding/<date>/   (newest copy is kept)
  ask        - unsure; left in place until decided
Personal files (by name/folder) are never listed, read or moved. Nothing is ever deleted: the holding folder is
emptied only when the owner explicitly asks.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import secrets
import shutil
from pathlib import Path
from typing import Any

from .orchestrator import AREAS, SKIP_DIRS, Orchestrator
from .vault import Vault, slugify

PROCESSED, HOLDING = "Processed", "_HIVE_Holding"
COPY_SUFFIX = re.compile(r"\s*\(\d+\)$")


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _free(dest: Path) -> Path:
    """Never overwrite: 'name.ext' → 'name (2).ext' …"""
    if not dest.exists():
        return dest
    n = 2
    while True:
        c = dest.with_name(f"{dest.stem} ({n}){dest.suffix}")
        if not c.exists():
            return c
        n += 1


class Cleanup:
    def __init__(self, vault: Vault):
        self.vault = vault
        self.orch = Orchestrator(vault)
        self.dir = vault.root / ".hive" / "cleanup"
        self.dir.mkdir(parents=True, exist_ok=True)

    def drive_root(self) -> Path:
        cfg = self.orch.config()
        if not cfg.get("drive_root"):
            cfg["drive_root"] = str(Path("G:/My Drive/Work"))
            self.orch._save("config", cfg)
        return Path(cfg["drive_root"])

    # ---------- planning (read-only) ----------
    def plan(self, folder: str, max_depth: int = 1) -> dict[str, Any]:
        base = Path(folder)
        if not base.is_dir():
            raise ValueError(f"not a folder: {folder}")
        props = {str(Path(p["path"])).lower(): p for p in self.orch.proposals() if p.get("path")}
        files, personal = [], 0
        for p in base.rglob("*"):
            rel = p.relative_to(base)
            if not p.is_file() or len(rel.parts) > max_depth + 1:
                continue
            if rel.parts[0] in (PROCESSED, HOLDING) or any(x.lower() in SKIP_DIRS or x.startswith(".") for x in rel.parts[:-1]):
                continue
            if p.name.startswith("~$"):
                continue
            if Orchestrator.is_personal(p, base):
                personal += 1  # never listed
                continue
            files.append(p)

        ops: list[dict[str, Any]] = []
        today = dt.date.today().isoformat()
        # exact duplicates: group by size, then hash; keep the newest, prefer names without " (1)"
        by_size: dict[int, list[Path]] = {}
        for p in files:
            by_size.setdefault(p.stat().st_size, []).append(p)
        dup_of: dict[Path, Path] = {}
        for group in (g for g in by_size.values() if len(g) > 1):
            by_hash: dict[str, list[Path]] = {}
            for p in group:
                by_hash.setdefault(_sha256(p), []).append(p)
            for same in (h for h in by_hash.values() if len(h) > 1):
                keep = sorted(same, key=lambda x: (bool(COPY_SUFFIX.search(x.stem)), -x.stat().st_mtime))[0]
                for p in same:
                    if p != keep:
                        dup_of[p] = keep
        drive = self.drive_root()
        for p in files:
            prop = props.get(str(p).lower())
            if p in dup_of:
                ops.append(self._op(p, base / HOLDING / today / p.name, "duplicate", f"exact copy of {dup_of[p].name}"))
            elif prop and prop.get("status") == "filed":
                ops.append(self._op(p, base / PROCESSED / p.name, "processed", f"copied into HIVE: {prop.get('filed_to')}"))
            elif prop and prop.get("status") == "proposed" and not prop.get("question") \
                    and float((prop.get("suggestion") or {}).get("confidence") or 0) >= 0.6:
                s = prop["suggestion"]
                area = s["area"] if s.get("area") in AREAS else "Consulting"
                ops.append(self._op(p, drive / area / slugify(s.get("topic") or "General") / p.name, "organize",
                                    f"{area} / {s.get('topic')}: {s.get('summary') or ''}".strip()))
            else:
                why = "needs your decision in Orchestrator" if prop else "not classified yet (run a scan)"
                ops.append(self._op(p, None, "ask", why))
        plan = {"id": "c_" + secrets.token_hex(4), "folder": str(base), "created": dt.datetime.now().isoformat(timespec="seconds"),
                "personal_skipped": personal, "ops": ops,
                "counts": {k: sum(o["kind"] == k for o in ops) for k in ("processed", "organize", "duplicate", "ask")}}
        (self.dir / f"{plan['id']}-plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
        return plan

    @staticmethod
    def _op(src: Path, dst: Path | None, kind: str, why: str) -> dict[str, Any]:
        return {"id": "o_" + secrets.token_hex(3), "kind": kind, "src": str(src), "dst": str(dst) if dst else None,
                "name": src.name, "why": why}

    # ---------- execution (deterministic) ----------
    def apply(self, plan_id: str, op_ids: list[str]) -> dict[str, Any]:
        pf = self.dir / f"{plan_id}-plan.json"
        if not pf.exists():
            raise KeyError(plan_id)
        plan = json.loads(pf.read_text(encoding="utf-8"))
        chosen = [o for o in plan["ops"] if o["id"] in set(op_ids) and o["dst"]]
        moved, errors = [], []
        for o in chosen:
            src, dst = Path(o["src"]), Path(o["dst"])
            try:
                if not src.exists():
                    raise FileNotFoundError("source is gone")
                dst = _free(dst)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                moved.append({"src": str(src), "dst": str(dst), "kind": o["kind"]})
            except (OSError, shutil.Error) as e:
                errors.append(f"{o['name']}: {e}")
        run = {"plan": plan_id, "applied": dt.datetime.now().isoformat(timespec="seconds"), "moved": moved, "errors": errors,
               "undone": False}
        (self.dir / f"{plan_id}-run.json").write_text(json.dumps(run, indent=2), encoding="utf-8")
        self._repoint_proposals(moved)
        self.vault.audit("cleanup", "apply", plan["folder"], moved=len(moved), errors=len(errors))
        return run

    def undo(self, plan_id: str) -> dict[str, Any]:
        rf = self.dir / f"{plan_id}-run.json"
        if not rf.exists():
            raise KeyError(plan_id)
        run = json.loads(rf.read_text(encoding="utf-8"))
        if run.get("undone"):
            raise ValueError("this run was already undone")
        back, errors = [], []
        for m in reversed(run["moved"]):
            src, dst = Path(m["dst"]), Path(m["src"])
            try:
                if not src.exists():
                    raise FileNotFoundError("moved file is gone")
                target = _free(dst)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(target))
                back.append({"src": str(src), "dst": str(target)})
            except (OSError, shutil.Error) as e:
                errors.append(f"{src.name}: {e}")
        run["undone"] = dt.datetime.now().isoformat(timespec="seconds")
        rf.write_text(json.dumps(run, indent=2), encoding="utf-8")
        self._repoint_proposals([{"src": b["src"], "dst": b["dst"]} for b in back])
        self.vault.audit("cleanup", "undo", plan_id, restored=len(back), errors=len(errors))
        return {"restored": len(back), "errors": errors}

    def _repoint_proposals(self, moves: list[dict[str, Any]]) -> None:
        """Keep Orchestrator proposals pointing at the file's new location (so 'Copy in' still works after a move)."""
        if not moves:
            return
        where = {m["src"].lower(): m["dst"] for m in moves}
        ps = self.orch.proposals()
        for p in ps:
            new = where.get((p.get("path") or "").lower())
            if new:
                p["path"] = new
        self.orch._set_proposals(ps)

    def runs(self) -> list[dict[str, Any]]:
        out = []
        for rf in sorted(self.dir.glob("*-run.json"), reverse=True)[:10]:
            r = json.loads(rf.read_text(encoding="utf-8"))
            out.append({"plan": r["plan"], "applied": r["applied"], "moved": len(r["moved"]), "errors": len(r["errors"]),
                        "undone": r.get("undone")})
        return out
