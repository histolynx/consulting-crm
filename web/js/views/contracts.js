import { useEffect, useState } from 'preact/hooks';
import { html, api, bus, openNote, toast, refreshAll, money, compactMoney, hours } from '../lib.js';

const LANES = ['lead', 'proposal', 'negotiating', 'active', 'paused', 'complete'];

function rateText(c) {
  if (!c.rate) return '';
  return c.rate_unit === 'fixed' ? 'fixed fee' : `${money(+c.rate, c.currency)}/${c.rate_unit === 'day' ? 'day' : 'h'}`;
}

export function Contracts({ tick }) {
  const [cs, setCs] = useState([]);
  const [over, setOver] = useState(null);
  const [showLost, setShowLost] = useState(false);
  useEffect(() => { api.get('/api/contracts').then(setCs); }, [tick]);

  const move = async (path, status) => {
    setOver(null);
    const c = cs.find((x) => x.path === path);
    if (!c || c.status === status) return;
    setCs(cs.map((x) => (x.path === path ? { ...x, status } : x)));
    try { await api.post('/api/contracts/status', { path, status }); toast(`${c.name} → ${status}`); refreshAll(); }
    catch (e) { toast(e.message, 'err'); refreshAll(); }
  };
  const lanes = showLost ? [...LANES, 'lost'] : LANES;
  const total = (st) => cs.filter((c) => c.status === st).reduce((s, c) => s + c.value, 0);

  return html`
  <div class="row" style="margin-bottom:16px">
    <span class="muted">Drag cards between stages. Everything writes back to the contract note’s frontmatter.</span>
    <span class="sp"></span>
    <label class="row muted" style="gap:6px;cursor:pointer"><input type="checkbox" checked=${showLost} onChange=${() => setShowLost(!showLost)} /> show lost</label>
    <button class="btn primary" onClick=${() => bus.emit('new-note', 'contract')}>+ New contract</button>
  </div>
  <div class="board">${lanes.map((st) => {
    const items = cs.filter((c) => c.status === st);
    return html`<div class=${'lane' + (over === st ? ' drop' : '')}
        onDragOver=${(e) => { e.preventDefault(); setOver(st); }} onDragLeave=${() => setOver(null)}
        onDrop=${(e) => move(e.dataTransfer.getData('text/plain'), st)}>
      <h4><span>${st} · ${items.length}</span><span>${total(st) ? compactMoney(total(st)) : ''}</span></h4>
      ${items.map((c) => html`<div class="kcard" draggable="true" onDragStart=${(e) => e.dataTransfer.setData('text/plain', c.path)} onClick=${() => openNote(c.path)}>
        <div class="n">${c.name}</div>
        <div class="muted" style="font-size:12px">${c.client || 'no client'} ${rateText(c) && html`· ${rateText(c)}`}</div>
        <div class="row"><span class="money">${c.value ? money(c.value, c.currency) : '—'}</span><span class="sp"></span>
          ${['lead', 'proposal', 'negotiating'].includes(c.status) && html`<span class="chip violet">${Math.round(c.probability * 100)}%</span>`}</div>
        ${c.burn != null && html`<div><div class="row dim" style="font-size:11px;justify-content:space-between"><span>${hours(c.hours_total)} / ${c.budget_hours}h</span><span>${Math.round(c.burn * 100)}%</span></div>
          <div class=${'bar' + (c.burn >= 0.8 ? ' hot' : '')}><i style=${{ width: `${Math.min(100, c.burn * 100)}%` }}></i></div></div>`}
        <div class="row" style="gap:4px">
          ${c.days_left != null && c.status === 'active' && html`<span class=${'chip ' + (c.days_left < 14 ? 'red' : '')}>${c.days_left}d left</span>`}
          ${c.unbilled_hours > 0 && html`<span class="chip green">${hours(c.unbilled_hours)} unbilled</span>`}
          ${c.invoiced > 0 && html`<span class="chip">${compactMoney(c.invoiced)} invoiced</span>`}
          ${c.expected_close && html`<span class="chip">close ${c.expected_close}</span>`}
        </div>
        ${c.next_step && html`<div style="font-size:12px"><span class="dim">next →</span> ${c.next_step}</div>`}
      </div>`)}
    </div>`;
  })}</div>`;
}
