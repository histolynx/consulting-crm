---
type: system
tags: [hive, system]
---
# HIVE vault conventions (agent + human reference)

This folder is a markdown **property graph**. Every note is a node; every `[[wikilink]]` is an edge.
The edge's *type* is the frontmatter key (or inline `field:: [[x]]`) it appears under; plain body links are `mentions`.
It opens directly in Obsidian. Never break these rules:

1. **Filenames are identities.** `contacts/Jane Doe.md` is referenced as `[[Jane Doe]]`. Before creating a note,
   Glob/Grep for an existing one (check `aliases` and `email` too). Update rather than duplicate.
2. **Frontmatter is YAML** with a `type`. Link values are quoted strings: `client: "[[Acme Corp]]"`.
3. **Dates** are ISO `YYYY-MM-DD`. Money is a plain number plus `currency` (default USD).
4. **Tasks** are checkboxes with an optional due date: `- [ ] Send revised SOW 📅 2026-10-01 [[Acme Corp]]`.
5. Tags are lowercase kebab-case (`#data-platform`, `#warm-lead`). Prefer links for entities, tags for themes.
6. Never delete notes. Never edit `time/` or `invoices/` files (the app owns them). Never touch `.hive/`.
7. Anything uncertain goes in the note as `> [!question] ...` rather than being guessed.

## Node types and folders

| type | folder | key fields |
|---|---|---|
| profile | `me.md` | name, business, email, phone, address, payment_instructions, invoice_prefix, default_terms_days |
| client | clients/ | industry, website, status (prospect/active/past), aliases |
| contact | contacts/ | name, org: "[[Client]]", role, email, phone, linkedin, relationship (champion/decision-maker/technical/referrer/other), last_contact, aliases |
| contract | contracts/ | client, status (lead/proposal/negotiating/active/paused/complete/lost), value, rate, rate_unit (hour/day/fixed), currency, start, end, budget_hours, payment_terms_days, probability, expected_close, next_step, stakeholders: ["[[Person]]"], sow, milestones: [{name, amount, due, status}] |
| project | projects/ | contract, client, status, stack: ["[[Tech]]"] |
| meeting | meetings/ | date, duration (minutes), attendees: ["[[Person]]"], client, contract |
| email | emails/ | date, from: "[[Person]]", to: ["[[Person]]"], client, contract, summary, source: "[[inbox note]]", needs_reply (bool) |
| note | knowledge/ | free-form knowledge: techniques, tools, reusable IP; link to where it was used |
| draft | outbox/ | to (email address), cc, subject, in_reply_to (message_id), status (ready/pushed), regarding: "[[email note]]" |
| briefing | briefings/ | date |
| inbox | inbox/ | raw fetched mail (status new/processed/ignored), written by the app |
| timelog / invoice | time/, invoices/ | owned by the app |

Filename patterns: emails `emails/YYYY-MM-DD Subject.md`; meetings `meetings/YYYY-MM-DD Title.md`;
drafts `outbox/YYYY-MM-DD Re Subject.md`; contacts `contacts/First Last.md`; clients by common company name.
