import { useEffect, useState } from 'preact/hooks';
import { html, api, openNote, go, typeColor, toast, refreshAll } from '../lib.js';

const ORDER = ['act', 'legislator', 'committee', 'topic', 'note'];
const PLURAL = { act: 'acts', legislator: 'legislators', committee: 'committees', topic: 'topics', note: 'notes' };

export function Ideas({ tick }) {
  const [ideas, setIdeas] = useState(null);
  const [draft, setDraft] = useState({ title: '', text: '', tags: '' });
  useEffect(() => { api.get('/api/ideas').then(setIdeas); }, [tick]);
  if (!ideas) return html`<div class="empty">Loading…</div>`;
  const lens = (path, depth) => go(`graph?root=${encodeURIComponent(path)}&depth=${depth}`);
  const set = (k) => (e) => setDraft({ ...draft, [k]: e.target.value });
  const add = async () => {
    const title = draft.title.trim() || draft.text.trim().split('\n')[0].slice(0, 80);
    if (!title) return toast('Give the idea a title or a sentence', 'err');
    try {
      await api.post('/api/idea', { title, text: draft.text, tags: draft.tags.split(/[,\s]+/).filter(Boolean) });
      toast(`Added ${title}`); setDraft({ title: '', text: '', tags: '' }); refreshAll();
    } catch (e) { toast(e.message, 'err'); }
  };

  return html`
  <div class="card" style="margin-bottom:16px">
    <div class="row" style="gap:8px;margin-bottom:8px">
      <input class="input" style="flex:2" placeholder="New idea: title" value=${draft.title} onInput=${set('title')} onKeyDown=${(e) => e.key === 'Enter' && add()} />
      <input class="input" style="flex:1" placeholder="tags (mcp, womens-health)" value=${draft.tags} onInput=${set('tags')} />
      <button class="btn primary" onClick=${add}>+ Add idea</button>
      <button class="btn ghost" title="Open the Ideas area note" onClick=${() => openNote('areas/Ideas.md')}>Area note</button>
    </div>
    <textarea class="input" rows="3" style="width:100%;resize:vertical" placeholder="Paste or jot the idea (markdown). Ctrl+Enter to add."
      value=${draft.text} onInput=${set('text')} onKeyDown=${(e) => e.key === 'Enter' && (e.ctrlKey || e.metaKey) && add()}></textarea>
  </div>
  <div class="stack" style="display:grid;gap:16px">
  ${ideas.map((i) => {
    const rank = (k) => (ORDER.includes(k) ? ORDER.indexOf(k) : 99);
    const kinds = Object.keys(i.counts).sort((a, b) => rank(a) - rank(b));
    return html`
    <div class="card">
      <div class="row" style="gap:8px">
        <h3 style="margin:0;cursor:pointer" onClick=${() => openNote(i.path)}>${i.name}</h3>
        ${(i.tags || []).filter((t) => t !== 'idea').map((t) => html`<span class="chip">#${t}</span>`)}
        ${i.created && html`<span class="dim mono" style="font-size:11px">${i.created}</span>`}
        <span class="sp"></span>
        <button class="btn sm" onClick=${() => openNote(i.path)}>Open note</button>
        <button class="btn primary sm" onClick=${() => lens(i.path, 2)}>◎ Explore graph</button>
      </div>
      ${i.summary && html`<p class="muted" style="margin:10px 0">${i.summary}</p>`}
      ${i.source && html`<div class="row" style="gap:6px;margin:8px 0"><span class="dim">Files</span><span class="mono" style="font-size:12px;user-select:all">${i.source}</span></div>`}
      ${kinds.length > 0 && html`<div class="row" style="gap:6px;margin:8px 0">${kinds.map((k) => html`
        <span class="chip" style=${{ color: typeColor(k) }}>${i.counts[k]} ${i.counts[k] === 1 ? k : PLURAL[k] || k}</span>`)}</div>`}
      ${i.topics.length > 0 && html`<div style="margin-top:10px"><div class="dim" style="font-size:12px;margin-bottom:6px">Topics · click to explore</div>
        <div class="chips">${i.topics.map((t) => html`<span class="chip click" style=${{ color: typeColor('topic') }} onClick=${() => lens(t.path, 2)}>${t.name}${t.count != null ? ` · ${t.count}` : ''}</span>`)}</div></div>`}
    </div>`;
  })}
  ${!ideas.length && html`<div class="empty">No ideas yet. Add a note with <span class="mono">area: "[[Ideas]]"</span>.</div>`}
  </div>`;
}
