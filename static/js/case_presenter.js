// Presentation only: counts and historical/live labels make no analytical claims.
export function caseCounts(row) {
  const kinds=kind=>(row.entities||[]).filter(e=>kind.includes(e.entity_type)).length;
  return [
    ['Wallets',kinds(['wallet'])],['Transactions / graphs',kinds(['transaction','graph_snapshot'])],
    ['Risk pins',kinds(['risk_assessment'])+(row.entities||[]).filter(e=>e.entity_type==='wallet'&&e.metadata_json?.risk_assessment).length],
    ['Labels',kinds(['label'])],['Discovery runs / results',kinds(['discovery_run','broad_discovery','discovery_observation'])],
    ['Captures',kinds(['public_source_capture'])],['Attribution',kinds(['attribution_claim','entity'])],
    ['Sanctions',row.sanctions_pins?.length||0],['Clusters',kinds(['technical_cluster'])],['Fund Flow',kinds(['fund_flow'])],
    ['Notes',(row.notes||[]).filter(n=>!n.archived_at).length],['Attachments',kinds(['attachment'])],['Reports',row.reports?.length||0]
  ];
}
export function referenceMode(row) {
  const historical=Object.keys(row.metadata_json||{}).some(k=>k.endsWith('_pin')||k.endsWith('_snapshot')||k==='risk_assessment');
  return historical?(row.entity_type==='wallet'?'LIVE REFERENCE + PINNED HISTORICAL RISK':'PINNED HISTORICAL SNAPSHOT'):'LIVE REFERENCE';
}
export function caseListQuery(filters={}) {
  const params=new URLSearchParams({sort:filters.sort||'updated'});
  if(filters.q?.trim())params.set('q',filters.q.trim());
  if(filters.status)params.set('status',filters.status);
  if(filters.include_archived)params.set('include_archived','true');
  return '?'+params;
}
