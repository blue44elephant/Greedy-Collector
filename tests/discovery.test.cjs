const {test}=require('node:test');
const assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url');
const path=require('node:path');
const load=()=>import(pathToFileURL(path.join(__dirname,'../static/js/discovery_api.js')));

test('only explicit queued/running states are active',async()=>{
  const {activeRun}=await load();
  for(const status of ['queued','running'])assert.equal(activeRun({status}),true);
  for(const status of ['completed','partial','failed','cancelled','interrupted','unknown',undefined])assert.equal(activeRun({status}),false);
});
async function harness(read,limit=80){
  const {createRunPoller}=await load();let serial=0;const timers=new Map(),received=[],errors=[];let pauses=0;
  const poller=createRunPoller({read,receive:r=>received.push(r),error:e=>errors.push(e),paused:()=>pauses++,limit,
    schedule:(fn,delay)=>{assert.equal(delay,1500);timers.set(++serial,fn);return serial;},unschedule:id=>timers.delete(id)});
  return {poller,timers,received,errors,pauses:()=>pauses,tick:async()=>{const [id,fn]=timers.entries().next().value;timers.delete(id);await fn();}};
}
test('poll only selected run, stop after terminal status',async()=>{
  let calls=0;const h=await harness(async id=>{assert.equal(id,'selected');return {id,status:++calls===2?'completed':'running'};});
  h.poller.start('selected');assert.equal(calls,0);await h.tick();await h.tick();assert.equal(calls,2);assert.equal(h.timers.size,0);
});
test('leaving workspace aborts in-flight read and ignores stale completion',async()=>{
  let finish,signal;const h=await harness((id,s)=>{signal=s;return new Promise(r=>finish=r);});
  h.poller.start('old');const pending=h.tick();h.poller.stop();assert.equal(signal.aborted,true);
  finish({id:'old',status:'running'});await pending;assert.equal(h.received.length,0);assert.equal(h.timers.size,0);
});
test('switching run cancels previous timer and never polls history',async()=>{
  const seen=[];const h=await harness(async id=>{seen.push(id);return {id,status:'partial'};});
  h.poller.start('old');h.poller.start('new');assert.equal(h.timers.size,1);await h.tick();assert.deepEqual(seen,['new']);assert.equal(h.timers.size,0);
});
test('bounded polling pauses and failures do not retry',async()=>{
  const h=await harness(async id=>({id,status:'running'}),2);h.poller.start('active');await h.tick();await h.tick();assert.equal(h.pauses(),1);assert.equal(h.timers.size,0);
  const failed=await harness(async()=>{throw Error('test');});failed.poller.start('active');await failed.tick();assert.equal(failed.errors.length,1);assert.equal(failed.timers.size,0);
});
test('API uses local JSON requests, explicit fingerprint/idempotency and fixed errors',async()=>{
  const {discoveryRequest}=await load();const original=global.fetch;const calls=[];
  try {
    global.fetch=async(url,options)=>{calls.push({url,options});return {ok:true,json:async()=>({id:'test'})};};
    await discoveryRequest('/runs',{body:{expected_plan_fingerprint:'test'},key:'intent'});
    assert.equal(calls[0].url,'/api/greedy-collector/discovery/runs');assert.equal(calls[0].options.method,'POST');assert.equal(calls[0].options.headers['Idempotency-Key'],'intent');
    for(const code of ['schema_unavailable','storage_unavailable','conflict','not_found','invalid_request','origin_rejected','internal_error']){
      global.fetch=async()=>({ok:false,json:async()=>({detail:{code,message:'secret SQL C:\\private\\token'}})});
      await assert.rejects(discoveryRequest('/runs'),e=>!e.message.includes('secret')&&!e.message.includes('SQL'));
    }
    await assert.rejects(discoveryRequest('https://example.invalid'));
    await assert.rejects(discoveryRequest('//evil'));
    await assert.rejects(discoveryRequest('/runs/../../evil'));
  }finally{global.fetch=original;}
});
