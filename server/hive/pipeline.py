"""End-to-end jobs used by the UI buttons, the CLI and the Windows scheduled task.

sync:  fetch Gmail -> agent ingests new inbox notes -> push ready drafts -> auto-add suggested time -> git commit
brief: snapshot dashboard -> agent writes briefings/YYYY-MM-DD.md -> git commit
"""
from __future__ import annotations

import datetime as dt
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from . import crm
from .agent import Agent, command_prompt
from .graph import Graph
from .mail import Mailbox
from .timetrack import TimeTracker
from .vault import Vault


class NotARepo(RuntimeError):
    pass


def git_commit(vault: Vault, message: str) -> str | None:
    """Commit vault changes in the vault's OWN git repo (kept separate from the public code repo so
    client data can't leak). Returns short sha, or None if nothing changed. Raises NotARepo if the
    vault isn't a git repo (reported as a failed step, never silently skipped)."""
    repo = vault.root
    if not (repo / ".git").exists():
        raise NotARepo(f"{repo} is not a git repo; run `python -m hive init` to version it")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    # audit.jsonl alone changing (e.g. the previous commit's own audit line) isn't worth a commit; it rides along with the next one
    if subprocess.run(["git", "diff", "--cached", "--quiet", "--", ".", ":(exclude).hive/audit.jsonl"], cwd=repo).returncode == 0:
        return None
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=repo, check=True, capture_output=True)
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
    vault.audit("git", "commit", sha, message=message)
    return sha


VAULT_FOLDERS = ["clients", "contacts", "contracts", "projects", "meetings", "emails", "time", "invoices",
                 "knowledge", "inbox", "outbox", "briefings", "attachments"]
VAULT_GITIGNORE = """# volatile HIVE state (audit.jsonl and mail.json ARE tracked)
.hive/agent-runs/
.hive/snapshot.json
.hive/timer.json
.hive/last_sync.json
.hive/scheduler.log
.obsidian/workspace*.json
.trash/
"""


def init_vault(root: Path, template: Path, git: bool = True) -> list[str]:
    """Scaffold a vault from vault-template/ without overwriting anything, and make it its own git repo."""
    created: list[str] = []
    root.mkdir(parents=True, exist_ok=True)
    for src in template.rglob("*"):
        if src.is_file():
            dest = root / src.relative_to(template)
            if not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
                created.append(dest.relative_to(root).as_posix())
    for d in VAULT_FOLDERS + [".hive"]:
        (root / d).mkdir(exist_ok=True)
        keep = root / d / ".gitkeep"
        if d != ".hive" and not any((root / d).iterdir()):
            keep.touch()
    gi = root / ".gitignore"
    if not gi.exists():
        gi.write_text(VAULT_GITIGNORE, encoding="utf-8")
        created.append(".gitignore")
    if git and not (root / ".git").exists():
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
        created.append(".git")
    return created


def snapshot(vault: Vault) -> dict[str, Any]:
    graph = Graph.build(vault.load_all())
    data = crm.dashboard(graph, TimeTracker(vault))
    (vault.root / ".hive" / "snapshot.json").write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return data


def sync(vault: Vault, fetch: bool = True, ingest: bool = True, push: bool = True, gaps: bool = True) -> dict[str, Any]:
    report: dict[str, Any] = {"started": dt.datetime.now().isoformat(timespec="seconds"), "steps": []}

    def step(name: str, fn) -> Any:
        try:
            out = fn()
            report["steps"].append({"step": name, "ok": True, "result": out})
            return out
        except Exception as e:  # noqa: BLE001 - every failure is reported, none silently swallowed
            report["steps"].append({"step": name, "ok": False, "error": f"{type(e).__name__}: {e}"})
            return None

    mb = Mailbox(vault)
    if fetch:
        step("fetch", mb.fetch_new)
    if ingest:
        new = [p for p in (vault.root / "inbox").glob("*.md") if vault.read(p.relative_to(vault.root).as_posix()).meta.get("status") == "new"]
        if new:
            step("ingest", lambda: Agent(vault).run(command_prompt(vault, "hive-ingest"), mode="write", task="ingest"))
        else:
            report["steps"].append({"step": "ingest", "ok": True, "result": "inbox empty"})
    if push:
        step("push_drafts", mb.push_drafts)
    if gaps:
        step("time_gaps", lambda: [e["id"] for e in TimeTracker(vault).apply_gaps(Graph.build(vault.load_all()))])
    step("snapshot", lambda: bool(snapshot(vault)))
    report["commit"] = step("git", lambda: git_commit(vault, f"hive sync {dt.datetime.now():%Y-%m-%d %H:%M}"))
    report["finished"] = dt.datetime.now().isoformat(timespec="seconds")
    vault.set_state("last_sync", report)
    return report


def brief(vault: Vault) -> dict[str, Any]:
    snapshot(vault)
    res = Agent(vault).run(command_prompt(vault, "hive-brief"), mode="write", task="brief")
    try:
        res["commit"] = git_commit(vault, f"hive briefing {dt.date.today()}")
    except (NotARepo, subprocess.CalledProcessError) as e:
        res["commit_error"] = str(e)
    return res


def export_lens(vault: Vault, root: str, depth: int, out_dir: Path) -> dict[str, Any]:
    """Copy the ego-network of `root` into a standalone Obsidian vault (e.g. to share one project)."""
    graph = Graph.build(vault.load_all())
    if root not in graph.notes:
        raise ValueError(f"unknown note {root}")
    keep = [p for p in graph.ego(root, depth) if p in graph.notes]
    if out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError(f"{out_dir} is not empty; choose another name")
    for p in keep:
        dest = out_dir / p
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(vault.root / p, dest)
    vault.audit("ui", "export-lens", root, depth=depth, notes=len(keep), out=str(out_dir))
    return {"out": str(out_dir), "notes": len(keep)}
