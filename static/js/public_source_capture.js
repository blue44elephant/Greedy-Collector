import {element,table,fields,dateText,run,UserError} from './ui.js';
import {discoveryRequest as request} from './discovery_api.js';
import {listCases} from './case_actions.js';
const encode=encodeURIComponent;
export const captureFailure=code=>({
  dns_failure:'The public hostname could not be resolved.',blocked_private_address:'Capture blocked: local, private, reserved or disallowed network destination.',
  blocked_scheme:'Capture accepts ordinary HTTP and HTTPS URLs only.',blocked_onion:'Onion capture is not supported. Use Manual Source Observation for an inert reference.',
  redirect_blocked:'Capture blocked an unsafe redirect destination.',too_many_redirects:'Capture stopped at the five-redirect limit.',
  timeout:'Capture exceeded its bounded retrieval time.',response_too_large:'The source exceeded the 5 MiB limit. No complete body was preserved.',
  unsupported_content_type:'Only uncompressed HTML and plain text are supported.',authentication_required:'The source requires authentication or contains credentials. No login or cookies were used.',
  rate_limited:'The source rate limited this request. No automatic retry was made.',http_error:'The source returned an unsuccessful HTTP status.',
  invalid_response:'The source returned an invalid response.',network_error:'The public source request could not be completed.'
}[code]||'Capture could not be completed.');
export function captureFacts(c){return [
  ['Capture',c.id],['Capture status',c.status],['Requested URL',c.requested_url],['Final URL',c.final_url||'Not retrieved'],
  ['Retrieved',dateText(c.retrieved_at)],['HTTP status',c.http_status??'Not received'],['Content type',c.content_type??'Not received'],
  ['Captured bytes',c.byte_count],['SHA-256',c.body_sha256||'No complete body hash'],
  ['Wallet string found',c.wallet_present_in_capture===true?'Yes':c.wallet_present_in_capture===false?'No':'Not evaluated'],
  ['Changed since previous capture',({CHANGED:'CHANGED',UNCHANGED:'UNCHANGED',FIRST_CAPTURE:'First capture',NOT_COMPARED:'Not compared'})[c.change_state]||'Not compared'],
  ['Original provider',c.origin?.provider],['Original observation',c.origin?.observation_id],
  ['Original result',c.origin?.result_id],['Original run',c.origin?.run_id],
  ['Chain',c.origin?.chain],['Wallet',c.origin?.wallet]
];}
export function captureProvenance(snapshot){
  const host=element('section');host.append(element('h3','Public source capture provenance'),table(['Field','Captured value'],captureFacts(snapshot.capture)),element('p',`Review: ${snapshot.review?.status} | ${snapshot.review?.note||''}`),element('blockquote',snapshot.selected_excerpt||''),element('p','Captured public text is source material, not proof of ownership.'));
  return host;
}
export function capturePinCard(snapshot){const host=element('details');host.append(element('summary','Pinned public source capture'),captureProvenance(snapshot));return host;}
export function captureControl(observation){
  const host=element('section',undefined,'panel public-source-capture'),view=element('div'),history=element('div');
  host.dataset.captureObservation=observation.id;
  const perform=fn=>run(host,fn,'Capturing or reading explicit public source material...');
  const button=(label,fn)=>{const b=element('button',label,'secondary');b.type='button';b.addEventListener('click',()=>perform(fn));return b;};
  const execute=async()=>{
    const c=await request(`/observations/${encode(observation.id)}/public-captures`,{body:{confirmed:true}});
    if(host.isConnected)draw(c);
  };
  const confirm=()=>{
    view.replaceChildren(element('p','Retrieve this selected public URL once? GC sends an identifiable request, validates DNS and redirects, stores an immutable bounded capture, and fetches no linked resources. Public access does not grant redistribution rights.'),element('p',observation.source_url),button('Confirm public source capture',execute),button('Cancel capture',()=>view.replaceChildren()));
  };
  host.append(button('Capture Public Source',confirm),button('View captures',()=>loadHistory(0)),view,history);
  async function loadHistory(offset){
    const page=await request(`/observations/${encode(observation.id)}/public-captures?limit=10&offset=${offset}`);
    history.replaceChildren(element('h3',`${page.total} public source captures`),table(['Captured','Status','Change',''],page.items.map(c=>[dateText(c.retrieved_at),c.status,c.change_state,button('Review capture',async()=>draw(await request(`/public-captures/${encode(c.id)}`)))]),'No public source capture yet.'));
    if(offset>0)history.append(button('Previous captures',()=>loadHistory(Math.max(0,offset-10))));
    if(page.next_offset!==null)history.append(button('Next captures',()=>loadHistory(page.next_offset)));
  }
  function draw(c){
    view.replaceChildren(element('h3','Public source capture'),table(['Field','Captured value'],captureFacts(c)));
    view.dataset.captureId=c.id;view.dataset.captureStatus=c.status;
    if(c.status!=='captured')view.append(element('p',captureFailure(c.failure_reason),'bounded-note'));
    if(c.wallet_present_in_capture===false)view.append(element('p','The current page did not contain the canonical wallet in captured readable text. The capture is retained; this does not disprove an earlier mention.'));
    view.append(element('p','Search metadata and this retrieved source remain separate records. Wallet presence does not establish ownership.'));
    const readable=element('details');readable.append(element('summary','Readable captured text'),element('pre',c.text||'No readable text captured.'));view.append(readable);
    const review=element('form',undefined,'editor');review.classList.add('capture-review');
    review.append(fields([{name:'status',label:'Capture review',options:[['unreviewed','Unreviewed'],['relevant','Relevant'],['irrelevant','Irrelevant']],value:c.review.status},{name:'note',label:'Analyst note',value:c.review.note,required:true,maxLength:2000}]));
    const save=element('button','Save capture review');save.type='submit';review.append(save);
    review.addEventListener('submit',e=>{e.preventDefault();const body={status:review.elements.status.value,note:review.elements.note.value,expected_version:c.review.sequence};perform(async()=>draw(await request(`/public-captures/${encode(c.id)}/review`,{body})));});view.append(review);
    if(c.status==='captured'){
      const label=element('label','Relevant excerpt (copy literal text from this capture)'),excerpt=element('textarea');excerpt.name='capture_excerpt';excerpt.maxLength=8000;excerpt.rows=4;label.append(excerpt);view.append(label);
      const selection=()=>{if(!excerpt.value.trim()||!c.text.includes(excerpt.value))throw new UserError('Enter a literal relevant excerpt from the captured text (up to 8,000 characters).');return excerpt.value;};
      view.append(button('Promote as evidence',async()=>{
        const text=selection(),p=await request(`/public-captures/${encode(c.id)}/promotion-preview`);
        if(!p.eligible)throw new UserError('Review this successful capture as Relevant first.');
        document.dispatchEvent(new CustomEvent('open-attribution',{detail:{action:'source_evidence',source_kind:'public_capture',source_id:c.id,excerpt:text}}));
      }),button('Pin capture to Case',async()=>{
        const text=selection(),cases=await listCases(),target=element('form',undefined,'editor');target.classList.add('capture-case-pin');
        if(!cases.length)throw new UserError('Create a Case first.');
        target.append(fields([{name:'case_id',label:'Case',options:cases.map(row=>[row.id,row.title])}]));
        const commit=element('button','Confirm capture pin');commit.type='submit';target.append(commit);view.append(target);
        target.addEventListener('submit',e=>{e.preventDefault();const id=target.elements.case_id.value;perform(async()=>{const p=await request(`/public-captures/${encode(c.id)}/promotion-preview`);await request(`/public-captures/${encode(c.id)}/cases/${encode(id)}/pin`,{body:{excerpt:text,expected_source_fingerprint:p.source_fingerprint}});target.replaceChildren(element('p','Historical public source capture pinned.'));});});
      }));
    }
    view.append(button('Capture again',confirm));
  }
  return host;
}
