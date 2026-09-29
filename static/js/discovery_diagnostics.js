// Display semantics only; eligibility, accounting and coverage come from the API.
export const typeName=t=>t.capture_only?'Manual capture':({automated:'Automated remote',local:'Local',manual:'Manual pivot'}[t.mode] || 'Unknown');
const help={
  'wallet.web_search.tavily':'Tavily performs an automated public web search for the exact wallet address using Basic Search. Returned search metadata is Discovery material, not proof of wallet ownership. No destination page is fetched. Monero public web mentions are allowed; blockchain tracing remains unsupported.',
  'wallet.broad_web':'Queries Brave official web search for a quoted wallet string. Only returned title/URL/snippet metadata is stored; pages are never fetched and fuzzy results are not wallet evidence.',
  'wallet.local_labels':'Reads current stored GC labels for the exact wallet. Labels are local annotations, not independently verified ownership.',
  'wallet.manual_exact_web':'Manual pivot. GC generates an exact-address search link. GC does not search the web itself; opening the link is an analyst action.',
  'wallet.manual_source_observation':'Manual capture. You provide material already observed elsewhere. GC does not fetch or independently verify the source.',
  'wallet.public_code_mentions':'Queries the GitHub API for exact public wallet code mentions within bounded results. A mention does not establish repository-owner control of the wallet.',
  'wallet.graphsense_public_tags':'Queries public GraphSense TagPacks through GitHub for exact address annotations. A result is third-party public attribution metadata, not GC verification of ownership; coverage is bounded.',
  'wallet.ens_primary_name':'Queries Ethereum RPC / Universal Resolver for a forward-verified ENS primary name. Ethereum only; a technical name relationship is not legal identity or proof of wallet control.',
};
export const explanation=t=>help[t.id] || t.description;
export const networkBehavior=t=>t.capture_only?'No network: analyst-supplied material':t.mode==='local'?'No network: local database':t.mode==='manual'?'No network: link generation only':'Remote requests only on explicit execution; compatible cached results may avoid a request';
export function availability(t,chain){
  if(chain&&!t.chains.includes(chain))return {executable:false,code:'unsupported_chain',text:`Not applicable to ${chain}. Supported chains: ${t.chains.join(', ')}${t.chains.length===1&&t.chains[0]==='ethereum'?' (Ethereum only)':''}.`};
  if(t.id==='wallet.web_search.tavily'&&t.executable)return {executable:true,code:'eligible',text:t.access_mode==='keyless'?'Free provider ready: rate-limited keyless Search. A free Tavily account/key is optional for a larger allowance.':'Free provider ready: TAVILY_API_KEY PRESENT. Basic Search uses the configured account allowance.'};
  if(t.id==='wallet.web_search.tavily'&&t.missing_configuration?.length)return {executable:false,code:'configuration_unavailable',text:'TAVILY_API_KEY MISSING and keyless access disabled. Free account/API key required: create a free Tavily key without a payment card, configure it server-side and restart GC.'};
  if(t.executable)return {executable:true,code:'eligible',text:t.capture_only?'Available through preview and explicit capture.':'Executable with the current default budget.'};
  if(t.id==='wallet.broad_web'&&t.unavailable_reason==='retention_not_permitted')return {executable:false,code:'retention_not_permitted',text:'Storage entitlement required. After obtaining provider storage rights, set BRAVE_SEARCH_STORAGE_ALLOWED=true server-side and restart GC.'};
  if(t.missing_configuration?.length)return {executable:false,code:'configuration_unavailable',text:`Configuration required: ${t.missing_configuration.join(', ')} is not configured. Set ${t.missing_configuration.join(', ')} in GC environment/.env and restart.`};
  if(t.dependency_unavailable)return {executable:false,code:'dependency_unavailable',text:t.id==='wallet.ens_primary_name'?'ENS local normalizer unavailable. Install the documented Node 24+ and locked normalization dependency, then restart GC.':'A required local dependency is unavailable.'};
  const reasons={configuration_unavailable:'Configuration unavailable.',not_implemented:'Not implemented.',disabled:'Execution disabled.',budget_exhausted:'Budget authorization required.',retention_not_permitted:'Source retention is not permitted.'};
  return {executable:false,code:t.unavailable_reason,text:reasons[t.unavailable_reason]||'Source is not currently executable.'};
}
export function preflightGroups(plan){return {ready:plan.selections.filter(p=>p.eligibility==='eligible'),unavailable:plan.selections.filter(p=>p.eligibility!=='eligible')};}
export function runSummary(run){
  const rows=run.sources||[],count=predicate=>new Set(rows.filter(predicate).map(s=>s.transform_id)).size;
  return {requested:count(()=>true),executed:count(s=>s.status==='succeeded'||s.status==='running'||s.requests_attempted>0),
    unavailable:count(s=>s.status==='unavailable'||['configuration_unavailable','retention_not_permitted','entitlement_unavailable','unsupported_input','budget_exhausted'].includes(s.error_code)),
    partial:count(s=>['provider_incomplete','limit_reached'].includes(s.coverage)||['failed','timeout','rate_limited','interrupted','cancelled'].includes(s.status)),
    cached:count(s=>s.status==='cache_hit'),manual:count(s=>s.status==='manual_ready'),results:run.returned_count||0,refresh:run.refresh===true};
}
export function zeroResult(source){
  if(!['succeeded','cache_hit'].includes(source.status)||source.returned_count!==0)return null;
  return {'wallet.web_search.tavily':'No exact or candidate public-web result was returned within the bounded Tavily search.','wallet.broad_web':'No exact or candidate public-web result was returned within the bounded search.','wallet.graphsense_public_tags':'No matching GraphSense public annotation was returned within the bounded search.',
    'wallet.public_code_mentions':'No exact public code mention was returned within this bounded search.',
    'wallet.ens_primary_name':'No verified ENS primary name returned.',
    'wallet.local_labels':'No matching stored local labels were returned for this wallet.'}[source.transform_id] || 'No results returned within this source execution.';
}

// Defaults run one available web search, never a hidden fallback or duplicate.
export function broadDefaults(transforms,chain){
  const compatible=transforms.filter(t=>t.mode!=='manual'&&t.chains.includes(chain));
  const web=['wallet.web_search.tavily','wallet.broad_web'];
  const preferred=web.find(id=>compatible.some(t=>t.id===id&&t.executable));
  return compatible.filter(t=>!web.includes(t.id)||t.id===preferred).map(t=>t.id);
}
export function providerDiagnostic(source){
  if(source.source_id!=='tavily_search')return null;
  return {
    missing_api_key:'Tavily API key missing and keyless access disabled. Create a free Tavily account/key without a payment card.',
    authentication_failed:'Tavily authentication failed. Check the server-side key; no fallback request was made.',
    quota_exhausted:'Tavily account allowance exhausted. Free plans stop at their allowance; no upgrade or paid fallback was attempted.',
    keyless_allowance_exhausted:'Tavily keyless allowance exhausted. Wait before trying again or configure a free Tavily API key (no payment card).',
    rate_limited:'Tavily rate limited this search. Try again later; no automatic retry.',
    provider_timeout:'Tavily search timed out. Other provider results remain available.',
    provider_error:'Tavily provider request failed. Other provider results remain available.',
    invalid_response:'Tavily returned an invalid search response. No unverified payload was stored.',
  }[source.quota_snapshot?.diagnostic] || null;
}
