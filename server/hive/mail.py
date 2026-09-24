"""Gmail over IMAP (stdlib only, app-password auth).

  fetch_new()   -> raw messages land in vault/inbox/ as `type: inbox, status: new` notes
                   (forwarded mail is unwrapped so the *original* sender is recorded)
  push_drafts() -> vault/outbox notes with `status: ready` are appended to [Gmail]/Drafts

Mailbox is opened read-only: HIVE never marks mail as read, moves or deletes it.
Credentials: HIVE_GMAIL_USER / HIVE_GMAIL_APP_PASSWORD in ~/.hive/secrets.env.
"""
from __future__ import annotations

import datetime as dt
import email
import email.policy
import html
import imaplib
import re
import time
from email.message import EmailMessage
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
from pathlib import Path
from typing import Any

from .config import require_gmail_login
from .vault import Vault, slugify


class LoginFailed(RuntimeError):
    pass


def imap_login(user: str, password: str, timeout: float = 20) -> imaplib.IMAP4_SSL:
    """Open an authenticated IMAP session. Raises LoginFailed with a human-readable reason."""
    try:
        imap = imaplib.IMAP4_SSL(IMAP_HOST, timeout=timeout)
    except OSError as e:
        raise LoginFailed(f"Can't reach Gmail ({e}). Check your internet connection.") from e
    try:
        imap.login(user.strip(), password.replace(" ", "").strip())
    except imaplib.IMAP4.error as e:
        msg = str(e)
        hint = ("Gmail rejected the login. Use a 16-character App password (not your normal password), "
                "make sure 2-Step Verification is on and IMAP is enabled.")
        raise LoginFailed(f"{hint} [{msg[:120]}]") from e
    return imap

IMAP_HOST = "imap.gmail.com"
MAX_ATTACHMENT = 20 * 1024 * 1024
FIRST_RUN_DAYS = 30

FWD_MARKERS = re.compile(
    r"^(?:-{5,}\s*Forwarded message\s*-{5,}|Begin forwarded message:|-{3,}\s*Original Message\s*-{3,}|_{20,})\s*$",
    re.I | re.M,
)
HDR = re.compile(r"^\s*\*?(From|Date|Sent|Subject|To|Cc)\*?:\s*(.*)$", re.I)


def html_to_text(s: str) -> str:
    s = re.sub(r"(?is)<(script|style).*?</\1>", "", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h\d>", "\n", s)
    s = re.sub(r"(?i)<li[^>]*>", "\n- ", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def unwrap_forward(body: str) -> dict[str, Any] | None:
    """Find the first forwarded-message block and return its original headers + inner body."""
    m = FWD_MARKERS.search(body)
    if not m:
        return None
    rest = body[m.end():].lstrip("\n").splitlines()
    headers: dict[str, str] = {}
    i = 0
    while i < len(rest):
        line = rest[i]
        if not line.strip():
            if headers:
                i += 1
                break
            i += 1
            continue
        h = HDR.match(line)
        if not h:
            break
        key = h.group(1).lower()
        headers["date" if key == "sent" else key] = h.group(2).strip()
        i += 1
    if "from" not in headers:
        return None
    name, addr = parseaddr(headers["from"])
    return {
        "from_name": name or addr, "from_email": addr.lower(), "date_raw": headers.get("date"),
        "subject": headers.get("subject"), "to": headers.get("to"), "cc": headers.get("cc"),
        "note": body[: m.start()].strip(), "body": "\n".join(rest[i:]).strip(),
    }


def _parse_loose_date(s: str | None) -> str | None:
    if not s:
        return None
    try:
        return parsedate_to_datetime(s).date().isoformat()
    except (TypeError, ValueError, IndexError):
        pass
    cleaned = re.sub(r"\s+at\s+", " ", s).strip()
    for fmt in ("%a, %b %d, %Y %I:%M %p", "%A, %B %d, %Y %I:%M %p", "%b %d, %Y %I:%M %p", "%A, %B %d, %Y %I:%M:%S %p"):
        try:
            return dt.datetime.strptime(cleaned, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_message(raw: bytes) -> dict[str, Any]:
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    text = html_body = None
    attachments: list[tuple[str, bytes]] = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        disp = part.get_content_disposition()
        ctype = part.get_content_type()
        if disp == "attachment" or (disp == "inline" and part.get_filename()):
            data = part.get_payload(decode=True) or b""
            if part.get_filename() and len(data) <= MAX_ATTACHMENT:
                attachments.append((part.get_filename(), data))
            continue
        if ctype == "text/plain" and text is None:
            text = part.get_content()
        elif ctype == "text/html" and html_body is None:
            html_body = part.get_content()
    body = (text or (html_to_text(html_body) if html_body else "")).replace("\r\n", "\n")
    try:
        date = parsedate_to_datetime(msg["Date"]).isoformat() if msg["Date"] else None
    except (TypeError, ValueError):
        date = None
    fname, faddr = parseaddr(str(msg.get("From", "")))
    parsed: dict[str, Any] = {
        "message_id": str(msg.get("Message-ID", "")).strip(), "subject": str(msg.get("Subject", "(no subject)")),
        "from_name": fname or faddr, "from_email": faddr.lower(), "date": date,
        "to": [a for _, a in getaddresses([str(msg.get("To", ""))]) if a],
        "cc": [a for _, a in getaddresses([str(msg.get("Cc", ""))]) if a],
        "body": body, "attachments": attachments, "forwarded": None,
    }
    fwd = unwrap_forward(body)
    if fwd:
        parsed["forwarded"] = fwd
    return parsed


def to_note(parsed: dict[str, Any], uid: str) -> tuple[str, dict[str, Any], str]:
    fwd = parsed["forwarded"]
    orig_from = f"{fwd['from_name']} <{fwd['from_email']}>" if fwd else f"{parsed['from_name']} <{parsed['from_email']}>"
    orig_date = (_parse_loose_date(fwd["date_raw"]) if fwd else None) or (parsed["date"] or "")[:10] or dt.date.today().isoformat()
    subject = (fwd.get("subject") if fwd else None) or parsed["subject"]
    subject = re.sub(r"^(?:(?:fwd?|fw):\s*)+", "", subject, flags=re.I).strip() or "(no subject)"
    meta = {
        "type": "inbox", "status": "new", "uid": uid, "received": parsed["date"], "date": orig_date,
        "subject": subject, "from": orig_from, "forwarded": bool(fwd),
        "forwarded_by": f"{parsed['from_name']} <{parsed['from_email']}>" if fwd else None,
        "to": fwd.get("to") if fwd else ", ".join(parsed["to"]), "cc": (fwd.get("cc") if fwd else ", ".join(parsed["cc"])) or None,
        "message_id": parsed["message_id"], "tags": ["inbox"],
    }
    meta = {k: v for k, v in meta.items() if v not in (None, "")}
    body_parts = [f"# {subject}", ""]
    if fwd and fwd.get("note"):
        body_parts += ["> **Forwarder's note:** " + fwd["note"].replace("\n", "\n> "), ""]
    body_parts.append(fwd["body"] if fwd else parsed["body"])
    rel = f"inbox/{orig_date} {slugify(subject)[:60]} ({uid}).md"
    return rel, meta, "\n".join(body_parts).strip() + "\n"


class Mailbox:
    def __init__(self, vault: Vault):
        self.vault = vault

    def _connect(self) -> imaplib.IMAP4_SSL:
        user, pw = require_gmail_login()
        return imap_login(user, pw)

    def fetch_new(self, limit: int = 200) -> list[str]:
        state = self.vault.state("mail", {})
        imap = self._connect()
        written: list[str] = []
        try:
            typ, data = imap.select("INBOX", readonly=True)
            if typ != "OK":
                raise RuntimeError(f"IMAP select failed: {data}")
            _, uv = imap.response("UIDVALIDITY")
            uidvalidity = (uv[0] or b"").decode() if uv and uv[0] else ""
            if state.get("uidvalidity") != uidvalidity:
                state = {"uidvalidity": uidvalidity, "last_uid": 0}
                since = (dt.date.today() - dt.timedelta(days=FIRST_RUN_DAYS)).strftime("%d-%b-%Y")
                typ, data = imap.uid("SEARCH", None, "SINCE", since)
            else:
                typ, data = imap.uid("SEARCH", None, "UID", f"{int(state['last_uid']) + 1}:*")
            uids = [int(u) for u in (data[0] or b"").split()]
            uids = sorted(u for u in uids if u > int(state.get("last_uid", 0)))[:limit]
            for uid in uids:
                typ, msgdata = imap.uid("FETCH", str(uid), "(BODY.PEEK[])")
                raw = next((x[1] for x in msgdata if isinstance(x, tuple)), None)
                if not raw:
                    continue
                parsed = parse_message(raw)
                rel, meta, body = to_note(parsed, str(uid))
                if parsed["attachments"]:
                    links, saved = [], []
                    for name, blob in parsed["attachments"]:
                        safe = re.sub(r'[\\/:*?"<>|]', "_", name)
                        p = self.vault.root / "attachments" / str(uid) / safe
                        p.parent.mkdir(parents=True, exist_ok=True)
                        p.write_bytes(blob)
                        saved.append(f"attachments/{uid}/{safe}")
                        links.append(f"- [{safe}](../attachments/{uid}/{safe.replace(' ', '%20')})")
                    meta["attachments"] = saved
                    body += "\n## Attachments\n" + "\n".join(links) + "\n"
                self.vault.write(rel, meta, body, actor="mail", action="fetch")
                written.append(rel)
                state["last_uid"] = uid
                self.vault.set_state("mail", state)  # checkpoint after every message
        finally:
            try:
                imap.logout()
            except Exception:  # noqa: BLE001 - logout failure is irrelevant once data is saved
                pass
        state["last_fetch"] = dt.datetime.now().isoformat(timespec="seconds")
        self.vault.set_state("mail", state)
        return written

    def pending_drafts(self) -> list[str]:
        out = []
        for p in sorted((self.vault.root / "outbox").glob("*.md")):
            rel = p.relative_to(self.vault.root).as_posix()
            n = self.vault.read(rel)
            if n.type == "draft" and n.meta.get("status") == "ready":
                out.append(rel)
        return out

    def push_drafts(self) -> list[str]:
        pending = self.pending_drafts()
        if not pending:
            return []
        user, _ = require_gmail_login()
        imap = self._connect()
        pushed = []
        try:
            for rel in pending:
                n = self.vault.read(rel)
                m = EmailMessage()
                m["From"] = user
                m["To"] = str(n.meta.get("to", ""))
                if n.meta.get("cc"):
                    m["Cc"] = str(n.meta["cc"])
                m["Subject"] = str(n.meta.get("subject", ""))
                if n.meta.get("in_reply_to"):
                    m["In-Reply-To"] = str(n.meta["in_reply_to"])
                    m["References"] = str(n.meta["in_reply_to"])
                m.set_content(re.sub(r"^# .*\n+", "", n.body, count=1).strip() + "\n")
                typ, resp = imap.append('"[Gmail]/Drafts"', r"(\Draft)", imaplib.Time2Internaldate(time.time()), m.as_bytes())
                if typ != "OK":
                    raise RuntimeError(f"draft append failed for {rel}: {resp}")
                meta = dict(n.meta)
                meta["status"] = "pushed"
                meta["pushed_at"] = dt.datetime.now().isoformat(timespec="seconds")
                self.vault.write(rel, meta, n.body, actor="mail", action="draft-push")
                pushed.append(rel)
        finally:
            try:
                imap.logout()
            except Exception:  # noqa: BLE001
                pass
        return pushed

    def status(self) -> dict[str, Any]:
        inbox = self.vault.root / "inbox"
        new = processed = 0
        for p in inbox.glob("*.md"):
            n = self.vault.read(p.relative_to(self.vault.root).as_posix())
            if n.meta.get("status") == "new":
                new += 1
            else:
                processed += 1
        return {"state": self.vault.state("mail", {}), "inbox_new": new, "inbox_processed": processed,
                "drafts_ready": len(self.pending_drafts())}


def attachment_path(vault: Vault, rel: str) -> Path:
    return vault.safe_path(rel)
