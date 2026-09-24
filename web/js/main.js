import { render } from 'preact';
import { useEffect, useState } from 'preact/hooks';
import { html, api, bus, toast, refreshAll, go } from './lib.js';
import { NoteDrawer, Toasts, Palette, NewNoteModal } from './components.js';
import { Dashboard } from './views/dashboard.js';
import { GraphView } from './views/graph.js';
import { Contacts } from './views/contacts.js';
import { Contracts } from './views/contracts.js';
import { TimeView } from './views/time.js';
import { Invoices } from './views/invoices.js';
import { Inbox } from './views/inbox.js';
import { Ask } from './views/ask.js';
import { Setup } from './views/setup.js';

const VIEWS = [
  { id: 'dashboard', label: 'Hive', icon: '⬢', C: Dashboard, key: '1' },
  { id: 'graph', label: 'Graph', icon: '✺', C: GraphView, full: true, key: '2' },
  { id: 'contacts', label: 'Contacts', icon: '◉', C: Contacts, key: '3' },
  { id: 'contracts', label: 'Contracts', icon: '▦', C: Contracts, key: '4' },
  { id: 'time', label: 'Time', icon: '◷', C: TimeView, key: '5' },
  { id: 'invoices', label: 'Invoices', icon: '$', C: Invoices, key: '6' },
  { id: 'inbox', label: 'Inbox', icon: '✉', C: Inbox, key: '7' },
  { id: 'ask', label: 'Ask the Hive', icon: '✦', C: Ask, key: '8' },
  { id: 'setup', label: 'Setup', icon: '⚙', C: Setup, key: '9' },
];

function parseHash() {
  const [id, qs] = location.hash.replace(/^#/, '').split('?');
  return { id: id || 'dashboard', params: Object.fromEntries(new URLSearchParams(qs || '')) };
}

function fmtClock(sec) {
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

function Timer() {
  const [timer, setTimer] = useState(null);
  const [contracts, setContracts] = useState([]);
  const [contract, setContract] = useState('');
  const [desc, setDesc] = useState('');
  const [now, setNow] = useState(Date.now());
  const load = () => api.get('/api/timer').then((r) => setTimer(r.timer));
  useEffect(() => {
    load();
    api.get('/api/contracts').then((cs) => {
      const order = ['active', 'negotiating', 'proposal'];
      const act = cs.filter((c) => order.includes(c.status)).sort((a, b) => order.indexOf(a.status) - order.indexOf(b.status));
      setContracts(act);
      if (act[0]) setContract((c) => c || act[0].name);
    });
    const i = setInterval(() => setNow(Date.now()), 1000);
    const off = bus.on('timer-changed', load);
    return () => { clearInterval(i); off(); };
  }, []);
  const start = async () => {
    try { setTimer(await api.post('/api/timer/start', { contract: contract || null, description: desc })); bus.emit('timer-changed'); toast('Timer started'); }
    catch (e) { toast(e.message, 'err'); }
  };
  const stop = async () => {
    const r = await api.post('/api/timer/stop');
    setTimer(null); setDesc(''); bus.emit('timer-changed');
    toast(r.entry ? `Logged ${(r.entry.minutes / 60).toFixed(2)}h → ${r.entry.contract || 'no contract'}` : 'Timer under a minute: discarded');
    refreshAll();
  };
  if (timer) {
    const secs = Math.max(0, Math.floor((now - new Date(timer.started).getTime()) / 1000));
    return html`<div class="timer running"><span class="dot"></span>
      <span title=${timer.description}>${timer.contract || 'No contract'}${timer.section ? html` <span class="dim">· ${timer.section}</span>` : ''}</span>
      <span class="clock">${fmtClock(secs)}</span>
      <button class="btn primary sm round" onClick=${stop}>■ Stop</button></div>`;
  }
  return html`<div class="timer">
    <select value=${contract} onChange=${(e) => setContract(e.target.value)}>
      <option value="">No contract</option>${contracts.map((c) => html`<option value=${c.name}>${c.name}</option>`)}</select>
    <input placeholder="What are you working on?" value=${desc} onInput=${(e) => setDesc(e.target.value)} onKeyDown=${(e) => e.key === 'Enter' && start()} />
    <button class="btn primary sm round" onClick=${start}>▶ Start</button></div>`;
}

function App() {
  const [route, setRoute] = useState(parseHash());
  const [palette, setPalette] = useState(false);
  const [creating, setCreating] = useState(null);
  const [tick, setTick] = useState(0);
  const [health, setHealth] = useState(null);

  useEffect(() => {
    const onHash = () => setRoute(parseHash());
    addEventListener('hashchange', onHash);
    const offR = bus.on('refresh', () => { setTick((t) => t + 1); api.get('/api/health').then(setHealth); });
    const offN = bus.on('new-note', (type) => setCreating(type));
    api.get('/api/health').then((h) => {
      setHealth(h);
      window.HIVE_VAULT_NAME = h.vault.split(/[\\/]/).pop();
    });
    const key = (e) => {
      const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName);
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setPalette((p) => !p); }
      else if (e.altKey && /^[1-9]$/.test(e.key)) { const v = VIEWS.find((x) => x.key === e.key); if (v) go(v.id); }
      else if (!typing && e.key === '/' && !document.querySelector('.overlay')) { e.preventDefault(); setPalette(true); }
    };
    addEventListener('keydown', key);
    return () => { removeEventListener('hashchange', onHash); removeEventListener('keydown', key); offR(); offN(); };
  }, []);

  const view = VIEWS.find((v) => v.id === route.id) || VIEWS[0];
  const commands = [
    ...VIEWS.map((v) => ({ label: `Go to ${v.label}`, icon: v.icon, run: () => go(v.id) })),
    ...['contact', 'client', 'contract', 'meeting', 'project', 'note'].map((t) => ({ label: `New ${t}`, icon: '+', run: () => setCreating(t) })),
    { label: 'Sync mail now (fetch → ingest → drafts → time gaps)', icon: '⟳', run: async () => { try { await api.post('/api/sync'); toast('Sync started'); go('inbox'); } catch (e) { toast(e.message, 'err'); } } },
    { label: 'Write today’s briefing', icon: '☀', run: async () => { try { await api.post('/api/brief'); toast('Briefing started: Claude is writing'); } catch (e) { toast(e.message, 'err'); } } },
    { label: 'Scan for missed time', icon: '◷', run: async () => { const r = await api.post('/api/time/gaps/apply'); toast(`${r.length} suggested entr${r.length === 1 ? 'y' : 'ies'} added`); refreshAll(); } },
  ];
  const isDemo = health && /demo-vault$/.test(health.vault.replace(/[\\/]+$/, ''));

  return html`<div class="shell">
    <aside class="side">
      <div class="brand"><img class="logoimg" src="/icons/hive.svg" alt="" /><div title="Hub for Independent Venture Ecosystem"><b>HIVE</b><small>Hub for Independent<br />Venture Ecosystem</small></div></div>
      ${VIEWS.map((v) => html`<div class=${'nav' + (v.id === view.id ? ' on' : '')} onClick=${() => go(v.id)} title=${`Alt+${v.key}`}>
        <span class="ico">${v.icon}</span><span class="lbl">${v.label}</span></div>`)}
      <div class="spacer"></div>
      ${isDemo && html`<div class="chip amber" style="margin:0 8px 8px">DEMO VAULT</div>`}
      <div class="foot"><span class="kbd">Ctrl</span> <span class="kbd">K</span> search · <span class="kbd">Alt</span> <span class="kbd">1-9</span> views</div>
    </aside>
    <main class="main">
      <div class="top">
        <h1>${view.label}</h1>
        <div class="searchbtn" onClick=${() => setPalette(true)}>⌕ <span>Search or command…</span><span class="sp"></span><span class="kbd">Ctrl K</span></div>
        <div class="grow"></div>
        <${Timer} />
      </div>
      <div class=${'content hexbg' + (view.full ? ' full' : '')}>
        <${view.C} key=${view.id} params=${route.params} tick=${tick} health=${health} />
      </div>
    </main>
    <${NoteDrawer} />
    ${palette && html`<${Palette} onClose=${() => setPalette(false)} commands=${commands} />`}
    ${creating && html`<${NewNoteModal} type=${creating} onClose=${() => setCreating(null)} />`}
    <${Toasts} />
  </div>`;
}

render(html`<${App} />`, document.getElementById('app'));
