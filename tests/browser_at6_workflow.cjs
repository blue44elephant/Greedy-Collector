const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
module.exports=async({evaluate,work,mode})=>{
  const prefix='/api/greedy-collector';
  const idle=id=>`waitFor(()=>document.getElementById(${JSON.stringify(id)})?.dataset.busy!=='true')`;
  const text=selector=>evaluate(`document.querySelector(${JSON.stringify(selector)}).innerText`);
  const click=(selector,label,scope='attribution-workspace')=>evaluate(`button(${JSON.stringify(selector)},${JSON.stringify(label)}).click();${idle(scope)}`);
  const submit=(id,values,scope)=>evaluate(`{const f=document.getElementById(${JSON.stringify(id)});for(const [k,v] of Object.entries(${JSON.stringify(values)})){if(f.elements[k].type==='checkbox')f.elements[k].checked=v;else f.elements[k].value=v;}f.requestSubmit();}${idle(scope)}`);
  const api=async(suffix,method='GET',body)=>{
    const result=await evaluate(`fetch(${JSON.stringify(prefix+suffix)},{method:${JSON.stringify(method)},headers:{'Content-Type':'application/json'},${body===undefined?'':`body:JSON.stringify(${JSON.stringify(body)}),`}}).then(async r=>({status:r.status,data:await r.json()}))`);
    assert.ok(result.status<300,JSON.stringify(result));return result.data;
  };
  await evaluate("window.at6Requests=[];window.at6Original=window.fetch;window.fetch=(url,options)=>{at6Requests.push({url:String(url),method:options?.method||'GET'});return at6Original(url,options);}");
  await evaluate("go('cases')");
  await submit('case-create',{title:'Synthetic AT6 case',description:'Existing case material remains'},'cases-workspace');
  await evaluate(idle('case-attribution'));
  const c=(await api('/cases')).cases[0];
  await submit('case-note',{body:'Independent case note'},'cases-workspace');await evaluate(idle('case-attribution'));
  const downloads=async()=>{
    const result={};
    for(const [format,extension] of [['markdown','md'],['html','html'],['json','json'],['pdf','pdf']]){
      await submit('case-report',{format},'cases-workspace');const file=path.join(work,`case-${c.id}.${extension}`);
      for(let i=0;i<100&&!fs.existsSync(file);i++)await new Promise(r=>setTimeout(r,50));
      assert.ok(fs.existsSync(file),format);const bytes=fs.readFileSync(file);result[format]=bytes;
      if(format==='pdf')assert.equal(bytes.subarray(0,5).toString(),'%PDF-');
      else assert.ok(bytes.toString().includes('Independent case note'));
      assert.equal(bytes.includes(Buffer.from('at6-browser-test-secret')),false);
    }return result;
  };
  if(mode==='unmigrated'){
    assert.ok((await text('#case-attribution')).includes('storage is not initialized'));
    await click('#case-attribution','Add attribution','case-attribution');
    assert.ok((await text('#case-attribution')).includes('storage is not initialized'));
    await downloads();assert.ok((await text('#case-notes')).includes('Independent case note'));
    assert.equal(await evaluate("at6Requests.some(r=>r.method==='POST'&&r.url.includes('/attribution/'))"),false);
    console.log('AT-6 unmigrated Cases, notes and all report formats remain usable.');return;
  }
  assert.ok((await text('#case-attribution')).includes('No attribution references'));
  const entity=await api('/attribution/entities','POST',{canonical_name:'Synthetic AT6 entity',entity_type:'service'});
  let claim=await api('/attribution/claims','POST',{entity_id:entity.id,chain:'ethereum',subject_ref:'0x'+'ab'.repeat(20),relationship:'operated_by',scope_note:'Explicit test scope'});
  const links=[];
  for(const stance of ['supports','contradicts','context']){
    const result=await api(`/attribution/claims/${claim.id}/evidence/capture`,'POST',{expected_version:claim.version,
      evidence:{evidence_type:'public_record',title:`Synthetic ${stance} citation`,summary:'Retained source material',source_name:'Synthetic source',source_url:'https://example.invalid/record',origin:'public_osint',source_reliability:'reliable',reliability_rationale:'Explicit test verification'},
      link:{stance,directness:stance==='context'?'context':'direct',rationale:'Explicit source relevance'}});
    claim=result.claim;links.push(result.link);
  }
  const assess=async category=>{claim=await api(`/attribution/claims/${claim.id}/assessment`,'POST',{expected_version:claim.version,assessment:category,rationale:'Explicit analyst conclusion',reviewed_link_ids:links.map(l=>l.id),acknowledged_contradictions:links.filter(l=>l.stance==='contradicts').map(l=>l.id),conflict_discussion:'Contradiction retained and considered'});};
  await assess('supported');
  assert.equal((await api(`/attribution/cases/${c.id}/references`)).total,0);
  // Case -> choose real paginated claim -> explicit confirm.
  await click('#case-attribution','Add attribution','case-attribution');
  await click('#case-attribution-picker','Choose reference','case-attribution');
  assert.equal((await api(`/attribution/cases/${c.id}/references`)).total,0);
  await click('#case-attribution-picker','Confirm add attribution','case-attribution');
  let rows=await api(`/attribution/cases/${c.id}/references`);assert.equal(rows.total,1);
  const originalPin=rows.items[0].pinned;
  assert.ok((await text('#case-attribution')).includes('Pinned assessment: Supported'));
  assert.ok((await text('#case-attribution')).includes('1 supporting / 1 contradicting / 1 contextual'));
  await click('#case-attribution','Open attribution','attribution-workspace');
  assert.ok((await text('#attr-claim-detail')).includes(claim.id));
  // Attribution -> existing case selection: duplicate does not overwrite the original pin.
  await click('#attr-claim-detail','Add to case','case-picker');
  await evaluate(`{const f=document.querySelector('#case-picker form');f.elements.case_id.value=${JSON.stringify(c.id)};f.requestSubmit();}${idle('case-picker')}`);
  assert.ok((await text('#case-picker')).includes('already in the case'));assert.equal((await api(`/attribution/cases/${c.id}/references`)).total,1);
  await click('#case-picker','Cancel','case-picker');
  // Direct entity reference through the same existing case selector.
  await evaluate(`document.dispatchEvent(new CustomEvent('open-attribution',{detail:{action:'open_entity',id:${JSON.stringify(entity.id)}}}));${idle('attribution-workspace')}`);
  await click('#attr-entity-detail','Add to case','case-picker');
  await evaluate(`{const f=document.querySelector('#case-picker form');f.elements.case_id.value=${JSON.stringify(c.id)};f.requestSubmit();}${idle('case-picker')}`);
  await click('#case-picker','Open case','cases-workspace');await evaluate(idle('case-attribution'));
  assert.equal((await api(`/attribution/cases/${c.id}/references`)).total,2);
  assert.ok((await text('#case-attribution')).includes('Entity reference'));
  const downloaded=await downloads();
  for(const format of ['markdown','html']){
    for(const label of ['Attribution Assessment','Pinned assessment: supported','Supporting evidence','Contradicting evidence','Contextual evidence'])assert.ok(downloaded[format].toString().includes(label),label);
  }
  const pinnedReport=JSON.parse(downloaded.json.toString());
  assert.equal(pinnedReport.attribution.references.find(r=>r.pinned.claim).pinned.claim.assessment,'supported');
  await assess('rejected');
  const withdrawn=await api(`/attribution/claims/${claim.id}/evidence/${links[0].id}/withdraw`,'POST',{expected_version:claim.version,reason:'Later source withdrawal'});claim=withdrawn.claim;
  await evaluate("go('cases')");await evaluate(idle('case-attribution'));
  assert.ok((await text('#case-attribution')).includes('Pinned assessment: Supported'));
  assert.ok((await text('#case-attribution')).includes('Current assessment: Rejected'));
  assert.ok((await text('#case-attribution')).includes('Review required'));
  rows=await api(`/attribution/cases/${c.id}/references`);assert.deepEqual(rows.items.find(r=>r.pinned.claim).pinned,originalPin);
  const fresh=await api(`/reports/${c.id}?format=json`);
  assert.equal(fresh.attribution.references.find(r=>r.pinned.claim).pinned.claim.assessment,'supported');
  assert.equal(fresh.attribution.references.find(r=>r.pinned.claim).current.claim.assessment,'rejected');
  assert.deepEqual(fs.readFileSync(path.join(work,`case-${c.id}.json`)),downloaded.json);
  assert.equal(await evaluate("at6Requests.some(r=>r.url.includes('/lookup/')||r.url.includes('/kyc/screen'))"),false);
  console.log('AT-6 bidirectional case handoffs, entity/claim pins, duplicate handling, all report downloads, contradictions, historical fidelity and current review status passed.');
};
