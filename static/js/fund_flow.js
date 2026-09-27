import {api} from './api.js';
import {byId,element,panel,makeForm,action,details,table,shortValue,UserError} from './ui.js';
const disclaimer='Observed blockchain relationships do not establish ownership, control, identity, transfer purpose or wrongdoing.';
let navigate;
let graphSerial=0;
export async function flowRequest(path,options) {
  try{return await api('/fund-flow'+path,options);}
  catch(error){
    if(error.status===422)throw new UserError('Fund flow is unavailable for this chain or query. Check wallet identifiers, asset, time range and hop bounds. Widest paths need one explicit account-chain asset.');
    if(error.status===503)throw new UserError('Fund-flow storage unavailable or busy. An explicit migration may be required.');
    throw error;
  }
}
export async function initFundFlow(nav) {
  navigate=nav;
  const host=byId('fund-flow-workspace');
  const capabilities=await flowRequest('/capabilities');
  const controls=panel('Fund Flow',disclaimer);
  controls.append(element('p','Local stored activity only. No providers are called. Monero has no transparent fund-flow capability. Paths do not establish that the same funds traversed every hop.','bounded-note'));
  const form=makeForm([
    {name:'chain',label:'Chain',options:capabilities.chains.map(d=>[d.id,d.name])},
    {name:'source',label:'Source wallet',required:true,maxLength:128},
    {name:'mode',label:'Analysis',options:[['path','Paths to target'],['neighborhood','Outgoing neighborhood + wallet metrics']]},
    {name:'target_type',label:'Target definition',options:[['wallet','Specific wallet'],['label_category','Local Label category'],['label','Exact local Label']]},
    {name:'target_value',label:'Target wallet or Label/category',maxLength:255},
    {name:'asset',label:'Asset (optional): native or chain:token:contract/mint',maxLength:180},
    {name:'algorithm',label:'Algorithm',options:[['shortest','Shortest hops'],['simple','Bounded simple paths'],['widest','Highest observed path capacity']]},
    {name:'max_hops',label:'Maximum hops (1-6)',type:'number',min:1,max:6,value:3,required:true},
    {name:'temporal_order',label:'Chronological edges',type:'checkbox',value:true},
    {name:'start_time',label:'Start time (UTC)',type:'datetime-local',step:1},
    {name:'end_time',label:'End time (UTC)',type:'datetime-local',step:1},
  ],'Run analysis',async data=>{
    const body={chain:data.chain,source:data.source.trim(),algorithm:data.algorithm,max_hops:Number(data.max_hops),temporal_order:!!data.temporal_order};
    if(data.asset.trim())body.asset=data.asset.trim();
    if(data.start_time)body.start_time=data.start_time+(data.start_time.length===16?':00Z':'Z');
    if(data.end_time)body.end_time=data.end_time+(data.end_time.length===16?':00Z':'Z');
    if(data.mode==='path') {
      if(!data.target_value.trim())throw new UserError('Enter a target wallet, Label or category.');
      body[data.target_type==='wallet'?'target':data.target_type]=data.target_value.trim();
    }
    const result=await flowRequest('/'+data.mode,{method:'POST',body});
    byId('flow-results').replaceChildren(flowCard(result));
  });
  form.id='fund-flow-form';controls.append(form);host.append(controls,element('div'));host.lastChild.id='flow-results';
  const restore=makeForm([{name:'run_id',label:'Stored run ID',required:true,maxLength:36}],'Open stored run',async data=>{
    byId('flow-results').replaceChildren(flowCard(await flowRequest('/runs/'+encodeURIComponent(data.run_id.trim()))));
  });controls.append(restore);
}
function svgNode(tag,attrs={},value) {
  const node=document.createElementNS('http://www.w3.org/2000/svg',tag);
  for(const [key,val] of Object.entries(attrs))node.setAttribute(key,val);
  if(value!==undefined)node.textContent=value;
  return node;
}
function resultGraph(run) {
  const host=element('div');const paths=run.paths;
  const select=element('select');select.setAttribute('aria-label','Selected flow path');
  paths.forEach((_,i)=>{const o=element('option',`Path ${i+1}`);o.value=i;select.append(o);});
  const svg=svgNode('svg',{'aria-label':'Bounded observed-flow result subgraph',role:'img',viewBox:'0 0 1200 500'});
  svg.classList.add('flow-graph');
  const inspection=element('div');
  const markerId='flow-arrow-'+(++graphSerial);
  function draw(index) {
    svg.replaceChildren();inspection.replaceChildren();
    const path=paths[index];if(!path)return;
    // Progressive graph disclosure: exactly one selected bounded result path at a time.
    const defs=svgNode('defs');const marker=svgNode('marker',{id:markerId,viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:6,markerHeight:6,orient:'auto'});marker.append(svgNode('path',{d:'M0,0 L10,5 L0,10 Z',fill:'#526b8a'}));defs.append(marker);svg.append(defs);
    const count=path.addresses.length;const width=160;const gap=240;
    svg.setAttribute('viewBox',`0 0 ${Math.max(450,count*gap)} 250`);
    path.addresses.forEach((address,i)=>{
      const group=svgNode('g',{'data-flow-address':address,transform:`translate(${i*gap+20},90)`});
      group.append(svgNode('rect',{width,height:64,rx:6,fill:i===0?'#d9e9fc':i===count-1?'#e5efdb':'#f2f3f5',stroke:'#526b8a'}));
      group.append(svgNode('text',{x:8,y:22},i===0?'SOURCE':i===count-1?'PATH TARGET':'ADDRESS'));
      group.append(svgNode('text',{x:8,y:45},address.slice(0,7)+'...'+address.slice(-7)));group.append(svgNode('title',{},address));svg.append(group);
      if(i<count-1){
        const step=path.steps[i];svg.append(svgNode('line',{x1:i*gap+20+width,y1:122,x2:(i+1)*gap+12,y2:122,stroke:'#526b8a','stroke-width':3,'marker-end':`url(#${markerId})`}));
        svg.append(svgNode('text',{x:i*gap+width+25,y:105},step.semantics==='utxo_connectivity'?'via TX':'transfer'));
      }
    });
    inspection.append(element('p',path.explanation,'bounded-note'));
    inspection.append(element('p',`${run.chain} ? ${path.hops} hops ? ${path.asset} ? ${path.first_timestamp || 'Unknown time'} ? ${path.last_timestamp || 'Unknown time'}`));
    if(path.observed_path_capacity!==null)inspection.append(element('p',`Observed path capacity: ${path.observed_path_capacity} (${path.asset})`));
    for(const step of path.steps) {
      const card=element('article');card.append(element('h3',`${step.source} ? ${step.target}`,'full-address'));
      card.append(element('p',`${step.tx_hash} / ${step.event_key}`,'full-address'));
      card.append(element('p',`${step.timestamp || 'Timestamp unavailable'} ? ${step.asset} ? ${step.amount===null?'Exact allocation unavailable':step.amount}`));
      if(step.semantics==='utxo_connectivity')card.append(element('p',`Transaction output ${step.output_index}: ${step.output_amount}. This amount is not allocated to this input.`, 'bounded-note'));
      card.append(details('Stored event provenance',step));
      if(step.transaction_provenance_ref)card.append(details('UTXO transaction participants',run.utxo_transactions.find(e=>e.id===step.transaction_provenance_ref)));
      inspection.append(card);
    }
  }
  select.addEventListener('change',()=>draw(Number(select.value)));host.append(select,svg,inspection);draw(0);return host;
}
export function flowCard(run,historical=false) {
  const host=panel(`Fund-flow run ${run.id}`,disclaimer);host.dataset.flowRun=run.id;
  host.append(element('p',`${run.algorithm_version} ? ${run.chain} ? ${run.paths.length} returned paths ? created ${run.created_at}`));
  host.append(element('p',run.coverage,'bounded-note'));
  host.append(element('p',run.truncated?`Truncated: ${run.limiting_reasons.join(', ')}. Results are not exhaustive.`:'Search completed within the stated local-data and hop bounds.'));
  host.append(details('Parameters and reproducibility',{parameters:run.parameters,resolved_targets:run.resolved_targets,source_data_cutoff:run.source_data_cutoff,source_data_fingerprint:run.source_data_fingerprint,result_fingerprint:run.result_fingerprint,excluded_records:run.excluded_records}));
  if(run.paths.length)host.append(resultGraph(run));
  else host.append(element('p','No paths returned in this scope. Additional collection may be required.','empty'));
  host.append(element('h3','Fan-in / fan-out'),element('p',run.metric_scope,'muted small'));
  host.append(table(['Direction','Asset identity','Distinct counterparties','Events','Observed amount'],run.analytics.fan_in_out.map(m=>[m.direction,m.asset,m.distinct_counterparties,m.event_count,m.observed_amount ?? 'UTXO connectivity; no allocation'])));
  host.append(element('h3','Repeated counterparties'),table(['Direction','Counterparty','Asset','Count','First','Last','Observed amount'],run.analytics.repeated_counterparties.map(m=>[m.direction,shortValue(m.counterparty),m.asset,m.count,m.first_observed,m.last_observed,m.observed_amount ?? 'No exact allocation'])));
  if(!historical)host.append(action('Pin run to Case',async()=>{
    const {listCases}=await import('./case_actions.js');const cases=await listCases();
    if(!cases.length)throw new UserError('Create a Case first.');
    const picker=makeForm([{name:'case_id',label:'Case',options:cases.map(c=>[c.id,c.title])}],'Confirm run pin',async data=>{
      await flowRequest(`/cases/${data.case_id}/pin`,{method:'POST',body:{run_id:run.id}});
      picker.replaceChildren(element('p','Run pinned. Later collection cannot change this historical material.'));
    });host.append(picker);
  }));
  return host;
}
