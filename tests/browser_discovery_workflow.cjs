const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const sleep=ms=>new Promise(r=>setTimeout(r,ms));

module.exports=async({evaluate,call,work,mode,httpPort,traffic})=>{
  const p='/api/greedy-collector/discovery';
  const text=()=>evaluate(`document.getElementById('discovery-workspace').innerText`);
  const busy=()=>evaluate(`waitFor(()=>document.getElementById('discovery-workspace').dataset.busy==='false')`);
  const click=async label=>{await evaluate(`button('#discovery-workspace',${JSON.stringify(label)}).click()`);await busy();};
  const api=async suffix=>{const response=await fetch(`http://127.0.0.1:${httpPort}${p}${suffix}`);return {status:response.status,data:await response.json()};};
  const setSubject=async(address='0x'+'ab'.repeat(20))=>{
    await evaluate(`document.querySelector('#discovery-subject input').value=${JSON.stringify(address)};document.querySelector('#discovery-subject input').dispatchEvent(new Event('input',{bubbles:true}));document.getElementById('discovery-subject').requestSubmit()`);await busy();
  };
  await evaluate(`go('discovery')`);await busy();
  assert.equal(await evaluate(`document.querySelectorAll('[data-workspace]').length`),11);
  assert.ok((await text()).includes('Public-source pivots & candidate evidence'));
  assert.equal(await evaluate(`document.querySelector('#discovery-workspace h1').textContent`),'Discovery');
  if(mode==='mc1'||mode==='mc2'){
    await require('./browser_multichain.cjs')({evaluate,call,work,httpPort,traffic});
  }else if(mode==='graphsense'){
    await require('./browser_discovery_graphsense.cjs')({evaluate,call,work,mode,httpPort,traffic});
  }else if(mode==='manual_source'){
    await require('./browser_discovery_manual_source.cjs')({evaluate,call,work,mode,httpPort,traffic});
  }else if(mode==='ens'){
    await require('./browser_discovery_ens.cjs')({evaluate,call,work,mode,httpPort,traffic});
  }else if(mode.startsWith('graph')){
    await require('./browser_discovery_graph.cjs')({evaluate,call,work,mode,httpPort,traffic});
  }else if(mode.startsWith('promotion')){
    await require('./browser_discovery_promotion.cjs')({evaluate,call,work,mode,httpPort,traffic});
  }else if(mode.startsWith('handoff')){
    await require('./browser_discovery_handoff.cjs')({evaluate,call,work,mode,httpPort,traffic});
  }else if(mode==='unmigrated'){
    assert.ok((await text()).includes('Discovery storage is not initialized for this database.'));
    assert.equal((await api('/runs')).status,503);
    await setSubject();await click('Why unavailable — diagnostic plan');assert.ok((await text()).includes('No selected pivots are currently executable.'));
    for(const name of ['wallet','graph','monitoring','alerts','cases','labels','research','attribution']){
      await evaluate(`go('${name}')`);assert.equal(await evaluate(`document.getElementById('${name}-workspace').hidden`),false);
    }
    // Only legacy tables may be created by existing startup; Discovery must stay absent.
    const {execFileSync}=require('node:child_process');
    const output=execFileSync(process.env.PYTHON||'python',['-c',"import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(c.execute(\"select count(*) from sqlite_master where type='table' and name like 'discovery_%'\").fetchone()[0])",path.join(work,'discovery-test.db')],{windowsHide:true,encoding:'utf8'});
    assert.equal(output.trim(),'0');
  }else if(mode==='github'){
    await require('./browser_discovery_github.cjs')({evaluate,call,work,httpPort,traffic});
  }else if(mode==='production'){
    await require('./browser_discovery_local_manual.cjs')({evaluate,call,work,httpPort,traffic});
  }else{
    await setSubject();
    const choose=async(failure=false)=>evaluate(`document.querySelectorAll('#discovery-transforms input[type=checkbox]').forEach(n=>{n.checked=n.dataset.source==='test_success'||${failure};n.dispatchEvent(new Event('change',{bubbles:true}));})`);
    const run=async({refresh=false,failure=false}={})=>{
      await choose(failure);
      await evaluate(`const f=document.querySelector('#discovery-plan input[name=refresh]');f.checked=${refresh};f.dispatchEvent(new Event('change',{bubbles:true}));`);
      const before=(await api('/runs')).data.total;
      await click('Plan selected pivots');assert.ok((await text()).includes('Plan ready for inspection'));
      assert.equal((await api('/runs')).data.total,before,'planning must not create runs');
      assert.ok((await text()).includes('paid authorized 0'));
      await click('Run discovery');
      const id=await evaluate(`document.getElementById('discovery-run').dataset.runId`);
      return id;
    };
    const finish=async status=>evaluate(`waitFor(()=>document.getElementById('discovery-run').dataset.status==='${status}' && !!button('#discovery-results','Inspect result'))`);
    const first=await run();await finish('completed');
    assert.equal(fs.readFileSync(path.join(work,'execution-count'),'utf8'),'1');
    let items=(await api(`/runs/${first}/results`)).data.items;const original=items[0].observation;
    await click('Inspect result');assert.ok((await text()).includes('Observations'));assert.ok((await text()).includes('Synthetic observation revision 1'));
    await evaluate(`document.querySelector('#discovery-review [name=status]').value='relevant';document.querySelector('#discovery-review [name=reason]').value='Synthetic browser relevance decision';document.getElementById('discovery-review').requestSubmit()`);await busy();
    assert.equal((await api('/results/'+items[0].result.id)).data.review_status,'relevant');assert.ok((await text()).includes('Synthetic browser relevance decision'));
    const beforeHistory=fs.readFileSync(path.join(work,'execution-count'),'utf8');
    await click('Open run');await click('Inspect result');assert.ok((await text()).includes('Relevant'));
    await click('Archive run');assert.ok((await text()).includes('Archived'));assert.equal((await api('/runs')).data.total,0);
    await click('Restore run');assert.equal((await api('/runs')).data.total,1);
    assert.equal(fs.readFileSync(path.join(work,'execution-count'),'utf8'),beforeHistory);
    const second=await run();await finish('completed');
    assert.ok((await text()).includes('Cached observation'));items=(await api(`/runs/${second}/results`)).data.items;
    assert.equal(items[0].observation.id,original.id);assert.equal(items[0].observation.retrieved_at,original.retrieved_at);
    assert.equal(fs.readFileSync(path.join(work,'execution-count'),'utf8'),'1');
    const third=await run({refresh:true});await finish('completed');assert.equal(fs.readFileSync(path.join(work,'execution-count'),'utf8'),'2');
    assert.ok((await text()).includes('Review needed'));await click('Inspect result');assert.ok((await text()).includes('Source material changed since the previous review.'));
    assert.equal(await evaluate(`document.querySelector('#discovery-review [name=status]').value`),'unreviewed');
    const partial=await run({failure:true});await finish('partial');assert.ok((await text()).includes('Provider error'));assert.ok((await text()).includes('Synthetic browser reference'));
    const countAtTerminal=traffic.filter(url=>url.endsWith('/runs/'+partial)).length;await sleep(3300);
    assert.equal(traffic.filter(url=>url.endsWith('/runs/'+partial)).length,countAtTerminal,'terminal polling stopped');
    await run({refresh:true});await click('Cancel');assert.equal(await evaluate(`document.getElementById('discovery-run').dataset.status`),'cancelled');
    const leaving=await run({refresh:true});await evaluate(`go('wallet')`);await sleep(1800);
    const countAway=traffic.filter(url=>url.endsWith('/runs/'+leaving)).length;await sleep(2000);assert.equal(traffic.filter(url=>url.endsWith('/runs/'+leaving)).length,countAway,'no polling while away');
    await evaluate(`go('discovery')`);await busy();await finish('completed');
    // Safe conflict/error rendering through the actual UI request boundary.
    await choose();await click('Plan selected pivots');
    await evaluate(`window.originalDiscoveryFetch=window.fetch;window.fetch=async(url,opts)=>url.endsWith('/discovery/runs')&&opts?.method==='POST'?new Response(JSON.stringify({detail:{code:'conflict',message:'SQL secret local-path'}}),{status:409,headers:{'Content-Type':'application/json'}}):originalDiscoveryFetch(url,opts)`);
    await click('Run discovery');assert.ok((await text()).includes('Discovery conflict'));assert.equal((await text()).includes('SQL secret'),false);
    await evaluate(`window.fetch=window.originalDiscoveryFetch`);
    assert.equal((await api('/results/'+items[0].result.id+'/observations')).data.total>=2,true);
    // One consolidated screenshot after workflow completion, not per edit.
    await call('Page.captureScreenshot',{format:'png'}).then(r=>fs.writeFileSync(path.join(work,'discovery.png'),Buffer.from(r.data,'base64')));
  }
  assert.equal((await text()).includes('ed3-test-only-secret'),false);
  // Native date inputs may load Chromium's inline calendar icon; no network.
  assert.deepEqual(traffic.filter(url=>!url.startsWith(`http://127.0.0.1:${httpPort}/`)&&!url.startsWith('data:image/svg+xml;base64,')),[]);
  assert.equal(fs.existsSync(path.join(work,'external-request-attempted')),false);
  console.log('ED-3 browser workflow passed:',mode);
};
