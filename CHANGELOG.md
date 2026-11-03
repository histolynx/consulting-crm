# Changelog

## 2026-11-03: v0.6.5, hive doctor, stale-sync warning, CI, MIT licence, atomic writes
- `python -m hive doctor`: checks the venv, the Claude login, Gmail, the last sync's age and that the four Windows scheduled tasks still point at this folder (they store absolute paths; after the 2026-11-01 move the hourly sync just stopped, with nothing turning red). Exit 1 on any failure.
- Dashboard: an amber banner when no sync has finished for 3 hours (`sync_age_hours` and `sync_stale` on `/api/dashboard`). A stopped task never *fails* a sync, so the red banner could never fire for it.
- `scheduler.log` is written as UTF-8 (PowerShell's `*>>` wrote UTF-16, which grep and tail can't read); the old log was rotated to `scheduler-utf16-until-2026-11-03.log`. Re-run `scripts\install-schedule.ps1` to pick this up.
- CI: `.github/workflows/tests.yml` runs the suite on windows-latest (the hash lock is win_amd64/cp314) on push and PR; actions pinned by commit SHA with the 14-day cooldown. Badge in the README. Unverified until the repo is pushed.
- `LICENSE`: MIT. README documents the Orchestrator, Ideas, doctor and the scheduled-task caveat. One version number, `hive.__version__`, shown by FastAPI and `/api/health` (was a stale 0.1.0). `.gitattributes` covers `.in`, `.lock`, `.yml` and `LICENSE`.
- Vault writes (notes and `.hive/*.json` state, incl. the mail checkpoint) go through a sibling temp file + `os.replace`, so a crash or Drive hiccup mid-write can't leave a truncated file. `*.tmp` added to the vault-template gitignore.
- Host guard: the `testserver` exception is gone from production; tests opt in with `create_app(..., allow_hosts=("testserver",))`. Duplicate tag filter in `/api/graph` removed.
- Leak guard ignores corporate suffixes (`Inc.`, `LLC`, …): an unquoted YAML flow list turns `Acme, Inc.` into the aliases `Acme` and `Inc.`, and the latter matched every licence header. `sensitive_terms(vault)` is now testable. Demo data renamed (`Lumen Health`, `Elena Marsh`) so fictional names no longer collide with real vault names. 108 tests.

## 2026-11-03: v0.6.4, dependency refresh, vendor no-cache, mail quarantine
- Deps (monthly recheck, 14-day cooldown, lock from 2026-09-24): FastAPI 0.141.1 → 0.150.0 (brings `opentelemetry-api` 1.45.1 as a new hard dependency), Starlette 1.6.0 → 1.9.0, uvicorn 0.52.4 → 0.54.0, pydantic 2.13.5 → 2.14.1, certifi → 2026.10.19 (GHSA-6q48-6c7w-9gw2, compromised emSign intermediates; not on HIVE's IMAP path, which uses the Windows trust store). JS: DOMPurify 3.4.14 → 3.4.17 (five advisories incl. GHSA-cg2g-xh64-v4q7; none applied to HIVE's default-config `sanitize`, patched anyway), marked 18.0.11 → 18.1.1, force-graph 1.51.4 → 1.51.5, 3d-force-graph 1.80.0 → 1.80.1. Held: Preact 10.29.8 (11.0 is a major and the UI has no test harness), pytest 9.1.1 (9.2.0 inside the cooldown). OSV: 0 advisories against every new version.
- Leak guard (`scripts/check_no_client_data.py`): skips `web/vendor/` like `vault/`. A licence header inside a minified third-party library matched a vault name and would have blocked this commit; vendored files are hash-verified against npm, so nothing private can get in by accident.
- `/vendor` is served `Cache-Control: no-cache` like `/js` and `/css`: a security bump must reach the browser on the next load instead of waiting out the heuristic cache (same class as the v0.6.2 `main.js` bug).
- Mail: one message HIVE couldn't parse or store (odd charset, a filename Windows refuses) left `last_uid` behind it, so every hourly fetch failed on the same message until `mail.json` was edited by hand. Such a message is now quarantined: raw bytes kept at `attachments/<uid>/message.eml`, a visible `status: failed` inbox note the ingest agent skips (counted as `inbox_failed`), an audit line, and the checkpoint moves on. IMAP transport errors still propagate and are retried next run. 102 tests.

## 2026-11-03: v0.6.3, agent sandbox and verified IMAP TLS
- Security: `imaplib.IMAP4_SSL` does **not** verify the server certificate by default (checked on Python 3.14: `CERT_NONE`, no hostname check), so the Gmail app password went to whatever answered at imap.gmail.com on the current network. `imap_login` now passes `ssl.create_default_context()`; a failed verification is reported as such (not as "can't reach Gmail") and the password is never sent. Verified live: Gmail's certificate (Google Trust Services) verifies; `wrong.host.badssl.com` is refused.
- Security: the ingest agent reads untrusted mail with Write/Edit, and nothing stopped a prompt-injected message from making it write `.claude/settings.json` (hooks run commands on the next run), the command prompts, `CLAUDE.md`, `.mcp.json`, `.git/hooks` (HIVE runs `git commit` in the vault), `.obsidian/` plugins or `.hive/` (state and audit log). `claude -p` now runs with `--strict-mcp-config` and `--settings` **deny rules** for those paths (`agent.PROTECTED`); deny rules beat `--allowedTools` and `acceptEdits`, whatever the model is told. `Agent` (the renamed subagent tool) joins the disallowed list. Verified live in a throwaway vault: a write-mode run asked to create `.claude/pwned.md` then `knowledge/ok.md` was refused the first ("directory denied by your permission settings") and allowed the second. 101 tests.

## 2026-11-01: v0.6.2, Ideas area and legislative-acts knowledge graph
- New **Ideas** area (side-project ideas and datasets, each with an idea note saying where its files live): added to `AREAS`, the area hub, the Orchestrator prompt and the vault schema.
- `hive/acts.py` + `python -m hive acts <parsed_dir>`: imports a session's parsed act JSON as typed notes under `library/Ideas/<collection>/`: `act`, `legislator`, `committee`, `topic`. Sponsor bylines are re-parsed from the bill text (the source JSON kept only the first line of multi-line bylines, which split names like "K. / Brown"). Topics are keyword matches on title/subtitle. Generated notes are rewritten only when changed; the idea note is written once and never overwritten. Hub names carry the state ("Sen. Irvin (AR)") so they can't collide with CRM notes.
- Graph view: the four new types get colours and are hidden by default in the full graph (it stays CRM-sized) but shown in a Lens.
- **Ideas page** in the sidebar (no Alt shortcut: all ten are taken): quick-add box (title, markdown text, tags; Ctrl+Enter), one card per idea with where its files live, what its folder holds, topic chips, and "Explore graph" (Lens). `hive/ideas.py`: `add_idea` (one folder per idea, `library/Ideas/<Title>/`, never overwrites) and the listing behind `GET /api/ideas`; `POST /api/idea` for capture.
- **Email capture:** a new sync step (`ideas`, after fetch, before the agent's ingest) turns inbox mail **from the owner's own addresses** (me.md `email` + `other_emails` + the HIVE mailbox) whose subject starts `Idea:` or contains `#idea` into idea notes; subject #hashtags become tags, the body (and a forwarded article) becomes the text, and the inbox note is marked `processed` with `processed_into`. Mail from anyone else is never routed. Forwarded mail now keeps the forwarder's own subject as `wrapper_subject`, so "Idea: Fwd: …" works. Fixed sender parsing for HIVE's `addr <addr>` form (parseaddr returns nothing for it).
- **CLI capture:** `python -m hive idea "<Title>" --file body.md --tags a,b`, used by a user-level `/idea` Claude Code skill (kept in `~/.claude/skills/idea/`, not in this repo, since it holds local paths).
- `Vault.load_all` caches parsed notes by (mtime, size): on Google Drive, file reads were ~3 ms each, so a 1,665-note rebuild took ~8 s after every edit; it is now ~1.3 s (stat only) plus changed files.
- Fix: `/js` and `/css` are now served `Cache-Control: no-cache` (revalidated by ETag). With no header, the browser cached them by file age, so after the update a normal reload kept the weeks-old `main.js` and the Ideas page never appeared in the sidebar. 99 tests.

## 2026-10-29: v0.6.1, folder cleanup (plan, tick, apply, undo)
- `hive/cleanup.py`: **plan** a watched folder (read-only). Each file gets one category: already in HIVE → `<folder>/Processed/`; confident work file (≥60%, no open question) → `<drive_root>/<Area>/<Topic>/` (default `G:/My Drive/Work`); exact duplicate (sha256, newest kept, " (1)" names lose) → `<folder>/_HIVE_Holding/<date>/`; anything else stays put as "needs you".
- **Apply** moves only the ticked ops with a deterministic script (never overwrites: `name (2).ext`) and keeps Orchestrator proposals pointing at the new path. **Undo** reverses a whole run. Nothing is deleted; personal files are never listed or touched. Plans and runs live in `.hive/cleanup/`, with an audit entry for each apply and undo.
- Orchestrator page: "Clean up a folder" card with a grouped, checkbox review modal and per-run Undo. 86 tests.

## 2026-10-29: v0.6.0, HIVE Orchestrator (phase 1)
- `hive/orchestrator.py`: watches work folders (default Downloads + Desktop, depth 3), filters personal files by **name/folder only** (never read; stored only as salted hashes), classifies work files with the agent (text excerpts only; PDFs/Office by name) into **areas** (Consulting, Committee of 100, Yale, MSU, Research, Career), and queues **filing proposals**. Files move only on approve: copy by default, move on request; markdown becomes graph notes under `library/<Area>/<Topic>/`, other files go to `documents/` with a stub note.
- Orchestrator page (cards, clickable questions, area/topic/project edits, bulk-file confident items, watched folders), Windows toast notifications (`hive/notify.py`, built-in WinRT), a 15-minute scheduled task, area hub notes, and schema rules.
- Privacy: orchestrator agent runs write **no logs** (`private=True`); CLI output is counts only; earlier logs were redacted. A cross-process `orchestrate` lock stops overlapping runs. Fixed a CLI refactor that would have run `sync` twice. 83 tests.

## 2026-10-27: v0.5.2, one task, one home
- Tasks are read only from home notes (contracts, projects, opportunities, contacts, clients, meetings, knowledge). Checkboxes in **briefings** and **email notes** are ignored: briefings restated every due task daily, and email notes duplicated the contract's task, which inflated 'Due within 7 days' (292 open, mostly copies).
- The brief prompt writes plain bullets; the ingest prompt writes each checkbox task once, in its home note. 75 tests.

## 2026-10-27: v0.5.1, agent failures are no longer silent
- Bug: when the agent's Claude login expired, `claude` exited 1 but the sync's ingest step still reported ok, so emails piled up unnoticed. Agent errors now **fail the step** (`agent_ok`) with a pointer to `scripts\claude-login.ps1`; the morning brief fails loudly too.
- The dashboard shows a red banner when the last sync had failed steps. `restart-hive.cmd` for a double-click restart. 74 tests.

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

