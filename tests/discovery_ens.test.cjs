const {test}=require('node:test');
const assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url');
const path=require('node:path');
const load=()=>import(pathToFileURL(path.join(__dirname,'../static/js/discovery_graph_layout.js')));
test('ENS lane preserves all existing positions and is deterministic',async()=>{
  const {discoveryLayout,CARD}=await load();
  const base={root:{id:'wallet'},items:Array.from({length:40},(_,i)=>({id:'old:'+i,type:i%2?'code_location':'label_annotation'}))};
  const graph={...base,items:[...base.items,...Array.from({length:60},(_,i)=>({id:'ens:'+i,type:'ens_name'}))]};
  const old=discoveryLayout(base),layout=discoveryLayout(graph);
  for(const [id,p] of old.positions)assert.deepEqual(layout.positions.get(id),p);
  assert.deepEqual(discoveryLayout({...graph,items:[...graph.items].reverse()}),layout);
  assert.equal(layout.positions.size,101);
  const points=[...layout.positions.values()];
  for(let i=0;i<points.length;i++)for(let j=i+1;j<points.length;j++)assert.ok(Math.abs(points[i].x-points[j].x)>CARD.width||Math.abs(points[i].y-points[j].y)>CARD.height);
});
test('ENS inbound path ends at the focus boundary',async()=>{
  const {discoveryLayout,discoveryPath}=await load();const g={root:{id:'wallet'},items:[{id:'ens',type:'ens_name'}]};
  const layout=discoveryLayout(g);assert.deepEqual(layout.positions.get('ens'),{x:0,y:260});
  assert.equal(discoveryPath({source:'ens',target:'wallet'},layout),'M 0 187 C 0 130, 0 130, 0 73');
});
