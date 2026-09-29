// Optional real-browser smoke test. All fixture data stays in tests/browser_osint2b_server.py.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const root = path.resolve(__dirname, '..');
const work = fs.mkdtempSync(path.join(os.tmpdir(), 'gc-osint2b-browser-'));
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function port() { return new Promise(resolve => {const server = net.createServer(); server.listen(0, '127.0.0.1', () => {const value = server.address().port; server.close(() => resolve(value));});}); }
async function until(fn) { for (let n = 0; n < 160; n++) {try {const value = await fn(); if (value) return value;} catch {} await sleep(100);} throw Error('Timed out waiting for local test process'); }
let server, browser, socket;
const failures = [];
(async () => {
  const httpPort = await port(), debugPort = await port();
  const browserPath = process.env.CHROMIUM_PATH || ['C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].find(fs.existsSync);
  assert.ok(browserPath, 'Set CHROMIUM_PATH to an installed Chromium browser');
  const log = fs.openSync(path.join(work, 'server.log'), 'a');
  server = spawn(process.env.PYTHON || 'python', ['-B', path.join(__dirname, 'browser_osint2b_server.py'), String(httpPort)], {cwd:work, windowsHide:true, stdio:['ignore', log, log]});
  await until(async () => (await fetch(`http://127.0.0.1:${httpPort}/health`)).ok);
  browser = spawn(browserPath, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check', '--disable-background-networking', `--remote-debugging-port=${debugPort}`, `--user-data-dir=${path.join(work, 'profile')}`, 'about:blank'], {windowsHide:true, stdio:'ignore'});
  const target = await until(async () => (await (await fetch(`http://127.0.0.1:${debugPort}/json`)).json()).find(item => item.type === 'page'));
  socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {socket.onopen = resolve; socket.onerror = reject;});
  let serial = 0; const pending = new Map();
  socket.onmessage = event => {const data = JSON.parse(event.data); if (data.id) {const item = pending.get(data.id); pending.delete(data.id); if(data.error) item.reject(Error(data.error.message)); else item.resolve(data.result);} else if(data.method === 'Runtime.exceptionThrown') failures.push(data.params.exceptionDetails.exception?.description || data.params.exceptionDetails.text);};
  const call = (method, params = {}) => new Promise((resolve, reject) => {const id = ++serial; pending.set(id, {resolve, reject}); socket.send(JSON.stringify({id, method, params}));});
  const evaluate = async expression => {const result = await call('Runtime.evaluate', {expression:expression.includes('const ') ? '{'+expression+'}' : expression, awaitPromise:true, returnByValue:true}); if(result.exceptionDetails) { const diagnostic = await call('Runtime.evaluate',{expression:'document.body.innerText',returnByValue:true}); console.error('Test-only UI:',diagnostic.result.value); throw Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text); } return result.result.value;};
  await call('Runtime.enable'); await call('Page.enable');
  await call('Browser.setDownloadBehavior', {behavior:'allow', downloadPath:work});
  await call('Emulation.setDeviceMetricsOverride', {width:1280,height:900,deviceScaleFactor:1,mobile:false});
  await call('Page.navigate', {url:`http://127.0.0.1:${httpPort}/`});
  try { await until(() => evaluate('!!document.querySelector("#graph-workspace form")')); }
  catch(error) { console.error('Initial page diagnostics:',await evaluate('({url:location.href,ready:document.readyState,body:document.body?.innerText})'),failures); throw error; }
  await evaluate(`window.waitFor = async predicate => {for(let i=0;i<150;i++){if(predicate()) return; await new Promise(r=>setTimeout(r,50));} throw Error('Browser condition timed out');}; window.go = async name => {document.querySelector('[data-workspace="'+name+'"]').click(); await waitFor(()=>document.getElementById(name+'-workspace').dataset.busy!=='true');}; window.button = (scope,label) => [...document.querySelectorAll(scope+' button')].find(b=>b.textContent===label);`);
  const BTC='1BoatSLRHtKNngkdXEeobR76b53LETtpyT',base=`http://127.0.0.1:${httpPort}`;
  const state=async()=>await(await fetch(base+'/test-osint2b-state')).json();
  let before,first,oldPin;
  if(!process.argv.includes('--recapture-only')) {
  await evaluate(`document.querySelector('#lookup-form input').value='${BTC}';document.getElementById('lookup-form').requestSubmit();waitFor(()=>!document.getElementById('results').hidden&&document.getElementById('lookup-form').dataset.busy==='false')`);
  before=await state();
  await evaluate(`button('#wallet-workspace','Broad Discovery').click();waitFor(()=>!document.getElementById('discovery-run-button').disabled)`);
  assert.equal((await state()).capture_calls.length,0);
  await evaluate(`document.getElementById('discovery-run-button').click();waitFor(()=>!!document.querySelector('[data-broad-result]')&&document.getElementById('discovery-workspace').dataset.busy==='false')`);
  await evaluate(`window.captureScope='[data-capture-observation="'+[...document.querySelectorAll('[data-broad-result]')].find(e=>e.textContent.includes('Fixture public notice')).querySelector('.public-source-capture').dataset.captureObservation+'"]';button(captureScope,'Capture Public Source').click()`);
  assert.equal((await state()).capture_calls.length,0);
  await evaluate(`button(captureScope,'Confirm public source capture').click();waitFor(()=>document.querySelector(captureScope+' [data-capture-status="captured"]')&&document.querySelector(captureScope).dataset.busy==='false')`);
  first=(await state()).captures[0];assert.ok(first.body_sha256);assert.equal(first.wallet_present_in_capture,true);
  const displayed=await evaluate(`document.querySelector(captureScope).innerText`);assert.match(displayed,/SHA-256/);assert.match(displayed,/Wallet string found/);assert.match(displayed,/Yes/);assert.match(displayed,/Final URL/);assert.match(displayed,/Retrieved/);
  assert.doesNotMatch(await evaluate(`document.querySelector(captureScope).textContent`),/DO NOT RUN OR DISPLAY/);
  assert.equal((await state()).capture_calls.length,1);assert.deepEqual((await state()).counts,before.counts);
  await evaluate(`(()=>{const f=document.querySelector(captureScope+' .capture-review');f.elements.status.value='relevant';f.elements.note.value='Reviewed literal source text';f.requestSubmit();})();waitFor(()=>document.querySelector(captureScope).dataset.busy==='false'&&document.querySelector(captureScope+' .capture-review').elements.status.value==='relevant')`);
  await evaluate(`document.querySelector(captureScope+' [name=capture_excerpt]').value='${BTC}';button(captureScope,'Promote as evidence').click();waitFor(()=>!!button('#attr-source-handoff','Choose claim')&&document.getElementById('attr-source-handoff').dataset.busy!=='true')`);
  assert.equal((await state()).counts.attribution_evidence,before.counts.attribution_evidence);
  await evaluate(`button('#attr-source-handoff','Choose claim').click();waitFor(()=>!document.getElementById('attr-handoff-confirm').hidden)`);
  await evaluate(`(()=>{const f=document.getElementById('attr-handoff-confirm');f.elements.stance.value='context';f.elements.directness.value='context';f.elements.rationale.value='Source context, no inferred ownership';f.elements.confirmed.checked=true;button('#attr-source-handoff','Preview promotion').click();})();waitFor(()=>!button('#attr-source-handoff','Confirm promotion').hidden&&document.getElementById('attr-source-handoff').dataset.busy!=='true')`);
  await evaluate(`document.getElementById('attr-handoff-confirm').requestSubmit();waitFor(()=>document.getElementById('attr-source-handoff').innerText.includes('Promoted to immutable evidence'))`);
  assert.equal((await state()).counts.attribution_evidence,before.counts.attribution_evidence+1);
  await evaluate(`button('#attr-source-handoff','Back to Discovery').click();waitFor(()=>!document.getElementById('discovery-workspace').hidden)`);
  await evaluate(`document.querySelector(captureScope+' [name=capture_excerpt]').value='${BTC}';button(captureScope,'Pin capture to Case').click();waitFor(()=>!!document.querySelector(captureScope+' .capture-case-pin'))`);
  await evaluate(`document.querySelector(captureScope+' .capture-case-pin').requestSubmit();waitFor(()=>document.querySelector(captureScope).textContent.includes('Historical public source capture pinned.'))`);
  const pinned=await(await fetch(base+'/api/greedy-collector/cases/osint2-case')).json();
  oldPin=pinned.entities.find(e=>e.entity_type==='public_source_capture');assert.equal(oldPin.metadata_json.public_source_capture_pin.capture.body_sha256,first.body_sha256);
  } else {
    // Initial browser capture/review/promotion/pin stages passed. Recreate only
    // their prerequisites through the real local API for the failed-stage retry.
    before=await state();
    const api=async(path,body)=>{const r=await fetch(base+'/api/greedy-collector'+path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});assert.ok(r.ok,await r.clone().text());return r.json();};
    const payload={broad:true,subject:{chain:'bitcoin',address:BTC},selections:[{transform_id:'wallet.web_search.tavily'}]};
    const plan=await api('/discovery/plan',payload),run=await api('/discovery/runs',{...payload,expected_plan_fingerprint:plan.fingerprint});
    await until(async()=>!['queued','running'].includes((await api('/discovery/runs/'+run.id)).status));
    const snapshot=await api('/discovery/broad/runs/'+run.id),o=snapshot.groups.flatMap(g=>g.observations).find(o=>o.source_snapshot.hostname==='www.justice.gov');
    first=await api('/discovery/observations/'+o.id+'/public-captures',{confirmed:true});
    await api('/discovery/public-captures/'+first.id+'/review',{status:'relevant',note:'Previously verified stage',expected_version:0});
    const pv=await api('/discovery/public-captures/'+first.id+'/promotion-preview');
    oldPin=await api('/discovery/public-captures/'+first.id+'/cases/osint2-case/pin',{excerpt:BTC,expected_source_fingerprint:pv.source_fingerprint});
    await evaluate(`document.dispatchEvent(new CustomEvent('open-discovery',{detail:{action:'open_observation',run_id:'${run.id}',result_id:'${o.result_id}',observation_id:'${o.id}'}}));waitFor(()=>!!document.querySelector('[data-capture-observation="${o.id}"]')&&document.getElementById('discovery-workspace').dataset.busy==='false')`);
    await evaluate(`window.captureScope='[data-capture-observation="${o.id}"]';button(captureScope,'View captures').click();waitFor(()=>!!button(captureScope,'Review capture')&&document.querySelector(captureScope).dataset.busy==='false')`);
    await evaluate(`button(captureScope,'Review capture').click();waitFor(()=>!!button(captureScope,'Capture again')&&document.querySelector(captureScope).dataset.busy==='false')`);
  }
  await fetch(base+'/test-osint2b-mode/modified',{method:'POST'});
  await evaluate(`button(captureScope,'Capture again').click();waitFor(()=>!!button(captureScope,'Confirm public source capture')&&document.querySelector(captureScope).dataset.busy==='false')`);
  await evaluate(`button(captureScope,'Confirm public source capture').click();waitFor(()=>document.querySelector(captureScope+' [data-capture-status="captured"]')?.dataset.captureId!=='${first.id}'&&document.querySelector(captureScope).dataset.busy==='false')`);
  const modified=(await state()).captures[1];assert.equal(modified.change_state,'CHANGED');assert.notEqual(modified.body_sha256,first.body_sha256);
  assert.match(await evaluate(`document.querySelector(captureScope).innerText`),/CHANGED/);
  const old=await(await fetch(base+'/api/greedy-collector/discovery/public-captures/'+first.id)).json();assert.equal(old.body_sha256,first.body_sha256);assert.equal(old.change_state,'FIRST_CAPTURE');
  const pinnedAgain=await(await fetch(base+'/api/greedy-collector/cases/osint2-case')).json();assert.deepEqual(pinnedAgain.entities.find(e=>e.id===oldPin.id),oldPin);
  await fetch(base+'/test-osint2b-mode/blocked',{method:'POST'});
  await evaluate(`button(captureScope,'Capture again').click();waitFor(()=>!!button(captureScope,'Confirm public source capture')&&document.querySelector(captureScope).dataset.busy==='false')`);
  await evaluate(`button(captureScope,'Confirm public source capture').click();waitFor(()=>document.querySelector(captureScope+' [data-capture-status="failed"]')&&document.querySelector(captureScope).dataset.busy==='false')`);
  const after=await state();assert.equal(after.capture_calls.length,2);assert.equal(after.captures[2].failure_reason,'blocked_private_address');
  assert.match(await evaluate(`document.querySelector(captureScope).innerText`),/Capture blocked/);
  for(const [name,count] of Object.entries(before.counts))if(!name.startsWith('attribution_')&&name!=='case_entities')assert.equal(after.counts[name],count,name);
  assert.equal(after.counts.attribution_entities,before.counts.attribution_entities);assert.equal(after.counts.attribution_claims,before.counts.attribution_claims);
  for(const route of ['/','/health','/docs','/openapi.json','/static/js/public_source_capture.js'])assert.equal((await fetch(base+route)).status,200);
  assert.deepEqual(failures,[]);
  console.log(process.argv.includes('--recapture-only')?'OSINT-2B remaining browser stages passed: changed recapture, retained original and historical Case pin, private DNS blocked, unchanged unrelated state.':'OSINT-2B consolidated browser smoke passed: explicit-only capture, text/hash/wallet display, separate review, explicit evidence promotion, immutable Case pin, changed recapture, retained original, private DNS blocked, no unrelated analytical mutation.');
  await call('Browser.close').catch(()=>{});
})().catch(error=>{console.error(error);console.error('Test diagnostics:',work);process.exitCode=1;}).finally(()=>{socket?.close();browser?.kill();server?.kill();});
