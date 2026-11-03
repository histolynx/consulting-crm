"""`python -m hive doctor`: the things that stop working silently.

A moved repo leaves the Windows scheduled tasks pointing at the old folder (the hourly sync simply stops), a
Claude login expires, Gmail gets disconnected. None of these raise anywhere a person looks, so check them on demand.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from .config import PROJECT_ROOT, claude_account, find_claude, gmail_login
from .vault import Vault

STALE_HOURS = 3  # the sync task runs hourly; three misses means it has stopped, not that the laptop blinked
TASKS = {"HIVE Server": "server", "HIVE Sync": "", "HIVE Orchestrator": "", "HIVE Brief": ""}  # expected working dir, relative to the repo


def sync_age_hours(last_sync: dict[str, Any] | None, now: dt.datetime | None = None) -> float | None:
    if not last_sync or not last_sync.get("finished"):
        return None
    return ((now or dt.datetime.now()) - dt.datetime.fromisoformat(last_sync["finished"])).total_seconds() / 3600


def check_sync(vault: Vault, now: dt.datetime | None = None) -> dict[str, Any]:
    ls = vault.state("last_sync")
    age = sync_age_hours(ls, now)
    if age is None:
        return {"check": "last sync", "ok": True, "detail": "no sync has run yet"}
    failed = [s.get("step") for s in ls.get("steps", []) if not s.get("ok")]
    detail = f"{age:.1f} h ago"
    if failed:
        detail += f", failed steps: {', '.join(map(str, failed))}"
    if age > STALE_HOURS:
        detail += " (stale: the hourly task may have stopped; see the scheduled-task checks)"
    return {"check": "last sync", "ok": age <= STALE_HOURS and not failed, "detail": detail}


def scheduled_tasks() -> list[dict[str, Any]] | None:
    """Windows scheduled tasks named HIVE*: [{name, state, dir}]. None = not on Windows or the query failed."""
    if os.name != "nt":
        return None
    cmd = ("Get-ScheduledTask -TaskName 'HIVE*' -ErrorAction SilentlyContinue | ForEach-Object { [pscustomobject]@{ "
           "name = $_.TaskName; state = [string]$_.State; dir = $_.Actions[0].WorkingDirectory } } | ConvertTo-Json -Compress")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=30,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None
    if not out:
        return []
    data = json.loads(out)
    return data if isinstance(data, list) else [data]


def check_tasks(tasks: list[dict[str, Any]] | None, root: Path = PROJECT_ROOT) -> list[dict[str, Any]]:
    if tasks is None:
        return [{"check": "scheduled tasks", "ok": False, "detail": "could not query Windows scheduled tasks"}]
    by_name = {t.get("name"): t for t in tasks}
    out = []
    for name, sub in TASKS.items():
        t = by_name.get(name)
        want = root / sub if sub else root
        if not t:
            out.append({"check": name, "ok": False, "detail": "not registered: run scripts\\install-server.ps1 / install-schedule.ps1"})
            continue
        have = Path(t.get("dir") or "")
        ok = bool(str(have)) and have.resolve() == want.resolve()
        detail = f"{t.get('state')}, runs in {have}"
        if not ok:
            detail += f" (expected {want}: the repo moved; re-run the install script from here)"
        out.append({"check": name, "ok": ok, "detail": detail})
    return out


def run(vault: Vault) -> dict[str, Any]:
    checks: list[dict[str, Any]] = [{"check": "python", "ok": True, "detail": sys.executable}]
    is_repo = (vault.root / ".git").exists()
    checks.append({"check": "vault", "ok": is_repo, "detail": str(vault.root) + ("" if is_repo else " is not a git repo: python -m hive init")})
    try:
        exe = find_claude()
        acct = claude_account()
        who = acct.get("email") or acct.get("error") or "not logged in"
        checks.append({"check": "claude", "ok": bool(acct.get("loggedIn")),
                       "detail": f"{exe} as {who}" + ("" if acct.get("loggedIn") else " (run scripts\\claude-login.ps1)")})
    except Exception as e:  # noqa: BLE001 - ConfigError etc. are the finding
        checks.append({"check": "claude", "ok": False, "detail": str(e)})
    login = gmail_login()
    checks.append({"check": "gmail", "ok": login is not None, "detail": f"{login[0]} via {login[2]}" if login else "not connected: HIVE → Setup"})
    checks.append(check_sync(vault))
    checks += check_tasks(scheduled_tasks(), PROJECT_ROOT)
    return {"ok": all(c["ok"] for c in checks), "checks": checks}
