# ⬢ HIVE: a knowledge-graph CRM for a consulting practice

HIVE is a local-first "hive mind" for running a consulting business: **CRM, contracts pipeline, time tracking,
invoicing and a knowledge graph**, all stored as plain **Obsidian-compatible markdown**. **Claude Code** runs as its
agent: it reads your forwarded email, builds the graph, drafts replies, and answers questions about everything.

```
Gmail (a dedicated inbox) ──IMAP, read-only──▶ vault/inbox/*.md ──claude -p /hive-ingest──▶ contacts · clients · contracts
                                                                                                  emails · meetings · tasks
                                                                                                  knowledge · reply drafts ──▶ Gmail Drafts
Timer / manual time ──▶ vault/time/YYYY-MM-DD.md ──▶ gap detection (emails vs. logged time) ──▶ suggested entries ──▶ invoices
                         ▲
Browser UI (Preact, no build) ◀── FastAPI @127.0.0.1:8787 ◀── graph engine (PageRank · communities · paths · link prediction)
```

## Quick start

```powershell
.\hive.ps1 -Demo     # fictional demo vault (outside Drive), opens http://127.0.0.1:8787
.\hive.ps1           # your real vault (./vault)
.\hive.ps1 -Test     # test suite
```
The first run creates a venv in `%LOCALAPPDATA%\hive\.venv` (outside Google Drive, so thousands of tiny files don't sync)
and installs hash-locked dependencies.

## Pin it to the taskbar (everyday use)
```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-server.ps1   # background server, starts at every login
```
Open http://127.0.0.1:8787 in **Edge** → `⋯` → **Apps → Install HIVE**, then right-click the HIVE taskbar icon → **Pin to taskbar**.
HIVE is an installable PWA (own window, hex-constellation icon, jump-list shortcuts for Ask / Graph / Log time).
After updating the code: `scripts\install-server.ps1 -Restart`. Logs: `%LOCALAPPDATA%\hive\server.log`.

## A separate Claude account for HIVE
`scripts\claude-login.ps1` signs HIVE's agent into its **own** Claude account (a separate `CLAUDE_CONFIG_DIR`),
e.g. the account tied to the hive mailbox. Your interactive Claude Code keeps its own login. Setup shows which account is active.
(claude.ai chats and Projects aren't accessible from Claude Code; export what you need into `vault/knowledge/`.)

## The graph model: markdown is the database
* **Node** = note (identity = filename, like Obsidian). `type:` in frontmatter: client, contact, contract, project,
  meeting, email, note, invoice, timelog, draft, briefing, profile.
* **Edge** = `[[wikilink]]`, *typed by where it appears*: frontmatter key (`client: "[[Acme]]"` → edge `client`),
  Dataview inline field (`Used in:: [[X]]`), or plain body link (`mentions`). `#tags` become tag nodes.
* Algorithms (pure Python, `server/hive/graph.py`): PageRank (hubs), label-propagation communities (clusters),
  BFS shortest path, ego-network "lenses", Adamic-Adar link prediction ("Hive suggests linking"), unlinked mentions.
* One vault for everything; any **lens** (a node plus N hops) can be exported as a standalone Obsidian vault into `exports/`.
* Conventions the agent follows: [vault/CLAUDE.md](vault/CLAUDE.md).

## Features
| View | What it does |
|---|---|
| **Hive** | KPIs (active value, weighted pipeline, hours, unbilled $, outstanding/overdue), Claude's daily briefing, tasks due, cold contacts, contracts ending or over budget, suggested time, activity feed |
| **Graph** | 2D hexagon canvas / 3D WebGL, colour by type or cluster, size by PageRank, lens + depth slider, pathfinder, layer toggles, one-click link suggestions, Obsidian export |
| **Contacts** | People cards with relationship warmth (days since last email/meeting), organisations table |
| **Contracts** | Drag-and-drop pipeline (lead → proposal → negotiating → active → complete), budget burn, days left, unbilled hours |
| **Time** | Header timer, week heatmap, manual entries, **gap detection**: days with client email/meetings but no logged time become *suggested* entries (never invoiced until confirmed) |
| **Invoices** | Draft from confirmed time (hourly/daily) or completed milestones (fixed fee), numbering, sent/paid/void (void releases the time), printable PDF |
| **Inbox** | Full pipeline: fetch → Claude ingest → push reply drafts → time gaps → git commit, with a per-step report |
| **Ask the Hive** | Streaming chat with Claude Code over the vault; read-only by default, "Can edit" mode commits changes to git |
| **Ctrl+K** | Command palette: search every note, create entities, run jobs |

## Gmail setup (about 2 min, no Google Cloud project)
1. On `your-hive-inbox@gmail.com`: enable 2-Step Verification → create an **App password** (myaccount.google.com/apppasswords).
2. Make sure IMAP is enabled in Gmail settings.
3. In HIVE → **Setup** (or the Inbox banner), sign in with the address and app password. HIVE checks the login
   with Gmail first, then stores it **encrypted in Windows Credential Manager** (entry `HIVE:gmail`, bound to your Windows login).
   Untick "Remember" to keep it in memory only until the server restarts. The password is never written to a file and never sent to Claude.
   (For headless setups, `HIVE_GMAIL_USER` + `HIVE_GMAIL_APP_PASSWORD` in `%USERPROFILE%\.hive\secrets.env` still work.)
4. Forward client mail from your personal account. HIVE unwraps Gmail/Outlook forwards so the **original sender** is recorded.

## Automation
`scripts\install-schedule.ps1` registers **HIVE Sync** (hourly) and **HIVE Brief** (07:30) Windows tasks; `-Remove` deletes them.

## Security and supply chain
* Server binds to 127.0.0.1; mutating requests need an `X-Hive` header (blocks cross-site requests) and a local Host header (blocks DNS rebinding).
* The agent runs with **scoped tools**: read = Read/Glob/Grep; write adds Write/Edit. Bash, web and MCP are always denied. Claude never sees mail credentials.
* Every write is appended to `vault/.hive/audit.jsonl`, every agent run is logged to `vault/.hive/agent-runs/`, and every sync or chat edit is a git commit (undo with git).
* Python deps: exact pins, only releases ≥ 14 days old, hash-locked (`scripts/lock-python.ps1`). JS deps: vendored without npm,
  each tarball verified against the registry's SHA-512 integrity and pinned in `web/vendor/vendor.lock.json` (`scripts/vendor.py`).

## Layout: code is public, data is private
```
hive.ps1                launcher              server/hive/     API, graph, CRM, time, invoices, mail, agent, pipeline
web/                    UI (no build)         server/tests/    pytest suite
vault-template/         schema + agent cmds   scripts/         lock deps, vendor JS, demo vault, scheduler
vault/                  YOUR DATA: git-ignored here; its OWN git repo (push it only to a private remote)
```
On first run `hive.ps1` (or `python -m hive init`) scaffolds `vault/` from `vault-template/` and runs `git init` inside it.
Every sync or chat edit commits to the **vault's** repo, never to the code repo, so client data can't end up in a public repo by accident.

## Roadmap ideas
S3 sync of the vault (versioned bucket + KMS) · Bedrock provider option · embeddings for semantic search ·
calendar ingestion for better gap detection · git-commit signals for time · client portal lens (read-only share).
