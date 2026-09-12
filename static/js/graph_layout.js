// Pure presentation layout. No collection, ownership inference, or provider calls.
const compare = (a, b) => a < b ? -1 : a > b ? 1 : 0;
export const nodeKey = value => value.toLowerCase();
export const compact = value => value.length > 25 ? `${value.slice(0, 11)}…${value.slice(-9)}` : value;

export function layoutGraph(graph) {
  const unique = new Map();
  [...graph.nodes].sort((a,b) => compare(a.id, b.id)).forEach(node => {
    if (!unique.has(nodeKey(node.id))) unique.set(nodeKey(node.id), node);
  });
  const nodes = [...unique.values()].sort((a,b) => compare(nodeKey(a.id), nodeKey(b.id)));
  const neighbors = new Map(nodes.map(node => [nodeKey(node.id), new Set()]));
  for (const edge of graph.edges) {
    const a = nodeKey(edge.source), b = nodeKey(edge.target);
    if (neighbors.has(a) && neighbors.has(b)) { neighbors.get(a).add(b); neighbors.get(b).add(a); }
  }
  // Minimum undirected hop depth from returned focus nodes, solely for placement.
  const depths = new Map(nodes.filter(node => node.is_focus).map(node => [nodeKey(node.id), 0]));
  const queue = [...depths.keys()];
  for (let index = 0; index < queue.length; index++) {
    const key = queue[index];
    for (const next of [...neighbors.get(key)].sort(compare)) if (!depths.has(next)) {
      depths.set(next, depths.get(key) + 1); queue.push(next);
    }
  }
  const lastDepth = Math.max(0, ...depths.values());
  const layers = new Map();
  for (const node of nodes) {
    const key = nodeKey(node.id), depth = depths.get(key) ?? lastDepth + 1;
    if (!layers.has(depth)) layers.set(depth, []);
    layers.get(depth).push(node);
  }
  const positions = new Map(), layerInfo = [];
  let x = 0;
  for (const [depth, siblings] of [...layers].sort((a,b) => a[0] - b[0])) {
    // Stable parent ordering reduces crossings while keeping siblings stable.
    const order = node => {
      const parents = [...neighbors.get(nodeKey(node.id))].map(key => positions.get(key)).filter(Boolean);
      return parents.length ? parents.reduce((sum,p) => sum + p.y, 0) / parents.length : 0;
    };
    siblings.sort((a,b) => order(a) - order(b) || compare(nodeKey(a.id), nodeKey(b.id)));
    const width = Math.max(...siblings.map(node => Math.min(248, Math.max(208, (node.label || node.id).slice(0, 28).length * 7 + 28))));
    const rows = Math.min(12, siblings.length), columns = Math.ceil(siblings.length / rows);
    layerInfo.push({depth, x, width, disconnected:siblings.every(node => !depths.has(nodeKey(node.id)))});
    siblings.forEach((node,index) => positions.set(nodeKey(node.id), {x:x + Math.floor(index / rows) * (width + 90), y:(index % rows - (rows - 1) / 2) * 116,
      width, height:76, depth:depths.get(nodeKey(node.id)) ?? null}));
    x += columns * (width + 90) + 100;
  }
  const grouped = new Map();
  for (const edge of graph.edges) {
    const key = JSON.stringify([nodeKey(edge.source), nodeKey(edge.target)]);
    if (!grouped.has(key)) grouped.set(key, {key, source:edge.source, target:edge.target, records:[]});
    grouped.get(key).records.push(edge);
  }
  const connections = [...grouped.values()].sort((a,b) => compare(a.key,b.key));
  connections.forEach(group => group.records.sort((a,b) => compare(a.id || a.tx_hash, b.id || b.tx_hash)));
  const boxes = [...positions.values()];
  const bounds = boxes.length ? [Math.min(...boxes.map(p=>p.x))-70, Math.min(...boxes.map(p=>p.y))-110,
    Math.max(...boxes.map(p=>p.x+p.width))-Math.min(...boxes.map(p=>p.x))+140,
    Math.max(...boxes.map(p=>p.y+p.height))-Math.min(...boxes.map(p=>p.y))+220] : [0,0,900,560];
  return {nodes, positions, connections, layers:layerInfo, bounds};
}

export function connectionPath(from, to, clearanceY = null) {
  const y1 = from.y + from.height / 2, y2 = to.y + to.height / 2;
  if (from === to) return `M ${from.x+from.width-20} ${from.y} C ${from.x+from.width+25} ${from.y-32}, ${from.x-20} ${from.y-32}, ${from.x+20} ${from.y}`;
  if (from.x === to.x) {
    const down = y1 < y2, x = down ? from.x + from.width : from.x, bend = x + (down ? 40 : -40);
    return `M ${x} ${y1} C ${bend} ${y1}, ${bend} ${y2}, ${x} ${y2}`;
  }
  const forward = from.x < to.x;
  const x1 = forward ? from.x + from.width : from.x;
  const x2 = forward ? to.x : to.x + to.width;
  // Reverse links use a separate curved lane rather than perfectly overlapping.
  const shift = forward ? -10 : 10;
  if (clearanceY !== null && Math.abs(x2-x1) > 400) {
    const exit=x1+(forward?28:-28), entry=x2+(forward?-28:28);
    return `M ${x1} ${y1+shift} L ${exit} ${y1+shift} L ${exit} ${clearanceY} L ${entry} ${clearanceY} L ${entry} ${y2+shift} L ${x2} ${y2+shift}`;
  }
  const mid = (x1 + x2) / 2;
  return `M ${x1} ${y1+shift} C ${mid} ${y1+shift}, ${mid} ${y2+shift}, ${x2} ${y2+shift}`;
}
