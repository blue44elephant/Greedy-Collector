import test from 'node:test';
import assert from 'node:assert/strict';
import {caseCounts,referenceMode,caseListQuery} from '../static/js/case_presenter.js';
test('empty Case counts are zero',()=>assert.ok(caseCounts({}).every(([,count])=>count===0)));
test('wallet identity remains chain scoped in counts',()=>assert.equal(new Map(caseCounts({entities:[{entity_type:'wallet',metadata_json:{chain:'ethereum'}},{entity_type:'wallet',metadata_json:{chain:'base'}}]})).get('Wallets'),2));
test('all major pin types are counted separately',()=>{
  const kinds=['transaction','risk_assessment','label','discovery_run','broad_discovery','discovery_observation','public_source_capture','attribution_claim','technical_cluster','fund_flow','attachment'];
  const counts=new Map(caseCounts({entities:kinds.map(entity_type=>({entity_type})),notes:[{},{archived_at:'time'}],reports:[{}],sanctions_pins:[{}]}));
  assert.equal(counts.get('Discovery runs / results'),3);assert.equal(counts.get('Captures'),1);assert.equal(counts.get('Notes'),1);assert.equal(counts.get('Reports'),1);
});
test('wallet with historical risk is distinguished from live reference',()=>assert.match(referenceMode({entity_type:'wallet',metadata_json:{risk_assessment:{}}}),/LIVE REFERENCE \+ PINNED HISTORICAL RISK/));
test('pin has explicit historical label',()=>assert.equal(referenceMode({metadata_json:{cluster_pin:{}}}),'PINNED HISTORICAL SNAPSHOT'));
test('plain transaction reference remains live',()=>assert.equal(referenceMode({metadata_json:{chain:'ethereum'}}),'LIVE REFERENCE'));
test('search filters encode literal input and archive state',()=>{
  const q=new URLSearchParams(caseListQuery({q:' a%&b ',status:'Paused',include_archived:'on',sort:'title'}));
  assert.equal(q.get('q'),'a%&b');assert.equal(q.get('include_archived'),'true');assert.equal(q.get('sort'),'title');
});
test('presentation never calls providers or mutates snapshot',()=>{
  const saved=globalThis.fetch;globalThis.fetch=()=>{throw Error('Network forbidden')};
  try {const row={entities:[{entity_type:'wallet',metadata_json:{risk_assessment:{overall_score:95}}}]},before=JSON.stringify(row);caseCounts(row);referenceMode(row.entities[0]);caseListQuery({});assert.equal(JSON.stringify(row),before);}
  finally {globalThis.fetch=saved;}
});
