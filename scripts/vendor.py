"""Vendor pinned frontend libraries into web/vendor without node_modules.

Supply-chain controls:
  * exact versions only, and each must be >= COOLDOWN_DAYS old (checked against the registry)
  * tarball sha512 verified against the registry's `dist.integrity`
  * integrity is recorded in web/vendor/vendor.lock.json; later runs fail if it ever changes

Usage:  python scripts/vendor.py
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import io
import json
import sys
import tarfile
import urllib.request
from pathlib import Path

COOLDOWN_DAYS = 14
ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "web" / "vendor"
LOCK = VENDOR / "vendor.lock.json"

# package, version, {path-in-package: vendored filename}
PACKAGES = [
    ("preact", "10.29.8", {"dist/preact.module.js": "preact.mjs", "hooks/dist/hooks.module.js": "preact-hooks.mjs"}),
    ("htm", "3.1.1", {"dist/htm.module.js": "htm.mjs"}),
    ("force-graph", "1.51.4", {"dist/force-graph.min.js": "force-graph.min.js"}),
    ("3d-force-graph", "1.80.0", {"dist/3d-force-graph.min.js": "3d-force-graph.min.js"}),
    ("marked", "18.0.11", {"lib/marked.esm.js": "marked.mjs"}),
    ("dompurify", "3.4.14", {"dist/purify.es.mjs": "purify.mjs"}),
]


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as r:  # noqa: S310 - fixed https registry URL
        return r.read()


def main() -> int:
    VENDOR.mkdir(parents=True, exist_ok=True)
    lock = json.loads(LOCK.read_text()) if LOCK.exists() else {}
    now = dt.datetime.now(dt.timezone.utc)

    for name, version, files in PACKAGES:
        meta = json.loads(fetch(f"https://registry.npmjs.org/{name}"))
        released = dt.datetime.fromisoformat(meta["time"][version].replace("Z", "+00:00"))
        age = (now - released).days
        if age < COOLDOWN_DAYS:
            print(f"REFUSING {name}@{version}: only {age} days old (< {COOLDOWN_DAYS})")
            return 1
        dist = meta["versions"][version]["dist"]
        integrity = dist["integrity"]
        key = f"{name}@{version}"
        if key in lock and lock[key]["integrity"] != integrity:
            print(f"INTEGRITY CHANGED for {key}! lock={lock[key]['integrity']} registry={integrity}")
            return 1

        blob = fetch(dist["tarball"])
        algo, b64 = integrity.split("-", 1)
        digest = base64.b64encode(hashlib.new(algo, blob).digest()).decode()
        if digest != b64:
            print(f"HASH MISMATCH for {key}")
            return 1

        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
            for src, dest in files.items():
                member = tar.getmember(f"package/{src}")
                data = tar.extractfile(member).read()
                (VENDOR / dest).write_bytes(data)
        lock[key] = {"integrity": integrity, "released": meta["time"][version], "files": list(files.values())}
        print(f"ok  {key:28s} age={age}d  {integrity[:26]}...")

    LOCK.write_text(json.dumps(lock, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
