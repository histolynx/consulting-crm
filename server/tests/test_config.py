import pytest

from hive import config


@pytest.fixture
def secrets(tmp_path, monkeypatch):
    f = tmp_path / "secrets.env"
    monkeypatch.setattr(config, "SECRETS_FILE", f)
    for k in list(__import__("os").environ):
        if k.startswith("HIVE_"):
            monkeypatch.delenv(k)
    return f


def test_secrets_tolerate_bom_comments_and_quotes(secrets):
    secrets.write_bytes("﻿HIVE_GMAIL_USER=a@b.test\n# comment\nHIVE_GMAIL_APP_PASSWORD='xx yy'\n".encode("utf-8"))
    s = config.read_secrets()
    assert s["HIVE_GMAIL_USER"] == "a@b.test" and s["HIVE_GMAIL_APP_PASSWORD"] == "xx yy"


def test_missing_secret_is_explicit_error(secrets):
    with pytest.raises(config.ConfigError, match="HIVE_GMAIL_USER"):
        config.secret("HIVE_GMAIL_USER")


def test_claude_env_dedicated_login(secrets, tmp_path, monkeypatch):
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    assert "CLAUDE_CONFIG_DIR" not in config.claude_env()  # default: shared login
    cfg = tmp_path / "hive-claude"
    secrets.write_text(f"HIVE_CLAUDE_CONFIG_DIR={cfg}\n")
    with pytest.raises(config.ConfigError, match="claude-login"):
        config.claude_env()  # configured but missing -> loud, not a silent fallback
    cfg.mkdir()
    assert config.claude_env()["CLAUDE_CONFIG_DIR"] == str(cfg)
