// Pure presentation. Graph filters never alter the saved evidence/run.
export const profileFields=['vendor_alias','marketplace','marketplace_account','domain','public_profile','platform','payment_method','logistics_method','consignment_type','origin_country','origin_region','origin_city','destination_country','destination_region','destination_city','seizure_location','concealment','packaging','delivery_method','drop_method','recipient_pattern','sender_pattern','mo_tag','notes','extension'];
export const fact=value=>({value,provenance:{kind:'analyst_entry',note:''}});
export function profilePayload(profile={}) {
  return structuredClone({expected_revision:profile.revision||0,fields:profile.fields||{},wallets:(profile.wallets||[]).map(({chain,address,provenance})=>({chain,address,provenance:inputProvenance(provenance)})),
    substances:(profile.substances||[]).map(({id,...row})=>({...row,provenance:inputProvenance(row.provenance)})),
    logistics:(profile.logistics||[]).map(({id,...row})=>({...row,provenance:inputProvenance(row.provenance),
      wallets:row.wallets.map(w=>({...w,provenance:inputProvenance(w.provenance)})),fields:inputFields(row.fields)})),
    period_start:profile.period_start||null,period_end:profile.period_end||null,
  });
}
export function inputProvenance({kind='analyst_entry',reference_id=null,note=''}={}) {return {kind,reference_id,note};}
export function inputFields(fields) {return Object.fromEntries(Object.entries(fields).map(([key,rows])=>[key,rows.map(r=>({value:r.value,provenance:inputProvenance(r.provenance)}))]));}
export function editedProfile(profile,data) {
  const payload=profilePayload(profile);payload.fields=inputFields(payload.fields);
  const provenance={kind:data.source_kind||'analyst_entry',reference_id:data.source_reference?.trim()||null,note:data.source_note||''};
  for(const key of profileFields) {
    if(!(key in data))continue;
    const values=data[key].split('\n').map(s=>s.trim()).filter(Boolean);
    const previous=(profile.fields?.[key]||[]);
    payload.fields[key]=values.map(value=>({value,provenance:inputProvenance(previous.find(p=>p.value===value)?.provenance||provenance)}));
  }
  if('wallets' in data)payload.wallets=data.wallets.split('\n').map(s=>s.trim()).filter(Boolean).map(row=>{
    const split=row.indexOf(':');if(split<=0)throw Error('Use one chain:address per line for wallet references.');
    const chain=row.slice(0,split),address=row.slice(split+1),old=profile.wallets?.find(w=>w.chain===chain&&w.address===address);
    return {chain,address,provenance:inputProvenance(old?.provenance||provenance)};
  });
  for(const key of ['period_start','period_end'])if(key in data)payload[key]=data[key].trim()||null;
  return payload;
}
export function filteredGraph(graph,filter={}) {
  const query=String(filter.text||'').trim().toLowerCase();
  const type=filter.node_type,subset=filter.case_id;
  let nodes=graph.nodes.filter(n=>(!type||n.type===type)&&(!subset||n.case_ids.includes(subset))&&
    (!query||JSON.stringify([n.label,n.metadata]).toLowerCase().includes(query))&&
    (!filter.wallets||['case','wallet','transaction','technical_cluster'].includes(n.type))&&
    (!filter.logistics||['case','consignment','logistics','location'].includes(n.type)));
  let ids=new Set(nodes.map(n=>n.id));
  let edges=graph.edges.filter(e=>ids.has(e.source)&&ids.has(e.target)&&(!filter.strength||e.strength===filter.strength)&&
    (!filter.review||e.review_status===filter.review)&&(!subset||e.case_id===subset)&&
    (!(filter.after||filter.before)||e.provenance.some(p=>p.observed_at&&(!filter.after||p.observed_at>=filter.after)&&(!filter.before||p.observed_at<=filter.before))));
  if(filter.strength||filter.review||filter.after||filter.before){ids=new Set(edges.flatMap(e=>[e.source,e.target]));nodes=nodes.filter(n=>ids.has(n.id));}
  return {...graph,nodes,edges};
}
export function nexusLayout(graph) {
  // Multi-source BFS from selected Cases; stable type/label/ID order within hop bands.
  const neighbors=new Map(graph.nodes.map(n=>[n.id,new Set()]));
  for(const e of graph.edges){neighbors.get(e.source)?.add(e.target);neighbors.get(e.target)?.add(e.source);}
  const depths=new Map(),queue=[];
  for(const n of graph.nodes.filter(n=>n.type==='case').sort((a,b)=>a.id.localeCompare(b.id))){depths.set(n.id,0);queue.push(n.id);}
  for(let i=0;i<queue.length;i++)for(const id of [...neighbors.get(queue[i])].sort())if(!depths.has(id)){depths.set(id,depths.get(queue[i])+1);queue.push(id);}
  const groups=new Map();
  for(const n of graph.nodes){const depth=depths.get(n.id)??Math.max(1,...depths.values());if(!groups.has(depth))groups.set(depth,[]);groups.get(depth).push(n);}
  const positions=new Map();
  for(const [depth,rows] of [...groups].sort((a,b)=>a[0]-b[0])){
    rows.sort((a,b)=>a.type.localeCompare(b.type)||a.label.localeCompare(b.label)||a.id.localeCompare(b.id));
    // Wrap large bands into five columns; fixed card dimensions guarantee no overlap.
    const columns=Math.min(5,Math.max(1,Math.ceil(rows.length/12))),height=Math.ceil(rows.length/columns);
    rows.forEach((n,i)=>positions.set(n.id,{x:depth*1500+(i%columns)*270,y:Math.floor(i/columns)*108-height*54,width:230,height:78}));
  }
  return {positions,depths};
}
export function nexusPath(edge,layout,offset=0) {
  const a=layout.positions.get(edge.source),b=layout.positions.get(edge.target);if(!a||!b)return '';
  const ax=a.x+230,ay=a.y+39,bx=b.x,by=b.y+39;
  const bend=Math.max(65,Math.abs(bx-ax)*.35)+offset;
  return `M ${ax} ${ay} C ${ax+bend} ${ay+offset}, ${bx-bend} ${by+offset}, ${bx} ${by}`;
}
