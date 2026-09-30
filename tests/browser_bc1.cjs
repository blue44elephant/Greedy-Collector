// Optional real-browser smoke test. All fixture data stays in tests/browser_bc1_server.py.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const root = path.resolve(__dirname, '..');
const work = fs.mkdtempSync(path.join(os.tmpdir(), 'gc-bc1-browser-'));
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
  server = spawn(process.env.PYTHON || 'python', ['-B', path.join(__dirname, 'browser_bc1_server.py'), String(httpPort)], {cwd:work, windowsHide:true, stdio:['ignore', log, log]});
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
  const search=async(value,hint='')=>evaluate(`document.getElementById('wallet-address').value=${JSON.stringify(value)};document.getElementById('chain-hint').value=${JSON.stringify(hint)};document.getElementById('lookup-form').requestSubmit();waitFor(()=>document.getElementById('lookup-form').dataset.busy==='false')`);
  const A='0x'+'1'.repeat(40),B='0x'+'2'.repeat(40),BTC='1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa';
  await search(A);
  assert.ok(await evaluate("document.querySelector('#lookup-form .operation-status').innerText.includes('matches more than one')"));
  await search(A,'ethereum');
  assert.equal(await evaluate("document.getElementById('results').hidden"),false);
  assert.ok(await evaluate("document.getElementById('transaction-rows').innerText.includes('123456789012345678901.234567890123456789')"));
  assert.ok(await evaluate("document.getElementById('transaction-rows').innerText.includes('Failed execution')"));
  assert.ok(await evaluate("document.getElementById('collection-summary').innerText.includes('COMPLETE_WITHIN_REQUESTED_BOUND')"));
  await search(B,'ethereum');
  assert.ok(await evaluate("document.getElementById('collection-summary').innerText.includes('PARTIAL')"));
  await search('0x'+'a'.repeat(64),'ethereum');
  assert.equal(await evaluate("document.getElementById('transaction-result').hidden"),false);
  await search(BTC);
  assert.ok(await evaluate("document.getElementById('collection-summary').innerText.includes('Records returned: 1')"));
  await evaluate(`document.getElementById('wallet-graph').click();document.querySelector('#graph-workspace form').requestSubmit();waitFor(()=>document.querySelector('#graph-workspace form').dataset.busy==='false')`);
  assert.ok(await evaluate("document.getElementById('graph-workspace').innerText.includes('UTXO transaction connectivity (1)')"));
  assert.equal(await evaluate("document.querySelectorAll('#graph-workspace .graph-edge').length"),0);
  assert.equal(await evaluate("document.querySelectorAll('#graph-workspace .graph-node').length"),2);
  assert.deepEqual(failures,[]);
  console.log('BC-1 consolidated browser passed: explicit ambiguity, real normalization/SQLite, exact amounts, failed status, partial collection, transaction lookup, conservative UTXO graph.');
  await call('Browser.close').catch(()=>{});
})().catch(error=>{console.error(error);console.error('Test diagnostics:',work);process.exitCode=1;}).finally(()=>{socket?.close();browser?.kill();server?.kill();});
