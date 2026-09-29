import test from 'node:test';
import assert from 'node:assert/strict';
import {availability,broadDefaults,providerDiagnostic,explanation,typeName,preflightGroups} from '../static/js/discovery_diagnostics.js';
import {broadMatches} from '../static/js/discovery_broad.js';
const tavily={id:'wallet.web_search.tavily',mode:'automated',cost_class:'LIMITED_FREE',chains:['bitcoin','monero'],executable:true,configured:true,access_mode:'api_key'};
const brave={...tavily,id:'wallet.broad_web'};
test('Tavily has independent type, free configuration help and safe diagnostics',()=>{
 assert.equal(typeName(tavily),'Automated remote');assert.equal(tavily.cost_class,'LIMITED_FREE');
 assert.match(availability(tavily,'bitcoin').text,/PRESENT/);
 assert.match(availability({...tavily,access_mode:'keyless'},'bitcoin').text,/keyless/);
 const missing=availability({...tavily,executable:false,missing_configuration:['TAVILY_API_KEY']},'bitcoin');
 assert.match(missing.text,/MISSING/);assert.match(missing.text,/without a payment card/);
 assert.match(explanation(tavily),/not proof of wallet ownership/);assert.match(explanation(tavily),/tracing remains unsupported/);
});
test('broad defaults prefer available Tavily without selecting a duplicate or unavailable Brave',()=>{
 assert.deepEqual(broadDefaults([tavily,brave],'bitcoin'),[tavily.id]);
 assert.deepEqual(broadDefaults([{...tavily,executable:false},brave],'bitcoin'),[brave.id]);
 assert.deepEqual(broadDefaults([{...tavily,executable:false},{...brave,executable:false}],'bitcoin'),[]);
 assert.equal(preflightGroups({selections:[{source_id:'tavily_search',eligibility:'eligible'},{source_id:'brave_search',eligibility:'configuration_unavailable'}]}).ready[0].source_id,'tavily_search');
});
test('failure explanations separate free allowance, auth, timeout and malformed response without echoing secrets',()=>{
 const messages=['missing_api_key','authentication_failed','quota_exhausted','keyless_allowance_exhausted','rate_limited','provider_timeout','provider_error','invalid_response'].map(diagnostic=>providerDiagnostic({source_id:'tavily_search',error:'SECRET',quota_snapshot:{diagnostic,raw:'SECRET'}}));
 assert.equal(new Set(messages).size,8);assert.ok(messages.every(m=>m&&!m.includes('SECRET')));
 assert.match(messages[2],/allowance exhausted/);assert.match(messages[3],/no payment card/);
});
test('Tavily provenance remains distinct in local broad result filtering',()=>{
 const group={observations:[{id:'o',provider:'tavily_search',source_snapshot:{exact_match:false}}]};
 assert.ok(broadMatches(group,{provider:'tavily_search'},[]));assert.equal(broadMatches(group,{provider:'brave_search'},[]),false);
});
