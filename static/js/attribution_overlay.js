import {element} from './ui.js';
import {caption} from './attribution_api.js';
import {currentOverlayClaim, assessmentText, openAttribution} from './attribution_summary.js';

const NS='http://www.w3.org/2000/svg';
const svgNode=(tag,attrs={},text)=>{const n=document.createElementNS(NS,tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,v);if(text!==undefined)n.textContent=text;return n;};

export function overlayData(claims,position,bounds) {
  const eligible=claims.filter(currentOverlayClaim).sort((a,b)=>a.id.localeCompare(b.id));
  const entities=[...new Map(eligible.map(c=>[c.entity.id,c.entity])).values()].sort((a,b)=>a.id.localeCompare(b.id));
  return {entities:entities.map((entity,index)=>({entity,id:`entity:${entity.id}`,x:position.x+(index%4)*290,y:bounds[1]+bounds[3]+60+Math.floor(index/4)*130})),
    edges:eligible.map(claim=>({id:`claim:${claim.id}`,source:`wallet:${claim.chain}:${claim.subject_ref}`,target:`entity:${claim.entity_id}`,claim}))};
}

export function attributionOverlay({svg,tools,detail,layout,getView,setView}) {
  let enabled=false,source=null,position=null,claims=[],savedView=null,selected=null;
  const layer=svgNode('g',{'data-layer':'attribution'});svg.append(layer);
  const control=element('label',undefined,'attr-check');const toggle=element('input');toggle.type='checkbox';toggle.id='graph-attribution-overlay';
  control.append(toggle,element('span','Attribution overlay'));tools.append(control);
  const note=element('p','Overlay off. Optional entities describe current assessed claims for the selected wallet and displayed summary page only.','muted small');tools.append(note);
  function select(node,render) {
    const activate=()=>{svg.querySelectorAll('.selected').forEach(n=>{n.classList.remove('selected');n.setAttribute('aria-pressed','false');});node.classList.add('selected');node.setAttribute('aria-pressed','true');render();};
    node.tabIndex=0;node.setAttribute('role','button');node.setAttribute('aria-pressed','false');
    node.addEventListener('click',activate);node.addEventListener('keydown',event=>{if(['Enter',' '].includes(event.key)){event.preventDefault();activate();}});
  }
  const open=(label,context)=>{const b=element('button',label,'secondary');b.type='button';b.addEventListener('click',()=>openAttribution(context));return b;};
  function render() {
    layer.replaceChildren();selected=null;
    if(!enabled||!source||!position)return;
    const data=overlayData(claims,position,layout.bounds);
    note.textContent=`Overlay on: ${data.edges.length} current assessed claims on this selected wallet's summary page. Review-required, unassessed, rejected and archived claims remain in the inspector, not as positive overlay edges. Attribution edges do not count as blockchain hops.`;
    for(const edge of data.edges) {
      const target=data.entities.find(e=>e.id===edge.target),index=data.edges.indexOf(edge);
      const x1=position.x+position.width/2,y1=position.y+position.height,x2=target.x+120,y2=target.y;
      const lane=layout.bounds[1]+layout.bounds[3]+20+index*3;
      const path=`M ${x1} ${y1} C ${x1+index*10} ${lane}, ${x2+index*10} ${lane}, ${x2} ${y2}`;
      const group=svgNode('g',{class:'attribution-edge','data-claim-id':edge.id,'data-source':edge.source,'data-target':edge.target,'data-edge-type':'attribution'});
      group.append(svgNode('path',{d:path,class:'edge-hit'}),svgNode('path',{d:path,class:`attribution-line ${edge.claim.assessment}`,'marker-end':'url(#attribution-arrow)'}),
        svgNode('title',{},`${caption(edge.claim.relationship)} · ${assessmentText(edge.claim)} — attribution claim, not a transaction`));
      select(group,()=>{
        selected=edge.id;detail.replaceChildren(element('h3','Attribution claim'),element('p',`${edge.claim.subject_ref} → ${edge.claim.entity.canonical_name}`,'full-address'),
          element('p',`Claimed relationship: ${caption(edge.claim.relationship)} · Assessment: ${assessmentText(edge.claim)}`),
          element('p','This is an analyst claim, not a blockchain transaction. It has no transaction amount or hop depth.','muted small'),open('Open attribution',{action:'open_claim',id:edge.claim.id}));
      });layer.append(group);
    }
    for(const entry of data.entities) {
      const {entity}=entry;
      const group=svgNode('g',{class:'attribution-entity','data-entity-id':entry.id,'data-node-type':'entity',transform:`translate(${entry.x} ${entry.y})`});
      group.append(svgNode('rect',{width:240,height:86,rx:2}),svgNode('text',{x:12,y:22},'ENTITY'),svgNode('text',{x:12,y:44},entity.canonical_name.length>28?entity.canonical_name.slice(0,25)+'…':entity.canonical_name),
        svgNode('text',{x:12,y:66},caption(entity.entity_type)),svgNode('title',{},`${entity.canonical_name} · ${entity.id}`));
      select(group,()=>{
        selected=entry.id;detail.replaceChildren(element('h3','Entity descriptor'),element('p',entity.canonical_name),element('p',`Type: ${caption(entity.entity_type)} · Aliases: ${entity.aliases.join(', ')||'None'}`),
          element('p',`${data.edges.filter(e=>e.target===entry.id).length} displayed claims · ${entity.archived_at?'Archived':'Active'}`),
          open('Open in Attribution',{action:'open_entity',id:entity.id}));
      });layer.append(group);
    }
  }
  const marker=svgNode('marker',{id:'attribution-arrow',viewBox:'0 0 10 10',refX:10,refY:5,markerWidth:8,markerHeight:8,orient:'auto'});
  marker.append(svgNode('path',{d:'M 0 0 L 10 5 L 0 10 z',fill:'#795b86'}));svg.querySelector('defs').append(marker);
  toggle.addEventListener('change',()=>{
    enabled=toggle.checked;
    if(enabled){savedView=[...getView()];render();const box=layer.childElementCount?layer.getBBox():null;if(box){const [x,y,w,h]=layout.bounds;const width=Math.max(w,box.x+box.width-x+70),height=Math.max(h,box.y+box.height-y+70);setView([x,y,Math.max(width,height*900/560),Math.max(height,width*560/900)]);}}
    else {layer.replaceChildren();if(savedView)setView(savedView);savedView=null;note.textContent='Overlay off. Base transaction graph retained.';if(selected)detail.replaceChildren(element('p','Attribution overlay hidden. Select a wallet or transaction connection.'));selected=null;}
  });
  return {
    bounds(){if(!enabled||!layer.childElementCount)return layout.bounds;const b=layer.getBBox(),[x,y,w,h]=layout.bounds;const left=Math.min(x,b.x-30),top=Math.min(y,b.y-30);return [left,top,Math.max(x+w,b.x+b.width+70)-left,Math.max(y+h,b.y+b.height+70)-top];},
    source(node,pos){source=node;position=pos;claims=[];render();},
    claims(rows){const wasSelected=selected;claims=rows;render();if(wasSelected)detail.replaceChildren(element('p','Attribution refreshed. Select a current entity or claim to inspect it.'));},
    clear(){source=null;position=null;claims=[];render();},
  };
}
