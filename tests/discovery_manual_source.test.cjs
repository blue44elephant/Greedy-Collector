const {test}=require('node:test');
const assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url');
const path=require('node:path');
const load=()=>import(pathToFileURL(path.join(__dirname,'../static/js/discovery_graph_layout.js')));
test('manual source lane is stable, collision free and preserves existing layouts',async()=>{
  const {discoveryLayout,CARD}=await load();
  const prior={root:{id:'wallet'},items:Array.from({length:40},(_,i)=>({id:'prior:'+i,type:['code_location','label_annotation','ens_name'][i%3]}))};
  const g={...prior,items:[...prior.items,...Array.from({length:60},(_,i)=>({id:'source:'+i,type:'source_page'}))]};
  const before=discoveryLayout(prior),after=discoveryLayout(g);
  for(const [id,p] of before.positions)assert.deepEqual(after.positions.get(id),p);
  assert.deepEqual(discoveryLayout({...g,items:[...g.items].reverse()}),after);
  assert.equal(after.positions.size,101);
  const points=[...after.positions.values()];
  for(let i=0;i<points.length;i++)for(let j=i+1;j<points.length;j++)assert.ok(Math.abs(points[i].x-points[j].x)>CARD.width||Math.abs(points[i].y-points[j].y)>CARD.height);
});
test('source arrow ends at wallet top boundary',async()=>{
  const {discoveryLayout,discoveryPath}=await load();const graph={root:{id:'wallet'},items:[{id:'source',type:'source_page'}]};
  const layout=discoveryLayout(graph);assert.deepEqual(layout.positions.get('source'),{x:0,y:-260});
  assert.equal(discoveryPath({source:'source',target:'wallet'},layout),'M 0 -187 C 0 -130, 0 -130, 0 -73');
});
