// Minimal service worker: makes HIVE installable as an app and shows a friendly page if the local server is down.
// Always network-first: data is live from the local API, never served stale from cache.
const OFFLINE = `<!doctype html><meta charset="utf-8"><title>HIVE</title>
<body style="margin:0;height:100vh;display:grid;place-items:center;background:#0d0f12;color:#e8e6e1;font:15px Segoe UI,sans-serif;text-align:center">
<div><img src="/icons/icon-192.png" width="96" style="opacity:.8"><h2>The hive is asleep</h2>
<p style="color:#8b93a1">The local HIVE server isn't running.<br>Start it with <code>scripts\\install-server.ps1 -Start</code> or run <code>hive.ps1</code>.</p>
<button onclick="location.reload()" style="background:#f5a524;border:0;padding:8px 18px;border-radius:8px;font-weight:600;cursor:pointer">Retry</button></div>`;

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open('hive-shell-v1').then((c) => c.addAll(['/icons/icon-192.png'])));
  self.skipWaiting();
});
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', (e) => {
  if (e.request.mode !== 'navigate') return; // API/static requests go straight to the network
  e.respondWith(fetch(e.request).catch(() => new Response(OFFLINE, { headers: { 'Content-Type': 'text/html' } })));
});
