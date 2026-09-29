// Optional real-browser smoke test. All fixture data stays in tests/browser_osint2a_server.py.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const root = path.resolve(__dirname, '..');
const work = fs.mkdtempSync(path.join(os.tmpdir(), 'gc-osint2a-browser-'));
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
  server = spawn(process.env.PYTHON || 'python', ['-B', path.join(__dirname, 'browser_osint2a_server.py'), String(httpPort)], {cwd:work, windowsHide:true, stdio:['ignore', log, log]});
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
  const before=await state();
  if(!process.argv.includes('--diagnostics-only')) {
  await evaluate(`document.querySelector('#lookup-form input').value='${BTC}';document.getElementById('lookup-form').requestSubmit();waitFor(()=>!document.getElementById('results').hidden&&document.getElementById('lookup-form').dataset.busy==='false')`);
  if(!process.argv.includes('--results-only'))assert.equal(before.calls.length,0);
  await evaluate(`button('#wallet-workspace','Broad Discovery').click();waitFor(()=>document.getElementById('discovery-plan-detail').textContent.includes('Will run')&&document.getElementById('discovery-workspace').dataset.busy==='false')`);
  if(!process.argv.includes('--results-only'))assert.equal((await state()).calls.length,0);
  const plan=await evaluate(`document.getElementById('discovery-plan-detail').innerText`);
  if(!process.argv.includes('--results-only'))assert.match(plan,/Tavily Web Search/);assert.match(plan,/Unavailable/);assert.match(plan,/Not applicable: ENS/);assert.match(plan,/Manual pivots/);
  assert.equal(await evaluate(`document.querySelectorAll('#discovery-transforms input[type=checkbox]:checked').length`),4);
  const cards=await evaluate(`document.getElementById('discovery-transforms').innerText`);
  assert.match(cards,/Tavily Web Search/);assert.match(cards,/Brave/);assert.match(cards,/Limited free/);assert.match(cards,/Free provider ready/);assert.match(cards,/Manual pivot/);
  assert.doesNotMatch(cards,/osint2a-browser-only-key/);
  await evaluate(`document.getElementById('discovery-run-button').click();waitFor(()=>document.getElementById('discovery-run').dataset.status==='partial'&&!!document.getElementById('broad-filters')&&document.getElementById('discovery-workspace').dataset.busy==='false')`);
  assert.equal((await state()).calls.length,1);
  assert.ok((await state()).calls[0].includes('api.tavily.com/search'));
  assert.equal(await evaluate(`document.querySelectorAll('[data-broad-result]').length`),2);
  assert.match(await evaluate(`document.getElementById('discovery-workspace').innerText`),/tavily_search/);
  assert.match(await evaluate(`document.getElementById('discovery-workspace').innerText`),/Exact wallet token present/);
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
  assert.deepEqual((await state()).counts,before.counts);
  }
  const baselineCalls=(await state()).calls.length;
  const base=`http://127.0.0.1:${httpPort}`;
  // Missing key diagnostic is visible without executing another provider.
  await fetch(base+'/test-osint2a-mode/missing',{method:'POST'});
  await call('Page.reload');await until(()=>evaluate(`!!document.querySelector('#discovery-subject')`));
  await evaluate(`window.waitFor = async predicate => {for(let i=0;i<150;i++){if(predicate()) return; await new Promise(r=>setTimeout(r,50));} throw Error('Browser condition timed out');}; window.go = async name => {document.querySelector('[data-workspace="'+name+'"]').click(); await waitFor(()=>document.getElementById(name+'-workspace').dataset.busy!=='true');}; window.button = (scope,label) => [...document.querySelectorAll(scope+' button')].find(b=>b.textContent===label);`);
  await evaluate(`go('discovery')`);
  await evaluate(`waitFor(()=>document.getElementById('discovery-transforms').innerText.includes('TAVILY_API_KEY MISSING'))`);
  assert.match(await evaluate(`document.getElementById('discovery-transforms').innerText`),/without a payment card/);
  assert.equal((await state()).calls.length,baselineCalls);
  // Explicit refresh and only Tavily selected: quota must not trigger Brave fallback.
  await fetch(base+'/test-osint2a-mode/quota',{method:'POST'});
  await call('Page.reload');await until(()=>evaluate(`!!document.querySelector('#discovery-subject')`));
  await evaluate(`window.waitFor = async predicate => {for(let i=0;i<150;i++){if(predicate()) return; await new Promise(r=>setTimeout(r,50));} throw Error('Browser condition timed out');}; window.go = async name => {document.querySelector('[data-workspace="'+name+'"]').click(); await waitFor(()=>document.getElementById(name+'-workspace').dataset.busy!=='true');}; window.button = (scope,label) => [...document.querySelectorAll(scope+' button')].find(b=>b.textContent===label);`);
  await evaluate(`document.dispatchEvent(new CustomEvent('open-discovery',{detail:{origin:'wallet',chain:'bitcoin',address:'${BTC}',broad:true}}));waitFor(()=>document.getElementById('discovery-plan-detail').textContent.includes('Will run')&&document.getElementById('discovery-workspace').dataset.busy==='false')`);
  await evaluate(`(()=>{for(const c of document.querySelectorAll('#discovery-transforms input[type=checkbox]')){c.checked=c.closest('.discovery-pivot').textContent.includes('Tavily Web Search');c.dispatchEvent(new Event('change',{bubbles:true}));}const refresh=document.querySelector('#discovery-workspace [name=refresh]');refresh.checked=true;refresh.dispatchEvent(new Event('change',{bubbles:true}));})()`);
  await evaluate(`button('#discovery-workspace','Broad Discovery preflight').click();waitFor(()=>!document.getElementById('discovery-run-button').disabled)`);
  await evaluate(`document.getElementById('discovery-run-button').click();waitFor(()=>document.getElementById('discovery-run').innerText.includes('allowance exhausted')&&document.getElementById('discovery-workspace').dataset.busy==='false')`);
  assert.equal((await state()).calls.length,baselineCalls+1);assert.deepEqual((await state()).counts,before.counts);
  for(const route of ['/','/health','/docs','/openapi.json','/static/js/discovery_diagnostics.js'])assert.equal((await fetch(base+route)).status,200);
  assert.deepEqual(failures,[]);
  console.log('OSINT-2A consolidated browser smoke passed: wallet handoff, independent Tavily/Brave cards, zero-network preflight, Tavily default dispatch, provenance, exact/fuzzy candidates, Relevant review without automatic Attribution, missing-key guidance, quota exhaustion without fallback, Manual Exact Web and isolated DB.');
  await call('Browser.close').catch(()=>{});
})().catch(error=>{console.error(error);console.error('Test diagnostics:',work);process.exitCode=1;}).finally(()=>{socket?.close();browser?.kill();server?.kill();});
