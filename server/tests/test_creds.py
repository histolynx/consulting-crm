import os
import uuid

import pytest
from fastapi.testclient import TestClient

from hive import app as app_mod
from hive import config, creds
from hive.app import create_app
from hive.mail import LoginFailed

H = {"X-Hive": "1"}


@pytest.mark.skipif(os.name != "nt", reason="Windows Credential Manager")
def test_credential_manager_roundtrip():
    target = f"HIVE:test-{uuid.uuid4().hex[:8]}"
    try:
        assert creds.vault_read(target) is None
        creds.vault_write("me@example.com", "abcd efgh ijkl mnop", target)
        assert creds.vault_read(target) == ("me@example.com", "abcd efgh ijkl mnop")
        creds.vault_write("me@example.com", "new-pass", target)  # overwrite
        assert creds.vault_read(target)[1] == "new-pass"
    finally:
        assert creds.vault_delete(target) is True
    assert creds.vault_delete(target) is False


@pytest.fixture
def fake_store(monkeypatch, tmp_path):
    """Isolate from the real secrets file and the real Credential Manager entry."""
    store: dict = {}
    monkeypatch.setattr(config, "SECRETS_FILE", tmp_path / "none.env")
    for k in list(os.environ):
        if k.startswith("HIVE_"):
            monkeypatch.delenv(k)
    monkeypatch.setattr(creds, "vault_write", lambda u, p, target=creds.TARGET: store.__setitem__(target, (u, p)))
    monkeypatch.setattr(creds, "vault_read", lambda target=creds.TARGET: store.get(target))
    monkeypatch.setattr(creds, "vault_delete", lambda target=creds.TARGET: store.pop(target, None) is not None)
    creds.session_clear()
    yield store
    creds.session_clear()


def test_login_precedence(fake_store, tmp_path, monkeypatch):
    assert config.gmail_login() is None
    creds.vault_write("vault@x.test", "v")
    assert config.gmail_login() == ("vault@x.test", "v", "credential-manager")
    creds.session_set("sess@x.test", "s")
    assert config.gmail_login()[2] == "session"
    f = tmp_path / "s.env"
    f.write_text("HIVE_GMAIL_USER=file@x.test\n")  # user alone is NOT enough to shadow a stored pair
    monkeypatch.setattr(config, "SECRETS_FILE", f)
    assert config.gmail_login()[2] == "session"
    f.write_text("HIVE_GMAIL_USER=file@x.test\nHIVE_GMAIL_APP_PASSWORD=f\n")
    assert config.gmail_login() == ("file@x.test", "f", "secrets-file")


def test_require_login_message(fake_store):
    with pytest.raises(config.ConfigError, match="Setup"):
        config.require_gmail_login()


class _FakeImap:
    def logout(self):
        pass


def test_api_connect_verifies_then_stores(fake_store, crm_vault, monkeypatch):
    seen = []

    def fake_login(user, pw):
        seen.append((user, pw))
        if pw != "goodpassword1234":
            raise LoginFailed("Gmail rejected the login.")
        return _FakeImap()
    monkeypatch.setattr(app_mod, "imap_login", fake_login)
    c = TestClient(create_app(crm_vault.root))

    bad = c.post("/api/gmail", json={"user": "h@x.test", "password": "nope"}, headers=H)
    assert bad.status_code == 400 and "rejected" in bad.json()["detail"]
    assert fake_store == {} and not c.get("/api/gmail").json()["connected"]  # nothing stored on failure

    ok = c.post("/api/gmail", json={"user": "h@x.test", "password": "good pass word 1234", "remember": True}, headers=H).json()
    assert ok == {"connected": True, "user": "h@x.test", "source": "credential-manager", "suggested_user": None}
    assert seen[-1] == ("h@x.test", "goodpassword1234")  # spaces stripped before use
    assert "password" not in c.get("/api/gmail").text.lower().replace("app password", "")
    assert c.get("/api/health").json()["mail_configured"] is True
    assert c.post("/api/gmail/test", headers=H).json()["ok"]

    audit = (crm_vault.root / ".hive" / "audit.jsonl").read_text()
    assert "goodpassword1234" not in audit  # never logged

    s = c.post("/api/gmail", json={"user": "h@x.test", "password": "goodpassword1234", "remember": False}, headers=H).json()
    assert s["source"] == "session" and fake_store == {}  # session-only removes the stored copy

    assert c.delete("/api/gmail", headers=H).json()["connected"] is False
