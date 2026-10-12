import {supportedChain, addressKey} from './chains.js';
import {element} from './ui.js';
import {request, readPage, encodeId, caption} from './attribution_api.js';

export function openAttribution(context) {
  document.dispatchEvent(new CustomEvent('open-attribution',{detail:context}));
}
export function refreshAttribution(scope) {
  scope.querySelectorAll('[data-attribution-summary]').forEach(node=>node.dispatchEvent(new Event('refresh-summary')));
}
export const assessmentText = claim => `${caption(claim.assessment)}${claim.needs_review?' · Review required':''}`;
export const evidenceText = claim => {
  const counts=claim.active_evidence_counts;
  return `${counts.supports} supporting / ${counts.contradicts} contradicting / ${counts.context} contextual`;
};
export const contradictionText = claim => claim.active_evidence_counts.contradicts>0
  ? `${claim.active_evidence_counts.contradicts} active contradiction(s) remain for review, regardless of the last assessment.` : '';
export const currentOverlayClaim = claim => !claim.archived_at&&!claim.entity_archived&&!claim.entity.archived_at&&!claim.needs_review&&['possible','supported','strongly_supported'].includes(claim.assessment);

// A guard, not a competing address validator/normalizer. AT-1 validates all queries.
// Existing graph keys fold case; never join a BTC Base58 spelling to its case sibling.
export function graphSubjectIsUnambiguous(graph,node) {
  if(!supportedChain(node.chain))return false;
  if(addressKey(node.chain,node.id)===addressKey(node.chain,node.id.toUpperCase()))return true;
  const addresses=[...graph.nodes.filter(n=>n.chain===node.chain).map(n=>n.id),...graph.edges.flatMap(edge=>[edge.source,edge.target])];
  return !addresses.some(address=>address&&address!==node.id&&address.toLowerCase()===node.id.toLowerCase());
}

export function attributionSummary({chain,address,graph=false,onPage=()=>{}}) {
  const host=element('section',undefined,'attribution-summary');host.dataset.attributionSummary='true';
  host.append(element('h3','Attribution'),element('p','Persisted analyst claims, separate from labels and risk. Evidence counts are context, not votes.','muted small'));
  const controls=element('div',undefined,'toolbar'),status=element('p',undefined,'operation-status'),list=element('div'),paging=element('div',undefined,'toolbar');
  status.setAttribute('role','status');
  let offset=0, generation=0;
  const btn=(text,fn)=>{const b=element('button',text,'secondary');b.type='button';b.addEventListener('click',fn);return b;};
  const showOther=element('input');showOther.type='checkbox';
  const label=element('label',undefined,'attr-check');label.append(showOther,element('span','Include archived and rejected claims'));
  controls.append(btn('Create attribution claim',()=>openAttribution({action:'create_claim',subject_type:'wallet',chain,address})),
    btn('Refresh attribution',()=>load()),label);
  host.append(controls,status,list,paging);
  showOther.addEventListener('change',()=>{offset=0;load();});
  host.addEventListener('refresh-summary',()=>load());
  async function load() {
    const token=++generation;host.dataset.busy='true';status.textContent='Loading local attribution…';status.className='operation-status';
    list.replaceChildren();paging.replaceChildren();onPage([]); // Stale positive overlays disappear during refresh/failure.
    try {
      const page=await readPage('/claims',{chain,subject_ref:address,include_archived:showOther.checked},offset,10);
      const rows=await Promise.all(page.items.map(item=>request(`/claims/${encodeId(item.id)}`)));
      if(token!==generation)return;
      const visible=showOther.checked?rows:rows.filter(row=>row.assessment!=='rejected'&&!row.archived_at&&!row.entity_archived);
      if(!visible.length)list.append(element('p',page.total? 'No active non-rejected claims on this page. Other claims remain available through the filter and pagination.':
        graph?'No attribution claims recorded.':'No attribution claims have been recorded for this wallet.','empty'));
      for(const row of visible) {
        const card=element('article',undefined,'attr-summary-card');card.dataset.claimId=row.id;
        card.append(element('strong',`Claimed entity: ${row.entity.canonical_name}`),element('p',`Entity type: ${caption(row.entity.entity_type)} · Claimed relationship: ${caption(row.relationship)}`,'small'),
          element('p',`Last assessment: ${assessmentText(row)}`,'small'),element('p',evidenceText(row),'small'),
          element('p',row.archived_at?'Claim archived':row.entity_archived?'Entity archived':row.assessment==='rejected'?'Rejected claim — not an active positive attribution':'Active claim','muted small'),
          btn('Open attribution',()=>openAttribution({action:'open_claim',id:row.id})));
        if(contradictionText(row))card.append(element('p',contradictionText(row),'bounded-note'));
        list.append(card);
      }
      const prev=btn('Previous claims',()=>{offset=Math.max(0,page.offset-page.limit);load();});prev.disabled=page.offset===0;
      const next=btn('Next claims',()=>{offset=page.next_offset;load();});next.disabled=page.next_offset===null;
      paging.append(prev,element('span',`${page.total} stored matching claims · page ${Math.floor(page.offset/page.limit)+1}. Rejected claims may be hidden on this page.`,'small'),next);
      status.textContent='Local attribution loaded.';onPage(visible);
    } catch(error) {
      if(token!==generation)return;
      status.textContent=error.status?error.message:'Attribution could not be loaded. Refresh this section to retry.';status.className='operation-status error';
    } finally {if(token===generation)host.dataset.busy='false';}
  }
  // Start a local read only; failure never propagates to wallet/graph rendering.
  load();return host;
}
