// One consolidated CASE-2 smoke; all source and attribution data are test-only.
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),net=require('node:net'),assert=require('node:assert/strict');
const {spawn}=require('node:child_process');
const work=fs.mkdtempSync(path.join(os.tmpdir(),'gc-case2-browser-'));
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function port(){return new Promise(resolve=>{const socket=net.createServer();socket.listen(0,'127.0.0.1',()=>{const value=socket.address().port;socket.close(()=>resolve(value));});});}
async function until(fn){for(let i=0;i<180;i++){try{const value=await fn();if(value)return value;}catch{}await sleep(100);}throw Error('Timed out waiting for browser fixture');}
let server,browser,socket,stage='startup';const failures=[];
(async()=>{
  const httpPort=await port(),debugPort=await port();
  const browserPath=process.env.CHROMIUM_PATH||['C:/Program Files/Google/Chrome/Application/chrome.exe','C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].find(fs.existsSync);
  assert.ok(browserPath,'Set CHROMIUM_PATH to Chromium');
  const log=fs.openSync(path.join(work,'server.log'),'a');
  server=spawn(process.env.PYTHON||'python',['-B',path.join(__dirname,'browser_case2_server.py'),String(httpPort)],{cwd:work,windowsHide:true,stdio:['ignore',log,log]});
  await until(async()=>(await fetch(`http://127.0.0.1:${httpPort}/health`)).ok);
  browser=spawn(browserPath,['--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--disable-background-networking',`--remote-debugging-port=${debugPort}`,`--user-data-dir=${path.join(work,'profile')}`,'about:blank'],{windowsHide:true,stdio:'ignore'});
  const target=await until(async()=>(await(await fetch(`http://127.0.0.1:${debugPort}/json`)).json()).find(item=>item.type==='page'));
  socket=new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=reject;});
  let serial=0;const pending=new Map();
  const onmessage=event=>{const data=JSON.parse(event.data);if(data.id){const entry=pending.get(data.id);pending.delete(data.id);if(data.error)entry.reject(Error(data.error.message));else entry.resolve(data.result);}else if(data.method==='Runtime.exceptionThrown')failures.push(data.params.exceptionDetails.exception?.description||data.params.exceptionDetails.text);};
  socket.onmessage=onmessage;
  const call=(method,params={})=>new Promise((resolve,reject)=>{const id=++serial;pending.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params}));});
  const evaluate=async expression=>{const output=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(output.exceptionDetails)throw Error(output.exceptionDetails.exception?.description||output.exceptionDetails.text);return output.result.value;};
  stage='enable';await call('Runtime.enable');await call('Page.enable');
  stage='navigate';
  await call('Page.navigate',{url:`http://127.0.0.1:${httpPort}/`}).catch(error=>{
    if(!/Inspected target navigated or closed/.test(error.message))throw error;
  });
  const appTarget=await until(async()=>(await(await fetch(`http://127.0.0.1:${debugPort}/json`)).json()).find(item=>item.type==='page'&&item.url.startsWith(`http://127.0.0.1:${httpPort}/`)));
  socket.close();socket=new WebSocket(appTarget.webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=reject;});
  socket.onmessage=onmessage;await call('Runtime.enable');
  stage='wait-for-app';await until(()=>evaluate('!!document.getElementById("sanctions-status") && !!document.querySelector("#chain-hint option[value=ethereum]")'));


  await call('Browser.setDownloadBehavior',{behavior:'allow',downloadPath:work});
  await evaluate("window.waitFor=async predicate=>{for(let i=0;i<200;i++){if(predicate())return;await new Promise(r=>setTimeout(r,50));}throw Error('Browser condition timed out')};window.button=(scope,label)=>[...document.querySelectorAll(scope+' button')].find(b=>b.textContent===label)");
  const prefix='/api/greedy-collector',ETH='0x'+'ab'.repeat(20);
  const api=async(suffix,method='GET',body)=>{
    const response=await evaluate("fetch("+JSON.stringify(prefix+suffix)+",{method:"+JSON.stringify(method)+",headers:{'Content-Type':'application/json'},"+(body===undefined?'':"body:JSON.stringify("+JSON.stringify(body)+"),")+"}).then(async r=>({status:r.status,data:await r.json()}))");
    assert.ok(response.status<300,JSON.stringify(response));return response.data;
  };
  const idle="waitFor(()=>document.getElementById('cases-workspace').dataset.busy!=='true')";
  const submit=async(id,values)=>evaluate("(()=>{const f=document.getElementById("+JSON.stringify(id)+");for(const [k,v] of Object.entries("+JSON.stringify(values)+")){if(f.elements[k].type==='checkbox')f.elements[k].checked=v;else f.elements[k].value=v;}f.requestSubmit()})();"+idle);
  const click=async(scope,label)=>evaluate("button("+JSON.stringify(scope)+","+JSON.stringify(label)+").click();"+idle);
  const text=selector=>evaluate("document.querySelector("+JSON.stringify(selector)+").innerText");
  const material=await (await fetch('http://127.0.0.1:'+httpPort+'/test-case2-material')).json();
  for(const route of ['/','/health','/docs','/openapi.json','/static/js/cases.js','/static/js/case_completion.js','/static/js/case_presenter.js']){
    assert.equal((await fetch('http://127.0.0.1:'+httpPort+route)).status,200,route);
  }
  stage='create-case';
  await evaluate("document.querySelector('[data-workspace=cases]').click();"+idle);
  await submit('case-create',{title:'CASE2 browser historical Case',description:'Analyst-controlled container'});
  const row=(await api('/cases')).cases[0],casePath='/cases/'+row.id;
  assert.match(await text('#case-entities'),/empty/);
  stage='wallet-summary-note';
  for(const chain of ['ethereum','base'])await submit('case-entity',{entity_type:'wallet',entity_ref:ETH,chain,event_key:'',note:'Chain-scoped fixture reference'});
  await submit('case-summary-form',{scope:'Public stored activity only',key_findings:'Analyst-authored findings',limitations:'Bounded collection'});
  await submit('case-note',{body:'Earlier explicit analyst decision'});
  let detail=await api(casePath);assert.equal(detail.entities.length,2);
  const note=detail.notes[0];
  await submit('case-note-'+note.id,{body:'Revised explicit analyst decision'});
  assert.match(await text('#case-timeline'),/note updated/);
  stage='attachment';
  await evaluate("(()=>{const transfer=new DataTransfer();transfer.items.add(new File(['Immutable fixture attachment'],'test-evidence.txt',{type:'text/plain'}));document.querySelector('#case-upload [name=file]').files=transfer.files;document.querySelector('#case-upload [name=note]').value='Analyst fixture file';document.getElementById('case-upload').requestSubmit()})();"+idle);
  assert.match(await text('#case-attachments'),/test-evidence.txt/);
  stage='analytical-pins';
  await click('#case-entities','Pin stored risk assessment');
  await api('/sanctions/cases/'+row.id+'/pins/ethereum/'+ETH,'POST');
  await api('/attribution/cases/'+row.id+'/references','POST',{reference_type:'attribution_claim',target_id:material.claim_id,expected_version:material.claim_version});
  await api(casePath+'/discovery-pins','POST',{run_id:material.run_id});
  const preview=await api('/discovery/public-captures/'+material.capture_id+'/promotion-preview');
  await api('/discovery/public-captures/'+material.capture_id+'/cases/'+row.id+'/pin','POST',{excerpt:ETH,expected_source_fingerprint:preview.source_fingerprint});
  await api('/clustering/cases/'+row.id+'/pin','POST',{cluster_id:material.cluster_id,version:material.cluster_version});
  await api('/fund-flow/cases/'+row.id+'/pin','POST',{run_id:material.flow_id});
  await click('#cases-workspace','Refresh cases');
  await evaluate("waitFor(()=>document.getElementById('case-attribution')?.innerText.includes('Pinned assessment: Supported'))");
  const pinned=await api(casePath);
  for(const phrase of ['deterministic-v3','CURRENTLY_LISTED','Technical cluster','Fund Flow','Pinned Broad Discovery','Public source capture']){
    assert.ok((await text('#case-detail')).toLowerCase().includes(phrase.toLowerCase()),phrase);
  }
  assert.match(await text('#case-attribution'),/Contradicting/i);
  stage='historical-live-navigation';
  await click('#case-entities','Open live Discovery run');
  await evaluate("waitFor(()=>document.getElementById('discovery-run')?.dataset.runId==="+JSON.stringify(material.run_id)+")");
  assert.match(await text('#discovery-workspace'),/Pin historical run to Case/);
  await evaluate("document.querySelector('[data-workspace=cases]').click();"+idle);
  stage='first-report';
  await submit('case-report',{format:'json'});
  const first=(await api(casePath+'/reports')).reports[0];
  assert.match(await text('#case-report-history'),/case-2.0/);
  const download=async id=>Buffer.from(await(await fetch('http://127.0.0.1:'+httpPort+prefix+casePath+'/reports/'+id)).arrayBuffer());
  const firstBytes=await download(first.id);
  assert.equal(require('node:crypto').createHash('sha256').update(firstBytes).digest('hex'),first.sha256);
  const json=JSON.parse(firstBytes);assert.equal(json.attribution.references[0].pinned.claim.assessment,'supported');
  assert.ok(firstBytes.includes(Buffer.from(material.capture_hash)));
  stage='mutate-live-state-and-reopen';
  assert.ok((await fetch('http://127.0.0.1:'+httpPort+'/test-case2-mutate',{method:'POST'})).ok);
  await click('#cases-workspace','Refresh cases');
  const later=await api(casePath);
  assert.deepEqual(later.entities,pinned.entities);assert.deepEqual(later.sanctions_pins,pinned.sanctions_pins);
  await evaluate("waitFor(()=>document.getElementById('case-attribution')?.innerText.includes('Current assessment: Rejected'))");
  assert.match(await text('#case-attribution'),/Pinned assessment: Supported/);
  stage='second-report';
  await submit('case-report',{format:'json'});
  const history=(await api(casePath+'/reports')).reports;
  assert.equal(history.length,2);assert.notEqual(history[0].id,first.id);
  assert.equal(history[0].state_fingerprint,first.state_fingerprint);
  assert.deepEqual(await download(first.id),firstBytes);
  stage='archive-restore';
  await click('#case-lifecycle-panel','Archive case');
  assert.ok((await api(casePath)).archived_at);
  assert.equal((await api('/cases')).cases.length,0);
  await submit('case-search',{include_archived:true,q:'CASE2',sort:'title'});
  assert.equal((await api('/cases?include_archived=true')).cases.length,1);
  await click('#case-lifecycle-panel','Restore case');
  assert.equal((await api(casePath)).archived_at,null);
  assert.deepEqual(await download(first.id),firstBytes);
  assert.match(await text('#case-timeline'),/case archived/);assert.match(await text('#case-timeline'),/case restored/);
  assert.deepEqual(failures,[]);
  assert.equal(fs.existsSync(path.join(work,'external-request-attempted')),false);
  console.log('CASE-2 consolidated browser passed: real temporary SQLite; chain-scoped wallets; summary; note revisions; immutable attachment; all seven historical pins; live navigation; report hashes/history; later source changes; unchanged pins and old output; archive/restore; routes/assets; no external requests.');
  await call('Browser.close').catch(()=>{});
})().catch(error=>{console.error('Stage:',stage,error);console.error('Test diagnostics:',work);process.exitCode=1;}).finally(()=>{socket?.close();browser?.kill();server?.kill();});
