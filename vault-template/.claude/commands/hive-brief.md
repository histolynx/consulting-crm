---
description: Write today's HIVE briefing into briefings/YYYY-MM-DD.md
---
Write today's briefing for the owner of this consulting practice.

1. Read `.hive/snapshot.json` (computed dashboard: KPIs, due tasks, cold contacts, contracts ending soon, over-budget
   contracts, suggested time entries). Read `me.md`.
2. Glob `emails/`, `meetings/`, `contracts/` and `outbox/` for items dated in the last 3 days or upcoming 7 days; read what matters.
3. Write `briefings/<today>.md` (type: briefing, date: today) with these sections, each tight and scannable:
   - `## TL;DR` 3 bullets max.
   - `## Today & this week` meetings, due tasks and deadlines as plain bullets (`- Send SOW (due 2026-10-01) → [[Contract]]`). **Never use `- [ ]` checkboxes in a briefing**: briefings restate tasks, and the tasks themselves live in their home notes.
   - `## Money` active contract value, pipeline (weighted), unbilled time, outstanding/overdue invoices, and one concrete
     action (e.g. "invoice [[Contract]] for 14.5h").
   - `## Relationships` who went cold and a one-line suggested touchpoint for each; replies waiting in outbox.
   - `## Time check` suggested (unconfirmed) time entries to review; days that look under-logged.
   - `## Hive insight` one non-obvious connection across the graph (shared contacts, reusable knowledge between
     projects, an upsell or referral opportunity). Cite [[links]].
4. If today's briefing already exists, rewrite it. Reply with the TL;DR only.
