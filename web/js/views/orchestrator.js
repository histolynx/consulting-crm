import { useEffect, useState } from 'preact/hooks';
import { html, api, openNote, toast, refreshAll, hashColor } from '../lib.js';
import { CleanupCard } from './cleanup.js';

function AreaChip({ area }) {
  if (!area) return null;
  const c = hashColor(area);
  return html`<span class="chip" style=${{ color: c, borderColor: c + '66', background: c + '14' }}>⬢ ${area}</span>`;
}

function Card({ p, areas, homes, onDone }) {
  const s = p.suggestion || {};
  const [area, setArea] = useState(s.area || '');
  const [topic, setTopic] = useState(s.topic || '');
  const [home, setHome] = useState(s.home || '');
  const [busy, setBusy] = useState(false);
  const act = async (action, extra = {}) => {
    setBusy(true);
    try {
      const r = await api.post('/api/orchestrator/decide', { id: p.id, action, area, topic, home, ...extra });
      toast(action === 'reject' ? `Skipped ${p.name}` : action === 'answer' ? 'Answer saved' : `Filed → ${r.filed_to}`);
      onDone();
      if (r.filed_to && r.filed_to.endsWith('.md')) openNote(r.filed_to);
    } catch (e) { toast(e.message, 'err'); } finally { setBusy(false); }
  };
  const conf = s.confidence != null ? Math.round(s.confidence * 100) : null;
  return html`<div class="card" style="margin-bottom:12px">
    <div class="row" style="gap:8px"><b style="font-size:15px">${p.name}</b><span class="dim mono" style="font-size:11px">${(p.size / 1024).toFixed(1)} KB · ${p.modified?.slice(0, 10)}</span>
      <span class="sp"></span>${p.status === 'new' ? html`<span class="chip">classifying…</span>` : html`<${AreaChip} area=${s.area} />${conf != null && html`<span class=${'chip ' + (conf >= 60 ? 'green' : 'amber')}>${conf}% sure</span>`}`}</div>
    <div class="dim mono" style="font-size:11px;margin:4px 0 8px">${p.path}</div>
    ${s.summary && html`<div style="margin-bottom:8px">${s.summary}</div>`}
    ${p.question && html`<div class="card" style="padding:10px;margin-bottom:10px;border-color:var(--amber)">
      <div style="margin-bottom:6px">❓ ${p.question.text}</div>
      <div class="row" style="gap:6px">${p.question.options.map((o) => html`<span class="chip click on" onClick=${() => act('answer', { answer: o })}>${o}</span>`)}</div></div>`}
    ${p.status === 'proposed' && html`<div class="row">
      <label class="f">Area<select class="select" value=${area} onChange=${(e) => setArea(e.target.value)}>${areas.map((a) => html`<option>${a}</option>`)}</select></label>
      <label class="f">Topic folder<input class="input" value=${topic} onInput=${(e) => setTopic(e.target.value)} /></label>
      <label class="f" style="min-width:240px">Linked project<select class="select" value=${home} onChange=${(e) => setHome(e.target.value)}>
        <option value="">(none)</option>${homes.map((h) => html`<option>${h}</option>`)}</select></label>
      <span class="sp"></span>
      <button class="btn primary" disabled=${busy} onClick=${() => act('copy')} title="Copy into HIVE; the original stays where it is">⇩ Copy in</button>
      <button class="btn" disabled=${busy} onClick=${() => act('move')} title="Move into HIVE (the original is removed after a successful copy)">Move in</button>
      <button class="btn ghost danger" disabled=${busy} onClick=${() => act('reject')}>Skip</button></div>`}
  </div>`;
}

export function Orchestrator({ tick }) {
  const [d, setD] = useState(null);
  const [homes, setHomes] = useState([]);
  const [busy, setBusy] = useState(false);
  const [watchText, setWatchText] = useState('');
  const load = () => {
    api.get('/api/orchestrator').then((x) => { setD(x); setWatchText(x.config.watch.join('\n')); });
    Promise.all(['contract', 'project', 'opportunity'].map((t) => api.get('/api/notes', { type: t })))
      .then((rs) => setHomes(rs.flat().map((n) => n.title).sort()));
  };
  useEffect(load, [tick]);
  useEffect(() => {
    if (!d || !d.open.some((p) => p.status === 'new')) return;
    const t = setInterval(load, 4000);  // poll while the agent classifies
    return () => clearInterval(t);
  }, [d]);
  const scan = async () => {
    setBusy(true);
    try { await api.post('/api/orchestrator/scan'); toast('Scanning… new files appear here in a minute'); setTimeout(load, 5000); setTimeout(load, 30000); }
    catch (e) { toast(e.message, 'err'); } finally { setBusy(false); }
  };
  const bulk = async () => {
    setBusy(true);
    try { const r = await api.post('/api/orchestrator/bulk', { min_confidence: 0.8 }); toast(`Filed ${r.filed} file(s)${r.errors.length ? `, ${r.errors.length} error(s)` : ''}`, r.errors.length ? 'err' : 'ok'); load(); refreshAll(); }
    catch (e) { toast(e.message, 'err'); } finally { setBusy(false); }
  };
  const saveWatch = async () => { await api.post('/api/orchestrator/config', { watch: watchText.split('\n').map((x) => x.trim()).filter(Boolean) }); toast('Watched folders saved'); load(); };
  if (!d) return html`<div class="thinking"><i></i><i></i><i></i></div>`;
  return html`
  <div class="kpis">
    <div class="kpi" style="--kc:var(--amber)"><div class="l">Waiting for you</div><div class="v">${d.stats.open}</div></div>
    <div class="kpi" style="--kc:var(--green)"><div class="l">Filed into HIVE</div><div class="v">${d.stats.filed}</div></div>
    <div class="kpi" style="--kc:var(--violet)"><div class="l">Personal files skipped</div><div class="v">${d.stats.personal_skipped || 0}</div><div class="s">never read or recorded</div></div>
    <div class="kpi" style="--kc:var(--blue)"><div class="l">Last scan</div><div class="v" style="font-size:16px">${(d.stats.last_scan || 'never').replace('T', ' ')}</div><div class="s">every 15 min</div></div>
  </div>
  <div class="row" style="margin-bottom:14px"><span class="muted">I watch your work folders, propose where new files belong, and file them only when you click. Personal files are skipped by name, unread.</span>
    <span class="sp"></span>${d.open.some((p) => p.status === 'proposed' && !p.question && (p.suggestion?.confidence || 0) >= 0.8) && html`<button class="btn" disabled=${busy} onClick=${bulk} title="Copy every proposal that is at least 80% sure and has no open question">⇩ File all confident (≥80%)</button>`}<button class="btn primary" disabled=${busy} onClick=${scan}>⟳ Scan now</button></div>
  ${d.open.length ? d.open.map((p) => html`<${Card} key=${p.id} p=${p} areas=${d.areas} homes=${homes} onDone=${() => { load(); refreshAll(); }} />`)
    : html`<div class="card"><div class="empty">Nothing waiting. New work files in your watched folders will show up here.</div></div>`}
  <${CleanupCard} folders=${d.config.watch} />
  <div class="grid2" style="margin-top:16px">
    <div class="card"><h3>Recently filed</h3><div class="list">${d.recent.map((p) => html`<div class="li">
      <span class=${'chip ' + (p.status === 'filed' ? 'green' : '')}>${p.status}</span><span class="sp">${p.name}</span>
      ${p.filed_to && html`<a style="cursor:pointer;font-size:12px" onClick=${() => openNote(p.filed_to.endsWith('.md') ? p.filed_to : p.filed_to)}>${p.filed_to}</a>`}</div>`)}
      ${!d.recent.length && html`<div class="empty">None yet.</div>`}</div></div>
    <div class="card"><h3>Watched folders</h3>
      <textarea class="input mono" rows="4" style="font-size:12px" value=${watchText} onInput=${(e) => setWatchText(e.target.value)}></textarea>
      <div class="row" style="margin-top:8px"><span class="dim" style="font-size:12px">One folder per line. The HIVE vault is always excluded.</span><span class="sp"></span><button class="btn sm" onClick=${saveWatch}>Save</button></div>
      <div class="row" style="gap:6px;margin-top:10px">${d.areas.map((a) => html`<${AreaChip} area=${a} />`)}</div></div>
  </div>`;
}
