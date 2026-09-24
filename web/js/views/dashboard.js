import { useEffect, useState } from 'preact/hooks';
import { html, api, openNote, toast, refreshAll, go, money, compactMoney, hours, ago, Markdown, linkText } from '../lib.js';
import { Hexav } from '../components.js';

function Kpi({ label, value, sub, color, onClick }) {
  return html`<div class="kpi" style=${{ '--kc': color, cursor: onClick ? 'pointer' : 'default' }} onClick=${onClick}>
    <div class="l">${label}</div><div class="v">${value}</div>${sub && html`<div class="s">${sub}</div>`}</div>`;
}

export function Dashboard({ tick }) {
  const [d, setD] = useState(null);
  const [brief, setBrief] = useState(null);
  const [audit, setAudit] = useState([]);
  const [jobs, setJobs] = useState({});

  const load = () => {
    api.get('/api/dashboard').then(setD).catch((e) => toast(e.message, 'err'));
    api.get('/api/briefing/latest').then(setBrief);
    api.get('/api/audit', { limit: 12 }).then(setAudit);
    api.get('/api/jobs').then(setJobs);
  };
  useEffect(load, [tick]);
  useEffect(() => {
    const running = Object.values(jobs).some((j) => j.running);
    if (!running) return;
    const t = setInterval(async () => {
      const js = await api.get('/api/jobs');
      setJobs(js);
      if (!Object.values(js).some((j) => j.running)) { toast('Hive job finished'); refreshAll(); }
    }, 2500);
    return () => clearInterval(t);
  }, [jobs]);

  const toggle = async (t) => { await api.post('/api/tasks/toggle', { path: t.path, line: t.line }); refreshAll(); };
  const runJob = async (name) => {
    try { await api.post(`/api/${name}`); toast(name === 'brief' ? 'Claude is writing your briefing…' : 'Sync started…'); setJobs(await api.get('/api/jobs')); }
    catch (e) { toast(e.message, 'err'); }
  };
  const confirm = async (e, ok) => { await api.post(`/api/time/${e.id}/${ok ? 'confirm' : 'reject'}`); refreshAll(); };

  if (!d) return html`<div class="thinking"><i></i><i></i><i></i></div>`;
  const k = d.kpis;
  const hour = new Date().getHours();
  const greet = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';
  const todayStr = new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' });

  return html`
  <div class="hero">
    <div><div class="muted">${todayStr}</div><h2>${greet}. The hive is humming.</h2></div>
    <span class="sp"></span>
    <button class="btn" disabled=${jobs.sync?.running} onClick=${() => runJob('sync')}>${jobs.sync?.running ? '⟳ Syncing…' : '⟳ Sync mail'}</button>
    <button class="btn primary" disabled=${jobs.brief?.running} onClick=${() => runJob('brief')}>${jobs.brief?.running ? '☀ Writing…' : '☀ Brief me'}</button>
  </div>

  <div class="kpis">
    <${Kpi} label="Active contracts" value=${compactMoney(k.active_value)} sub=${`${k.active_contracts} running`} onClick=${() => go('contracts')} />
    <${Kpi} label="Pipeline (weighted)" value=${compactMoney(k.pipeline_weighted)} sub=${`${k.pipeline_count} deals in play`} color="var(--violet)" onClick=${() => go('contracts')} />
    <${Kpi} label="Hours this week" value=${hours(k.hours_week)} sub=${`${hours(k.hours_month)} this month`} color="var(--blue)" onClick=${() => go('time')} />
    <${Kpi} label="Unbilled" value=${money(k.unbilled_value)} sub="ready to invoice" color="var(--green)" onClick=${() => go('invoices')} />
    <${Kpi} label="Outstanding" value=${money(k.outstanding)} sub=${k.overdue ? `${money(k.overdue)} overdue` : 'nothing overdue'} color=${k.overdue ? 'var(--red)' : 'var(--teal)'} onClick=${() => go('invoices')} />
    <${Kpi} label="Knowledge graph" value=${`${d.graph.nodes}`} sub=${`${d.graph.edges} links · ${d.graph.communities} clusters`} color="var(--pink)" onClick=${() => go('graph')} />
  </div>

  <div class="grid2">
    <div class="col">
      <div class="card"><h3>☀ Briefing<span class="sp"></span>${brief && html`<a onClick=${() => openNote(brief.path)} style="cursor:pointer;text-transform:none;letter-spacing:0">${brief.title}</a>`}</h3>
        ${brief ? html`<${Markdown} src=${brief.body.replace(/^# .*\n/, '')} />` : html`<div class="empty">No briefing yet. Hit “Brief me” and Claude will write one from the graph.</div>`}
      </div>
      <div class="card"><h3>▦ Contracts needing attention</h3>
        ${[...d.ending_soon.map((c) => ({ ...c, why: `ends in ${c.days_left}d` })), ...d.over_budget.map((c) => ({ ...c, why: `${Math.round(c.burn * 100)}% of budget used` }))]
          .map((c) => html`<div class="li click" onClick=${() => openNote(c.path)}><span class="sp">${c.name}</span><span class="chip red">${c.why}</span></div>`)}
        ${!d.ending_soon.length && !d.over_budget.length && html`<div class="empty">All contracts healthy.</div>`}
      </div>
    </div>
    <div class="col">
      <div class="card"><h3>✓ Due within 7 days <span class="sp"></span><span class="dim" style="text-transform:none;letter-spacing:0">${d.tasks_open} open total</span></h3>
        <div class="list">${d.tasks_due.map((t) => {
          const overdue = t.due < d.today;
          return html`<div class="li"><input type="checkbox" onChange=${() => toggle(t)} />
            <div class="sp"><${Markdown} src=${t.text.replace(/📅\s*\d{4}-\d{2}-\d{2}/, '')} cls="inline" /><div class="dim" style="font-size:12px;cursor:pointer" onClick=${() => openNote(t.path)}>${t.note}</div></div>
            <span class=${'chip ' + (overdue ? 'red' : 'amber')}>${overdue ? 'overdue ' : ''}${t.due}</span></div>`;
        })}${!d.tasks_due.length && html`<div class="empty">Nothing due. Nice.</div>`}</div>
      </div>
      <div class="card"><h3>◷ Hive noticed missing time</h3>
        ${d.suggested_time.length ? html`<div class="list">${d.suggested_time.map((e) => html`<div class="li">
            <div class="sp"><b>${hours(e.minutes / 60)}</b> · ${linkText(e.contract)} <span class="dim">on ${e.date}</span>
              <div class="dim" style="font-size:12px">${e.description}</div></div>
            <button class="btn sm primary" onClick=${() => confirm(e, true)}>✓ Keep</button>
            <button class="btn sm danger" onClick=${() => confirm(e, false)}>✕</button></div>`)}</div>`
          : html`<div class="empty">No gaps detected. Every email and meeting has matching time.</div>`}
      </div>
      <div class="card"><h3>◉ Going cold</h3>
        <div class="list">${d.cold_contacts.map((c) => html`<div class="li click" onClick=${() => openNote(c.path)}>
          <${Hexav} name=${c.name} size=${26} /><div class="sp">${c.name}<div class="dim" style="font-size:12px">${c.org || ''}</div></div>
          <span class="chip red">${ago(c.days_since)}</span></div>`)}
          ${!d.cold_contacts.length && html`<div class="empty">Every relationship is warm.</div>`}</div>
      </div>
      <div class="card"><h3>⌁ Activity</h3>
        <div class="list">${audit.map((a) => html`<div class="li" style="font-size:12px">
          <span class="mono dim">${a.ts.slice(5, 16).replace('T', ' ')}</span><span class="chip">${a.actor}</span><span>${a.action}</span>
          <span class="dim" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${a.target}</span></div>`)}</div>
        ${d.last_sync && html`<div class="dim" style="font-size:12px;margin-top:8px">Last sync ${d.last_sync.finished?.replace('T', ' ')} · ${d.last_sync.steps.filter((s) => !s.ok).length ? html`<span style="color:var(--red)">${d.last_sync.steps.filter((s) => !s.ok).length} step(s) failed</span>` : 'all steps ok'}</div>`}
      </div>
    </div>
  </div>`;
}
