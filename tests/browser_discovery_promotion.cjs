const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
module.exports=async({evaluate,work,mode,httpPort,traffic})=>{
  const prefix=`http://127.0.0.1:${httpPort}/api/greedy-collector`,address='0x'+'ab'.repeat(20);
  const api=async(suffix,body,method)=>{const r=await fetch(prefix+suffix,{method:method||(body?'POST':'GET'),headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});assert.ok(r.ok,await r.clone().text());return r.json();};
  const busy=scope=>evaluate(`waitFor(()=>{const root=document.getElementById('${scope}-workspace');return root.dataset.busy!=='true'&&!root.querySelector('[data-busy="true"]');})`);
  const click=async(scope,label)=>{await evaluate(`button('#${scope}-workspace',${JSON.stringify(label)}).click()`);await busy(scope);};
  const text=scope=>evaluate(`document.getElementById('${scope}-workspace').innerText`);
  const githubCalls=()=>fs.existsSync(path.join(work,'github-calls'))?Number(fs.readFileSync(path.join(work,'github-calls'),'utf8')):0;
  if(mode==='promotion_unmigrated'){
    assert.ok((await text('discovery')).includes('Discovery storage is not initialized'));
    const response=await fetch(prefix+'/discovery/observations/missing/promotion-preview');assert.equal(response.status,503);
    assert.equal((await response.json()).detail.code,'promotion_schema_unavailable');
    for(const scope of ['wallet','graph','monitoring','alerts','cases','labels','research','attribution','discovery'])await evaluate(`go('${scope}')`);
    console.log('ED-6 unmigrated browser passed');return;
  }
  await api('/labels/manual',{chain:'ethereum',address,label:'ED-6 test annotation',type:'Exchange',source:'ED-6 test source',confidence:.8});
  const entity=await api('/attribution/entities',{canonical_name:'ED-6 test existing entity'});
  let claim=await api('/attribution/claims',{entity_id:entity.id,chain:'ethereum',subject_ref:address,relationship:'operated_by',scope_note:'Explicit test scope'});
  async function run(transform,refresh=false){
    await evaluate(`go('discovery')`);await busy('discovery');
    await evaluate(`document.querySelector('#discovery-subject input').value='${address}';document.querySelector('#discovery-subject input').dispatchEvent(new Event('input',{bubbles:true}));document.getElementById('discovery-subject').requestSubmit()`);await busy('discovery');
    await evaluate(`document.querySelectorAll('#discovery-transforms input[type=checkbox]').forEach(n=>{n.checked=n.closest('[data-transform]').dataset.transform===${JSON.stringify(transform)};n.dispatchEvent(new Event('change',{bubbles:true}));});document.querySelector('#discovery-plan [name=refresh]').checked=${refresh};document.querySelector('#discovery-plan [name=refresh]').dispatchEvent(new Event('change',{bubbles:true}));`);
    await click('discovery','Plan selected pivots');await click('discovery','Run discovery');
    await evaluate(`waitFor(()=>document.getElementById('discovery-run').dataset.status==='completed')`);
    const id=await evaluate(`document.getElementById('discovery-run').dataset.runId`);
    await evaluate(`waitFor(()=>!!button('#discovery-results','Inspect result'))`);await click('discovery','Inspect result');
    return (await api('/discovery/runs/'+id+'/results')).items[0];
  }
  const local=await run('wallet.local_labels');
  assert.equal(await evaluate(`!!button('#discovery-promotion','Use as attribution evidence')`),false);
  if(mode==='promotion_partial'){
    assert.ok((await text('discovery')).includes('Discovery promotion storage is not initialized'));
    assert.equal((await api('/discovery/runs')).total,1);assert.equal((await api('/attribution/claims')).total,1);
    for(const scope of ['wallet','graph','monitoring','alerts','cases','labels','research','attribution','discovery'])await evaluate(`go('${scope}')`);
    console.log('ED-6 partial migration browser passed');return;
  }
  async function review(status){
    await evaluate(`document.querySelector('#discovery-review [name=status]').value=${JSON.stringify(status)};document.querySelector('#discovery-review [name=reason]').value='ED-6 explicit test review';document.getElementById('discovery-review').requestSubmit()`);await busy('discovery');
  }
  await review('irrelevant');assert.equal(await evaluate(`!!button('#discovery-promotion','Use as attribution evidence')`),false);await review('relevant');
  async function promote(item,stance){
    const calls=githubCalls(),entities=(await api('/attribution/entities')).total,claims=(await api('/attribution/claims')).total;
    await click('discovery','Use as attribution evidence');await busy('attribution');
    assert.ok((await text('attribution')).includes(item.observation.id));
    await click('attribution','Choose claim');
    assert.equal(await evaluate(`document.querySelector('#attr-handoff-confirm [name=stance]').value`),'');
    await evaluate(`document.querySelector('#attr-handoff-confirm [name=stance]').value='${stance}';document.querySelector('#attr-handoff-confirm [name=directness]').value='${stance==='context'?'context':'indirect'}';document.querySelector('#attr-handoff-confirm [name=rationale]').value='Explicit ED-6 test rationale';document.querySelector('#attr-handoff-confirm [name=confirmed]').checked=true;`);
    await click('attribution','Preview promotion');await evaluate(`document.getElementById('attr-handoff-confirm').requestSubmit()`);await busy('attribution');
    assert.ok((await text('attribution')).includes('Promoted to immutable evidence'),await text('attribution'));
    assert.equal(githubCalls(),calls);assert.equal((await api('/attribution/entities')).total,entities);assert.equal((await api('/attribution/claims')).total,claims);
    const history=await api('/discovery/results/'+item.result.id+'/promotions');
    const saved=history.items.find(p=>p.observation_id===item.observation.id);assert.ok(saved);assert.equal(saved.stance,stance);
    await click('attribution','Open attribution');assert.ok((await text('attribution')).includes(claim.id));
    await click('attribution','Inspect capture');assert.ok((await text('attribution')).includes('Discovery observation provenance'));
    claim=await api('/attribution/claims/'+claim.id);assert.equal(claim.assessment,'unassessed');assert.ok(claim.needs_review);
    return saved;
  }
  const first=await promote(local,'supports');const capture=await api('/attribution/evidence/'+first.evidence_id);
  assert.equal(capture.origin,'analyst_added');assert.equal(capture.metadata_json.observation.source_snapshot.record.confidence,.8);
  await evaluate(`(async()=>{const body=new FormData();body.append('file',new Blob([${JSON.stringify('chain,address,label,type,source,confidence\nethereum,'+address+',ED-6 test annotation,Bridge,ED-6 test source,0.2\n')}],{type:'text/csv'}),'test.csv');const r=await fetch('/api/greedy-collector/labels/import',{method:'POST',body});if(!r.ok)throw Error('Test Label update failed');})()`);
  assert.deepEqual(await api('/attribution/evidence/'+first.evidence_id),capture);
  const changed=await run('wallet.local_labels',true);assert.equal(await evaluate(`!!button('#discovery-promotion','Use as attribution evidence')`),false);
  await review('relevant');await promote(changed,'contradicts');
  const github=await run('wallet.public_code_mentions');await review('relevant');const gh=await promote(github,'context');
  const old=await api('/attribution/evidence/'+gh.evidence_id);assert.equal(old.origin,'public_osint');assert.ok(JSON.stringify(old).includes('test/browser-fixture'));
  fs.writeFileSync(path.join(work,'github-mode'),'changed');const newer=await run('wallet.public_code_mentions',true);
  assert.equal(await evaluate(`!!button('#discovery-promotion','Use as attribution evidence')`),false);assert.deepEqual(await api('/attribution/evidence/'+gh.evidence_id),old);
  await review('relevant');await promote(newer,'context');
  const prev=await api('/discovery/observations/'+newer.observation.id+'/promotion-preview');
  const duplicate=await fetch(prefix+'/discovery/observations/'+newer.observation.id+'/promote',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({result_id:newer.result.id,claim_id:claim.id,expected_claim_version:claim.version,expected_source_fingerprint:prev.source_fingerprint,link:{stance:'context',directness:'context',rationale:'Duplicate test'}})});
  assert.equal(duplicate.status,409);assert.equal((await api('/discovery/results/'+newer.result.id+'/promotions')).total,2);
  // Explicit claim creation returns to the selected observation with pending
  // decisions intact, and creates no evidence until separately confirmed.
  await evaluate(`go('discovery')`);await busy('discovery');await click('discovery','Inspect result');
  await click('discovery','Use as attribution evidence');await busy('attribution');await click('attribution','Choose claim');
  await evaluate(`const f=document.getElementById('attr-handoff-confirm');f.elements.stance.value='context';f.elements.directness.value='context';f.elements.rationale.value='Retain explicit pending decisions';`);
  const captures=(await api('/attribution/evidence')).total;
  await click('attribution','Create attribution claim');
  assert.equal(await evaluate(`document.querySelector('#attr-claim-form [name=subject_ref]').value`),address);
  assert.equal(await evaluate(`document.querySelector('#attr-claim-form [name=relationship]').value`),'');
  await click('attribution','Create a new entity');
  await evaluate(`const f=document.getElementById('attr-entity-form');f.elements.canonical_name.value='Explicit ED-6 second entity';f.elements.entity_type.value='service';f.requestSubmit();`);await busy('attribution');
  await click('attribution','Create claim for entity');
  await evaluate(`const f=document.getElementById('attr-claim-form');f.elements.relationship.value='operated_by';f.elements.scope_note.value='Explicit separate claim scope';f.requestSubmit();`);await busy('attribution');
  assert.equal(await evaluate(`document.querySelector('#attr-handoff-confirm [name=rationale]').value`),'Retain explicit pending decisions');
  assert.equal(await evaluate(`document.querySelector('#attr-handoff-confirm [name=stance]').value`),'context');
  assert.ok((await text('attribution')).includes(newer.observation.id));assert.equal((await api('/attribution/evidence')).total,captures);
  await click('attribution','Back to Discovery');await busy('discovery');
  assert.ok((await text('discovery')).includes(newer.observation.id));await click('discovery','Reload result');
  assert.ok((await text('discovery')).includes('Promoted: 2'));
  // Chromium's native date input loads an inline calendar SVG, without HTTP.
  assert.deepEqual(traffic.filter(url=>!url.startsWith(`http://127.0.0.1:${httpPort}/`)&&!url.startsWith('data:image/svg+xml;base64,')),[]);assert.equal(traffic.some(url=>url.includes('/lookup/')),false);
  console.log('ED-6 Local Label/GitHub/contradiction/changed material/duplicate browser workflows passed.');
};
