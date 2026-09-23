const {test}=require('node:test');
const assert=require('node:assert/strict');
test('central metadata drives choices, case identity and capability display',async()=>{
  const m=await require('./chain_metadata_fixture.cjs')();
  assert.deepEqual(m.chains,[['bitcoin','Bitcoin'],['ethereum','Ethereum']]);
  assert.equal(m.chainMetadata('ethereum').native_symbol,'ETH');
  assert.equal(m.addressKey('bitcoin','1AbC'),'1AbC');
  assert.equal(m.addressKey('bitcoin','BC1ABC'),'bc1abc');
  assert.equal(m.addressKey('ethereum','0xAB'),'0xab');
  assert.equal(m.supportedChain('test_chain'),false);
  assert.equal(m.hasCapability('ethereum','monitoring'),false);
});
test('Base58 case siblings remain separate in graph rendering',async()=>{
  await require('./chain_metadata_fixture.cjs')();
  const {layoutGraph}=await import('../static/js/graph_layout.js');
  const graph={nodes:[{id:'1AbC',chain:'bitcoin',is_focus:true},{id:'1abc',chain:'bitcoin'}],edges:[{id:'1',source:'1AbC',target:'1abc'}]};
  const result=layoutGraph(graph);assert.equal(result.nodes.length,2);assert.equal(result.positions.size,2);
});
