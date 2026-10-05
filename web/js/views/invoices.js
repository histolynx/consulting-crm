import { useEffect, useState } from 'preact/hooks';
import { html, api, openNote, toast, refreshAll, money, linkText } from '../lib.js';
import { Modal } from '../components.js';

const STATUS_CHIP = { draft: '', sent: 'amber', paid: 'green', void: 'red' };

function monthRange(offset = 0) {
  const d = new Date(); d.setDate(1); d.setMonth(d.getMonth() + offset);
  const s = d.toLocaleDateString('en-CA');
  const e = new Date(d.getFullYear(), d.getMonth() + 1, 0).toLocaleDateString('en-CA');
  return [s, e];
}

function InvoiceDoc({ inv, profile, onClose }) {
  const cur = inv.currency || 'USD';
  return html`<${Modal} title=${`Invoice ${inv.number}`} onClose=${onClose} wide
      footer=${html`<button class="btn ghost" onClick=${onClose}>Close</button>
        ${inv.document && html`<a class="btn" href=${'/vault/' + encodeURI(inv.document)} target="_blank">📎 Open the PDF as sent</a>`}
        <button class="btn primary" onClick=${() => window.print()}>⎙ Print / Save PDF</button>`}>
    <div class="invoice-doc">
      <div style="display:flex;justify-content:space-between;align-items:flex-start">
        <div><h1>INVOICE</h1><div style="margin-top:6px;color:#666">${inv.number}</div></div>
        <div style="text-align:right"><b style="font-size:15px">${profile.business || profile.name || ''}</b><br/>${profile.name || ''}<br/>${profile.address || ''}<br/>${profile.email || ''}${profile.phone ? html`<br/>${profile.phone}` : ''}</div>
      </div>
      <div style="display:flex;justify-content:space-between;margin-top:30px">
        <div><div style="color:#888;font-size:11px;text-transform:uppercase">Bill to</div><b>${linkText(inv.client) || '—'}</b><div style="color:#666">${linkText(inv.contract)}</div></div>
        <div style="text-align:right"><div><span style="color:#888">Issued</span> ${inv.issued}</div><div><span style="color:#888">Due</span> <b>${inv.due}</b></div><div><span style="color:#888">Period</span> ${inv.period_start} → ${inv.period_end}</div></div>
      </div>
      <table><thead><tr><th>Period</th><th>Description</th><th class="num">Qty</th><th class="num">Rate</th><th class="num">Amount</th></tr></thead>
        <tbody>${(inv.lines || []).map((l) => html`<tr><td>${l.date}</td><td>${l.description}</td><td class="num">${l.qty} ${l.unit}</td><td class="num">${money(l.rate, cur)}</td><td class="num">${money(l.amount, cur)}</td></tr>`)}</tbody></table>
      <div class="total">Total due: ${money(inv.total, cur)}</div>
      ${inv.timesheet?.length > 0 && html`<div style="margin-top:34px;page-break-before:always">
        <div style="font-size:15px;font-weight:700;margin-bottom:4px">Timesheet</div>
        <div style="color:#666;font-size:12px">${inv.period_start} → ${inv.period_end} · ${linkText(inv.contract)}</div>
        <table><thead><tr><th>Date</th><th>Section</th><th>Description</th><th class="num">Hours</th></tr></thead>
          <tbody>${inv.timesheet.map((t) => html`<tr><td>${t.date}</td><td>${t.section}</td><td>${t.description}</td><td class="num">${t.hours.toFixed(2)}</td></tr>`)}</tbody></table>
        <div style="text-align:right;font-weight:700">Total hours: ${inv.timesheet.reduce((a, t) => a + t.hours, 0).toFixed(2)}</div></div>`}
      ${profile.payment_instructions && html`<div style="margin-top:30px;padding-top:12px;border-top:1px solid #ddd"><div style="color:#888;font-size:11px;text-transform:uppercase">Payment</div>${profile.payment_instructions}</div>`}
      <div style="margin-top:20px;color:#999;font-size:11px">Thank you for your business.</div>
    </div>
  <//>`;
}

export function Invoices({ tick }) {
  const [s, setS] = useState(null);
  const [contracts, setContracts] = useState([]);
  const [profile, setProfile] = useState({});
  const [view, setView] = useState(null);
  const [lm0, lm1] = monthRange(-1);
  const [f, setF] = useState({ contract: '', start: lm0, end: lm1 });
  const [dating, setDating] = useState(null);
  const [recording, setRecording] = useState(false);
  const [showVoid, setShowVoid] = useState(false);
  useEffect(() => {
    api.get('/api/invoices').then(setS);
    api.get('/api/contracts').then((cs) => { setContracts(cs); setF((x) => ({ ...x, contract: x.contract || (cs.find((c) => c.unbilled_hours > 0) || cs[0])?.path || '' })); });
    api.get('/api/profile').then(setProfile);
  }, [tick]);

  const gen = async () => {
    try { const inv = await api.post('/api/invoices', f); toast(`Drafted ${inv.number}: ${money(inv.total)}`); refreshAll(); setView(inv); }
    catch (e) { toast(e.message, 'err'); }
  };
  const status = async (inv, st, date, reference) => {
    try { await api.post('/api/invoices/status', { path: inv.path, status: st, date, reference }); toast(`${inv.number} → ${st}${date ? ` (${date})` : ''}`); refreshAll(); }
    catch (e) { toast(e.message, 'err'); }
  };
  const sel = contracts.find((c) => c.path === f.contract);

  if (!s) return html`<div class="thinking"><i></i><i></i><i></i></div>`;
  return html`
  <div class="kpis">
    <div class="kpi" style="--kc:var(--amber)"><div class="l">Outstanding</div><div class="v">${money(s.outstanding)}</div></div>
    <div class="kpi" style="--kc:var(--red)"><div class="l">Overdue</div><div class="v">${money(s.overdue)}</div></div>
    <div class="kpi" style="--kc:var(--green)"><div class="l">Paid this year</div><div class="v">${money(s.paid_ytd)}</div></div>
    <div class="kpi" style="--kc:var(--blue)"><div class="l">Unbilled (all contracts)</div><div class="v">${contracts.reduce((a, c) => a + c.unbilled_hours, 0).toFixed(1)}h</div></div>
  </div>
  <div class="card" style="margin-bottom:16px"><h3>Draft an invoice</h3>
    <div class="row">
      <label class="f" style="min-width:260px">Contract<select class="select" value=${f.contract} onChange=${(e) => setF({ ...f, contract: e.target.value })}>
        ${contracts.map((c) => html`<option value=${c.path}>${c.name}${c.unbilled_hours ? ` · ${c.unbilled_hours}h unbilled` : ''}</option>`)}</select></label>
      <label class="f">From<input class="input" type="date" value=${f.start} onInput=${(e) => setF({ ...f, start: e.target.value })} /></label>
      <label class="f">To<input class="input" type="date" value=${f.end} onInput=${(e) => setF({ ...f, end: e.target.value })} /></label>
      <div class="col" style="gap:4px"><span class="dim" style="font-size:12px">Quick</span><div class="row" style="gap:4px">
        <button class="btn sm" onClick=${() => { const [a, b] = monthRange(-1); setF({ ...f, start: a, end: b }); }}>Last month</button>
        <button class="btn sm" onClick=${() => { const [a, b] = monthRange(0); setF({ ...f, start: a, end: b }); }}>This month</button></div></div>
      <span class="sp"></span>
      <button class="btn primary" onClick=${gen}>⚡ Generate draft</button>
    </div>
    ${sel && html`<div class="dim" style="margin-top:8px;font-size:12px">${sel.rate_unit === 'fixed' ? 'Fixed fee: bills milestones marked complete.' : `Bills confirmed, billable, un-invoiced time at ${money(+sel.rate || 0)}/${sel.rate_unit}.`} Entries get stamped with the invoice number so they're never billed twice.</div>`}
  </div>
  <div class="card"><h3>Invoices <span class="sp"></span><label class="row muted" style="gap:4px;text-transform:none;letter-spacing:0;font-weight:400;cursor:pointer"><input type="checkbox" checked=${showVoid} onChange=${() => setShowVoid(!showVoid)} />show void</label>
      <button class="btn sm primary" onClick=${() => setRecording(true)}>⇪ Record a sent invoice</button></h3>
    <table class="t"><thead><tr><th>Number</th><th>Client · contract</th><th>Issued</th><th>Sent</th><th>Due</th><th>Paid</th><th class="num">Total</th><th>Status</th><th></th></tr></thead>
    <tbody>${s.items.filter((inv) => showVoid || inv.status !== 'void').map((inv) => html`<tr style=${inv.status === 'void' ? { opacity: 0.45 } : null}>
      <td><a style="cursor:pointer" onClick=${() => setView(inv)}><b>${inv.number}</b></a>${inv.document && html` <a href=${'/vault/' + encodeURI(inv.document)} target="_blank" title="Open the invoice as sent">📎</a>`}</td>
      <td>${linkText(inv.client)}<div class="dim" style="font-size:12px">${linkText(inv.contract)}</div></td>
      <td class="mono">${inv.issued}</td><td class="mono">${inv.sent || ''}</td><td class="mono">${inv.due}</td>
      <td class="mono" style=${inv.paid ? { color: 'var(--green)' } : null}>${inv.paid || ''}</td>
      <td class="num"><b>${money(inv.total, inv.currency)}</b></td>
      <td><span class=${'chip ' + (inv.overdue ? 'red' : STATUS_CHIP[inv.status])}>${inv.overdue ? 'overdue' : inv.status}</span></td>
      <td class="right" style="white-space:nowrap">
        ${inv.status === 'draft' && html`<button class="btn sm" onClick=${() => setDating({ inv, st: 'sent' })}>Mark sent</button>`}
        ${inv.status === 'sent' && html`<button class="btn sm primary" onClick=${() => setDating({ inv, st: 'paid' })}>Mark paid</button>`}
        <button class="btn ghost sm" onClick=${() => openNote(inv.path)}>note</button>
        ${inv.status !== 'void' && inv.status !== 'paid' && html`<button class="btn ghost sm danger" onClick=${() => status(inv, 'void')}>void</button>`}</td></tr>`)}</tbody></table>
    ${!s.items.length && html`<div class="empty">No invoices yet.</div>`}
  </div>
  ${view && html`<${InvoiceDoc} inv=${view} profile=${profile} onClose=${() => setView(null)} />`}
  ${dating && html`<${DateModal} {...dating} onClose=${() => setDating(null)} onSave=${(date, ref) => { status(dating.inv, dating.st, date, ref); setDating(null); }} />`}
  ${recording && html`<${RecordModal} contracts=${contracts} onClose=${() => setRecording(false)} />`}`;
}

// ---------- when did it happen? ----------
function DateModal({ inv, st, onClose, onSave }) {
  const [date, setDate] = useState(new Date().toLocaleDateString('en-CA'));
  const [ref, setRef] = useState('');
  return html`<${Modal} title=${`${inv.number}: mark ${st}`} onClose=${onClose}
      footer=${html`<button class="btn ghost" onClick=${onClose}>Cancel</button><button class="btn primary" onClick=${() => onSave(date, ref)}>Save</button>`}>
    <div class="row"><label class="f">${st === 'paid' ? 'Payment received on' : 'Sent on'}<input class="input" type="date" value=${date} onInput=${(e) => setDate(e.target.value)} /></label>
      ${st === 'paid' && html`<label class="f" style="flex:1">Reference (optional)<input class="input" placeholder="ACH trace, check #…" value=${ref} onInput=${(e) => setRef(e.target.value)} /></label>`}</div>
    <div class="dim" style="font-size:12px">${money(inv.total, inv.currency)} · due ${inv.due}</div>
  <//>`;
}

// ---------- record an invoice produced outside HIVE ----------
function RecordModal({ contracts, onClose }) {
  const hourly = contracts.filter((c) => c.rate_unit === 'hour' || c.rate_unit === 'day');
  const [c, setC] = useState(hourly[0]?.path || '');
  const cur = contracts.find((x) => x.path === c);
  const [f, setF] = useState({ number: '', issued: new Date().toLocaleDateString('en-CA'), due: '', sent_to: '', start: '', end: new Date().toLocaleDateString('en-CA') });
  const [secs, setSecs] = useState([]);
  const [entries, setEntries] = useState([]);
  const [lines, setLines] = useState([]);
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.get('/api/time', { start: '2000-01-01' }).then(setEntries); }, []);
  useEffect(() => { setSecs((cur?.sections || []).map((s) => s.name)); }, [c]);
  const pick = entries.filter((e) => e.status !== 'suggested' && !e.invoice && e.billable !== false && linkText(e.contract) === cur?.name
    && (!f.start || e.date >= f.start) && (!f.end || e.date <= f.end) && (!secs.length || secs.includes(e.section)));
  const lineOf = (sec) => (cur?.sections || []).find((s) => s.name === sec)?.bill_as || sec || 'Consulting services';
  const suggested = {};
  pick.forEach((e) => { const l = lineOf(e.section); suggested[l] = (suggested[l] || 0) + e.minutes / 60; });
  const useSuggested = () => setLines(Object.entries(suggested).map(([d, h]) => ({ description: d, qty: +h.toFixed(2), rate: +cur.rate })));
  const pickedH = pick.reduce((a, e) => a + e.minutes / 60, 0);
  const lineH = lines.reduce((a, l) => a + (+l.qty || 0), 0);
  const total = lines.reduce((a, l) => a + (+l.qty || 0) * (+l.rate || 0), 0);
  const save = async () => {
    setBusy(true);
    try {
      const unbilledH = +(pickedH - lineH).toFixed(2);
      const inv = await api.post('/api/invoices/record', { contract: c, ...f, due: f.due || null, entry_ids: pick.map((e) => e.id),
        lines: lines.map((l) => ({ ...l, qty: +l.qty, rate: +l.rate })),
        unbilled: unbilledH > 0.009 ? [{ section: 'various', hours: unbilledH, reason: 'covered hours not billed on this invoice' }] : null });
      if (file) {
        const b64 = await new Promise((res) => { const r = new FileReader(); r.onload = () => res(String(r.result).split(',')[1]); r.readAsDataURL(file); });
        await api.post('/api/invoices/attach', { path: inv.path, filename: file.name, content_b64: b64 });
      }
      toast(`Recorded ${inv.number}: ${money(inv.total)} · ${pick.length} entries marked billed`); refreshAll(); onClose();
    } catch (e) { toast(e.message, 'err'); } finally { setBusy(false); }
  };
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  return html`<${Modal} title="Record a sent invoice" onClose=${onClose} wide
      footer=${html`<button class="btn ghost" onClick=${onClose}>Cancel</button><button class="btn primary" disabled=${busy || !f.number || !lines.length || !pick.length} onClick=${save}>Record ${money(total)}</button>`}>
    <div class="muted" style="font-size:13px">For invoices you made or sent outside HIVE. The hours you select get marked as billed on it, so they're never billed twice.</div>
    <div class="formgrid">
      <label class="f">Contract<select class="select" value=${c} onChange=${(e) => setC(e.target.value)}>${hourly.map((x) => html`<option value=${x.path}>${x.name}</option>`)}</select></label>
      <label class="f">Invoice number<input class="input" value=${f.number} onInput=${set('number')} placeholder="as printed" /></label>
      <label class="f">Issued<input class="input" type="date" value=${f.issued} onInput=${set('issued')} /></label>
      <label class="f">Due (blank = terms)<input class="input" type="date" value=${f.due} onInput=${set('due')} /></label>
      <label class="f">Sent to<input class="input" value=${f.sent_to} onInput=${set('sent_to')} placeholder="ap@client.com" /></label>
      <label class="f">PDF<input type="file" accept=".pdf,image/*" onChange=${(e) => setFile(e.target.files[0])} /></label>
    </div>
    <div class="card" style="padding:12px"><h3 style="margin-bottom:8px">Hours covered: ${pickedH.toFixed(2)} h in ${pick.length} entries</h3>
      <div class="row"><label class="f">From<input class="input" type="date" value=${f.start} onInput=${set('start')} /></label><label class="f">To<input class="input" type="date" value=${f.end} onInput=${set('end')} /></label></div>
      <div class="row" style="gap:6px;margin-top:8px">${(cur?.sections || []).map((s) => html`<span class=${'chip click ' + (secs.includes(s.name) ? 'on' : '')} onClick=${() => setSecs(secs.includes(s.name) ? secs.filter((x) => x !== s.name) : [...secs, s.name])}>◆ ${s.name}</span>`)}</div>
    </div>
    <div class="card" style="padding:12px"><h3 style="margin-bottom:8px">Lines as printed <span class="sp"></span><button class="btn sm" onClick=${useSuggested} disabled=${!pick.length}>Fill from hours</button></h3>
      <table class="t"><thead><tr><th>Description</th><th class="num">Qty (h)</th><th class="num">Rate</th><th class="num">Amount</th><th></th></tr></thead><tbody>
        ${lines.map((l, i) => html`<tr>
          <td><input class="input" value=${l.description} onInput=${(e) => setLines(lines.map((x, j) => (j === i ? { ...x, description: e.target.value } : x)))} /></td>
          <td class="num"><input class="input" style="width:90px;text-align:right" value=${l.qty} onInput=${(e) => setLines(lines.map((x, j) => (j === i ? { ...x, qty: e.target.value } : x)))} /></td>
          <td class="num"><input class="input" style="width:90px;text-align:right" value=${l.rate} onInput=${(e) => setLines(lines.map((x, j) => (j === i ? { ...x, rate: e.target.value } : x)))} /></td>
          <td class="num">${money((+l.qty || 0) * (+l.rate || 0))}</td>
          <td><button class="btn ghost sm danger" onClick=${() => setLines(lines.filter((_, j) => j !== i))}>✕</button></td></tr>`)}
      </tbody></table>
      <button class="btn ghost sm" onClick=${() => setLines([...lines, { description: '', qty: 0, rate: cur?.rate || 0 }])}>+ line</button>
      ${lines.length > 0 && Math.abs(pickedH - lineH) > 0.009 && html`<div style="margin-top:8px;font-size:12px;color:var(--amber2)">Lines bill ${lineH.toFixed(2)} h but the selected entries hold ${pickedH.toFixed(2)} h. The ${(pickedH - lineH).toFixed(2)} h difference will be recorded as "not billed on this invoice".</div>`}
    </div>
  <//>`;
}
