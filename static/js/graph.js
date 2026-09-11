import {api} from "./api.js";
import {byId, panel, element, makeForm, chainAddress, table, shortValue, action, dateText, UserError} from "./ui.js";
import {investigate} from "./wallet.js";

const NS = "http://www.w3.org/2000/svg";
function svgNode(tag, attrs = {}, label) {
  const node = document.createElementNS(NS, tag);
  Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
  if (label != null) node.textContent = label;
  return node;
}
export function initGraph() {
  const host = byId("graph-workspace");
  const controls = panel("Graph", "Graph relationships are built from transactions currently stored by Greedy Collector. Hops 1–3 are traversal depth, not completeness guarantees. Counterparties are not recursively fetched automatically. Bitcoin relationships are simplified representations.");
  const output = panel("Stored relationships");
  const form = makeForm([...chainAddress(), {name:"hops", label:"Hops", options:["1", "2", "3"]}], "Load graph", async data => {
    output.replaceChildren(element("h2", "Stored relationships"));
    if (!data.address.trim()) throw new UserError("Enter a public wallet address.");
    const graph = await api(`/address/${data.chain}/${encodeURIComponent(data.address.trim())}/graph?hops=${data.hops}`);
    renderGraph(output, graph, data.chain);
  });
  controls.append(form); host.append(controls, output);
  output.append(element("p", "Choose a public address and load its stored relationships.", "empty"));
  document.addEventListener("wallet-selected", event => {
    form.elements.chain.value = event.detail.chain; form.elements.address.value = event.detail.address;
  });
}

function renderGraph(host, graph, chain) {
  host.replaceChildren(element("h2", "Stored relationships"));
  host.append(element("p", `Backend: ${graph.backend} · Requested hops: ${graph.requested_hops} · Available: ${graph.available_hops}`, "muted small"));
  host.append(element("p", graph.note, "muted small"));
  if (!graph.nodes.length && !graph.edges.length) { host.append(element("p", "No stored relationships are available for this address.", "empty")); return; }
  const tools = element("div", undefined, "toolbar");
  const svg = svgNode("svg", {viewBox:"0 0 900 560", role:"img", "aria-label":"Stored transaction relationships", class:"graph-canvas"});
  const defs = svgNode("defs");
  const arrow = svgNode("marker", {id:"graph-arrow", viewBox:"0 0 10 10", refX:10, refY:5, markerWidth:7, markerHeight:7, orient:"auto-start-reverse"});
  arrow.append(svgNode("path", {d:"M 0 0 L 10 5 L 0 10 z", fill:"#69889f"}));
  defs.append(arrow); svg.append(defs);
  const detail = element("div", undefined, "node-detail");
  detail.append(element("p", "Select a node to inspect its address. Drag to pan; use the buttons or mouse wheel to zoom.", "muted small"));
  const positions = new Map();
  graph.nodes.forEach((node, index) => {
    const angle = 2 * Math.PI * index / graph.nodes.length;
    positions.set(node.id.toLowerCase(), {x:450 + 320 * Math.cos(angle), y:280 + 210 * Math.sin(angle)});
  });
  for (const edge of graph.edges) {
    const from = positions.get(edge.source.toLowerCase()), to = positions.get(edge.target.toLowerCase());
    if (!from || !to) continue;
    const distance = Math.hypot(to.x - from.x, to.y - from.y);
    const inset = distance ? 16 / distance : 0;
    const attrs = {stroke:"#69889f", "stroke-width":1.5, "marker-end":"url(#graph-arrow)", fill:"none"};
    const line = distance
      ? svgNode("line", {...attrs, x1:from.x, y1:from.y, x2:to.x - (to.x - from.x) * inset, y2:to.y - (to.y - from.y) * inset})
      : svgNode("path", {...attrs, d:`M ${from.x - 8} ${from.y - 10} C ${from.x - 65} ${from.y - 75}, ${from.x + 65} ${from.y - 75}, ${from.x + 8} ${from.y - 14}`});
    line.append(svgNode("title", {}, `${edge.source} → ${edge.target}\n${edge.value_native} ${edge.token_symbol}\n${edge.tx_hash}\n${dateText(edge.timestamp)}`)); svg.append(line);
  }
  for (const node of graph.nodes) {
    const pos = positions.get(node.id.toLowerCase());
    const group = svgNode("g", {tabindex:"0", role:"button", "aria-label":`Select ${node.label || node.id}`, class:"graph-node"});
    group.append(svgNode("circle", {cx:pos.x, cy:pos.y, r:node.is_focus ? 13 : 8, fill:node.is_focus ? "#244969" : "#fff", stroke:"#244969", "stroke-width":2}));
    const label = node.label || node.id;
    group.append(svgNode("text", {x:pos.x, y:pos.y + 26, "text-anchor":"middle", "font-size":11}, label.length > 24 ? `${label.slice(0, 10)}…${label.slice(-8)}` : label));
    group.append(svgNode("title", {}, `${label}\n${node.id}`));
    const select = () => {
      detail.replaceChildren(element("h3", node.label || "Wallet"), element("p", node.id, "full-address"), element("p", `${node.chain || chain} · ${node.type || "Wallet"}${node.is_focus ? " · Focus wallet" : ""}`));
      detail.append(action("Investigate wallet", () => investigate(node.chain || chain, node.id)));
    };
    group.addEventListener("click", select);
    group.addEventListener("keydown", event => { if (["Enter", " "].includes(event.key)) { event.preventDefault(); select(); } });
    svg.append(group);
  }
  let view = [0, 0, 900, 560];
  const setView = () => svg.setAttribute("viewBox", view.join(" "));
  const zoom = factor => {
    const width = Math.max(150, Math.min(3600, view[2] * factor));
    const height = width * 560 / 900;
    view = [view[0] + (view[2] - width) / 2, view[1] + (view[3] - height) / 2, width, height]; setView();
  };
  tools.append(action("Zoom in", () => zoom(.8)), action("Zoom out", () => zoom(1.25)), action("Reset view", () => {view = [0, 0, 900, 560]; setView();}));
  svg.addEventListener("wheel", event => {event.preventDefault(); zoom(event.deltaY > 0 ? 1.1 : .9);}, {passive:false});
  let drag;
  svg.addEventListener("pointerdown", event => {if (event.target.closest(".graph-node")) return; drag = [event.clientX, event.clientY, ...view]; svg.setPointerCapture(event.pointerId);});
  svg.addEventListener("pointermove", event => {if (!drag) return; const box = svg.getBoundingClientRect(); view[0] = drag[2] - (event.clientX - drag[0]) * view[2] / box.width; view[1] = drag[3] - (event.clientY - drag[1]) * view[3] / box.height; setView();});
  ["pointerup", "pointercancel", "lostpointercapture"].forEach(type => svg.addEventListener(type, () => {drag = null;}));
  host.append(tools, svg, detail, table(["From", "To", "Transaction", "Amount", "Asset", "Timestamp"], graph.edges.map(edge => [shortValue(edge.source), shortValue(edge.target), shortValue(edge.tx_hash), edge.value_native, edge.token_symbol, dateText(edge.timestamp)])));
}
