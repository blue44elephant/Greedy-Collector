// Optional real-browser smoke test. All fixture data stays in tests/browser_fund_flow_server.py.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const root = path.resolve(__dirname, '..');
const work = fs.mkdtempSync(path.join(os.tmpdir(), 'gc-flow-browser-'));
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
  server = spawn(process.env.PYTHON || 'python', ['-B', path.join(__dirname, 'browser_fund_flow_server.py'), String(httpPort)], {cwd:work, windowsHide:true, stdio:['ignore', log, log]});
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
  const A='0x'+'1'.repeat(40),B='0x'+'2'.repeat(40),C='0x'+'3'.repeat(40),TOKEN='0x'+'a'.repeat(40);
  await evaluate(`go('fund-flow')`);
  await evaluate(`window.flow=async values=>{const f=document.getElementById('fund-flow-form');for(const [key,value] of Object.entries(values)){if(f.elements[key].type==='checkbox')f.elements[key].checked=value;else f.elements[key].value=value;}if(!f.checkValidity())throw Error('Invalid browser fixture form values');f.requestSubmit();await waitFor(()=>f.dataset.busy==='false');if(f.querySelector('.error'))throw Error(f.querySelector('.error').textContent);return document.querySelector('#flow-results [data-flow-run]').dataset.flowRun;};`);
  const first=await evaluate(`flow({chain:'ethereum',source:'${A}',target_value:'${B}',target_type:'wallet',asset:'native',algorithm:'shortest'})`);
  assert.ok(await evaluate(`document.getElementById('flow-results').innerText.includes('1 hops')`));
  assert.ok(await evaluate(`!!document.querySelector('#flow-results svg [marker-end]')`));
  assert.ok(await evaluate(`document.getElementById('flow-results').innerText.includes('Repeated counterparties')`));
  assert.ok(await evaluate(`document.getElementById('flow-results').innerText.includes('incoming')`));
  await evaluate(`flow({target_value:'${C}',asset:'ethereum:token:${TOKEN}',algorithm:'widest'})`);
  assert.ok(await evaluate(`document.getElementById('flow-results').innerText.includes('Observed path capacity: 80')`));
  assert.ok(await evaluate(`document.getElementById('flow-results').innerText.includes('2 hops')`));
  await evaluate(`flow({target_type:'label_category',target_value:'Exchange',asset:'native',algorithm:'shortest'})`);
  assert.ok(await evaluate(`document.getElementById('flow-results').innerText.includes('2 hops')`));
  const pinned=await evaluate(`document.querySelector('#flow-results [data-flow-run]').dataset.flowRun`);
  await evaluate(`button('#flow-results','Pin run to Case').click();waitFor(()=>!!button('#flow-results','Confirm run pin'))`);
  await evaluate(`button('#flow-results','Confirm run pin').closest('form').requestSubmit();waitFor(()=>document.getElementById('flow-results').innerText.includes('Run pinned.'))`);
  await evaluate(`flow({start_time:'2026-09-01T00:00:03',end_time:'2026-09-01T00:00:05'})`);
  assert.ok(await evaluate(`document.getElementById('flow-results').innerText.includes('No paths returned')`));
  await evaluate(`flow({start_time:'',end_time:'',mode:'neighborhood',target_value:'',asset:''})`);
  assert.ok(await evaluate(`document.getElementById('flow-results').innerText.includes('Fan-in / fan-out')`));
  const fixtures={"bitcoin": ["11111111111111111111BZbvjr", "11111111111111111111QekFQw"], "litecoin": ["LKDxGDJq5fF4FohAB8zJH24mDDNHL33V4Q", "LKDxGDJq5fF4FohAB8zJH24mDDNHULe2Jr"]};
  for(const chain of ['bitcoin','litecoin']) {
    await evaluate(`flow({chain:'${chain}',source:'${fixtures[chain][0]}',mode:'path',target_type:'wallet',target_value:'${fixtures[chain][1]}',asset:'native'})`);
    assert.ok(await evaluate(`document.getElementById('flow-results').innerText.includes('Exact input-to-output value allocation cannot be established')`));
    assert.ok(await evaluate(`document.getElementById('flow-results').innerText.includes('Exact allocation unavailable')`));
  }
  assert.equal(await evaluate(`!!document.querySelector('#fund-flow-form [name=chain] option[value=monero]')`),false);
  assert.ok(await evaluate(`document.getElementById('fund-flow-workspace').innerText.includes('Monero has no transparent fund-flow capability')`));
  assert.equal(await evaluate(`fetch('/api/greedy-collector/fund-flow/path',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({chain:'monero',source:'x',target:'y'})}).then(r=>r.json()).then(r=>r.detail)`),'unsupported_chain_capability');
  await evaluate(`go('cases')`);await evaluate(`waitFor(()=>!!button('#cases-list','FL-1 pinned run'))`);
  await evaluate(`button('#cases-list','FL-1 pinned run').click();waitFor(()=>!!document.querySelector('#case-detail [data-flow-run]'))`);
  assert.equal(await evaluate(`document.querySelector('#case-detail [data-flow-run]').dataset.flowRun`),pinned);
  assert.equal(await evaluate(`!!button('#case-detail','Pin run to Case')`),false);
  assert.ok(await evaluate(`document.getElementById('case-detail').innerText.includes('2 hops')`));
  for(const route of ['/','/health','/docs','/openapi.json','/static/js/fund_flow.js'])assert.equal((await fetch(`http://127.0.0.1:${httpPort}${route}`)).status,200);
  assert.deepEqual(failures,[]);
  console.log('FL-1 consolidated browser smoke passed: native/token paths, BTC/LTC connectivity, Label targets, temporal window, fan-in/out, immutable Case pin, Monero unsupported, routes/assets.');
  await call('Browser.close').catch(()=>{});
})().catch(error=>{console.error(error);console.error('Test diagnostics:',work);process.exitCode=1;}).finally(()=>{socket?.close();browser?.kill();server?.kill();});
