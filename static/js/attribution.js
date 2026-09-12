import {ApiError} from './api.js';
import {byId, element, panel, table, fields, shortValue, dateText, details, run, UserError} from './ui.js';
import {request, readPage, encodeId, caption, options, assessments, relationships, entityTypes, stances, origins} from './attribution_api.js';
import {reasonField, descriptorFields, descriptor, claimFields, scopeFields, scopeData, linkFields, linkData, captureFields, advancedCapture, captureData} from './attribution_forms.js';

export function initAttribution() {
  const host=byId('attribution-workspace');
  let loaded=false, view='claims', selectedClaim=null, selectedEntity=null, claimOffset=0, entityOffset=0;
  let targetEntity=null, filterEntity=null, pendingSubject=null;
  const top=element('div',undefined,'workspace-heading');top.append(element('h1','Attribution'));
  const status=element('p',undefined,'operation-status');status.setAttribute('role','status');
  const recovery=element('div',undefined,'toolbar');recovery.id='attr-recovery';
  const tabs=element('div',undefined,'toolbar');tabs.setAttribute('aria-label','Attribution views');
  const claimsView=element('div');claimsView.id='attr-claims-view';
  const entitiesView=element('div');entitiesView.id='attr-entities-view';entitiesView.hidden=true;
  const claimList=panel('Claims');claimList.id='attr-claims-list';
  const entityList=panel('Entities');entityList.id='attr-entities-list';
  const claimDetail=panel('Claim detail');claimDetail.id='attr-claim-detail';claimDetail.hidden=true;
  const entityDetail=panel('Entity detail');entityDetail.id='attr-entity-detail';entityDetail.hidden=true;
  const claimEditor=panel('Create claim');claimEditor.id='attr-claim-editor';claimEditor.hidden=true;
  const entityEditor=panel('Create entity');entityEditor.id='attr-entity-editor';entityEditor.hidden=true;
  const picker=element('dialog');picker.id='attr-picker';
  host.append(top,element('p','Evidence-backed entity claims','intro'),status,recovery,
    element('p','Attribution is evidence-backed analyst assessment. Claims and strongly supported assessments are not legal proof. Public wallet addresses only; never enter private keys or recovery phrases.','bounded-note'),
    tabs,claimsView,entitiesView,picker);
  top.append(button('Reload',reload));
  const claimsTab=button('Claims',()=>switchView('claims')), entitiesTab=button('Entities',()=>switchView('entities'));
  claimsTab.setAttribute('aria-pressed','true');entitiesTab.setAttribute('aria-pressed','false');tabs.append(claimsTab,entitiesTab);

  function perform(operation) {
    return run(host,async()=>{
      recovery.replaceChildren();
      try {await operation();}
      catch(error) {
        recovery.append(button('Reload',reload));
        if(error.duplicateClaim && error.existingId) recovery.append(button('Open existing claim',async()=>{
          await switchView('claims');await showClaim(error.existingId);
        }));
        throw error;
      }
    },'Loading or saving local attribution records…');
  }
  function button(label, operation) {
    const node=element('button',label,'secondary');node.type='button';node.addEventListener('click',()=>perform(operation));return node;
  }
  function form(id, definitions, label, operation) {
    const node=element('form',undefined,'attr-form');node.id=id;node.append(fields(definitions));
    const submit=element('button',label);submit.type='submit';node.append(submit);
    node.addEventListener('submit',event=>{event.preventDefault();const data=Object.fromEntries(new FormData(node));perform(()=>operation(data,node));});
    return node;
  }
  function pager(page, load) {
    const bar=element('div',undefined,'toolbar attr-pagination');
    const prev=button('Previous',()=>load(Math.max(0,page.offset-page.limit)));
    const next=button('Next',()=>load(page.next_offset));prev.disabled=page.offset===0;next.disabled=page.next_offset===null;
    bar.append(prev,element('span',`${page.total} records · ${page.items.length ? page.offset+1 : 0}–${page.offset+page.items.length}`,'small'),next);return bar;
  }
  function metadata(pairs) {
    const dl=element('dl',undefined,'metadata');
    for(const [key,value] of pairs) {const part=element('div'),dd=element('dd');dd.append(value instanceof Node ? value : element('span',value));part.append(element('dt',key),dd);dl.append(part);}
    return dl;
  }
  function safeSource(url) {
    try {
      const value=new URL(url);
      if(!['http:','https:'].includes(value.protocol)||value.username||value.password)throw Error();
      const keys=[...value.searchParams.keys(),...new URLSearchParams(value.hash.slice(1)).keys()];
      if(keys.some(key=>/^(?:key|api_?key|token|access_?token|password|secret|authorization|signature)$/i.test(key)))throw Error();
      const link=element('a','Open source');link.href=value.href;link.target='_blank';link.rel='noopener noreferrer';link.referrerPolicy='no-referrer';return link;
    } catch {return element('span','No public source link','muted small');}
  }
  function reveal(node) {node.hidden=false;node.scrollIntoView({block:'start'});}
  async function switchView(next) {
    view=next;claimsView.hidden=next!=='claims';entitiesView.hidden=next!=='entities';
    claimsTab.setAttribute('aria-pressed',String(next==='claims'));entitiesTab.setAttribute('aria-pressed',String(next==='entities'));
    if(next==='claims')await loadClaims();else await loadEntities();
  }
  async function reload() {
    picker.close();claimEditor.hidden=true;entityEditor.hidden=true;
    if(view==='claims') {await loadClaims();if(selectedClaim)await showClaim(selectedClaim);}
    else {await loadEntities();if(selectedEntity)await showEntity(selectedEntity);}
  }

  const claimFilters=panel('Filter claims');
  const filterTarget=element('p','All entities','muted small');
  const cf=form('attr-claim-filters',[
    {name:'chain',label:'Chain',options:[['','All chains'],['bitcoin','Bitcoin'],['ethereum','Ethereum']]},
    {name:'subject_ref',label:'Subject address (select its chain)',maxLength:128},
    {name:'relationship',label:'Relationship',options:[['','All relationships'],...options(relationships)]},
    {name:'assessment',label:'Assessment',options:[['','All assessments'],...options(assessments)]},
    {name:'include_archived',label:'Include archived claims/entities',type:'checkbox'},
  ],'Apply claim filters',async()=>{claimOffset=0;await loadClaims();});
  claimFilters.append(cf,filterTarget,button('Filter by entity',()=>chooseEntity(row=>{filterEntity=row;filterTarget.textContent=row.canonical_name;claimOffset=0;return loadClaims();})),
    button('Clear entity filter',async()=>{filterEntity=null;filterTarget.textContent='All entities';claimOffset=0;await loadClaims();}));
  claimsView.append(button('Create claim',()=>openClaimEditor()),claimEditor,claimFilters,claimList,claimDetail);
  const ef=form('attr-entity-filters',[
    {name:'search',label:'Canonical name contains',maxLength:255},
    {name:'entity_type',label:'Entity type',options:[['','All types'],...options(entityTypes)]},
    {name:'include_archived',label:'Include archived entities',type:'checkbox'},
  ],'Apply entity filters',async()=>{entityOffset=0;await loadEntities();});
  const entityFilters=panel('Filter entities');entityFilters.append(ef);
  entitiesView.append(button('Create entity',()=>openEntityEditor()),entityEditor,entityFilters,entityList,entityDetail);
  function filterValues(node) {
    // run() temporarily disables controls; read their values, not successful form controls.
    return Object.fromEntries([...node.elements].filter(input=>input.name).map(input=>[input.name,input.type==='checkbox'?input.checked:input.value]));
  }
  async function loadClaims(offset=claimOffset) {
    claimOffset=offset;
    const filters={...filterValues(cf),entity_id:filterEntity?.id};
    if(filters.subject_ref&&!filters.chain)throw new UserError('Select a chain when filtering by subject address.');
    const page=await readPage('/claims',filters,offset);
    // Only fetch descriptors referenced on this bounded page, never the full entity database.
    const names=new Map(await Promise.all([...new Set(page.items.map(row=>row.entity_id))].map(async id=>[id,await request(`/entities/${encodeId(id)}`)])));
    claimList.replaceChildren(element('h2','Claims'),table(['Subject','Chain','Relationship','Attributed entity','Last assessment','Review','Archive state','Updated (UTC)',''],
      page.items.map(row=>[shortValue(row.subject_ref),caption(row.chain),caption(row.relationship),names.get(row.entity_id).canonical_name,
        caption(row.assessment),row.needs_review?'Review required':'Up to date',row.archived_at?'Claim archived':names.get(row.entity_id).archived_at?'Entity archived':'Active',
        dateText(row.updated_at),button('View claim',()=>showClaim(row.id))]),'No attribution claims have been created.'),pager(page,loadClaims));
  }
  async function loadEntities(offset=entityOffset) {
    entityOffset=offset;const page=await readPage('/entities',filterValues(ef),offset);
    entityList.replaceChildren(element('h2','Entities'),table(['Canonical name','Type','Aliases','Archive state','Version',''],page.items.map(row=>[
      row.canonical_name,caption(row.entity_type),row.aliases.join(', ')||'None',row.archived_at?'Archived':'Active',row.version,button('View entity',()=>showEntity(row.id))
    ]),'No attribution entities have been created.'),pager(page,loadEntities));
  }
  async function chooseEntity(choose) {
    picker.replaceChildren(element('h2','Choose an existing entity'),element('p','Names are not unique. Inspect the type and identifier before selecting.','muted small'));
    const list=element('div');
    const search=form('attr-picker-filter',[{name:'search',label:'Canonical name contains',maxLength:255}],'Search entities',()=>load(0));
    picker.append(search,list,button('Cancel',()=>picker.close()));
    async function load(offset) {
      const page=await readPage('/entities',{search:search.elements.search.value},offset,10);
      list.replaceChildren(table(['Entity','Type','ID',''],page.items.map(row=>[row.canonical_name,caption(row.entity_type),shortValue(row.id),
        button('Choose entity',async()=>{picker.close();await choose(row);})]),'No attribution entities have been created.'),pager(page,load));
    }
    if(!picker.open)picker.showModal();await load(0);
  }
  function openEntityEditor(row=null) {
    entityEditor.replaceChildren(element('h2',row?'Edit entity descriptor':'Create entity'),element('p','An entity is a reusable descriptor. Creating it makes no wallet claim.','muted small'));
    entityEditor.append(form('attr-entity-form',[...descriptorFields(row),...(row?[reasonField]:[])],row?'Save descriptor':'Save entity',async data=>{
      const saved=await request(row?`/entities/${encodeId(row.id)}`:'/entities',{method:row?'PATCH':'POST',body:row?
        {expected_version:row.version,reason:data.reason,descriptor:descriptor(data)}:descriptor(data)});
      entityEditor.hidden=true;await loadEntities();await showEntity(saved.id);
    }),button('Cancel',()=>{entityEditor.hidden=true;}));reveal(entityEditor);
  }
  async function showEntity(id) {
    const row=await request(`/entities/${encodeId(id)}`);selectedEntity=row.id;
    entityEditor.hidden=true;
    entityDetail.replaceChildren(element('h2',row.canonical_name),metadata([
      ['Type',caption(row.entity_type)],['Aliases',row.aliases.join(', ')||'None'],['Version',row.version],['Archive state',row.archived_at?'Archived':'Active'],
      ['Created',dateText(row.created_at)],['Updated',dateText(row.updated_at)],['Actor',row.created_by],['Entity ID',row.id],
    ]),element('p',row.description||'No description.','prose'));
    const controls=element('div',undefined,'toolbar');
    if(!row.archived_at)controls.append(button('Edit descriptor',()=>openEntityEditor(row)),button('Create claim for entity',async()=>{await switchView('claims');const subject=pendingSubject;pendingSubject=null;openClaimEditor(row,subject);}));
    controls.append(button(row.archived_at?'Restore entity':'Archive entity',()=>lifecycle(entityDetail,`/entities/${encodeId(id)}`,row,row.archived_at?'restore':'archive','entity',()=>showEntity(id))));
    entityDetail.append(controls);
    const related=element('section');related.id='attr-entity-claims';entityDetail.append(related);
    async function relatedPage(offset=0) {
      const page=await readPage('/claims',{entity_id:id,include_archived:true},offset,10);
      related.replaceChildren(element('h3','Claims about wallets'),table(['Subject','Relationship','Last assessment','Review','Archive state',''],page.items.map(claim=>[
        shortValue(claim.subject_ref),caption(claim.relationship),caption(claim.assessment),claim.needs_review?'Review required':'Up to date',claim.archived_at?'Archived':'Active',
        button('View claim',async()=>{await switchView('claims');await showClaim(claim.id);})
      ]),'No attribution claims have been created.'),pager(page,relatedPage));
    }
    await relatedPage();const history=element('section');entityDetail.append(button('Entity history',()=>loadHistory(history,`/entities/${encodeId(id)}/events`)),history);reveal(entityDetail);
  }
  function openClaimEditor(entity=null,subject=null) {
    pendingSubject=null;
    targetEntity=entity;claimEditor.replaceChildren(element('h2','Create claim'));
    const target=element('p',entity?`Attributed entity: ${entity.canonical_name}`:'Choose an entity before creating the claim.');target.id='attr-claim-target';
    claimEditor.append(target,button('Choose target entity',()=>chooseEntity(row=>{targetEntity=row;target.textContent=`Attributed entity: ${row.canonical_name} · ${row.id}`;})),
      button('Create a new entity',async()=>{const node=claimEditor.querySelector('form');pendingSubject={chain:node.elements.chain.value,address:node.elements.subject_ref.value};await switchView('entities');openEntityEditor();}),
      form('attr-claim-form',claimFields(),'Save claim',async data=>{
        if(!targetEntity)throw new UserError('Choose or create the target entity first.');
        const row=await request('/claims',{method:'POST',body:{entity_id:targetEntity.id,subject_type:data.subject_type,chain:data.chain,
          subject_ref:data.subject_ref,relationship:data.relationship,...scopeData(data)}});
        claimEditor.hidden=true;await loadClaims();await showClaim(row.id);
      }),button('Cancel',()=>{claimEditor.hidden=true;}));
    if(subject){const node=claimEditor.querySelector('form');node.elements.subject_type.value='wallet';node.elements.chain.value=subject.chain;node.elements.subject_ref.value=subject.address;node.elements.relationship.value='';}
    reveal(claimEditor);
  }
  async function showClaim(id) {
    const row=await request(`/claims/${encodeId(id)}`);selectedClaim=row.id;
    claimEditor.hidden=true;
    claimDetail.replaceChildren(element('h2','Claim detail'),element('p',row.subject_ref,'full-address'));
    claimDetail.append(metadata([
      ['Chain',caption(row.chain)],['Normalized subject',row.subject_ref],['Relationship',caption(row.relationship)],['Attributed entity',row.entity.canonical_name],
      ['Entity type',caption(row.entity.entity_type)],['Last assessment',caption(row.assessment)],['Review',row.needs_review?'Review required':'Up to date'],
      ['Version',row.version],['Archive state',row.archived_at?'Claim archived':row.entity_archived?'Entity archived':'Active'],
      ['Created',dateText(row.created_at)],['Updated',dateText(row.updated_at)],['Actor',row.created_by],['Claim ID',row.id],
      ['Valid from',row.valid_from||'Unknown'],['Valid to',row.valid_to||'Unknown'],['Assessed at',dateText(row.assessed_at)],['Assessed by',row.assessed_by||'Not assessed'],
    ]));
    const review=element('p',row.needs_review?'Review required. The last assessment is retained; review current evidence before relying on it.':'Assessment review is up to date for this claim version.',row.needs_review?'bounded-note attr-review':'bounded-note');review.id='attr-review-state';
    claimDetail.append(review,element('h3','Scope and rationale'),element('p',row.scope_note,'prose'),element('h3','Assessment rationale'),
      element('p',row.assessment_rationale||'No assessment rationale recorded.','prose'));
    const count=row.active_evidence_counts;
    claimDetail.append(element('p',`${count.supports} supporting · ${count.contradicts} contradicting · ${count.context} contextual active links`,'attr-counts'));
    const controls=element('div',undefined,'toolbar'),editor=element('section');editor.id='attr-claim-action';
    const active=!row.archived_at&&!row.entity_archived;
    if(active)controls.append(button('Capture evidence',()=>captureEditor(editor,row)),button('Link existing evidence',()=>reuseEvidence(editor,row)),
      button('Review assessment',()=>assessmentEditor(editor,row)),button('Revise scope',()=>{
        editor.replaceChildren(element('h3','Revise claim scope'),form('attr-scope-form',[...scopeFields(row),reasonField],'Save scope',async data=>{
          await request(`/claims/${encodeId(id)}/scope`,{method:'PATCH',body:{expected_version:row.version,reason:data.reason,scope:scopeData(data)}});await refreshClaim(id);
        }));reveal(editor);
      }));
    controls.append(button(row.archived_at?'Restore claim':'Archive claim',()=>lifecycle(editor,`/claims/${encodeId(id)}`,row,row.archived_at?'restore':'archive','claim',()=>refreshClaim(id))));
    claimDetail.append(controls,editor);
    const evidence=element('section');evidence.id='attr-linked-evidence';claimDetail.append(evidence);
    if(!Object.values(count).some(Boolean))evidence.append(element('p','No evidence is linked to this claim.','empty'));
    const showWithdrawn=element('label',undefined,'attr-check');const checkbox=element('input');checkbox.type='checkbox';checkbox.id='attr-show-withdrawn';
    showWithdrawn.append(checkbox,element('span','Include withdrawn links'));evidence.append(showWithdrawn);
    const groups=element('div',undefined,'attr-evidence-groups');evidence.append(groups);
    const groupNodes=Object.fromEntries(stances.map(stance=>{const node=element('section',undefined,`attr-stance ${stance}`);node.id=`attr-evidence-${stance}`;groups.append(node);return [stance,node];}));
    const groupNames={supports:'Supporting evidence',contradicts:'Contradicting evidence',context:'Contextual evidence'};
    async function loadGroup(stance,offset=0) {
      const page=await readPage(`/claims/${encodeId(id)}/evidence`,{stance,include_withdrawn:checkbox.checked},offset,10);
      const box=groupNodes[stance];box.replaceChildren(element('h3',groupNames[stance]));
      if(!page.items.length)box.append(element('p','No links in this view.','muted small'));
      for(const link of page.items) {
        const card=element('article',undefined,'attr-evidence-card');card.dataset.linkId=link.id;
        card.append(element('strong',caption(stance),'badge'),element('h4',link.evidence.title),element('p',`Source: ${link.evidence.source_name} · Origin: ${caption(link.evidence.origin)}`,'small'),
          element('p',`Directness: ${caption(link.directness)} · ${link.withdrawn_at?'Withdrawn':'Active'} · Captured ${dateText(link.evidence.captured_at)}`,'small'),element('p',link.rationale,'prose small'));
        if(origins.includes(link.evidence.origin)&&link.evidence.source_url)card.append(safeSource(link.evidence.source_url));
        const material=element('div');card.append(button('Inspect capture',()=>inspectCapture(material,link.evidence_id)),material);
        if(active) {
          card.append(button(link.withdrawn_at?'Restore link':'Withdraw link',()=>lifecycle(editor,`/claims/${encodeId(id)}/evidence/${encodeId(link.id)}`,row,
            link.withdrawn_at?'restore':'withdraw','link',()=>refreshClaim(id))));
          if(!link.withdrawn_at)card.append(button('Replace evidence',()=>captureEditor(editor,row,link)),button('Change link relevance',()=>{
            editor.replaceChildren(element('h3','Change link relevance'),element('p','This changes the claim link only. Captured evidence remains immutable.'),
              form('attr-link-edit',[...linkFields(link),reasonField],'Save link relevance',async data=>{
                await request(`/claims/${encodeId(id)}/evidence/${encodeId(link.id)}`,{method:'PATCH',body:{expected_version:row.version,reason:data.reason,link:linkData(data)}});await refreshClaim(id);
              }));reveal(editor);
          }));
        }
        box.append(card);
      }
      box.append(pager(page,offset=>loadGroup(stance,offset)));
    }
    checkbox.addEventListener('change',()=>perform(()=>Promise.all(stances.map(stance=>loadGroup(stance)))));
    await Promise.all(stances.map(stance=>loadGroup(stance)));
    const history=element('section');history.id='attr-claim-history';claimDetail.append(button('Claim history',()=>loadHistory(history,`/claims/${encodeId(id)}/events`)),history);
    reveal(claimDetail);
  }
  async function refreshClaim(id) {await loadClaims();await showClaim(id);}
  async function inspectCapture(host,id) {
    const row=await request(`/evidence/${encodeId(id)}`);
    host.replaceChildren(element('h4',row.title),element('p',`Origin: ${caption(row.origin)} · Actor: ${row.captured_by}`,'small'));
    if(!origins.includes(row.origin)) {host.append(element('p','Restricted-origin capture. Detailed material is not displayed in this workspace.'));return;}
    host.append(element('p',row.summary,'prose'),element('p',row.excerpt||'No excerpt captured.','prose'),metadata([
      ['Source',row.source_name],['Locator',row.source_locator||'Not supplied'],['Published',row.published_on||'Unknown'],['Observed',row.observed_on||'Unknown'],
      ['Captured',dateText(row.captured_at)],['Source reliability',caption(row.source_reliability)],['Evidence ID',row.id],['Fingerprint',row.content_sha256],
    ]),element('p',row.reliability_rationale||'Reliability unassessed.','prose small'),element('p',row.analyst_note||'No analyst note.','prose small'),
      details('Captured metadata',row.metadata_json),element('p','Immutable capture. Changing link relevance does not change this record.','muted small'));
  }
  function captureEditor(editor,row,replaced=null) {
    editor.replaceChildren(element('h3',replaced?'Replace evidence':'Capture and link evidence'),element('p',replaced?
      'Replacement creates a new immutable evidence record; the original remains in history. The old claim link will be withdrawn.':'Capture public material or an analyst observation, then explicitly state its relevance to this claim.','bounded-note'));
    if(replaced)editor.append(element('p',`Original evidence: ${replaced.evidence.title} · ${replaced.evidence_id}`));
    const node=form('attr-evidence-form',[...captureFields(),...linkFields(),...(replaced?[reasonField]:[])],replaced?'Create replacement':'Capture and link',async data=>{
      const path=`/claims/${encodeId(row.id)}/evidence/${replaced?encodeId(replaced.id)+'/replace':'capture'}`;
      await request(path,{method:'POST',body:{expected_version:row.version,evidence:captureData(data),link:linkData(data),...(replaced?{reason:data.reason}:{})}});
      await refreshClaim(row.id);
    });advancedCapture(node);editor.append(node);reveal(editor);
  }
  async function reuseEvidence(editor,row) {
    editor.replaceChildren(element('h3','Link existing evidence'),element('p','Reuse an immutable capture with a separate rationale for this claim.','muted small'));
    let chosen=null;const chosenText=element('p','Choose a capture.');const list=element('div');list.id='attr-reuse-list';
    const filter=form('attr-reuse-filter',[{name:'origin',label:'Origin',options:[['','All origins'],...options(origins)]},
      {name:'source_catalog_id',label:'Source catalog ID (optional)'}],'Filter captures',()=>load(0));
    const linkForm=form('attr-reuse-form',linkFields(),'Link chosen evidence',async data=>{
      if(!chosen)throw new UserError('Choose an existing evidence capture.');
      await request(`/claims/${encodeId(row.id)}/evidence`,{method:'POST',body:{expected_version:row.version,evidence_id:chosen.id,link:linkData(data)}});await refreshClaim(row.id);
    });
    editor.append(filter,list,chosenText,linkForm);
    async function load(offset) {
      const page=await readPage('/evidence',{origin:filter.elements.origin.value,source_catalog_id:filter.elements.source_catalog_id.value},offset,10);
      list.replaceChildren(table(['Title','Source','Origin','Captured',''],page.items.map(item=>[item.title,item.source_name,caption(item.origin),dateText(item.captured_at),
        button('Choose capture',()=>{chosen=item;chosenText.textContent=`Chosen: ${item.title} · ${item.id}`;})]),'No evidence captures are available.'),pager(page,load));
    }
    await load(0);reveal(editor);
  }
  async function assessmentEditor(editor,initial) {
    // Capture the current version once. Paging never silently refreshes or overwrites it.
    const row=await request(`/claims/${encodeId(initial.id)}`),reviewed=new Set(),acknowledged=new Set();
    const total=Object.values(row.active_evidence_counts).reduce((a,b)=>a+b,0);
    editor.replaceChildren(element('h3','Review assessment'),element('p',`Review each active link for claim version ${row.version}. Check each acknowledgement yourself. GC does not authenticate individual analysts.`,'bounded-note'));
    const progress=element('p');progress.id='attr-assessment-progress';const checklist=element('div');checklist.id='attr-review-links';
    const updateProgress=()=>{progress.textContent=`${reviewed.size} of ${total} active links reviewed; ${acknowledged.size} contradictions acknowledged.`;};updateProgress();
    const node=form('attr-assessment-form',[
      {name:'assessment',label:'New assessment',options:[['','Choose assessment'],...options(assessments)],required:true},
      {name:'rationale',label:'Assessment rationale',type:'textarea',required:true,maxLength:8000},
      {name:'conflict_discussion',label:'Contradiction discussion (required when contradictions are active)',type:'textarea',required:row.active_evidence_counts.contradicts>0,maxLength:8000},
      {name:'source_verification',label:'Source verification (required for strongly supported)',type:'textarea',maxLength:8000},
    ],'Save assessment',async data=>{
      if(reviewed.size!==total)throw new UserError('Review every active evidence link, including further pages, before saving the assessment.');
      if(acknowledged.size!==row.active_evidence_counts.contradicts)throw new UserError('Explicitly acknowledge every contradicting evidence link before saving.');
      await request(`/claims/${encodeId(row.id)}/assessment`,{method:'POST',body:{expected_version:row.version,...data,
        reviewed_link_ids:[...reviewed],acknowledged_contradictions:[...acknowledged]}});await refreshClaim(row.id);
    });
    editor.append(progress,checklist,node);
    async function load(offset=0) {
      const page=await readPage(`/claims/${encodeId(row.id)}/evidence`,{},offset,10);checklist.replaceChildren();
      for(const link of page.items) {
        const card=element('article',undefined,'attr-evidence-card');
        card.append(element('strong',caption(link.stance),'badge'),element('h4',link.evidence.title),element('p',`${link.evidence.source_name} · ${caption(link.directness)} · ${link.rationale}`,'prose small'));
        const material=element('div');card.append(button('Inspect capture',()=>inspectCapture(material,link.evidence_id)),material);
        function check(label,set,kind) {
          const wrap=element('label',undefined,'attr-check'),input=element('input');input.type='checkbox';input.dataset[kind]=link.id;input.checked=set.has(link.id);
          input.addEventListener('change',()=>{if(input.checked)set.add(link.id);else set.delete(link.id);updateProgress();});
          wrap.append(input,element('span',`${label} (${link.id})`));card.append(wrap);
        }
        check('I reviewed this evidence link',reviewed,'reviewId');
        if(link.stance==='contradicts')check('I acknowledge this contradiction',acknowledged,'ackId');
        checklist.append(card);
      }
      checklist.append(pager(page,load));
    }
    await load();reveal(editor);
  }
  function lifecycle(container,path,row,operation,kind,after) {
    const box=element('section');box.id='attr-lifecycle';
    const note=kind==='link'?'This changes the link to this claim. The original evidence and history will be retained.':'Archiving preserves evidence and history. Restoration requires a new review.';
    box.append(element('h3',`${caption(operation)} ${kind}`),element('p',note,'bounded-note'));
    box.append(form('attr-lifecycle-form',[reasonField,{name:'ack',label:`I intend to ${operation} this ${kind}; records and history are retained.`,type:'checkbox',required:true}],`${caption(operation)} ${kind}`,async data=>{
      if(data.ack!=='on')throw new UserError('Confirm the intended lifecycle action.');
      await request(`${path}/${operation}`,{method:'POST',body:{expected_version:row.version,reason:data.reason}});
      if(kind==='entity')await loadEntities();await after();
    }));
    const old=container.querySelector('#attr-lifecycle');if(old)old.remove();container.append(box);reveal(box);
  }
  async function loadHistory(container,path,offset=0) {
    const page=await readPage(path,{},offset,10);
    container.replaceChildren(element('h3','History'),element('p','Actor values describe local operations. GC does not currently authenticate individual analysts.','muted small'));
    for(const event of page.items) {
      const card=element('article',undefined,'attr-evidence-card');card.append(element('strong',`#${event.sequence} · ${caption(event.event_type)}`),
        element('p',`${dateText(event.occurred_at)} · Actor: ${event.actor_ref} (${event.actor_kind})`,'small'),element('p',event.reason,'prose'),details('Before / after and event evidence',event.payload));container.append(card);
    }
    container.append(pager(page,offset=>loadHistory(container,path,offset)));reveal(container);
  }
  return context=>{
    if(context)return perform(async()=>{
      if(context.action==='open_claim'&&typeof context.id==='string'){await switchView('claims');await showClaim(context.id);}
      else if(context.action==='open_entity'&&typeof context.id==='string'){await switchView('entities');await showEntity(context.id);}
      else if(context.action==='create_claim'&&['bitcoin','ethereum'].includes(context.chain)&&typeof context.address==='string'){
        await switchView('claims');openClaimEditor(null,{chain:context.chain,address:context.address});
      }
      loaded=true;
    });
    if(!loaded)return perform(async()=>{await loadClaims();loaded=true;});
  };
}
