import { html, openNote } from '../lib.js';

export function Setup({ health }) {
  if (!health) return html`<div class="thinking"><i></i><i></i><i></i></div>`;
  const ok = (b) => html`<span class=${'chip ' + (b ? 'green' : 'red')}>${b ? 'ready' : 'not set'}</span>`;
  return html`<div class="col" style="max-width:900px;gap:16px">
    <div class="card"><h3>Status</h3><table class="t"><tbody>
      <tr><td>Vault</td><td class="mono">${health.vault}</td><td>${ok(true)}</td></tr>
      <tr><td>Claude Code (agent)</td><td class="mono">${health.claude.ok ? health.claude.path : health.claude.error}</td><td>${ok(health.claude.ok)}</td></tr>
      <tr><td>Gmail</td><td class="mono">${health.gmail_user || '—'}</td><td>${ok(health.mail_configured)}</td></tr>
      <tr><td>Secrets file</td><td class="mono">${health.secrets_file}</td><td></td></tr></tbody></table></div>

    <div class="card"><h3>✉ Connect Gmail (≈2 minutes)</h3><ol style="margin:0;padding-left:20px;line-height:1.9">
      <li>Sign in to <b>your-hive-inbox@gmail.com</b> → Google Account → Security → turn on <b>2-Step Verification</b>.</li>
      <li>Open <span class="mono">myaccount.google.com/apppasswords</span>, create one named <b>HIVE</b>, copy the 16 characters.</li>
      <li>Gmail → Settings → <b>Forwarding and POP/IMAP</b> → make sure IMAP is enabled.</li>
      <li>Create <span class="mono">${health.secrets_file}</span> containing:
        <pre class="md" style="background:var(--bg2);padding:10px;border-radius:8px">HIVE_GMAIL_USER=your-hive-inbox@gmail.com
HIVE_GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx</pre></li>
      <li>In your personal Gmail, forward client threads to the hive address (or set a filter to auto-forward from client domains).</li></ol>
      <div class="dim" style="font-size:12px">The mailbox is opened read-only: HIVE never deletes or marks mail. Claude never sees the password: Python fetches mail, Claude only reads the saved markdown.</div></div>

    <div class="card"><h3>⬡ Obsidian</h3><div>Open <span class="mono">${health.vault}</span> as a vault in Obsidian (“Open folder as vault”). Everything HIVE writes is plain markdown with <span class="mono">[[wikilinks]]</span> and YAML, so Obsidian’s graph view, backlinks and Dataview work out of the box. The “⬡ Obsidian” button on any note jumps straight to it.</div></div>

    <div class="card"><h3>⏰ Automation</h3><div>Run <span class="mono">scripts\\install-schedule.ps1</span> to register two Windows scheduled tasks: <b>hourly sync</b> (fetch → ingest → drafts → time gaps → git commit) and a <b>7:30am briefing</b>. You can remove them with <span class="mono">scripts\\install-schedule.ps1 -Remove</span>.</div></div>

    <div class="card"><h3>Your profile</h3><div>Invoices use the <a style="cursor:pointer" onClick=${() => openNote('me.md')}>me.md</a> note (name, business, address, payment instructions, invoice prefix, terms).</div></div>
  </div>`;
}
