import {element,fields,table,run,UserError,dateText} from './ui.js';
import {request,readPage,encodeId,caption,options,relationships} from './attribution_api.js';
import {openAttribution} from './attribution_summary.js';

export async function addCaseAttribution(caseId,kind,id,version) {
  try{return await request(`/cases/${encodeId(caseId)}/references`,{method:'POST',body:{reference_type:kind,target_id:id,expected_version:version}});}
  catch(error){if(error.status===409)error.message=error.existingId?'This attribution reference is already in the case. Its original pin is retained.':'Attribution changed. Reload and review its current version before adding it.';throw error;}
}

export function caseAttribution(caseId) {
  const host=element('section',undefined,'panel');host.id='case-attribution';
  const status=element('p',undefined,'operation-status');status.setAttribute('role','status');
  const list=element('div'),picker=element('section');picker.id='case-attribution-picker';picker.hidden=true;
  let selected=null;
  const perform=op=>run(host,op,'Loading local case attribution…');
  function button(label,op){const b=element('button',label,'secondary');b.type='button';b.addEventListener('click',()=>perform(op));return b;}
  function paging(page,load){const bar=element('div',undefined,'toolbar');const prev=button('Previous',()=>load(Math.max(0,page.offset-page.limit))),next=button('Next',()=>load(page.next_offset));prev.disabled=page.offset===0;next.disabled=page.next_offset===null;bar.append(prev,element('span',`${page.total} records`),next);return bar;}
  host.append(element('h2','Attribution'),element('p','Only explicitly added references. Pinned assessments remain historical; current state is shown separately.','muted small'),status,
    button('Add attribution',()=>openPicker()),button('Refresh attribution',()=>load()),picker,list);
  async function load(offset=0) {
    const page=await readPage(`/cases/${encodeId(caseId)}/references`,{},offset,10);list.replaceChildren();
    for(const row of page.items){
      const pin=row.pinned,claim=pin.claim,current=row.current,counts=row.pinned_evidence_counts;
      const card=element('article',undefined,'attr-summary-card');card.dataset.referenceId=row.id;
      card.append(element('h3',claim?'Attribution claim':'Entity reference'),element('p',`${pin.entity.canonical_name} · ${caption(pin.entity.entity_type)} · ${pin.entity.archived_at?'Pinned entity archived':'Pinned entity active'}`),
        element('p',`Pinned: ${dateText(pin.captured_at)} · Entity version ${pin.entity.version}`,'small'));
      if(claim){card.append(element('p',`${claim.chain} · ${claim.subject_ref} · ${caption(claim.relationship)}`,'full-address'),
        element('p',`Pinned assessment: ${caption(claim.assessment)} · Version ${claim.version} · ${claim.needs_review?'Review required':'Reviewed'} · ${claim.archived_at?'Archived':'Active'}`),
        element('p',`Evidence active at pin: ${counts.supports} supporting / ${counts.contradicts} contradicting / ${counts.context} contextual`,'small'),
        element('p',current.claim?`Current assessment: ${caption(current.claim.assessment)} · Version ${current.claim.version} · ${current.claim.needs_review?'Review required':'Reviewed'} · ${current.claim.archived_at?'Archived':'Active'}`:'Current claim unavailable. Historical pin retained.'));
      }else card.append(element('p','Entity relevance does not assert control of any wallet in this case.','muted small'));
      card.append(element('p',current.changed?'Current attribution changed since this case pin.':'Current attribution matches the pinned version.','bounded-note'),
        element('p',current.entity?`Current entity: ${current.entity.canonical_name} · ${current.entity.archived_at?'Archived':'Active'}`:'Current entity unavailable.'),
        button('Open attribution',()=>openAttribution({action:claim?'open_claim':'open_entity',id:pin.target_id})));
      list.append(card);
    }
    if(!page.items.length)list.append(element('p','No attribution references have been added to this case.','empty'));
    list.append(paging(page,load));
  }
  async function openPicker(){
    picker.hidden=false;selected=null;picker.replaceChildren(element('h3','Choose attribution to pin'));
    const filters=element('form',undefined,'attr-form');filters.id='case-attribution-filter';
    filters.append(fields([{name:'kind',label:'Reference type',options:[['attribution_claim','Claim'],['entity','Entity']]},
      {name:'chain',label:'Claim chain',options:[['','All chains'],['bitcoin','Bitcoin'],['ethereum','Ethereum']]},
      {name:'subject_ref',label:'Claim address (requires chain)'},{name:'relationship',label:'Claim relationship',options:[['','All relationships'],...options(relationships)]},
      {name:'search',label:'Entity name contains (Entity view)'},{name:'include_archived',label:'Include archived records',type:'checkbox'}]));
    const apply=element('button','Search attribution');apply.type='submit';filters.append(apply);
    const results=element('div'),confirmation=element('div');
    picker.append(filters,results,confirmation,button('Cancel',()=>{picker.hidden=true;selected=null;}));
    async function search(offset=0){
      selected=null;confirmation.replaceChildren();const f=filters.elements;const kind=f.kind.value;
      if(kind==='attribution_claim'&&f.subject_ref.value&&!f.chain.value)throw new UserError('Choose a chain for the claim address filter.');
      const query=kind==='entity'?{search:f.search.value,include_archived:f.include_archived.checked}:{chain:f.chain.value,subject_ref:f.subject_ref.value,relationship:f.relationship.value,include_archived:f.include_archived.checked};
      const page=await readPage(kind==='entity'?'/entities':'/claims',query,offset,10);
      const names=kind==='entity'?new Map():new Map(await Promise.all([...new Set(page.items.map(r=>r.entity_id))].map(async id=>[id,await request(`/entities/${encodeId(id)}`)])));
      results.replaceChildren(table(['Reference','Description','Version',''],page.items.map(row=>[row.id,kind==='entity'?`${row.canonical_name} · ${caption(row.entity_type)}`:`${row.chain} ${row.subject_ref} · ${caption(row.relationship)} · ${names.get(row.entity_id).canonical_name} · ${caption(row.assessment)}`,row.version,
        button('Choose reference',()=>{selected={kind,row};confirmation.replaceChildren(element('p',`Pin ${kind}: ${row.id}, version ${row.version}. Existing case pins are retained.`),button('Confirm add attribution',async()=>{
          if(!selected)throw new UserError('Choose a reference first.');await addCaseAttribution(caseId,selected.kind,selected.row.id,selected.row.version);picker.hidden=true;selected=null;await load();
        }));})]),'No matching attribution records.'),paging(page,search));
    }
    filters.addEventListener('submit',event=>{event.preventDefault();perform(()=>search());});await search();
  }
  // Independent read failure must not hide notes, reports or other case material.
  perform(()=>load());return host;
}
