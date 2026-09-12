const {test}=require('node:test');
const assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url');
const path=require('node:path');
const load=name=>import(pathToFileURL(path.join(__dirname,'../static/js/'+name+'.js')));
const claim=(id,extra={})=>({id,chain:'ethereum',subject_ref:'0x'+'a'.repeat(40),entity_id:'e'+id,
  entity:{id:'e'+id,canonical_name:'Synthetic '+id,entity_type:'service',aliases:[],archived_at:null},
  relationship:'operated_by',assessment:'supported',needs_review:false,archived_at:null,entity_archived:false,
  active_evidence_counts:{supports:1,contradicts:1,context:1},...extra});

test('overlay excludes rejected, archived, unassessed and stale claims',async()=>{
  const {overlayData}=await load('attribution_overlay');
  const rows=[claim('ok'),claim('possible',{assessment:'possible'}),claim('strong',{assessment:'strongly_supported'}),
    claim('rejected',{assessment:'rejected'}),claim('archive',{archived_at:'date'}),claim('parent',{entity_archived:true}),
    claim('draft',{assessment:'unassessed'}),claim('stale',{needs_review:true})];
  const result=overlayData(rows,{x:0},[0,0,900,560]);
  assert.equal(result.edges.length,3);assert.equal(result.entities.length,3);
  assert.ok(result.edges.every(e=>e.id.startsWith('claim:')&&e.target.startsWith('entity:')&&e.source.startsWith('wallet:ethereum:')));
  for(const e of result.edges)for(const forbidden of ['tx_hash','value_native','fee','block_number','depth'])assert.equal(Object.hasOwn(e,forbidden),false);
});
test('overlay layout is deterministic and does not mutate base inputs',async()=>{
  const {overlayData}=await load('attribution_overlay');const rows=[claim('2'),claim('1')],pos={x:22,y:10},bounds=[-70,-110,900,560];
  const before=JSON.stringify({rows,pos,bounds});const result=overlayData(rows,pos,bounds);
  assert.deepEqual(result,overlayData([...rows].reverse(),pos,bounds));assert.equal(JSON.stringify({rows,pos,bounds}),before);
  assert.ok(result.entities.every(e=>e.y>bounds[1]+bounds[3]));
});
test('multiple claims to same entity remain independent without duplicate entity cards',async()=>{
  const {overlayData}=await load('attribution_overlay');const a=claim('1'),b=claim('2',{entity_id:a.entity_id,entity:a.entity,relationship:'controlled_by'});
  const result=overlayData([a,b],{x:0},[0,0,900,560]);assert.equal(result.entities.length,1);assert.equal(result.edges.length,2);
});
test('case-folded Bitcoin collisions are guarded using nodes and transaction endpoints',async()=>{
  const {graphSubjectIsUnambiguous}=await load('attribution_summary');const id='1BoatSLRHtKNngkdXEeobR76b53LETtpyT',node={id,chain:'bitcoin'};
  assert.equal(graphSubjectIsUnambiguous({nodes:[node],edges:[]},node),true);
  assert.equal(graphSubjectIsUnambiguous({nodes:[node,{id:id.toLowerCase(),chain:'bitcoin'}],edges:[]},node),false);
  assert.equal(graphSubjectIsUnambiguous({nodes:[node],edges:[{source:id.toLowerCase(),target:id}]},node),false);
  assert.equal(graphSubjectIsUnambiguous({nodes:[],edges:[]},{id:'0xAB',chain:'ethereum'}),true);
});
test('same-hash transfer records do not become identity joins or collapse in overlay inputs',async()=>{
  const {layoutGraph}=await load('graph_layout');const {overlayData}=await load('attribution_overlay');
  const graph={nodes:[{id:'a',is_focus:true},{id:'b'}],edges:[{source:'a',target:'b',id:'one',tx_hash:'same',value_native:'1'},{source:'a',target:'b',id:'two',tx_hash:'same',value_native:'2'}]};
  const layout=layoutGraph(graph),before=JSON.stringify(graph);overlayData([claim('1')],layout.positions.get('a'),layout.bounds);
  assert.equal(layout.connections[0].records.length,2);assert.equal(JSON.stringify(graph),before);
});
