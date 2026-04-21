"""Interactive belief-graph export — ``alxia export <dir> --format graph``.

Writes two self-contained artifacts into the output directory:

* ``graph.json`` — cytoscape-compatible node/edge bundle
* ``graph.html`` — zero-dependency canvas-based viewer with force layout,
  zoom, pan, click-to-inspect, topic filtering

No CDN, no external JS, no Python graph libraries — pure stdlib + a
bundled minimal renderer.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class GraphExportResult:
    """Summary of a graph export run."""

    nodes: int
    edges: int
    output_path: Path


def export_graph(
    output_dir: Path, conn: sqlite3.Connection, workspace: str,
) -> GraphExportResult:
    """Write graph.json + graph.html for the workspace."""
    output_dir.mkdir(parents=True, exist_ok=True)

    nodes, edges = _build_graph(conn, workspace)
    payload = {"nodes": nodes, "edges": edges, "workspace": workspace}

    (output_dir / "graph.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8",
    )
    (output_dir / "graph.html").write_text(
        _render_html(payload), encoding="utf-8",
    )
    return GraphExportResult(
        nodes=len(nodes), edges=len(edges), output_path=output_dir,
    )


def _build_graph(
    conn: sqlite3.Connection, workspace: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Collect beliefs + supersession + topic edges from SQLite."""
    belief_rows = conn.execute(
        """
        SELECT belief_id, statement, topic, source_kind,
               wiki_document_path, superseded_by_belief_id
          FROM wiki_beliefs
         WHERE workspace = ? AND superseded_at IS NULL
         LIMIT 500
        """,
        (workspace,),
    ).fetchall()

    nodes: list[dict[str, Any]] = []
    topic_set: set[str] = set()
    belief_ids: set[str] = set()
    for row in belief_rows:
        belief_ids.add(row["belief_id"])
        topic = row["topic"] or "general"
        topic_set.add(topic)
        nodes.append({
            "id": row["belief_id"],
            "label": (row["statement"] or "")[:80],
            "topic": topic,
            "source_kind": row["source_kind"] or "unknown",
            "kind": "belief",
            "wiki_path": row["wiki_document_path"],
        })

    for topic in sorted(topic_set):
        nodes.append({
            "id": f"topic:{topic}",
            "label": topic,
            "topic": topic,
            "source_kind": "topic",
            "kind": "topic",
        })

    edges: list[dict[str, Any]] = []
    for row in belief_rows:
        topic = row["topic"] or "general"
        edges.append({
            "source": row["belief_id"],
            "target": f"topic:{topic}",
            "relation": "in_topic",
        })

    # supersession edges (include even if target is now superseded itself)
    for row in conn.execute(
        """
        SELECT belief_id, superseded_by_belief_id
          FROM wiki_beliefs
         WHERE workspace = ? AND superseded_by_belief_id IS NOT NULL
         LIMIT 500
        """,
        (workspace,),
    ):
        if (row["belief_id"] in belief_ids
                and row["superseded_by_belief_id"] in belief_ids):
            edges.append({
                "source": row["superseded_by_belief_id"],
                "target": row["belief_id"],
                "relation": "supersedes",
            })

    return nodes, edges


def _render_html(payload: dict[str, Any]) -> str:
    """Return a self-contained HTML document embedding the graph data."""
    data_json = json.dumps(payload)
    return _HTML_TEMPLATE.replace("__GRAPH_DATA__", data_json)


_HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Alexandria — belief graph</title>
<style>
  html, body { margin: 0; height: 100%; background: #0d1117; color: #c9d1d9;
               font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
  #header { padding: 10px 16px; border-bottom: 1px solid #21262d; display: flex;
            align-items: center; gap: 16px; }
  #header h1 { margin: 0; font-size: 14px; font-weight: 600; letter-spacing: 0.02em; }
  #header .meta { color: #8b949e; font-size: 12px; }
  #header select { background: #161b22; color: #c9d1d9; border: 1px solid #30363d;
                   padding: 4px 8px; border-radius: 4px; font-size: 12px; }
  #canvas-wrap { position: absolute; top: 41px; left: 0; right: 0; bottom: 0; }
  canvas { display: block; width: 100%; height: 100%; cursor: grab; }
  canvas:active { cursor: grabbing; }
  #panel { position: absolute; top: 55px; right: 12px; width: 320px; max-height: 70vh;
           overflow-y: auto; background: rgba(22,27,34,0.95); border: 1px solid #30363d;
           border-radius: 6px; padding: 12px; font-size: 12px; display: none; }
  #panel h3 { margin: 0 0 8px; font-size: 13px; color: #58a6ff; }
  #panel .row { margin: 4px 0; color: #8b949e; }
  #panel .row span { color: #c9d1d9; }
  #legend { position: absolute; bottom: 12px; left: 12px;
            background: rgba(22,27,34,0.9); border: 1px solid #30363d;
            border-radius: 6px; padding: 8px 12px; font-size: 11px; }
  #legend .key { display: inline-flex; align-items: center; margin-right: 12px; }
  #legend .swatch { display: inline-block; width: 10px; height: 10px; border-radius: 50%;
                    margin-right: 4px; }
</style>
</head>
<body>
<div id="header">
  <h1>Alexandria belief graph</h1>
  <span class="meta" id="meta"></span>
  <label class="meta">Topic:
    <select id="topic-filter"><option value="">all</option></select>
  </label>
</div>
<div id="canvas-wrap"><canvas id="c"></canvas></div>
<div id="panel"></div>
<div id="legend"></div>
<script>
const GRAPH = __GRAPH_DATA__;
const kindColor = {
  paper: "#7ce38b", code: "#79c0ff", conversation: "#d2a8ff",
  web: "#ffa657", manual: "#ff7b72", unknown: "#6e7681",
  topic: "#f2cc60",
};
const legend = document.getElementById("legend");
for (const [k, v] of Object.entries(kindColor)) {
  const el = document.createElement("span"); el.className = "key";
  el.innerHTML = `<span class="swatch" style="background:${v}"></span>${k}`;
  legend.appendChild(el);
}
const topicSel = document.getElementById("topic-filter");
const topics = [...new Set(GRAPH.nodes.map(n => n.topic))].sort();
topics.forEach(t => {
  const o = document.createElement("option"); o.value = t; o.textContent = t;
  topicSel.appendChild(o);
});
document.getElementById("meta").textContent =
  `${GRAPH.nodes.length} nodes · ${GRAPH.edges.length} edges · workspace ${GRAPH.workspace}`;

const canvas = document.getElementById("c");
const ctx = canvas.getContext("2d");
function resize() {
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * dpr; canvas.height = rect.height * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}
window.addEventListener("resize", resize); resize();

// Initialize positions
const nodes = GRAPH.nodes.map((n, i) => ({
  ...n,
  x: Math.cos(i) * 200 + canvas.clientWidth / 2,
  y: Math.sin(i) * 200 + canvas.clientHeight / 2,
  vx: 0, vy: 0,
}));
const byId = Object.fromEntries(nodes.map(n => [n.id, n]));
const edges = GRAPH.edges.filter(e => byId[e.source] && byId[e.target]);

let selectedTopic = "";
topicSel.addEventListener("change", () => { selectedTopic = topicSel.value; });

// Simple force sim: repulsion + spring + gravity
function step() {
  const filter = n => !selectedTopic || n.topic === selectedTopic || n.kind === "topic";
  const active = nodes.filter(filter);
  for (const n of active) { n.fx = 0; n.fy = 0; }
  for (let i = 0; i < active.length; i++) {
    for (let j = i + 1; j < active.length; j++) {
      const a = active[i], b = active[j];
      const dx = b.x - a.x, dy = b.y - a.y;
      const d2 = dx*dx + dy*dy + 0.01;
      const f = 1200 / d2;
      a.fx -= dx * f; a.fy -= dy * f;
      b.fx += dx * f; b.fy += dy * f;
    }
  }
  for (const e of edges) {
    const a = byId[e.source], b = byId[e.target];
    if (!filter(a) || !filter(b)) continue;
    const dx = b.x - a.x, dy = b.y - a.y;
    const d = Math.sqrt(dx*dx + dy*dy) + 0.01;
    const f = (d - 80) * 0.02;
    a.fx += dx / d * f; a.fy += dy / d * f;
    b.fx -= dx / d * f; b.fy -= dy / d * f;
  }
  const cx = canvas.clientWidth / 2, cy = canvas.clientHeight / 2;
  for (const n of active) {
    n.fx += (cx - n.x) * 0.002; n.fy += (cy - n.y) * 0.002;
    n.vx = (n.vx + n.fx) * 0.85; n.vy = (n.vy + n.fy) * 0.85;
    n.x += n.vx; n.y += n.vy;
  }
}

let offsetX = 0, offsetY = 0, scale = 1;
let selected = null;

function draw() {
  ctx.clearRect(0, 0, canvas.clientWidth, canvas.clientHeight);
  ctx.save();
  ctx.translate(offsetX, offsetY);
  ctx.scale(scale, scale);

  const filter = n => !selectedTopic || n.topic === selectedTopic || n.kind === "topic";
  ctx.strokeStyle = "rgba(110,118,129,0.3)";
  ctx.lineWidth = 1;
  for (const e of edges) {
    const a = byId[e.source], b = byId[e.target];
    if (!filter(a) || !filter(b)) continue;
    ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y);
    if (e.relation === "supersedes") ctx.strokeStyle = "#ff7b72";
    else ctx.strokeStyle = "rgba(110,118,129,0.3)";
    ctx.stroke();
  }

  for (const n of nodes) {
    if (!filter(n)) continue;
    const r = n.kind === "topic" ? 10 : 5;
    ctx.fillStyle = kindColor[n.source_kind] || kindColor.unknown;
    ctx.beginPath(); ctx.arc(n.x, n.y, r, 0, 2 * Math.PI); ctx.fill();
    if (n === selected) {
      ctx.strokeStyle = "#58a6ff"; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(n.x, n.y, r + 3, 0, 2 * Math.PI); ctx.stroke();
    }
    if (n.kind === "topic") {
      ctx.fillStyle = "#c9d1d9"; ctx.font = "12px sans-serif";
      ctx.fillText(n.label, n.x + 12, n.y + 4);
    }
  }
  ctx.restore();
}

function loop() { step(); draw(); requestAnimationFrame(loop); } loop();

let dragging = false, dragStartX = 0, dragStartY = 0;
canvas.addEventListener("mousedown", e => {
  dragging = true; dragStartX = e.clientX - offsetX; dragStartY = e.clientY - offsetY;
});
canvas.addEventListener("mousemove", e => {
  if (dragging) { offsetX = e.clientX - dragStartX; offsetY = e.clientY - dragStartY; }
});
window.addEventListener("mouseup", () => { dragging = false; });
canvas.addEventListener("wheel", e => {
  e.preventDefault();
  const factor = e.deltaY < 0 ? 1.1 : 0.9;
  scale *= factor;
}, { passive: false });

canvas.addEventListener("click", e => {
  const rect = canvas.getBoundingClientRect();
  const mx = (e.clientX - rect.left - offsetX) / scale;
  const my = (e.clientY - rect.top - offsetY) / scale;
  let hit = null;
  for (const n of nodes) {
    const r = n.kind === "topic" ? 10 : 5;
    if (Math.hypot(n.x - mx, n.y - my) < r + 3) { hit = n; break; }
  }
  selected = hit;
  const panel = document.getElementById("panel");
  if (!hit) { panel.style.display = "none"; return; }
  panel.style.display = "block";
  panel.innerHTML = `
    <h3>${hit.kind === "topic" ? "Topic" : "Belief"}</h3>
    <div class="row">Label: <span>${hit.label}</span></div>
    <div class="row">Topic: <span>${hit.topic}</span></div>
    ${hit.source_kind !== "topic" ? `<div class="row">Source kind: <span>${hit.source_kind}</span></div>` : ""}
    ${hit.wiki_path ? `<div class="row">Wiki: <span>${hit.wiki_path}</span></div>` : ""}
  `;
});
</script>
</body></html>
"""
