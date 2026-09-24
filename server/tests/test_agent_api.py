import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hive import agent as agent_mod
from hive.agent import Agent
from hive.app import create_app

FAKE_CLAUDE = r'''
import json, sys
prompt = sys.stdin.read()
print(json.dumps({"type": "system", "subtype": "init", "session_id": "s1", "model": "fake"}))
print(json.dumps({"type": "assistant", "message": {"content": [
    {"type": "tool_use", "name": "Read", "input": {"file_path": sys.argv[1] + "/contacts/Jane Doe.md"}},
    {"type": "text", "text": "echo: " + prompt}]}}))
print(json.dumps({"type": "result", "result": "done", "session_id": "s1", "total_cost_usd": 0.01, "num_turns": 2}))
'''


@pytest.fixture
def fake_claude(tmp_path, monkeypatch):
    script = tmp_path / "fake_claude.py"
    script.write_text(FAKE_CLAUDE)
    seen = {}

    def fake_cmd(self, mode, session_id):
        seen["mode"], seen["session"] = mode, session_id
        return [sys.executable, str(script), self.vault.root.as_posix()]
    monkeypatch.setattr(Agent, "_cmd", fake_cmd)
    return seen


def test_agent_stream_translates_events(crm_vault, fake_claude):
    evs = list(Agent(crm_vault).stream("who is Jane?", mode="read"))
    kinds = [e["kind"] for e in evs]
    assert kinds == ["init", "tool", "text", "result"]
    assert evs[1]["detail"] == "contacts/Jane Doe.md"
    assert evs[2]["text"] == "echo: who is Jane?"
    assert list((crm_vault.root / ".hive" / "agent-runs").glob("*-ask.jsonl"))


def test_agent_real_cmd_scopes_tools(monkeypatch, crm_vault):
    monkeypatch.setattr(agent_mod, "find_claude", lambda: Path("claude"))
    read = Agent(crm_vault)._cmd("read", None)
    write = Agent(crm_vault)._cmd("write", "abc")
    assert read[read.index("--allowedTools") + 1] == "Read,Glob,Grep"
    assert "--permission-mode" not in read
    assert write[write.index("--allowedTools") + 1] == "Read,Glob,Grep,Write,Edit"
    assert "Bash" in write[write.index("--disallowedTools") + 1]
    assert write[write.index("--resume") + 1] == "abc"


def test_agent_missing_binary_is_an_error_event(monkeypatch, crm_vault):
    from hive.config import ConfigError

    def boom():
        raise ConfigError("Claude Code CLI not found")
    monkeypatch.setattr(agent_mod, "find_claude", boom)
    evs = list(Agent(crm_vault).stream("q", mode="write"))
    assert evs == [{"kind": "error", "text": "Claude Code CLI not found"}]
    # lock must have been released
    assert agent_mod._write_lock.acquire(blocking=False)
    agent_mod._write_lock.release()


@pytest.fixture
def client(crm_vault):
    return TestClient(create_app(crm_vault.root))


H = {"X-Hive": "1"}


def test_guard_requires_header_and_local_host(client):
    assert client.post("/api/time", json={"minutes": 5}).status_code == 403
    assert client.get("/api/health", headers={"host": "evil.example"}).status_code == 403
    assert client.get("/api/health").status_code == 200


def test_graph_and_note_endpoints(client):
    g = client.get("/api/graph").json()
    ids = {n["id"] for n in g["nodes"]}
    assert "clients/Acme.md" in ids and "#graph" in ids
    assert "#graph" not in {n["id"] for n in client.get("/api/graph?tags=false").json()["nodes"]}
    lens = client.get("/api/graph", params={"root": "clients/Globex.md", "depth": 1}).json()
    assert "clients/Acme.md" not in {n["id"] for n in lens["nodes"]}
    n = client.get("/api/note", params={"path": "clients/Acme.md"}).json()
    assert {b["source"] for b in n["backlinks"]} >= {"contacts/Jane Doe.md", "contracts/Acme Platform.md"}
    assert client.get("/api/search", params={"q": "jane"}).json()[0]["path"] == "contacts/Jane Doe.md"


def test_create_note_uses_template(client, crm_vault):
    (crm_vault.root / "_templates").mkdir()
    (crm_vault.root / "_templates" / "contact.md").write_text("---\ntype: contact\nname: {{title}}\n---\n# {{title}}\n")
    r = client.post("/api/note", json={"type": "contact", "title": "New Person"}, headers=H).json()
    assert r["path"] == "contacts/New Person.md"
    assert "name: New Person" in (crm_vault.root / r["path"]).read_text(encoding="utf-8")


def test_time_invoice_flow(client):
    e = client.post("/api/time", json={"date": "2026-09-10", "contract": "Acme Platform", "minutes": 120}, headers=H).json()
    assert e["minutes"] == 120
    inv = client.post("/api/invoices", json={"contract": "contracts/Acme Platform.md", "start": "2026-09-01",
                                            "end": "2026-09-30"}, headers=H).json()
    assert inv["total"] == 300.0
    bad = client.post("/api/invoices", json={"contract": "contracts/Acme Platform.md", "start": "2026-09-01",
                                            "end": "2026-09-30"}, headers=H)
    assert bad.status_code == 400 and "nothing billable" in bad.json()["detail"]
    assert client.post("/api/invoices/status", json={"path": inv["path"], "status": "paid"}, headers=H).json()["status"] == "paid"


def test_task_toggle(client, crm_vault):
    t = [x for x in client.get("/api/tasks").json() if x["text"].startswith("Send SOW")][0]
    assert client.post("/api/tasks/toggle", json={"path": t["path"], "line": t["line"]}, headers=H).json()["ok"]
    assert "- [x] Send SOW" in (crm_vault.root / t["path"]).read_text(encoding="utf-8")


def test_ask_streams_sse(client, fake_claude):
    r = client.post("/api/ask", json={"question": "hi", "session_id": "prev"}, headers=H)
    events = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]
    assert events[-1]["kind"] == "result" and fake_claude == {"mode": "read", "session": "prev"}


def test_notes_by_type_and_link(client, crm_vault):
    rows = client.get("/api/notes", params={"type": "contact"}).json()
    assert {r["path"] for r in rows} == {"contacts/Jane Doe.md", "contacts/Hank Scorpio.md"}
    assert client.post("/api/link", json={"a": "contacts/Jane Doe.md", "b": "contracts/Acme Platform.md"}, headers=H).json()["ok"]
    assert "related:: [[Acme Platform]]" in (crm_vault.root / "contacts/Jane Doe.md").read_text(encoding="utf-8")
    labels = {(l["source"], l["target"], l["label"]) for l in client.get("/api/graph").json()["links"]}
    assert ("contacts/Jane Doe.md", "contracts/Acme Platform.md", "related") in labels


def test_contract_status_and_dashboard(client):
    assert client.post("/api/contracts/status", json={"path": "contracts/Globex Graph.md", "status": "active"}, headers=H).json()["ok"]
    assert client.get("/api/dashboard").json()["kpis"]["active_contracts"] == 2
