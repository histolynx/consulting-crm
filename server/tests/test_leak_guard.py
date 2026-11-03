"""The public-repo pre-commit guard (scripts/check_no_client_data.py)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import check_no_client_data as guard  # noqa: E402


def test_staged_files_skip_the_vault_and_vendored_third_party_code(monkeypatch):
    """A licence header in a minified library once matched a vault name; vendor files are hash-verified, not scanned."""
    class Done:
        stdout = ("vault/clients/Acme.md\nweb/vendor/force-graph.min.js\nweb/vendor/vendor.lock.json\n"
                  "server/hive/app.py\nREADME.md\n")
    monkeypatch.setattr(guard.subprocess, "run", lambda *a, **k: Done())
    assert guard.staged_files() == ["server/hive/app.py", "README.md"]
