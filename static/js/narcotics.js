import {api} from './api.js';
import {narcoticsRequest as request,narcoticsPath as path} from './narcotics_api.js';
import {byId,element,panel,table,details,fields,makeForm,action,run,UserError,dateText} from './ui.js';
import {profileFields,editedProfile,profilePayload,inputFields,fact} from './narcotics_presenter.js';
import {nexusGraph} from './narcotics_graph.js';

const sourceFields=[{name:'source_kind',label:'Provenance for new/changed facts',options:['analyst_entry','case_note','public_source_capture','discovery_result','attribution_evidence','sanctions_record','blockchain_observation']},
  {name:'source_reference',label:'Case source reference ID (required except analyst entry)'},{name:'source_note',label:'Provenance note',type:'textarea'}];
const provenance=data=>({kind:data.source_kind||'analyst_entry',reference_id:data.source_reference?.trim()||null,note:data.source_note||''});
export function initNarcotics(){
  const host=byId('narcotics-workspace');let caseId=null,profile=null,capabilities=null,comparison=null,graph=null,selected=[];
  const focus=panel('Selected Case'),editorHost=element('div'),analyses=element('div'),relatedHost=element('div'),graphHost=element('div'),priorityHost=element('div'),historyHost=element('div');
  host.append(element('h1','Narcotics Network Intelligence'),element('p','Analyst-controlled cross-Case linkage using stored Cases, public-source pins and explicit MO facts. No automatic identity or ownership inference.','bounded-note'),focus,editorHost,analyses,relatedHost,graphHost,priorityHost,historyHost);
  const operation=(fn)=>run(host,fn,'Loading stored Case intelligence...');
  const button=(label,fn)=>action(label,()=>operation(fn));
  const pin=(kind,id)=>button('Pin '+kind.replaceAll('_',' ')+' to selected Case',async()=>{await request(path(caseId,'/pins'),{method:'POST',body:{kind,reference_id:id}});await history();});
  async function load(id){
    if(id)caseId=id;
    capabilities ||= await request('/capabilities');
    const {cases}=await api('/cases?include_archived=true&sort=title');
    focus.replaceChildren(element('h2','Selected Case'));
    const choose=makeForm([{name:'case_id',label:'Case',options:[['','Select a Case'],...cases.map(c=>[c.id,c.title+(c.archived_at?' (archived)':'')])],value:caseId}], 'Open intelligence',async data=>{caseId=data.case_id||null;await load();});choose.id='narcotics-case-select';focus.append(choose,button('Open selected Case',()=>document.dispatchEvent(new CustomEvent('open-case',{detail:{id:caseId}}))));
    if(!caseId){editorHost.replaceChildren(element('p','Create Cases in the Cases workspace, then select one here.','empty'));return;}
    if(!cases.some(c=>c.id===caseId))throw new UserError('This Case is no longer available.');
    profile=(await request(path(caseId,'/profile'))).profile;
    comparison=null;graph=null;selected=[caseId];relatedHost.replaceChildren();graphHost.replaceChildren();priorityHost.replaceChildren();
    renderProfile();renderActions(cases);await history();
  }
  async function save(payload){profile=await request(path(caseId,'/profile'),{method:'PUT',body:payload});renderProfile();await history();}
  function renderProfile(){
    const section=panel('Narcotics Profile','Optional analyst-controlled facts. Unknown fields are excluded from comparison. One value per line. Existing unchanged facts retain their provenance.');section.id='narcotics-profile';
    const defs=profileFields.map(name=>({name,label:name.replaceAll('_',' '),type:['platform','logistics_method'].includes(name)?undefined:'textarea',
      ...(['platform','logistics_method'].includes(name)?{options:[['','Unknown / not entered'],...(name==='platform'?capabilities.platforms:capabilities.courier_methods)]}:{}),
      value:profile?.fields?.[name]?.map(f=>f.value).join('\n')||''}));
    const form=makeForm([...defs,{name:'wallets',label:'Chain-scoped wallets (one chain:address per line)',type:'textarea',value:profile?.wallets?.map(w=>w.chain+':'+w.address).join('\n')||''},
      {name:'period_start',label:'Activity period start (ISO-8601 including timezone)',value:profile?.period_start||''},
      {name:'period_end',label:'Activity period end (ISO-8601 including timezone)',value:profile?.period_end||''},...sourceFields], 'Save profile revision',async data=>{
        let payload;try{payload=editedProfile(profile||{},data);}catch(error){throw new UserError(error.message);}await save(payload);
      });form.id='narcotics-profile-form';
    const collapsed=element('details');collapsed.append(element('summary','Edit structured MO fields'),form);section.append(element('p',profile?'Profile revision '+profile.revision+' · '+dateText(profile.created_at):'No Narcotics Profile yet.','badge'),collapsed);
    if(!profile)collapsed.open=true;
    section.append(details('Full profile and per-fact provenance',profile));
    section.append(table(['Substance source name','Analyst category','Quantity / unit','Kind','Provenance'],(profile?.substances||[]).map(s=>[s.source_name,s.category,s.quantity==null?'Unknown':s.quantity+' '+(s.unit||''),s.kind,details('Source',s.provenance)]),'No substances entered.'));
    const substance=makeForm([{name:'source_name',label:'Substance name exactly as source entered',required:true},{name:'category',label:'Normalized category (analyst supplied, optional)'},
      {name:'kind',label:'Kind',options:['substance','precursor','pre_precursor']},{name:'quantity',label:'Quantity (decimal string)'},{name:'unit',label:'Unit'},{name:'note',label:'Substance note',type:'textarea'},...sourceFields], 'Add substance',async data=>{
      const payload=profilePayload(profile||{});payload.fields=inputFields(payload.fields);payload.substances.push({source_name:data.source_name,category:data.category||null,kind:data.kind,quantity:data.quantity||null,unit:data.unit||null,note:data.note,provenance:provenance(data)});await save(payload);
    });substance.id='narcotics-substance-form';section.append(substance);
    section.append(table(['Kind','Reference / service','Logistics facts'],(profile?.logistics||[]).map(s=>[s.kind,s.fields.carrier_reference?.map(f=>f.value).join(', ')||s.fields.carrier_service?.map(f=>f.value).join(', '),details('Full logistics object',s)]),'No consignments or courier events entered.'));
    const logistics=makeForm([{name:'kind',label:'Logistics object',options:['consignment','parcel','shipment','courier_event']},
      ...['carrier_reference','carrier_service','dispatch_at','interception_at','origin_country','origin_region','origin_city','destination_country','destination_region','destination_city','weight','weight_unit','packaging','concealment','notes'].map(name=>({name,label:name.replaceAll('_',' ')})),
      ...sourceFields], 'Add logistics object',async data=>{
      const payload=profilePayload(profile||{});payload.fields=inputFields(payload.fields);const f={};for(const [k,v] of Object.entries(data))if(v&&capabilities.fields.includes(k))f[k]=[{value:v,provenance:provenance(data)}];
      payload.logistics.push({kind:data.kind,fields:f,wallets:[],entity_reference_ids:[],provenance:provenance(data)});await save(payload);
    });logistics.id='narcotics-logistics-form';section.append(logistics);
    const advanced=element('details');advanced.append(element('summary','Advanced profile JSON: multiple facts, wallet/entity associations and individual provenance'),
      makeForm([{name:'payload',label:'Complete profile request',type:'textarea',value:JSON.stringify({...profilePayload(profile||{}),fields:inputFields(profile?.fields||{})},null,2)}], 'Save structured profile JSON',async data=>{let value;try{value=JSON.parse(data.payload);}catch{throw new UserError('Enter valid JSON.');}await save(value);}));section.append(advanced);
    editorHost.replaceChildren(section);
  }
  function renderActions(cases){
    const section=panel('Analyses','Actions run only when explicitly selected. Similarity is a weighted match fraction, never a probability.');section.id='narcotics-analyses';
    section.append(button('Generate MO fingerprint',async()=>{showFingerprint(await request(path(caseId,'/fingerprints'),{method:'POST',body:{}}));await history();}),
      button('Find related Cases',async()=>{comparison=await request(path(caseId,'/related'),{method:'POST',body:{}});showRelated(comparison);await history();}));
    const selection=element('fieldset');selection.id='narcotics-graph-cases';selection.append(element('legend','Selected Nexus Cases (maximum 20)'));
    for(const c of cases){const label=element('label',undefined,'narcotics-case-choice'),input=element('input');input.type='checkbox';input.value=c.id;input.checked=c.id===caseId;label.append(input,element('span',c.title));selection.append(label);}
    section.append(selection,button('Build Nexus Graph',async()=>{selected=[...selection.querySelectorAll('input:checked')].map(i=>i.value);if(!selected.length||selected.length>20)throw new UserError('Select between 1 and 20 Cases.');
      graph=await request('/nexus',{method:'POST',body:{case_ids:selected,link_run_ids:comparison&&comparison.case_ids.every(id=>selected.includes(id))?[comparison.id]:[]}});showGraph(graph);
    }));analyses.replaceChildren(section);
  }
  function showFingerprint(row){const card=panel('Modus Operandi fingerprint');card.id='narcotics-fingerprint';card.append(element('p',row.algorithm_version+' · source Case revision '+row.source_case_version),details('Selected normalized attributes, provenance and explicit weights',row),pin('mo_fingerprint',row.id));byId('narcotics-fingerprint')?.remove();analyses.append(card);}
  function showRelated(row){
    comparison=row;const section=panel('Related Cases','Potential links require review. Current reviews are shown; pinned comparisons retain their captured review state.');section.id='narcotics-related';
    section.append(element('p',`Compared ${row.related_cases.length} Cases at ${dateText(row.created_at)}${row.bounds.truncated?' · CASE LIMIT REACHED':''}`),pin('case_comparison',row.id));
    section.append(table(['Case','MO similarity','Comparable fields','Strong / moderate / weak / context','Review states','Last compared',''],row.related_cases.map(r=>[
      element('p',r.title+'\n'+r.case_id,'full-address'),r.similarity.score==null?'No comparable attributes':r.similarity.score+'/100',r.similarity.comparable_field_count,
      ['STRONG','MODERATE','WEAK','CONTEXT_ONLY'].map(s=>r.counts[s]).join(' / '),[...new Set(row.links.filter(l=>l.case_b===r.case_id).map(l=>l.review.status))].join(', ')||'No candidate links',dateText(r.compared_at),
      button('Why linked?',()=>explain(row,r))
    ]),'No other Cases were selected or available.'));
    relatedHost.replaceChildren(section);
  }
  function explain(runRow,related){
    const box=panel('Why linked?');box.id='narcotics-link-explanation';const s=related.similarity;
    box.append(element('p',`${s.matched_field_count} of ${s.comparable_field_count} comparable attributes match. Matched weight ${s.matched_weight}; denominator ${s.denominator}; weighted match fraction ${s.score??'unknown'}/100. Temporal relation: ${related.temporal_relation}.`),
      table(['Attribute','Match state','Configured / effective weight','Matched weight','Provenance'],s.contributions.map(c=>[c.field,c.state,c.weight+' / '+c.effective_weight,c.matched_weight,details('Inputs',c)])));
    for(const link of runRow.links.filter(l=>l.case_b===related.case_id)){
      const card=panel(link.link_type,link.strength+' · '+link.review.status);card.dataset.linkId=link.id;
      card.append(element('p',link.explanation),details('Source objects, provenance and review history',link));
      const review=makeForm([{name:'status',label:'Analyst review',options:['RELEVANT','IRRELEVANT','UNREVIEWED'],value:link.review.status},
        {name:'rationale',label:'Review rationale',type:'textarea',required:true}], 'Save link review',async data=>{
          await request('/links/'+encodeURIComponent(link.id)+'/reviews',{method:'POST',body:{...data,expected_sequence:link.review.sequence}});
          const current=await request('/runs/case_comparison/'+runRow.id);showRelated(current);explain(current,current.related_cases.find(r=>r.case_id===related.case_id));
        });review.dataset.linkReview=link.id;card.append(review);if(link.review.status!=='UNREVIEWED')card.append(pin('reviewed_link',link.id));box.append(card);
    }
    byId('narcotics-link-explanation')?.remove();relatedHost.append(box);
  }
  function showGraph(row){
    graph=row;const section=panel('Narcotics Nexus Graph',row.coverage);section.id='narcotics-nexus';
    section.append(element('p',row.disclaimer,'bounded-note'),pin('nexus',row.id),button('Run Network Priority',async()=>showPriority(await request('/priority',{method:'POST',body:{nexus_id:row.id}}))));
    const canvas=element('div');canvas.id='narcotics-graph';
    const filters=makeForm([{name:'node_type',label:'Node type',options:[['','All'],...[...new Set(row.nodes.map(n=>n.type))].sort()]},
      {name:'case_id',label:'Case',options:[['','All selected Cases'],...row.case_ids]},
      {name:'strength',label:'Link strength',options:[['','All'],'STRONG','MODERATE','WEAK','CONTEXT_ONLY']},
      {name:'review',label:'Review',options:[['','All'],'RELEVANT','IRRELEVANT','UNREVIEWED','relevant','unreviewed']},
      {name:'after',label:'Observed after (ISO-8601)'},{name:'before',label:'Observed before (ISO-8601)'},
      {name:'text',label:'Substance / geography / label text'},{name:'wallets',label:'Wallet / crypto types only',type:'checkbox'},{name:'logistics',label:'Logistics types only',type:'checkbox'}], 'Apply graph filters',data=>nexusGraph(canvas,row,data));filters.id='narcotics-graph-filters';
    section.append(filters,canvas);graphHost.replaceChildren(section);nexusGraph(canvas,row);
  }
  function showPriority(row){
    const section=panel('Network Priority',row.disclaimer);section.id='narcotics-priority';section.append(element('p','Structural importance within this selected, bounded graph. This does not change Risk or Attribution.'),pin('priority',row.id),
      table(['Node','Priority','Selected Cases','Degree / betweenness','Independent source references','Explanation'],row.metrics.map(m=>[m.label,m.category+' '+m.score+'/100',m.case_count,m.degree+' / '+m.betweenness,m.independent_source_count,details('Reasons and reproducible metrics',m)])),details('Run, graph fingerprint, version and bounds',row));priorityHost.replaceChildren(section);
  }
  async function history(){
    const rows=await request(path(caseId,'/history'));const section=panel('Intelligence history','Newest 50 records per type. Every stored run is immutable; current link reviews are a separate append-only history.');section.id='narcotics-history';
    for(const [key,kind] of [['fingerprints','mo_fingerprint'],['comparisons','case_comparison']])section.append(table([key,'Calculated',''],rows[key].map(r=>[r.id,dateText(r.created_at),button('Open '+kind.replaceAll('_',' '),async()=>{const current=await request('/runs/'+kind+'/'+r.id);kind==='mo_fingerprint'?showFingerprint(current):showRelated(current);})])));
    const pinRefs=(await api('/cases/'+encodeURIComponent(caseId))).entities.filter(r=>r.metadata_json?.narcotics_pin);
    section.append(table(['Pinned historical analysis','ID','Snapshot'],pinRefs.map(r=>[r.metadata_json.narcotics_pin.kind,r.entity_ref,details('Immutable pin',r.metadata_json.narcotics_pin)]),'No Narcotics intelligence pins. Reports include pinned analyses and the profile at report generation.'));
    historyHost.replaceChildren(section);
  }
  return id=>operation(()=>load(id));
}
