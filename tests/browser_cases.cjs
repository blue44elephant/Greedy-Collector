// Test-only workflow against the isolated browser server's actual SQLite case APIs.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
module.exports=async({evaluate,call,work})=>{
  const idle="waitFor(()=>document.getElementById('cases-workspace').dataset.busy==='false')";
  const wallet='1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa', hash='0x'+'b'.repeat(64);
  const text=selector=>evaluate(`document.querySelector(${JSON.stringify(selector)}).innerText`);
  await evaluate(`go('cases')`);
  assert.ok((await text('#cases-list')).includes('No cases have been created.'));
  await evaluate(`window.caseRequests=[];window.originalCaseFetch=window.fetch;window.fetch=(url,options)=>{caseRequests.push({url,method:options?.method||'GET'});return originalCaseFetch(url,options);}`);
  await evaluate(`const f=document.getElementById('case-create');f.elements.title.value='Browser case <script>test</script>';f.elements.description.value='Test-only analyst material';f.requestSubmit();${idle}`);
  assert.ok((await text('#case-overview')).includes('Browser case <script>test</script>'));
  assert.equal(await evaluate("!!document.querySelector('#case-overview script')"),false);
  for(const [selector,message] of [['#case-entities','No entities have been added to this case.'],['#case-notes','No analyst notes.'],['#case-alerts','No alerts are associated with this case.'],['#case-attachments','No attachments.']]) assert.ok((await text(selector)).includes(message));
  const id=await evaluate("originalCaseFetch('/api/greedy-collector/cases').then(r=>r.json()).then(r=>r.cases[0].id)");
  await evaluate(`window.currentCaseId=${JSON.stringify(id)}`);
  const open=()=>evaluate(`document.dispatchEvent(new CustomEvent('open-case',{detail:{id:currentCaseId}}));${idle}`);
  const search=async value=>{
    await evaluate(`go('wallet')`);
    await evaluate(`document.getElementById('wallet-address').value=${JSON.stringify(value)};document.getElementById('lookup-form').requestSubmit();waitFor(()=>document.getElementById('lookup-form').dataset.busy==='false')`);
  };
  const add=async scope=>{
    await evaluate(`caseRequests.length=0;button(${JSON.stringify(scope)},'Add to case').click();waitFor(()=>document.getElementById('case-picker')?.dataset.busy==='false')`);
    assert.equal(await evaluate("document.querySelector('#case-picker select').options[1].value"),id);
    await evaluate(`const f=document.querySelector('#case-picker form');f.elements.case_id.value=currentCaseId;f.requestSubmit();waitFor(()=>document.getElementById('case-picker').dataset.busy==='false')`);
    assert.ok((await text('#case-picker')).includes('Reference added'));
    assert.equal(await evaluate("caseRequests.some(r=>r.url.includes('/lookup/'))"),false);
    await evaluate(`button('#case-picker','Open case').click();${idle}`);
  };
  await search(wallet);await add('#wallet-case-action');
  assert.ok(await evaluate(`document.querySelector('#case-entities [title=${JSON.stringify(wallet)}]')!==null`));
  await search(hash);await add('#transaction-result');
  assert.equal(await evaluate("document.querySelectorAll('#case-entities tbody tr').length"),2);
  await evaluate(`const f=document.getElementById('case-entity');caseRequests.length=0;f.elements.entity_type.value='wallet';f.elements.entity_ref.value='unsupported reference';f.requestSubmit();${idle}`);
  assert.ok((await text('#cases-workspace > .operation-status')).includes('does not match'));
  assert.deepEqual(await evaluate('caseRequests.map(r=>r.url)'),['/api/greedy-collector/resolve']);
  await evaluate(`const f=document.getElementById('case-note');f.elements.body.value='Persisted browser case note';f.requestSubmit();${idle}`);
  assert.ok((await text('#case-notes')).includes('Persisted browser case note'));
  assert.ok((await text('#case-notes')).includes('analyst'));
  // Same user filename twice must preserve both real uploads, with unique stored names.
  for(const content of ['First harmless attachment','Second harmless attachment']){
    await evaluate(`const f=document.getElementById('case-upload');const transfer=new DataTransfer();transfer.items.add(new File([${JSON.stringify(content)}],'note.txt',{type:'text/plain'}));f.elements.file.files=transfer.files;f.requestSubmit();${idle}`);
  }
  const attachments=await evaluate("originalCaseFetch('/api/greedy-collector/cases/'+currentCaseId).then(r=>r.json()).then(r=>r.entities.filter(e=>e.entity_type==='attachment'))");
  assert.equal(attachments.length,2);assert.notEqual(attachments[0].entity_ref,attachments[1].entity_ref);
  assert.deepEqual(attachments.map(item=>fs.readFileSync(path.join(work,'data',item.entity_ref),'utf8')),['First harmless attachment','Second harmless attachment']);
  assert.equal(await evaluate("!!button('#case-attachments','Download')"),false);
  await evaluate(`caseRequests.length=0;button('#case-entities','Investigate wallet').click();waitFor(()=>document.getElementById('lookup-form').dataset.busy==='false')`);
  assert.deepEqual(await evaluate('caseRequests.map(r=>r.url)'),['/api/greedy-collector/resolve','/api/greedy-collector/lookup/address']);
  await open();
  await evaluate(`caseRequests.length=0;button('#case-entities','Open transaction').click();waitFor(()=>document.getElementById('lookup-form').dataset.busy==='false')`);
  assert.deepEqual(await evaluate('caseRequests.map(r=>r.url)'),['/api/greedy-collector/resolve','/api/greedy-collector/lookup/tx']);
  await open();
  await evaluate(`caseRequests.length=0;button('#case-entities','Open graph').click();waitFor(()=>document.querySelector('#graph-workspace form').dataset.busy==='false')`);
  assert.equal(await evaluate('caseRequests.length'),1);
  assert.ok(await evaluate("caseRequests[0].url.includes('/graph?hops=')"));
  await evaluate("document.querySelector('#graph-workspace .graph-node').dispatchEvent(new MouseEvent('click',{bubbles:true}))");
  await add('#graph-detail');
  assert.equal(await evaluate("document.querySelectorAll('#case-entities tbody tr').length"),3);

  // Case association is produced by the real monitoring workflow, not inferred in JavaScript.
  await evaluate(`go('monitoring')`);
  assert.equal(await evaluate("document.querySelector('#monitoring-create [name=case_id]').tagName"),'SELECT');
  assert.ok(await evaluate("[...document.querySelector('#monitoring-create [name=case_id]').options].some(o=>o.value===currentCaseId&&o.textContent.includes('Browser case'))"));
  const midle="waitFor(()=>document.getElementById('monitoring-workspace').dataset.busy==='false')";
  await evaluate(`const f=document.getElementById('monitoring-create');f.elements.chain.value='bitcoin';f.elements.address.value='3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy';f.elements.label.value='Case-linked watch';f.elements.case_id.value=currentCaseId;f.requestSubmit();${midle}`);
  for(let i=0;i<3;i++) await evaluate(`button('#monitoring-selected','Check now').click();${midle}`);
  await evaluate(`button('#monitoring-selected','Disable watch').click();${midle}`);
  await open();
  assert.ok((await text('#case-alerts')).includes('New incoming transaction'));
  await evaluate(`button('#case-alerts','Open alert').click();waitFor(()=>document.getElementById('alerts-workspace').dataset.busy==='false')`);
  assert.equal(await evaluate("document.getElementById('alerts-workspace').hidden"),false);
  assert.ok((await text('#alert-detail')).includes('Browser case <script>test</script>'));
  await evaluate(`button('#alert-detail','Open case').click();${idle}`);
  assert.equal(await evaluate("document.getElementById('cases-workspace').hidden"),false);

  for(const [format,extension] of [['markdown','md'],['html','html'],['json','json'],['pdf','pdf']]){
    await evaluate(`const f=document.getElementById('case-report');f.elements.format.value='${format}';f.requestSubmit();${idle}`);
    const destination=path.join(work,`case-${id}.${extension}`);
    for(let n=0;n<100&&!fs.existsSync(destination);n++)await new Promise(r=>setTimeout(r,50));
    assert.ok(fs.existsSync(destination),`Downloaded ${format}`);
    const bytes=fs.readFileSync(destination);assert.ok(bytes.length>0);assert.equal(bytes.includes(Buffer.from('browser-test-only-key')),false);
    if(format==='pdf')assert.ok(bytes.subarray(0,5).equals(Buffer.from('%PDF-')));
    else {assert.ok(bytes.toString().includes('Persisted browser case note'));assert.ok(bytes.toString().includes('New incoming transaction'));}
    if(format==='html')assert.equal(bytes.toString().includes('<script>test</script>'),false);
  }
  // API failures never render raw internals, and stale references have a clear case error.
  for(const [route,status,selector] of [['/notes',500,'#case-note'],['/attachments',500,'#case-upload'],['/reports/',422,'#case-report']]){
    await evaluate(`window.fetch=(url,options)=>url.includes(${JSON.stringify(route)})?Promise.resolve(new Response(JSON.stringify({detail:'SQLITE C:/private browser-test-only-key'}),{status:${status},headers:{'Content-Type':'application/json'}})):originalCaseFetch(url,options)`);
    if(selector==='#case-note')await evaluate("document.querySelector('#case-note [name=body]').value='A failed note'");
    if(selector==='#case-upload')await evaluate("{const transfer=new DataTransfer();transfer.items.add(new File(['Test'],'test.txt'));document.querySelector('#case-upload [name=file]').files=transfer.files;}");
    await evaluate(`document.querySelector(${JSON.stringify(selector)}).requestSubmit();${idle}`);
    assert.ok((await text('#cases-workspace > .operation-status')).includes('case operation'));
    assert.equal((await text('#cases-workspace')).includes('browser-test-only-key'),false);
  }
  await evaluate(`window.fetch=originalCaseFetch;document.dispatchEvent(new CustomEvent('open-case',{detail:{id:'missing-case'}}));${idle}`);
  assert.ok((await text('#cases-workspace > .operation-status')).includes('no longer exists'));
  await open();
  assert.ok((await text('#case-notes')).includes('Persisted browser case note'));
  assert.equal(await evaluate("document.body.innerText.includes('browser-test-only-key')"),false);
  await evaluate('window.scrollTo(0,0)');
  const metrics=await call('Page.getLayoutMetrics');
  await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip:{x:0,y:0,width:metrics.cssContentSize.width,height:metrics.cssContentSize.height,scale:1}}).then(r=>fs.writeFileSync(path.join(work,'cases.png'),Buffer.from(r.data,'base64')));
  console.log('Cases browser passed: empty/create/detail, Wallet/transaction/Graph add-to-case, references without collection, notes, collision-safe local uploads, real watch/alert association, cross-navigation, all report downloads, safe errors.');
};
