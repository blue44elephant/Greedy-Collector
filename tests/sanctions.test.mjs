import test from 'node:test';
import assert from 'node:assert/strict';
import {sanctionsHeadline} from '../static/js/sanctions.js';

test('unsynchronized and unresolved screening never claims clean',()=>{
  assert.match(sanctionsHeadline({listing_state:'REGISTRY_NOT_SYNCED'}),/not synchronized/i);
  assert.match(sanctionsHeadline({listing_state:'SCREENING_UNRESOLVED'}),/unavailable/i);
  assert.doesNotMatch(sanctionsHeadline({listing_state:'REGISTRY_STALE',match_type:'NO_MATCH'}),/No exact match/i);
});
test('direct current and historical OFAC matches are visibly different',()=>{
  const current=sanctionsHeadline({listing_state:'CURRENTLY_LISTED',match_type:'DIRECT_CHAIN_MATCH'});
  const historical=sanctionsHeadline({listing_state:'HISTORICALLY_LISTED',match_type:'DIRECT_CHAIN_MATCH'});
  assert.match(current,/CURRENT OFAC MATCH/);
  assert.match(historical,/HISTORICAL OFAC MATCH/);
  assert.notEqual(current,historical);
});
test('unresolved and other-chain text do not claim direct listing',()=>{
  for(const match_type of ['EXACT_TEXT_MATCH_CHAIN_UNRESOLVED','TEXT_MATCH_OTHER_CHAIN']){
    for(const listing_state of ['CURRENTLY_LISTED','HISTORICALLY_LISTED']){
      const text=sanctionsHeadline({listing_state,match_type});
      assert.doesNotMatch(text,/(CURRENT|HISTORICAL) OFAC MATCH/);
    }
  }
});
