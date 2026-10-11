import {api} from './api.js';
import {byId,element,panel,table,shortValue,dateText,run,UserError,action,fields} from './ui.js';
import {listCases,openCase} from './case_actions.js';

const enc = value => encodeURIComponent(value);
const listed = state => state === 'CURRENTLY_LISTED' || state === 'HISTORICALLY_LISTED';
const programs = associations => [...new Set(associations.flatMap(item => item.entity?.programs || []))];

export function sanctionsHeadline(result) {
  const state = result?.listing_state || 'SCREENING_UNRESOLVED';
  let heading;
  if (state === 'REGISTRY_NOT_SYNCED') heading = 'Sanctions screening unavailable — OFAC registry not synchronized.';
  else if (state === 'SCREENING_UNRESOLVED') heading = 'Sanctions screening unavailable.';
  else if (state === 'REGISTRY_STALE') heading = 'OFAC registry stale — no current match conclusion.';
  else if (state === 'CURRENTLY_LISTED' && result.match_type === 'DIRECT_CHAIN_MATCH') heading = 'CURRENT OFAC MATCH in locally synchronized snapshot';
  else if (state === 'HISTORICALLY_LISTED' && result.match_type === 'DIRECT_CHAIN_MATCH') heading = 'HISTORICAL OFAC MATCH in earlier local snapshot';
  else if (result.match_type === 'EXACT_TEXT_MATCH_CHAIN_UNRESOLVED') heading = `${state === 'HISTORICALLY_LISTED' ? 'Historical exact text' : 'Exact text'} in OFAC snapshot; network unresolved`;
  else if (result.match_type === 'TEXT_MATCH_OTHER_CHAIN') heading = `${state === 'HISTORICALLY_LISTED' ? 'Historical same text' : 'Same text'} appears in OFAC data for another network`;
  else heading = 'No exact match in the available OFAC snapshot.';
  return heading;
}

export function walletSanctions(result, chain, address) {
  const box = panel('Sanctions screening', 'Exact local screening against a synchronized OFAC SDN snapshot. Separate from behavioral risk.');
  box.id = 'wallet-sanctions';
  const state = result?.listing_state || 'SCREENING_UNRESOLVED';
  const rows = result?.associations || [];
  const heading = sanctionsHeadline(result);
  const status = element('p', heading, 'sanctions-state');
  status.dataset.listingState = state;
  status.dataset.matchType = result?.match_type || 'UNAVAILABLE';
  box.append(status);
  if (result?.stale) box.append(element('p','Registry is stale. Review the snapshot retrieval time before relying on this result.','bounded-note'));
  if (result?.snapshot) box.append(element('p',`Source: OFAC SDN · Retrieved: ${dateText(result.snapshot.retrieved_at)} · Snapshot: ${result.snapshot.id} · SHA-256: ${result.snapshot.sha256}`,'muted small'));
  if (state === 'HISTORICALLY_LISTED') box.append(element('p',`Last observed listed: ${dateText(result.last_seen_at)}. Absence first observed: ${dateText(result.observed_removed_at)}. This is not an official delisting date.`,'bounded-note'));
  if (rows.length) {
    box.append(element('p',`OFAC associates this identifier with ${rows.length} source record${rows.length === 1 ? '' : 's'}; no ownership inference. Programs: ${programs(rows).join(', ') || 'not supplied'}.`));
    box.append(table(['OFAC entity','Programs','Source asset','Chain mapping','Source identifier'],rows.map(item => [
      item.entity.name, (item.entity.programs || []).join(', '), item.identifier.source_asset,
      item.identifier.mapping_status + (item.identifier.chain ? ` (${item.identifier.chain})` : ''),shortValue(item.identifier.raw_value)
    ])));
    const controls = element('div',undefined,'toolbar');
    controls.append(action('View sanctions record',()=>{document.dispatchEvent(new CustomEvent('open-sanctions',{detail:{entity_id:rows[0].entity.source_entity_id,snapshot_id:rows[0].snapshot_id}}));}));
    controls.append(action('Add to Case',()=>openPinPicker(chain,address)));
    controls.append(action('Open Discovery',()=>document.dispatchEvent(new CustomEvent('open-discovery',{detail:{chain,address}}))));
    box.append(controls);
  }
  return box;
}

async function openPinPicker(chain,address) {
  if (byId('sanctions-pin-dialog')) return;
  const dialog=element('dialog');dialog.id='sanctions-pin-dialog';
  dialog.append(element('h2','Pin sanctions screening to Case'));
  const form=element('form',undefined,'editor');dialog.append(form);document.body.append(dialog);
  dialog.addEventListener('close',()=>dialog.remove());dialog.showModal();
  await run(dialog,async()=>{
    const cases=await listCases();
    if (!cases.length) {form.append(element('p','Create a Case first, then return to pin this result.'));return;}
    form.append(fields([{name:'case_id',label:'Case',options:[['','Choose a Case'],...cases.map(row=>[row.id,row.title])],required:true}]));
    const save=element('button','Pin current screening');save.type='submit';form.append(save);
    form.addEventListener('submit',event=>{event.preventDefault();run(dialog,async()=>{
      const id=form.elements.case_id.value;if(!id)throw new UserError('Choose a Case.');
      await api(`/sanctions/cases/${enc(id)}/pins/${enc(chain)}/${enc(address)}`,{method:'POST'});
      form.replaceChildren(element('p','Screening result pinned with its source snapshot.'),action('Open Case',()=>{dialog.close();openCase(id);}));
    },'Pinning screening snapshot…');});
  },'Loading cases…');
}

export function initSanctions() {
  const host=byId('sanctions-workspace');
  let pendingEntity=null;
  const head=element('div',undefined,'workspace-heading');head.append(element('h1','Sanctions'),element('span','OFAC SDN · local authoritative snapshot','muted'));
  const overview=panel('Registry status','Refresh explicitly. Wallet screening uses stored data and makes no OFAC request.');
  const status=element('div');status.id='sanctions-status';
  const refresh=element('button','Refresh OFAC data');refresh.id='sanctions-refresh';refresh.type='button';
  overview.append(status,refresh);
  const searchPanel=panel('Search identifiers and entities','Exact address or OFAC ID; entity names and aliases can also be searched.');
  const form=element('form',undefined,'editor');form.id='sanctions-search';
  form.append(fields([
    {name:'q',label:'Address, entity, alias or OFAC ID'},
    {name:'program',label:'Program'},
    {name:'asset',label:'Source asset'},
    {name:'chain',label:'Mapped chain'},
    {name:'state',label:'Listing in local snapshots',options:[['current','Current snapshot'],['historical','Historical (absent from current)']]}
  ]));
  const submit=element('button','Search');submit.type='submit';form.append(submit);
  const results=element('div');results.id='sanctions-results';searchPanel.append(form,results);
  const detail=panel('OFAC entity');detail.id='sanctions-entity';detail.hidden=true;
  host.append(head,overview,searchPanel,detail);
  const perform=operation=>run(host,operation,'Loading sanctions registry…');
  function renderStatus(data) {
    status.replaceChildren();
    if (!data.snapshot) {status.append(element('p','OFAC registry not synchronized. Screening is unavailable.','empty'));return;}
    const snap=data.snapshot;
    status.append(element('p',data.stale ? 'Registry stale — review retrieval date' : 'Current local OFAC snapshot available','sanctions-state'));
    status.append(element('p',`Retrieved: ${dateText(snap.retrieved_at)} · Published: ${snap.published_at || 'not supplied'} · Snapshot: ${snap.id}`));
    status.append(element('p',`Source: OFAC SDN · Parser: ${snap.parser_version} · SHA-256: ${snap.sha256} · Official checksum: ${snap.integrity_status}`,'muted small'));
    status.append(element('p',`Entities: ${snap.entity_count} · Digital-currency identifiers: ${snap.identifier_count} · Unresolved chain: ${data.unresolved_count}`));
    status.append(element('p',`Changes from previous complete snapshot: ${JSON.stringify(snap.change_counts)}`,'muted small'));
    if (data.last_sync?.status === 'failed') status.append(element('p',`Last refresh failed: ${data.last_sync.reason}. The previous complete snapshot remains current.`,'bounded-note'));
    status.append(table(['Source asset','Identifiers'],Object.entries(data.by_asset || {}).map(([key,value])=>[key,value])));
    status.append(table(['Mapped chain','Identifiers'],Object.entries(data.by_chain || {}).map(([key,value])=>[key,value])));
  }
  async function load(){renderStatus(await api('/sanctions/summary'));}
  async function search(){
    const params=new URLSearchParams(new FormData(form));
    const data=await api('/sanctions/search?'+params);
    results.replaceChildren(element('p',`${data.total} associations found in available local snapshots.`, 'muted small'));
    results.append(table(['Entity','Programs','Asset','Address','Mapping','Actions'],data.items.map(item=>{
      const actions=element('div',undefined,'toolbar');
      actions.append(action('View entity',()=>openEntity(item.entity.source_entity_id,item.snapshot.id)));
      if(item.identifier.chain && item.identifier.canonical_address)actions.append(action('Open in Wallet',()=>document.dispatchEvent(new CustomEvent('investigate-wallet',{detail:{chain:item.identifier.chain,address:item.identifier.canonical_address}}))));
      return [item.entity.name,(item.entity.programs || []).join(', '),item.identifier.source_asset,shortValue(item.identifier.raw_value),
        item.identifier.mapping_status + (item.identifier.chain ? ` (${item.identifier.chain})` : ''),actions];
    }), 'No matching identifiers in the selected local snapshot state.'));
  }
  async function openEntity(id,snapshotId){
    const data=await api('/sanctions/entities/'+enc(id)+(snapshotId ? '?snapshot_id='+enc(snapshotId) : ''));
    detail.hidden=false;detail.replaceChildren(element('h2',data.entity.name),
      element('p',`OFAC ID: ${data.entity.source_entity_id} · Programs: ${data.entity.programs.join(', ')}`),
      element('p',`Aliases: ${data.entity.aliases.map(a=>a.name).join(', ') || 'none supplied'}`),
      element('p',`Snapshot: ${data.snapshot.id} · Retrieved: ${dateText(data.snapshot.retrieved_at)}`,'muted small'));
    detail.append(table(['Asset','Identifier','Mapping','Actions'],data.identifiers.map(item=>[
      item.source_asset,shortValue(item.raw_value),item.mapping_status,
      item.chain && item.canonical_address ? action('Open in Wallet',()=>document.dispatchEvent(new CustomEvent('investigate-wallet',{detail:{chain:item.chain,address:item.canonical_address}}))) : element('span','Tracing unavailable')
    ])));
    detail.scrollIntoView({block:'start'});
  }
  refresh.addEventListener('click',()=>perform(async()=>{
    refresh.disabled=true;
    try {
      try { await api('/sanctions/sync',{method:'POST'}); }
      catch (error) { await load(); throw error; }
      await load();
      await search();
    } finally { refresh.disabled=false; }
  }));
  form.addEventListener('submit',event=>{event.preventDefault();perform(search);});
  document.addEventListener('open-sanctions',event=>{pendingEntity=event.detail || null;document.querySelector('[data-workspace="sanctions"]').click();});
  return {load:()=>perform(async()=>{await load();if(pendingEntity){const entity=pendingEntity;pendingEntity=null;await openEntity(entity.entity_id,entity.snapshot_id);}}),openEntity};
}
