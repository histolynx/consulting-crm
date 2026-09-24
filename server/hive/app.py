"""HIVE HTTP API + static web UI (FastAPI). Bind to 127.0.0.1 only.

Local-app hardening: every mutating /api request must carry `X-Hive: 1` (forces a CORS preflight,
which we never grant, so other websites can't drive the agent), and the Host header must be
localhost/127.0.0.1 (blocks DNS-rebinding).
"""
from __future__ import annotations

import datetime as dt
import json
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import crm, invoices, pipeline, toggl
from .sections import contract_sections
from .agent import Agent, claude_available
from . import creds
from .config import SECRETS_FILE, claude_account, gmail_login, load_settings, read_secrets
from .graph import Graph
from .mail import LoginFailed, Mailbox, imap_login
from .timetrack import TimeTracker
from .vault import Vault

FOLDERS = {"client": "clients", "contact": "contacts", "contract": "contracts", "project": "projects",
           "meeting": "meetings", "note": "knowledge", "email": "emails", "draft": "outbox"}
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}


class Hive:
    """Holds the vault and a cached graph that rebuilds when any note changes."""

    def __init__(self, vault_root: Path):
        self.vault = Vault(vault_root)
        self.tracker = TimeTracker(self.vault)
        self._graph: Graph | None = None
        self._sig: tuple[int, float] | None = None
        self._checked = 0.0
        self._lock = threading.Lock()
        self.jobs: dict[str, dict[str, Any]] = {}

    def _signature(self) -> tuple[int, float]:
        count, latest = 0, 0.0
        for p in self.vault.iter_files():
            count += 1
            latest = max(latest, p.stat().st_mtime)
        return count, latest

    def graph(self) -> Graph:
        with self._lock:
            now = time.monotonic()
            if self._graph is None or now - self._checked > 2.0:
                sig = self._signature()
                self._checked = now
                if sig != self._sig or self._graph is None:
                    self._graph = Graph.build(self.vault.load_all())
                    self._sig = sig
            return self._graph

    def invalidate(self) -> None:
        with self._lock:
            self._graph = None

    def run_job(self, name: str, fn) -> dict[str, Any]:
        job = self.jobs.get(name)
        if job and job.get("running"):
            raise HTTPException(409, f"{name} is already running")
        job = {"running": True, "started": dt.datetime.now().isoformat(timespec="seconds"), "result": None}
        self.jobs[name] = job

        def target() -> None:
            try:
                job["result"] = fn()
            except Exception as e:  # noqa: BLE001
                job["result"] = {"error": f"{type(e).__name__}: {e}"}
            finally:
                job["running"] = False
                job["finished"] = dt.datetime.now().isoformat(timespec="seconds")
                self.invalidate()

        threading.Thread(target=target, daemon=True).start()
        return job


def create_app(vault_root: Path | None = None) -> FastAPI:
    settings = load_settings()
    hive = Hive(vault_root or settings.vault)
    app = FastAPI(title="HIVE", version="0.1.0")
    app.state.hive = hive

    @app.middleware("http")
    async def guard(request: Request, call_next):
        host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]")
        if host not in ALLOWED_HOSTS and host != "testserver":
            return JSONResponse({"detail": "forbidden host"}, status_code=403)
        if request.url.path.startswith("/api") and request.method not in ("GET", "HEAD", "OPTIONS"):
            if request.headers.get("x-hive") != "1":
                return JSONResponse({"detail": "missing X-Hive header"}, status_code=403)
        return await call_next(request)

    def err(e: Exception, code: int = 400):
        raise HTTPException(code, str(e)) from e

    # ---------------- health ----------------
    @app.get("/api/health")
    def health():
        s = read_secrets()
        login = gmail_login()
        return {"vault": str(hive.vault.root), "claude": claude_available(),
                "mail_configured": login is not None, "mail_source": login[2] if login else None,
                "secrets_file": str(SECRETS_FILE), "gmail_user": login[0] if login else s.get("HIVE_GMAIL_USER")}

    # ---------------- gmail login (entered in the GUI, never stored in plaintext) ----------------
    def gmail_status() -> dict:
        login = gmail_login()
        return {"connected": login is not None, "user": login[0] if login else None,
                "source": login[2] if login else None, "suggested_user": read_secrets().get("HIVE_GMAIL_USER")}

    @app.get("/api/gmail")
    def gmail_get():
        return gmail_status()

    @app.post("/api/gmail")
    def gmail_connect(payload: dict = Body(...)):
        user = (payload.get("user") or "").strip()
        pw = (payload.get("password") or "").replace(" ", "").strip()
        if not user or not pw:
            raise HTTPException(400, "email and app password are required")
        try:
            imap_login(user, pw).logout()  # verify BEFORE storing anything
        except LoginFailed as e:
            hive.vault.audit("ui", "gmail-connect-failed", user)
            raise HTTPException(400, str(e)) from e
        creds.session_clear()
        if payload.get("remember", True):
            creds.vault_write(user, pw)
        else:
            creds.vault_delete()
            creds.session_set(user, pw)
        hive.vault.audit("ui", "gmail-connect", user, stored="credential-manager" if payload.get("remember", True) else "session")
        return gmail_status()

    @app.post("/api/gmail/test")
    def gmail_test():
        login = gmail_login()
        if not login:
            raise HTTPException(400, "Gmail isn't connected")
        try:
            imap_login(login[0], login[1]).logout()
        except LoginFailed as e:
            raise HTTPException(400, str(e)) from e
        return {"ok": True, **gmail_status()}

    @app.delete("/api/gmail")
    def gmail_forget():
        creds.session_clear()
        removed = creds.vault_delete()
        hive.vault.audit("ui", "gmail-forget", "", removed=removed)
        return gmail_status()

    @app.get("/api/claude/account")
    def claude_acct():
        return {**claude_account(), "dedicated": bool(read_secrets().get("HIVE_CLAUDE_CONFIG_DIR"))}

    # ---------------- graph ----------------
    @app.get("/api/graph")
    def graph(tags: bool = True, demo: bool = True, root: str | None = None, depth: int = 2,
              hide: str = Query("", description="comma-separated node types to hide")):
        g = hive.graph()
        hidden = {h for h in hide.split(",") if h}
        keep = set(g.ego(root, depth)) if root else set(g.nodes)
        keep = {v for v in keep if (tags or g.nodes[v]["type"] != "tag") and (demo or not g.nodes[v]["demo"])
                and g.nodes[v]["type"] not in hidden}
        if not tags:
            keep = {v for v in keep if g.nodes[v]["type"] != "tag"}
        return g.to_json(keep)

    @app.get("/api/graph/stats")
    def graph_stats():
        return hive.graph().stats()

    @app.get("/api/graph/path")
    def graph_path(a: str, b: str):
        g = hive.graph()
        path = g.shortest_path(a, b)
        return {"path": path, "titles": [g.nodes[p]["title"] for p in path]}

    @app.get("/api/graph/suggest")
    def graph_suggest(node: str | None = None, limit: int = 15):
        g = hive.graph()
        return [{**s, "a_title": g.nodes[s["a"]]["title"], "b_title": g.nodes[s["b"]]["title"]} for s in g.suggest_links(node, limit)]

    # ---------------- notes ----------------
    @app.get("/api/note")
    def note(path: str):
        g = hive.graph()
        if path not in g.notes:
            raise HTTPException(404, f"no note {path}")
        n = g.notes[path]
        raw = hive.vault.safe_path(path).read_text(encoding="utf-8")
        t = lambda p: g.nodes.get(p, {}).get("title", p)  # noqa: E731
        return {"path": path, "title": n.title, "type": n.type, "meta": n.meta, "body": n.body, "raw": raw, "tags": n.tags,
                "tasks": [t_.__dict__ for t_ in n.tasks],
                "outlinks": [{**o, "title": t(o["target"]), "type": g.nodes.get(o["target"], {}).get("type")} for o in g.outlinks(path)],
                "backlinks": [{**b, "title": t(b["source"]), "type": g.nodes.get(b["source"], {}).get("type")} for b in g.backlinks(path)],
                "unlinked_mentions": [{"path": p, "title": t(p)} for p in g.unlinked_mentions(path)],
                "suggestions": [{"path": s["b"], "title": t(s["b"]), "score": s["score"]} for s in g.suggest_links(path, 6)]}

    @app.get("/api/resolve")
    def resolve(target: str):
        p = hive.graph().resolve(target)
        if not p:
            raise HTTPException(404, f"unresolved: {target}")
        return {"path": p}

    @app.put("/api/note")
    def save_note(payload: dict = Body(...)):
        try:
            n = hive.vault.write_raw(payload["path"], payload["text"], actor="ui")
        except (KeyError, ValueError) as e:
            err(e)
        hive.invalidate()
        return {"path": n.path}

    @app.post("/api/note")
    def create_note(payload: dict = Body(...)):
        ntype = payload.get("type", "note")
        title = (payload.get("title") or "").strip()
        if not title:
            raise HTTPException(400, "title required")
        folder = FOLDERS.get(ntype, "knowledge")
        rel = hive.vault.unique_path(folder, title)
        tpl = hive.vault.root / "_templates" / f"{ntype}.md"
        today = dt.date.today().isoformat()
        if tpl.exists() and not payload.get("body") and not payload.get("meta"):
            text = tpl.read_text(encoding="utf-8").replace("{{title}}", title).replace("{{date}}", today)
            n = hive.vault.write_raw(rel, text, actor="ui")
        else:
            meta = {"type": ntype, **(payload.get("meta") or {}), "created": today}
            n = hive.vault.write(rel, meta, payload.get("body") or f"# {title}\n", actor="ui", action="create")
        hive.invalidate()
        return {"path": n.path}

    @app.get("/api/notes")
    def notes_by_type(type: str, limit: int = 200):
        g = hive.graph()
        rows = [{"path": p, "title": n.title, "mtime": n.mtime, **{k: v for k, v in n.meta.items() if not isinstance(v, (list, dict)) or k == "processed_into"}}
                for p, n in g.notes.items() if n.type == type]
        rows.sort(key=lambda r: (str(r.get("date") or ""), r["mtime"]), reverse=True)
        return rows[:limit]

    @app.post("/api/link")
    def link_notes(payload: dict = Body(...)):
        """Accept a suggested link: append `label:: [[B]]` to note A."""
        g = hive.graph()
        a, b = payload.get("a"), payload.get("b")
        label = "".join(ch for ch in payload.get("label", "related") if ch.isalnum() or ch in " _-").strip() or "related"
        if a not in g.notes or b not in g.nodes:
            raise HTTPException(400, "unknown note")
        n = g.notes[a]
        body = n.body.rstrip("\n") + f"\n{label}:: [[{g.nodes[b]['title']}]]\n"
        hive.vault.write(a, n.meta, body, actor="ui", action="link")
        hive.invalidate()
        return {"ok": True}

    @app.get("/api/search")
    def search(q: str, limit: int = 20):
        g = hive.graph()
        ql = q.lower().strip()
        if not ql:
            return []
        hits = []
        for p, d in g.nodes.items():
            title = d["title"].lower()
            n = g.notes.get(p)
            score = 0
            if title == ql:
                score = 100
            elif title.startswith(ql):
                score = 60
            elif ql in title:
                score = 40
            elif n and ql in n.body.lower():
                score = 10
            if score:
                snippet = ""
                if n and ql in n.body.lower():
                    i = n.body.lower().index(ql)
                    snippet = n.body[max(0, i - 50): i + 80].replace("\n", " ")
                hits.append({"path": p, "title": d["title"], "type": d["type"], "score": score + len(g.adj.get(p, ())) * 0.1,
                             "snippet": snippet})
        return sorted(hits, key=lambda h: -h["score"])[:limit]

    # ---------------- CRM ----------------
    @app.get("/api/dashboard")
    def dashboard():
        d = crm.dashboard(hive.graph(), hive.tracker)
        d["last_sync"] = hive.vault.state("last_sync")
        d["timer"] = hive.tracker.timer()
        return d

    @app.get("/api/contacts")
    def contacts():
        return crm.contacts(hive.graph())

    @app.get("/api/clients")
    def clients():
        return crm.clients(hive.graph())

    @app.get("/api/contracts")
    def contracts():
        return crm.contracts(hive.graph(), hive.tracker)

    @app.post("/api/contracts/status")
    def contract_status(payload: dict = Body(...)):
        g = hive.graph()
        n = g.notes.get(payload.get("path", ""))
        if not n or n.type != "contract" or payload.get("status") not in crm.PIPELINE:
            raise HTTPException(400, "need a contract path and a valid status")
        meta = dict(n.meta)
        meta["status"] = payload["status"]
        hive.vault.write(n.path, meta, n.body, actor="ui", action=f"contract-{payload['status']}")
        hive.invalidate()
        return {"ok": True}

    @app.get("/api/tasks")
    def tasks(done: bool = False):
        return crm.tasks(hive.graph(), include_done=done)

    @app.post("/api/tasks/toggle")
    def toggle_task(payload: dict = Body(...)):
        p = hive.vault.safe_path(payload["path"])
        text = p.read_text(encoding="utf-8")
        n = hive.vault.read(payload["path"])
        offset = text.count("\n", 0, len(text) - len(n.body))  # lines of frontmatter before body
        lines = text.split("\n")
        i = offset + int(payload["line"])
        if i >= len(lines) or "[" not in lines[i]:
            raise HTTPException(409, "task line moved; refresh")
        if "- [ ]" in lines[i] or "* [ ]" in lines[i]:
            lines[i] = lines[i].replace("[ ]", f"[x]", 1) + f" ✅ {dt.date.today()}"
        else:
            lines[i] = lines[i].replace("[x]", "[ ]", 1).replace("[X]", "[ ]", 1).split(" ✅ ")[0]
        hive.vault.write_raw(payload["path"], "\n".join(lines), actor="ui")
        hive.invalidate()
        return {"ok": True}

    # ---------------- time ----------------
    @app.get("/api/time")
    def time_entries(start: str | None = None, end: str | None = None):
        es = hive.tracker.all_entries()
        if start:
            es = [e for e in es if e["date"] >= start]
        if end:
            es = [e for e in es if e["date"] <= end]
        return sorted(es, key=lambda e: (e["date"], str(e.get("start") or "")), reverse=True)

    @app.get("/api/time/summary")
    def time_summary():
        return hive.tracker.summary(hive.graph())

    @app.post("/api/time")
    def add_time(payload: dict = Body(...)):
        try:
            date = payload.pop("date", dt.date.today().isoformat())
            e = hive.tracker.add(date, payload)
        except (ValueError, TypeError) as e_:
            err(e_)
        hive.invalidate()
        return e

    @app.patch("/api/time/{entry_id}")
    def patch_time(entry_id: str, payload: dict = Body(...)):
        try:
            e = hive.tracker.update(entry_id, payload)
        except KeyError as e_:
            err(e_, 404)
        hive.invalidate()
        return e

    @app.delete("/api/time/{entry_id}")
    def delete_time(entry_id: str):
        try:
            hive.tracker.delete(entry_id)
        except KeyError as e_:
            err(e_, 404)
        hive.invalidate()
        return {"ok": True}

    @app.post("/api/time/{entry_id}/confirm")
    def confirm_time(entry_id: str):
        e = hive.tracker.confirm(entry_id)
        hive.invalidate()
        return e

    @app.post("/api/time/{entry_id}/reject")
    def reject_time(entry_id: str):
        hive.tracker.reject(entry_id)
        hive.invalidate()
        return {"ok": True}

    @app.get("/api/time/gaps")
    def gaps(days: int = 14):
        return hive.tracker.detect_gaps(hive.graph(), days)

    @app.post("/api/time/gaps/apply")
    def apply_gaps(days: int = 14):
        added = hive.tracker.apply_gaps(hive.graph(), days)
        hive.invalidate()
        return added

    @app.get("/api/timer")
    def timer():
        return {"timer": hive.tracker.timer()}

    @app.post("/api/timer/start")
    def timer_start(payload: dict = Body(...)):
        try:
            return hive.tracker.start_timer(payload.get("contract"), payload.get("description", ""),
                                            section=payload.get("section") or None, billable=payload.get("billable", True))
        except ValueError as e:
            err(e, 409)

    @app.post("/api/time/import/preview")
    def toggl_preview(payload: dict = Body(...)):
        try:
            p = toggl.plan(payload.get("csv", ""), hive.graph(), hive.tracker, payload.get("project_map"))
        except ValueError as e:
            err(e)
        p["projects"] = sorted({i["contract"] or "" for i in p["items"]} | set(p["unmapped_projects"]))
        p["sample"] = p.pop("items")[:8]
        return p

    @app.post("/api/time/import")
    def toggl_import(payload: dict = Body(...)):
        try:
            out = toggl.run(payload.get("csv", ""), hive.graph(), hive.tracker, payload.get("project_map"),
                            remember=payload.get("remember", True))
        except ValueError as e:
            err(e)
        hive.invalidate()
        return out

    @app.post("/api/contracts/section")
    def contract_section(payload: dict = Body(...)):
        """Add (or with remove=true, delete) a named section on a contract; sections are time-entry tags."""
        g = hive.graph()
        n = g.notes.get(payload.get("path", ""))
        name = (payload.get("name") or "").strip()
        if not n or n.type != "contract" or not name:
            raise HTTPException(400, "need a contract path and a section name")
        meta = dict(n.meta)
        secs = [s for s in contract_sections(meta) if s["name"].lower() != name.lower()]
        if not payload.get("remove"):
            s = {"name": name}
            if payload.get("budget_hours"):
                s["budget_hours"] = float(payload["budget_hours"])
            match = [m.strip() for m in (payload.get("match") or []) if m.strip()]
            if match:
                s["match"] = match
            secs.append(s)
        meta["sections"] = [{k: v for k, v in s.items() if v not in (None, [], "")} for s in secs]
        hive.vault.write(n.path, meta, n.body, actor="ui", action="contract-section")
        hive.invalidate()
        return {"sections": meta["sections"]}

    @app.post("/api/timer/stop")
    def timer_stop():
        e = hive.tracker.stop_timer()
        hive.invalidate()
        return {"entry": e}

    # ---------------- invoices ----------------
    @app.get("/api/invoices")
    def invoice_list():
        return invoices.summary(hive.graph())

    @app.post("/api/invoices")
    def invoice_create(payload: dict = Body(...)):
        try:
            inv = invoices.generate(hive.vault, hive.graph(), hive.tracker, payload["contract"], payload["start"], payload["end"])
        except (KeyError, ValueError) as e:
            err(e)
        hive.invalidate()
        return inv

    @app.post("/api/invoices/status")
    def invoice_status(payload: dict = Body(...)):
        try:
            inv = invoices.set_status(hive.vault, hive.graph(), payload["path"], payload["status"], hive.tracker)
        except (KeyError, ValueError) as e:
            err(e)
        hive.invalidate()
        return inv

    @app.get("/api/profile")
    def profile():
        return invoices.profile(hive.graph())

    # ---------------- mail / jobs / agent ----------------
    @app.get("/api/mail/status")
    def mail_status():
        return Mailbox(hive.vault).status()

    @app.post("/api/sync")
    def sync(payload: dict = Body(default={})):
        opts = {k: bool(payload.get(k, True)) for k in ("fetch", "ingest", "push", "gaps")}
        return hive.run_job("sync", lambda: pipeline.sync(hive.vault, **opts))

    @app.post("/api/brief")
    def brief():
        return hive.run_job("brief", lambda: pipeline.brief(hive.vault))

    @app.get("/api/jobs")
    def jobs():
        return hive.jobs

    @app.get("/api/briefing/latest")
    def latest_briefing():
        files = sorted((hive.vault.root / "briefings").glob("*.md"))
        if not files:
            return None
        n = hive.vault.read(files[-1].relative_to(hive.vault.root).as_posix())
        return {"path": n.path, "title": n.title, "body": n.body, "meta": n.meta}

    @app.post("/api/ask")
    def ask(payload: dict = Body(...)):
        q = (payload.get("question") or "").strip()
        if not q:
            raise HTTPException(400, "question required")
        mode = "write" if payload.get("mode") == "write" else "read"

        def gen():
            for ev in Agent(hive.vault).stream(q, mode=mode, task="ask", session_id=payload.get("session_id")):
                yield f"data: {json.dumps(ev)}\n\n"
            if mode == "write":
                hive.invalidate()
                try:
                    sha = pipeline.git_commit(hive.vault, f"hive chat edit: {q[:60]}")
                    if sha:
                        yield f"data: {json.dumps({'kind': 'commit', 'sha': sha})}\n\n"
                except Exception as e:  # noqa: BLE001 - surfaced to the UI, not swallowed
                    yield f"data: {json.dumps({'kind': 'error', 'text': f'edits saved but not committed: {e}'})}\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @app.get("/api/audit")
    def audit(limit: int = 100):
        return hive.vault.read_audit(limit)

    @app.post("/api/export")
    def export(payload: dict = Body(...)):
        name = "".join(ch for ch in payload.get("name", "") if ch.isalnum() or ch in " -_").strip()
        if not name:
            raise HTTPException(400, "name required")
        out = hive.vault.root.parent / "exports" / name
        try:
            return pipeline.export_lens(hive.vault, payload["root"], int(payload.get("depth", 2)), out)
        except (ValueError, FileExistsError, KeyError) as e:
            err(e)

    # ---------------- files + static UI ----------------
    @app.get("/vault/{path:path}")
    def vault_file(path: str):
        try:
            p = hive.vault.safe_path(path)
        except ValueError as e:
            err(e, 403)
        if not p.is_file():
            raise HTTPException(404)
        return FileResponse(p)

    web = settings.web
    app.mount("/vendor", StaticFiles(directory=web / "vendor"), name="vendor")
    app.mount("/js", StaticFiles(directory=web / "js"), name="js")
    app.mount("/css", StaticFiles(directory=web / "css"), name="css")
    app.mount("/icons", StaticFiles(directory=web / "icons"), name="icons")

    @app.get("/manifest.webmanifest")
    def manifest():
        return FileResponse(web / "manifest.webmanifest", media_type="application/manifest+json")

    @app.get("/sw.js")
    def service_worker():
        return FileResponse(web / "sw.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})

    @app.get("/")
    def index():
        return FileResponse(web / "index.html", headers={"Cache-Control": "no-cache"})

    return app
