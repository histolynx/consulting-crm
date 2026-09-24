// Shared components: note drawer, modal, command palette, toasts, new-note forms.
import { useEffect, useRef, useState } from 'preact/hooks';
import { html, api, bus, openNote, toast, refreshAll, go, Markdown, typeColor, linkText, hashColor, initials } from './lib.js';

export function Hexav({ name, size = 38 }) {
  return html`<div class="hexav" style=${{ width: size, height: size * 1.1, background: hashColor(name) }}>${initials(name)}</div>`;
}

export function TypeChip({ type }) {
  return html`<span class="chip" style=${{ color: typeColor(type), borderColor: typeColor(type) + '66' }}>${type}</span>`;
}

export function Modal({ title, onClose, children, footer, wide }) {
  useEffect(() => {
    const k = (e) => e.key === 'Escape' && onClose();
    addEventListener('keydown', k);
    return () => removeEventListener('keydown', k);
  }, [onClose]);
  return html`<div class="overlay" onMouseDown=${(e) => e.target === e.currentTarget && onClose()}>
    <div class="modal" style=${wide ? { width: 'min(900px, 96vw)' } : null}>
      <header>${title}<span class="sp"></span><button class="btn ghost sm" onClick=${onClose}>✕</button></header>
      <div class="mbody">${children}</div>
      ${footer && html`<footer>${footer}</footer>`}
    </div></div>`;
}

// ---------- toasts ----------
export function Toasts() {
  const [items, setItems] = useState([]);
  useEffect(() => bus.on('toast', (t) => {
    const id = Math.random();
    setItems((xs) => [...xs, { ...t, id }]);
    setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), t.kind === 'err' ? 7000 : 3500);
  }), []);
  return html`<div class="toasts">${items.map((t) => html`<div class=${'toast ' + (t.kind === 'err' ? 'err' : '')}>${t.text}</div>`)}</div>`;
}

// ---------- note drawer ----------
function MetaValue({ v }) {
  if (Array.isArray(v)) {
    if (v.length && typeof v[0] === 'object') return html`<span class="dim">${v.length} item(s)</span>`;
    return html`<span>${v.map((x, i) => html`${i ? ', ' : ''}<${MetaValue} v=${x} />`)}</span>`;
  }
  if (v && typeof v === 'object') return html`<span class="mono dim">${JSON.stringify(v)}</span>`;
  const s = String(v ?? '');
  if (/^\[\[.*\]\]$/.test(s)) return html`<${Markdown} src=${s} cls="inline" />`;
  return html`<span>${s || html`<span class="dim">—</span>`}</span>`;
}

function LinkGroup({ items, keyName }) {
  const groups = {};
  items.forEach((x) => (groups[x.label] ||= []).push(x));
  return Object.entries(groups).map(([label, xs]) => html`
    <div style="margin-bottom:8px"><span class="chip amber">${label}</span>
      <div class="row" style="margin-top:6px;gap:6px">${xs.map((x) => html`
        <span class="chip click" style=${{ color: typeColor(x.type) }} onClick=${() => x.type !== 'ghost' && x.type !== 'tag' && openNote(x[keyName])}>${x.title}</span>`)}
      </div></div>`);
}

export function NoteDrawer() {
  const [path, setPath] = useState(null);
  const [note, setNote] = useState(null);
  const [edit, setEdit] = useState(false);
  const [raw, setRaw] = useState('');
  const [history, setHistory] = useState([]);

  useEffect(() => bus.on('open-note', (p) => {
    setHistory((h) => (path && path !== p ? [...h, path] : h));
    setPath(p); setEdit(false);
  }), [path]);
  useEffect(() => {
    if (!path) return;
    setNote(null);
    api.get('/api/note', { path }).then((n) => { setNote(n); setRaw(n.raw); }).catch((e) => toast(e.message, 'err'));
  }, [path]);
  useEffect(() => {
    const k = (e) => e.key === 'Escape' && path && !document.querySelector('.overlay') && close();
    addEventListener('keydown', k);
    return () => removeEventListener('keydown', k);
  });

  const close = () => { setPath(null); setNote(null); setHistory([]); };
  const back = () => { const h = [...history]; const p = h.pop(); setHistory(h); setPath(p); };
  const save = async () => {
    try {
      await api.put('/api/note', { path, text: raw });
      toast('Saved'); setEdit(false);
      setNote(await api.get('/api/note', { path })); refreshAll();
    } catch (e) { toast(e.message, 'err'); }
  };
  if (!path) return null;
  const obsidian = `obsidian://open?vault=${encodeURIComponent(window.HIVE_VAULT_NAME || 'vault')}&file=${encodeURIComponent(path.replace(/\.md$/, ''))}`;
  const meta = note ? Object.entries(note.meta).filter(([k]) => !['type', 'tags'].includes(k)) : [];
  return html`<div class="drawer">
    <header>
      ${history.length > 0 && html`<button class="btn ghost sm" onClick=${back} title="Back">←</button>`}
      ${note && html`<${TypeChip} type=${note.type} />`}
      <h2>${note ? note.meta.title || note.title : '…'}</h2>
      <button class="btn sm" onClick=${() => { go(`graph?root=${encodeURIComponent(path)}`); close(); }} title="Focus this note in the graph">◎ Lens</button>
      <a class="btn sm" href=${obsidian} title="Open in Obsidian (vault must be opened in Obsidian once)">⬡ Obsidian</a>
      ${edit ? html`<button class="btn primary sm" onClick=${save}>Save</button>` : html`<button class="btn sm" onClick=${() => setEdit(true)}>Edit</button>`}
      <button class="btn ghost sm" onClick=${close}>✕</button>
    </header>
    <div class="body">
      ${!note ? html`<div class="thinking"><i></i><i></i><i></i></div>` : edit
        ? html`<textarea value=${raw} onInput=${(e) => setRaw(e.target.value)} spellcheck="false"></textarea>
               <div class="dim" style="margin-top:6px">${path} · frontmatter + markdown · links as [[Note Name]]</div>`
        : html`
        ${meta.length > 0 && html`<div class="meta-table">${meta.map(([k, v]) => html`<div class="k">${k}</div><div><${MetaValue} v=${v} /></div>`)}</div>`}
        ${note.tags.length > 0 && html`<div class="row" style="margin-bottom:10px;gap:6px">${note.tags.map((t) => html`<span class="chip tag">#${t}</span>`)}</div>`}
        <${Markdown} src=${note.body} />
        ${note.backlinks.length > 0 && html`<div class="section-title">Backlinks (${note.backlinks.length})</div><${LinkGroup} items=${note.backlinks} keyName="source" />`}
        ${note.outlinks.filter((o) => o.type !== 'tag').length > 0 && html`<div class="section-title">Links out</div><${LinkGroup} items=${note.outlinks.filter((o) => o.type !== 'tag')} keyName="target" />`}
        ${note.suggestions.length > 0 && html`<div class="section-title">Hive suggests linking</div>
          <div class="list">${note.suggestions.map((s) => html`<div class="li">
            <a class="sp" onClick=${() => openNote(s.path)} style="cursor:pointer">${s.title}</a><span class="dim mono">${s.score}</span>
            <button class="btn sm" onClick=${async () => { await api.post('/api/link', { a: path, b: s.path }); toast('Linked'); setNote(await api.get('/api/note', { path })); refreshAll(); }}>+ link</button></div>`)}</div>`}
        ${note.unlinked_mentions.length > 0 && html`<div class="section-title">Unlinked mentions</div>
          <div class="row" style="gap:6px">${note.unlinked_mentions.map((m) => html`<span class="chip click" onClick=${() => openNote(m.path)}>${m.title}</span>`)}</div>`}
        <div class="dim" style="margin-top:24px;font-size:12px">${path}</div>`}
    </div></div>`;
}

// ---------- new-note modal (contact / client / contract / note / meeting / project) ----------
const FIELDS = {
  contact: [['org', 'Organisation', 'client'], ['role', 'Role'], ['email', 'Email'], ['phone', 'Phone'],
            ['relationship', 'Relationship', ['champion', 'decision-maker', 'technical', 'referrer', 'other']]],
  client: [['industry', 'Industry'], ['website', 'Website'], ['status', 'Status', ['prospect', 'active', 'past']]],
  contract: [['client', 'Client', 'client'], ['status', 'Status', ['lead', 'proposal', 'negotiating', 'active', 'paused', 'complete']],
             ['value', 'Total value', 'number'], ['rate', 'Rate', 'number'], ['rate_unit', 'Rate unit', ['hour', 'day', 'fixed']],
             ['start', 'Start', 'date'], ['end', 'End', 'date'], ['budget_hours', 'Budget hours', 'number'],
             ['payment_terms_days', 'Payment terms (days)', 'number'], ['next_step', 'Next step']],
  meeting: [['date', 'Date', 'date'], ['duration', 'Duration (min)', 'number'], ['client', 'Client', 'client']],
  project: [['client', 'Client', 'client'], ['contract', 'Contract', 'contract']],
  note: [],
};

export function NewNoteModal({ type, onClose, preset = {} }) {
  const [title, setTitle] = useState(preset.title || '');
  const [meta, setMeta] = useState(preset.meta || {});
  const [opts, setOpts] = useState({ client: [], contract: [] });
  const ref = useRef();
  useEffect(() => {
    ref.current?.focus();
    Promise.all([api.get('/api/notes', { type: 'client' }), api.get('/api/notes', { type: 'contract' })])
      .then(([c, k]) => setOpts({ client: c.map((x) => x.title), contract: k.map((x) => x.title) }));
  }, []);
  const set = (k, v) => setMeta((m) => ({ ...m, [k]: v }));
  const submit = async () => {
    if (!title.trim()) return toast('Title required', 'err');
    const m = { tags: [type] };
    for (const [k, , kind] of FIELDS[type]) {
      let v = meta[k];
      if (v === undefined || v === '') continue;
      if (kind === 'number') v = Number(v);
      if (kind === 'client' || kind === 'contract') v = `[[${v}]]`;
      m[k] = v;
    }
    if (type === 'contact') m.name = title.trim();
    if (type === 'contract') { m.currency = 'USD'; m.rate_unit ||= 'hour'; m.status ||= 'lead'; }
    try {
      const r = await api.post('/api/note', { type, title, meta: m, body: `# ${title}\n\n` });
      toast(`Created ${title}`); onClose(); refreshAll(); openNote(r.path);
    } catch (e) { toast(e.message, 'err'); }
  };
  return html`<${Modal} title=${`New ${type}`} onClose=${onClose}
      footer=${html`<button class="btn ghost" onClick=${onClose}>Cancel</button><button class="btn primary" onClick=${submit}>Create</button>`}>
    <label class="f">${type === 'contact' ? 'Full name' : 'Title'}<input ref=${ref} class="input" value=${title} onInput=${(e) => setTitle(e.target.value)} onKeyDown=${(e) => e.key === 'Enter' && submit()} /></label>
    <div class="formgrid">${FIELDS[type].map(([k, label, kind]) => html`<label class="f">${label}${
      Array.isArray(kind) ? html`<select class="select" value=${meta[k] || ''} onChange=${(e) => set(k, e.target.value)}><option value="">—</option>${kind.map((o) => html`<option>${o}</option>`)}</select>`
      : kind === 'client' || kind === 'contract' ? html`<input class="input" list=${'dl-' + kind} value=${meta[k] || ''} onInput=${(e) => set(k, e.target.value)} placeholder="type or pick" />`
      : html`<input class="input" type=${kind === 'number' ? 'number' : kind === 'date' ? 'date' : 'text'} value=${meta[k] || ''} onInput=${(e) => set(k, e.target.value)} />`}</label>`)}
    </div>
    <datalist id="dl-client">${opts.client.map((o) => html`<option value=${o} />`)}</datalist>
    <datalist id="dl-contract">${opts.contract.map((o) => html`<option value=${o} />`)}</datalist>
    <div class="dim" style="font-size:12px">Creates a markdown note; everything is editable later (it's just a file).</div>
  <//>`;
}

// ---------- command palette ----------
export function Palette({ onClose, commands }) {
  const [q, setQ] = useState('');
  const [hits, setHits] = useState([]);
  const [sel, setSel] = useState(0);
  const ref = useRef();
  useEffect(() => ref.current?.focus(), []);
  useEffect(() => {
    let live = true;
    const t = setTimeout(async () => {
      const cmds = commands.filter((c) => !q || c.label.toLowerCase().includes(q.toLowerCase())).map((c) => ({ ...c, kind: 'cmd' }));
      const notes = q.trim() ? (await api.get('/api/search', { q })).map((n) => ({ ...n, kind: 'note' })) : [];
      if (live) { setHits([...notes, ...cmds].slice(0, 30)); setSel(0); }
    }, 90);
    return () => { live = false; clearTimeout(t); };
  }, [q]);
  const run = (h) => {
    if (!h) return;
    onClose();
    if (h.kind === 'note') { if (h.type !== 'tag' && h.type !== 'ghost') openNote(h.path); } else h.run();
  };
  const key = (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setSel((s) => Math.min(s + 1, hits.length - 1)); }
    if (e.key === 'ArrowUp') { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)); }
    if (e.key === 'Enter') run(hits[sel]);
    if (e.key === 'Escape') onClose();
  };
  return html`<div class="overlay" onMouseDown=${(e) => e.target === e.currentTarget && onClose()}>
    <div class="palette">
      <input ref=${ref} placeholder="Search the hive or run a command…" value=${q} onInput=${(e) => setQ(e.target.value)} onKeyDown=${key} />
      <div class="res">${hits.length === 0 ? html`<div class="it dim">No matches</div>` : hits.map((h, i) => html`
        <div class=${'it' + (i === sel ? ' sel' : '')} onMouseEnter=${() => setSel(i)} onClick=${() => run(h)}>
          ${h.kind === 'cmd' ? html`<span style="width:18px;text-align:center">${h.icon || '›'}</span><span>${h.label}</span><span class="sp"></span><span class="dim">command</span>`
            : html`<${TypeChip} type=${h.type} /><div style="min-width:0;flex:1"><div>${h.title}</div>${h.snippet && html`<div class="snip">${h.snippet}</div>`}</div>`}
        </div>`)}</div>
    </div></div>`;
}

export { linkText };
