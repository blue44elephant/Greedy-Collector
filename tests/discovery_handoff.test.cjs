const {before}=require('node:test');
before(()=>require('./chain_metadata_fixture.cjs')());
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url');
const path=require('node:path');
const load=()=>import(pathToFileURL(path.join(__dirname,'../static/js/discovery_handoff.js')));
const BTC='1BoatSLRHtKNngkdXEeobR76b53LETtpyT', ETH='0x'+'aB'.repeat(20);

test('handoff preserves full address/case and discards unexpected fields',async()=>{
  const {walletContext}=await load();
  for(const [chain,address] of [['bitcoin',BTC],['ethereum',ETH],['bitcoin','BC1QXY2KGDYGJRSQTZQ2N0YRF2493P83KKFJHX0WLH']]){
    assert.deepEqual(walletContext({origin:'wallet',chain,address:' '+address+' ',url:'https://invalid',run:true}),{origin:'wallet',chain,address,isCurrent:null});
  }
});
test('unsupported and missing context is rejected without requests',async()=>{
  const {walletContext}=await load();
  for(const value of [null,{}, {origin:'cases',chain:'ethereum',address:ETH},{origin:'wallet',chain:'ens',address:ETH},{origin:'graph',chain:'bitcoin',address:''},{origin:'graph',chain:'bitcoin',address:'x'.repeat(129)}])assert.equal(walletContext(value),null);
});
test('graph requires supported wallet type; rejects transaction and overlay entities',async()=>{
  const {graphWalletEligible}=await load();const graph={nodes:[],edges:[]};
  assert.ok(graphWalletEligible(graph,{id:ETH,chain:'ethereum'}));
  for(const type of ['transaction','entity','repository'])assert.equal(graphWalletEligible(graph,{id:ETH,chain:'ethereum',type}),false);
  assert.equal(graphWalletEligible(graph,{id:ETH,chain:'ethereum',kind:'unsupported'}),false);
  assert.equal(graphWalletEligible(graph,{id:ETH,chain:'unknown'}),false);
});
test('existing Graph label categories are wallet metadata, not structural kinds',async()=>{
  const {graphWalletEligible}=await load();
  for(const type of ['Wallet','Exchange','Unknown','Bridge'])assert.ok(graphWalletEligible({nodes:[],edges:[]},{id:ETH,chain:'ethereum',type}));
});
test('AT-4 Bitcoin case sibling guard is retained for Discovery',async()=>{
  const {graphWalletEligible}=await load();const node={id:BTC,chain:'bitcoin'};
  assert.ok(graphWalletEligible({nodes:[node],edges:[]},node));
  assert.equal(graphWalletEligible({nodes:[node],edges:[{source:BTC.toLowerCase(),target:BTC}]},node),false);
});
test('return context dispatches only to its known origin without I/O',async()=>{
  const {returnFromDiscovery}=await load();const previous=global.document;const events=[];
  global.document={dispatchEvent:e=>events.push(e)};
  try{for(const origin of ['wallet','graph'])returnFromDiscovery({origin,chain:'ethereum',address:ETH,isCurrent:()=>true});}
  finally{global.document=previous;}
  assert.deepEqual(events.map(e=>[e.type,e.detail]),[['return-discovery',{workspace:'wallet'}],['return-discovery',{workspace:'graph'}]]);
});
test('stale or missing return view is safe and cannot trigger navigation',async()=>{
  const {returnFromDiscovery}=await load();
  for(const value of [null,{origin:'wallet',chain:'ethereum',address:ETH},{origin:'graph',chain:'bitcoin',address:BTC,isCurrent:()=>false}])assert.throws(()=>returnFromDiscovery(value),/original view has changed/);
});
