import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {qualityData} from '../static/js/attribution_forms.js';
import {contradictionText, assessmentText} from '../static/js/attribution_summary.js';
import {ofacProvenanceFacts} from '../static/js/discovery_promotion.js';

test('source quality defaults to unassessed and requires an explicit rationale',()=>{
  assert.deepEqual(qualityData({}),{source_reliability:'unassessed',reliability_rationale:''});
  assert.throws(()=>qualityData({source_reliability:'reliable',reliability_rationale:' '}),/Explain/);
  assert.equal(qualityData({source_reliability:'reliable',reliability_rationale:'Primary source checked'}).reliability_rationale,'Primary source checked');
});

test('contradictions remain prominent for strong and rejected assessments',()=>{
  for(const assessment of ['possible','supported','strongly_supported','rejected']){
    const claim={assessment,needs_review:false,active_evidence_counts:{supports:3,contradicts:1,context:0}};
    assert.match(contradictionText(claim),/1 active contradiction/);
    assert.ok(assessmentText(claim));
  }
  assert.equal(contradictionText({active_evidence_counts:{contradicts:0}}),'');
});

test('OFAC provenance displays the original snapshot and association state',()=>{
  const facts=new Map(ofacProvenanceFacts({snapshot_id:'fixture-snapshot',snapshot_sha256:'a'.repeat(64),
    entity:{source_entity_id:'17',name:'Fixture record',programs:['CYBER2']},
    identifier:{raw_value:'literal fixture',source_field:'Digital Currency Address - ETH',chain:'ethereum'},
    match_type:'DIRECT_CHAIN_MATCH',listing_state:'HISTORICALLY_LISTED'}));
  assert.equal(facts.get('Source'),'OFAC SDN');assert.equal(facts.get('Snapshot SHA-256'),'a'.repeat(64));
  assert.equal(facts.get('Listing state at observation'),'HISTORICALLY_LISTED');
  assert.equal(facts.get('Raw identifier'),'literal fixture');
});

test('workspace exposes claimed entities, contradiction warning, and valid wallet navigation',()=>{
  const workspace=readFileSync(new URL('../static/js/attribution.js',import.meta.url),'utf8');
  const app=readFileSync(new URL('../static/js/app.js',import.meta.url),'utf8');
  assert.match(workspace,/Claimed entity/);assert.match(workspace,/attr-contradiction-warning/);
  assert.match(workspace,/Investigate wallet/);assert.doesNotMatch(workspace,/Owner:|Attributed entity/);
  assert.doesNotMatch(app,/investigateWallet/);assert.match(app,/initWallet, investigate/);
});
