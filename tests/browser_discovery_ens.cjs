// Single isolated browser session: positive, reviewed promotion, changed name,
// mismatch, empty, cached empty, and navigation through all nine workspaces.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
module.exports=async({evaluate,work,httpPort,traffic})=>{
  const address='0x'+'ab'.repeat(20),prefix=`http://127.0.0.1:${httpPort}/api/greedy-collector`;
  const api=async(p,body)=>{const r=await fetch(prefix+p,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:undefined);assert.ok(r.ok,await r.clone().text());return r.json();};
  const busy=scope=>evaluate(`waitFor(()=>{const root=document.getElementById('${scope}-workspace');return root.dataset.busy!=='true'&&!root.querySelector('[data-busy="true"]');})`);
  const click=async(label,scope='discovery')=>{await evaluate(`button('#${scope}-workspace',${JSON.stringify(label)}).click()`);await busy(scope);};
  const calls=()=>fs.existsSync(path.join(work,'ens-calls'))?Number(fs.readFileSync(path.join(work,'ens-calls'),'utf8')):0;
  const text=scope=>evaluate(`document.getElementById('${scope}-workspace').innerText`);
  await evaluate(`go('discovery')`);await busy('discovery');
  await evaluate(`document.dispatchEvent(new CustomEvent('open-discovery',{detail:{chain:'ethereum',address:'${address}',origin:'wallet'}}))`);await busy('discovery');
  // Explicit subject check exercises the same local resolver without a lookup.
  await evaluate(`document.querySelector('#discovery-subject input').value='${address}';document.querySelector('#discovery-subject input').dispatchEvent(new Event('input',{bubbles:true}));document.getElementById('discovery-subject').requestSubmit()`);await busy('discovery');
  assert.ok((await text('discovery')).includes('ENS Primary Name'));
  assert.equal(await evaluate(`document.querySelectorAll('#discovery-transforms input:checked').length`),0);assert.equal(calls(),0);
  async function run(mode,refresh=true){
    fs.writeFileSync(path.join(work,'ens-mode'),mode);
    await evaluate(`go('discovery')`);await busy('discovery');
    await evaluate(`document.querySelectorAll('#discovery-transforms input[type=checkbox]').forEach(n=>{n.checked=n.closest('[data-transform]').dataset.transform==='wallet.ens_primary_name';n.dispatchEvent(new Event('change',{bubbles:true}));});document.querySelector('#discovery-plan [name=refresh]').checked=${refresh};document.querySelector('#discovery-plan [name=refresh]').dispatchEvent(new Event('change',{bubbles:true}));`);
    await click('Plan selected pivots');await click('Run discovery');
    await evaluate(`waitFor(()=>['completed','partial','failed'].includes(document.getElementById('discovery-run').dataset.status))`);await busy('discovery');
    const id=await evaluate(`document.getElementById('discovery-run').dataset.runId`);
    const row=await api('/discovery/runs/'+id),items=(await api('/discovery/runs/'+id+'/results')).items;
    return {id,row,items};
  }
  const first=await run('success',false);assert.equal(first.row.status,'completed');assert.equal(first.items.length,1);assert.equal(calls(),1);
  const item=first.items[0],ob=await api('/discovery/observations/'+item.observation.id);
  assert.equal(ob.source_snapshot.primary_name,'alice.eth');assert.equal(ob.source_snapshot.verification,'forward_verified');
  await click('Graph');await evaluate(`waitFor(()=>!!document.querySelector('.discovery-graph-node.ens_name'))`);
  await evaluate(`document.querySelector('.discovery-graph-node.ens_name').dispatchEvent(new MouseEvent('click',{bubbles:true}))`);
  assert.ok((await text('discovery')).includes('Forward verified'));
  const g=await api('/discovery/runs/'+first.id+'/graph');assert.equal(g.edges[0].source,g.items[0].id);assert.equal(g.edges[0].target,g.root.id);
  await click('Open result');assert.ok((await text('discovery')).includes('alice.eth'));
  assert.equal(await evaluate(`!!button('#discovery-promotion','Use as attribution evidence')`),false);
  await evaluate(`document.querySelector('#discovery-review [name=status]').value='relevant';document.querySelector('#discovery-review [name=reason]').value='Explicit ENS technical-context review';document.getElementById('discovery-review').requestSubmit()`);await busy('discovery');
  const entity=await api('/attribution/entities',{canonical_name:'Explicit browser test entity'});
  const claim=await api('/attribution/claims',{entity_id:entity.id,chain:'ethereum',subject_ref:address,relationship:'operated_by',scope_note:'Explicit test scope; ENS is context only'});
  await click('Use as attribution evidence');await busy('attribution');await click('Choose claim','attribution');
  assert.equal(await evaluate(`document.querySelector('#attr-handoff-confirm [name=stance]').value`),'');
  await evaluate(`const f=document.getElementById('attr-handoff-confirm');f.elements.stance.value='context';f.elements.directness.value='context';f.elements.rationale.value='Technical naming context only';f.elements.confirmed.checked=true;`);
  await click('Preview promotion','attribution');await evaluate(`document.getElementById('attr-handoff-confirm').requestSubmit()`);await busy('attribution');
  assert.ok((await text('attribution')).includes('Promoted to immutable evidence'));
  const promotion=(await api('/discovery/results/'+item.result.id+'/promotions')).items[0];assert.equal(promotion.stance,'context');
  const evidence=await api('/attribution/evidence/'+promotion.evidence_id);assert.equal(evidence.origin,'public_osint');assert.equal(evidence.metadata_json.observation.source_snapshot.primary_name,'alice.eth');
  await click('Open attribution','attribution');await click('Inspect capture','attribution');assert.ok((await text('attribution')).includes('alice.eth'));
  const changed=await run('changed');assert.equal(changed.items.length,1);assert.equal((await api('/discovery/runs/'+changed.id+'/graph')).items[0].title,'alice2.eth');
  assert.equal((await api('/discovery/runs/'+first.id+'/graph')).items[0].title,'alice.eth');assert.deepEqual(await api('/attribution/evidence/'+evidence.id),evidence);
  const mismatch=await run('mismatch');assert.equal(mismatch.row.status,'partial');assert.equal(mismatch.items.length,0);
  assert.ok((await text('discovery')).includes('reverse_forward_mismatch'));
  await click('Graph');assert.equal((await api('/discovery/runs/'+mismatch.id+'/graph')).items.length,0);
  await evaluate(`waitFor(()=>document.querySelectorAll('.discovery-graph-node.ens_name').length===0)`);
  const empty=await run('empty');assert.equal(empty.row.status,'completed');assert.equal(empty.items.length,0);
  assert.ok((await text('discovery')).includes('No verified ENS primary name returned.'));
  assert.equal((await api('/discovery/runs/'+empty.id+'/graph')).items.length,0);
  const before=calls();const cached=await run('empty',false);assert.equal(cached.row.sources[0].status,'cache_hit');assert.equal(calls(),before);
  assert.equal((await api('/attribution/entities')).total,1);assert.equal((await api('/attribution/claims')).total,1);assert.equal((await api('/attribution/claims/'+claim.id)).assessment,'unassessed');
  for(const scope of ['wallet','graph','monitoring','alerts','cases','labels','research','attribution','discovery']){await evaluate(`go('${scope}')`);await busy(scope);assert.equal(await evaluate(`document.getElementById('${scope}-workspace').hidden`),false);}
  assert.equal(calls(),4);assert.equal(traffic.some(url=>url.includes('/lookup/')),false);
  assert.deepEqual(traffic.filter(url=>!url.startsWith(`http://127.0.0.1:${httpPort}/`)&&!url.startsWith('data:image/svg+xml;base64,')),[]);
  assert.equal(JSON.stringify([first,changed,mismatch,empty,evidence]).includes('ed8a-browser-test-only'),false);
  console.log('ED-8A consolidated browser passed: normalization, graph, Context promotion, immutable history, mismatch, empty/cache, all nine workspaces.');
};
