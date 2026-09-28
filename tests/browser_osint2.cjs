// Optional real-browser smoke test. All fixture data stays in tests/browser_osint2_server.py.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const root = path.resolve(__dirname, '..');
const work = fs.mkdtempSync(path.join(os.tmpdir(), 'gc-osint2-browser-'));
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
  server = spawn(process.env.PYTHON || 'python', ['-B', path.join(__dirname, 'browser_osint2_server.py'), String(httpPort)], {cwd:work, windowsHide:true, stdio:['ignore', log, log]});
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
  const BTC='1BoatSLRHtKNngkdXEeobR76b53LETtpyT';
  const state=async()=>await(await fetch(`http://127.0.0.1:${httpPort}/test-osint2-state`)).json();
  if(!process.argv.includes('--case-only')) {
  await evaluate(`document.querySelector('#lookup-form input').value='${BTC}';document.getElementById('lookup-form').requestSubmit();waitFor(()=>!document.getElementById('results').hidden&&document.getElementById('lookup-form').dataset.busy==='false')`);
  const before=await state();if(!process.argv.includes('--results-only'))assert.equal(before.calls.length,0);
  await evaluate(`button('#wallet-workspace','Broad Discovery').click();waitFor(()=>document.getElementById('discovery-plan-detail').textContent.includes('Will run')&&document.getElementById('discovery-workspace').dataset.busy==='false')`);
  if(!process.argv.includes('--results-only'))assert.equal((await state()).calls.length,0);
  const plan=await evaluate(`document.getElementById('discovery-plan-detail').innerText`);
  if(!process.argv.includes('--results-only'))assert.match(plan,/Broad Web Search/);assert.match(plan,/Unavailable/);assert.match(plan,/Not applicable: ENS/);assert.match(plan,/Manual pivots/);
  if(!process.argv.includes('--results-only'))assert.equal(await evaluate(`document.querySelectorAll('#discovery-transforms input[type=checkbox]:checked').length`),4);
  await evaluate(`document.getElementById('discovery-run-button').click();waitFor(()=>document.getElementById('discovery-run').dataset.status==='partial'&&!!document.getElementById('broad-filters')&&document.getElementById('discovery-workspace').dataset.busy==='false')`);
  assert.equal((await state()).calls.length,1);
  assert.equal(await evaluate(`document.querySelectorAll('[data-broad-result]').length`),3);
  assert.match(await evaluate(`document.getElementById('discovery-workspace').innerText`),/Official \/ legal sources/);
  assert.match(await evaluate(`document.getElementById('discovery-workspace').innerText`),/Non-exact search candidate/);
  assert.equal(await evaluate(`document.querySelectorAll('a[href*=".onion"]').length`),0);
  await evaluate(`(()=>{const f=document.getElementById('broad-filters');f.elements.search.value='vendor123';f.elements.search.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  assert.equal(await evaluate(`document.querySelectorAll('[data-broad-result]').length`),1);
  assert.match(await evaluate(`document.querySelector('[data-broad-result]').innerText`),/alias candidate: vendor123/);
  assert.equal((await state()).calls.length,1);
  await evaluate(`(()=>{const f=[...document.querySelectorAll('[data-candidate-id]')].find(e=>e.textContent.includes('alias candidate')).querySelector('form');f.elements.status.value='relevant';f.elements.note.value='Explicit source text, no ownership inference';f.requestSubmit();})();waitFor(()=>document.getElementById('discovery-workspace').dataset.busy==='false'&&document.querySelector('[data-candidate-id]').textContent.includes('relevant'))`);
  assert.deepEqual((await state()).counts,before.counts);
  await evaluate(`(()=>{const f=document.getElementById('broad-filters');f.elements.search.value='vendor123';f.elements.search.dispatchEvent(new Event('input',{bubbles:true}));})();button('#discovery-workspace','Inspect / review source').click();waitFor(()=>!!document.getElementById('discovery-review')&&document.getElementById('discovery-workspace').dataset.busy==='false')`);
  // Select the exact institutional source if deterministic URL ordering opened another result.
  await evaluate(`(()=>{const f=document.getElementById('discovery-review');f.elements.status.value='relevant';f.elements.reason.value='Reviewed public metadata only';f.requestSubmit();})();waitFor(()=>!!button('#discovery-promotion','Use as attribution evidence')&&document.getElementById('discovery-workspace').dataset.busy==='false')`);
  await evaluate(`button('#discovery-promotion','Use as attribution evidence').click();waitFor(()=>!!button('#attr-source-handoff','Choose claim')&&document.getElementById('attr-source-handoff').dataset.busy!=='true')`);
  await evaluate(`button('#attr-source-handoff','Choose claim').click();waitFor(()=>!document.getElementById('attr-handoff-confirm').hidden&&document.getElementById('attr-source-handoff').dataset.busy!=='true')`);
  await evaluate(`(()=>{const f=document.getElementById('attr-handoff-confirm');f.elements.stance.value='context';f.elements.directness.value='context';f.elements.rationale.value='Test analyst context, not identity verification';f.elements.confirmed.checked=true;button('#attr-source-handoff','Preview promotion').click();})();waitFor(()=>!button('#attr-source-handoff','Confirm promotion').hidden&&document.getElementById('attr-source-handoff').dataset.busy!=='true')`);
  await evaluate(`document.getElementById('attr-handoff-confirm').requestSubmit();waitFor(()=>document.getElementById('attr-source-handoff').innerText.includes('Promoted to immutable evidence'))`);
  const promoted=await state();assert.equal(promoted.counts.attribution_evidence,before.counts.attribution_evidence+1);
  for(const [name,value] of Object.entries(before.counts))if(!name.startsWith('attribution_'))assert.equal(promoted.counts[name],value,name);
  await evaluate(`button('#attr-source-handoff','Back to Discovery').click();waitFor(()=>!document.getElementById('discovery-workspace').hidden&&document.getElementById('discovery-workspace').dataset.busy==='false');button('#discovery-workspace','Results').click()`);
  } else {
    // Prior browser stages passed. Rebuild only their prerequisite data via the real test API.
    const api=async(path,body)=>{const r=await fetch(`http://127.0.0.1:${httpPort}/api/greedy-collector${path}`,{method:body?'POST':'GET',headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});assert.ok(r.ok,await r.clone().text());return r.json();};
    const data={broad:true,subject:{chain:'bitcoin',address:BTC},selections:[{transform_id:'wallet.broad_web'}]};
    const plan=await api('/discovery/plan',data),run=await api('/discovery/runs',{...data,expected_plan_fingerprint:plan.fingerprint});
    await until(async()=>!['queued','running'].includes((await api('/discovery/runs/'+run.id)).status));
    const snapshot=await api('/discovery/broad/runs/'+run.id),o=snapshot.groups.flatMap(g=>g.observations).find(o=>o.source_snapshot.hostname==='www.justice.gov'),candidate=snapshot.candidates.find(c=>c.kind==='alias');
    await api('/discovery/broad/candidates/'+candidate.id+'/review',{status:'relevant',note:'Prior-stage fixture review',expected_version:candidate.version});
    await api('/discovery/results/'+o.result_id+'/review',{observation_id:o.id,status:'relevant',reason:'Prior-stage fixture review',expected_version:o.result_version,expected_source_fingerprint:o.content_sha256});
    await evaluate(`document.dispatchEvent(new CustomEvent('open-discovery',{detail:{action:'open_observation',run_id:'${run.id}',result_id:'${o.result_id}',observation_id:'${o.id}'}}));waitFor(()=>!!document.getElementById('broad-filters')&&document.getElementById('discovery-workspace').dataset.busy==='false')`);
  }
  const prePin=(await state()).counts;
  await evaluate(`button('#discovery-workspace','Pin Broad Discovery to Case').click();waitFor(()=>!!button('#discovery-workspace','Confirm Broad Discovery pin')&&document.getElementById('discovery-workspace').dataset.busy==='false')`);
  await evaluate(`button('#discovery-workspace','Confirm Broad Discovery pin').closest('form').requestSubmit();waitFor(()=>document.getElementById('discovery-workspace').innerText.includes('Broad Discovery snapshot pinned.'))`);
  await evaluate(`button('#discovery-workspace','Graph').click();waitFor(()=>!!document.querySelector('.discovery-graph-node.alias_candidate'))`);
  await evaluate(`document.querySelector('.discovery-graph-node.alias_candidate').dispatchEvent(new MouseEvent('click',{bubbles:true}))`);
  assert.match(await evaluate(`document.getElementById('discovery-graph-detail').innerText`),/Source metadata \/ candidate only/);
  const runs=await(await fetch(`http://127.0.0.1:${httpPort}/api/greedy-collector/discovery/runs`)).json();const runId=runs.items[0].id;
  const pinned=await(await fetch(`http://127.0.0.1:${httpPort}/api/greedy-collector/cases/osint2-case`)).json();assert.ok(pinned.entities.some(e=>e.entity_type==='broad_discovery'));
  await call('Page.reload');await until(()=>evaluate(`!!document.querySelector('#discovery-subject')`));
  const stored=await(await fetch(`http://127.0.0.1:${httpPort}/api/greedy-collector/discovery/broad/runs/${runId}`)).json();assert.equal(stored.groups.length,3);assert.equal(stored.candidate_reviews.length,1);assert.equal(stored.source_reviews.length,1);
  assert.equal((await state()).calls.length,1);
  for(const route of ['/','/health','/docs','/openapi.json','/static/js/discovery_broad.js'])assert.equal((await fetch(`http://127.0.0.1:${httpPort}${route}`)).status,200);
  for(const [name,value] of Object.entries(prePin))if(name!=='case_entities')assert.equal((await state()).counts[name],value,name);
  assert.deepEqual(failures,[]);console.log('OSINT-2 consolidated browser smoke passed: wallet handoff, zero-network preflight, federation, grouping/local filters, candidates, review, explicit evidence promotion, immutable Case pin, graph, persisted reload and unchanged unrelated state.');
  await call('Browser.close').catch(()=>{});
})().catch(error=>{console.error(error);console.error('Test diagnostics:',work);process.exitCode=1;}).finally(()=>{socket?.close();browser?.kill();server?.kill();});
