import { useEffect, useRef, useState } from 'preact/hooks';
import { html, api, bus, openNote, toast, refreshAll, hours, today, linkText, hashColor } from '../lib.js';
import { Modal } from '../components.js';

const ACTIVE = ['active', 'negotiating', 'proposal', 'lead'];

function weekDays(startIso) {
  const s = new Date(startIso + 'T00:00:00');
  return [...Array(7)].map((_, i) => { const d = new Date(s); d.setDate(s.getDate() + i); return d.toLocaleDateString('en-CA'); });
}
const clock = (sec) => `${Math.floor(sec / 3600)}:${String(Math.floor(sec % 3600 / 60)).padStart(2, '0')}:${String(sec % 60).padStart(2, '0')}`;

export function SectionChip({ name, small }) {
  if (!name) return null;
  const c = hashColor(name);
  return html`<span class="chip" style=${{ color: c, borderColor: c + '66', background: c + '14', fontSize: small ? '10.5px' : null }}>◆ ${name}</span>`;
}

// ---------- Toggl-style tracker bar ----------
function TrackerBar({ contracts, onChanged }) {
  const [timer, setTimer] = useState(null);
  const [desc, setDesc] = useState('');
  const [contract, setContract] = useState('');
  const [section, setSection] = useState('');
  const [billable, setBillable] = useState(true);
  const [now, setNow] = useState(Date.now());
  const [adding, setAdding] = useState(false);
  const [newSec, setNewSec] = useState('');
  const load = () => api.get('/api/timer').then((r) => setTimer(r.timer));
  useEffect(() => {
    load();
    const i = setInterval(() => setNow(Date.now()), 1000);
    const off = bus.on('timer-changed', load);
    const offC = bus.on('continue-entry', (e) => { setDesc(e.description || ''); setContract(linkText(e.contract) || ''); setSection(e.section || ''); setBillable(e.billable !== false); start(e); });
    return () => { clearInterval(i); off(); offC(); };
  }, []);
  useEffect(() => { if (!contract && contracts[0]) setContract(contracts[0].name); }, [contracts]);
  const cur = contracts.find((c) => c.name === contract);

  async function start(prefill) {
    const body = prefill ? { description: prefill.description, contract: linkText(prefill.contract) || null, section: prefill.section || null, billable: prefill.billable !== false }
      : { description: desc, contract: contract || null, section: section || null, billable };
    try { setTimer(await api.post('/api/timer/start', body)); bus.emit('timer-changed'); toast(`▶ ${body.section || body.contract || 'Timer'} started`); }
    catch (e) { toast(e.message, 'err'); }
  }
  const stop = async () => {
    const r = await api.post('/api/timer/stop');
    setTimer(null); setDesc(''); bus.emit('timer-changed');
    toast(r.entry ? `Logged ${hours(r.entry.minutes / 60)} → ${[linkText(r.entry.contract), r.entry.section].filter(Boolean).join(' · ')}` : 'Under a minute: discarded');
    onChanged();
  };
  const addSection = async () => {
    if (!newSec.trim() || !cur) return;
    await api.post('/api/contracts/section', { path: cur.path, name: newSec.trim() });
    toast(`Section “${newSec.trim()}” added to ${cur.name}`); setSection(newSec.trim()); setNewSec(''); setAdding(false); onChanged();
  };

  if (timer) {
    const secs = Math.max(0, Math.floor((now - new Date(timer.started).getTime()) / 1000));
    return html`<div class="tracker running">
      <div class="tr-main"><div class="tr-desc">${timer.description || html`<span class="dim">(no description)</span>`}</div>
        <div class="row" style="gap:6px"><span class="muted">${timer.contract || 'No contract'}</span><${SectionChip} name=${timer.section} />${timer.billable === false && html`<span class="chip">non-billable</span>`}</div></div>
      <div class="tr-clock">${clock(secs)}</div>
      <button class="tr-btn stop" onClick=${stop} title="Stop">■</button></div>`;
  }
  return html`<div class="tracker">
    <div class="tr-main">
      <input class="tr-input" placeholder="What are you working on?" value=${desc} onInput=${(e) => setDesc(e.target.value)} onKeyDown=${(e) => e.key === 'Enter' && start()} />
      <div class="row" style="gap:6px;margin-top:8px">
        <select class="select" style="width:auto;max-width:240px;padding:4px 8px" value=${contract} onChange=${(e) => { setContract(e.target.value); setSection(''); }}>
          <option value="">No contract</option>${contracts.map((c) => html`<option value=${c.name}>${c.name}</option>`)}</select>
        ${cur && cur.sections.map((s) => html`<span class=${'chip click ' + (section === s.name ? 'on' : '')} style=${section === s.name ? null : { color: hashColor(s.name) }}
          onClick=${() => setSection(section === s.name ? '' : s.name)}>◆ ${s.name}</span>`)}
        ${cur && (adding ? html`<input class="input" style="width:180px;padding:3px 8px" placeholder="New section, e.g. Discovery" value=${newSec}
            onInput=${(e) => setNewSec(e.target.value)} onKeyDown=${(e) => { if (e.key === 'Enter') addSection(); if (e.key === 'Escape') setAdding(false); }} ref=${(el) => el && el.focus()} />`
          : html`<span class="chip click dim" onClick=${() => setAdding(true)} title="Add a section to this contract">+ section</span>`)}
      </div></div>
    <button class=${'tr-bill ' + (billable ? 'on' : '')} onClick=${() => setBillable(!billable)} title=${billable ? 'Billable' : 'Non-billable'}>$</button>
    <div class="tr-clock dim">0:00:00</div>
    <button class="tr-btn" onClick=${() => start()} title="Start (Enter)">▶</button></div>`;
}

// ---------- Toggl import ----------
function ImportModal({ contracts, onClose }) {
  const [csv, setCsv] = useState('');
  const [pv, setPv] = useState(null);
  const [map, setMap] = useState({});
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const file = useRef();
  const preview = async (text = csv, m = map) => {
    setErr(''); setBusy(true);
    try { setPv(await api.post('/api/time/import/preview', { csv: text, project_map: m })); } catch (e) { setErr(e.message); setPv(null); } finally { setBusy(false); }
  };
  const onFile = async (e) => { const f = e.target.files[0]; if (!f) return; const t = await f.text(); setCsv(t); preview(t); };
  const doImport = async () => {
    setBusy(true);
    try { const r = await api.post('/api/time/import', { csv, project_map: map, remember: true }); toast(`Imported ${r.imported} entries (${r.hours}h)${r.duplicates ? `, skipped ${r.duplicates} duplicates` : ''}`); refreshAll(); onClose(); }
    catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  return html`<${Modal} title="Import from Toggl" onClose=${onClose} wide
      footer=${html`<button class="btn ghost" onClick=${onClose}>Cancel</button><button class="btn" disabled=${!csv || busy} onClick=${() => preview()}>Preview</button>
        <button class="btn primary" disabled=${!pv || busy || Object.keys(pv.unmapped_projects).some((p) => !map[p]) || !pv.new} onClick=${doImport}>Import ${pv ? pv.new : ''} entries</button>`}>
    <div class="muted" style="font-size:13px">In Toggl: <b>Reports → Detailed</b> → choose the date range → <b>Export → Download CSV</b>. (The Summary export has no dates.) Re-importing is safe: duplicates are skipped.</div>
    <div class="row"><input type="file" accept=".csv,text/csv" ref=${file} onChange=${onFile} /><span class="dim">or paste below</span></div>
    <textarea class="input mono" rows="5" placeholder="Paste Toggl Detailed CSV…" value=${csv} onInput=${(e) => setCsv(e.target.value)} style="font-size:12px"></textarea>
    ${err && html`<div style="color:var(--red)">${err}</div>`}
    ${pv && html`<div class="col" style="gap:10px">
      <div class="row"><span class="chip green">${pv.new} new</span><span class="chip">${pv.duplicates} already imported</span><b>${pv.hours} h</b><span class="dim">${pv.first_date} → ${pv.last_date}</span></div>
      ${Object.keys(pv.unmapped_projects).length > 0 && html`<div class="card" style="padding:12px"><h3 style="margin-bottom:8px">Map Toggl projects → contracts (remembered)</h3>
        ${Object.entries(pv.unmapped_projects).map(([p, h]) => html`<div class="row" style="margin-bottom:6px"><span style="min-width:180px"><b>${p}</b> <span class="dim">${h}h</span></span>→
          <select class="select" style="width:auto" value=${map[p] || ''} onChange=${(e) => { const m = { ...map, [p]: e.target.value }; setMap(m); preview(csv, m); }}>
            <option value="">choose contract…</option>${contracts.map((c) => html`<option value=${c.path}>${c.name}</option>`)}</select></div>`)}</div>`}
      <table class="t"><thead><tr><th>Contract · section</th><th class="num">Hours</th></tr></thead><tbody>
        ${Object.entries(pv.by_bucket).map(([k, h]) => html`<tr><td>${k}</td><td class="num">${h}</td></tr>`)}</tbody></table>
      ${Object.keys(pv.unmapped_tags).length > 0 && html`<div class="dim" style="font-size:12px">Tags with no matching section are kept as their own section: ${Object.keys(pv.unmapped_tags).join(', ')}. Add them as sections (or to a section's <span class="mono">match</span> list) to fold them in.</div>`}
    </div>`}
  <//>`;
}

// ---------- entry row ----------
function EntryRow({ e, contracts }) {
  const [edit, setEdit] = useState(false);
  const [f, setF] = useState({});
  const cur = contracts.find((c) => c.name === (f.contract ?? linkText(e.contract)));
  const startEdit = () => { setF({ date: e.date, contract: linkText(e.contract) || '', section: e.section || '', start: e.start || '', end: e.end || '', hours: (e.minutes / 60).toFixed(2), description: e.description || '', billable: e.billable !== false }); setEdit(true); };
  const save = async () => {
    const patch = { date: f.date, contract: f.contract ? `[[${f.contract}]]` : null, section: f.section || null, description: f.description, billable: f.billable };
    const origH = (e.minutes / 60).toFixed(2);
    if (f.start !== (e.start || '') || f.end !== (e.end || '')) { if (f.start && f.end) Object.assign(patch, { start: f.start, end: f.end }); }
    else if (f.hours !== origH) Object.assign(patch, { start: null, end: null, minutes: Math.round(parseFloat(f.hours) * 60) });
    try { await api.patch(`/api/time/${e.id}`, patch); setEdit(false); refreshAll(); } catch (err) { toast(err.message, 'err'); }
  };
  const del = async () => { await api.del(`/api/time/${e.id}`); toast('Entry deleted'); refreshAll(); };
  if (edit) {
    const set = (k) => (ev) => setF({ ...f, [k]: ev.target.type === 'checkbox' ? ev.target.checked : ev.target.value });
    return html`<tr><td colspan="6"><div class="row">
      <input class="input" type="date" style="width:140px" value=${f.date} onInput=${set('date')} />
      <select class="select" style="width:190px" value=${f.contract} onChange=${(ev) => setF({ ...f, contract: ev.target.value, section: '' })}><option value="">No contract</option>${contracts.map((c) => html`<option>${c.name}</option>`)}</select>
      <select class="select" style="width:170px" value=${f.section} onChange=${set('section')}><option value="">No section</option>${(cur?.sections || []).map((s) => html`<option>${s.name}</option>`)}${f.section && !(cur?.sections || []).some((s) => s.name === f.section) && html`<option>${f.section}</option>`}</select>
      <input class="input" type="time" style="width:105px" value=${f.start} onInput=${set('start')} /><input class="input" type="time" style="width:105px" value=${f.end} onInput=${set('end')} />
      <span class="dim">or</span><input class="input" style="width:70px" value=${f.hours} onInput=${set('hours')} title="hours" />
      <input class="input" style="flex:1;min-width:150px" value=${f.description} onInput=${set('description')} />
      <label class="row muted" style="gap:4px"><input type="checkbox" checked=${f.billable} onChange=${set('billable')} />$</label>
      <button class="btn primary sm" onClick=${save}>Save</button><button class="btn ghost sm" onClick=${() => setEdit(false)}>Cancel</button></div></td></tr>`;
  }
  const sugg = e.status === 'suggested';
  return html`<tr style=${sugg ? { background: 'rgba(166,140,255,.07)' } : null}>
    <td class="mono dim">${e.start ? `${e.start}–${e.end || ''}` : ''}</td>
    <td class="num"><b>${hours(e.minutes / 60)}</b></td>
    <td><div class="row" style="gap:6px;flex-wrap:nowrap;overflow:hidden">${e.contract ? html`<a style="cursor:pointer;white-space:nowrap" onClick=${async () => { try { openNote((await api.get('/api/resolve', { target: linkText(e.contract) })).path); } catch { toast('Contract note not found', 'err'); } }}>${linkText(e.contract)}</a>` : html`<span class="dim">—</span>`}<${SectionChip} name=${e.section} small /></div></td>
    <td>${e.description || ''} ${e.billable === false && html`<span class="chip">non-billable</span>`} ${e.invoice && html`<span class="chip green">${linkText(e.invoice)}</span>`}</td>
    <td>${sugg ? html`<span class="chip violet">suggested</span>` : html`<span class="chip dim">${e.source}</span>`}</td>
    <td class="right" style="white-space:nowrap">${sugg && html`<button class="btn sm primary" onClick=${async () => { await api.post(`/api/time/${e.id}/confirm`); refreshAll(); }}>✓</button> <button class="btn sm danger" onClick=${async () => { await api.post(`/api/time/${e.id}/reject`); refreshAll(); }}>✕</button> `}
      <button class="btn ghost sm" title="Continue: start a timer with the same details" onClick=${() => bus.emit('continue-entry', e)}>▶</button>
      ${!e.invoice && html`<button class="btn ghost sm" onClick=${startEdit}>edit</button><button class="btn ghost sm danger" onClick=${del}>del</button>`}</td></tr>`;
}

// ---------- view ----------
export function TimeView({ tick }) {
  const [entries, setEntries] = useState([]);
  const [sum, setSum] = useState(null);
  const [contracts, setContracts] = useState([]);
  const [gaps, setGaps] = useState([]);
  const [importing, setImporting] = useState(false);
  const [f, setF] = useState({ date: today(), contract: '', section: '', start: '', end: '', hours: '', description: '', billable: true });
  const [ver, setVer] = useState(0);
  const load = () => {
    const from = new Date(); from.setDate(from.getDate() - 60);
    api.get('/api/time', { start: from.toLocaleDateString('en-CA') }).then(setEntries);
    api.get('/api/time/summary').then(setSum);
    api.get('/api/contracts').then((cs) => setContracts(cs.filter((c) => ACTIVE.includes(c.status)).sort((a, b) => ACTIVE.indexOf(a.status) - ACTIVE.indexOf(b.status))));
    api.get('/api/time/gaps').then(setGaps);
  };
  useEffect(load, [tick, ver]);
  useEffect(() => bus.on('timer-changed', () => setVer((v) => v + 1)), []);

  const add = async () => {
    const body = { date: f.date, contract: f.contract || null, section: f.section || null, description: f.description, billable: f.billable, source: 'manual' };
    if (f.start && f.end) Object.assign(body, { start: f.start, end: f.end });
    else if (f.hours) body.minutes = Math.round(parseFloat(f.hours) * 60);
    else return toast('Enter start+end or hours', 'err');
    try { await api.post('/api/time', body); toast('Logged'); setF({ ...f, start: '', end: '', hours: '', description: '' }); refreshAll(); }
    catch (e) { toast(e.message, 'err'); }
  };
  const scan = async () => { const r = await api.post('/api/time/gaps/apply'); toast(`${r.length} suggested entr${r.length === 1 ? 'y' : 'ies'} added`); refreshAll(); };
  const set = (k) => (ev) => setF({ ...f, [k]: ev.target.type === 'checkbox' ? ev.target.checked : ev.target.value });
  const fCur = contracts.find((c) => c.name === f.contract);

  const days = sum ? weekDays(sum.week_start) : [];
  const rows = sum ? Object.entries(sum.week_grid) : [];
  const title = (p) => contracts.find((c) => c.path === p)?.name || p.replace(/^contracts\/|\.md$/g, '');
  const maxCell = Math.max(1, ...rows.flatMap(([, v]) => Object.values(v)));
  const byDate = {};
  entries.forEach((e) => (byDate[e.date] ||= []).push(e));
  const budgeted = contracts.filter((c) => c.sections?.length);

  return html`
  <${TrackerBar} contracts=${contracts} onChanged=${() => { refreshAll(); setVer((v) => v + 1); }} />

  ${budgeted.length > 0 && html`<div class="card" style="margin-bottom:16px"><h3>◆ Sections: hours vs SOW budget</h3>
    <div class="col" style="gap:14px">${budgeted.map((c) => html`<div>
      <div class="row" style="margin-bottom:6px"><b>${c.name}</b><span class="dim">${hours(c.hours_total)}${c.budget_hours ? ` of ${c.budget_hours}h` : ''}</span></div>
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:10px">${c.sections.map((s) => html`<div>
        <div class="row" style="justify-content:space-between;font-size:12px"><${SectionChip} name=${s.name} small /><span class=${s.burn >= 1 ? '' : 'dim'} style=${s.burn >= 1 ? { color: 'var(--red)' } : null}>${hours(s.billed_hours ?? s.hours)}${s.budget_hours ? ` / ${s.budget_hours}h` : ''}</span></div>
        ${s.budget_hours ? html`<div class=${'bar' + (s.burn >= 0.8 ? ' hot' : '')} style="margin-top:4px"><i style=${{ width: `${Math.min(100, (s.burn || 0) * 100)}%` }}></i></div>`
          : s.bill_as ? html`<div class="dim" style="font-size:11px;margin-top:4px">→ bills as <b>${s.bill_as}</b></div>` : html`<div class="dim" style="font-size:11px;margin-top:4px">no budget line</div>`}
        ${s.includes?.length > 0 && html`<div class="dim" style="font-size:11px;margin-top:2px">incl. ${s.includes.join(' + ')} (${hours(s.billed_hours - s.hours)})</div>`}
        ${s.over_hours > 0 && html`<div style="font-size:11px;margin-top:2px;color:${s.overflow_as ? 'var(--amber2)' : 'var(--red)'}">+${hours(s.over_hours)} over${s.overflow_as ? ' → billed as additional hours' : ''}</div>`}
      </div>`)}${c.unsectioned_hours > 0 && html`<div><div class="row" style="justify-content:space-between;font-size:12px"><span class="chip">untagged</span><span class="dim">${hours(c.unsectioned_hours)}</span></div></div>`}</div>
    </div>`)}</div></div>`}

  <div class="grid2" style="margin-bottom:16px">
    <div class="card"><h3>This week <span class="sp"></span><span style="color:var(--amber2);font-size:16px;letter-spacing:0">${sum ? hours(sum.week_total) : ''}</span></h3>
      <div style="overflow-x:auto"><table class="t"><thead><tr><th>Contract</th>${days.map((d) => html`<th class="num">${new Date(d + 'T00:00').toLocaleDateString('en-US', { weekday: 'short' })}</th>`)}<th class="num">Σ</th></tr></thead>
      <tbody>${rows.map(([p, v]) => html`<tr><td style="max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${title(p)}</td>${days.map((d) => {
        const h = v[d] || 0;
        return html`<td class="num" style=${{ background: h ? `rgba(245,165,36,${0.12 + 0.5 * h / maxCell})` : 'transparent', color: h ? '#fff' : 'var(--dim)' }}>${h ? h.toFixed(1) : '·'}</td>`;
      })}<td class="num"><b>${Object.values(v).reduce((a, b) => a + b, 0).toFixed(1)}</b></td></tr>`)}
      ${!rows.length && html`<tr><td colspan="9" class="empty">No confirmed time this week.</td></tr>`}</tbody></table></div>
    </div>
    <div class="card"><h3>Log time manually <span class="sp"></span><button class="btn sm" onClick=${() => setImporting(true)}>⇪ Import from Toggl</button></h3>
      <div class="formgrid">
        <label class="f">Date<input class="input" type="date" value=${f.date} onInput=${set('date')} /></label>
        <label class="f">Contract<select class="select" value=${f.contract} onChange=${(e) => setF({ ...f, contract: e.target.value, section: '' })}><option value="">No contract</option>${contracts.map((c) => html`<option>${c.name}</option>`)}</select></label>
        <label class="f">Section<select class="select" value=${f.section} onChange=${set('section')}><option value="">—</option>${(fCur?.sections || []).map((s) => html`<option>${s.name}</option>`)}</select></label>
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
    <div class="muted" style="margin-bottom:8px;font-size:13px">HIVE compares dated emails and meetings linked to each contract against your logged time. Suggested entries never reach an invoice until you confirm them.</div>
    ${gaps.length ? html`<div class="list">${gaps.map((g) => html`<div class="li"><span class="mono dim">${g.date}</span><b>${hours(g.minutes / 60)}</b><span>${g.contract_name}</span><span class="sp dim" style="font-size:12px">${g.reason}</span>
      ${g.evidence.slice(0, 3).map((p) => html`<span class="chip click" onClick=${() => openNote(p)}>${p.split('/').pop().replace('.md', '')}</span>`)}</div>`)}</div>`
      : html`<div class="empty">No new gaps in the last 14 days.</div>`}
  </div>

  <div class="card"><h3>Entries · last 60 days</h3>
    ${Object.keys(byDate).sort().reverse().map((d) => html`
      <div class="section-title" style="display:flex">${new Date(d + 'T00:00').toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' })}<span class="sp"></span>${hours(byDate[d].filter((e) => e.status !== 'suggested').reduce((s, e) => s + e.minutes, 0) / 60)}</div>
      <table class="t" style="table-layout:fixed"><colgroup><col style="width:110px" /><col style="width:64px" /><col style="width:34%" /><col /><col style="width:96px" /><col style="width:170px" /></colgroup>
      <tbody>${byDate[d].map((e) => html`<${EntryRow} key=${e.id} e=${e} contracts=${contracts} />`)}</tbody></table>`)}
    ${!entries.length && html`<div class="empty">No time logged yet. Hit ▶ above, or import your Toggl history.</div>`}
  </div>
  ${importing && html`<${ImportModal} contracts=${contracts} onClose=${() => setImporting(false)} />`}`;
}
