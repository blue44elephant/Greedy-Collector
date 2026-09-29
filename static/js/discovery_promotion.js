import {captureControl} from './public_source_capture.js';
import {graphSenseDetail} from './discovery_graphsense.js';
import {manualSourceDetail} from './discovery_manual_source.js';
import {element,table,details,dateText,UserError} from './ui.js';
import {discoveryRequest as request} from './discovery_api.js';

export function discoveryProvenance(snapshot) {
  const node=element('section',undefined,'attr-source-provenance');
  const o=snapshot.observation||{},s=o.source_snapshot||{};
  node.append(element('h3','Discovery observation provenance'),table(['Field','Captured value'],[
    ['Result',snapshot.discovery_result_id],['Selected observation',snapshot.discovery_observation_id],
    ['Material fingerprint',snapshot.observation_fingerprint],['Transform',snapshot.transform_id],
    ['Source',snapshot.source_id],['Predicate',snapshot.predicate],['Wallet',`${snapshot.subject?.chain} · ${snapshot.subject?.address}`],
    [o.kind==='analyst_capture'?'Captured':'Retrieved',dateText(o.kind==='analyst_capture'?o.created_at:o.retrieved_at)],['Coverage',snapshot.coverage],
  ]));
  if(s.provider==='GraphSense' && o.kind==='verified_page_observation')node.append(graphSenseDetail(s,o.retrieved_at));
  if(o.kind==='local_label_snapshot') {
    const r=s.record||{};
    node.append(table(['Underlying Label','Stored annotation'],[['Label',r.label],['Original source',r.source],['Annotation confidence',r.confidence],['Last updated',dateText(r.last_updated)]]),
      element('p','Label confidence is source annotation metadata, not Attribution confidence.','bounded-note'));
  } else if(o.kind==='search_result' && ['brave_search','tavily_search'].includes(snapshot.source_id)) {
    node.append(table(['Broad search provenance','Stored value'],[['Provider',s.provider],['Query',s.query],['URL',o.source_url],['Title',s.title],['Source category',s.source_category],['Exact wallet token present',String(s.exact_match)],['Analyst note',snapshot.analyst_review_note]]),element('blockquote',o.excerpt||o.summary),element('p','Search metadata only; GC did not fetch this source or verify its statements.'));
  } else if(o.kind==='analyst_capture' && snapshot.source_id==='manual_source') {
    node.append(manualSourceDetail(s,o.created_at));
  } else if(o.kind==='name_service_record' && snapshot.source_id==='ens_ethereum') {
    node.append(table(['ENS provenance','Observed value'],[
      ['ENS primary name',s.primary_name],['Namespace',s.namespace],['Wallet',s.wallet],
      ['Verification',s.verification==='forward_verified'?'Forward verified':'Not verified'],
      ['Verification method',s.verification_method],['Universal Resolver',s.universal_resolver],
      ['Resolver',s.resolver],['Reverse resolver',s.reverse_resolver],['Provider',s.provider],
    ]),element('p','At observation time, ENS primary-name resolution returned this name and verified its address relationship. This technical naming relationship does not establish real-world identity or wallet control.','bounded-note'));
  } else {
    node.append(table(['GitHub provenance','Stored value'],[['Repository',s.repository_full_name],['File',s.file_path||s.path],['Blob SHA',s.blob_sha],['GitHub URL',o.source_url],['GitHub search score',s.github_search_score??'Not recorded']]),
      element('h4','Matched code context'),element('blockquote',o.excerpt||o.summary),
      element('p','Code mention does not establish repository owner control of the wallet. Search score is provider metadata.','bounded-note'));
  }
  return node;
}

// Reads only on selected observation detail. No per-result-list promotion fan-out.
export async function promotionDetail(parent,observation) {
  if(observation.kind==='search_result')parent.append(captureControl(observation));
  const host=element('section',undefined,'panel');host.id='discovery-promotion';parent.append(host);
  const status=element('p');host.append(element('h3','Attribution promotion'),status);
  try {
    const preview=await request(`/observations/${encodeURIComponent(observation.id)}/promotion-preview`);
    if(!host.isConnected)return;
    status.textContent=preview.eligible?'Selected material has a Relevant review. Promotion remains a separate analyst action.':
      preview.reason==='review_required'?'Review this selected material as Relevant before promotion.':'This source observation is not promotable.';
    host.append(element('p',`Selected observation: ${observation.id}`,'small full-address'));
    if(preview.eligible) {
      const action=element('button','Use as attribution evidence','secondary');action.type='button';
      action.addEventListener('click',()=>{
        if(!host.isConnected)return;
        document.dispatchEvent(new CustomEvent('open-attribution',{detail:{action:'source_evidence',source_kind:'discovery',source_id:observation.id}}));
      });host.append(action);
    }
    const history=element('div');host.append(history);
    const load=async(offset=0)=>{
      const page=await request(`/results/${encodeURIComponent(observation.result_id)}/promotions?limit=10&offset=${offset}`);
      if(!host.isConnected)return;
      history.replaceChildren(element('p',`Promoted: ${page.total} · separate from relevance review`),table(['Claim','Observation','When','Current link','Evidence / link',''],page.items.map(row=>{
        const open=element('button','Open attribution','secondary');open.type='button';
        open.addEventListener('click',()=>document.dispatchEvent(new CustomEvent('open-attribution',{detail:{action:'open_claim',id:row.claim_id}})));
        return [row.claim_id,row.observation_id,dateText(row.created_at),`${row.stance} · ${row.directness} · ${row.withdrawn_at?'Withdrawn':'Active'}`,`${row.evidence_id} / ${row.link_id}`,open];
      }),'No observations from this result have been promoted.'));
      for(const [label,next] of [['Previous promotions',offset>0?Math.max(0,offset-10):null],['Next promotions',page.next_offset]]) {
        if(next===null)continue;const button=element('button',label,'secondary');button.type='button';
        button.addEventListener('click',async()=>{button.disabled=true;try{await load(next);}catch(e){status.textContent=e instanceof UserError?e.message:'Promotion history could not be loaded.';}finally{button.disabled=false;}});history.append(button);
      }
    };await load();
  } catch(e) {status.textContent=e instanceof UserError?e.message:'Promotion information could not be loaded.';}
}
