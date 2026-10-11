import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {riskPresentation} from '../static/js/risk_presentation.js';
import {sanctionsHeadline} from '../static/js/sanctions.js';

const assessed={model_version:'deterministic-v3',overall_score:95,overall_tier:'CRITICAL',
  behavioral_exposure_score:0,authoritative_status:[{source:'OFAC SDN',listing_state:'CURRENTLY_LISTED',match_type:'DIRECT_CHAIN_MATCH'}],
  overrides:[{reason:'Overall score elevated by current direct authoritative sanctions match.'}],
  data_coverage:{status:'PARTIAL'},limitations:['Collection coverage is PARTIAL.']};

test('current OFAC override and behavioral/exposure score remain separate',()=>{
  const view=riskPresentation(assessed);
  assert.equal(view.overall,95);assert.equal(view.tier,'CRITICAL');assert.equal(view.behavioralExposure,0);
  assert.match(view.overrides[0],/authoritative sanctions match/);
  assert.match(view.statuses[0],/CURRENTLY_LISTED/);
  assert.equal(view.coverage,'PARTIAL');assert.match(view.limitations[0],/PARTIAL/);
  assert.equal(view.model,'deterministic-v3');
  assert.doesNotMatch(JSON.stringify(view),/95%|probability of criminal/);
});

test('historical, unsynced and manual Label results never become current OFAC',()=>{
  const historical=riskPresentation({...assessed,overall_score:0,overall_tier:'LOW',overrides:[],
    authoritative_status:[{source:'OFAC SDN',listing_state:'HISTORICALLY_LISTED',match_type:'DIRECT_CHAIN_MATCH'}]});
  assert.equal(historical.overrides.length,0);
  assert.match(historical.statuses[0],/HISTORICALLY_LISTED/);
  assert.match(sanctionsHeadline({listing_state:'HISTORICALLY_LISTED',match_type:'DIRECT_CHAIN_MATCH'}),/HISTORICAL OFAC MATCH/);
  const unsynced=riskPresentation({...assessed,overall_score:0,overall_tier:'LOW',overrides:[],
    authoritative_status:[{source:'OFAC SDN',listing_state:'REGISTRY_NOT_SYNCED',match_type:'UNAVAILABLE'}]});
  assert.match(unsynced.statuses[0],/REGISTRY_NOT_SYNCED/);
  const manual=riskPresentation({...assessed,overall_score:35,overall_tier:'MODERATE',behavioral_exposure_score:35,
    overrides:[],authoritative_status:[]});
  assert.equal(manual.overall,35);assert.equal(manual.overrides.length,0);
});

test('wallet markup exposes both scores and explanation panel uses safe DOM',()=>{
  const markup=readFileSync(new URL('../static/index.html',import.meta.url),'utf8');
  const script=readFileSync(new URL('../static/js/wallet.js',import.meta.url),'utf8');
  assert.match(markup,/id="risk-behavioral"/);
  assert.match(script,/Why this score/);
  assert.match(script,/Collection coverage/);
  assert.match(script,/risk\/observation/);
  assert.doesNotMatch(script,/innerHTML/);
});
