import {element,panel,fields,action,details,table,dateText,shortValue} from './ui.js';
import {casePath,caseRequest} from './case_actions.js';
import {caseCounts,referenceMode} from './case_presenter.js';
import {flowCard,flowRequest} from './fund_flow.js';
import {clusterCard,clusterRequest} from './clustering.js';

export function completionSections(row,{editor,button,reload,refresh}) {
  const path=casePath(row.id);
  const lifecycle=panel('Case lifecycle');lifecycle.id='case-lifecycle-panel';
  const update=async body=>{await caseRequest(path,{method:'PATCH',body:{...body,expected_version:row.version}});await refresh();};
  lifecycle.append(editor('case-lifecycle',[
    {name:'title',label:'Title',required:true,maxLength:255,value:row.title},
    {name:'status',label:'Status',options:['Open','Paused','Closed'],value:row.status},
    {name:'description',label:'Description',type:'textarea',value:row.description}
  ],'Save case details',update),button(row.archived_at?'Restore case':'Archive case',()=>update({archived:!row.archived_at})));
  const summary=panel('Analyst-authored summary');summary.id='case-summary';
  const names=['scope','key_findings','unresolved_questions','limitations','next_actions'];
  summary.append(editor('case-summary-form',names.map(name=>({name,label:name.replaceAll('_',' '),type:'textarea',maxLength:20000,value:row.summary?.[name]||''})),'Save analyst summary',data=>update({summary:data})));
  const counts=element('div',undefined,'toolbar');counts.id='case-counts';
  for(const [label,count] of caseCounts(row))counts.append(element('span',label+': '+count,'badge'));
  const timeline=panel('Case activity timeline','Writes and explicit pins only. Reads and navigation create no activity.');timeline.id='case-timeline';
  timeline.append(table(['Time','Activity','Reference','Retained revision'],(row.timeline||[]).map(e=>[dateText(e.created_at),e.kind.replaceAll('_',' '),shortValue(e.reference_id||''),details('View event / earlier note text',e.record)]),'No recorded activity.'));
  const history=panel('Immutable report history','Stored bytes are never regenerated or replaced. SHA-256 identifies the downloaded bytes; state fingerprint identifies the exact Case material used.');history.id='case-report-history';
  history.append(table(['Report / format','Generated','SHA-256','State fingerprint','Generator','Download'],(row.reports||[]).map(r=>{
    const link=element('a','Download stored report');link.href='/api/greedy-collector'+path+'/reports/'+encodeURIComponent(r.id);
    const identity=element('span');identity.append(shortValue(r.id),element('span',' / '+r.format));
    return [identity,dateText(r.generated_at),shortValue(r.sha256),shortValue(r.state_fingerprint),r.generator_version,link];
  }),'No reports have been generated.'));
  const pins=panel('Pinned risk / Discovery snapshots','Historical analytical material remains unchanged after later analysis.');pins.id='case-additional-pins';
  for(const item of row.entities){
    const m=item.metadata_json||{},risk=m.risk_assessment;
    if(risk){
      pins.append(element('p',`Pinned risk: ${m.chain} ${m.address||item.entity_ref} · ${risk.overall_score??risk.score}/100 · ${risk.overall_tier||risk.level} · ${risk.model_version||risk.scoring_model}`),details('View pinned risk assessment',risk));
    }
    if(item.entity_type==='discovery_run'){
      pins.append(element('p','Discovery run: '+item.entity_ref),details('View pinned Discovery run',m.discovery_run_pin));
    }
  }
  pins.hidden=!row.entities.some(e=>e.metadata_json?.risk_assessment||e.entity_type==='discovery_run');
  return {lifecycle,summary,counts,timeline,history,pins};
}

export function noteEditors(row,{editor,button,reload}) {
  const host=element('div');
  for(const note of row.notes){
    const card=element('details');card.append(element('summary',`Edit note ${note.id} · version ${note.version}${note.archived_at?' · Archived':''}`));
    const update=async body=>{await caseRequest(casePath(row.id)+'/notes/'+encodeURIComponent(note.id),{method:'PATCH',body:{...body,expected_version:note.version}});await reload();};
    card.append(editor('case-note-'+note.id,[{name:'body',label:'Note',type:'textarea',required:true,value:note.body}],'Save note',data=>update(data)),
      button(note.archived_at?'Restore note':'Archive note',()=>update({archived:!note.archived_at})));host.append(card);
  }
  return host;
}

export function pinNavigation(item) {
  const controls=element('div',undefined,'toolbar'),m=item.metadata_json||{};
  const navigate=name=>document.querySelector('[data-workspace="'+name+'"]').click();
  if(item.entity_type==='technical_cluster')controls.append(action('Open current cluster',async()=>{
    const snapshot=await clusterRequest('/clusters/'+encodeURIComponent(m.cluster_pin.id));navigate('clustering');document.getElementById('cluster-results').replaceChildren(clusterCard(snapshot));
  }));
  if(item.entity_type==='fund_flow')controls.append(action('Open stored Fund Flow run',async()=>{
    const snapshot=await flowRequest('/runs/'+encodeURIComponent(item.entity_ref));navigate('fund-flow');document.getElementById('flow-results').replaceChildren(flowCard(snapshot));
  }));
  const pin=m.broad_discovery_pin||m.discovery_run_pin;
  if(pin)controls.append(action('Open live Discovery run',()=>document.dispatchEvent(new CustomEvent('open-discovery',{detail:{action:'open_run',run_id:pin.run.id}}))));
  if(m.public_source_capture_pin){
    const origin=m.public_source_capture_pin.capture.origin;
    controls.append(action('Open Discovery source',()=>document.dispatchEvent(new CustomEvent('open-discovery',{detail:{action:'open_observation',...origin}}))));
  }
  controls.prepend(element('span',referenceMode(item),'badge'));
  return controls;
}
