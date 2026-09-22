const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {execFileSync}=require('node:child_process');

module.exports=async({evaluate,call,work,mode,httpPort,traffic})=>{
  const prefix=`http://127.0.0.1:${httpPort}/api/greedy-collector`;
  const ETH='0x'+'ab'.repeat(20), BTC='1BoatSLRHtKNngkdXEeobR76b53LETtpyT';
  const unmigrated=mode==='handoff_unmigrated', github=mode==='handoff_github';
  await evaluate(`window.handoffRequests=[];window.handoffFetch=window.fetch;window.fetch=(url,options={})=>{handoffRequests.push({url:String(url),method:options.method||'GET'});return handoffFetch(url,options);}`);
  const api=async(route,body)=>{const r=await fetch(prefix+route,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:undefined);assert.ok(r.ok,await r.clone().text());return r.json();};
  const text=()=>evaluate(`document.getElementById('discovery-workspace').innerText`);
  const busy=()=>evaluate(`waitFor(()=>document.getElementById('discovery-workspace').dataset.busy==='false')`);
  const click=async(scope,label)=>{await evaluate(`button(${JSON.stringify(scope)},${JSON.stringify(label)}).click()`);await busy();};
  const counters=()=>['handoff-provider-calls','github-calls'].map(file=>fs.existsSync(path.join(work,file))?Number(fs.readFileSync(path.join(work,file),'utf8')):0);
  const state=()=>JSON.parse(execFileSync(process.env.PYTHON||'python',['-B','-c',
    `import sqlite3,json,hashlib; d=sqlite3.connect(${JSON.stringify(path.join(work,'discovery-test.db'))}); tables=[r[0] for r in d.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]; print(json.dumps({t:hashlib.sha256(repr(d.execute('SELECT * FROM "'+t+'" ORDER BY rowid').fetchall()).encode()).hexdigest() for t in tables}))`],{encoding:'utf8',windowsHide:true}));
  async function wallet(address,stored=false){
    await evaluate(`go('wallet');document.getElementById('wallet-address').value=${JSON.stringify(address)};${stored?"document.getElementById('stored-button').click()":"document.getElementById('lookup-form').requestSubmit()"};waitFor(()=>document.getElementById('lookup-form').dataset.busy==='false')`);
    assert.equal(await evaluate(`document.getElementById('results').hidden`),false);
    await evaluate(`waitFor(()=>document.querySelector('#wallet-attribution [data-attribution-summary]')?.dataset.busy==='false')`);
  }
  async function enter(origin,address){
    const before=state(),counts=counters(),start=await evaluate('handoffRequests.length');
    await click(origin==='wallet'?'#wallet-discovery':'#graph-detail','Discover public evidence');
    assert.equal(await evaluate(`document.getElementById('discovery-workspace').hidden`),false);
    assert.equal(await evaluate(`document.querySelector('#discovery-subject input').value`),address);
    assert.equal(await evaluate(`document.querySelectorAll('#discovery-transforms input[type=checkbox]:checked').length`),0);
    assert.equal(await evaluate(`document.getElementById('discovery-run-button').hidden`),true);
    assert.ok((await text()).includes(origin==='wallet'?'Back to wallet':'Back to graph'));
    assert.ok((await text()).includes('Local Labels')||(await text()).includes('Stored Label context'));
    assert.ok((await text()).includes(github?'Configured':'Not configured'));
    assert.deepEqual(counters(),counts,'No provider attempt on handoff');assert.deepEqual(state(),before,'No runs, quota, annotations, risk, Cases or Attribution writes');
    const requests=await evaluate(`handoffRequests.slice(${start})`);
    assert.ok(requests.every(r=>r.method==='GET'||r.url==='/api/greedy-collector/resolve'),JSON.stringify(requests));
    assert.ok(requests.every(r=>!r.url.includes('/lookup/')));
    if(unmigrated)assert.ok((await text()).includes('Discovery storage is not initialized for this database.'));
  }
  async function back(origin){
    const before=state(),counts=counters(),start=traffic.length;
    await click('#discovery-entry',origin==='wallet'?'Back to wallet':'Back to graph');
    assert.equal(await evaluate(`document.getElementById('${origin}-workspace').hidden`),false);
    assert.deepEqual(counters(),counts);assert.deepEqual(state(),before);
    assert.ok(traffic.slice(start).every(url=>!url.includes('/lookup/')&&!url.includes('/graph?')));
  }
  async function planRun(source,refresh=false,terminal=true){
    await evaluate(`document.querySelectorAll('#discovery-transforms input[type=checkbox]').forEach(n=>{n.checked=n.closest('[data-transform]').dataset.transform===${JSON.stringify(source==='github'?'wallet.public_code_mentions':'wallet.local_labels')};n.dispatchEvent(new Event('change',{bubbles:true}));});document.querySelector('#discovery-plan [name=refresh]').checked=${refresh};document.querySelector('#discovery-plan [name=refresh]').dispatchEvent(new Event('change',{bubbles:true}));`);
    const before=state(),counts=counters();await click('#discovery-workspace','Plan selected pivots');assert.deepEqual(state(),before);assert.deepEqual(counters(),counts);
    await click('#discovery-workspace','Run discovery');
    if(terminal)await evaluate(`waitFor(()=>document.getElementById('discovery-run').dataset.status==='completed')`);
    return evaluate(`document.getElementById('discovery-run').dataset.runId`);
  }
  // Both provider-backed and subsequently stored wallets use the same handoff.
  for(const address of [BTC,ETH]){
    await wallet(address);const result=await evaluate(`document.getElementById('results').innerHTML`);
    await enter('wallet',address);await back('wallet');
    assert.equal(await evaluate(`document.getElementById('results').innerHTML`),result);
    await wallet(address,true);await enter('wallet',address);await back('wallet');
  }
  if(!unmigrated){
    await enter('wallet',ETH);const run=await planRun('gc_labels');
    await evaluate(`waitFor(()=>!!button('#discovery-results','Inspect result'))`);await click('#discovery-workspace','Inspect result');
    assert.ok((await text()).includes('ED-5 test annotation'));await back('wallet');
    await enter('wallet',ETH);assert.ok((await text()).includes('Current subject'));assert.ok((await text()).includes(run));
    // Re-entry removes selections and an existing plan without erasing the run.
    await evaluate(`document.querySelector('#discovery-transforms input[data-source=gc_labels]').checked=true;document.querySelector('#discovery-transforms input[data-source=gc_labels]').dispatchEvent(new Event('change',{bubbles:true}));`);
    await click('#discovery-workspace','Plan selected pivots');await back('wallet');await enter('wallet',ETH);await back('wallet');
  }
  // Real stored graph, optional real persisted Attribution overlay.
  if(!unmigrated){
    const entity=await api('/attribution/entities',{canonical_name:'ED-5 fixture entity',entity_type:'service'});
    let claim=await api('/attribution/claims',{entity_id:entity.id,chain:'ethereum',subject_ref:ETH,relationship:'operated_by',scope_note:'Test-only explicit claim'});
    claim=(await api(`/attribution/claims/${claim.id}/evidence/capture`,{expected_version:claim.version,evidence:{evidence_type:'public_record',title:'Test-only record',source_name:'Fixture',source_url:'https://example.invalid/evidence',origin:'public_osint',summary:'Fixture only',source_reliability:'reliable',reliability_rationale:'Test'},link:{stance:'supports',directness:'direct',rationale:'Test'}})).claim;
    const links=(await api(`/attribution/claims/${claim.id}/evidence`)).items;
    await api(`/attribution/claims/${claim.id}/assessment`,{expected_version:claim.version,assessment:'supported',rationale:'Test',reviewed_link_ids:links.map(l=>l.id),acknowledged_contradictions:[],conflict_discussion:'None',source_verification:'Test only'});
  }
  await evaluate(`go('graph');{const f=document.querySelector('#graph-workspace form');f.elements.chain.value='ethereum';f.elements.address.value='${ETH}';f.elements.hops.value='2';f.requestSubmit();}waitFor(()=>document.querySelector('#graph-workspace form').dataset.busy==='false')`);
  const select=async()=>evaluate(`document.querySelector('#graph-workspace .graph-node[data-node-id="${ETH}"]').dispatchEvent(new MouseEvent('click',{bubbles:true}));waitFor(()=>document.querySelector('#graph-attribution [data-attribution-summary]')?.dataset.busy==='false')`);
  await select();
  if(!unmigrated){await evaluate(`document.getElementById('graph-attribution-overlay').click();waitFor(()=>document.querySelectorAll('.attribution-entity').length===1)`);}
  await evaluate(`button('#graph-workspace','Zoom in').click()`);
  const topology=()=>evaluate(`({nodes:[...document.querySelectorAll('#graph-workspace .graph-node')].map(n=>[n.dataset.nodeId,n.getAttribute('transform'),n.dataset.depth,n.className.baseVal]),edges:[...document.querySelectorAll('#graph-workspace .graph-edge')].map(n=>[n.dataset.edgeKey,n.querySelector('.edge-line').getAttribute('d')]),view:document.querySelector('#graph-workspace svg').getAttribute('viewBox'),overlay:document.getElementById('graph-attribution-overlay').checked,entities:[...document.querySelectorAll('.attribution-entity')].map(n=>n.outerHTML)})`);
  const original=await topology();await enter('graph',ETH);await back('graph');assert.deepEqual(await topology(),original);
  // Edge/entity inspectors cannot launch wallet pivots; stale detached actions do nothing.
  await evaluate(`window.oldDiscoveryAction=button('#graph-detail','Discover public evidence');document.querySelector('#graph-workspace .graph-edge').dispatchEvent(new MouseEvent('click',{bubbles:true}));oldDiscoveryAction.click()`);
  assert.equal(await evaluate(`!!button('#graph-detail','Discover public evidence')`),false);
  assert.equal(await evaluate(`document.getElementById('graph-workspace').hidden`),false);
  if(!unmigrated){await select();await evaluate(`waitFor(()=>!!document.querySelector('.attribution-entity'));document.querySelector('.attribution-entity').dispatchEvent(new MouseEvent('click',{bubbles:true}))`);assert.equal(await evaluate(`!!button('#graph-detail','Discover public evidence')`),false);}
  // Transaction results and unresolved/error states hide the Wallet action.
  await evaluate(`go('wallet');document.getElementById('wallet-address').value='0x'+'1'.repeat(64);document.getElementById('lookup-form').requestSubmit();waitFor(()=>document.getElementById('lookup-form').dataset.busy==='false')`);
  assert.equal(await evaluate(`document.getElementById('results').hidden`),true);
  await evaluate(`document.getElementById('wallet-address').value='unsupported input';document.getElementById('lookup-form').requestSubmit();waitFor(()=>document.getElementById('lookup-form').dataset.busy==='false')`);
  assert.equal(await evaluate(`document.getElementById('results').hidden`),true);
  if(github){
    await wallet(ETH,true);await enter('wallet',ETH);const calls=counters();await planRun('github');assert.equal(counters()[1],calls[1]+1);
    await evaluate(`waitFor(()=>!!button('#discovery-results','Inspect result'))`);await click('#discovery-workspace','Inspect result');assert.ok((await text()).includes('Matched code context'));
    fs.writeFileSync(path.join(work,'github-mode'),'slow');const active=await planRun('github',true,false);
    await evaluate(`waitFor(()=>['queued','running'].includes(document.getElementById('discovery-run').dataset.status))`);
    await wallet(BTC,true);const count=(await api('/discovery/runs')).total,attempts=counters()[1];
    await click('#wallet-discovery','Discover public evidence');
    assert.ok((await text()).includes('You have an active run for another subject.'));
    assert.equal(await evaluate(`document.getElementById('discovery-run').dataset.runId`),active);
    assert.equal((await api('/discovery/runs')).total,count);assert.equal(counters()[1],attempts);
    await evaluate(`waitFor(()=>document.getElementById('discovery-run').dataset.status==='completed')`);
    assert.equal((await api('/discovery/runs/'+active)).cancel_requested_at,null);
  }
  // Malformed/stale context: safe error, no execution. Resolver stays authoritative.
  const before=state(),counts=counters();
  for(const [chain,address,expected] of [['ethereum','0x'+'aB'.repeat(20),ETH],['bitcoin','BC1QXY2KGDYGJRSQTZQ2N0YRF2493P83KKFJHX0WLH','bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh']]){
    await evaluate(`document.dispatchEvent(new CustomEvent('open-discovery',{detail:${JSON.stringify({origin:'wallet',chain,address})}}))`);await busy();
    assert.equal(await evaluate(`document.querySelector('#discovery-subject input').value`),expected);
  }
  await evaluate(`document.dispatchEvent(new CustomEvent('open-discovery',{detail:{origin:'wallet',chain:'bitcoin',address:'${ETH}'}}))`);await busy();
  assert.ok((await text()).includes('does not match its chain'));
  await evaluate(`document.dispatchEvent(new CustomEvent('open-discovery',{detail:{origin:'wallet',chain:'ethereum',address:'0x'+'1'.repeat(64)}}))`);await busy();
  assert.ok((await text()).includes('wallet addresses only'));
  await evaluate(`document.dispatchEvent(new CustomEvent('open-discovery',{detail:{origin:'wallet',chain:'unsupported',address:'private internal text'}}))`);await busy();
  assert.ok((await text()).includes('handoff requires a supported wallet'));assert.equal((await text()).includes('private internal text'),false);
  await evaluate(`document.dispatchEvent(new CustomEvent('open-discovery',{detail:{origin:'graph',chain:'ethereum',address:'${ETH}',isCurrent:()=>false}}))`);await busy();
  assert.ok((await text()).includes('selected wallet view has changed'));assert.deepEqual(state(),before);assert.deepEqual(counters(),counts);
  // An incoming handoff during a local read is queued. Leaving while queued
  // must not reopen the workspace or lose the latest explicit subject.
  await evaluate(`window.fetchBeforeQueue=window.fetch;window.delayHandoff=true;window.fetch=(url,options)=>{if(delayHandoff&&String(url).endsWith('/resolve')){delayHandoff=false;return new Promise(resolve=>{window.releaseHandoff=()=>resolve(fetchBeforeQueue(url,options));});}return fetchBeforeQueue(url,options);};document.dispatchEvent(new CustomEvent('open-discovery',{detail:{origin:'wallet',chain:'ethereum',address:'${ETH}'}}));waitFor(()=>typeof window.releaseHandoff==='function')`);
  await evaluate(`document.dispatchEvent(new CustomEvent('open-discovery',{detail:{origin:'wallet',chain:'bitcoin',address:'${BTC}'}}));go('wallet');releaseHandoff();waitFor(()=>document.querySelector('#discovery-subject input').value==='${BTC}'&&document.getElementById('discovery-workspace').dataset.busy==='false')`);
  assert.equal(await evaluate(`document.getElementById('discovery-workspace').hidden`),true);
  await evaluate(`window.fetch=window.fetchBeforeQueue`);assert.deepEqual(state(),before);assert.deepEqual(counters(),counts);
  const runs=unmigrated?null:(await api('/discovery/runs')).total;
  await call('Page.reload');
  let ready=false;
  for(let n=0;n<100&&!ready;n++){await new Promise(r=>setTimeout(r,100));try{ready=await evaluate(`document.readyState==='complete'&&!!document.querySelector('#graph-workspace form')`);}catch{}}
  assert.ok(ready,'Reloaded application initialized');
  await evaluate(`window.waitFor=async predicate=>{for(let n=0;n<150;n++){if(predicate())return;await new Promise(r=>setTimeout(r,50));}throw Error('Reload condition timed out');};document.querySelector('[data-workspace=discovery]').click()`);await busy();
  assert.equal(await evaluate(`document.querySelector('#discovery-subject input').value`),'');
  if(!unmigrated)assert.equal((await api('/discovery/runs')).total,runs);
  else assert.equal(Object.keys(state()).some(t=>t.startsWith('discovery_')),false);
  assert.deepEqual(counters(),counts);assert.ok(traffic.every(url=>url.startsWith(`http://127.0.0.1:${httpPort}/`)));
  console.log('ED-5 browser passed:',mode,'Wallet/Graph handoffs, return state, no automatic work, typed selection, capabilities, history and reload.');
};
