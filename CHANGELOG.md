# Changelog

## 2026-10-09: v0.5.0, Sent mail, sync lock, opportunities
- Mail fetch reads **Sent Mail** as well as Inbox (read-only, separate checkpoint, `s`-prefixed ids). Notes carry `direction`, and the ingest prompt treats sent mail as outreach: contacts are the recipients, no reply drafts.
- **Cross-process sync lock** (`.hive/sync.lock`, stale after 60 min): the UI job and the scheduled CLI run can never ingest at the same time.
- New **opportunity** note type (`opportunities/`) for jobs and recruiter outreach, kept out of the consulting pipeline.
- Hourly sync + 7:30 briefing scheduled. Title-bar strip (v0.4.1). 73 tests.

## 2026-10-05: v0.4.0, record sent invoices, attach documents, dated payments
- `invoices.record()` / `POST /api/invoices/record`: record an invoice made or sent outside HIVE, exactly as sent (own number, lines, dates); stamps the covered entries; stores a line-hours vs entry-hours **reconciliation** and any hours deliberately not billed.
- `POST /api/invoices/attach`: store the PDF under `documents/<client>/invoices/` (base64 JSON, no new dependency); 📎 opens it from the list and the preview.
- Sent/paid can be **backdated** and payments take an optional reference. The list shows Sent and Paid columns, with a show-void toggle.
- UI: **Record a sent invoice** form (period and section picker, fill lines from hours, editable lines, mismatch warning, PDF upload). Malformed payloads get a 400, not a 500. 71 tests.

## 2026-09-28: v0.3.2, smarter gap detection
- Gap suggestions only for **active** contracts, and only for dates **inside the contract term** (start/end). Pre-sales emails on unsigned deals or before a start date no longer produce billable-time suggestions. 68 tests.

## 2026-09-24: v0.3.1, section billing rules + name
- Sections support `bill_as` (roll hours into another section's invoice line; the timesheet keeps the original section) and `overflow_as` (hours past budget, counted across invoices, go on a separate line).
- Time page shows billed hours, what rolls in, and over-budget status. HIVE = **Hub for Independent Venture Ecosystem** (sidebar, app manifest, README). 66 tests.

## 2026-09-24: v0.3.0, contract sections, Toggl-style tracker, Toggl import
- **Contract sections** (`sections:` with `budget_hours` and `match` tags) act as time-entry tags; add or remove them from the tracker ("+ section").
  Hours roll up per section against the SOW budget (Time page burn bars; `/api/contracts` → `sections`).
- **Toggl-style tracker bar** on Time: description, contract, section chips, billable toggle, live clock, big start/stop; ▶ "continue" on any entry; timer carries section and billable.
- **Toggl CSV import** (`hive/toggl.py`, `/api/time/import[/preview]`): Detailed export only (a Summary export is refused with instructions),
  project→contract mapping remembered in `toggl_projects`, tag→section via `match`, exact seconds kept, idempotent via `toggl_id`.
- **Invoices** now have one line per section plus a dated **timesheet** (the CSA requires both monthly); the printable invoice includes the timesheet page.
- `sections.py` split out (avoids a crm↔invoices import cycle). `_intake/` drop folder is ignored by the graph. 64 tests.

## 2026-09-24: v0.2.1, Gmail sign-in from the GUI
- Gmail sign-in form (Setup and Inbox): verifies against Gmail IMAP **before** storing; saves to Windows Credential Manager
  (`HIVE:gmail`, via stdlib ctypes → advapi32) or memory-only for the session. Test / Sign out buttons.
- `config.gmail_login()` resolves one source (secrets file pair → session → Credential Manager); clear error pointing to Setup when missing.
- `/api/gmail` GET/POST/DELETE and `/api/gmail/test`; password never returned, logged or passed to the agent.
- Local `secrets.env` no longer holds a password line. 57 tests (new `test_creds.py`, includes a real Credential Manager round trip).

## 2026-09-24: v0.2.0, desktop app and separate Claude account
- **Logo:** "Hex Constellation" (amber hex + 4-node graph): `web/icons/hive.svg`, PNGs 16–512, multi-size `hive.ico` (`scripts/make_ico.py`).
- **Installable PWA:** manifest (standalone window, jump-list shortcuts), network-first service worker with an "asleep" page when the server is down.
- **Background server:** `scripts/install-server.ps1` registers the "HIVE Server" logon task (pythonw, no console, auto-restart, log in `%LOCALAPPDATA%\hive\server.log`). Registered and started on this PC.
- **Dedicated Claude login:** `HIVE_CLAUDE_CONFIG_DIR` + `scripts/claude-login.ps1`; agent subprocesses use it; `/api/claude/account` and the Setup page show the active account. Missing config dir raises an error instead of silently falling back.
- `secrets.env` reader tolerates the BOM that PowerShell 5 writes; demo runs on port 8788 so it never clashes with the real app.
- Tests: 53 passing (new `test_config.py`).

## 2026-09-24: v0.1.1, public code / private data split
- Code repo is published to GitHub (public); `vault/` is git-ignored and is now its **own** repo, pushed to a separate private repo.
- `vault-template/` (schema, agent commands, note templates, placeholder profile) ships publicly; `python -m hive init` scaffolds a vault from it.
- `git_commit` now commits inside the vault repo, raises `NotARepo` instead of skipping silently, and ignores audit-log-only changes (fixes a commit on every sync).
- Personal email addresses removed from public files; commit author set to the GitHub noreply identity.
- Tests: 50 passing (new `test_pipeline.py`).

## 2026-09-24: v0.1.0, initial build (Claude Code session)

**Decisions (from the ideation Q&A):** local-first desktop; markdown-with-tags as the graph (S3 later); custom graph UI
plus Obsidian compatibility; Claude Code as the agent (no API key); local web app; email agent auto-writes and drafts replies;
built-in time tracker (Toggl dropped); draft invoices; dark amber "hive" theme; vault in this Drive folder under git.

**Added**
- `server/hive`: vault parser (frontmatter, typed wikilinks, inline fields, tags, tasks), graph engine (PageRank,
  communities, shortest path, ego lenses, Adamic-Adar suggestions, unlinked mentions), CRM views and dashboard,
  time tracker with timer and email/meeting-based gap detection, invoicing (hourly/daily/fixed milestones, void releases time),
  Gmail IMAP fetch (read-only, forward unwrapping, attachments) and draft push, Claude Code headless bridge (scoped tools,
  streaming, run logs, kill on disconnect), sync/brief pipelines with git commits, FastAPI app with CSRF/DNS-rebinding guards.
- `web/`: Preact + htm UI with no build step: dashboard, 2D/3D graph explorer, contacts, drag-drop contracts board, time, invoices
  (printable), inbox pipeline, Ask the Hive chat, setup, Ctrl+K palette, note drawer with backlinks and link suggestions.
- `vault/`: `CLAUDE.md` schema, `/hive-ingest` and `/hive-brief` agent commands, templates, `me.md` profile.
- `scripts/`: hash-locked Python resolver (14-day cooldown), verified JS vendoring, demo vault generator, Windows scheduler.
- 46 pytest tests; verified end-to-end with the real Claude CLI (read-only ask) and headless-browser screenshots.

**Fixed during build:** inline fields with spaces; invoice client alias resolution; future meetings counted as "last contact";
schema-example links in CLAUDE.md creating ghost nodes; graph clusters drifting apart (custom gravity force); link suggestions
limited to durable entities.

