// Graph explorer: 2D canvas hexagons (force-graph) or 3D (3d-force-graph, lazy-loaded).
import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import { html, api, openNote, toast, refreshAll, go, typeColor, TYPE_COLORS, COMMUNITY } from '../lib.js';

const HIDEABLE = ['email', 'timelog', 'inbox', 'invoice', 'meeting', 'briefing', 'draft', 'ghost', 'system'];
const DEFAULT_HIDE = ['timelog', 'inbox', 'system', 'briefing'];

let load3d;
function ensure3d() {
  load3d ||= new Promise((res, rej) => {
    const s = document.createElement('script');
    s.src = '/vendor/3d-force-graph.min.js';
    s.onload = () => res(window.ForceGraph3D);
    s.onerror = rej;
    document.head.appendChild(s);
  });
  return load3d;
}

// Weak pull toward the origin so disconnected clusters stay in frame (d3 isn't exported by force-graph).
function gravity(k = 0.07) {
  let nodes = [];
  const f = (alpha) => {
    for (const n of nodes) { n.vx -= n.x * k * alpha; n.vy -= n.y * k * alpha; if (n.z !== undefined) n.vz -= n.z * k * alpha; }
  };
  f.initialize = (ns) => { nodes = ns; };
  return f;
}

function hexPath(ctx, x, y, r) {
  ctx.beginPath();
  for (let i = 0; i < 6; i++) {
    const a = (Math.PI / 3) * i + Math.PI / 6;
    ctx[i ? 'lineTo' : 'moveTo'](x + r * Math.cos(a), y + r * Math.sin(a));
  }
  ctx.closePath();
}

export function GraphView({ params, tick }) {
  const box = useRef();
  const fgRef = useRef();
  const hl = useRef({ nodes: new Set(), links: new Set(), hover: null, selected: null, path: new Set() });
  const [mode, setMode] = useState('2d');
  const [colorBy, setColorBy] = useState('type');
  const [tags, setTags] = useState(false);
  const [hide, setHide] = useState(DEFAULT_HIDE);
  const [depth, setDepth] = useState(Number(params.depth || 2));
  const [data, setData] = useState(null);
  const [selected, setSelected] = useState(null);
  const [q, setQ] = useState('');
  const [pathTo, setPathTo] = useState('');
  const [suggest, setSuggest] = useState([]);
  const root = params.root || null;
  const colorByRef = useRef(colorBy);
  colorByRef.current = colorBy;

  // ---- data
  useEffect(() => {
    const p = { tags, hide: hide.join(',') };
    if (root) Object.assign(p, { root, depth });
    api.get('/api/graph', p).then((g) => {
      const idx = new Map(g.nodes.map((n) => [n.id, n]));
      g.links.forEach((l) => {
        const a = idx.get(l.source), b = idx.get(l.target);
        if (!a || !b) return;
        (a.nbrs ||= new Set()).add(b.id); (b.nbrs ||= new Set()).add(a.id);
        (a.lnks ||= []).push(l); (b.lnks ||= []).push(l);
      });
      setData(g);
    }).catch((e) => toast(e.message, 'err'));
    api.get('/api/graph/suggest', { limit: 8 }).then(setSuggest);
  }, [tags, hide.join(','), root, depth, tick]);

  const maxPr = useMemo(() => Math.max(1e-9, ...(data?.nodes || []).map((n) => n.pagerank)), [data]);
  const nodeColor = (n) => {
    const h = hl.current;
    if (h.path.size && !h.path.has(n.id)) return '#2a2f38';
    if ((h.hover || h.selected) && h.nodes.size && !h.nodes.has(n.id)) return '#2e343e';
    return colorByRef.current === 'community' && n.community >= 0 ? COMMUNITY[n.community % COMMUNITY.length] : typeColor(n.type);
  };
  const nodeSize = (n) => 2.5 + 8 * Math.sqrt(n.pagerank / maxPr);

  const setFocus = (node) => {
    const h = hl.current;
    h.nodes = new Set(); h.links = new Set();
    if (node) {
      h.nodes.add(node.id);
      (node.nbrs || []).forEach((x) => h.nodes.add(x));
      (node.lnks || []).forEach((l) => h.links.add(l));
    }
  };

  // ---- create graph instance per mode
  useEffect(() => {
    if (!data || !box.current) return;
    let fg, disposed = false;
    const el = box.current;
    el.innerHTML = '';
    const common = (g) => g
      .graphData({ nodes: data.nodes, links: data.links })
      .nodeId('id').nodeLabel((n) => `${n.title} · ${n.type} · degree ${n.degree}`)
      .nodeVal((n) => nodeSize(n) ** 1.3)
      .linkLabel((l) => l.label)
      .linkDirectionalParticles((l) => (hl.current.links.has(l) || hl.current.path.has(l.__pathKey) ? 3 : 0))
      .linkDirectionalParticleWidth(2.2)
      .linkDirectionalParticleColor(() => '#ffc85c')
      .onNodeHover((n) => { hl.current.hover = n || null; if (!hl.current.selected) setFocus(n); el.style.cursor = n ? 'pointer' : 'default'; refresh(); })
      .onNodeClick((n) => { hl.current.selected = n; setFocus(n); setSelected(n); refresh(); })
      .onBackgroundClick(() => { hl.current.selected = null; hl.current.path = new Set(); setFocus(null); setSelected(null); refresh(); });

    const refresh = () => fg && fg.nodeColor(fg.nodeColor());

    if (mode === '2d') {
      fg = common(window.ForceGraph()(el))
        .backgroundColor('rgba(0,0,0,0)')
        .autoPauseRedraw(false)
        .linkColor((l) => (hl.current.path.has(l.__pathKey) ? '#ffc85c' : hl.current.links.has(l) ? 'rgba(245,165,36,.7)' : 'rgba(120,130,150,.18)'))
        .linkWidth((l) => (hl.current.links.has(l) || hl.current.path.has(l.__pathKey) ? 1.8 : 0.6))
        .nodeCanvasObject((n, ctx, scale) => {
          const r = nodeSize(n);
          const c = nodeColor(n);
          const focus = hl.current.selected === n || hl.current.hover === n || hl.current.path.has(n.id);
          if (focus) { ctx.shadowColor = '#f5a524'; ctx.shadowBlur = 25; }
          if (n.type === 'tag') { ctx.beginPath(); ctx.arc(n.x, n.y, r * 0.6, 0, 2 * Math.PI); ctx.fillStyle = '#3a4452'; ctx.fill(); }
          else {
            hexPath(ctx, n.x, n.y, r);
            ctx.fillStyle = n.type === 'ghost' ? 'transparent' : c; ctx.fill();
            ctx.lineWidth = focus ? 2 / scale * 2 : 1 / scale;
            ctx.strokeStyle = n.type === 'ghost' ? '#6b7280' : 'rgba(0,0,0,.55)';
            if (n.type === 'ghost') ctx.setLineDash([2 / scale, 2 / scale]);
            ctx.stroke(); ctx.setLineDash([]);
          }
          ctx.shadowBlur = 0;
          const important = n.pagerank / maxPr > 0.35;
          if (scale > 1.4 || important || focus || hl.current.nodes.has(n.id)) {
            const fs = Math.max(10 / scale, focus ? 4.5 : 3.2);
            ctx.font = `${focus ? 600 : 400} ${fs}px Segoe UI, sans-serif`;
            ctx.textAlign = 'center'; ctx.textBaseline = 'top';
            const dimmed = (hl.current.hover || hl.current.selected) && hl.current.nodes.size && !hl.current.nodes.has(n.id);
            ctx.fillStyle = dimmed ? 'rgba(200,200,200,.2)' : focus ? '#ffe2a8' : 'rgba(232,230,225,.85)';
            ctx.fillText(n.title, n.x, n.y + r + 2);
          }
        })
        .nodePointerAreaPaint((n, color, ctx) => { hexPath(ctx, n.x, n.y, nodeSize(n) + 2); ctx.fillStyle = color; ctx.fill(); })
        .d3VelocityDecay(0.28)
        .warmupTicks(80)
        .cooldownTicks(200);
      let fitted = false;
      fg.onEngineStop(() => { if (!fitted && !disposed) { fitted = true; fg.zoomToFit(600, 70); } });
      fg.d3Force('charge').strength(-110);
      fg.d3Force('gravity', gravity());
      fg.d3Force('link').distance((l) => (l.label === 'tagged' ? 60 : 42));
      setTimeout(() => !disposed && !fitted && fg.zoomToFit(400, 70), 400);
    } else {
      ensure3d().then((FG3) => {
        if (disposed) return;
        fg = common(FG3()(el))
          .backgroundColor('#0d0f12')
          .nodeColor(nodeColor)
          .nodeOpacity(0.95)
          .nodeResolution(12)
          .linkColor((l) => (hl.current.path.has(l.__pathKey) ? '#ffc85c' : hl.current.links.has(l) ? '#f5a524' : '#39414e'))
          .linkOpacity(0.35)
          .linkWidth((l) => (hl.current.links.has(l) || hl.current.path.has(l.__pathKey) ? 1.2 : 0))
          .nodeThreeObjectExtend(false);
        fg.d3Force('charge').strength(-60);
        fg.d3Force('gravity', gravity(0.05));
        fgRef.current = fg;
        resize();
      }).catch(() => toast('Could not load 3D engine', 'err'));
    }
    fgRef.current = fg;
    const resize = () => fgRef.current && fgRef.current.width(el.clientWidth).height(el.clientHeight);
    const ro = new ResizeObserver(resize);
    ro.observe(el);
    resize();
    return () => { disposed = true; ro.disconnect(); fgRef.current?._destructor?.(); fgRef.current = null; el.innerHTML = ''; };
  }, [data, mode]);

  useEffect(() => { const fg = fgRef.current; fg && fg.nodeColor && fg.nodeColor(fg.nodeColor()); }, [colorBy]);

  const flyTo = (n) => {
    const fg = fgRef.current;
    if (!fg || !n) return;
    hl.current.selected = n; setFocus(n); setSelected(n);
    if (mode === '2d') { fg.centerAt(n.x, n.y, 700); fg.zoom(3.2, 700); }
    else {
      const d = 90, r = 1 + d / Math.hypot(n.x, n.y, n.z || 1);
      fg.cameraPosition({ x: n.x * r, y: n.y * r, z: n.z * r }, n, 1000);
    }
  };
  const find = () => {
    const ql = q.toLowerCase();
    const n = data?.nodes.find((x) => x.title.toLowerCase() === ql) || data?.nodes.find((x) => x.title.toLowerCase().includes(ql));
    n ? flyTo(n) : toast('Not in the current view', 'err');
  };
  const findPath = async () => {
    const target = data?.nodes.find((x) => x.title.toLowerCase().includes(pathTo.toLowerCase()));
    if (!selected || !target) return toast('Select a node, then type a destination', 'err');
    const r = await api.get('/api/graph/path', { a: selected.id, b: target.id });
    if (!r.path.length) return toast('No path in the graph between those', 'err');
    const set = new Set(r.path);
    for (let i = 0; i < r.path.length - 1; i++) set.add(`${r.path[i]}→${r.path[i + 1]}`);
    data.links.forEach((l) => {
      const s = l.source.id || l.source, t = l.target.id || l.target;
      l.__pathKey = set.has(`${s}→${t}`) ? `${s}→${t}` : set.has(`${t}→${s}`) ? `${t}→${s}` : undefined;
    });
    hl.current.path = set;
    const fg = fgRef.current; fg && fg.nodeColor(fg.nodeColor());
    toast(r.titles.join('  →  '));
  };
  const exportLens = async () => {
    const name = `${(data.nodes.find((n) => n.id === root)?.title || 'lens')} ${new Date().toISOString().slice(0, 10)}`;
    try { const r = await api.post('/api/export', { root, depth, name }); toast(`Exported ${r.notes} notes → ${r.out}`); }
    catch (e) { toast(e.message, 'err'); }
  };

  const hubs = useMemo(() => (data?.nodes || []).filter((n) => !['tag', 'ghost'].includes(n.type)).sort((a, b) => b.pagerank - a.pagerank).slice(0, 7), [data]);
  const clusters = useMemo(() => {
    const m = {};
    (data?.nodes || []).forEach((n) => { if (n.community >= 0) (m[n.community] ||= []).push(n); });
    return Object.entries(m).sort((a, b) => b[1].length - a[1].length).slice(0, 6)
      .map(([c, ns]) => ({ c: +c, size: ns.length, lead: ns.sort((a, b) => b.pagerank - a.pagerank)[0] }));
  }, [data]);
  const presentTypes = useMemo(() => [...new Set((data?.nodes || []).map((n) => n.type))], [data]);

  return html`<div class="graphwrap" ref=${box}></div>
    <div class="gtool">
      <div class="gpanel col" style="gap:10px">
        <div class="row">
          <div class="seg"><button class=${mode === '2d' ? 'on' : ''} onClick=${() => setMode('2d')}>2D</button><button class=${mode === '3d' ? 'on' : ''} onClick=${() => setMode('3d')}>3D</button></div>
          <div class="seg"><button class=${colorBy === 'type' ? 'on' : ''} onClick=${() => setColorBy('type')}>Type</button><button class=${colorBy === 'community' ? 'on' : ''} onClick=${() => setColorBy('community')}>Clusters</button></div>
        </div>
        <div class="row" style="flex-wrap:nowrap"><input class="input" placeholder="Fly to node…" value=${q} onInput=${(e) => setQ(e.target.value)} onKeyDown=${(e) => e.key === 'Enter' && find()} /><button class="btn sm" onClick=${find}>Go</button></div>
      </div>
      ${root && html`<div class="gpanel"><h4>◎ Lens <span class="sp"></span><button class="btn ghost sm" onClick=${() => go('graph')}>exit</button></h4>
        <div style="margin-bottom:6px"><b>${data?.nodes.find((n) => n.id === root)?.title || root}</b> · ${depth} hop${depth > 1 ? 's' : ''}</div>
        <input type="range" min="1" max="4" value=${depth} onInput=${(e) => setDepth(+e.target.value)} />
        <button class="btn sm" style="margin-top:8px" onClick=${exportLens} title="Copy this subgraph into exports/ as a standalone Obsidian vault">⬡ Export as Obsidian vault</button></div>`}
      <div class="gpanel"><h4>Layers</h4><div class="chips">
        <span class=${'chip click ' + (tags ? 'on' : '')} onClick=${() => setTags(!tags)}>#tags</span>
        ${HIDEABLE.map((t) => html`<span class=${'chip click ' + (!hide.includes(t) ? 'on' : '')} onClick=${() => setHide(hide.includes(t) ? hide.filter((x) => x !== t) : [...hide, t])}>${t}</span>`)}
      </div></div>
      <div class="gpanel"><h4>Legend</h4><div class="legend">${colorBy === 'type'
        ? presentTypes.filter((t) => TYPE_COLORS[t]).map((t) => html`<span><i style=${{ background: typeColor(t) }}></i>${t}</span>`)
        : clusters.map((c) => html`<span><i style=${{ background: COMMUNITY[c.c % COMMUNITY.length] }}></i>${c.lead?.title}</span>`)}</div></div>
    </div>

    <div class="ginsight col" style="gap:10px">
      ${selected ? html`<div class="gpanel">
        <h4 style="color:${typeColor(selected.type)}">${selected.type}<span class="sp"></span><button class="btn ghost sm" onClick=${() => { hl.current.selected = null; hl.current.path = new Set(); setFocus(null); setSelected(null); }}>✕</button></h4>
        <div style="font-size:16px;font-weight:600;margin-bottom:6px">${selected.title}</div>
        <div class="row dim mono" style="font-size:11px;gap:12px"><span>degree ${selected.degree}</span><span>PR ${(selected.pagerank * 100).toFixed(2)}</span><span>cluster ${selected.community}</span></div>
        <div class="row" style="margin-top:10px">
          ${!['tag', 'ghost'].includes(selected.type) && html`<button class="btn primary sm" onClick=${() => openNote(selected.id)}>Open note</button>`}
          ${!['tag'].includes(selected.type) && html`<button class="btn sm" onClick=${() => go(`graph?root=${encodeURIComponent(selected.id)}&depth=2`)}>◎ Lens</button>`}
        </div>
        <div class="row" style="margin-top:10px;flex-wrap:nowrap"><input class="input" placeholder="Path to… (name)" value=${pathTo} onInput=${(e) => setPathTo(e.target.value)} onKeyDown=${(e) => e.key === 'Enter' && findPath()} /><button class="btn sm" onClick=${findPath}>⇝</button></div>
        <div class="section-title">Neighbours (${selected.nbrs?.size || 0})</div>
        <div class="chips">${[...(selected.nbrs || [])].slice(0, 30).map((id) => { const n = data.nodes.find((x) => x.id === id); return n && html`<span class="chip click" style=${{ color: typeColor(n.type) }} onClick=${() => flyTo(n)}>${n.title}</span>`; })}</div>
      </div>` : html`
      <div class="gpanel"><h4>⬢ Hubs (PageRank)</h4><div class="list">${hubs.map((n, i) => html`<div class="li click" style="padding:5px 4px" onClick=${() => flyTo(n)}>
        <span class="dim mono" style="width:14px">${i + 1}</span><i style=${{ width: 9, height: 9, borderRadius: '50%', background: typeColor(n.type), display: 'inline-block' }}></i><span class="sp">${n.title}</span><span class="dim mono">${n.degree}</span></div>`)}</div></div>
      <div class="gpanel"><h4>✦ Hive suggests links</h4>${suggest.length ? html`<div class="list">${suggest.map((s) => html`<div class="li" style="padding:5px 0;font-size:12px">
        <span class="sp">${s.a_title} <span class="dim">↔</span> ${s.b_title}</span>
        <button class="btn sm" onClick=${async () => { await api.post('/api/link', { a: s.a, b: s.b }); toast('Linked'); refreshAll(); }}>+</button></div>`)}</div>` : html`<div class="empty">No suggestions yet.</div>`}</div>`}
    </div>
    <div class="gstats">${data ? `${data.nodes.length} nodes · ${data.links.length} edges · ${mode.toUpperCase()}` : 'loading…'} · click a hexagon to focus · scroll to zoom</div>`;
}
