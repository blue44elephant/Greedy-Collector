// Optional real-browser smoke test. All fixture data stays in tests/browser_server.py.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const root = path.resolve(__dirname, '..');
const work = fs.mkdtempSync(path.join(os.tmpdir(), 'gc-browser-'));
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
  server = spawn(process.env.PYTHON || 'python', ['-B', path.join(__dirname, 'browser_server.py'), String(httpPort)], {cwd:work, windowsHide:true, stdio:['ignore', log, log]});
  await until(async () => (await fetch(`http://127.0.0.1:${httpPort}/health`)).ok);
  browser = spawn(browserPath, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check', '--disable-background-networking', `--remote-debugging-port=${debugPort}`, `--user-data-dir=${path.join(work, 'profile')}`, 'about:blank'], {windowsHide:true, stdio:'ignore'});
  const target = await until(async () => (await (await fetch(`http://127.0.0.1:${debugPort}/json`)).json()).find(item => item.type === 'page'));
  socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {socket.onopen = resolve; socket.onerror = reject;});
  let serial = 0; const pending = new Map();
  socket.onmessage = event => {const data = JSON.parse(event.data); if (data.id) {const item = pending.get(data.id); pending.delete(data.id); if(data.error) item.reject(Error(data.error.message)); else item.resolve(data.result);} else if(data.method === 'Runtime.exceptionThrown') failures.push(data.params.exceptionDetails.exception?.description || data.params.exceptionDetails.text);};
  const call = (method, params = {}) => new Promise((resolve, reject) => {const id = ++serial; pending.set(id, {resolve, reject}); socket.send(JSON.stringify({id, method, params}));});
  const evaluate = async expression => {const result = await call('Runtime.evaluate', {expression:expression.startsWith('const f=') ? '{'+expression+'}' : expression, awaitPromise:true, returnByValue:true}); if(result.exceptionDetails) throw Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text); return result.result.value;};
  await call('Runtime.enable'); await call('Page.enable');
  await call('Browser.setDownloadBehavior', {behavior:'allow', downloadPath:work});
  await call('Emulation.setDeviceMetricsOverride', {width:1280,height:900,deviceScaleFactor:1,mobile:false});
  await call('Page.navigate', {url:`http://127.0.0.1:${httpPort}/`});
  try { await until(() => evaluate('!!document.querySelector("#graph-workspace form")')); }
  catch(error) { console.error('Initial page diagnostics:',await evaluate('({url:location.href,ready:document.readyState,body:document.body?.innerText})'),failures); throw error; }
  await evaluate(`window.waitFor = async predicate => {for(let i=0;i<150;i++){if(predicate()) return; await new Promise(r=>setTimeout(r,50));} throw Error('Browser condition timed out');}; window.go = async name => {document.querySelector('[data-workspace="'+name+'"]').click(); await waitFor(()=>document.getElementById(name+'-workspace').dataset.busy!=='true');}; window.button = (scope,label) => [...document.querySelectorAll(scope+' button')].find(b=>b.textContent===label);`);
  await evaluate(`document.getElementById('wallet-address').value='1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa'; document.getElementById('lookup-form').requestSubmit(); waitFor(()=>!document.getElementById('results').hidden)`);
  assert.equal(await evaluate("document.getElementById('balance').textContent"), '1.000000000000000001 BTC');
  assert.ok(await evaluate("document.getElementById('risk-breakdown').innerText.includes('Score breakdown')"));
  assert.ok(await evaluate("document.getElementById('risk-breakdown').innerText.includes('Context')"));
  assert.ok(await evaluate("document.getElementById('risk-breakdown').innerText.includes('0 points (raw 0; cap 0)')"));
  assert.ok(await evaluate("document.getElementById('transaction-rows').innerText.includes('Unconfirmed')"));
  assert.ok(await evaluate("document.querySelector('#transaction-rows [title]').title.length >= 40"));
  await evaluate(`button('#counterparties','Investigate').click(); waitFor(()=>document.getElementById('lookup-form').dataset.busy==='false')`);
  assert.equal(await evaluate("document.getElementById('result-address').textContent"), '1BoatSLRHtKNngkdXEeobR76b53LETtpyT');
  await evaluate(`go('graph')`);
  await evaluate(`document.querySelector('#graph-workspace form').requestSubmit(); waitFor(()=>!!document.querySelector('#graph-workspace svg .graph-node'))`);
  await evaluate(`document.querySelector('#graph-workspace .graph-node').dispatchEvent(new MouseEvent('click',{bubbles:true}))`);
  assert.ok(await evaluate("!!button('#graph-workspace','Investigate wallet')"));
  assert.deepEqual(await evaluate("[...document.querySelectorAll('[data-workspace]')].map(n=>n.dataset.workspace)"), ['wallet', 'graph', 'monitoring', 'alerts', 'cases', 'labels', 'research', 'attribution', 'discovery']);
  assert.ok(await evaluate("!!document.querySelector('#graph-workspace [marker-end]')"));
  const initialGraphView = await evaluate("document.querySelector('#graph-workspace svg').getAttribute('viewBox')");
  await evaluate(`button('#graph-workspace','Zoom in').click()`);
  assert.notEqual(await evaluate("document.querySelector('#graph-workspace svg').getAttribute('viewBox')"), initialGraphView);
  await evaluate(`button('#graph-workspace','Reset view').click()`);
  assert.equal(await evaluate("document.querySelector('#graph-workspace svg').getAttribute('viewBox')"), initialGraphView);
  for (const hops of ['2','3']) {
    await evaluate(`const f=document.querySelector('#graph-workspace form'); f.elements.hops.value='${hops}'; f.requestSubmit(); waitFor(()=>f.dataset.busy==='false')`);
    assert.ok(await evaluate(`document.querySelector('#graph-workspace').innerText.includes('Requested hops: ${hops}')`));
  }
  await evaluate(`document.querySelector('#graph-workspace .graph-node').dispatchEvent(new MouseEvent('click',{bubbles:true})); button('#graph-workspace','Investigate wallet').click(); waitFor(()=>document.getElementById('lookup-form').dataset.busy==='false')`);
  assert.equal(await evaluate("document.getElementById('wallet-workspace').hidden"), false);
  await evaluate(`go('wallet')`);
  await evaluate(`document.getElementById('stored-button').click(); waitFor(()=>document.getElementById('data-mode').textContent==='Stored local state')`);
  await evaluate(`document.getElementById('wallet-address').value='0x'+'1'.repeat(40); document.getElementById('lookup-form').requestSubmit(); waitFor(()=>document.getElementById('balance').textContent.endsWith(' ETH'))`);
  assert.equal(await evaluate("document.getElementById('balance').textContent"), '1.000000000000000001 ETH');
  assert.ok(await evaluate("document.getElementById('transaction-rows').innerText.includes('1.234567') && document.getElementById('transaction-rows').innerText.includes('TEST')"));
  await evaluate(`document.getElementById('stored-button').click(); waitFor(()=>document.getElementById('lookup-form').dataset.busy==='false')`);
  assert.equal(await evaluate("document.getElementById('stored-note').hidden"), false);
  assert.ok(await evaluate("document.getElementById('risk-time').textContent.includes('UTC')"));
  assert.ok(await evaluate("document.getElementById('risk-breakdown').innerText.includes('Its original score is preserved')"));
  await evaluate(`document.getElementById('wallet-address').value='0x'+'9'.repeat(40); document.getElementById('lookup-form').requestSubmit(); waitFor(()=>document.getElementById('lookup-form').dataset.busy==='false')`);
  assert.equal(await evaluate("document.getElementById('transactions-empty').hidden"), false);
  assert.equal(await evaluate("document.getElementById('risk-empty').hidden"), false);
  assert.equal(await evaluate("document.getElementById('counterparties-empty').hidden"), false);
  await evaluate(`go('graph'); document.querySelector('#graph-workspace form').requestSubmit(); waitFor(()=>document.querySelector('#graph-workspace form').dataset.busy==='false')`);
  assert.ok(await evaluate("document.querySelector('#graph-workspace').innerText.includes('No stored relationships are available for this address.')"));
  assert.equal(await evaluate("!!document.querySelector('#graph-workspace svg')"), false);
  await evaluate(`go('wallet'); document.getElementById('wallet-address').value='0x'+'8'.repeat(40); document.getElementById('stored-button').click(); waitFor(()=>document.getElementById('lookup-form').dataset.busy==='false')`);
  assert.ok(await evaluate("document.querySelector('#lookup-form .operation-status').textContent.includes('This address has not been stored locally yet.')"));
  for (const [address, expected] of [['', 'Enter a supported wallet address or transaction hash.'], ['invalid-address', 'Greedy Collector could not identify this value as a supported wallet address or transaction hash. Supported: Bitcoin/Ethereum addresses and transaction hashes.'], ['0x'+'5'.repeat(40), 'Ethereum provider configuration is unavailable.'], ['0x'+'6'.repeat(40), 'Blockchain provider request failed. Try again later.']]) {
    await evaluate(`document.getElementById('wallet-address').value=${JSON.stringify(address)}; document.getElementById('lookup-form').requestSubmit(); waitFor(()=>document.getElementById('lookup-form').dataset.busy==='false')`);
    assert.equal(await evaluate("document.querySelector('#lookup-form .operation-status').textContent"), expected);
    assert.equal(await evaluate("document.getElementById('results').hidden"), true);
    assert.equal(await evaluate("document.getElementById('lookup-button').disabled"), false);
  }
  assert.equal(await evaluate("document.body.innerText.includes('browser-test-only-key')"), false);
  await evaluate(`document.getElementById('wallet-address').value='0x'+'1'.repeat(40); document.getElementById('lookup-form').requestSubmit(); waitFor(()=>document.getElementById('lookup-form').dataset.busy==='false')`);
  await call('Page.captureScreenshot', {format:'png'}).then(result => fs.writeFileSync(path.join(work,'wallet.png'), Buffer.from(result.data,'base64')));
  await require("./browser_alerts.cjs").empty({evaluate});
  await require("./browser_search_graph.cjs")({evaluate,call,work});
  await require("./browser_monitoring.cjs")({evaluate, call, work});
  await require("./browser_alerts.cjs").review({evaluate,call,work});
  await require("./browser_cases.cjs")({evaluate,call,work});
  await require("./browser_labels.cjs")({evaluate,call,work});
  await require("./browser_research.cjs")({evaluate,call,work});
  assert.deepEqual(failures, []);
  console.log('Browser smoke passed: Wallet BTC/ETH, token/mempool records, stored views/timestamps, counterparty investigation, graph hops/selection/investigation/zoom, empty states, missing stored address, and safe errors.');
  console.log('Screenshot:', path.join(work,'wallet.png'));
  await call('Browser.close').catch(()=>{});
})().catch(error => {console.error(error); console.error('Test diagnostics:',work); process.exitCode=1;}).finally(()=> {socket?.close(); browser?.kill(); server?.kill();});
