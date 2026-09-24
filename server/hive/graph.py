"""Property graph built from the markdown vault, plus graph algorithms.

Nodes:  every note (id = vault path), unresolved link targets ("ghost" nodes), and tags ("#tag").
Edges:  typed by where the link appears: frontmatter key (client, contact, ...), inline
        `field:: [[x]]`, or "mentions" for plain body links. Tags produce "tagged" edges.
"""
from __future__ import annotations

import math
import random
import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

from .vault import Note


SUGGESTABLE = {"client", "contact", "contract", "project", "note"}


@dataclass
class Edge:
    source: str
    target: str
    label: str


@dataclass
class Graph:
    notes: dict[str, Note] = field(default_factory=dict)
    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    resolve_map: dict[str, str] = field(default_factory=dict)
    adj: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))

    # ---------- construction ----------
    @classmethod
    def build(cls, notes: list[Note], include_tags: bool = True) -> "Graph":
        g = cls()
        for n in notes:
            g.notes[n.path] = n
            g.resolve_map.setdefault(n.title.lower(), n.path)
            for a in n.meta.get("aliases") or []:
                g.resolve_map.setdefault(str(a).lower(), n.path)
            g.nodes[n.path] = {
                "id": n.path, "title": str(n.meta.get("title") or n.title), "type": n.type,
                "tags": n.tags, "demo": bool(n.meta.get("demo")), "status": n.meta.get("status"),
            }
        # resolve by stem first; fall back to full relative path without .md
        for n in notes:
            g.resolve_map.setdefault(n.path[:-3].lower(), n.path)

        seen: set[tuple[str, str, str]] = set()
        for n in notes:
            for link in n.links:
                tgt = g.resolve(link.target)
                if tgt is None:
                    tgt = f"ghost:{link.target.lower()}"
                    g.nodes.setdefault(tgt, {"id": tgt, "title": link.target, "type": "ghost", "tags": [], "demo": False, "status": None})
                if tgt == n.path:
                    continue
                key = (n.path, tgt, link.label)
                if key in seen:
                    continue
                seen.add(key)
                g._add_edge(n.path, tgt, link.label)
            if include_tags:
                for t in n.tags:
                    tid = f"#{t}"
                    g.nodes.setdefault(tid, {"id": tid, "title": tid, "type": "tag", "tags": [], "demo": False, "status": None})
                    g._add_edge(n.path, tid, "tagged")
        return g

    def _add_edge(self, s: str, t: str, label: str) -> None:
        self.edges.append(Edge(s, t, label))
        self.adj[s].add(t)
        self.adj[t].add(s)

    def resolve(self, target: str) -> str | None:
        t = target.strip().lower()
        if t.endswith(".md"):
            t = t[:-3]
        return self.resolve_map.get(t) or self.resolve_map.get(t.rsplit("/", 1)[-1])

    # ---------- queries ----------
    def backlinks(self, node_id: str) -> list[dict[str, str]]:
        return [{"source": e.source, "label": e.label} for e in self.edges if e.target == node_id]

    def outlinks(self, node_id: str) -> list[dict[str, str]]:
        return [{"target": e.target, "label": e.label} for e in self.edges if e.source == node_id]

    def ego(self, root: str, depth: int = 2, skip_types: set[str] | None = None) -> set[str]:
        """Nodes within `depth` hops of root (undirected). Tag nodes are not traversed through."""
        skip_types = skip_types or {"tag"}
        seen = {root}
        frontier = deque([(root, 0)])
        while frontier:
            cur, d = frontier.popleft()
            if d >= depth:
                continue
            for nb in self.adj.get(cur, ()):
                if nb in seen:
                    continue
                seen.add(nb)
                if self.nodes.get(nb, {}).get("type") not in skip_types:
                    frontier.append((nb, d + 1))
        return seen

    def shortest_path(self, a: str, b: str) -> list[str]:
        if a not in self.nodes or b not in self.nodes:
            return []
        prev: dict[str, str | None] = {a: None}
        q = deque([a])
        while q:
            cur = q.popleft()
            if cur == b:
                path = []
                node: str | None = b
                while node is not None:
                    path.append(node)
                    node = prev[node]
                return path[::-1]
            for nb in sorted(self.adj.get(cur, ())):
                if nb not in prev:
                    prev[nb] = cur
                    q.append(nb)
        return []

    # ---------- algorithms ----------
    def pagerank(self, damping: float = 0.85, iters: int = 60, tol: float = 1e-9) -> dict[str, float]:
        """PageRank on the undirected projection (relationships in a CRM are mutual)."""
        nodes = list(self.nodes)
        n = len(nodes)
        if n == 0:
            return {}
        rank = {v: 1.0 / n for v in nodes}
        for _ in range(iters):
            dangling = sum(rank[v] for v in nodes if not self.adj.get(v))
            new = {}
            for v in nodes:
                s = sum(rank[u] / len(self.adj[u]) for u in self.adj.get(v, ()))
                new[v] = (1 - damping) / n + damping * (s + dangling / n)
            delta = sum(abs(new[v] - rank[v]) for v in nodes)
            rank = new
            if delta < tol:
                break
        return rank

    def communities(self, seed: int = 7, rounds: int = 30) -> dict[str, int]:
        """Label propagation over non-tag nodes. Deterministic for a given seed."""
        rng = random.Random(seed)
        nodes = sorted(v for v, d in self.nodes.items() if d["type"] != "tag")
        label = {v: i for i, v in enumerate(nodes)}
        for _ in range(rounds):
            order = nodes[:]
            rng.shuffle(order)
            changed = False
            for v in order:
                nbs = [u for u in self.adj.get(v, ()) if u in label]
                if not nbs:
                    continue
                counts: dict[int, int] = defaultdict(int)
                for u in nbs:
                    counts[label[u]] += 1
                best = max(counts.values())
                choice = min(lbl for lbl, c in counts.items() if c == best)
                if label[v] != choice:
                    label[v] = choice
                    changed = True
            if not changed:
                break
        # renumber by community size, largest = 0
        sizes: dict[int, int] = defaultdict(int)
        for lbl in label.values():
            sizes[lbl] += 1
        ranked = {lbl: i for i, (lbl, _) in enumerate(sorted(sizes.items(), key=lambda kv: (-kv[1], kv[0])))}
        return {v: ranked[lbl] for v, lbl in label.items()}

    def suggest_links(self, node_id: str | None = None, limit: int = 15) -> list[dict[str, Any]]:
        """Adamic-Adar: unlinked note pairs that share neighbours (tags count, weakly)."""
        def real(v: str) -> bool:
            return self.nodes[v]["type"] not in ("ghost",)

        def entity(v: str) -> bool:  # only suggest links between durable entities, not events/logs
            return self.nodes[v]["type"] in SUGGESTABLE

        candidates = [node_id] if node_id else [v for v in self.nodes if entity(v)]
        scores: dict[tuple[str, str], float] = {}
        for a in candidates:
            if a not in self.nodes:
                continue
            for mid in self.adj.get(a, ()):
                deg = len(self.adj[mid])
                if deg < 2 or not real(mid):
                    continue
                w = 1.0 / math.log(deg + 1)
                if self.nodes[mid]["type"] == "tag":
                    w *= 0.5
                for b in self.adj[mid]:
                    if b == a or b in self.adj[a] or not entity(b):
                        continue
                    key = (a, b) if node_id else tuple(sorted((a, b)))
                    scores[key] = scores.get(key, 0.0) + w
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])[:limit]
        return [{"a": a, "b": b, "score": round(s, 3)} for (a, b), s in ranked]

    def unlinked_mentions(self, node_id: str, limit: int = 20) -> list[str]:
        """Notes whose body mentions this note's title as plain text but never links it."""
        node = self.nodes.get(node_id)
        if not node or node["type"] in ("tag", "ghost") or len(node["title"]) < 4:
            return []
        pat = re.compile(rf"(?<!\[\[)\b{re.escape(node['title'])}\b", re.I)
        linked = self.adj.get(node_id, set())
        out = []
        for path, n in self.notes.items():
            if path == node_id or path in linked:
                continue
            if pat.search(n.body):
                out.append(path)
                if len(out) >= limit:
                    break
        return out

    # ---------- serialisation ----------
    def to_json(self, subset: set[str] | None = None) -> dict[str, Any]:
        pr = self.pagerank()
        comm = self.communities()
        keep = subset if subset is not None else set(self.nodes)
        nodes = []
        for v in keep:
            d = dict(self.nodes[v])
            d["degree"] = len(self.adj.get(v, ()))
            d["pagerank"] = round(pr.get(v, 0.0), 6)
            d["community"] = comm.get(v, -1)
            nodes.append(d)
        links = [{"source": e.source, "target": e.target, "label": e.label}
                 for e in self.edges if e.source in keep and e.target in keep]
        return {"nodes": nodes, "links": links}

    def stats(self) -> dict[str, Any]:
        by_type: dict[str, int] = defaultdict(int)
        for d in self.nodes.values():
            by_type[d["type"]] += 1
        by_label: dict[str, int] = defaultdict(int)
        for e in self.edges:
            by_label[e.label] += 1
        comm = self.communities()
        return {"nodes": len(self.nodes), "edges": len(self.edges), "by_type": dict(by_type),
                "by_label": dict(by_label), "communities": len(set(comm.values()))}
