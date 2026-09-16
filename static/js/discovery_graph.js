import {element,table,dateText,run,UserError} from './ui.js';
import {discoveryRequest as request} from './discovery_api.js';
import {discoveryLayout,discoveryPath,zoomView,CARD} from './discovery_graph_layout.js';

const kinds={wallet:'Wallet',label_annotation:'Label annotation',code_location:'Code location'};
const short=(value,n=36)=>String(value??'Not available').length>n?String(value).slice(0,n-1)+'…':String(value??'Not available');
const review=node=>node.current_review_required?`Review required · previous ${node.current_review_status}`:node.current_review_status;
function svgNode(tag,attrs={},text) {
  const node=document.createElementNS('http://www.w3.org/2000/svg',tag);
  for(const [key,value] of Object.entries(attrs))node.setAttribute(key,value);
  if(text!==undefined)node.textContent=text;return node;
}
export function initDiscoveryGraph(host,{openResult}) {
  let active=false,runId=null,offset=0,generation=0,controller=null;
  const states=new Map();let state=null;
  function button(label,fn) {const b=element('button',label,'secondary');b.type='button';b.addEventListener('click',()=>run(host,fn));return b;}
  async function load() {
    if(!active)return;
    if(!runId){host.replaceChildren(element('p','Select a stored run to view its Discovery graph.','empty'));return;}
    const token=++generation;controller?.abort();controller=new AbortController();
    let graph;
    try{graph=await request(`/runs/${encodeURIComponent(runId)}/graph?limit=100&offset=${offset}`,{signal:controller.signal});}
    catch(e){if(e.name==='AbortError')return;throw e;}
    if(token!==generation||!active)return;
    const key=runId+':'+offset;
    state=states.get(key)||{view:null,selected:null};states.delete(key);states.set(key,state);
    if(states.size>8)states.delete(states.keys().next().value);
    render(graph);
  }
  function render(graph) {
    host.replaceChildren(element('h2','Discovery graph'),element('p','Public-source relationships, not blockchain transactions or Attribution. Graph proximity does not imply common ownership.','bounded-note'),
      element('p',`Run: ${graph.run_id}`,'small full-address'),
      element('p',`Showing ${graph.items.length} of ${graph.total} Discovery results${graph.offset?` · offset ${graph.offset}`:''}.`,'discovery-graph-count'),
      element('p','Node material belongs to this run. Review, total observation counts and promotion counts are current analytic status across runs.','muted small'));
    if(!graph.promotion_available)host.append(element('p','Promotion metadata is unavailable; the stored Discovery graph remains usable.','bounded-note'));
    const tools=element('div',undefined,'toolbar');host.append(tools);
    if(graph.offset>0)tools.append(button('Previous graph page',async()=>{offset=Math.max(0,offset-100);await load();}));
    if(graph.next_offset!==null)tools.append(button('Next graph page',async()=>{offset=graph.next_offset;await load();}));
    const layout=discoveryLayout(graph),svg=svgNode('svg',{class:'discovery-graph-canvas',role:'group','aria-label':'Typed Discovery relationships',tabindex:0});
    const defs=svgNode('defs'),marker=svgNode('marker',{id:'discovery-arrow',viewBox:'0 0 10 10',refX:10,refY:5,markerWidth:8,markerHeight:8,orient:'auto'});
    marker.append(svgNode('path',{d:'M 0 0 L 10 5 L 0 10 z',fill:'context-stroke'}));defs.append(marker);svg.append(defs);
    const inspector=element('section',undefined,'discovery-graph-detail');inspector.id='discovery-graph-detail';inspector.setAttribute('aria-live','polite');
    const views=()=>{if(!state.view)state.view=[...layout.bounds];svg.setAttribute('viewBox',state.view.join(' '));};
    const select=(id,edge=false)=>{
      state.selected={id,edge};svg.querySelectorAll('[aria-pressed]').forEach(n=>{const selected=n.dataset.id===id&&n.dataset.edge===String(edge);n.classList.toggle('selected',selected);n.setAttribute('aria-pressed',String(selected));});
      const node=id===graph.root.id?graph.root:graph.items.find(n=>edge?n.result_id===id:n.id===id);
      if(!node)return;
      inspector.replaceChildren(element('h3',edge?'Relationship detail':kinds[node.type]));
      if(node.type==='wallet') {
        inspector.append(table(['Field','Value'],[['Chain',node.chain],['Full wallet',node.address]]),button('Copy wallet address',async()=>{try{await navigator.clipboard.writeText(node.address);}catch{throw new UserError('Copy the full wallet address from the detail table.');}}),
          button('Open blockchain graph',()=>document.dispatchEvent(new CustomEvent('open-discovery-blockchain-graph',{detail:{chain:node.chain,address:node.address}}))),element('p','Opens the separate blockchain workspace with this wallet prefilled. Load graph there to read stored transfer relationships.','muted small'));return;
      }
      inspector.append(element('p',node.predicate==='repository_contains'?'The wallet identifier was observed in this public code location. Code mention does not establish repository owner control of the wallet.':'This wallet had the displayed stored Label annotation. This is secondary annotation metadata.'),
        table(['Field','Value'],[['Predicate',node.predicate],['Result',node.result_id],['Selected run observation',node.observation_id],['Source / transform',`${node.source_id} / ${node.transform_id}`],
          ...(node.type==='label_annotation'?[['Label',node.title],['Label type',node.label_type],['Original source',node.annotation_source],['Annotation confidence (metadata)',node.confidence]]:[['Repository',node.repository],['File',node.path],['Blob SHA',node.blob_sha]]),
          ['Current review',review(node)],['Observations in this run',node.run_observation_count],['Observations across runs (current)',node.current_observation_count],['First included retrieval (original)',dateText(node.first_retrieved_at)],['Last included retrieval (original)',dateText(node.last_retrieved_at)],['Promoted (current)',node.promotion_count??'Unavailable']]),
        element('p',node.summary),...(node.excerpt?[element('blockquote',node.excerpt)]:[]),
        button('Open result',()=>openResult(node.result_id,node.observation_id)),button('View observations',()=>openResult(node.result_id,node.observation_id)),
        element('p','Review and promotion use the existing result inspector and its selected-observation checks.','muted small'));
      if(node.url) {
        try {const url=new URL(node.url);if(['https:','http:'].includes(url.protocol)&&!url.username&&!url.password){const a=element('a','Open source');a.href=url.href;a.target='_blank';a.rel='noopener noreferrer';a.referrerPolicy='no-referrer';inspector.append(a);}}catch{}
      }
      if(node.promotion_count>0) {
        const links=element('div');inspector.append(button('Open attribution',()=>promotions(0)),links);
        const selected=state.selected;
        async function promotions(page) {
          const value=await request(`/results/${encodeURIComponent(node.result_id)}/promotions?limit=10&offset=${page}`);
          if(state.selected!==selected||!links.isConnected)return;
          links.replaceChildren(element('p',`Current promotion history: ${value.total}`),table(['Claim','Stance','Link',''],value.items.map(p=>[p.claim_id,p.stance,p.withdrawn_at?'Withdrawn':'Active',button('Open claim',()=>document.dispatchEvent(new CustomEvent('open-attribution',{detail:{action:'open_claim',id:p.claim_id}})))])));
          if(page>0)links.append(button('Previous promotions',()=>promotions(Math.max(0,page-10))));
          if(value.next_offset!==null)links.append(button('Next promotions',()=>promotions(value.next_offset)));
        }
      }
    };
    function selectable(node,id,edge) {
      node.dataset.id=id;node.dataset.edge=String(edge);node.setAttribute('role','button');node.setAttribute('tabindex','0');node.setAttribute('aria-pressed','false');
      node.addEventListener('click',()=>select(id,edge));node.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();select(id,edge);}});
    }
    for(const edge of graph.edges) {
      const g=svgNode('g',{class:'discovery-graph-edge','aria-label':edge.predicate});
      g.append(svgNode('path',{d:discoveryPath(edge,layout),'marker-end':'url(#discovery-arrow)'}),svgNode('path',{d:discoveryPath(edge,layout),class:'hit'}),svgNode('title',{},edge.predicate));
      if(graph.items.length<=8){const a=layout.positions.get(edge.source),b=layout.positions.get(edge.target);g.append(svgNode('text',{x:(a.x+b.x)/2,y:(a.y+b.y)/2-8,class:'predicate','text-anchor':'middle'},edge.predicate));}
      selectable(g,edge.id,true);svg.append(g);
    }
    for(const node of [graph.root,...graph.items]) {
      const p=layout.positions.get(node.id),g=svgNode('g',{class:`discovery-graph-node ${node.type}`,transform:`translate(${p.x},${p.y})`,'aria-label':`${kinds[node.type]}: ${node.title||node.address}`});
      g.append(svgNode('rect',{x:-CARD.width/2,y:-CARD.height/2,width:CARD.width,height:CARD.height,rx:node.type==='wallet'?28:node.type==='code_location'?3:10}),
        svgNode('title',{},node.title||node.address),svgNode('text',{x:-138,y:-47,class:'kind'},kinds[node.type]),
        svgNode('text',{x:-138,y:-22},short(node.title||node.address)),svgNode('text',{x:-138,y:0},short(node.subtitle||node.chain)),
        svgNode('text',{x:-138,y:24,class:'status'},node.type==='wallet'?'Focus wallet':short(review(node),42)),
        svgNode('text',{x:-138,y:48,class:'status'},node.type==='wallet'?'Public identifier':`Observations: ${node.run_observation_count} · Promoted: ${node.promotion_count??'unavailable'}`));
      selectable(g,node.id,false);svg.append(g);
    }
    tools.append(button('Fit to graph',()=>{state.view=[...layout.bounds];views();}),button('Zoom in',()=>{state.view=zoomView(state.view,.8);views();}),button('Zoom out',()=>{state.view=zoomView(state.view,1.25);views();}),button('Reset view',()=>{state.view=[...layout.bounds];views();select(graph.root.id);}));
    let drag=null;
    svg.addEventListener('pointerdown',e=>{if(e.target.closest('.discovery-graph-node,.discovery-graph-edge'))return;drag={x:e.clientX,y:e.clientY,view:[...state.view]};svg.setPointerCapture(e.pointerId);});
    svg.addEventListener('pointermove',e=>{if(!drag)return;const scale=Math.min(svg.clientWidth/drag.view[2],svg.clientHeight/drag.view[3]);state.view=[drag.view[0]-(e.clientX-drag.x)/scale,drag.view[1]-(e.clientY-drag.y)/scale,drag.view[2],drag.view[3]];views();});
    for(const type of ['pointerup','pointercancel','lostpointercapture'])svg.addEventListener(type,()=>{drag=null;});
    svg.addEventListener('wheel',e=>{e.preventDefault();state.view=zoomView(state.view,e.deltaY>0?1.12:1/1.12);views();},{passive:false});
    svg.addEventListener('keydown',e=>{if(e.key==='Escape')select(graph.root.id);});
    host.append(element('p','Labels: wallet → annotation. Code: code location → wallet. Select a connection for its literal predicate and provenance. Drag empty space to pan.','muted small'),svg,inspector);
    if(!graph.total)host.append(element('p','No Discovery results were returned for this run.','empty'));
    const fallback=element('details');fallback.append(element('summary','Accessible result list for this graph page'),table(['Type','Result','Predicate','Current review','Promoted',''],graph.items.map(n=>[kinds[n.type],n.title,n.predicate,review(n),n.promotion_count??'Unavailable',button('Select result',()=>select(n.id))]),'No Discovery results were returned for this run.'));host.append(fallback);
    views();const chosen=state.selected;if(chosen&&(chosen.id===graph.root.id||graph.items.some(n=>chosen.edge?n.result_id===chosen.id:n.id===chosen.id)))select(chosen.id,chosen.edge);else select(graph.root.id);
  }
  return {get active(){return active;},async show(value){active=value;host.hidden=!value;if(value)await load();else{generation++;controller?.abort();}},
    async setRun(id){if(id!==runId){generation++;controller?.abort();runId=id;offset=0;}if(active)await load();},
    pause(){generation++;controller?.abort();},refresh:load};
}
