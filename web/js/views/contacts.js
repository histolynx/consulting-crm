import { useEffect, useState } from 'preact/hooks';
import { html, api, bus, openNote, ago } from '../lib.js';
import { Hexav } from '../components.js';

const warmth = (d) => (d == null ? '' : d < 7 ? 'green' : d < 21 ? 'amber' : 'red');

export function Contacts({ tick }) {
  const [tab, setTab] = useState('people');
  const [people, setPeople] = useState([]);
  const [orgs, setOrgs] = useState([]);
  const [q, setQ] = useState('');
  const [sort, setSort] = useState('recent');
  useEffect(() => {
    api.get('/api/contacts').then(setPeople);
    api.get('/api/clients').then(setOrgs);
  }, [tick]);

  const ql = q.toLowerCase();
  let ps = people.filter((p) => !ql || [p.name, p.org, p.role, p.email, ...(p.tags || [])].join(' ').toLowerCase().includes(ql));
  if (sort === 'name') ps = [...ps].sort((a, b) => a.name.localeCompare(b.name));
  if (sort === 'connected') ps = [...ps].sort((a, b) => b.degree - a.degree);
  if (sort === 'cold') ps = [...ps].sort((a, b) => (b.days_since ?? 9999) - (a.days_since ?? 9999));
  const os = orgs.filter((o) => !ql || [o.name, o.industry].join(' ').toLowerCase().includes(ql));

  return html`
  <div class="row" style="margin-bottom:16px">
    <div class="seg"><button class=${tab === 'people' ? 'on' : ''} onClick=${() => setTab('people')}>People · ${people.length}</button><button class=${tab === 'orgs' ? 'on' : ''} onClick=${() => setTab('orgs')}>Organisations · ${orgs.length}</button></div>
    <input class="input" style="max-width:320px" placeholder="Filter…" value=${q} onInput=${(e) => setQ(e.target.value)} />
    ${tab === 'people' && html`<select class="select" style="max-width:170px" value=${sort} onChange=${(e) => setSort(e.target.value)}>
      <option value="recent">Recently in touch</option><option value="cold">Coldest first</option><option value="connected">Most connected</option><option value="name">Name</option></select>`}
    <span class="sp"></span>
    <button class="btn primary" onClick=${() => bus.emit('new-note', tab === 'people' ? 'contact' : 'client')}>+ New ${tab === 'people' ? 'contact' : 'organisation'}</button>
  </div>
  ${tab === 'people' ? html`<div class="cards">${ps.map((p) => html`
    <div class="pcard" onClick=${() => openNote(p.path)}>
      <${Hexav} name=${p.name} />
      <div style="min-width:0;flex:1">
        <div class="row" style="gap:6px"><span class="name">${p.name}</span><span class="sp"></span>${p.days_since != null && html`<span class=${'chip ' + warmth(p.days_since)}>${ago(p.days_since)}</span>`}</div>
        <div class="meta">${[p.role, p.org].filter(Boolean).join(' · ') || html`<span class="dim">no org</span>`}</div>
        <div class="meta mono" style="font-size:11px">${p.email || ''}</div>
        <div class="row" style="gap:4px;margin-top:6px">${p.relationship && html`<span class="chip violet">${p.relationship}</span>`}<span class="chip">${p.degree} links</span></div>
      </div></div>`)}
    ${!ps.length && html`<div class="empty">No contacts yet. Forward an email to the hive or add one.</div>`}</div>`
  : html`<div class="card"><table class="t"><thead><tr><th>Organisation</th><th>Industry</th><th>Status</th><th class="num">People</th><th class="num">Contracts</th></tr></thead>
    <tbody>${os.map((o) => html`<tr class="click" onClick=${() => openNote(o.path)}>
      <td><div class="row" style="flex-wrap:nowrap"><${Hexav} name=${o.name} size=${24} /><b>${o.name}</b></div></td><td class="muted">${o.industry || '—'}</td>
      <td>${o.status && html`<span class=${'chip ' + (o.status === 'active' ? 'green' : 'amber')}>${o.status}</span>`}</td><td class="num">${o.contacts}</td><td class="num">${o.contracts}</td></tr>`)}</tbody></table>
    ${!os.length && html`<div class="empty">No organisations yet.</div>`}</div>`}`;
}
