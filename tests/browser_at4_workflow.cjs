const assert=require('node:assert/strict');
const fs=require('node:fs');const path=require('node:path');const {execFileSync}=require('node:child_process');

module.exports=async({evaluate,call,work,mode})=>{
  const address='0x'+'ab'.repeat(20),prefix='/api/greedy-collector/attribution';
  const attrIdle="waitFor(()=>document.getElementById('attribution-workspace').dataset.busy==='false')";
  const summaryIdle=scope=>`waitFor(()=>document.querySelector(${JSON.stringify(scope+' [data-attribution-summary]')})?.dataset.busy==='false')`;
  const text=selector=>evaluate(`document.querySelector(${JSON.stringify(selector)}).innerText`);
  const click=(scope,label,wait=attrIdle)=>evaluate(`button(${JSON.stringify(scope)},${JSON.stringify(label)}).click();${wait}`);
  const submit=async(id,values,wait=attrIdle)=>evaluate(`{const f=document.getElementById(${JSON.stringify(id)});for(const [key,value] of Object.entries(${JSON.stringify(values)})){f.elements[key].value=value;}f.requestSubmit();}${wait}`);
  const api=async(route,method='GET',body)=>{
    const r=await evaluate(`fetch(${JSON.stringify(prefix+route)},{method:${JSON.stringify(method)},headers:{'Content-Type':'application/json'},${body===undefined?'':`body:JSON.stringify(${JSON.stringify(body)}),`}}).then(async r=>({status:r.status,data:await r.json()}))`);
    assert.ok(r.status<300,JSON.stringify(r));return r.data;
  };
  const state=()=>JSON.parse(execFileSync(process.env.PYTHON||'python',['-B','-c',`import sqlite3,json; d=sqlite3.connect(${JSON.stringify(path.join(work,'attribution-test.db'))}); t=[r[0] for r in d.execute("SELECT name FROM sqlite_master WHERE type='table'")]; print(json.dumps({n:d.execute('SELECT COUNT(*) FROM '+n).fetchone()[0] for n in t}))`],{windowsHide:true,encoding:'utf8'}));
  const before=state();
  await evaluate("window.integrationRequests=[];window.originalIntegrationFetch=window.fetch;window.fetch=(url,options)=>{integrationRequests.push({url:String(url),method:options?.method||'GET'});return originalIntegrationFetch(url,options);}");
  await evaluate(`document.getElementById('wallet-address').value=${JSON.stringify(address)};document.getElementById('stored-button').click();waitFor(()=>document.getElementById('lookup-form').dataset.busy==='false')`);
  await evaluate(summaryIdle('#wallet-attribution'));
  assert.ok((await text('#balance')).includes('7 ETH'));
  const risk=await text('#risk-score');assert.ok(risk.includes('9'));
  assert.ok((await text('#wallet-labels')).includes('Synthetic annotation only'));
  assert.ok((await text('#wallet-attribution')).includes(mode==='migrated'?'No attribution claims have been recorded for this wallet.':'storage is not initialized'));
  const callsBeforeGraph=await evaluate("integrationRequests.filter(r=>r.url.includes('/attribution/')).length");
  await evaluate("go('graph')");
  await evaluate("{const f=document.querySelector('#graph-workspace form');f.elements.hops.value='2';f.requestSubmit();}waitFor(()=>document.querySelector('#graph-workspace form').dataset.busy==='false')");
  assert.equal(await evaluate("integrationRequests.filter(r=>r.url.includes('/attribution/')).length"),callsBeforeGraph);
  const snapshot=()=>evaluate("({nodes:[...document.querySelectorAll('#graph-workspace .graph-node')].map(n=>({id:n.dataset.nodeId,depth:n.dataset.depth,position:n.getAttribute('transform')})),edges:[...document.querySelectorAll('#graph-workspace .graph-edge')].map(n=>({key:n.dataset.edgeKey,path:n.querySelector('.edge-line').getAttribute('d')}))})");
  const topology=await snapshot();assert.equal(topology.nodes.length,3);assert.equal(topology.edges.length,2);
  const selectWallet=async()=>evaluate(`document.querySelector('#graph-workspace .graph-node[data-node-id="${address}"]').dispatchEvent(new MouseEvent('click',{bubbles:true}));${summaryIdle('#graph-attribution')}`);
  await selectWallet();
  assert.ok((await text('#graph-attribution')).includes(mode==='migrated'?'No attribution claims recorded.':'storage is not initialized'));
  assert.equal(await evaluate("document.getElementById('graph-attribution-overlay').checked"),false);
  if(mode==='unmigrated'){
    assert.deepEqual(await snapshot(),topology);
    await click('#graph-workspace','Zoom in',"Promise.resolve()");
    assert.ok((await text('#graph-detail')).includes(address));
    assert.equal(Object.keys(state()).some(name=>name.startsWith('attribution_')),false);
    await evaluate("go('wallet')");await evaluate(summaryIdle('#wallet-attribution'));
    assert.equal(await text('#risk-score'),risk);
    assert.ok(await evaluate("integrationRequests.every(r=>!r.url.includes('/lookup/'))"));return;
  }
  assert.equal((await api('/claims')).total,0); // Neither label nor graph created claims.
  const checkPrefill=async()=>{
    assert.equal(await evaluate("document.querySelector('#attr-claim-form [name=subject_ref]').value"),address);
    assert.equal(await evaluate("document.querySelector('#attr-claim-form [name=chain]').value"),'ethereum');
    assert.equal(await evaluate("document.querySelector('#attr-claim-form [name=relationship]').value"),'');
    assert.ok((await text('#attr-claim-target')).includes('Choose an entity'));
  };
  await click('#graph-attribution','Create attribution claim');await checkPrefill();
  assert.equal((await api('/claims')).total,0);
  await evaluate("go('graph')");await evaluate(summaryIdle('#graph-attribution'));assert.deepEqual(await snapshot(),topology);

  const entities=[];
  for(const name of ['Synthetic Alpha','Synthetic Beta','Synthetic Gamma'])entities.push(await api('/entities','POST',{canonical_name:name,entity_type:'service'}));
  async function create(entity,relationship){return api('/claims','POST',{entity_id:entity.id,chain:'ethereum',subject_ref:'0x'+'aB'.repeat(20),relationship,scope_note:'Synthetic AT-4 scope'});}
  async function link(row,stance){return (await api(`/claims/${row.id}/evidence/capture`,'POST',{expected_version:row.version,
    evidence:{evidence_type:'public_record',title:'Synthetic '+stance,source_name:'Synthetic source',source_url:'https://source.example/at4',origin:'public_osint',summary:'Test-only evidence',source_reliability:'reliable',reliability_rationale:'Test provenance'},
    link:{stance,directness:stance==='context'?'context':'direct',rationale:'Test relevance'}})).claim;}
  async function assess(row,assessment){const links=(await api(`/claims/${row.id}/evidence`)).items;return api(`/claims/${row.id}/assessment`,'POST',{expected_version:row.version,assessment,rationale:'Synthetic assessment',reviewed_link_ids:links.map(l=>l.id),acknowledged_contradictions:links.filter(l=>l.stance==='contradicts').map(l=>l.id),conflict_discussion:'Synthetic conflict discussion',source_verification:'Synthetic verification'});}
  let alpha=await create(entities[0],'operated_by');for(const stance of ['supports','contradicts','context'])alpha=await link(alpha,stance);alpha=await assess(alpha,'supported');
  let stale=await create(entities[1],'controlled_by');stale=await link(stale,'supports');stale=await assess(stale,'supported');stale=await link(stale,'contradicts');
  let rejected=await create(entities[2],'publicly_declared_by');rejected=await assess(rejected,'rejected');
  let archived=await create(entities[2],'operated_by');archived=await api(`/claims/${archived.id}/archive`,'POST',{expected_version:archived.version,reason:'Synthetic archive'});
  let possible=await create(entities[2],'controlled_by');possible=await link(possible,'supports');possible=await assess(possible,'possible');
  await evaluate("go('wallet')");await evaluate(summaryIdle('#wallet-attribution'));
  assert.equal(await evaluate("document.querySelectorAll('#wallet-attribution .attr-summary-card').length"),3);
  assert.ok((await text('#wallet-attribution')).includes('1 supporting / 1 contradicting / 1 contextual'));
  assert.ok((await text('#wallet-attribution')).includes('Review required'));
  assert.equal(await evaluate(`!!document.querySelector('#wallet-attribution [data-claim-id="${rejected.id}"]')`),false);
  await evaluate(`{const n=document.querySelector('#wallet-attribution input[type=checkbox]');n.checked=true;n.dispatchEvent(new Event('change'));}${summaryIdle('#wallet-attribution')}`);
  assert.ok((await text('#wallet-attribution')).includes('Rejected claim'));
  assert.ok((await text('#wallet-attribution')).includes('Claim archived'));
  await click(`#wallet-attribution [data-claim-id="${alpha.id}"]`,'Open attribution');
  assert.ok((await text('#attr-claim-detail')).includes(alpha.id));
  alpha=await assess(alpha,'strongly_supported');
  await evaluate("go('wallet')");await evaluate(summaryIdle('#wallet-attribution'));
  assert.ok((await text('#wallet-attribution')).includes('Strongly supported'));assert.equal(await text('#risk-score'),risk);
  await click('#wallet-attribution','Create attribution claim');await checkPrefill();
  await submit('attr-claim-form',{relationship:'controlled_by',scope_note:'Explicit second relationship'});
  assert.ok((await text('#attribution-workspace > .operation-status')).includes('Choose or create'));
  await click('#attr-claim-editor','Choose target entity');await click('#attr-picker','Choose entity');
  await submit('attr-claim-form',{relationship:'controlled_by',scope_note:'Explicit second relationship'});
  assert.equal((await api('/claims')).total,5); // Five active claims; the archived record is excluded.
  await evaluate("go('graph')");await evaluate(summaryIdle('#graph-attribution'));
  assert.ok((await text('#graph-attribution')).includes('Strongly supported'));
  assert.deepEqual(await snapshot(),topology);
  await click(`#graph-attribution [data-claim-id="${alpha.id}"]`,'Open attribution');assert.ok((await text('#attr-claim-detail')).includes(alpha.id));
  await evaluate("go('graph')");await evaluate(summaryIdle('#graph-attribution'));
  const baseView=await evaluate("document.querySelector('#graph-workspace svg').getAttribute('viewBox')");
  await evaluate("{const n=document.getElementById('graph-attribution-overlay');n.checked=true;n.dispatchEvent(new Event('change'));}");
  assert.equal(await evaluate("document.querySelectorAll('.attribution-entity').length"),2);
  assert.equal(await evaluate("document.querySelectorAll('.attribution-edge').length"),2);
  assert.deepEqual(await snapshot(),topology);
  assert.equal(await evaluate(`!!document.querySelector('[data-claim-id="claim:${stale.id}"]')`),false);
  assert.equal(await evaluate(`!!document.querySelector('[data-claim-id="claim:${rejected.id}"]')`),false);
  await evaluate(`document.querySelector('[data-claim-id="claim:${alpha.id}"]').dispatchEvent(new MouseEvent('click',{bubbles:true}))`);
  assert.ok((await text('#graph-detail')).includes('Strongly supported'));
  assert.ok((await text('#graph-detail')).includes('Claimed relationship: Operated by'));
  assert.ok((await text('#graph-detail')).includes('not a blockchain transaction'));
  await evaluate(`document.querySelector('[data-entity-id="entity:${entities[0].id}"]').dispatchEvent(new MouseEvent('click',{bubbles:true}))`);
  assert.ok((await text('#graph-detail')).includes('Synthetic Alpha'));
  await click('#graph-detail','Open in Attribution');assert.ok((await text('#attr-entity-detail')).includes(entities[0].id));
  await evaluate("go('graph')");await evaluate(summaryIdle('#graph-attribution'));
  assert.deepEqual(await snapshot(),topology);
  await evaluate("document.querySelector('#graph-workspace svg').scrollIntoView({block:'center'})");
  await call('Page.captureScreenshot',{format:'png'}).then(r=>fs.writeFileSync(path.join(work,'at4-overlay.png'),Buffer.from(r.data,'base64')));
  await evaluate("{const n=document.getElementById('graph-attribution-overlay');n.checked=false;n.dispatchEvent(new Event('change'));}");
  assert.equal(await evaluate("document.querySelectorAll('.attribution-edge,.attribution-entity').length"),0);
  assert.equal(await evaluate("document.querySelector('#graph-workspace svg').getAttribute('viewBox')"),baseView);
  assert.deepEqual(await snapshot(),topology);
  // Creating an entity inside the handoff retains the public subject, without auto-submitting.
  await click('#graph-attribution','Create attribution claim');await checkPrefill();
  await click('#attr-claim-editor','Create a new entity');
  await submit('attr-entity-form',{canonical_name:'Synthetic newly chosen entity',entity_type:'service',description:'Explicit descriptor',aliases:''});
  await click('#attr-entity-detail','Create claim for entity');
  assert.equal(await evaluate("document.querySelector('#attr-claim-form [name=subject_ref]').value"),address);
  assert.equal(await evaluate("document.querySelector('#attr-claim-form [name=relationship]').value"),'');
  // The new descriptor did not create a seventh claim.
  assert.equal((await api('/claims?include_archived=true')).total,6);

  // Isolated subsystem failure must retain stored wallet, labels, risk and graph.
  await evaluate("window.fetch=(url,options)=>String(url).includes('/attribution/')?Promise.resolve(new Response(JSON.stringify({detail:{code:'schema_unavailable'}}),{status:503})):originalIntegrationFetch(url,options)");
  await evaluate("go('wallet')");await evaluate(summaryIdle('#wallet-attribution'));
  assert.ok((await text('#wallet-attribution')).includes('storage is not initialized'));assert.equal(await text('#risk-score'),risk);
  assert.ok((await text('#wallet-labels')).includes('Synthetic annotation only'));
  await evaluate("go('graph')");await evaluate(summaryIdle('#graph-attribution'));
  assert.ok((await text('#graph-attribution')).includes('storage is not initialized'));assert.deepEqual(await snapshot(),topology);
  await evaluate('window.fetch=originalIntegrationFetch');
  const after=state();for(const key of Object.keys(before).filter(k=>!k.startsWith('attribution_')))assert.equal(after[key],before[key],key);
  assert.ok(await evaluate("integrationRequests.every(r=>r.url.startsWith('/api/greedy-collector/'))"));
  assert.ok(await evaluate("integrationRequests.every(r=>!r.url.includes('/lookup/')&&!r.url.includes('/kyc/'))"));
  console.log('AT-4 Wallet/Graph summaries, explicit handoffs, optional overlay, topology/risk separation and unavailable-state checks passed.');
};
