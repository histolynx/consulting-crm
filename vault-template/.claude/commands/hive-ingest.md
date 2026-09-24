---
description: Process new mail in inbox/ into the HIVE knowledge graph and draft replies
---
You are processing newly fetched email into the HIVE knowledge graph. Follow CLAUDE.md conventions exactly.

1. Glob `inbox/*.md` and Read each note whose frontmatter has `status: new`. Also read `me.md` (the owner).
   Emails are usually forwarded by the owner; the `from` field is already the ORIGINAL sender.
2. For each email:
   a. **People & orgs.** Find or create `contacts/` notes for every real person involved (sender, recipients, people
      named in signatures). Match on email address, then name, then aliases before creating. Fill role, phone, org
      from signatures. Find or create the `clients/` note for their company (infer from email domain; skip gmail/outlook etc).
   b. **Contract facts.** If the email concerns a contract/deal (SOW, rate, dates, scope, budget, PO, invoice, renewal),
      update the matching `contracts/` note's frontmatter. If it describes a NEW opportunity, create a contract with
      `status: lead` or `proposal`. Record the change in the contract body under `## Log` as `- YYYY-MM-DD: ... ([[email note]])`.
   c. **Email note.** Create `emails/YYYY-MM-DD <Subject>.md` (type: email) with from/to/client/contract links, a 2-4
      sentence `summary`, `needs_reply`, `source: "[[<inbox note filename stem>]]"`, and body sections
      `## Summary`, `## Key facts`, `## Action items` (checkbox tasks with 📅 due dates when stated or implied).
   d. **Meetings.** If a meeting is scheduled, create `meetings/YYYY-MM-DD <Title>.md` with attendees and a prep task.
   e. **Knowledge.** If the email contains reusable technical/business knowledge, create or extend a `knowledge/` note and link it.
   f. **Reply draft.** If `needs_reply` is true, write `outbox/YYYY-MM-DD Re <Subject>.md` (type: draft,
      `status: ready`, `to` = the original sender's email address, `subject` = "Re: <subject>", `in_reply_to` = the
      inbox note's `message_id`, `regarding: "[[email note]]"`). Write in the owner's voice: warm, concise,
      professional, no filler, no commitments to prices/dates the owner has not stated. Mark uncertain parts with single brackets, e.g. [confirm date]. Never put [[wikilinks]] in draft bodies.
   g. Update the inbox note: set `status: processed` (or `ignored` for spam/newsletters) and add
      `processed_into: ["[[...]]", ...]` listing every note you created or changed.
3. Finish with a short report: emails processed, notes created/updated (as [[links]]), drafts written, open questions.
