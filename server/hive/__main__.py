"""CLI:  python -m hive serve | sync | brief | fetch | gaps"""
from __future__ import annotations

import argparse
import json
import sys

from .config import load_settings
from .vault import Vault


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="hive")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=8787)
    sy = sub.add_parser("sync")
    sy.add_argument("--no-fetch", action="store_true")
    sy.add_argument("--no-ingest", action="store_true")
    sub.add_parser("brief")
    sub.add_parser("init", help="scaffold the vault from vault-template/ and make it its own git repo")
    sub.add_parser("fetch")
    sub.add_parser("gaps")
    a = ap.parse_args(argv)

    if a.cmd == "serve":
        import os
        from pathlib import Path

        import uvicorn
        if sys.stdout is None or sys.stderr is None:  # pythonw (background task): no console, so log to a file
            log = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "hive" / "server.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            sys.stdout = sys.stderr = open(log, "a", buffering=1, encoding="utf-8")  # noqa: SIM115
        uvicorn.run("hive.app:create_app", factory=True, host="127.0.0.1", port=a.port)
        return 0

    from . import pipeline
    if a.cmd == "init":
        from .config import PROJECT_ROOT
        out = pipeline.init_vault(load_settings().vault, PROJECT_ROOT / "vault-template")
        print(json.dumps({"vault": str(load_settings().vault), "created": out}, indent=2))
        return 0
    vault = Vault(load_settings().vault)
    if a.cmd == "sync":
        out = pipeline.sync(vault, fetch=not a.no_fetch, ingest=not a.no_ingest)
    elif a.cmd == "brief":
        out = pipeline.brief(vault)
    elif a.cmd == "fetch":
        from .mail import Mailbox
        out = Mailbox(vault).fetch_new()
    else:
        from .graph import Graph
        from .timetrack import TimeTracker
        out = TimeTracker(vault).detect_gaps(Graph.build(vault.load_all()))
    print(json.dumps(out, indent=2, default=str))
    failed = isinstance(out, dict) and any(not st.get("ok", True) for st in out.get("steps", []))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
