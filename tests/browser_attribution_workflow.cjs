const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {execFileSync}=require('node:child_process');

module.exports=async({evaluate,call,work,mode,httpPort})=>{
  const idle="waitFor(()=>document.getElementById('attribution-workspace').dataset.busy==='false')";
  const text=selector=>evaluate(`document.querySelector(${JSON.stringify(selector)}).innerText`);
  const click=(selector,label)=>evaluate(`button(${JSON.stringify(selector)},${JSON.stringify(label)}).click();${idle}`);
  const fill=(id,values)=>evaluate(`{const f=document.getElementById(${JSON.stringify(id)});for(const [key,value] of Object.entries(${JSON.stringify(values)})){if(f.elements[key].type==='checkbox')f.elements[key].checked=value;else f.elements[key].value=value;}}`);
  const submit=async(id,values)=>{await fill(id,values);return evaluate(`document.getElementById(${JSON.stringify(id)}).requestSubmit();${idle}`);};
  const api=async(suffix,method='GET',body)=>evaluate(`fetch('/api/greedy-collector/attribution'+${JSON.stringify(suffix)},{method:${JSON.stringify(method)},headers:{'Content-Type':'application/json'},${body===undefined?'':`body:JSON.stringify(${JSON.stringify(body)}),`}}).then(async r=>({status:r.status,data:await r.json()}))`);
  const state=()=>JSON.parse(execFileSync(process.env.PYTHON||'python',['-B','-c',
    `import sqlite3,json; db=sqlite3.connect(${JSON.stringify(path.join(work,'attribution-test.db'))}); tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]; print(json.dumps({t:db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in tables}))`],{windowsHide:true,encoding:'utf8'}));
  await evaluate("window.attrRequests=[];window.attrOriginalFetch=window.fetch;window.fetch=(url,options)=>{attrRequests.push({url:String(url),method:options?.method||'GET',body:options?.body||null});if(!String(url).startsWith('/api/greedy-collector/attribution'))throw Error('Unexpected external/workspace request');return attrOriginalFetch(url,options);}");
  await evaluate("go('attribution')");
  assert.equal(await evaluate("document.querySelectorAll('[data-workspace]').length"),11);
  if(mode==='unmigrated'){
    assert.ok((await text('#attribution-workspace > .operation-status')).includes('storage is not initialized'));
    assert.equal(Object.keys(state()).some(name=>name.startsWith('attribution_')),false);
    await click('#attr-recovery','Reload');
    assert.ok((await text('#attribution-workspace > .operation-status')).includes('storage is not initialized'));
    assert.equal(Object.keys(state()).some(name=>name.startsWith('attribution_')),false);
    await evaluate("attrOriginalFetch('/health').then(r=>{if(!r.ok)throw Error('Health failed')})");
    await call('Page.captureScreenshot',{format:'png'}).then(r=>fs.writeFileSync(path.join(work,'attribution-unmigrated.png'),Buffer.from(r.data,'base64')));
    assert.ok(await evaluate("attrRequests.every(r=>r.method==='GET')"));return;
  }
  assert.ok((await text('#attr-claims-list')).includes('No attribution claims have been created.'));
  await click('#attribution-workspace > .toolbar[aria-label]','Entities');
  assert.ok((await text('#attr-entities-list')).includes('No attribution entities have been created.'));
  const before=state();
  await click('#attr-entities-view','Create entity');
  await submit('attr-entity-form',{canonical_name:'Synthetic AT-3 entity',entity_type:'service',aliases:'Synthetic alias',description:'Synthetic browser descriptor'});
  assert.ok((await text('#attr-entity-detail')).includes('Synthetic AT-3 entity'));
  let entity=(await api('/entities')).data.items[0];
  assert.equal(entity.version,1);
  await click('#attr-entity-detail','Edit descriptor');
  await submit('attr-entity-form',{description:'Revised browser descriptor',reason:'Explicit revision'});
  entity=(await api('/entities/'+entity.id)).data;assert.equal(entity.version,2);
  await click('#attr-entity-detail','Edit descriptor');
  assert.equal((await api('/entities/'+entity.id,'PATCH',{expected_version:2,reason:'Concurrent test edit',descriptor:{canonical_name:entity.canonical_name,entity_type:'service',description:'Concurrent descriptor',aliases:[]}})).status,200);
  await submit('attr-entity-form',{description:'Stale update must not win',reason:'Stale browser write'});
  assert.ok((await text('#attribution-workspace > .operation-status')).includes('record changed since you loaded it'));
  assert.equal((await api('/entities/'+entity.id)).data.description,'Concurrent descriptor');
  await click('#attr-recovery','Reload');
  assert.ok((await text('#attr-entity-detail')).includes('Concurrent descriptor'));
  await click('#attr-entity-detail','Create claim for entity');
  const address='0x'+'aB'.repeat(20);
  await submit('attr-claim-form',{chain:'ethereum',subject_ref:'  '+address+'  ',relationship:'operated_by',scope_note:'Synthetic browser claim scope'});
  let claim=(await api('/claims')).data.items[0];
  assert.equal(claim.subject_ref,address.toLowerCase());
  assert.ok((await text('#attr-claim-detail')).includes(address.toLowerCase()));
  assert.ok((await text('#attr-linked-evidence')).includes('No evidence is linked to this claim.'));
  await click('#attr-claims-view','Create claim');
  await click('#attr-claim-editor','Choose target entity');
  await click('#attr-picker','Choose entity');
  await submit('attr-claim-form',{chain:'ethereum',subject_ref:address,relationship:'operated_by',scope_note:'Duplicate test'});
  assert.ok((await text('#attribution-workspace > .operation-status')).includes('claim already exists'));
  await click('#attr-recovery','Open existing claim');
  assert.equal((await api('/claims')).data.total,1);

  const capture=async(stance,title,replacement=false)=>{
    if(!replacement)await click('#attr-claim-detail','Capture evidence');
    await submit('attr-evidence-form',{evidence_type:'official_disclosure',origin:'public_osint',title,source_name:'Synthetic browser source',
      source_url:'https://source.example/at3',summary:'Synthetic public material <img src=x onerror=alert(1)>',excerpt:'Synthetic excerpt retained',
      source_reliability:'reliable',reliability_rationale:'Synthetic source verification',stance,directness:stance==='context'?'context':'direct',rationale:'Explicit '+stance+' rationale',
      ...(replacement?{reason:'Replace this capture explicitly'}:{})});
    const message=await text('#attribution-workspace > .operation-status');assert.equal(message,'Complete.',message);
  };
  await capture('supports','Synthetic supporting capture');
  await capture('contradicts','Synthetic contradicting capture');
  await capture('context','Synthetic contextual capture');
  for(const [stance,label] of [['supports','Supporting'],['contradicts','Contradicting'],['context','Contextual']]){
    assert.ok((await text('#attr-evidence-'+stance)).includes(label+' evidence'));
    assert.ok((await text('#attr-evidence-'+stance)).includes(stance==='context'?'Context':stance==='supports'?'Supports':'Contradicts'));
  }
  await click('#attr-evidence-supports','Inspect capture');
  assert.ok((await text('#attr-evidence-supports')).includes('<img src=x onerror=alert(1)>'));
  assert.equal(await evaluate("document.querySelectorAll('#attribution-workspace img, #attribution-workspace iframe').length"),0);
  assert.ok(await evaluate("[...document.querySelectorAll('#attr-linked-evidence a')].every(a=>a.target==='_blank'&&a.rel==='noopener noreferrer')"));
  assert.equal(await evaluate("[...document.querySelectorAll('#attribution-workspace button')].some(b=>/Delete|Edit evidence/.test(b.textContent))"),false);

  await click('#attr-claim-detail','Review assessment');
  assert.equal(await evaluate("[...document.querySelectorAll('[data-ack-id]')].some(n=>n.checked)"),false);
  assert.equal(await evaluate("[...document.querySelectorAll('#attr-assessment-form option')].some(n=>n.textContent==='Confirmed')"),false);
  const checkAll=async selector=>evaluate(`document.querySelectorAll(${JSON.stringify(selector)}).forEach(n=>{n.checked=true;n.dispatchEvent(new Event('change'));})`);
  await checkAll('[data-review-id]');
  const posts=await evaluate("attrRequests.filter(r=>r.url.endsWith('/assessment')&&r.method==='POST').length");
  await submit('attr-assessment-form',{assessment:'strongly_supported',rationale:'Synthetic assessed conclusion',conflict_discussion:'Discussed the synthetic contradiction',source_verification:'Synthetic direct source reviewed'});
  assert.ok((await text('#attribution-workspace > .operation-status')).includes('Explicitly acknowledge'));
  assert.equal(await evaluate("attrRequests.filter(r=>r.url.endsWith('/assessment')&&r.method==='POST').length"),posts);
  await checkAll('[data-ack-id]');
  await submit('attr-assessment-form',{});
  claim=(await api('/claims/'+claim.id)).data;
  assert.equal(claim.assessment,'strongly_supported');assert.equal(claim.needs_review,false);
  await click('#attr-claim-detail','Claim history');
  assert.ok((await text('#attr-claim-history')).includes('Assessment changed'));
  assert.ok((await text('#attr-claim-history')).includes('local_analyst'));
  await evaluate("document.querySelector('#attr-claim-history details').open=true");
  assert.ok((await text('#attr-claim-history')).includes('schema_version'));

  async function lifecycle(buttonScope,label){
    await click(buttonScope,label);await submit('attr-lifecycle-form',{reason:'Explicit lifecycle test decision',ack:true});
    assert.equal(await text('#attribution-workspace > .operation-status'),'Complete.');
  }
  let links=(await api(`/claims/${claim.id}/evidence`)).data.items;
  const original=links.find(link=>link.stance==='contradicts');
  const originalCapture=(await api('/evidence/'+original.evidence_id)).data;
  await lifecycle('#attr-evidence-contradicts','Withdraw link');
  assert.ok((await text('#attr-review-state')).includes('Review required'));
  await evaluate(`{const n=document.getElementById('attr-show-withdrawn');n.checked=true;n.dispatchEvent(new Event('change'));}${idle}`);
  assert.ok((await text('#attr-evidence-contradicts')).includes('Withdrawn'));
  await lifecycle('#attr-evidence-contradicts','Restore link');
  await click('#attr-evidence-contradicts','Replace evidence');
  assert.ok((await text('#attr-claim-action')).includes('original remains in history'));
  await capture('contradicts','Synthetic replacement capture',true);
  assert.deepEqual((await api('/evidence/'+original.evidence_id)).data,originalCapture);
  assert.ok((await text('#attr-evidence-contradicts')).includes('Synthetic replacement capture'));
  await evaluate(`{const n=document.getElementById('attr-show-withdrawn');n.checked=true;n.dispatchEvent(new Event('change'));}${idle}`);
  assert.ok((await text('#attr-evidence-contradicts')).includes('Synthetic contradicting capture'));
  await click('#attr-claim-detail','Claim history');
  assert.ok((await text('#attr-claim-history')).includes('Evidence changed'));

  // Reuse a real capture from another explicit claim, without preloading a library.
  await lifecycle('#attr-claim-detail','Archive claim');
  await submit('attr-claim-filters',{include_archived:true});
  assert.ok((await text('#attr-claims-list')).includes('Claim archived'));
  await lifecycle('#attr-claim-detail','Restore claim');
  await click('#attribution-workspace > .toolbar[aria-label]','Entities');
  await click('#attr-entities-list','View entity');
  assert.ok((await text('#attr-entity-claims')).includes(address.toLowerCase().slice(0,10)));
  await lifecycle('#attr-entity-detail','Archive entity');
  await submit('attr-entity-filters',{include_archived:true});
  assert.ok((await text('#attr-entities-list')).includes('Archived'));
  await lifecycle('#attr-entity-detail','Restore entity');
  await click('#attr-entity-detail','Create claim for entity');
  await submit('attr-claim-form',{chain:'ethereum',subject_ref:address,relationship:'publicly_declared_by',scope_note:'Separate synthetic disclosure proposition'});
  const second=(await api('/claims?relationship=publicly_declared_by')).data.items[0];
  await click('#attr-claim-detail','Link existing evidence');
  await click('#attr-reuse-list','Choose capture');
  await submit('attr-reuse-form',{stance:'context',directness:'context',rationale:'Reused for contextual review'});
  assert.equal((await api(`/claims/${second.id}/evidence`)).data.total,1);
  await click('#attr-claim-detail','Link existing evidence');await click('#attr-reuse-list','Choose capture');
  await submit('attr-reuse-form',{stance:'context',directness:'context',rationale:'Duplicate link test'});
  assert.ok((await text('#attribution-workspace > .operation-status')).includes('already linked'));
  await click('#attr-recovery','Reload');

  // Review spans pages. A contradiction on a later page is never auto-acknowledged.
  let evolving=(await api('/claims/'+second.id)).data;
  for(let i=0;i<11;i++){
    const response=await api(`/claims/${second.id}/evidence/capture`,'POST',{
      expected_version:evolving.version,
      evidence:{evidence_type:'public_record',origin:'public_osint',title:'Synthetic review page '+i,source_name:'Synthetic source',
        source_url:'https://source.example/page',summary:'Test-only paginated evidence',source_reliability:'reliable',reliability_rationale:'Test provenance'},
      link:{stance:i===10?'contradicts':'supports',directness:'direct',rationale:'Test-only relevance'},
    });
    assert.equal(response.status,201);evolving=response.data.claim;
  }
  await click('#attribution-workspace > .workspace-heading','Reload');
  await click('#attr-claim-detail','Review assessment');
  assert.equal(await evaluate("document.querySelectorAll('[data-review-id]').length"),10);
  await checkAll('[data-review-id]');await click('#attr-review-links','Next');
  assert.equal(await evaluate("document.querySelectorAll('[data-review-id]').length"),2);
  assert.equal(await evaluate("[...document.querySelectorAll('[data-ack-id]')].some(n=>n.checked)"),false);
  assert.ok((await text('#attr-assessment-progress')).includes('10 of 12'));
  await checkAll('[data-review-id]');
  await submit('attr-assessment-form',{assessment:'supported',rationale:'Review all pages',conflict_discussion:'Discuss the later-page contradiction'});
  assert.ok((await text('#attribution-workspace > .operation-status')).includes('Explicitly acknowledge'));
  await checkAll('[data-ack-id]');await submit('attr-assessment-form',{});
  assert.equal((await api('/claims/'+second.id)).data.needs_review,false);
  await click('#attr-claim-detail','Claim history');await click('#attr-claim-history','Next');
  assert.ok((await text('#attr-claim-history')).includes('Assessment changed'));

  // Paginated lists and review navigation use the real API with test-only setup.
  for(let i=0;i<21;i++)assert.equal((await api('/entities','POST',{canonical_name:'Synthetic page entity '+i,entity_type:'organization'})).status,201);
  await click('#attribution-workspace > .toolbar[aria-label]','Entities');
  assert.equal(await evaluate("document.querySelectorAll('#attr-entities-list tbody tr').length"),20);
  await click('#attr-entities-list','Next');assert.equal(await evaluate("document.querySelectorAll('#attr-entities-list tbody tr').length"),2);
  await submit('attr-entity-filters',{search:'page entity 20'});
  assert.equal(await evaluate("document.querySelectorAll('#attr-entities-list tbody tr').length"),1);
  assert.ok((await text('#attr-entities-list')).includes('Synthetic page entity 20'));
  await click('#attribution-workspace > .toolbar[aria-label]','Claims');
  await submit('attr-claim-filters',{relationship:'publicly_declared_by'});
  assert.equal(await evaluate("document.querySelectorAll('#attr-claims-list tbody tr').length"),1);
  await click('#attr-claims-list','View claim');
  await click('#attr-evidence-context','Inspect capture');
  await evaluate('window.scrollTo(0,0)');
  await call('Page.captureScreenshot',{format:'png'}).then(r=>fs.writeFileSync(path.join(work,'attribution.png'),Buffer.from(r.data,'base64')));
  await evaluate("document.getElementById('attr-claim-detail').scrollIntoView({block:'start'})");
  await call('Page.captureScreenshot',{format:'png'}).then(r=>fs.writeFileSync(path.join(work,'attribution-detail.png'),Buffer.from(r.data,'base64')));
  const metrics=await call('Page.getLayoutMetrics');
  await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip:{x:0,y:0,width:metrics.cssContentSize.width,height:metrics.cssContentSize.height,scale:1}})
    .then(r=>fs.writeFileSync(path.join(work,'attribution-full.png'),Buffer.from(r.data,'base64')));
  assert.ok(await evaluate('document.documentElement.scrollWidth<=window.innerWidth+1'));

  // Error messages never echo raw payloads. Real stale/duplicate errors were tested above.
  for(const [code,expected] of [[404,'no longer available'],[422,'Check the public address'],[503,'temporarily unavailable'],[500,'could not be completed']]){
    await evaluate(`window.fetch=()=>Promise.resolve(new Response('SQL Traceback C:\\private at3-browser-test-secret',{status:${code}}))`);
    await click('#attribution-workspace > .workspace-heading','Reload');
    assert.ok((await text('#attribution-workspace > .operation-status')).includes(expected));
    assert.equal((await text('#attribution-workspace')).includes('at3-browser-test-secret'),false);
  }
  await evaluate('window.fetch=attrOriginalFetch');
  const after=state();
  for(const key of Object.keys(before).filter(key=>!key.startsWith('attribution_')))assert.equal(after[key],before[key],`Attribution must not change ${key}`);
  assert.equal(after.attribution_claims,2);assert.equal(after.attribution_evidence,15);
  assert.ok(await evaluate("attrRequests.every(r=>r.url.startsWith('/api/greedy-collector/attribution'))"));
  assert.equal(await evaluate("attrRequests.some(r=>r.method==='DELETE')"),false);
  console.log('Attribution workflows passed: explicit entity/claim/evidence/assessment, unchecked contradictions, immutable replacement, history, lifecycle, pagination, safe errors, and local-only state.');
};
