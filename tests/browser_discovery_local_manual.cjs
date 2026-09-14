const assert=require('node:assert/strict');
module.exports=async({evaluate,httpPort,traffic})=>{
  const prefix='/api/greedy-collector/discovery';const address='0x'+'ab'.repeat(20);
  const local=async(path,body)=>{const r=await fetch(`http://127.0.0.1:${httpPort}/api/greedy-collector${path}`,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:undefined);assert.ok(r.ok,await r.clone().text());return r.json();};
  const text=()=>evaluate(`document.getElementById('discovery-workspace').innerText`);
  const busy=()=>evaluate(`waitFor(()=>document.getElementById('discovery-workspace').dataset.busy==='false')`);
  const click=async value=>{await evaluate(`button('#discovery-workspace',${JSON.stringify(value)}).click()`);await busy();};
  const before=await local('/discovery/runs');assert.equal(before.total,0);
  const record=await local('/labels/manual',{chain:'ethereum',address,label:'Synthetic stored label',type:'Exchange',source:'Synthetic analyst annotation',confidence:.8});
  await evaluate(`document.querySelector('#discovery-subject input').value=${JSON.stringify(address)};document.querySelector('#discovery-subject input').dispatchEvent(new Event('input',{bubbles:true}));document.getElementById('discovery-subject').requestSubmit()`);await busy();
  const catalog=await local('/discovery/transforms');
  for(const id of ['wallet.local_labels','wallet.manual_exact_web'])assert.ok(catalog.find(t=>t.id===id).implemented&&catalog.find(t=>t.id===id).executable);
  assert.equal(catalog.find(t=>t.id==='wallet.public_code_mentions').implemented,true);
  assert.equal(catalog.find(t=>t.id==='wallet.public_code_mentions').configured,false);
  assert.ok((await text()).includes('Manual action generation available'));
  assert.ok((await text()).includes('Not executable'));
  assert.equal((await local('/discovery/runs')).total,0,'typing does not run Discovery');
  async function run(tid,refresh=false){
    await evaluate(`document.querySelectorAll('#discovery-transforms input[type=checkbox]').forEach(n=>{n.checked=n.closest('[data-transform]').dataset.transform===${JSON.stringify(tid)};n.dispatchEvent(new Event('change',{bubbles:true}));});document.querySelector('#discovery-plan [name=refresh]').checked=${refresh};document.querySelector('#discovery-plan [name=refresh]').dispatchEvent(new Event('change',{bubbles:true}));`);
    const count=(await local('/discovery/runs')).total;await click('Plan selected pivots');assert.equal((await local('/discovery/runs')).total,count);
    await click('Run discovery');await evaluate(`waitFor(()=>document.getElementById('discovery-run').dataset.status==='completed')`);
    return evaluate(`document.getElementById('discovery-run').dataset.runId`);
  }
  const first=await run('wallet.local_labels');await evaluate(`waitFor(()=>!!button('#discovery-results','Inspect result'))`);await click('Inspect result');
  assert.ok((await text()).includes('Synthetic stored label'));assert.ok((await text()).includes('Original annotation source'));
  assert.ok((await text()).includes('Synthetic analyst annotation'));assert.ok((await text()).includes('Annotation confidence (metadata only)'));
  await evaluate(`document.querySelector('#discovery-review [name=status]').value='relevant';document.querySelector('#discovery-review [name=reason]').value='Synthetic relevance review';document.getElementById('discovery-review').requestSubmit()`);await busy();
  assert.ok((await text()).includes('Synthetic relevance review'));
  let items=(await local('/discovery/runs/'+first+'/results')).items;const old=items[0].observation;const rid=items[0].result.id;
  // Existing CSV upsert changes type/confidence without inventing a Label edit API.
  await evaluate(`(async()=>{const body=new FormData();body.append('file',new Blob([${JSON.stringify('chain,address,label,type,source,confidence\nethereum,'+address+',Synthetic stored label,Bridge,Synthetic analyst annotation,0.3\n')}],{type:'text/csv'}),'test.csv');const r=await fetch('/api/greedy-collector/labels/import',{method:'POST',body});if(!r.ok)throw Error('CSV upsert failed');})()`);
  const fresh=await run('wallet.local_labels',true);await evaluate(`waitFor(()=>!!button('#discovery-results','Inspect result'))`);await click('Inspect result');
  assert.ok((await text()).includes('Source material changed since the previous review.'));
  assert.ok((await text()).includes('Bridge'));
  const historical=await local('/discovery/observations/'+old.id);assert.equal(historical.source_snapshot.record.confidence,.8);
  const current=(await local('/discovery/runs/'+fresh+'/results')).items[0];assert.equal(current.result.id,rid);
  const detail=await local('/discovery/observations/'+current.observation.id);assert.equal(detail.source_snapshot.record.confidence,.3);
  const count=(await local('/discovery/results/'+rid+'/observations')).total;
  const manual=await run('wallet.manual_exact_web');await evaluate(`waitFor(()=>!!document.querySelector('.discovery-manual-action a'))`);
  assert.ok((await text()).includes('The search engine was not queried by Greedy Collector.'));
  assert.ok((await text()).includes('Opening this link leaves GC'));
  const link=await evaluate(`(()=>{const a=document.querySelector('.discovery-manual-action a');return {href:a.href,target:a.target,rel:a.rel};})()`);
  const url=new URL(link.href);assert.equal(url.origin,'https://www.google.com');assert.equal(url.searchParams.get('q'),'"'+address+'"');
  assert.equal(link.target,'_blank');assert.equal(link.rel,'noopener noreferrer');
  // Deliberately never click the external link.
  const row=await local('/discovery/runs/'+manual);assert.equal(row.sources[0].status,'manual_ready');assert.equal(row.returned_count,0);
  assert.equal((await local('/discovery/runs/'+manual+'/results')).total,0);
  assert.equal((await local('/discovery/results/'+rid+'/observations')).total,count);
  assert.equal(traffic.some(url=>url.includes('/lookup/')||url.startsWith('https://')),false);
  console.log('ED-4A Local Labels, immutable refresh/review, manual outbound action and mixed capabilities passed.');
};
