"""Markdown vault I/O: frontmatter, [[wikilinks]], #tags, `key:: [[x]]` inline fields, tasks.

The vault is plain Obsidian-compatible markdown. A note's identity is its filename stem
(case-insensitive, like Obsidian); `aliases` in frontmatter also resolve.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

import yaml

WIKILINK = re.compile(r"\[\[([^\[\]|#^]+)(?:[#^][^\[\]|]*)?(?:\|([^\[\]]*))?\]\]")
TAG = re.compile(r"(?<![\w/&#\]])#([A-Za-z][\w/-]*)")
INLINE_FIELD = re.compile(r"^\s*[-*]?\s*([A-Za-z_][\w -]*?)\s*::\s*(.+)$")
TASK = re.compile(r"^\s*[-*] \[( |x|X)\] (.+)$")
DUE = re.compile(r"(?:📅|due::?)\s*(\d{4}-\d{2}-\d{2})")
FENCE = re.compile(r"```.*?```", re.S)
INLINE_CODE = re.compile(r"`[^`\n]*`")

SKIP_DIRS = {".hive", ".obsidian", ".git", ".claude", ".trash", "attachments", "_templates", "_intake"}
SKIP_FILES = {"CLAUDE.md"}  # agent instructions: its example [[links]] must not become graph nodes


@dataclass
class Link:
    target: str          # raw target text as written
    label: str           # frontmatter key / inline field / "mentions"


@dataclass
class Task:
    text: str
    done: bool
    due: str | None
    line: int


@dataclass
class Note:
    path: str                          # vault-relative posix path
    title: str                         # filename stem
    meta: dict[str, Any]
    body: str
    links: list[Link] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    tasks: list[Task] = field(default_factory=list)
    mtime: float = 0.0

    @property
    def type(self) -> str:
        return str(self.meta.get("type", "note"))


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if text.startswith("﻿"):
        text = text[1:]
    if not text.startswith("---"):
        return {}, text
    m = re.match(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", text, re.S)
    if not m:
        return {}, text
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        meta = {"_yaml_error": str(e)}
    if not isinstance(meta, dict):
        meta = {"_yaml_error": "frontmatter is not a mapping"}
    return meta, text[m.end():]


def _json_safe(v: Any) -> Any:
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    if isinstance(v, dict):
        return {str(k): _json_safe(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_json_safe(x) for x in v]
    return v


def _walk_values(v: Any) -> Iterator[str]:
    if isinstance(v, str):
        yield v
    elif isinstance(v, list):
        for x in v:
            yield from _walk_values(x)
    elif isinstance(v, dict):
        for x in v.values():
            yield from _walk_values(x)


def extract_links(meta: dict[str, Any], body: str) -> list[Link]:
    links: list[Link] = []
    for key, val in meta.items():
        if key in ("tags", "aliases"):
            continue
        # nested lists of dicts (e.g. time entries) label by the inner key when possible
        if isinstance(val, list) and val and all(isinstance(x, dict) for x in val):
            for item in val:
                for ik, iv in item.items():
                    for s in _walk_values(iv):
                        for m in WIKILINK.finditer(s):
                            links.append(Link(m.group(1).strip(), str(ik)))
            continue
        for s in _walk_values(val):
            for m in WIKILINK.finditer(s):
                links.append(Link(m.group(1).strip(), str(key)))
    clean = INLINE_CODE.sub("", FENCE.sub("", body))
    for line in clean.splitlines():
        f = INLINE_FIELD.match(line)
        label = f.group(1) if f else "mentions"
        for m in WIKILINK.finditer(line):
            links.append(Link(m.group(1).strip(), label))
    return links


def extract_tags(meta: dict[str, Any], body: str) -> list[str]:
    tags: list[str] = []
    raw = meta.get("tags") or []
    if isinstance(raw, str):
        raw = re.split(r"[,\s]+", raw)
    for t in raw:
        if t:
            tags.append(str(t).lstrip("#"))
    clean = INLINE_CODE.sub("", FENCE.sub("", body))
    tags.extend(m.group(1) for m in TAG.finditer(clean))
    seen: dict[str, None] = {}
    for t in tags:
        seen.setdefault(t.lower(), None)
    return list(seen)


def extract_tasks(body: str) -> list[Task]:
    out = []
    for i, line in enumerate(body.splitlines()):
        m = TASK.match(line)
        if m:
            d = DUE.search(m.group(2))
            out.append(Task(text=m.group(2).strip(), done=m.group(1) != " ", due=d.group(1) if d else None, line=i))
    return out


def parse_note(text: str, path: str, mtime: float = 0.0) -> Note:
    meta, body = split_frontmatter(text)
    meta = _json_safe(meta)
    return Note(
        path=path,
        title=Path(path).stem,
        meta=meta,
        body=body,
        links=extract_links(meta, body),
        tags=extract_tags(meta, body),
        tasks=extract_tasks(body),
        mtime=mtime,
    )


def render_note(meta: dict[str, Any], body: str) -> str:
    fm = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, default_flow_style=False).strip()
    return f"---\n{fm}\n---\n{body.lstrip(chr(10))}"


def slugify(title: str) -> str:
    """Filename-safe but human-readable (Obsidian style: keep spaces and case)."""
    s = re.sub(r'[\\/:*?"<>|#^\[\]]', "", title).strip()
    return re.sub(r"\s+", " ", s)[:120] or "untitled"


class Vault:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / ".hive").mkdir(exist_ok=True)

    # ---------- reading ----------
    def iter_files(self) -> Iterator[Path]:
        for p in self.root.rglob("*.md"):
            rel = p.relative_to(self.root)
            if any(part in SKIP_DIRS or part.startswith(".") for part in rel.parts[:-1]):
                continue
            if rel.name in SKIP_FILES:
                continue
            yield p

    def load_all(self) -> list[Note]:
        notes = []
        for p in self.iter_files():
            rel = p.relative_to(self.root).as_posix()
            notes.append(parse_note(p.read_text(encoding="utf-8"), rel, p.stat().st_mtime))
        return notes

    def read(self, rel: str) -> Note:
        p = self.safe_path(rel)
        return parse_note(p.read_text(encoding="utf-8"), rel, p.stat().st_mtime)

    def safe_path(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if self.root.resolve() not in p.parents and p != self.root.resolve():
            raise ValueError(f"path escapes vault: {rel}")
        return p

    # ---------- writing ----------
    def write(self, rel: str, meta: dict[str, Any], body: str, actor: str = "ui", action: str = "write") -> Note:
        p = self.safe_path(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(render_note(meta, body), encoding="utf-8")
        self.audit(actor, action, rel)
        return self.read(rel)

    def write_raw(self, rel: str, text: str, actor: str = "ui") -> Note:
        p = self.safe_path(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        self.audit(actor, "write", rel)
        return self.read(rel)

    def unique_path(self, folder: str, title: str) -> str:
        base = slugify(title)
        rel = f"{folder}/{base}.md"
        n = 2
        while (self.root / rel).exists():
            rel = f"{folder}/{base} {n}.md"
            n += 1
        return rel

    # ---------- audit trail ----------
    def audit(self, actor: str, action: str, target: str, **extra: Any) -> None:
        rec = {"ts": dt.datetime.now().isoformat(timespec="seconds"), "actor": actor, "action": action, "target": target, **extra}
        with open(self.root / ".hive" / "audit.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")

    def read_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        f = self.root / ".hive" / "audit.jsonl"
        if not f.exists():
            return []
        lines = f.read_text(encoding="utf-8").splitlines()[-limit:]
        return [json.loads(x) for x in reversed(lines) if x.strip()]

    # ---------- small JSON state store ----------
    def state(self, name: str, default: Any = None) -> Any:
        f = self.root / ".hive" / f"{name}.json"
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else default

    def set_state(self, name: str, value: Any) -> None:
        (self.root / ".hive" / f"{name}.json").write_text(json.dumps(value, indent=2), encoding="utf-8")
