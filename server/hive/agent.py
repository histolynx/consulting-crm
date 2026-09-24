"""Claude Code as HIVE's agent: runs `claude -p` headless inside the vault directory.

Tool scopes (Bash, web and MCP are always denied; the agent never sees credentials):
  read   -> Read, Glob, Grep                     ("Ask the Hive")
  write  -> + Write, Edit                        (chat with edit permission, ingestion, briefings)

Every run is logged to vault/.hive/agent-runs/<timestamp>-<task>.jsonl and the audit log.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import threading
from pathlib import Path
from typing import Any, Iterator

from .config import find_claude
from .vault import Vault, split_frontmatter

READ_TOOLS = ["Read", "Glob", "Grep"]
WRITE_TOOLS = READ_TOOLS + ["Write", "Edit"]
DENY_TOOLS = ["Bash", "WebFetch", "WebSearch", "NotebookEdit", "Task"]

SYSTEM = (
    "You are HIVE, the knowledge-graph agent for a solo AI/data consulting practice. The current working "
    "directory is an Obsidian-compatible markdown vault; follow the conventions in CLAUDE.md exactly. "
    "Cite notes you rely on as [[wikilinks]]. Be concise and concrete. Today is {today}."
)

_write_lock = threading.Lock()


def command_prompt(vault: Vault, name: str, args: str = "") -> str:
    """Load a slash-command body from vault/.claude/commands/<name>.md (shared with interactive Claude Code)."""
    p = vault.root / ".claude" / "commands" / f"{name}.md"
    if not p.exists():
        raise FileNotFoundError(f"missing command prompt {p}")
    _, body = split_frontmatter(p.read_text(encoding="utf-8"))
    return body.replace("$ARGUMENTS", args).strip()


def _summarise_tool(block: dict[str, Any], root: str = "") -> str:
    inp = block.get("input") or {}
    for k in ("file_path", "pattern", "path", "query"):
        if k in inp:
            v = str(inp[k])
            if k in ("file_path", "path"):
                v = v.replace("\\", "/")
                if root and v.lower().startswith(root.lower()):
                    v = v[len(root):].lstrip("/")
            return v
    return ""


class Agent:
    def __init__(self, vault: Vault):
        self.vault = vault

    def _cmd(self, mode: str, session_id: str | None) -> list[str]:
        tools = WRITE_TOOLS if mode == "write" else READ_TOOLS
        cmd = [str(find_claude()), "-p", "--output-format", "stream-json", "--verbose",
               "--allowedTools", ",".join(tools), "--disallowedTools", ",".join(DENY_TOOLS),
               "--append-system-prompt", SYSTEM.format(today=dt.date.today().isoformat())]
        if mode == "write":
            cmd += ["--permission-mode", "acceptEdits"]
        if session_id:
            cmd += ["--resume", session_id]
        return cmd

    def stream(self, prompt: str, mode: str = "read", task: str = "ask", session_id: str | None = None) -> Iterator[dict[str, Any]]:
        """Yield simplified events: init, text, tool, result, error."""
        if mode not in ("read", "write"):
            raise ValueError("mode must be read or write")
        if mode == "write" and not _write_lock.acquire(blocking=False):
            yield {"kind": "error", "text": "Another write-capable agent run is in progress. Try again when it finishes."}
            return
        runs = self.vault.root / ".hive" / "agent-runs"
        runs.mkdir(parents=True, exist_ok=True)
        log_path = runs / f"{dt.datetime.now():%Y%m%d-%H%M%S}-{task}.jsonl"
        self.vault.audit("agent", f"run-{task}", mode, log=log_path.name)
        try:
            cmd = self._cmd(mode, session_id)
        except Exception as e:  # ConfigError -> surface, never guess
            if mode == "write":
                _write_lock.release()
            yield {"kind": "error", "text": str(e)}
            return
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        proc = None
        try:
            proc = subprocess.Popen(cmd, cwd=self.vault.root, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                                    creationflags=flags)
            assert proc.stdin and proc.stdout and proc.stderr
            proc.stdin.write(prompt)
            proc.stdin.close()
            got_result = False
            with open(log_path, "w", encoding="utf-8") as log:
                log.write(json.dumps({"prompt": prompt, "mode": mode, "cmd": cmd[1:]}) + "\n")
                for line in proc.stdout:
                    line = line.strip()
                    if not line:
                        continue
                    log.write(line + "\n")
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    for out in self._translate(ev, self.vault.root.as_posix()):
                        got_result |= out["kind"] == "result"
                        yield out
            err = proc.stderr.read()
            code = proc.wait()
            if code != 0 or not got_result:
                yield {"kind": "error", "text": f"claude exited with code {code}. {err.strip()[:800]}"}
        finally:
            if proc and proc.poll() is None:  # consumer went away (e.g. browser closed): stop the agent
                proc.kill()
                self.vault.audit("agent", f"killed-{task}", mode, log=log_path.name)
            if mode == "write":
                _write_lock.release()

    @staticmethod
    def _translate(ev: dict[str, Any], root: str = "") -> Iterator[dict[str, Any]]:
        t = ev.get("type")
        if t == "system" and ev.get("subtype") == "init":
            yield {"kind": "init", "session_id": ev.get("session_id"), "model": ev.get("model")}
        elif t == "assistant":
            for block in (ev.get("message") or {}).get("content") or []:
                if block.get("type") == "text" and block.get("text"):
                    yield {"kind": "text", "text": block["text"]}
                elif block.get("type") == "tool_use":
                    yield {"kind": "tool", "name": block.get("name"), "detail": _summarise_tool(block, root)}
        elif t == "result":
            yield {"kind": "result", "text": ev.get("result", ""), "session_id": ev.get("session_id"),
                   "cost": ev.get("total_cost_usd"), "duration_ms": ev.get("duration_ms"),
                   "turns": ev.get("num_turns"), "is_error": bool(ev.get("is_error"))}

    def run(self, prompt: str, mode: str = "write", task: str = "job") -> dict[str, Any]:
        """Blocking run for pipelines. Returns the final result/error event plus tool count."""
        tools = 0
        last: dict[str, Any] = {"kind": "error", "text": "no output"}
        for ev in self.stream(prompt, mode=mode, task=task):
            if ev["kind"] == "tool":
                tools += 1
            if ev["kind"] in ("result", "error"):
                last = ev
        return {**last, "tools": tools}


def claude_available() -> dict[str, Any]:
    try:
        p: Path = find_claude()
        return {"ok": True, "path": str(p)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
