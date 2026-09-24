import subprocess
from pathlib import Path

import pytest

from hive.pipeline import NotARepo, git_commit, init_vault
from hive.vault import Vault

TEMPLATE = Path(__file__).resolve().parents[2] / "vault-template"


def _identity(root: Path) -> None:
    for k, v in (("user.name", "t"), ("user.email", "t@example.com")):
        subprocess.run(["git", "config", "--local", k, v], cwd=root, check=True)


def test_init_vault_scaffolds_without_overwriting(tmp_path):
    root = tmp_path / "v"
    root.mkdir()
    (root / "me.md").write_text("mine")
    created = init_vault(root, TEMPLATE)
    assert (root / "me.md").read_text() == "mine"  # never overwrites
    assert "CLAUDE.md" in created and ".claude/commands/hive-ingest.md" in created and ".git" in created
    assert (root / "contacts" / ".gitkeep").exists() and ".hive/agent-runs/" in (root / ".gitignore").read_text()
    assert init_vault(root, TEMPLATE) == []  # idempotent


def test_template_has_no_personal_data():
    """The template ships in the public repo: only example.com addresses allowed."""
    import re
    text = "\n".join(p.read_text(encoding="utf-8") for p in TEMPLATE.rglob("*.md"))
    emails = re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", text)
    assert emails and all(e.endswith("example.com") for e in emails)


def test_git_commit_uses_vault_own_repo(tmp_path):
    root = tmp_path / "v"
    init_vault(root, TEMPLATE)
    _identity(root)
    v = Vault(root)
    sha = git_commit(v, "seed")
    assert sha
    assert git_commit(v, "noop") is None  # nothing changed
    (root / "contacts" / "A.md").write_text("---\ntype: contact\n---\n")
    assert git_commit(v, "add A") not in (None, sha)
    log = subprocess.run(["git", "log", "--format=%s"], cwd=root, capture_output=True, text=True).stdout.split("\n")
    assert log[:2] == ["add A", "seed"]


def test_git_commit_requires_repo(tmp_path):
    with pytest.raises(NotARepo):
        git_commit(Vault(tmp_path / "plain"), "x")
