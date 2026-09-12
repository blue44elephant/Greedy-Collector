const assert=require('node:assert/strict');
const path=require('node:path');
const fs=require('node:fs');
const {execFileSync}=require('node:child_process');

exports.empty=async({evaluate})=>{
  await evaluate(`go('alerts')`);
  assert.ok(await evaluate("document.getElementById('alerts-list').innerText.includes('No alerts have been generated.')"));
  assert.ok(await evaluate("document.getElementById('alerts-workspace').innerText.includes('first monitoring observation is silent')"));
};
exports.review=async({evaluate,call,work})=>{
  execFileSync(process.env.PYTHON||'python',['-B',path.join(__dirname,'browser_alert_fixture.py'),path.join(work,'browser-test.db')],{windowsHide:true,stdio:'pipe'});
  const idle="waitFor(()=>document.getElementById('alerts-workspace').dataset.busy==='false')";
  const filter=async status=>evaluate(`document.getElementById('alerts-status').value=${JSON.stringify(status)};document.getElementById('alerts-status').dispatchEvent(new Event('change'));${idle}`);
  const choose=async trigger=>evaluate(`const f=[...document.querySelectorAll('#alerts-list tbody tr')].find(row=>row.innerText.includes(${JSON.stringify(trigger)}));f.querySelector('button').click();${idle}`);
  await evaluate(`go('alerts')`);
  await evaluate(`window.alertRequests=[];window.originalAlertFetch=window.fetch;window.fetch=(url,options)=>{alertRequests.push({url,method:options?.method||'GET'});return originalAlertFetch(url,options);}`);
  await filter('New');
  assert.ok(await evaluate("alertRequests.some(r=>r.url==='/api/greedy-collector/alerts?status=New')"));
  const count=await evaluate('alertRequests.length');
  await choose('Browser transaction alert');
  assert.equal(await evaluate('alertRequests.length'),count);
  assert.ok(await evaluate("document.getElementById('alert-detail').innerText.includes('0.00000001')"));
  assert.ok(await evaluate("!!button('#alert-detail','Open transaction')"));

  for(const status of ['Reviewed','Escalated','Dismissed','New']){
    await evaluate(`const f=document.getElementById('alert-review');f.elements.status.value='${status}';f.elements.notes.value='Persisted browser analyst note';f.requestSubmit();${idle}`);
    assert.equal(await evaluate("document.querySelector('#alert-review [name=status]').value"),status);
    assert.equal(await evaluate("document.querySelector('#alert-review [name=notes]').value"),'Persisted browser analyst note');
    assert.ok(await evaluate("alertRequests.some(r=>r.method==='PATCH'&&r.url.startsWith('/api/greedy-collector/alerts/'))"));
    await filter(status);await choose('Browser transaction alert');
    assert.equal(await evaluate("document.querySelector('#alert-review [name=notes]').value"),'Persisted browser analyst note');
  }
  await evaluate(`alertRequests.length=0;button('#alert-detail','Investigate wallet').click();waitFor(()=>document.getElementById('lookup-form').dataset.busy==='false')`);
  assert.deepEqual(await evaluate('alertRequests.map(r=>r.url)'),['/api/greedy-collector/resolve','/api/greedy-collector/lookup/address']);
  await evaluate(`go('alerts')`);await choose('Browser transaction alert');
  await evaluate(`alertRequests.length=0;button('#alert-detail','Open transaction').click();waitFor(()=>document.getElementById('lookup-form').dataset.busy==='false')`);
  assert.deepEqual(await evaluate('alertRequests.map(r=>r.url)'),['/api/greedy-collector/resolve','/api/greedy-collector/lookup/tx']);
  await evaluate(`go('alerts')`);await filter('');await choose('Browser risk-only alert');
  assert.ok(await evaluate("document.getElementById('alert-detail').innerText.includes('No transaction reference')"));
  assert.equal(await evaluate("!!button('#alert-detail','Open transaction')"),false);
  await evaluate(`alertRequests.length=0;button('#alert-detail','Open graph').click();waitFor(()=>document.querySelector('#graph-workspace form').dataset.busy==='false')`);
  assert.equal(await evaluate('alertRequests.length'),1);
  assert.ok(await evaluate("alertRequests[0].url.includes('/graph?hops=')"));
  assert.equal(await evaluate("document.querySelector('#graph-workspace [name=address]').value"),'0x'+'4'.repeat(40));
  await evaluate(`go('alerts')`);await choose('Browser risk-only alert');

  // Error responses are injected only in this automated browser test.
  for(const [status,message] of [[404,'This alert no longer exists.'],[422,'The alert update was not accepted.'],[500,'The request could not be completed.']]){
    await evaluate(`window.fetch=(url,options)=>options?.method==='PATCH'?Promise.resolve(new Response(JSON.stringify({detail:'https://provider.invalid/browser-test-only-key SQLITE internal error'}),{status:${status},headers:{'Content-Type':'application/json'}})):originalAlertFetch(url,options);document.getElementById('alert-review').requestSubmit();${idle}`);
    assert.ok(await evaluate(`document.querySelector('#alerts-workspace > .operation-status').innerText.includes(${JSON.stringify(message)})`));
    assert.equal(await evaluate("document.getElementById('alerts-workspace').innerText.includes('browser-test-only-key')"),false);
  }
  await evaluate(`window.fetch=()=>Promise.resolve(new Response(JSON.stringify({alerts:[{unexpected:'browser-test-only-key'}]}),{status:200,headers:{'Content-Type':'application/json'}}));button('#alerts-workspace','Refresh alerts').click();${idle}`);
  assert.ok(await evaluate("document.querySelector('#alerts-workspace > .operation-status').innerText.includes('unexpected alerts response')"));
  assert.equal(await evaluate("document.getElementById('alerts-workspace').innerText.includes('browser-test-only-key')"),false);
  await evaluate(`window.fetch=window.originalAlertFetch;button('#alerts-workspace','Refresh alerts').click();${idle}`);
  await choose('Browser risk-only alert');
  await evaluate('window.scrollTo(0,0)');
  const metrics=await call('Page.getLayoutMetrics');
  await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip:{x:0,y:0,width:metrics.cssContentSize.width,height:metrics.cssContentSize.height,scale:1}}).then(result=>fs.writeFileSync(path.join(work,'alerts.png'),Buffer.from(result.data,'base64')));
  console.log('Alerts browser passed: empty state, filtering, transaction/risk-only detail, all review statuses, persisted notes, wallet/transaction/graph actions, missing/invalid/server/malformed errors.');
};
