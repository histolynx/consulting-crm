import { useEffect, useRef, useState } from 'preact/hooks';
import { html, streamPost, toast, refreshAll, Markdown } from '../lib.js';

const STARTERS = [
  'What did I promise each client in the last two weeks, and what is overdue?',
  'Who in my network has worked with AWS or data platforms? Rank by relationship strength.',
  'Which knowledge notes could I reuse for my pipeline deals? Suggest an upsell.',
  'Summarise the state of every active contract in a table: burn, next step, risk.',
  'Draft a warm check-in for the contact I have neglected the longest.',
];
const TOOL_ICON = { Read: '📖', Glob: '🗂', Grep: '🔎', Write: '✍', Edit: '✎' };

let saved = { msgs: [], session: null };  // survives view switches within the session

export function Ask() {
  const [msgs, setMsgs] = useState(saved.msgs);
  const [session, setSession] = useState(saved.session);
  const [q, setQ] = useState('');
  const [mode, setMode] = useState('read');
  const [busy, setBusy] = useState(false);
  const abort = useRef(null);
  const end = useRef();
  useEffect(() => { saved = { msgs, session }; end.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }); }, [msgs, session]);

  const send = async (text) => {
    const question = (text ?? q).trim();
    if (!question || busy) return;
    setQ(''); setBusy(true);
    const idx = msgs.length + 1;
    setMsgs((m) => [...m, { role: 'user', text: question, mode }, { role: 'hive', text: '', tools: [], live: true }]);
    const patch = (fn) => setMsgs((m) => m.map((x, i) => (i === idx ? fn(x) : x)));
    abort.current = new AbortController();
    try {
      await streamPost('/api/ask', { question, mode, session_id: session }, (ev) => {
        if (ev.kind === 'init') setSession(ev.session_id);
        if (ev.kind === 'tool') patch((x) => ({ ...x, tools: [...x.tools, ev] }));
        if (ev.kind === 'text') patch((x) => ({ ...x, text: x.text ? `${x.text}\n\n${ev.text}` : ev.text }));
        if (ev.kind === 'result') { setSession(ev.session_id); patch((x) => ({ ...x, text: x.text || ev.text, meta: ev, live: false })); }
        if (ev.kind === 'error') patch((x) => ({ ...x, error: ev.text, live: false }));
        if (ev.kind === 'commit') { toast(`Changes committed (${ev.sha})`); refreshAll(); }
      }, abort.current.signal);
    } catch (e) {
      if (e.name !== 'AbortError') patch((x) => ({ ...x, error: e.message }));
    }
    patch((x) => ({ ...x, live: false }));
    setBusy(false);
  };
  const reset = () => { setMsgs([]); setSession(null); };

  return html`<div class="chat">
    ${!msgs.length && html`<div style="text-align:center;padding:40px 0 10px">
      <div class="brand" style="justify-content:center"><div class="logo" style="width:54px;height:60px"></div></div>
      <h2 style="margin:10px 0 4px">Ask the Hive</h2>
      <div class="muted">Claude Code reads your vault (graph-aware, cites notes as links). Switch to <b>Can edit</b> to let it update notes. Every change is git-committed.</div>
      <div class="col" style="margin-top:22px;align-items:center">${STARTERS.map((s) => html`<button class="btn" style="max-width:640px;white-space:normal;text-align:left" onClick=${() => send(s)}>✦ ${s}</button>`)}</div></div>`}
    ${msgs.map((m) => html`<div class=${'msg ' + m.role}>
      <div class="who">${m.role === 'user' ? 'YOU' : 'H'}</div>
      <div class="bubble">
        ${m.role === 'user' ? html`<div style="white-space:pre-wrap">${m.text}</div>${m.mode === 'write' && html`<span class="chip amber" style="margin-top:6px">can edit</span>`}` : html`
          ${m.tools?.length > 0 && html`<div class="tools">${m.tools.map((t) => html`<span class="chip" title=${t.detail}>${TOOL_ICON[t.name] || '⚙'} ${t.name} <span class="dim">${(t.detail || '').split('/').pop().slice(0, 40)}</span></span>`)}</div>`}
          ${m.text ? html`<${Markdown} src=${m.text} />` : m.live && html`<span class="thinking"><i></i><i></i><i></i></span>`}
          ${m.error && html`<div style="color:var(--red);margin-top:8px">⚠ ${m.error}</div>`}
          ${m.meta && html`<div class="dim mono" style="font-size:11px;margin-top:8px">${m.meta.turns} turns · ${(m.meta.duration_ms / 1000).toFixed(1)}s${m.meta.cost != null ? ` · $${m.meta.cost.toFixed(4)} API-equivalent` : ''}</div>`}`}
      </div></div>`)}
    <div ref=${end}></div>
  </div>
  <div class="composer"><div class="box">
    <textarea rows="2" placeholder="Ask anything about your clients, contracts, people, knowledge…  (Enter to send, Shift+Enter for newline)" value=${q}
      onInput=${(e) => setQ(e.target.value)} onKeyDown=${(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }}></textarea>
    <div class="row">
      <div class="seg"><button class=${mode === 'read' ? 'on' : ''} onClick=${() => setMode('read')}>Read-only</button><button class=${mode === 'write' ? 'on' : ''} onClick=${() => setMode('write')}>Can edit</button></div>
      ${session && html`<span class="chip">session ${session.slice(0, 8)}</span><button class="btn ghost sm" onClick=${reset}>new chat</button>`}
      <span class="sp"></span>
      ${busy ? html`<button class="btn sm" onClick=${() => abort.current?.abort()}>■ Stop</button>` : html`<button class="btn primary sm" onClick=${() => send()}>Send ↵</button>`}
    </div></div></div>`;
}
