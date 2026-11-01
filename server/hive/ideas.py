"""Ideas area: one idea note per folder, library/Ideas/<Title>/<Title>.md, so an idea can grow its own notes and files
(e.g. an imported acts graph) without them being counted against another idea."""
from __future__ import annotations

import datetime as dt
import re
from email.utils import parseaddr
from pathlib import Path
from typing import Any

from .graph import Graph
from .orchestrator import ensure_area_hubs
from .timetrack import _link_target
from .vault import Vault, slugify

GENERATED = ("area", "act", "legislator", "committee", "topic")
IDEA_PREFIX = re.compile(r"^\s*(?:(?:fwd?|fw|re)\s*:\s*)*idea\s*[:\-–—]\s*", re.I)
HASHTAG = re.compile(r"(?<![\w&])#([A-Za-z][\w-]*)")
FWD_PREFIX = re.compile(r"^(?:(?:fwd?|fw)\s*:\s*)+", re.I)


def add_idea(vault: Vault, title: str, text: str = "", tags: list[str] | None = None, source: str | None = None,
             actor: str = "ui") -> str:
    """Create an idea note; never overwrites (a repeated title gets ' 2'). Returns the vault path."""
    title = slugify(title or "")
    if title == "untitled" and not text.strip():
        raise ValueError("an idea needs a title or some text")
    ensure_area_hubs(vault)
    folder = f"library/Ideas/{title}"
    rel = vault.unique_path(folder, title)
    clean = sorted({t.strip().lstrip("#").lower().replace(" ", "-") for t in (tags or []) if t.strip()} | {"idea"})
    meta: dict[str, Any] = {"type": "note", "area": "[[Ideas]]", "status": "idea", "created": dt.date.today().isoformat(),
                            "tags": clean}
    if source:
        meta["source"] = source
    body = f"# {title}\n\n{text.strip()}\n" if text.strip() else f"# {title}\n"
    vault.write(rel, meta, body, actor=actor, action="add-idea")
    return rel


def parse_idea_subject(subject: str) -> tuple[str, list[str]] | None:
    """'Idea: Outbreak graph #aws' or 'Outbreak graph #idea #aws' -> ('Outbreak graph', ['aws']); anything else -> None."""
    tags = [t.lower() for t in HASHTAG.findall(subject or "")]
    if not IDEA_PREFIX.match(subject or "") and "idea" not in tags:
        return None
    title = FWD_PREFIX.sub("", HASHTAG.sub("", IDEA_PREFIX.sub("", subject))).strip(" -:")
    return re.sub(r"\s+", " ", title), [t for t in tags if t != "idea"]


def address(s: str) -> str:
    """Bare lowercase address. mail.to_note writes 'me@x.test <me@x.test>' when there's no display name, which
    parseaddr can't split, so the <...> part wins."""
    m = re.search(r"<([^<>@\s]+@[^<>\s]+)>", s)
    return (m.group(1) if m else parseaddr(s)[1] or s.strip()).lower()


def owner_addresses(vault: Vault, extra: list[str] | None = None) -> set[str]:
    """The owner's own addresses (me.md email + other_emails, plus e.g. the HIVE mailbox). Only these can file ideas."""
    out = {address(a) for a in (extra or []) if a}
    if (vault.root / "me.md").exists():
        m = vault.read("me.md").meta
        others = m.get("other_emails") or []
        out |= {address(str(a)) for a in [m.get("email"), *(others if isinstance(others, list) else [others])] if a}
    return out


def route_idea_emails(vault: Vault, owner: set[str]) -> list[str]:
    """New inbox notes the owner sent with an 'Idea:' subject (or #idea) become idea notes; the inbox note is marked
    processed so the ingest agent skips it. Mail from anyone else is left alone: it's ordinary mail, not an idea."""
    made = []
    inbox = vault.root / "inbox"
    for p in sorted(inbox.glob("*.md")) if inbox.exists() else []:
        rel = p.relative_to(vault.root).as_posix()
        n = vault.read(rel)
        m = n.meta
        if m.get("status") != "new" or m.get("direction", "received") != "received":
            continue
        if address(str(m.get("forwarded_by") or m.get("from") or "")) not in owner:
            continue
        hit = next((r for r in (parse_idea_subject(str(s)) for s in (m.get("wrapper_subject"), m.get("subject")) if s) if r), None)
        if not hit:
            continue
        title, tags = hit
        lines = n.body.strip().split("\n")
        text = "\n".join(lines[1:] if lines and lines[0].startswith("# ") else lines).strip()
        if not title:
            title = next((ln.strip("#> *") for ln in text.split("\n") if ln.strip()), "") or "Untitled idea"
        idea_rel = add_idea(vault, title[:120], text, tags, source=f"[[{Path(rel).stem}]]", actor="mail")
        vault.write(rel, {**m, "status": "processed", "processed_into": [f"[[{Path(idea_rel).stem}]]"]}, n.body,
                    actor="mail", action="route-idea")
        made.append(idea_rel)
    return made


def ideas(graph: Graph) -> list[dict[str, Any]]:
    """Idea notes (area: [[Ideas]]) with where their files live and what each one's folder holds."""
    hub = graph.resolve("Ideas")
    out = []
    for p, n in graph.notes.items():
        if n.type in GENERATED or not n.meta.get("area"):
            continue
        if graph.resolve(_link_target(n.meta["area"]) or "") != hub:
            continue
        folder = p.rsplit("/", 1)[0] + "/"
        inside = [m for q, m in graph.notes.items() if q != p and q.startswith(folder)] if p.startswith("library/Ideas/") else []
        counts: dict[str, int] = {}
        for m in inside:
            counts[m.type] = counts.get(m.type, 0) + 1
        topics = sorted((m for m in inside if m.type == "topic"), key=lambda m: -int(m.meta.get("acts") or 0))
        para = next((b.strip() for b in n.body.split("\n\n") if b.strip() and not b.lstrip().startswith(("#", "|", "-", ">"))), "")
        out.append({"path": p, "name": n.title, "summary": para, "source": n.meta.get("source"), "tags": n.tags,
                    "status": n.meta.get("status"), "created": str(n.meta.get("created") or n.meta.get("imported") or ""),
                    "counts": counts, "topics": [{"path": m.path, "name": m.title, "count": m.meta.get("acts")} for m in topics[:12]]})
    return sorted(out, key=lambda i: (i["created"], i["name"].lower()), reverse=True)
