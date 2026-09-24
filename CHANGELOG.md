# Changelog

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
