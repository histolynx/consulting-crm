"""Paths, secrets and external-binary discovery.

Secrets never live in the (Google Drive synced) project folder: they are read from
%USERPROFILE%\\.hive\\secrets.env (KEY=VALUE lines) or real environment variables.
"""
from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SECRETS_FILE = Path.home() / ".hive" / "secrets.env"


class ConfigError(RuntimeError):
    """Raised when something required is missing. Never silently fall back."""


@dataclass
class Settings:
    vault: Path
    web: Path

    @property
    def state_dir(self) -> Path:
        return self.vault / ".hive"


def load_settings() -> Settings:
    vault = Path(os.environ.get("HIVE_VAULT", PROJECT_ROOT / "vault")).resolve()
    return Settings(vault=vault, web=PROJECT_ROOT / "web")


def read_secrets() -> dict[str, str]:
    out: dict[str, str] = {}
    if SECRETS_FILE.exists():
        for line in SECRETS_FILE.read_text(encoding="utf-8-sig").splitlines():  # -sig: PowerShell 5 writes a BOM
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    for k, v in os.environ.items():
        if k.startswith("HIVE_"):
            out[k] = v
    return out


def secret(name: str) -> str:
    val = read_secrets().get(name)
    if not val:
        raise ConfigError(f"Missing secret {name}. Add it to {SECRETS_FILE} (see README 'Gmail setup').")
    return val


def claude_env() -> dict[str, str]:
    """Environment for the claude subprocess. If HIVE_CLAUDE_CONFIG_DIR is set, HIVE's agent uses that
    config dir, i.e. its OWN Claude login (e.g. the account tied to the hive mailbox), independent of
    the account your interactive Claude Code uses."""
    env = dict(os.environ)
    cfg = read_secrets().get("HIVE_CLAUDE_CONFIG_DIR")
    if cfg:
        p = Path(os.path.expandvars(cfg)).expanduser()
        if not p.exists():
            raise ConfigError(f"HIVE_CLAUDE_CONFIG_DIR {p} does not exist; run scripts\\claude-login.ps1")
        env["CLAUDE_CONFIG_DIR"] = str(p)
    return env


def claude_account() -> dict:
    """`claude auth status` for the account HIVE's agent will use (no token contents, just identity)."""
    import json
    import subprocess
    try:
        out = subprocess.run([str(find_claude()), "auth", "status"], env=claude_env(), capture_output=True,
                             text=True, timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        data = json.loads(out.stdout)
        return {k: data.get(k) for k in ("loggedIn", "email", "subscriptionType", "authMethod", "configDirectory")}
    except Exception as e:  # noqa: BLE001 - reported to the UI
        return {"loggedIn": False, "error": str(e)}


def _version_key(p: Path) -> tuple[int, ...]:
    m = re.search(r"claude-code-(\d+)\.(\d+)\.(\d+)", str(p))
    return tuple(int(x) for x in m.groups()) if m else (0,)


def find_claude() -> Path:
    """Locate the Claude Code CLI: HIVE_CLAUDE_BIN, PATH, then the newest VS Code extension bundle."""
    explicit = read_secrets().get("HIVE_CLAUDE_BIN")
    if explicit:
        p = Path(explicit)
        if not p.exists():
            raise ConfigError(f"HIVE_CLAUDE_BIN points to a missing file: {p}")
        return p
    on_path = shutil.which("claude")
    if on_path:
        return Path(on_path)
    candidates = sorted(
        (Path.home() / ".vscode" / "extensions").glob("anthropic.claude-code-*/resources/native-binary/claude*"),
        key=_version_key,
    )
    candidates = [c for c in candidates if c.suffix in (".exe", "")]
    if candidates:
        return candidates[-1]
    raise ConfigError("Claude Code CLI not found. Install it or set HIVE_CLAUDE_BIN in ~/.hive/secrets.env.")
