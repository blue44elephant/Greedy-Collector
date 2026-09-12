// This workflow runs only on browser_server.py with its temporary DB and provider fixtures.
const assert=require('node:assert/strict');const fs=require('node:fs');const path=require('node:path');
const {execFileSync}=require('node:child_process');
module.exports=async({evaluate,call,work})=>{
  const idle="waitFor(()=>document.getElementById('research-workspace').dataset.busy==='false')";
  const text=selector=>evaluate(`document.querySelector(${JSON.stringify(selector)}).innerText`);
  const state=()=>JSON.parse(execFileSync('python',['-c',
    "import sqlite3,json,sys; from pathlib import Path; p=Path(sys.argv[1]).resolve(); assert p.name=='browser-test.db' and p.parent.name.startswith('gc-browser-'); c=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True); print(json.dumps({t:c.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ['addresses','labels','case_entities','kyc_screening_runs','kyc_matches']})); c.close()",
    path.join(work,'browser-test.db')],{cwd:work,windowsHide:true,encoding:'utf8'}));
  const before=state();
  await evaluate("window.researchRequests=[];window.originalResearchFetch=window.fetch;window.fetch=(url,options)=>{researchRequests.push({url,method:options?.method||'GET'});return originalResearchFetch(url,options);}");
  await evaluate("go('research')");
  assert.ok((await text('#research-capabilities')).includes('25 sources: 7 automated, 18 manual'));
  await evaluate("document.querySelector('#research-capabilities details').open=true");
  assert.equal(await evaluate("document.querySelectorAll('#research-capabilities tbody tr').length"),25);
  for(const source of ['OpenSanctions','VirusTotal','urlscan.io'])assert.ok(await evaluate(`[...document.querySelectorAll('#research-capabilities tr')].some(row=>row.textContent.includes(${JSON.stringify(source)})&&row.textContent.includes('Configured'))`));
  assert.equal((await text('#research-workspace')).includes('browser-test-only-key'),false);
  await evaluate("document.querySelector('#research-capabilities details').open=false;document.querySelector('#research-query [name=name]').value='Typing does not query';document.querySelector('#research-query [name=name]').dispatchEvent(new Event('input',{bubbles:true}))");
  assert.equal(await evaluate("researchRequests.some(r=>r.url.endsWith('/kyc/screen'))"),false);
  const submit=async(name,domain='',manual=true)=>evaluate(`const f=document.getElementById('research-query');f.elements.name.value=${JSON.stringify(name)};f.elements.domain.value=${JSON.stringify(domain)};f.elements.include_manual_sources.checked=${manual};f.requestSubmit();${idle}`);
  await submit('  ');
  assert.ok((await text('#research-workspace > .operation-status')).includes('Enter a name'));
  await submit('Fixture Company','https://example.org/path');
  assert.ok((await text('#research-workspace > .operation-status')).includes('without a URL'));
  assert.equal(await evaluate("researchRequests.filter(r=>r.url.endsWith('/kyc/screen')).length"),0);
  await submit('Fixture Company');
  assert.ok((await text('#research-matches')).includes('Fixture Company'));
  assert.ok((await text('#research-coverage')).includes('Successfully checked: 4'));
  assert.ok((await text('#research-coverage')).includes('Not run — no domain supplied'));
  assert.equal(await evaluate("document.getElementById('research-unavailable').hidden"),true);
  assert.ok((await text('#research-manual')).includes('OpenCorporates'));
  assert.ok((await text('#research-manual')).includes('Companies House'));
  assert.equal(await evaluate("document.querySelectorAll('#research-manual a').length"),18);
  assert.ok(await evaluate("[...document.querySelectorAll('#research-manual a')].every(a=>a.target==='_blank'&&a.rel==='noopener noreferrer'&&a.referrerPolicy==='no-referrer'&&a.href.startsWith('https://'))"));
  const posts=await evaluate("researchRequests.filter(r=>r.url.endsWith('/kyc/screen')).length");
  await evaluate("go('wallet')");await evaluate("go('research')");
  await evaluate(`button('#research-matches','View match').click();${idle}`);
  assert.equal(await evaluate("researchRequests.filter(r=>r.url.endsWith('/kyc/screen')).length"),posts);
  assert.ok((await text('#research-detail')).includes('does not confirm ownership'));
  await evaluate("document.querySelector('#research-detail details').open=true");
  assert.ok((await text('#research-detail')).includes('Retained source evidence'));
  assert.ok((await text('#research-detail')).includes('[redacted]'));
  assert.equal((await text('#research-detail')).includes('browser-test-only-key'),false);
  const review=async status=>evaluate(`const f=document.getElementById('research-review');f.elements.review_status.value=${JSON.stringify(status)};f.requestSubmit();${idle}`);
  for(const status of ['False positive','Potential match','Confirmed source match','Unreviewed']){
    await review(status);assert.ok((await text('#research-matches')).includes(status));
    assert.equal(await evaluate("document.querySelector('#research-review [name=review_status]').value"),status);
  }
  await evaluate("Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async value=>{window.copiedResearch=value;}}})");
  await evaluate(`button('#research-detail','Copy result').click();${idle}`);
  assert.equal(await evaluate("JSON.parse(copiedResearch).subject_name"),'Fixture Company');
  assert.equal(await evaluate("copiedResearch.includes('browser-test-only-key')"),false);
  for(const [code,expected] of [[404,'no longer available'],[422,'selected review status'],[429,'rate limited'],[500,'could not be completed']]){
    await evaluate(`window.fetch=(url,options)=>options?.method==='PATCH'?Promise.resolve(new Response('browser-test-only-key Traceback C:\\private SQLITE',{status:${code}})):originalResearchFetch(url,options)`);
    await review('Potential match');assert.ok((await text('#research-workspace > .operation-status')).includes(expected));
    assert.equal((await text('#research-workspace')).includes('browser-test-only-key'),false);
  }
  await evaluate("window.fetch=(url,options)=>{researchRequests.push({url,method:options?.method||'GET'});return originalResearchFetch(url,options)}");
  await submit('Fixture Company','example.org');
  assert.ok((await text('#research-coverage')).includes('Successfully checked: 6'));
  assert.ok((await text('#research-unavailable')).includes('urlscan.io'));
  assert.ok((await text('#research-unavailable')).includes('Source unavailable'));
  assert.ok((await text('#research-matches')).includes('VirusTotal'));
  assert.equal((await text('#research-coverage')).includes('no domain supplied'),false);
  await evaluate(`button('#research-matches','View match').click();${idle}`);
  await evaluate('window.scrollTo(0,0)');
  await call('Page.captureScreenshot',{format:'png'}).then(r=>fs.writeFileSync(path.join(work,'research.png'),Buffer.from(r.data,'base64')));
  const metrics=await call('Page.getLayoutMetrics');
  await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip:{x:0,y:0,width:metrics.cssContentSize.width,height:metrics.cssContentSize.height,scale:1}}).then(r=>fs.writeFileSync(path.join(work,'research-full.png'),Buffer.from(r.data,'base64')));
  assert.ok(await evaluate("document.documentElement.scrollWidth<=window.innerWidth+1"));
  await submit('No result fixture','',false);
  assert.ok((await text('#research-matches')).includes('No automated matches were returned.'));
  assert.equal(await evaluate("document.getElementById('research-manual').hidden"),true);
  for(const code of [500,503]){
    await evaluate(`window.fetch=(url,options)=>String(url).endsWith('/kyc/screen')?Promise.resolve(new Response('browser-test-only-key Traceback C:\\private SQLITE',{status:${code}})):originalResearchFetch(url,options)`);
    await submit('Fixture Company');assert.ok((await text('#research-workspace > .operation-status')).includes(code===500?'could not be completed':'temporarily unavailable'));
    assert.ok((await text('#research-matches')).includes('No automated matches were returned.'));
    assert.equal((await text('#research-workspace')).includes('browser-test-only-key'),false);
  }
  await evaluate('window.fetch=originalResearchFetch');
  const after=state();
  for(const field of ['addresses','labels','case_entities'])assert.equal(after[field],before[field],`Research must not create ${field}`);
  assert.equal(after.kyc_screening_runs-before.kyc_screening_runs,3);
  assert.equal(after.kyc_matches-before.kyc_matches,3);
  console.log('Research browser passed: capabilities, name/domain screening, partial/empty states, manual link safety, four persisted review states, copy/evidence, quota-safe navigation, sanitized errors, and no wallet/label/case attribution.');
};
