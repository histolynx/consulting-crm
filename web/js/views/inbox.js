import { useEffect, useState } from 'preact/hooks';
import { html, api, openNote, toast, refreshAll, go } from '../lib.js';

const STEP_ICON = { fetch: '✉', ingest: '✦', push_drafts: '✎', time_gaps: '◷', snapshot: '▣', git: '⎇' };

export function Inbox({ tick, health }) {
  const [st, setSt] = useState(null);
  const [inbox, setInbox] = useState([]);
  const [drafts, setDrafts] = useState([]);
  const [emails, setEmails] = useState([]);
  const [job, setJob] = useState(null);
  const load = () => {
    api.get('/api/mail/status').then(setSt);
    api.get('/api/notes', { type: 'inbox', limit: 60 }).then(setInbox);
    api.get('/api/notes', { type: 'draft', limit: 30 }).then(setDrafts);
    api.get('/api/notes', { type: 'email', limit: 30 }).then(setEmails);
    api.get('/api/jobs').then((j) => setJob(j.sync || null));
  };
  useEffect(load, [tick]);
  useEffect(() => {
    if (!job?.running) return;
    const t = setInterval(async () => {
      const j = (await api.get('/api/jobs')).sync;
      setJob(j);
      if (!j.running) { toast('Sync finished'); refreshAll(); }
    }, 2000);
    return () => clearInterval(t);
  }, [job?.running]);

  const sync = async (opts = {}) => {
    try { setJob(await api.post('/api/sync', opts)); } catch (e) { toast(e.message, 'err'); }
  };
  const report = job?.result;

  return html`
  ${health && !health.mail_configured && html`<div class="card" style="margin-bottom:16px;border-color:var(--amber)">
    <h3>✉ Connect Gmail</h3><div>Mail isn't configured yet. See <a style="cursor:pointer" onClick=${() => go('setup')}>Setup</a>: it takes 2 minutes (app password, no Google Cloud project needed).</div></div>`}
  <div class="grid3" style="margin-bottom:16px">
    <div class="kpi" style="--kc:var(--violet)"><div class="l">New in inbox</div><div class="v">${st?.inbox_new ?? '…'}</div><div class="s">${st?.inbox_processed ?? 0} processed</div></div>
    <div class="kpi" style="--kc:var(--pink)"><div class="l">Drafts ready to push</div><div class="v">${st?.drafts_ready ?? '…'}</div><div class="s">land in Gmail → Drafts</div></div>
    <div class="kpi" style="--kc:var(--teal)"><div class="l">Last fetch</div><div class="v" style="font-size:16px">${st?.state?.last_fetch?.replace('T', ' ') || 'never'}</div><div class="s">${health?.gmail_user || ''}</div></div>
  </div>
  <div class="card" style="margin-bottom:16px"><h3>Pipeline <span class="sp"></span>
    <button class="btn sm" disabled=${job?.running} onClick=${() => sync({ fetch: false, push: false, gaps: false })} title="Run the Claude ingestion on notes already in inbox/">✦ Ingest only</button>
    <button class="btn primary sm" disabled=${job?.running} onClick=${() => sync()}>${job?.running ? '⟳ Running…' : '⟳ Full sync'}</button></h3>
    <div class="row" style="gap:6px;margin-bottom:8px">${['fetch Gmail', 'Claude ingests → graph', 'push reply drafts', 'detect missed time', 'snapshot', 'git commit'].map((s, i) => html`${i ? html`<span class="dim">→</span>` : ''}<span class="chip">${s}</span>`)}</div>
    ${job?.running && html`<div class="row"><span class="thinking"><i></i><i></i><i></i></span><span class="muted">Started ${job.started}. Claude may take a minute per batch of emails.</span></div>`}
    ${report && !job.running && (report.error ? html`<div style="color:var(--red)">${report.error}</div>` : html`<div class="list">${(report.steps || []).map((s) => html`<div class="li">
      <span style="width:18px">${STEP_ICON[s.step] || '·'}</span><b style="width:110px">${s.step}</b>
      ${s.ok ? html`<span class="chip green">ok</span>` : html`<span class="chip red">failed</span>`}
      <span class="sp muted" style="font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${s.ok ? (typeof s.result === 'object' ? (Array.isArray(s.result) ? `${s.result.length} item(s)` : (s.result?.text || '').slice(0, 160)) : String(s.result ?? '')) : s.error}</span></div>`)}</div>`)}
  </div>
  <div class="grid2">
    <div class="card"><h3>Raw inbox</h3><div class="list">${inbox.map((m) => html`<div class="li click" onClick=${() => openNote(m.path)}>
      <span class=${'chip ' + (m.status === 'new' ? 'violet' : m.status === 'processed' ? 'green' : '')}>${m.status}</span>
      <div class="sp" style="min-width:0"><div style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${m.subject || m.title}</div><div class="dim" style="font-size:12px">${m.from || ''} · ${m.date || ''}${m.forwarded ? ' · fwd' : ''}</div></div></div>`)}
      ${!inbox.length && html`<div class="empty">Nothing fetched yet. Forward mail to ${health?.gmail_user || 'the hive address'} and hit sync.</div>`}</div></div>
    <div class="col">
      <div class="card"><h3>Reply drafts</h3><div class="list">${drafts.map((d) => html`<div class="li click" onClick=${() => openNote(d.path)}>
        <span class=${'chip ' + (d.status === 'ready' ? 'amber' : 'green')}>${d.status}</span><div class="sp">${d.subject || d.title}<div class="dim" style="font-size:12px">to ${d.to || '?'}</div></div></div>`)}
        ${!drafts.length && html`<div class="empty">No drafts. Claude writes one when an email needs a reply.</div>`}</div></div>
      <div class="card"><h3>Processed emails</h3><div class="list">${emails.map((e) => html`<div class="li click" onClick=${() => openNote(e.path)}>
        <span class="mono dim">${e.date}</span><div class="sp">${e.title.replace(/^\d{4}-\d{2}-\d{2}\s*/, '')}<div class="dim" style="font-size:12px">${e.summary || ''}</div></div>
        ${e.needs_reply && html`<span class="chip amber">reply</span>`}</div>`)}
        ${!emails.length && html`<div class="empty">No processed emails yet.</div>`}</div></div>
    </div>
  </div>`;
}
