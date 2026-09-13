const assert=require('node:assert/strict');

module.exports=async({evaluate,mode})=>{
  const prefix='/api/greedy-collector',address='0x'+'ab'.repeat(20);
  const idle=id=>`waitFor(()=>document.getElementById(${JSON.stringify(id)}).dataset.busy!=='true')`;
  const text=selector=>evaluate(`document.querySelector(${JSON.stringify(selector)}).innerText`);
  const click=async(scope,label,id='attribution-workspace')=>evaluate(`button(${JSON.stringify(scope)},${JSON.stringify(label)}).click();${idle(id)}`);
  const submit=async(id,values,scope='attribution-workspace')=>evaluate(`{const f=document.getElementById(${JSON.stringify(id)});for(const [k,v] of Object.entries(${JSON.stringify(values)})){if(f.elements[k].type==='checkbox')f.elements[k].checked=v;else f.elements[k].value=v;}f.requestSubmit();}${idle(scope)}`);
  const api=async(path,method='GET',body)=>{
    const response=await evaluate(`fetch(${JSON.stringify(prefix+path)},{method:${JSON.stringify(method)},headers:{'Content-Type':'application/json'},${body===undefined?'':`body:JSON.stringify(${JSON.stringify(body)}),`}}).then(async r=>({status:r.status,data:await r.json()}))`);
    assert.ok(response.status<300,JSON.stringify(response));return response.data;
  };
  await evaluate("window.at5Requests=[];window.at5Original=window.fetch;window.fetch=(url,options)=>{at5Requests.push({url:String(url),method:options?.method||'GET',body:options?.body});return at5Original(url,options);}");
  await evaluate("go('labels')");
  await submit('label-create',{chain:'ethereum',address,label:'Synthetic AT5 label',type:'Exchange',source:'Manual analyst label',confidence:'0.9'},'labels-workspace');
  const label=(await api('/labels')).labels[0];
  assert.ok((await text('#label-detail')).includes('Use as attribution evidence'));
  await click('#label-detail','Use as attribution evidence');
  if(mode==='unmigrated'){
    assert.ok((await text('#attribution-workspace > .operation-status')).includes('storage is not initialized'));
    await evaluate("go('labels')");assert.ok((await text('#labels-list')).includes('Synthetic AT5 label'));
  }else{
    assert.equal((await api('/attribution/entities')).total,0);assert.equal((await api('/attribution/claims')).total,0);assert.equal((await api('/attribution/evidence')).total,0);
    assert.ok((await text('#attr-source-handoff')).includes('Annotation confidence: 0.9'));
    await click('#attr-source-handoff','Create attribution claim','attr-source-handoff');
    assert.equal(await evaluate("document.querySelector('#attr-claim-form [name=subject_ref]').value"),address);
    assert.equal(await evaluate("document.querySelector('#attr-claim-form [name=relationship]').value"),'');
    assert.ok((await text('#attr-claim-target')).includes('Choose an entity'));
    await click('#attr-claim-editor','Create a new entity');
    await submit('attr-entity-form',{canonical_name:'Synthetic AT5 entity',entity_type:'service',description:'Explicit descriptor',aliases:''});
    await click('#attr-entity-detail','Create claim for entity');
    assert.equal(await evaluate("document.querySelector('#attr-claim-form [name=relationship]').value"),'');
    await submit('attr-claim-form',{relationship:'operated_by',scope_note:'Explicit test scope'});
    assert.equal((await api('/attribution/evidence')).total,0);
    assert.equal(await evaluate("document.querySelector('#attr-handoff-confirm [name=stance]').value"),'');
    assert.equal(await evaluate("document.querySelector('#attr-handoff-confirm [name=directness]').value"),'');
    await submit('attr-handoff-confirm',{rationale:'Inspected local annotation',confirmed:true},'attr-source-handoff');
    assert.equal((await api('/attribution/evidence')).total,0); // Required stance blocks capture.
    await submit('attr-handoff-confirm',{stance:'supports',directness:'indirect',rationale:'Source annotation supports this bounded claim',confirmed:true},'attr-source-handoff');
    assert.ok((await text('#attr-source-handoff')).includes('Immutable evidence captured and linked'));
    await click('#attr-source-handoff','Open attribution','attr-source-handoff');
    let claim=(await api('/attribution/claims')).items[0];
    assert.ok((await text('#attr-claim-detail')).includes(claim.id));
    assert.equal(claim.assessment,'unassessed');
    await click('#attr-evidence-supports','Inspect capture');
    assert.ok((await text('#attr-evidence-supports')).includes('Greedy Collector Label'));
    assert.ok((await text('#attr-evidence-supports')).includes('Original label source: Manual analyst label'));
    const capture=(await api('/attribution/evidence')).items[0];
    assert.equal(capture.metadata_json.record.confidence,.9);
    // Existing CSV update semantics, no special test endpoint or immutable-evidence edits.
    const csv=`chain,address,label,type,source,confidence\nethereum,${address},Synthetic AT5 label,Exchange,Manual analyst label,0.1\n`.replaceAll('\\n','\n');
    await evaluate(`(async()=>{const f=new FormData();f.append('file',new Blob([${JSON.stringify(csv)}],{type:'text/csv'}),'labels.csv');await fetch('/api/greedy-collector/labels/import',{method:'POST',body:f}).then(r=>{if(!r.ok)throw Error('CSV update failed')});})()`);
    assert.deepEqual(await api('/attribution/evidence/'+capture.id),capture);
    assert.equal((await api('/labels')).labels[0].confidence,.1);
    // Assess separately so contradiction invalidation can be distinguished from promotion.
    const links=(await api(`/attribution/claims/${claim.id}/evidence`)).items;
    await api(`/attribution/claims/${claim.id}/assessment`,'POST',{expected_version:claim.version,assessment:'possible',rationale:'Explicit provisional test assessment',reviewed_link_ids:links.map(x=>x.id),acknowledged_contradictions:[]});
  }

  await evaluate("go('research')");
  await submit('research-query',{name:'Synthetic AT5 subject',domain:'',include_manual_sources:true},'research-workspace');
  await click('#research-matches','View match','research-workspace');
  assert.ok((await text('#research-detail')).includes('Use as attribution evidence'));
  assert.equal(await evaluate("!!button('#research-manual','Use as attribution evidence')"),false);
  assert.equal(await evaluate("!!button('#research-unavailable','Use as attribution evidence')"),false);
  const screenCount=await evaluate("at5Requests.filter(r=>r.url.endsWith('/kyc/screen')).length");
  await click('#research-detail','Use as attribution evidence');
  if(mode==='unmigrated'){
    assert.ok((await text('#attribution-workspace > .operation-status')).includes('storage is not initialized'));
    await evaluate("go('research')");assert.ok((await text('#research-detail')).includes('Synthetic AT5 subject'));
    assert.equal(await evaluate("at5Requests.some(r=>r.method==='POST'&&r.url.includes('/attribution/'))"),false);
    console.log('AT-5 unmigrated: Labels/Research remain usable; handoff safely unavailable.');return;
  }
  assert.ok((await text('#attr-source-handoff')).includes('Match score (source similarity): 1'));
  assert.ok((await text('#attr-source-handoff')).includes('Research review status: Unreviewed'));
  assert.equal((await text('#attr-source-handoff')).includes('at5-nested-canary'),false);
  await click('#attr-source-handoff','Choose claim','attr-source-handoff');
  assert.equal(await evaluate("document.querySelector('#attr-handoff-confirm [name=stance]').value"),'');
  await submit('attr-handoff-confirm',{stance:'contradicts',directness:'indirect',rationale:'Conflicting public-source context for review',confirmed:true},'attr-source-handoff');
  await click('#attr-source-handoff','Open attribution','attr-source-handoff');
  let claim=(await api('/attribution/claims')).items[0];
  assert.equal(claim.assessment,'possible');assert.equal(claim.needs_review,true);
  await click('#attr-evidence-contradicts','Inspect capture');
  assert.ok((await text('#attr-evidence-contradicts')).includes('Greedy Collector Research'));
  assert.ok((await text('#attr-evidence-contradicts')).includes('Provider: opensanctions'));
  assert.ok((await text('#attr-evidence-contradicts')).includes('Research review status: Unreviewed'));
  const researchCapture=(await api('/attribution/evidence')).items.find(row=>row.collection_method==='research_snapshot');
  assert.ok(researchCapture.source_url.includes('/synthetic-at5/'));
  assert.equal(researchCapture.metadata_json.record.source_data.public_field,'Retained public context');
  await evaluate("go('research')");
  await submit('research-review',{review_status:'False positive'},'research-workspace');
  assert.deepEqual(await api('/attribution/evidence/'+researchCapture.id),researchCapture);
  await click('#research-detail','Use as attribution evidence');
  await click('#attr-source-handoff','Choose claim','attr-source-handoff');
  await submit('attr-handoff-confirm',{stance:'context',directness:'context',rationale:'Updated source review context',confirmed:true},'attr-source-handoff');
  assert.equal((await api('/attribution/evidence')).total,3);
  await click('#attr-source-handoff','Open attribution','attr-source-handoff');
  assert.equal((await api('/attribution/claims')).total,1);assert.equal((await api('/attribution/entities')).total,1);
  // Duplicate snapshot is a conflict even when the analyst chooses a different stance.
  await evaluate("go('research')");await click('#research-detail','Use as attribution evidence');await click('#attr-source-handoff','Choose claim','attr-source-handoff');
  await submit('attr-handoff-confirm',{stance:'context',directness:'context',rationale:'Repeat review',confirmed:true},'attr-source-handoff');
  assert.ok((await text('#attr-source-handoff .operation-status')).includes('already linked'));
  assert.equal((await api('/attribution/evidence')).total,3);
  // Research creates no wallet prefill or entity inference.
  await click('#attr-source-handoff','Create attribution claim','attr-source-handoff');
  assert.equal(await evaluate("document.querySelector('#attr-claim-form [name=subject_ref]').value"),'');
  assert.equal(await evaluate("document.querySelector('#attr-claim-form [name=relationship]').value"),'');
  assert.ok((await text('#attr-claim-target')).includes('Choose an entity'));
  assert.equal(await evaluate("at5Requests.filter(r=>r.url.endsWith('/kyc/screen')).length"),screenCount);
  assert.equal(await evaluate("at5Requests.some(r=>r.url.includes('/lookup/'))"),false);
  assert.ok(await evaluate("at5Requests.every(r=>r.url.startsWith('/api/greedy-collector/'))"));
  console.log('AT-5 Label/Research explicit capture, immutable snapshots, provenance, all stances, creation boundaries, duplicate protection and provider isolation passed.');
};
