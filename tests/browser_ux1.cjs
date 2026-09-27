// Optional real-browser smoke test. All fixture data stays in tests/browser_ux1_server.py.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const root = path.resolve(__dirname, '..');
const work = fs.mkdtempSync(path.join(os.tmpdir(), 'gc-ux1-browser-'));
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
  server = spawn(process.env.PYTHON || 'python', ['-B', path.join(__dirname, 'browser_ux1_server.py'), String(httpPort)], {cwd:work, windowsHide:true, stdio:['ignore', log, log]});
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
  const BTC='11111111111111111111BZbvjr', ETH='0x'+'1'.repeat(40);
  const transform=selector=>evaluate(`document.querySelector(${JSON.stringify(selector)}).getAttribute('transform')`);
  async function move(selector,dx,dy){
    await evaluate(`document.querySelector(${JSON.stringify(selector)}).scrollIntoView({block:'center'})`);
    const box=await evaluate(`(()=>{const r=document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()`);
    await call('Input.dispatchMouseEvent',{type:'mouseMoved',x:box.x,y:box.y});
    await call('Input.dispatchMouseEvent',{type:'mousePressed',x:box.x,y:box.y,button:'left',clickCount:1});
    for(let i=1;i<=5;i++)await call('Input.dispatchMouseEvent',{type:'mouseMoved',x:box.x+dx*i/5,y:box.y+dy*i/5,button:'left',buttons:1});
    await call('Input.dispatchMouseEvent',{type:'mouseReleased',x:box.x+dx,y:box.y+dy,button:'left',clickCount:1});
  }
  if(!process.argv.includes('--discovery-only')) {
  await evaluate(`window.loadGraph=async()=>{await go('graph');const f=document.querySelector('#graph-workspace form');f.elements.chain.value='bitcoin';f.elements.address.value='${BTC}';f.requestSubmit();await waitFor(()=>f.dataset.busy==='false');if(!document.querySelector('.graph-node'))throw Error('Graph fixture missing');};loadGraph()`);
  const nodeSelector='.graph-node.is-focus';
  const beforeData=await (await fetch(`http://127.0.0.1:${httpPort}/api/greedy-collector/address/bitcoin/${BTC}/graph?hops=1`)).json();
  const original=await transform(nodeSelector), originalEdge=await evaluate(`document.querySelector('.graph-edge path').getAttribute('d')`);
  await move(nodeSelector,85,55);const moved=await transform(nodeSelector);assert.notEqual(moved,original);
  assert.ok(await evaluate(`document.querySelector('${nodeSelector}').classList.contains('is-pinned')`));
  assert.notEqual(await evaluate(`document.querySelector('.graph-edge path').getAttribute('d')`),originalEdge);
  const other='.graph-node:not(.is-focus)';const otherOriginal=await transform(other);await move(other,-35,-45);
  await evaluate(`button('#graph-workspace','Auto layout').click()`);assert.equal(await transform(nodeSelector),moved);
  await evaluate(`button('#graph-workspace','Unpin selected node').click();button('#graph-workspace','Auto layout').click()`);assert.equal(await transform(other),otherOriginal);
  await evaluate(`button('#graph-workspace','Fit to graph').click()`);
  assert.ok(await evaluate(`(()=>{const svg=document.querySelector('.graph-canvas'),v=svg.viewBox.baseVal;return [...svg.querySelectorAll('.graph-node rect')].every(r=>{const b=r.parentNode.getBBox(),m=r.parentNode.transform.baseVal.consolidate().matrix;return b.x+m.e>=v.x&&b.y+m.f>=v.y&&b.x+m.e+b.width<=v.x+v.width&&b.y+m.f+b.height<=v.y+v.height;});})()`));
  for(const label of ['Technical Cluster overlay: OFF','Technical Cluster overlay: ON','Technical Cluster overlay: OFF']){await evaluate(`button('#graph-workspace',${JSON.stringify(label)}).click()`);await sleep(150);assert.equal(await transform(nodeSelector),moved);}
  await evaluate(`loadGraph()`);assert.equal(await transform(nodeSelector),moved);
  await evaluate(`go('wallet')`);await evaluate(`go('graph')`);assert.equal(await transform(nodeSelector),moved);
  await call('Page.reload');await until(()=>evaluate(`!!document.querySelector('#graph-workspace form')`));
  await evaluate(`window.waitFor=async p=>{for(let i=0;i<150;i++){if(p())return;await new Promise(r=>setTimeout(r,50));}throw Error('UI wait');};window.go=async n=>{document.querySelector('[data-workspace="'+n+'"]').click();await waitFor(()=>document.getElementById(n+'-workspace').dataset.busy!=='true');};window.button=(scope,label)=>[...document.querySelectorAll(scope+' button')].find(b=>b.textContent===label);go('graph')`);
  await evaluate(`(()=>{const f=document.querySelector('#graph-workspace form');f.elements.chain.value='bitcoin';f.elements.address.value='${BTC}';f.requestSubmit();})();waitFor(()=>!!document.querySelector('.graph-node'))`);
  assert.equal(await transform(nodeSelector),moved);
  await evaluate(`button('#graph-workspace','Reset layout').click()`);assert.equal(await transform(nodeSelector),original);
  assert.equal(await evaluate(`document.querySelectorAll('.graph-node.is-pinned').length`),0);
  const afterData=await (await fetch(`http://127.0.0.1:${httpPort}/api/greedy-collector/address/bitcoin/${BTC}/graph?hops=1`)).json();assert.deepEqual(afterData,beforeData);
  }
  await evaluate(`go('discovery')`);
  await evaluate(`waitFor(()=>document.querySelectorAll('[data-transform]').length===6)`);
  await evaluate(`document.querySelector('#discovery-subject [name=address]').value='${BTC}';document.getElementById('discovery-subject').requestSubmit();waitFor(()=>document.getElementById('discovery-detected').textContent.includes('Format checked'))`);
  const card=id=>evaluate(`document.querySelector('[data-transform="${id}"]').innerText`);
  assert.match(await card('wallet.public_code_mentions'),/Automated remote/);
  assert.match(await card('wallet.graphsense_public_tags'),/DISCOVERY_GITHUB_TOKEN is not configured/);
  assert.match(await card('wallet.ens_primary_name'),/Not applicable to bitcoin.*Ethereum only/);
  assert.match(await card('wallet.manual_exact_web'),/Manual pivot/);
  assert.match(await card('wallet.manual_source_observation'),/Manual capture/);
  assert.equal(await evaluate(`document.querySelector('[data-transform="wallet.ens_primary_name"] input[type=checkbox]').disabled`),true);
  await evaluate(`for(const id of ['wallet.local_labels','wallet.public_code_mentions','wallet.graphsense_public_tags']){const c=document.querySelector('[data-transform="'+id+'"] input[type=checkbox]');c.checked=true;c.dispatchEvent(new Event('change'));}document.getElementById('discovery-plan-button').click();waitFor(()=>document.getElementById('discovery-plan-detail').textContent.includes('Will run'))`);
  assert.match(await evaluate(`document.getElementById('discovery-plan-detail').innerText`),/Unavailable.*GraphSense Public Tags.*Public code mentions/s);
  assert.equal((await (await fetch(`http://127.0.0.1:${httpPort}/api/greedy-collector/discovery/runs`)).json()).total,0);
  await evaluate(`document.getElementById('discovery-run-button').click();waitFor(()=>document.getElementById('discovery-run').dataset.status==='partial')`);
  const summary=await evaluate(`document.querySelector('.discovery-run-summary').innerText`);assert.match(summary,/3 transforms requested/);assert.match(summary,/1 executed/);assert.match(summary,/2 unavailable/);assert.match(summary,/0 manual links/);
  assert.match(await evaluate(`document.getElementById('discovery-run').innerText`),/No matching stored local labels/);
  assert.equal(await evaluate(`document.getElementById('discovery-run').innerText.includes('No exact public code mention')`),false);
  await evaluate(`button('#discovery-workspace','Graph').click();waitFor(()=>document.getElementById('discovery-workspace').dataset.busy==='false'&&!!document.querySelector('.discovery-graph-node'))`);
  const discoveryNode='.discovery-graph-node.wallet';const dp=await transform(discoveryNode);await move(discoveryNode,65,35);const dm=await transform(discoveryNode);assert.notEqual(dp,dm);
  await evaluate(`button('#discovery-graph-panel','Auto layout').click()`);assert.equal(await transform(discoveryNode),dm);
  await evaluate(`button('#discovery-workspace','Results').click()`);await evaluate(`button('#discovery-workspace','Graph').click();waitFor(()=>document.getElementById('discovery-workspace').dataset.busy==='false'&&!!document.querySelector('.discovery-graph-node'))`);assert.equal(await transform(discoveryNode),dm);
  await evaluate(`button('#discovery-graph-panel','Reset layout').click()`);assert.equal(await transform(discoveryNode),dp);
  await evaluate(`document.querySelector('#discovery-subject [name=address]').value='${ETH}';document.getElementById('discovery-subject').requestSubmit();waitFor(()=>document.getElementById('discovery-detected').textContent.includes('Ethereum'))`);
  assert.doesNotMatch(await card('wallet.ens_primary_name'),/Not applicable to/);assert.match(await card('wallet.ens_primary_name'),/ALCHEMY_API_KEY is not configured/);
  for(const route of ['/','/health','/docs','/openapi.json','/static/js/graph_interaction.js','/static/js/discovery_diagnostics.js'])assert.equal((await fetch(`http://127.0.0.1:${httpPort}${route}`)).status,200);
  assert.deepEqual(failures,[]);
  console.log((process.argv.includes('--discovery-only')?'UX-1 Discovery subset passed; earlier graph checks passed. ':'UX-1 consolidated browser smoke passed: ')+ ' drag/pin/auto/reset/fit/session persistence/cluster overlay, unchanged analytical graph, Discovery cards/preflight/mixed execution/zero results/manual pivot/chain context/shared drag.');
  await call('Browser.close').catch(()=>{});
})().catch(error=>{console.error(error);console.error('Test diagnostics:',work);process.exitCode=1;}).finally(()=>{socket?.close();browser?.kill();server?.kill();});
