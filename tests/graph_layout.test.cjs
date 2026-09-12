const {test} = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const modulePromise = import(pathToFileURL(path.join(__dirname,'../static/js/graph_layout.js')));
const fixture = () => ({nodes:['a','b','c','d'].map(id=>({id,label:id,chain:'ethereum',is_focus:id==='a'})),
  edges:[['a','b'],['b','c'],['c','d'],['a','b'],['b','a']].map(([source,target],index)=>({source,target,tx_hash:String(index),id:String(index),value_native:'0.000001',token_symbol:'TEST'}))});

test('stable layout under response reordering', async()=>{
  const {layoutGraph}=await modulePromise; const graph=fixture(); const first=layoutGraph(graph);
  graph.nodes.reverse(); graph.edges.reverse(); const second=layoutGraph(graph);
  assert.deepEqual([...first.positions],[...second.positions]);
  assert.deepEqual(first.connections,second.connections);
});
test('focus and successive hops occupy distinct ordered layers',async()=>{
  const {layoutGraph}=await modulePromise; const {positions}=layoutGraph(fixture());
  assert.equal(positions.get('a').x,0);
  for(const [index,key] of ['a','b','c','d'].entries())assert.equal(positions.get(key).depth,index);
  assert.ok(positions.get('b').x < positions.get('c').x);
});
test('duplicate node IDs do not create duplicate cards',async()=>{
  const {layoutGraph}=await modulePromise;const graph=fixture();graph.nodes.push({...graph.nodes[0]});
  assert.equal(layoutGraph(graph).nodes.length,4);
});
test('parallel relationships retain each record and separate reverse direction',async()=>{
  const {layoutGraph}=await modulePromise;const layout=layoutGraph(fixture());
  assert.equal(layout.connections.find(c=>c.source==='a'&&c.target==='b').records.length,2);
  assert.equal(layout.connections.reduce((n,c)=>n+c.records.length,0),5);
  assert.ok(layout.connections.find(c=>c.source==='b'&&c.target==='a'));
});
test('large layers wrap with collision-free cards and no node loss',async()=>{
  const {layoutGraph}=await modulePromise;
  const graph={nodes:[{id:'focus',is_focus:true},...Array.from({length:200},(_,i)=>({id:String(i),label:'A very long real stored label'}))],edges:Array.from({length:200},(_,i)=>({source:'focus',target:String(i),id:String(i)}))};
  const layout=layoutGraph(graph), boxes=[...layout.positions.values()];assert.equal(boxes.length,201);
  for(let i=0;i<boxes.length;i++)for(let j=i+1;j<boxes.length;j++){
    const a=boxes[i],b=boxes[j];assert.ok(a.x+a.width<=b.x||b.x+b.width<=a.x||a.y+a.height<=b.y||b.y+b.height<=a.y);
  }
});
test('empty and disconnected graphs retain honest structure',async()=>{
  const {layoutGraph}=await modulePromise;
  assert.equal(layoutGraph({nodes:[],edges:[]}).positions.size,0);
  const graph=fixture();graph.nodes.push({id:'unconnected'});assert.equal(layoutGraph(graph).positions.get('unconnected').depth,null);
});
test('reverse and self connections have distinct finite paths',async()=>{
  const {layoutGraph,connectionPath}=await modulePromise;const {positions}=layoutGraph(fixture());const a=positions.get('a'),b=positions.get('b');
  assert.notEqual(connectionPath(a,b),connectionPath(b,a));assert.ok(!connectionPath(a,a).includes('NaN'));
});
test('connections across wrapped columns use clearance outside entity cards',async()=>{
  const {connectionPath}=await modulePromise;
  const a={x:0,y:0,width:220,height:76},b={x:1200,y:200,width:220,height:76};
  assert.ok(connectionPath(a,b,-100).includes(' -100'));
  assert.ok(!connectionPath(a,b,-100).includes('NaN'));
});
