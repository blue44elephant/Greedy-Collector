import {element,details,table,action} from './ui.js';
import {graphInteraction,positionBounds} from './graph_interaction.js';
import {filteredGraph,nexusLayout,nexusPath} from './narcotics_presenter.js';
const svgElement=(tag,attrs={},text)=>{const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,v);if(text!=null)n.textContent=text;return n;};
const short=s=>s.length>28?s.slice(0,25)+'...':s;
export function nexusGraph(host,snapshot,filter={}) {
  const graph=filteredGraph(snapshot,filter),layout=nexusLayout(graph);
  host.replaceChildren(element('p',`Showing ${graph.nodes.length} nodes / ${graph.edges.length} edges. Saved run: ${snapshot.nodes.length} nodes / ${snapshot.edges.length} edges; available before bounds: ${snapshot.bounds.available_nodes} / ${snapshot.bounds.available_edges}.${snapshot.bounds.truncated?' BOUNDS TRUNCATED this analysis.':''}`,'bounded-note'));
  const tools=element('div',undefined,'toolbar'),inspector=element('section',undefined,'narcotics-inspector');inspector.id='narcotics-graph-detail';inspector.setAttribute('aria-live','polite');
  const svg=svgElement('svg',{class:'narcotics-canvas',role:'group','aria-label':'Narcotics Nexus typed graph',tabindex:0});
  const defs=svgElement('defs'),marker=svgElement('marker',{id:'narcotics-arrow',viewBox:'0 0 10 10',refX:10,refY:5,markerWidth:7,markerHeight:7,orient:'auto'});
  marker.append(svgElement('path',{d:'M 0 0 L 10 5 L 0 10 z',fill:'context-stroke'}));defs.append(marker);svg.append(defs);
  const edgeGroups=new Map();let view=null;
  function setView(){svg.setAttribute('viewBox',(view||layout.bounds).join(' '));}
  const interaction=graphInteraction({svg,tools,layout,context:['narcotics',snapshot.graph_fingerprint],redraw:()=>{
    for(const [id,{group,edge,offset}] of edgeGroups)for(const path of group.querySelectorAll('path'))path.setAttribute('d',nexusPath(edge,layout,offset));
    if(!view){layout.bounds=positionBounds(layout.positions);setView();}
  }});
  function select(item,isEdge=false){
    svg.querySelectorAll('[data-id]').forEach(n=>{const yes=n.dataset.id===item.id;n.classList.toggle('selected',yes);n.setAttribute('aria-pressed',String(yes));});
    inspector.replaceChildren(element('h3',isEdge?'Relationship detail':item.type.replaceAll('_',' ')+' detail'),details('Full stored record and provenance',item));
    if(isEdge)inspector.append(table(['Type','Source','Target','Strength','Review'],[[item.type,item.source,item.target,item.strength||'Context',item.review_status||'Not reviewed']]));
    else {
      inspector.append(element('p',item.label,'full-address'),element('p','Selected Cases: '+item.case_ids.join(', ')));
      if(item.type==='case')inspector.append(action('Open Case',()=>document.dispatchEvent(new CustomEvent('open-case',{detail:{id:item.metadata.case_id}}))));
      if(item.type==='wallet')inspector.append(action('Investigate wallet',()=>document.dispatchEvent(new CustomEvent('investigate-wallet',{detail:{chain:item.metadata.chain,address:item.metadata.address}}))));
    }
  }
  const bind=(g,item,edge=false)=>{g.dataset.id=item.id;g.tabIndex=0;g.setAttribute('role','button');g.setAttribute('aria-pressed','false');g.addEventListener('click',()=>select(item,edge));g.addEventListener('keydown',e=>{if(['Enter',' '].includes(e.key)){e.preventDefault();select(item,edge);}});};
  const parallel=new Map();
  for(const edge of graph.edges){const key=[edge.source,edge.target].sort().join(':');if(!parallel.has(key))parallel.set(key,[]);parallel.get(key).push(edge.id);}
  for(const edge of graph.edges){const family=parallel.get([edge.source,edge.target].sort().join(':')),offset=(family.indexOf(edge.id)-(family.length-1)/2)*18;
    const group=svgElement('g',{class:'narcotics-edge','aria-label':edge.type});
    group.append(svgElement('path',{d:nexusPath(edge,layout,offset),'marker-end':'url(#narcotics-arrow)'}),svgElement('path',{d:nexusPath(edge,layout,offset),class:'hit'}),svgElement('title',{},edge.type));
    bind(group,edge,true);edgeGroups.set(edge.id,{group,edge,offset});svg.append(group);
  }
  for(const node of graph.nodes){const p=layout.positions.get(node.id),g=svgElement('g',{class:'narcotics-node '+node.type,transform:`translate(${p.x} ${p.y})`,'aria-label':node.type+': '+node.label});
    g.append(svgElement('rect',{width:230,height:78,rx:8}),svgElement('title',{},node.label),svgElement('text',{x:12,y:20,class:'kind'},node.type.replaceAll('_',' ')),
      svgElement('text',{x:12,y:42},short(node.label)),svgElement('text',{x:12,y:64,class:'kind'},`${node.case_ids.length} selected Cases`));bind(g,node);svg.append(g);interaction.bind(g,node.id);
  }
  interaction.update();view=[...layout.bounds];setView();
  const fit=()=>{view=[...layout.bounds];setView();};
  tools.append(action('Fit to graph',fit),action('Reset view',fit));
  for(const [label,factor] of [['Zoom in',.8],['Zoom out',1.25]])tools.append(action(label,()=>{view=[view[0]+view[2]*(1-factor)/2,view[1]+view[3]*(1-factor)/2,view[2]*factor,view[3]*factor];setView();}));
  let pan=null;
  svg.addEventListener('pointerdown',e=>{if(e.target.closest('.narcotics-node,.narcotics-edge'))return;pan={x:e.clientX,y:e.clientY,view:[...view]};svg.setPointerCapture(e.pointerId);});
  svg.addEventListener('pointermove',e=>{if(!pan)return;const scale=Math.min(svg.clientWidth/pan.view[2],svg.clientHeight/pan.view[3]);view=[pan.view[0]-(e.clientX-pan.x)/scale,pan.view[1]-(e.clientY-pan.y)/scale,pan.view[2],pan.view[3]];setView();});
  for(const event of ['pointerup','pointercancel','lostpointercapture'])svg.addEventListener(event,()=>{pan=null;});
  svg.addEventListener('keydown',e=>{if(e.key==='Escape'){inspector.replaceChildren();svg.querySelectorAll('.selected').forEach(n=>n.classList.remove('selected'));}});
  host.append(tools,element('p','Drag/pin nodes or pan empty space. Manual layout is presentation only; it never changes evidence. Select a node or arrow to inspect its full record.','muted small'),svg,inspector);
  if(!graph.nodes.length)host.append(element('p','No nodes match the current presentation filters. The saved graph remains available.','empty'));
  host.append(details('All saved nodes and relationships (including filtered records)',snapshot));
  return {layout,interaction,fit};
}
