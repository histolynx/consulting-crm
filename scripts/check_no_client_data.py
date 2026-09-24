"""Pre-commit guard for the PUBLIC code repo: block commits that mention anything from the private vault.

Reads client/contact/contract/project/profile note titles and aliases from vault/ at run time (so the names
themselves never live in this repo) and scans the staged content for them. Exit 1 lists the hits.
Install (local only):  python scripts/check_no_client_data.py --install
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

from hive.vault import Vault  # noqa: E402

SENSITIVE_TYPES = {"client", "contact", "contract", "project", "profile"}
MIN_LEN = 4
IGNORE = {"me", "your name", "your business name"}


def sensitive_terms() -> set[str]:
    vault = ROOT / "vault"
    if not vault.exists():
        return set()
    terms: set[str] = set()
    for n in Vault(vault).load_all():
        if n.type not in SENSITIVE_TYPES:
            continue
        for t in [n.title, n.meta.get("name"), n.meta.get("business"), *(n.meta.get("aliases") or [])]:
            if isinstance(t, str) and len(t.strip()) >= MIN_LEN and t.strip().lower() not in IGNORE:
                terms.add(t.strip())
        for k in ("email", "website"):
            v = n.meta.get(k)
            if isinstance(v, str) and len(v) >= MIN_LEN:
                terms.add(v.strip())
    return terms


def staged_files() -> list[str]:
    out = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    return [f for f in out.splitlines() if f and not f.startswith("vault/")]


def main() -> int:
    if "--install" in sys.argv:
        hook = ROOT / ".git" / "hooks" / "pre-commit"
        py = Path(sys.executable).as_posix()
        hook.write_text(f'#!/bin/sh\n"{py}" scripts/check_no_client_data.py\n', encoding="utf-8")
        print(f"installed {hook}")
        return 0
    terms = sensitive_terms()
    if not terms:
        return 0
    pat = re.compile(r"(?<![\w@.])(" + "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True)) + r")(?![\w])", re.I)
    hits = []
    for f in staged_files():
        blob = subprocess.run(["git", "show", f":{f}"], cwd=ROOT, capture_output=True).stdout
        try:
            text = blob.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            m = pat.search(line)
            if m:
                hits.append(f"{f}:{i}: '{m.group(1)}'")
    if hits:
        print("BLOCKED: staged files mention private vault data (client/contact/project names):")
        print("\n".join(hits[:40]))
        print("Replace them with generic examples (Acme, Jane Doe...). To override deliberately: git commit --no-verify")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
