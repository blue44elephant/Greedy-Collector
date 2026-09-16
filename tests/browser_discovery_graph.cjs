const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
module.exports=async({evaluate,call,work,mode,httpPort,traffic})=>{
  const address='0x'+'ab'.repeat(20),prefix=`http://127.0.0.1:${httpPort}/api/greedy-collector`;
  const api=async(p,body)=>{const r=await fetch(prefix+p,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:undefined);assert.ok(r.ok,await r.clone().text());return r.json();};
  const busy=scope=>evaluate(`waitFor(()=>{const root=document.getElementById('${scope}-workspace');return root.dataset.busy!=='true'&&!root.querySelector('[data-busy="true"]');})`);
  const click=async(label,scope='discovery')=>{await evaluate(`button('#${scope}-workspace',${JSON.stringify(label)}).click()`);await busy(scope);};
  const text=()=>evaluate(`document.getElementById('discovery-graph-panel').innerText`);
  const view=()=>evaluate(`document.querySelector('.discovery-graph-canvas').getAttribute('viewBox')`);
  const calls=()=>fs.existsSync(path.join(work,'github-calls'))?Number(fs.readFileSync(path.join(work,'github-calls'),'utf8')):0;
  const select=async(selector,key=false)=>evaluate(`document.querySelector(${JSON.stringify(selector)}).dispatchEvent(new ${key?'KeyboardEvent':'MouseEvent'}('${key?'keydown':'click'}',{bubbles:true${key?",key:'Enter'":''}}))`);
  if(mode==='graph_unmigrated'){
    await click('Graph');assert.ok((await text()).includes('Select a stored run'));
    const r=await fetch(prefix+'/discovery/runs/missing/graph');assert.equal(r.status,503);
    for(const scope of ['wallet','graph','monitoring','alerts','cases','labels','research','attribution','discovery'])await evaluate(`go('${scope}')`);
    console.log('ED-7 unmigrated graph remains safe.');return;
  }
  const label=async(value)=>api('/labels/manual',{chain:'ethereum',address,label:value,type:'Exchange',source:'ED-7 test source',confidence:.7});
  await label('ED-7 first annotation');await label('ED-7 conflicting annotation');
  async function check(value=address){await evaluate(`document.querySelector('#discovery-subject input').value=${JSON.stringify(value)};document.querySelector('#discovery-subject input').dispatchEvent(new Event('input',{bubbles:true}));document.getElementById('discovery-subject').requestSubmit()`);await busy('discovery');}
  await check();
  async function run(ids=['wallet.local_labels','wallet.public_code_mentions'],refresh=false){
    await evaluate(`document.querySelectorAll('#discovery-transforms input[type=checkbox]').forEach(n=>{n.checked=${JSON.stringify(ids)}.includes(n.closest('[data-transform]').dataset.transform);n.dispatchEvent(new Event('change',{bubbles:true}));});document.querySelector('#discovery-plan [name=refresh]').checked=${refresh};document.querySelector('#discovery-plan [name=refresh]').dispatchEvent(new Event('change',{bubbles:true}));`);
    await click('Plan selected pivots');await click('Run discovery');
    await evaluate(`waitFor(()=>['completed','partial'].includes(document.getElementById('discovery-run').dataset.status))`);await busy('discovery');
    const id=await evaluate(`document.getElementById('discovery-run').dataset.runId`);
    if(await evaluate(`!document.getElementById('discovery-graph-panel').hidden`)){
      const g=await api('/discovery/runs/'+id+'/graph');
      await evaluate(`waitFor(()=>{const text=document.getElementById('discovery-graph-panel').innerText;return text.includes('Run: ${id}')&&text.includes('Showing ${g.items.length} of ${g.total}');})`);
    }
    return id;
  }
  const first=await run(),before=await api('/discovery/runs/'+first+'/graph'),providerCalls=calls(),runCount=(await api('/discovery/runs')).total;
  await click('Graph');assert.equal(await evaluate(`document.querySelectorAll('.discovery-graph-node').length`),4);
  assert.equal(await evaluate(`document.querySelectorAll('.discovery-graph-edge').length`),3);
  assert.ok((await text()).includes('Showing 3 of 3'));
  assert.ok(await evaluate(`document.querySelector('.discovery-graph-canvas').textContent.includes('repository_contains')`));
  await select('.discovery-graph-node.label_annotation',true);assert.ok((await text()).includes('Annotation confidence (metadata)'));
  await select('.discovery-graph-node.code_location');assert.ok((await text()).includes('test/browser-fixture')&&(await text()).includes('src/wallet.txt'));
  const link=await evaluate(`(()=>{const a=document.querySelector('#discovery-graph-detail a');return {href:a.href,target:a.target,rel:a.rel};})()`);
  assert.ok(link.href.startsWith('https://github.com/'));assert.equal(link.target,'_blank');assert.equal(link.rel,'noopener noreferrer');
  await select('.discovery-graph-edge');assert.ok((await text()).includes('Relationship detail'));
  const original=await view();await click('Zoom in');assert.notEqual(await view(),original);await click('Fit to graph');assert.equal(await view(),original);
  await evaluate(`document.querySelector('.discovery-graph-canvas').scrollIntoView({block:'center'})`);
  const rect=await evaluate(`(()=>{const r=document.querySelector('.discovery-graph-canvas').getBoundingClientRect();return {x:r.x,y:r.y};})()`);
  await call('Input.dispatchMouseEvent',{type:'mousePressed',x:rect.x+15,y:rect.y+15,button:'left',clickCount:1});
  await call('Input.dispatchMouseEvent',{type:'mouseMoved',x:rect.x+65,y:rect.y+55,button:'left',buttons:1});
  await call('Input.dispatchMouseEvent',{type:'mouseReleased',x:rect.x+65,y:rect.y+55,button:'left',clickCount:1});
  assert.notEqual(await view(),original);await click('Reset view');assert.equal(await view(),original);
  await select('.discovery-graph-node.code_location');await click('Zoom in');const kept=await view();
  await click('Open result');assert.ok(await evaluate(`!document.getElementById('discovery-detail').hidden`));
  await click('Back to Discovery graph');assert.equal(await view(),kept);assert.ok((await text()).includes('Code location'));
  assert.equal(calls(),providerCalls);assert.equal((await api('/discovery/runs')).total,runCount);
  await click('Open result');
  await evaluate(`document.querySelector('#discovery-review [name=status]').value='relevant';document.querySelector('#discovery-review [name=reason]').value='ED-7 explicit code review';document.getElementById('discovery-review').requestSubmit()`);await busy('discovery');
  if(mode==='graph_partial'){
    await click('Back to Discovery graph');assert.ok((await text()).includes('Promotion metadata is unavailable'));
    assert.equal(await evaluate(`!!button('#discovery-promotion','Use as attribution evidence')`),false);
    console.log('ED-7 partial migration graph, node/edge details and viewport passed.');return;
  }
  const entity=await api('/attribution/entities',{canonical_name:'ED-7 explicit test entity'});
  const claim=await api('/attribution/claims',{entity_id:entity.id,chain:'ethereum',subject_ref:address,relationship:'operated_by',scope_note:'Explicit ED-7 test scope'});
  await click('Use as attribution evidence');await busy('attribution');await click('Choose claim','attribution');
  await evaluate(`const f=document.getElementById('attr-handoff-confirm');f.elements.stance.value='context';f.elements.directness.value='context';f.elements.rationale.value='Explicit graph-to-result promotion';f.elements.confirmed.checked=true;`);
  await click('Preview promotion','attribution');await evaluate(`document.getElementById('attr-handoff-confirm').requestSubmit()`);await busy('attribution');
  await click('Back to Discovery','attribution');await busy('discovery');
  assert.equal(await view(),kept);assert.ok((await text()).includes('Promoted: 1'));
  await click('Open attribution');await click('Open claim');await busy('attribution');
  assert.ok(await evaluate(`document.getElementById('attribution-workspace').innerText.includes('${claim.id}')`));
  await evaluate(`go('discovery')`);await busy('discovery');assert.equal(await view(),kept);
  assert.equal(calls(),providerCalls);
  await evaluate(`(async()=>{const b=new FormData();b.append('file',new Blob([${JSON.stringify('chain,address,label,type,source,confidence\nethereum,'+address+',ED-7 first annotation,Bridge,ED-7 test source,0.2\n')}],{type:'text/csv'}),'test.csv');const r=await fetch('/api/greedy-collector/labels/import',{method:'POST',body:b});if(!r.ok)throw Error('Test-only Label update failed');})()`);
  fs.writeFileSync(path.join(work,'github-mode'),'changed');await run(undefined,true);
  await click('Load history');const history=await api('/discovery/runs'),index=history.items.findIndex(r=>r.id===first);
  await evaluate(`[...document.querySelectorAll('#discovery-history-rows button')].filter(b=>b.textContent==='Open run')[${index}].click()`);await busy('discovery');
  const old=await api('/discovery/runs/'+first+'/graph');assert.deepEqual(old.edges,before.edges);
  assert.deepEqual(old.items.map(n=>[n.id,n.observation_id,n.summary]),before.items.map(n=>[n.id,n.observation_id,n.summary]));
  await select('.discovery-graph-node.code_location');assert.ok((await text()).includes('Review required'));
  assert.ok((await text()).includes('Test-only code context'));assert.equal((await text()).includes('Changed test-only context'),false);
  // Real test-only stored rows exercise the actual summary cap and page UI.
  for(let i=0;i<99;i++)await label('ED-7 bounded annotation '+i);
  await run(undefined,true);assert.ok((await text()).includes('Showing 100 of 101'));
  assert.equal(await evaluate(`document.getElementById('discovery-run').dataset.status`),'partial');
  assert.equal(await evaluate(`document.querySelectorAll('.discovery-graph-node').length`),101);
  await click('Next graph page');assert.ok((await text()).includes('Showing 1 of 101'));
  await run(['wallet.manual_exact_web']);assert.ok((await text()).includes('No Discovery results were returned for this run.'));
  assert.equal(await evaluate(`document.querySelectorAll('.discovery-graph-node').length`),1);
  await check('0x'+'cd'.repeat(20));await run(['wallet.local_labels']);assert.equal(await evaluate(`document.querySelectorAll('.discovery-graph-edge').length`),0);
  const beforeOpen=calls();await click('Open blockchain graph');assert.equal(await evaluate(`document.getElementById('graph-workspace').hidden`),false);
  assert.equal(await evaluate(`document.querySelector('#graph-workspace form [name=address]').value`),'0x'+'cd'.repeat(20));assert.equal(calls(),beforeOpen);
  assert.equal(traffic.some(url=>url.includes('/lookup/')),false);
  console.log('ED-7 mixed graph, selection/pan/zoom, ED-6 handoff, historical material, 101-result pagination, manual/empty and blockchain navigation passed.');
};
