// Folder cleanup: the AI plans, you tick, a script moves files, every run can be undone.
import { useEffect, useState } from 'preact/hooks';
import { html, api, toast, refreshAll } from '../lib.js';
import { Modal } from '../components.js';

const GROUPS = [
  { kind: 'processed', title: 'Already in HIVE → Processed folder', hint: 'Originals of files HIVE has copied in.', on: true },
  { kind: 'organize', title: 'Work files → Google Drive area folders', hint: 'Confident classification (≥60%).', on: true },
  { kind: 'duplicate', title: 'Exact duplicates → 30-day holding folder', hint: 'Byte-identical; the newest copy stays.', on: true },
  { kind: 'ask', title: 'Needs you (left in place)', hint: 'Decide these in the Orchestrator cards above.', on: false },
];

function PlanModal({ plan, onClose, onApplied }) {
  const [sel, setSel] = useState(() => new Set(plan.ops.filter((o) => o.dst && GROUPS.find((g) => g.kind === o.kind)?.on).map((o) => o.id)));
  const [busy, setBusy] = useState(false);
  const toggle = (id) => setSel((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const apply = async () => {
    setBusy(true);
    try {
      const r = await api.post('/api/cleanup/apply', { plan: plan.id, ops: [...sel] });
      toast(`Moved ${r.moved.length} file(s)${r.errors.length ? `, ${r.errors.length} error(s)` : ''}. Undo is available below.`, r.errors.length ? 'err' : 'ok');
      onApplied(); onClose();
    } catch (e) { toast(e.message, 'err'); } finally { setBusy(false); }
  };
  return html`<${Modal} title=${`Cleanup plan: ${plan.folder}`} onClose=${onClose} wide
      footer=${html`<span class="dim" style="margin-right:auto;font-size:12px">${plan.personal_skipped} personal file(s) not listed, not touched. Nothing is deleted.</span>
        <button class="btn ghost" onClick=${onClose}>Cancel</button><button class="btn primary" disabled=${busy || !sel.size} onClick=${apply}>Move ${sel.size} file(s)</button>`}>
    ${GROUPS.map((g) => {
      const ops = plan.ops.filter((o) => o.kind === g.kind);
      if (!ops.length) return null;
      const all = ops.filter((o) => o.dst).every((o) => sel.has(o.id));
      return html`<div class="card" style="padding:12px">
        <h3 style="margin-bottom:6px">${g.title} <span class="dim" style="text-transform:none;letter-spacing:0">(${ops.length})</span><span class="sp"></span>
          ${g.kind !== 'ask' && html`<button class="btn ghost sm" onClick=${() => setSel((s) => { const n = new Set(s); ops.forEach((o) => (all ? n.delete(o.id) : n.add(o.id))); return n; })}>${all ? 'untick all' : 'tick all'}</button>`}</h3>
        <div class="dim" style="font-size:12px;margin-bottom:6px">${g.hint}</div>
        <div class="list" style="max-height:260px;overflow:auto">${ops.map((o) => html`<label class="li" style="cursor:${o.dst ? 'pointer' : 'default'};font-size:13px">
          ${o.dst ? html`<input type="checkbox" checked=${sel.has(o.id)} onChange=${() => toggle(o.id)} />` : html`<span style="width:13px"></span>`}
          <span style="min-width:0;flex:1"><b>${o.name}</b><div class="dim" style="font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${o.dst ? `→ ${o.dst}` : o.why}</div></span>
          ${o.dst && html`<span class="dim" style="font-size:11px;max-width:40%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${o.why}</span>`}</label>`)}</div></div>`;
    })}
  <//>`;
}

export function CleanupCard({ folders }) {
  const [folder, setFolder] = useState(folders[0] || '');
  const [plan, setPlan] = useState(null);
  const [runs, setRuns] = useState([]);
  const [busy, setBusy] = useState(false);
  const loadRuns = () => api.get('/api/cleanup/runs').then(setRuns);
  useEffect(() => { loadRuns(); }, []);
  useEffect(() => { if (!folder && folders[0]) setFolder(folders[0]); }, [folders]);
  const makePlan = async () => {
    setBusy(true);
    try { setPlan(await api.post('/api/cleanup/plan', { folder })); } catch (e) { toast(e.message, 'err'); } finally { setBusy(false); }
  };
  const undo = async (id) => {
    try { const r = await api.post('/api/cleanup/undo', { plan: id }); toast(`Restored ${r.restored} file(s)${r.errors.length ? `, ${r.errors.length} error(s)` : ''}`, r.errors.length ? 'err' : 'ok'); loadRuns(); refreshAll(); }
    catch (e) { toast(e.message, 'err'); }
  };
  return html`<div class="card" style="margin-top:16px"><h3>🧹 Clean up a folder</h3>
    <div class="muted" style="font-size:13px;margin-bottom:10px">I make a plan; you tick what to apply; a plain script moves the files. Every run can be undone, nothing is deleted, and personal files are never listed or touched.</div>
    <div class="row"><select class="select" style="max-width:420px" value=${folder} onChange=${(e) => setFolder(e.target.value)}>${folders.map((f) => html`<option>${f}</option>`)}</select>
      <button class="btn primary" disabled=${busy || !folder} onClick=${makePlan}>${busy ? 'Planning…' : 'Plan cleanup'}</button></div>
    ${runs.length > 0 && html`<div class="list" style="margin-top:12px">${runs.map((r) => html`<div class="li" style="font-size:13px">
      <span class="mono dim">${r.applied.replace('T', ' ')}</span><span class="sp">moved ${r.moved}${r.errors ? `, ${r.errors} error(s)` : ''}</span>
      ${r.undone ? html`<span class="chip">undone</span>` : html`<button class="btn sm" onClick=${() => undo(r.plan)}>↶ Undo</button>`}</div>`)}</div>`}
    ${plan && html`<${PlanModal} plan=${plan} onClose=${() => setPlan(null)} onApplied=${() => { loadRuns(); refreshAll(); }} />`}
  </div>`;
}
