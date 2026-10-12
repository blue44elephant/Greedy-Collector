import {captureProvenance} from './public_source_capture.js';
import {chains as chainChoices, supportedChain} from './chains.js';
import {discoveryRequest} from './discovery_api.js';
import {discoveryProvenance} from './discovery_promotion.js';
import {element, fields, table, details, dateText, run, UserError} from './ui.js';
import {request, readPage, encodeId, caption, options, relationships} from './attribution_api.js';
import {linkFields, linkData, qualityFields, qualityData} from './attribution_forms.js';

export function evidenceHandoffButton(kind,id) {
  const button=element('button','Use as attribution evidence','secondary');button.type='button';
  button.addEventListener('click',()=>document.dispatchEvent(new CustomEvent('open-attribution',{
    detail:{action:'source_evidence',source_kind:kind,source_id:id}
  })));return button;
}

export function snapshotProvenance(snapshot) {
  if(snapshot.source_subsystem==='Greedy Collector Public Source Capture')return captureProvenance(snapshot);
  if(snapshot.source_subsystem==='Greedy Collector Discovery')return discoveryProvenance(snapshot);
  const node=element('section',undefined,'attr-source-provenance'),row=snapshot.record||{};
  node.append(element('h3',snapshot.source_subsystem||'Source snapshot'));
  const pairs=snapshot.source_subsystem==='Greedy Collector Label'
    ? [['Original label source',row.source],['Label',row.label],['Chain',row.chain],['Address',row.address],['Label type',row.type],['Annotation confidence',row.confidence],['Last updated',dateText(row.last_updated)]]
    : [['Provider',row.source],['Subject',row.subject_name],['Match score (source similarity)',row.match_score],['Research review status',row.review_status],['Source URL',row.source_url||'Not available'],['Research run time',dateText(snapshot.run?.created_at)]];
  for(const [label,value] of pairs)node.append(element('p',`${label}: ${value??'Not recorded'}`,'small full-address'));
  node.append(element('p','Source scores and review status are metadata, not attribution assessment. Confirmed source match does not confirm wallet attribution.','bounded-note'));
  return node;
}

export function initEvidenceHandoff(parent,{createClaim,openClaim}) {
  const host=element('section',undefined,'panel');host.id='attr-source-handoff';host.hidden=true;parent.append(host);
  let source=null,preview=null,target=null,awaitingClaim=false,promotionConsent=null;
  const status=element('p',undefined,'operation-status');status.setAttribute('role','status');
  const sourceView=element('div'),list=element('div'),chosen=element('div'),success=element('div');
  const filters=element('form',undefined,'attr-form');filters.id='attr-handoff-filter';
  filters.append(fields([
    {name:'chain',label:'Claim chain',options:[['','All chains'],...chainChoices]},
    {name:'subject_ref',label:'Claim wallet address (select chain)',maxLength:128},
    {name:'relationship',label:'Claim relationship',options:[['','All relationships'],...options(relationships)]},
  ]));
  const apply=element('button','Filter claims');apply.type='submit';filters.append(apply);
  const form=element('form',undefined,'attr-form');form.id='attr-handoff-confirm';
  form.append(fields([...linkFields(),...qualityFields(),{name:'confirmed',label:'I reviewed the source snapshot and selected claim',type:'checkbox',required:true}]));
  const capture=element('button','Confirm capture');capture.type='submit';form.append(capture);form.hidden=true;
  const perform=op=>run(host,op,'Reading or capturing local evidence…');
  function button(label,op) {const b=element('button',label,'secondary');b.type='button';b.addEventListener('click',()=>perform(op));return b;}
  const create=button('Create attribution claim',async()=>{
    if(!preview)throw new UserError('Load and review the stored source snapshot first.');
    awaitingClaim=true;target=null;form.hidden=true;chosen.replaceChildren();
    const row=preview.snapshot.record;
    if(['discovery','public_capture'].includes(source.kind)){await createClaim({chain:preview.chain,address:preview.address});return;}
    await createClaim(source.kind==='label'&&supportedChain(row.chain)?{chain:row.chain,address:row.address}:null);
  });
  host.append(element('h2','Use as attribution evidence'),status,sourceView,
    button('Reload source snapshot',async()=>{await loadSource();target=null;form.hidden=true;chosen.replaceChildren();}),
    create,button('Back to Discovery',()=>{if(['discovery','public_capture'].includes(source?.kind))document.dispatchEvent(new CustomEvent('return-discovery-promotion'));}),button('Cancel handoff',()=>{source=null;preview=null;target=null;awaitingClaim=false;host.hidden=true;}),
    filters,list,chosen,form,success);
  async function loadSource() {
    if(['discovery','public_capture'].includes(source.kind)) {
      preview=await discoveryRequest(`/${source.kind==='public_capture'?'public-captures':'observations'}/${encodeId(source.id)}/promotion-preview`);
      if(!preview.eligible)throw new UserError('Review the selected material as Relevant before promotion.');
      preview.snapshot=source.kind==='public_capture'?{...preview.snapshot,selected_excerpt:source.excerpt}:preview.evidence.metadata_json;
      filters.elements.chain.value=preview.chain;filters.elements.subject_ref.value=preview.address;
    } else preview=await request(`/evidence/sources/${source.kind}/${encodeId(source.id)}`);
    sourceView.replaceChildren(snapshotProvenance(preview.snapshot),details('Snapshot to capture',preview.snapshot),
      element('p','Confirming captures this stored version. If the source changes before capture, reload and review it again.','muted small'));
  }
  async function loadClaims(offset=0) {
    const values=Object.fromEntries([...filters.elements].filter(n=>n.name).map(n=>[n.name,n.value]));
    if(values.subject_ref&&!values.chain)throw new UserError('Select the claim chain when filtering by address.');
    const page=await readPage('/claims',values,offset,10);
    const entities=new Map(await Promise.all([...new Set(page.items.map(row=>row.entity_id))].map(async id=>[id,await request(`/entities/${encodeId(id)}`)])));
    list.replaceChildren(table(['Wallet','Chain','Relationship','Claimed entity','Last assessment',''],page.items.map(row=>[
      row.subject_ref,caption(row.chain),caption(row.relationship),entities.get(row.entity_id).canonical_name,
      `${caption(row.assessment)}${row.needs_review?' · Review required':''}`,button('Choose claim',()=>chooseClaim(row.id))
    ]),'No claims match. Create a claim explicitly or change the filters.'));
    const prev=button('Previous claims',()=>loadClaims(Math.max(0,page.offset-page.limit))),next=button('Next claims',()=>loadClaims(page.next_offset));
    prev.disabled=page.offset===0;next.disabled=page.next_offset===null;
    list.append(prev,element('span',`${page.total} matching claims · page ${Math.floor(page.offset/page.limit)+1}`,'small'),next);
  }
  async function chooseClaim(id) {
    success.replaceChildren();
    const keepChoices=awaitingClaim&&['discovery','public_capture'].includes(source?.kind);
    target=await request(`/claims/${encodeId(id)}`);awaitingClaim=false;
    chosen.replaceChildren(element('h3','Selected claim'),element('p',`${target.chain} · ${target.subject_ref} · ${caption(target.relationship)} · ${target.entity.canonical_name}`,'full-address'),
      element('p',`Claim ID: ${target.id} · Version ${target.version}`,'small'));
    if(!keepChoices)form.reset();promotionConsent=null;capture.hidden=['discovery','public_capture'].includes(source.kind);promotionPreview.hidden=!['discovery','public_capture'].includes(source.kind);form.hidden=false;form.scrollIntoView({block:'center'});
  }
  const promotionPreview=button('Preview promotion',async()=>{
    // run() disables controls while the request is pending; FormData omits
    // disabled controls. Read the explicit choices directly before validating.
    const choices={stance:form.elements.stance.value,directness:form.elements.directness.value,
      rationale:form.elements.rationale.value,confirmed:form.elements.confirmed.checked?'on':undefined,
      ...qualityData({source_reliability:form.elements.source_reliability.value,reliability_rationale:form.elements.reliability_rationale.value})};
    if(!target||!choices.stance||!choices.directness||!choices.rationale.trim()||!choices.confirmed)throw new UserError('Choose a claim, stance and directness, enter a rationale, and confirm review.');
    await loadSource();
    if(target.chain!==preview.chain||target.subject_ref!==preview.address)throw new UserError('Select a claim for this exact wallet and chain.');
    if(preview.context_only&&(form.elements.stance.value!=='context'||form.elements.directness.value!=='context'))throw new UserError('This material can only provide Context with context directness.');
    promotionConsent={...choices,claim_id:target.id,expected_claim_version:target.version,source_fingerprint:preview.source_fingerprint};
    sourceView.append(element('p',`Ready to promote selected observation ${source.id} to claim ${target.id}, version ${target.version}. Stance: ${promotionConsent.stance}; directness: ${promotionConsent.directness}.`,'bounded-note'));
    capture.hidden=false;
  });promotionPreview.hidden=true;form.append(promotionPreview);
  form.addEventListener('input',()=>{if(['discovery','public_capture'].includes(source?.kind)){promotionConsent=null;capture.hidden=true;}});
  filters.addEventListener('submit',event=>{event.preventDefault();perform(()=>loadClaims());});
  form.addEventListener('submit',event=>{
    event.preventDefault();const data=Object.fromEntries(new FormData(form));
    perform(async()=>{
      if(!target||!preview||!data.confirmed||!data.stance||!data.directness||!data.rationale.trim())throw new UserError('Choose a claim, stance and directness, enter a rationale, and confirm review.');
      if(['discovery','public_capture'].includes(source.kind)) {
        if(!promotionConsent||promotionConsent.claim_id!==target.id||['stance','directness','rationale','confirmed','source_reliability','reliability_rationale'].some(k=>promotionConsent[k]!==data[k]))throw new UserError('Preview the selected promotion before confirming.');
        const body={claim_id:target.id,expected_claim_version:target.version,expected_source_fingerprint:promotionConsent.source_fingerprint,link:linkData(data),...qualityData(data),...(source.kind==='public_capture'?{confirmed:true,excerpt:source.excerpt}:{result_id:preview.result_id})};
        const saved=await discoveryRequest(`/${source.kind==='public_capture'?'public-captures':'observations'}/${encodeId(source.id)}/promote`,{body});
        target=null;promotionConsent=null;form.hidden=true;
        success.replaceChildren(element('p','Promoted to immutable evidence. Relevance remains separate; claim assessment was not changed and requires review.'),
          button('Open attribution',async()=>{host.hidden=true;source=null;await openClaim(saved.claim.id);}));return;
      }
      const saved=await request(`/claims/${encodeId(target.id)}/evidence/from-${source.kind}/${encodeId(source.id)}`,{method:'POST',body:{
        expected_version:target.version,expected_source_fingerprint:preview.source_fingerprint,link:linkData(data),...qualityData(data)
      }});
      target=null;form.hidden=true;success.replaceChildren(element('p','Immutable evidence captured and linked. The claim requires review; its assessment was not changed.'),
        button('Open attribution',async()=>{host.hidden=true;source=null;await openClaim(saved.claim.id);}));
    });
  });
  return {
    async open(context) {
      if(!['label','research','discovery','public_capture'].includes(context.source_kind)||typeof context.source_id!=='string')return;
      source={kind:context.source_kind,id:context.source_id,excerpt:context.excerpt};preview=null;target=null;awaitingClaim=false;
      host.hidden=false;form.hidden=true;sourceView.replaceChildren();list.replaceChildren();chosen.replaceChildren();success.replaceChildren();filters.reset();status.textContent='';
      // Called inside Attribution's existing operation boundary, never nested run().
      capture.textContent=['discovery','public_capture'].includes(source.kind)?'Confirm promotion':'Confirm capture';
      [...host.querySelectorAll('button')].find(b=>b.textContent==='Back to Discovery').hidden=!['discovery','public_capture'].includes(source.kind);
      promotionConsent=null;promotionPreview.hidden=true;await loadSource();await loadClaims();host.scrollIntoView({block:'start'});
    },
    async claimCreated(id){if(source&&awaitingClaim)await chooseClaim(id);}
  };
}
