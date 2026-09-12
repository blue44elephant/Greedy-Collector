import {element, fields, UserError} from './ui.js';
import {options, entityTypes, relationships, evidenceTypes, origins, stances} from './attribution_api.js';

export const reasonField = {name:'reason', label:'Reason for this change', type:'textarea', required:true, maxLength:8000};
export const descriptorFields = row => [
  {name:'canonical_name',label:'Canonical name',required:true,maxLength:255,value:row?.canonical_name},
  {name:'entity_type',label:'Entity type',options:options(entityTypes),value:row?.entity_type || 'unknown'},
  {name:'aliases',label:'Aliases (one per line, optional)',type:'textarea',value:row?.aliases?.join('\n') || ''},
  {name:'description',label:'Description (optional)',type:'textarea',maxLength:8000,value:row?.description || ''},
];
export const descriptor = data => ({canonical_name:data.canonical_name, entity_type:data.entity_type,
  description:data.description, aliases:data.aliases.split('\n').map(s=>s.trim()).filter(Boolean)});
export const scopeFields = row => [
  {name:'scope_note',label:'Scope and rationale',type:'textarea',required:true,maxLength:4000,value:row?.scope_note},
  {name:'valid_from',label:'Valid from (optional)',type:'date',value:row?.valid_from},
  {name:'valid_to',label:'Valid to (optional)',type:'date',value:row?.valid_to},
];
export const scopeData = data => ({scope_note:data.scope_note, valid_from:data.valid_from || null, valid_to:data.valid_to || null});
export const claimFields = () => [
  {name:'subject_type',label:'Subject type',options:[['wallet','Wallet address']]},
  {name:'chain',label:'Chain',options:[['bitcoin','Bitcoin'],['ethereum','Ethereum']]},
  {name:'subject_ref',label:'Public wallet address',required:true,maxLength:128},
  {name:'relationship',label:'Relationship',options:[['','Choose relationship'],...options(relationships)],required:true}, ...scopeFields(),
];
export const linkFields = row => [
  {name:'stance',label:'Evidence stance',options:[['','Choose stance'],...options(stances)],required:true,value:row?.stance || ''},
  {name:'directness',label:'Directness',options:[['','Choose directness'],...options(['direct','indirect','context'])],required:true,value:row?.directness || ''},
  {name:'rationale',label:'Link rationale',type:'textarea',required:true,maxLength:8000,value:row?.rationale},
];
export const linkData = data => ({stance:data.stance, directness:data.directness, rationale:data.rationale});

export function captureFields() {
  return [
    {name:'evidence_type',label:'Evidence type',options:options(evidenceTypes)},
    {name:'origin',label:'Origin',options:options(origins)},
    {name:'title',label:'Evidence title',required:true,maxLength:255},
    {name:'source_name',label:'Source name',required:true,maxLength:255},
    {name:'source_url',label:'Public source URL (optional)',type:'url',maxLength:2048},
    {name:'source_locator',label:'Citation locator (optional)',maxLength:512},
    {name:'summary',label:'Evidence summary',type:'textarea',required:true,maxLength:8000},
    {name:'excerpt',label:'Captured excerpt (optional)',type:'textarea',maxLength:8000},
    {name:'published_on',label:'Published on (optional)',type:'date'},
    {name:'observed_on',label:'Observed on (optional)',type:'date'},
    {name:'analyst_note',label:'Analyst note (required for an analyst observation)',type:'textarea',maxLength:8000},
    {name:'source_reliability',label:'Source reliability',options:options(['unassessed','reliable','uncertain','unreliable'])},
    {name:'reliability_rationale',label:'Reliability rationale (required when assessed)',type:'textarea',maxLength:8000},
  ];
}

export function advancedCapture(form) {
  const box = element('details');box.append(element('summary','Optional structured metadata and provenance'));
  box.append(fields([
    {name:'metadata_json',label:'Metadata JSON object (optional)',type:'textarea'},
    {name:'origin_group',label:'Common origin group (optional)',maxLength:128},
    {name:'source_catalog_id',label:'Source catalog ID (optional)',maxLength:128},
  ]));form.insertBefore(box,form.querySelector('button[type=submit]'));
}

export function captureData(data) {
  let metadata = {};
  try {if(data.metadata_json?.trim()) metadata = JSON.parse(data.metadata_json);}
  catch {throw new UserError('Optional metadata must be a JSON object.');}
  if (!metadata || Array.isArray(metadata) || typeof metadata !== 'object') throw new UserError('Optional metadata must be a JSON object.');
  const evidence = {};
  for (const key of ['evidence_type','origin','title','source_name','summary','analyst_note','source_reliability','reliability_rationale']) evidence[key]=data[key];
  for (const key of ['source_url','source_locator','excerpt','published_on','observed_on','origin_group','source_catalog_id']) evidence[key]=data[key] || null;
  evidence.metadata_json=metadata;return evidence;
}
