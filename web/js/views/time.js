import { useEffect, useState } from 'preact/hooks';
import { html, api, openNote, toast, refreshAll, hours, today, linkText } from '../lib.js';

function weekDays(startIso) {
  const s = new Date(startIso + 'T00:00:00');
  return [...Array(7)].map((_, i) => { const d = new Date(s); d.setDate(s.getDate() + i); return d.toLocaleDateString('en-CA'); });
}

function EntryRow({ e, contracts }) {
  const [edit, setEdit] = useState(false);
  const [f, setF] = useState({});
  const start = () => { setF({ date: e.date, contract: linkText(e.contract) || '', start: e.start || '', end: e.end || '', hours: (e.minutes / 60).toFixed(2), description: e.description || '', billable: e.billable !== false }); setEdit(true); };
  const save = async () => {
    const patch = { date: f.date, contract: f.contract ? `[[${f.contract}]]` : null, description: f.description, billable: f.billable };
    if (f.start && f.end) Object.assign(patch, { start: f.start, end: f.end });
    else Object.assign(patch, { start: null, end: null, minutes: Math.round(parseFloat(f.hours) * 60) });
    try { await api.patch(`/api/time/${e.id}`, patch); setEdit(false); refreshAll(); } catch (err) { toast(err.message, 'err'); }
  };
  const del = async () => { await api.del(`/api/time/${e.id}`); toast('Entry deleted'); refreshAll(); };
  if (edit) {
    const set = (k) => (ev) => setF({ ...f, [k]: ev.target.type === 'checkbox' ? ev.target.checked : ev.target.value });
    return html`<tr><td colspan="6"><div class="row">
      <input class="input" type="date" style="width:140px" value=${f.date} onInput=${set('date')} />
      <select class="select" style="width:200px" value=${f.contract} onChange=${set('contract')}><option value="">No contract</option>${contracts.map((c) => html`<option>${c.name}</option>`)}</select>
      <input class="input" type="time" style="width:110px" value=${f.start} onInput=${set('start')} /><input class="input" type="time" style="width:110px" value=${f.end} onInput=${set('end')} />
      <span class="dim">or</span><input class="input" style="width:80px" value=${f.hours} onInput=${set('hours')} title="hours (used when start/end empty)" />
      <input class="input" style="flex:1;min-width:160px" value=${f.description} onInput=${set('description')} />
      <label class="row muted" style="gap:4px"><input type="checkbox" checked=${f.billable} onChange=${set('billable')} />billable</label>
      <button class="btn primary sm" onClick=${save}>Save</button><button class="btn ghost sm" onClick=${() => setEdit(false)}>Cancel</button></div></td></tr>`;
  }
  const sugg = e.status === 'suggested';
  return html`<tr style=${sugg ? { background: 'rgba(166,140,255,.07)' } : null}>
    <td class="mono dim">${e.start ? `${e.start}–${e.end}` : ''}</td>
    <td class="num"><b>${hours(e.minutes / 60)}</b></td>
    <td>${e.contract ? html`<a style="cursor:pointer" onClick=${async () => { try { openNote((await api.get('/api/resolve', { target: linkText(e.contract) })).path); } catch { toast('Contract note not found', 'err'); } }}>${linkText(e.contract)}</a>` : html`<span class="dim">—</span>`}</td>
    <td>${e.description || ''} ${e.billable === false && html`<span class="chip">non-billable</span>`} ${e.invoice && html`<span class="chip green">${linkText(e.invoice)}</span>`}</td>
    <td>${sugg ? html`<span class="chip violet">suggested</span>` : html`<span class="chip dim">${e.source}</span>`}</td>
    <td class="right" style="white-space:nowrap">${sugg && html`<button class="btn sm primary" onClick=${async () => { await api.post(`/api/time/${e.id}/confirm`); refreshAll(); }}>✓</button> <button class="btn sm danger" onClick=${async () => { await api.post(`/api/time/${e.id}/reject`); refreshAll(); }}>✕</button> `}
      ${!e.invoice && html`<button class="btn ghost sm" onClick=${start}>edit</button><button class="btn ghost sm danger" onClick=${del}>del</button>`}</td></tr>`;
}

export function TimeView({ tick }) {
  const [entries, setEntries] = useState([]);
  const [sum, setSum] = useState(null);
  const [contracts, setContracts] = useState([]);
  const [gaps, setGaps] = useState([]);
  const [f, setF] = useState({ date: today(), contract: '', start: '', end: '', hours: '', description: '', billable: true });
  const load = () => {
    const from = new Date(); from.setDate(from.getDate() - 45);
    api.get('/api/time', { start: from.toLocaleDateString('en-CA') }).then(setEntries);
    api.get('/api/time/summary').then(setSum);
    api.get('/api/contracts').then((cs) => setContracts(cs.filter((c) => c.status !== 'lost')));
    api.get('/api/time/gaps').then(setGaps);
  };
  useEffect(load, [tick]);

  const add = async () => {
    const body = { date: f.date, contract: f.contract || null, description: f.description, billable: f.billable, source: 'manual' };
    if (f.start && f.end) Object.assign(body, { start: f.start, end: f.end });
    else if (f.hours) body.minutes = Math.round(parseFloat(f.hours) * 60);
    else return toast('Enter start+end or hours', 'err');
    try { await api.post('/api/time', body); toast('Logged'); setF({ ...f, start: '', end: '', hours: '', description: '' }); refreshAll(); }
    catch (e) { toast(e.message, 'err'); }
  };
  const scan = async () => { const r = await api.post('/api/time/gaps/apply'); toast(`${r.length} suggested entr${r.length === 1 ? 'y' : 'ies'} added`); refreshAll(); };
  const set = (k) => (ev) => setF({ ...f, [k]: ev.target.type === 'checkbox' ? ev.target.checked : ev.target.value });

  const days = sum ? weekDays(sum.week_start) : [];
  const rows = sum ? Object.entries(sum.week_grid) : [];
  const title = (p) => contracts.find((c) => c.path === p)?.name || p.replace(/^contracts\/|\.md$/g, '');
  const maxCell = Math.max(1, ...rows.flatMap(([, v]) => Object.values(v)));
  const byDate = {};
  entries.forEach((e) => (byDate[e.date] ||= []).push(e));

  return html`
  <div class="grid2" style="margin-bottom:16px">
    <div class="card"><h3>This week <span class="sp"></span><span style="color:var(--amber2);font-size:16px;letter-spacing:0">${sum ? hours(sum.week_total) : ''}</span></h3>
      <div style="overflow-x:auto"><table class="t"><thead><tr><th>Contract</th>${days.map((d) => html`<th class="num">${new Date(d + 'T00:00').toLocaleDateString('en-US', { weekday: 'short' })}</th>`)}<th class="num">Σ</th></tr></thead>
      <tbody>${rows.map(([p, v]) => html`<tr><td style="max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${title(p)}</td>${days.map((d) => {
        const h = v[d] || 0;
        return html`<td class="num" style=${{ background: h ? `rgba(245,165,36,${0.12 + 0.5 * h / maxCell})` : 'transparent', color: h ? '#fff' : 'var(--dim)' }}>${h ? h.toFixed(1) : '·'}</td>`;
      })}<td class="num"><b>${Object.values(v).reduce((a, b) => a + b, 0).toFixed(1)}</b></td></tr>`)}
      ${!rows.length && html`<tr><td colspan="9" class="empty">No confirmed time this week.</td></tr>`}</tbody></table></div>
    </div>
    <div class="card"><h3>Log time</h3>
      <div class="formgrid">
        <label class="f">Date<input class="input" type="date" value=${f.date} onInput=${set('date')} /></label>
        <label class="f">Contract<select class="select" value=${f.contract} onChange=${set('contract')}><option value="">No contract</option>${contracts.map((c) => html`<option>${c.name}</option>`)}</select></label>
        <label class="f">Start<input class="input" type="time" value=${f.start} onInput=${set('start')} /></label>
        <label class="f">End<input class="input" type="time" value=${f.end} onInput=${set('end')} /></label>
        <label class="f">…or hours<input class="input" placeholder="1.5" value=${f.hours} onInput=${set('hours')} /></label>
      </div>
      <div class="row" style="margin-top:10px;flex-wrap:nowrap"><input class="input" placeholder="What did you do?" value=${f.description} onInput=${set('description')} onKeyDown=${(e) => e.key === 'Enter' && add()} />
        <label class="row muted" style="gap:4px;white-space:nowrap"><input type="checkbox" checked=${f.billable} onChange=${set('billable')} />billable</label>
        <button class="btn primary" onClick=${add}>Log</button></div>
    </div>
  </div>

  <div class="card" style="margin-bottom:16px"><h3>◷ Gap detection <span class="sp"></span><button class="btn sm primary" onClick=${scan} disabled=${!gaps.length}>Add ${gaps.length} as suggested</button></h3>
    <div class="muted" style="margin-bottom:8px;font-size:13px">HIVE compares dated emails and meetings linked to each contract (directly, via the client, or via its people) against your logged time. Suggested entries never reach an invoice until you confirm them.</div>
    ${gaps.length ? html`<div class="list">${gaps.map((g) => html`<div class="li"><span class="mono dim">${g.date}</span><b>${hours(g.minutes / 60)}</b><span>${g.contract_name}</span><span class="sp dim" style="font-size:12px">${g.reason}</span>
      ${g.evidence.slice(0, 3).map((p) => html`<span class="chip click" onClick=${() => openNote(p)}>${p.split('/').pop().replace('.md', '')}</span>`)}</div>`)}</div>`
      : html`<div class="empty">No new gaps in the last 14 days.</div>`}
  </div>

  <div class="card"><h3>Entries · last 45 days</h3>
    ${Object.keys(byDate).sort().reverse().map((d) => html`
      <div class="section-title" style="display:flex">${new Date(d + 'T00:00').toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' })}<span class="sp"></span>${hours(byDate[d].filter((e) => e.status !== 'suggested').reduce((s, e) => s + e.minutes, 0) / 60)}</div>
      <table class="t" style="table-layout:fixed"><colgroup><col style="width:120px" /><col style="width:70px" /><col style="width:26%" /><col /><col style="width:110px" /><col style="width:150px" /></colgroup><tbody>${byDate[d].map((e) => html`<${EntryRow} key=${e.id} e=${e} contracts=${contracts} />`)}</tbody></table>`)}
    ${!entries.length && html`<div class="empty">No time logged yet. Start the timer up top.</div>`}
  </div>`;
}
