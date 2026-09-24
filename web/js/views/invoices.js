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
      footer=${html`<button class="btn ghost" onClick=${onClose}>Close</button><button class="btn primary" onClick=${() => window.print()}>⎙ Print / Save PDF</button>`}>
    <div class="invoice-doc">
      <div style="display:flex;justify-content:space-between;align-items:flex-start">
        <div><h1>INVOICE</h1><div style="margin-top:6px;color:#666">${inv.number}</div></div>
        <div style="text-align:right"><b style="font-size:15px">${profile.business || profile.name || ''}</b><br/>${profile.name || ''}<br/>${profile.address || ''}<br/>${profile.email || ''}${profile.phone ? html`<br/>${profile.phone}` : ''}</div>
      </div>
      <div style="display:flex;justify-content:space-between;margin-top:30px">
        <div><div style="color:#888;font-size:11px;text-transform:uppercase">Bill to</div><b>${linkText(inv.client) || '—'}</b><div style="color:#666">${linkText(inv.contract)}</div></div>
        <div style="text-align:right"><div><span style="color:#888">Issued</span> ${inv.issued}</div><div><span style="color:#888">Due</span> <b>${inv.due}</b></div><div><span style="color:#888">Period</span> ${inv.period_start} → ${inv.period_end}</div></div>
      </div>
      <table><thead><tr><th>Date</th><th>Description</th><th class="num">Qty</th><th class="num">Rate</th><th class="num">Amount</th></tr></thead>
        <tbody>${(inv.lines || []).map((l) => html`<tr><td>${l.date}</td><td>${l.description}</td><td class="num">${l.qty} ${l.unit}</td><td class="num">${money(l.rate, cur)}</td><td class="num">${money(l.amount, cur)}</td></tr>`)}</tbody></table>
      <div class="total">Total due: ${money(inv.total, cur)}</div>
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
  useEffect(() => {
    api.get('/api/invoices').then(setS);
    api.get('/api/contracts').then((cs) => { setContracts(cs); setF((x) => ({ ...x, contract: x.contract || (cs.find((c) => c.unbilled_hours > 0) || cs[0])?.path || '' })); });
    api.get('/api/profile').then(setProfile);
  }, [tick]);

  const gen = async () => {
    try { const inv = await api.post('/api/invoices', f); toast(`Drafted ${inv.number}: ${money(inv.total)}`); refreshAll(); setView(inv); }
    catch (e) { toast(e.message, 'err'); }
  };
  const status = async (inv, st) => { await api.post('/api/invoices/status', { path: inv.path, status: st }); toast(`${inv.number} → ${st}`); refreshAll(); };
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
  <div class="card"><h3>Invoices</h3>
    <table class="t"><thead><tr><th>Number</th><th>Client</th><th>Contract</th><th>Issued</th><th>Due</th><th class="num">Total</th><th>Status</th><th></th></tr></thead>
    <tbody>${s.items.map((inv) => html`<tr>
      <td><a style="cursor:pointer" onClick=${() => setView(inv)}><b>${inv.number}</b></a></td><td>${linkText(inv.client)}</td><td class="muted">${linkText(inv.contract)}</td>
      <td class="mono">${inv.issued}</td><td class="mono">${inv.due}</td><td class="num"><b>${money(inv.total, inv.currency)}</b></td>
      <td><span class=${'chip ' + (inv.overdue ? 'red' : STATUS_CHIP[inv.status])}>${inv.overdue ? 'overdue' : inv.status}</span></td>
      <td class="right" style="white-space:nowrap">
        ${inv.status === 'draft' && html`<button class="btn sm" onClick=${() => status(inv, 'sent')}>Mark sent</button>`}
        ${inv.status === 'sent' && html`<button class="btn sm primary" onClick=${() => status(inv, 'paid')}>Mark paid</button>`}
        <button class="btn ghost sm" onClick=${() => openNote(inv.path)}>note</button>
        ${inv.status !== 'void' && inv.status !== 'paid' && html`<button class="btn ghost sm danger" onClick=${() => status(inv, 'void')}>void</button>`}</td></tr>`)}</tbody></table>
    ${!s.items.length && html`<div class="empty">No invoices yet.</div>`}
  </div>
  ${view && html`<${InvoiceDoc} inv=${view} profile=${profile} onClose=${() => setView(null)} />`}`;
}
