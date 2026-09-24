// Shared core: preact/htm, API client, event bus, markdown with [[wikilinks]], formatters.
import { h } from 'preact';
import htm from 'htm';
import { marked } from 'marked';
import DOMPurify from 'dompurify';

export const html = htm.bind(h);

// ---------- API ----------
async function req(method, url, body) {
  const opts = { method, headers: { 'X-Hive': '1' } };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(url, opts);
  const text = await r.text();
  const data = text ? JSON.parse(text) : null;
  if (!r.ok) throw new Error((data && data.detail) || `${r.status} ${r.statusText}`);
  return data;
}
export const api = {
  get: (url, params) => req('GET', params ? `${url}?${new URLSearchParams(params)}` : url),
  post: (url, body = {}) => req('POST', url, body),
  put: (url, body) => req('PUT', url, body),
  patch: (url, body) => req('PATCH', url, body),
  del: (url) => req('DELETE', url),
};

/** POST and consume a server-sent-event stream; calls onEvent(obj) per `data:` line. */
export async function streamPost(url, body, onEvent, signal) {
  const r = await fetch(url, {
    method: 'POST', signal,
    headers: { 'X-Hive': '1', 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const chunk = buf.slice(0, i);
      buf = buf.slice(i + 2);
      if (chunk.startsWith('data: ')) onEvent(JSON.parse(chunk.slice(6)));
    }
  }
}

// ---------- event bus ----------
const listeners = {};
export const bus = {
  on(ev, fn) { (listeners[ev] ||= new Set()).add(fn); return () => listeners[ev].delete(fn); },
  emit(ev, data) { (listeners[ev] || []).forEach((fn) => fn(data)); },
};
export const openNote = (path) => bus.emit('open-note', path);
export const toast = (text, kind = 'ok') => bus.emit('toast', { text, kind });
export const refreshAll = () => bus.emit('refresh');
export const go = (route) => { location.hash = route; };

// ---------- markdown ----------
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
marked.setOptions({ gfm: true, breaks: false });

export function renderMarkdown(src) {
  const withLinks = String(src || '')
    .replace(/\[\[([^\[\]|#^]+)(?:[#^][^\[\]|]*)?(?:\|([^\[\]]*))?\]\]/g,
      (_, t, alias) => `<a class="wl" data-target="${esc(t.trim())}">${esc((alias || t).trim())}</a>`)
    .replace(/(^|[\s(])#([A-Za-z][\w/-]*)/g, (_, pre, t) => `${pre}<span class="tg">#${esc(t)}</span>`);
  return DOMPurify.sanitize(marked.parse(withLinks), { ADD_ATTR: ['data-target'] });
}

/** Click handler for containers holding rendered markdown: resolves [[links]] and opens notes. */
export async function onMdClick(e) {
  const a = e.target.closest('a.wl');
  if (!a) return;
  e.preventDefault();
  try {
    const r = await api.get('/api/resolve', { target: a.dataset.target });
    openNote(r.path);
  } catch {
    toast(`No note named “${a.dataset.target}” yet`, 'err');
  }
}

export function Markdown({ src, cls = '' }) {
  return html`<div class=${'md ' + cls} onClick=${onMdClick} dangerouslySetInnerHTML=${{ __html: renderMarkdown(src) }}></div>`;
}

// ---------- formatting ----------
export const money = (v, cur = 'USD') => (v == null || isNaN(v)) ? '—'
  : new Intl.NumberFormat('en-US', { style: 'currency', currency: cur || 'USD', maximumFractionDigits: v >= 1000 ? 0 : 2 }).format(v);
export const compactMoney = (v) => v >= 1e6 ? `$${(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `$${(v / 1e3).toFixed(v >= 1e4 ? 0 : 1)}k` : money(v);
export const hours = (h) => `${h >= 10 ? Math.round(h) : (+h || 0).toFixed(2).replace(/\.?0+$/, '')}h`;
export const today = () => new Date().toLocaleDateString('en-CA');
export const linkText = (v) => (typeof v === 'string' ? v.replace(/^\[\[|\]\]$/g, '').split('|')[0] : v);
export function ago(days) {
  if (days == null) return 'never';
  if (days <= 0) return 'today';
  if (days === 1) return 'yesterday';
  if (days < 30) return `${days}d ago`;
  return `${Math.round(days / 30)}mo ago`;
}
export const initials = (name = '') => name.replace(/^(Dr|Mr|Ms|Mrs)\.?\s+/i, '').split(/\s+/).map((w) => w[0]).slice(0, 2).join('').toUpperCase();

// Node palette (also used by the graph legend)
export const TYPE_COLORS = {
  profile: '#ffffff', client: '#f5a524', contact: '#5aa9e6', contract: '#4cc38a', project: '#3cc6c0',
  meeting: '#e86fb0', email: '#a68cff', note: '#ffc85c', knowledge: '#ffc85c', invoice: '#d9822b',
  timelog: '#6b7280', briefing: '#c0c7d1', inbox: '#7c6bb0', draft: '#b08cff', tag: '#3a4452', ghost: '#4a4f58', system: '#5d6573',
};
export const COMMUNITY = ['#f5a524', '#5aa9e6', '#4cc38a', '#e86fb0', '#a68cff', '#3cc6c0', '#ef5b5b', '#ffc85c', '#8fd16a', '#d9822b', '#6fa8ff', '#c792ea'];
export const typeColor = (t) => TYPE_COLORS[t] || '#9aa3af';
export const hashColor = (s) => { let x = 0; for (const c of String(s)) x = (x * 31 + c.charCodeAt(0)) | 0; return COMMUNITY[Math.abs(x) % COMMUNITY.length]; };
