import {addToCaseButton} from "./case_actions.js";
import {readLabels, labelsFor, labelCards} from "./label_ui.js";
import {api} from "./api.js";
import {byId, panel, element, makeForm, chainAddress, table, shortValue, action, dateText, UserError} from "./ui.js";
import {investigate} from "./wallet.js";
import {layoutGraph, connectionPath, nodeKey, compact} from "./graph_layout.js";

const NS = "http://www.w3.org/2000/svg";
function svgNode(tag, attrs = {}, label) {
  const node = document.createElementNS(NS, tag);
  Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
  if (label != null) node.textContent = label;
  return node;
}
export function initGraph() {
  const host = byId("graph-workspace");
  const controls = panel("Graph", "This graph represents relationships currently stored by Greedy Collector. Hop depth does not imply complete blockchain coverage.");
  controls.append(element("p", "Counterparties are not recursively fetched. Bitcoin relationships use representative endpoints; arrows do not imply ownership or wrongdoing.", "muted small"));
  const output = panel("Stored relationships");
  const form = makeForm([...chainAddress(), {name:"hops", label:"Hops", options:["1", "2", "3"]}], "Load graph", async data => {
    output.replaceChildren(element("h2", "Stored relationships"));
    if (!data.address.trim()) throw new UserError("Enter a public wallet address.");
    const graph = await api(`/address/${data.chain}/${encodeURIComponent(data.address.trim())}/graph?hops=${data.hops}`);
    const labels = await readLabels();
    renderGraph(output, graph, data.chain, labels);
  });
  controls.append(form); host.append(controls, output);
  output.append(element("p", "Search a wallet, then load its stored relationships here.", "empty"));
  document.addEventListener("wallet-selected", event => {
    form.elements.chain.value = event.detail.chain; form.elements.address.value = event.detail.address;
  });
}

export function renderGraph(host, graph, chain, labels = null) {
  host.replaceChildren(element("h2", "Stored relationships"));
  host.append(element("p", `Requested hops: ${graph.requested_hops} · Available: ${graph.available_hops} · ${graph.nodes.length} returned entities · ${graph.edges.length} transaction records`, "muted small"));
  if (!graph.nodes.length && !graph.edges.length) { host.append(element("p", "No stored relationships are available for this address.", "empty")); return; }
  const layout = layoutGraph(graph);
  const tools = element("div", undefined, "toolbar");
  const svg = svgNode("svg", {role:"group", "aria-label":"Stored transaction relationships", class:"graph-canvas", tabindex:"0"});
  const defs = svgNode("defs");
  const marker = svgNode("marker", {id:"graph-arrow", viewBox:"0 0 10 10", refX:10, refY:5, markerWidth:8, markerHeight:8, orient:"auto"});
  marker.append(svgNode("path", {d:"M 0 0 L 10 5 L 0 10 z", fill:"#607b90"})); defs.append(marker); svg.append(defs);
  const detail = element("div", undefined, "node-detail"); detail.id = "graph-detail";
  const clear = () => {
    svg.querySelectorAll(".selected").forEach(node => {node.classList.remove("selected"); node.setAttribute("aria-pressed", "false");});
    detail.replaceChildren(element("p", "Select an entity or connection to inspect it. Drag empty space to pan. Focus entities are blue; selection has an amber outline.", "muted small"));
  };
  const selectable = (node, select) => {
    node.setAttribute("tabindex", "0"); node.setAttribute("role", "button"); node.setAttribute("aria-pressed", "false");
    const activate = () => {clear(); node.classList.add("selected"); node.setAttribute("aria-pressed", "true"); select();};
    node.addEventListener("click", activate);
    node.addEventListener("keydown", event => {if (["Enter", " "].includes(event.key)) {event.preventDefault(); activate();}});
  };
  const edgeTable = edges => table(["Transaction", "Source →", "Target", "Amount", "Asset", "Timestamp (UTC)"], edges.map(edge =>
    [shortValue(edge.tx_hash), shortValue(edge.source), shortValue(edge.target), edge.value_native, edge.token_symbol, dateText(edge.timestamp)]));
  for (const layer of layout.layers) {
    svg.append(svgNode("text", {x:layer.x, y:layout.bounds[1]+50, class:"graph-layer"}, layer.disconnected ? "Other returned entities" : layer.depth === 0 ? "FOCUS" : `HOP ${layer.depth}`));
  }
  for (const group of layout.connections) {
    const from = layout.positions.get(nodeKey(group.source)), to = layout.positions.get(nodeKey(group.target));
    if (!from || !to) continue; // Unpositionable edges remain in the complete records table.
    const node = svgNode("g", {class:"graph-edge", "data-edge-key":group.key, "aria-label":`${group.source} to ${group.target}: ${group.records.length} records`});
    const path = connectionPath(from, to, layout.bounds[1]+20);
    node.append(svgNode("path", {d:path, class:"edge-hit"}), svgNode("path", {d:path, class:"edge-line", "marker-end":"url(#graph-arrow)"}));
    node.append(svgNode("title", {}, `${group.source} → ${group.target}\n${group.records.length} transaction records. Select to inspect.`));
    selectable(node, () => {
      detail.replaceChildren(element("h3", "Directional relationship"), element("p", `${group.source} → ${group.target}`, "full-address"),
        element("p", `${group.records.length} underlying transaction records. Amounts are listed individually; no mixed-asset totals are calculated.`), edgeTable(group.records));
    });
    svg.append(node);
  }
  for (const node of layout.nodes) {
    const position = layout.positions.get(nodeKey(node.id));
    const annotations = labelsFor(labels || [], node.chain || chain, node.id);
    const displayLabel = annotations[0]?.label || (labels === null ? node.label : node.id);
    const named = displayLabel && displayLabel !== node.id;
    const group = svgNode("g", {class:`graph-node${node.is_focus ? " is-focus" : ""}`, "data-node-id":node.id,
      "data-depth":position.depth ?? "unconnected", transform:`translate(${position.x} ${position.y})`, "aria-label":`Select ${node.label || node.id}`});
    group.append(svgNode("rect", {width:position.width, height:position.height, rx:9}));
    group.append(svgNode("text", {x:13,y:23,class:"entity-name"}, named ? displayLabel.length > 28 ? displayLabel.slice(0,25)+"…" : displayLabel : compact(node.id)));
    group.append(svgNode("text", {x:13,y:43,class:"entity-address"}, named ? compact(node.id) : "Wallet entity"));
    group.append(svgNode("text", {x:13,y:63,class:"entity-chain"}, `${node.chain || chain}${annotations[0] ? " · " + annotations[0].type : ""}${node.is_focus ? " · FOCUS" : ""}`));
    group.append(svgNode("title", {}, `${displayLabel || node.id}\n${node.id}\n${node.chain || chain}`));
    selectable(group, () => {
      const count = graph.edges.filter(edge => nodeKey(edge.source) === nodeKey(node.id) || nodeKey(edge.target) === nodeKey(node.id)).length;
      detail.replaceChildren(element("h3", named ? displayLabel : "Wallet entity"), element("p", node.id, "full-address"),
        element("p", `${node.chain || chain} · ${node.is_focus ? "Focus entity" : "Related entity"} · ${count} stored transaction relationships`),
        action("Investigate wallet", () => investigate(node.chain || chain, node.id)),
        addToCaseButton("wallet", node.chain || chain, node.id), labelCards(annotations));
    });
    svg.append(group);
  }
  const ratio = 900 / 560;
  function fit() {
    const [x,y,w,h] = layout.bounds, width = Math.max(w,h*ratio), height=width/ratio;
    return [x+(w-width)/2,y+(h-height)/2,width,height];
  }
  const focus = layout.positions.get(nodeKey(layout.nodes.find(node => node.is_focus)?.id || layout.nodes[0]?.id || ""));
  const centered = () => focus ? [focus.x+focus.width/2-450,focus.y+focus.height/2-280,900,560] : fit();
  const initial = layout.nodes.length > 40 ? centered() : fit();
  let view = [...initial];
  const setView = () => svg.setAttribute("viewBox", view.join(" "));
  const zoom = factor => {
    const width=Math.max(300,Math.min(Math.max(...fit().slice(2))*2,view[2]*factor)),height=width/ratio;
    view=[view[0]+(view[2]-width)/2,view[1]+(view[3]-height)/2,width,height]; setView();
  };
  tools.append(action("Fit to graph",()=>{view=fit();setView();}), action("Center on focus",()=>{view=centered();setView();}),
    action("Reset view",()=>{view=[...initial];setView();clear();}), action("Zoom in",()=>zoom(.8)), action("Zoom out",()=>zoom(1.25)));
  svg.addEventListener("wheel",event=>{event.preventDefault();zoom(event.deltaY>0?1.1:.9);},{passive:false});
  let drag;
  svg.addEventListener("pointerdown",event=>{if(event.target.closest(".graph-node,.graph-edge"))return;drag=[event.clientX,event.clientY,...view];svg.setPointerCapture(event.pointerId);});
  svg.addEventListener("pointermove",event=>{if(!drag)return;const scale=Math.min(svg.clientWidth/view[2],svg.clientHeight/view[3]);view[0]=drag[2]-(event.clientX-drag[0])/scale;view[1]=drag[3]-(event.clientY-drag[1])/scale;setView();});
  ["pointerup","pointercancel","lostpointercapture"].forEach(type=>svg.addEventListener(type,()=>{drag=null;}));
  svg.addEventListener("keydown",event=>{if(event.key==="Escape")clear();});
  const records = element("details"); records.append(element("summary", `All returned transaction records (${graph.edges.length})`));
  records.addEventListener("toggle",()=>{if(records.open&&!records.querySelector("table"))records.append(edgeTable(graph.edges));});
  host.append(tools,svg,detail,records); setView(); clear();
}
