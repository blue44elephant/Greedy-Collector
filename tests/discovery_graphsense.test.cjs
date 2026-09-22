const {test}=require('node:test');
const assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url');
const path=require('node:path');
const load=()=>import(pathToFileURL(path.join(__dirname,'../static/js/discovery_graph_layout.js')));
test('public annotation lane is deterministic, collision free, preserving all prior lanes',async()=>{
  const {discoveryLayout,CARD}=await load();
  const prior={root:{id:'wallet'},items:Array.from({length:40},(_,i)=>({id:'old:'+i,type:['code_location','label_annotation','ens_name','source_page'][i%4]}))};
  const graph={...prior,items:[...prior.items,...Array.from({length:60},(_,i)=>({id:'public:'+i,type:'public_annotation'}))]};
  const before=discoveryLayout(prior),after=discoveryLayout(graph);
  for(const [id,p] of before.positions)assert.deepEqual(after.positions.get(id),p);
  assert.deepEqual(discoveryLayout({...graph,items:[...graph.items].reverse()}),after);
  assert.equal(after.positions.size,101);
  const points=[...after.positions.values()];
  for(let i=0;i<points.length;i++)for(let j=i+1;j<points.length;j++)assert.ok(Math.abs(points[i].x-points[j].x)>CARD.width||Math.abs(points[i].y-points[j].y)>CARD.height);
});
test('public annotation arrow points from wallet to tag',async()=>{
  const {discoveryLayout,discoveryPath}=await load();
  const layout=discoveryLayout({root:{id:'wallet'},items:[{id:'tag',type:'public_annotation'}]});
  assert.equal(discoveryPath({source:'wallet',target:'tag'},layout),'M 155 0 C 260 0, 260 -95, 365 -95');
});
