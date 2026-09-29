import test from 'node:test';
import assert from 'node:assert/strict';
import {captureFacts,captureFailure} from '../static/js/public_source_capture.js';
import {discoveryRequest} from '../static/js/discovery_api.js';
import {discoveryLayout} from '../static/js/discovery_graph_layout.js';
const capture={id:'c',status:'captured',requested_url:'https://source.example/start',final_url:'https://source.example/end',retrieved_at:'2026-09-29T00:00:00Z',http_status:200,content_type:'text/html',byte_count:100,body_sha256:'a'.repeat(64),wallet_present_in_capture:true,change_state:'CHANGED',origin:{provider:'tavily_search',chain:'bitcoin',wallet:'test'}};
test('capture facts preserve hash timestamp URL and provider rather than implicit ownership',()=>{
 const facts=Object.fromEntries(captureFacts(capture));assert.equal(facts['SHA-256'],capture.body_sha256);assert.equal(facts['Final URL'],capture.final_url);assert.ok(facts.Retrieved);assert.equal(facts['Original provider'],'tavily_search');
});
for(const [value,expected] of [[true,'Yes'],[false,'No'],[null,'Not evaluated']])test(`capture wallet presence ${expected}`,()=>assert.equal(Object.fromEntries(captureFacts({...capture,wallet_present_in_capture:value}))['Wallet string found'],expected));
for(const state of ['CHANGED','UNCHANGED','FIRST_CAPTURE'])test(`capture change state ${state}`,()=>assert.equal(Object.fromEntries(captureFacts({...capture,change_state:state}))['Changed since previous capture'],state==='FIRST_CAPTURE'?'First capture':state));
test('closed failure explanations do not echo raw server input',()=>{
 assert.match(captureFailure('blocked_private_address'),/blocked/);assert.match(captureFailure('blocked_onion'),/Manual Source Observation/);assert.match(captureFailure('response_too_large'),/5 MiB/);assert.match(captureFailure('unsupported_content_type'),/HTML and plain text/);assert.doesNotMatch(captureFailure('secret raw traceback'),/secret|traceback/);
});
test('explicit capture API paths accept local operations and preserve consent',async()=>{
 const original=globalThis.fetch,calls=[];
 globalThis.fetch=async(url,options)=>{calls.push({url,options});return {ok:true,json:async()=>({id:'c'})};};
 try{await discoveryRequest('/observations/o/public-captures',{body:{confirmed:true}});await discoveryRequest('/public-captures/c/review',{body:{status:'relevant'}});await discoveryRequest('/public-captures/c/promote',{body:{confirmed:true,excerpt:'literal'}});await discoveryRequest('/public-captures/c/cases/k/pin',{body:{excerpt:'literal'}});
 assert.equal(calls.length,4);assert.ok(calls.every(c=>c.url.startsWith('/api/greedy-collector/discovery/')));assert.equal(JSON.parse(calls[0].options.body).confirmed,true);
 }finally{globalThis.fetch=original;}
});
test('capture nodes have distinct stable positions only in Discovery layout',()=>{
 const g={root:{id:'root'},items:[{id:'result',type:'web_source'},{id:'capture',type:'public_capture'}]};const a=discoveryLayout(g),b=discoveryLayout(g);assert.deepEqual(a.positions,b.positions);assert.notDeepEqual(a.positions.get('result'),a.positions.get('capture'));
});
