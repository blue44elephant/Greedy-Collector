// Namespaced Discovery IDs only. No wallet folding, inference or physics.
export const CARD = {width:310,height:146};
export function discoveryLayout(graph) {
  const positions=new Map([[graph.root.id,{x:0,y:0}]]);
  for(const type of ['code_location','label_annotation']) {
    const nodes=graph.items.filter(n=>n.type===type).sort((a,b)=>a.id<b.id?-1:a.id>b.id?1:0);
    const rows=Math.max(1,Math.ceil(Math.sqrt(nodes.length*2)));
    nodes.forEach((n,i)=>positions.set(n.id,{x:(type==='code_location'?-1:1)*(520+Math.floor(i/rows)*410),y:(i%rows-(rows-1)/2)*190}));
  }
  const points=[...positions.values()],xs=points.map(p=>p.x),ys=points.map(p=>p.y);
  return {positions,bounds:[Math.min(...xs)-200,Math.min(...ys)-120,Math.max(...xs)-Math.min(...xs)+400,Math.max(...ys)-Math.min(...ys)+240]};
}
export function discoveryPath(edge,layout) {
  const a=layout.positions.get(edge.source),b=layout.positions.get(edge.target);
  const sign=b.x>=a.x?1:-1,x1=a.x+sign*CARD.width/2,x2=b.x-sign*CARD.width/2;
  const bend=(x1+x2)/2;
  return `M ${x1} ${a.y} C ${bend} ${a.y}, ${bend} ${b.y}, ${x2} ${b.y}`;
}
export function zoomView(view,factor) {
  const width=Math.max(300,Math.min(15000,view[2]*factor)),ratio=width/view[2];
  return [view[0]+(view[2]-width)/2,view[1]+(view[3]-view[3]*ratio)/2,width,view[3]*ratio];
}
