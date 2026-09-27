// Presentation state only. No API calls, analytical mutations or provider data.
const memory = new Map();
export const layoutKey = context => 'gc.graph-layout.v1:' + JSON.stringify(context);
const valid = p => p && Number.isFinite(p.x) && Number.isFinite(p.y) && Math.abs(p.x)<1e7 && Math.abs(p.y)<1e7;
export function manualLayout(context, positions, storage) {
  if (storage === undefined) { try { storage=globalThis.sessionStorage; } catch {} }
  const key=layoutKey(context), defaults=new Map([...positions].map(([id,p])=>[id,{...p}]));
  let saved=memory.get(key) || [];
  try { const value=JSON.parse(storage?.getItem(key) || 'null'); if(Array.isArray(value)) saved=value; } catch {}
  const entries=new Map(saved.filter(row=>Array.isArray(row)&&typeof row[0]==='string'&&valid(row[1])));
  const pins=new Set();
  for(const [id,p] of positions) {const prior=entries.get(id);if(prior){p.x=prior.x;p.y=prior.y;if(prior.pinned===true)pins.add(id);}}
  function save() {
    for(const [id,p] of positions) entries.set(id,{x:p.x,y:p.y,pinned:pins.has(id)});
    const value=[...entries];memory.set(key,value);
    try {storage?.setItem(key,JSON.stringify(value));} catch {} // Still retained in this page if storage is disabled/full.
  }
  save();
  return {positions, pinned:id=>pins.has(id),
    move(id,x,y){if(!positions.has(id)||!valid({x,y}))return;Object.assign(positions.get(id),{x,y});pins.add(id);save();},
    pin(id,value){if(!positions.has(id))return;value?pins.add(id):pins.delete(id);save();},
    auto(){for(const [id,p] of positions)if(!pins.has(id))Object.assign(p,defaults.get(id));save();},
    reset(){pins.clear();for(const [id,p] of positions)Object.assign(p,defaults.get(id));entries.clear();memory.delete(key);try{storage?.removeItem(key);}catch{}},
  };
}
export function positionBounds(positions, {centered=false,width=0,height=0}={}) {
  const boxes=[...positions.values()].map(p=>({x:p.x-(centered?width/2:0),y:p.y-(centered?height/2:0),w:p.width||width,h:p.height||height}));
  if(!boxes.length)return [0,0,900,560];
  const x=Math.min(...boxes.map(p=>p.x))-80,y=Math.min(...boxes.map(p=>p.y))-110;
  return [x,y,Math.max(...boxes.map(p=>p.x+p.w))-x+80,Math.max(...boxes.map(p=>p.y+p.h))-y+110];
}
export function graphInteraction({svg,tools,layout,context,redraw,centered=false,width=0,height=0}) {
  const state=manualLayout(context,layout.positions),nodes=new Map();let selected=null;
  const button=(label,fn)=>{const b=document.createElement('button');b.type='button';b.className='secondary';b.textContent=label;b.addEventListener('click',fn);tools.append(b);return b;};
  const pin=button('Pin selected node',()=>{if(selected!==null){state.pin(selected,!state.pinned(selected));update();}});pin.disabled=true;
  button('Auto layout',()=>{state.auto();update();});button('Reset layout',()=>{state.reset();update();});
  function update(){
    layout.bounds=positionBounds(layout.positions,{centered,width,height});
    for(const [id,{group,badge}] of nodes){const p=layout.positions.get(id);group.setAttribute('transform',`translate(${p.x} ${p.y})`);group.classList.toggle('is-pinned',state.pinned(id));badge.textContent=state.pinned(id)?'PINNED':'';}
    pin.disabled=selected===null;pin.textContent=selected!==null&&state.pinned(selected)?'Unpin selected node':'Pin selected node';redraw();
  }
  svg.addEventListener('click',e=>{if(![...nodes.values()].some(n=>n.group.contains(e.target))){selected=null;pin.disabled=true;pin.textContent='Pin selected node';}});
  svg.addEventListener('keydown',e=>{if(e.key==='Escape'){selected=null;pin.disabled=true;pin.textContent='Pin selected node';}});
  function bind(group,id){
    const badge=document.createElementNS('http://www.w3.org/2000/svg','text');badge.setAttribute('class','pin-badge');badge.setAttribute('x',centered?width/2:layout.positions.get(id).width);badge.setAttribute('y',centered?-height/2-10:-10);badge.setAttribute('text-anchor','end');group.append(badge);nodes.set(id,{group,badge});
    let drag=null,suppress=false;
    const point=e=>{const matrix=svg.getScreenCTM();return matrix?new DOMPoint(e.clientX,e.clientY).matrixTransform(matrix.inverse()):null;};
    const select=()=>{selected=id;pin.disabled=false;pin.textContent=state.pinned(id)?'Unpin selected node':'Pin selected node';};
    group.addEventListener('click',e=>{if(suppress){e.preventDefault();e.stopImmediatePropagation();suppress=false;}else select();},true);
    group.addEventListener('keydown',e=>{if(['Enter',' '].includes(e.key))select();});
    group.addEventListener('pointerdown',e=>{if(e.button!==0||!e.isPrimary)return;const p=point(e);if(!p)return;const old=layout.positions.get(id);drag={pointer:e.pointerId,x:p.x,y:p.y,sx:e.clientX,sy:e.clientY,oldX:old.x,oldY:old.y,moved:false};group.setPointerCapture(e.pointerId);e.stopPropagation();});
    group.addEventListener('pointermove',e=>{if(!drag||e.pointerId!==drag.pointer)return;const p=point(e);if(!p)return;if(!drag.moved&&Math.hypot(e.clientX-drag.sx,e.clientY-drag.sy)<4)return;drag.moved=true;select();state.move(id,drag.oldX+p.x-drag.x,drag.oldY+p.y-drag.y);update();e.preventDefault();e.stopPropagation();});
    const end=e=>{if(!drag||e.pointerId!==drag.pointer)return;suppress=drag.moved;drag=null;if(group.hasPointerCapture(e.pointerId))group.releasePointerCapture(e.pointerId);setTimeout(()=>{suppress=false;},0);};
    for(const event of ['pointerup','pointercancel','lostpointercapture'])group.addEventListener(event,end);
  }
  // Restored positions are used before paths/nodes are first rendered.
  layout.bounds=positionBounds(layout.positions,{centered,width,height});
  return {bind,update,state};
}
