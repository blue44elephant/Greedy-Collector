const assert=require('node:assert/strict');
module.exports=async({evaluate,httpPort})=>{
  const base=`http://127.0.0.1:${httpPort}`;
  const metadata=await (await fetch(base+'/api/greedy-collector/chains')).json();
  assert.deepEqual(metadata.chains.map(c=>c.id),['bitcoin','ethereum','tron']);
  if(!process.env.MC1_METADATA_ONLY) {
  for(const [chain,address,name] of [['bitcoin','1BoatSLRHtKNngkdXEeobR76b53LETtpyT','Bitcoin'],['ethereum','0x'+'ab'.repeat(20),'Ethereum'],['tron','TJRabPrwbZy45sbavfcjinPJC18kjpRTv8','TRON']]){
    await evaluate(`go('wallet');document.getElementById('wallet-address').value=${JSON.stringify(address)};document.getElementById('lookup-form').requestSubmit();waitFor(()=>document.getElementById('lookup-form').dataset.busy==='false')`);
    assert.equal(await evaluate(`document.getElementById('results').hidden`),false);
    assert.equal(await evaluate(`document.getElementById('result-chain').textContent`),name);
    if(chain==='tron'){
      assert.equal(await evaluate(`document.getElementById('balance').textContent`),'1 TRX');
      assert.ok(await evaluate(`document.getElementById('transaction-rows').innerText.includes('TEST')&&document.getElementById('transaction-rows').innerText.includes('Test token')&&document.getElementById('transaction-rows').innerText.includes('Confirmed')`));
    }
    await evaluate(`go('graph');document.querySelector('#graph-workspace [name=chain]').value=${JSON.stringify(chain)};document.querySelector('#graph-workspace [name=address]').value=${JSON.stringify(address)};document.querySelector('#graph-workspace form').requestSubmit();waitFor(()=>document.querySelector('#graph-workspace form').dataset.busy==='false')`);
    assert.ok(await evaluate(`document.querySelectorAll('#graph-workspace svg').length>0`));
    await evaluate(`go('discovery');waitFor(()=>document.getElementById('discovery-workspace').dataset.busy==='false')`);
    await evaluate(`document.querySelector('#discovery-subject input').value=${JSON.stringify(address)};document.querySelector('#discovery-subject input').dispatchEvent(new Event('input',{bubbles:true}));document.getElementById('discovery-subject').requestSubmit();waitFor(()=>document.getElementById('discovery-workspace').dataset.busy==='false')`);
    if(chain==='bitcoin')assert.ok(await evaluate(`document.querySelector('[data-transform="wallet.ens_primary_name"] input[type=checkbox]').disabled`));
  }
  await evaluate(`go('monitoring');waitFor(()=>document.getElementById('monitoring-workspace').dataset.busy==='false')`);
  assert.equal(await evaluate(`document.getElementById('monitoring-workspace').hidden`),false);
  }
  const caps=await (await fetch(base+'/api/greedy-collector/discovery/transforms')).json();
  assert.deepEqual(caps.find(t=>t.id==='wallet.ens_primary_name').chains,['ethereum']);
  assert.deepEqual(caps.find(t=>t.id==='wallet.graphsense_public_tags').chains,['bitcoin','ethereum']);
  assert.ok(caps.find(t=>t.id==='wallet.local_labels').chains.includes('tron'));
  assert.ok(caps.find(t=>t.id==='wallet.manual_source_observation').chains.includes('tron'));
  assert.ok(caps.find(t=>t.id==='wallet.public_code_mentions').chains.includes('tron'));
  for(const path of ['/','/health','/docs','/openapi.json','/static/js/chains.js'])assert.equal((await fetch(base+path)).status,200);
  assert.deepEqual(await evaluate(`[...document.querySelectorAll('select[name=chain] option')].map(o=>o.value).filter(v=>v&&!['bitcoin','ethereum','tron','any'].includes(v))`),[]);
  console.log(process.env.MC1_METADATA_ONLY ? 'MC-1 remaining browser metadata and route checks passed' : 'MC-2 consolidated BTC/ETH/TRON browser smoke passed');
};
