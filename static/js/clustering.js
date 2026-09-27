import {api} from './api.js';
import {element, panel, action, details, makeForm, byId, run, UserError} from './ui.js';
let supported = [];
let navigate;
const disclaimer = 'Technical clustering indicates heuristic relationships, not confirmed common ownership.';
export async function clusterRequest(path, options) {
  try { return await api('/clustering' + path, options); }
  catch (error) {
    if (error.status === 503) throw new UserError('Clustering storage is unavailable or busy. An explicit migration may be required.');
    if (error.status === 422) throw new UserError('Clustering is unavailable for this input, the rationale is missing, or stored data exceeds the documented analysis bounds.');
    throw error;
  }
}
export async function initClustering(nav) {
  navigate = nav;
  const capabilities = await clusterRequest('/capabilities');
  supported = capabilities.automatic_chains;
  const host = byId('clustering-workspace');
  const controls = panel('Technical wallet clustering', disclaimer);
  controls.append(element('p', 'Explicit analysis of locally stored Bitcoin/Litecoin inputs. No providers are called. PayJoin and shared-control arrangements may escape structural checks.', 'bounded-note'));
  controls.append(makeForm([{name:'chain',label:'Chain',options:supported}], 'Analyze stored evidence', async data => showAnalysis(await clusterRequest('/analyze', {method:'POST',body:data}))));
  host.append(controls, element('div'));
  host.lastChild.id = 'cluster-results';
}
function evidenceCard(e, refresh) {
  const card = element('details');
  card.dataset.evidenceId = e.id;
  card.append(element('summary', `${e.excluded ? 'Excluded from clustering' : 'Direct common-input support'}: ${e.tx_hash}`));
  card.append(element('p', `Participating inputs: ${e.inputs.join(', ')}`, 'full-address'));
  card.append(element('p', `Exclusion checks: ${e.automatic_exclusions.join(', ') || 'No structural exclusion triggered; this does not rule out PayJoin.'}`));
  if (e.analyst_exclusion) card.append(element('p', `Analyst exclusion: ${e.analyst_exclusion.reason} (${e.analyst_exclusion.timestamp})`));
  for (const warning of e.counter_indicators) card.append(element('p', warning, 'bounded-note'));
  card.append(details('Evidence provenance and applied checks', e));
  if (refresh && !e.analyst_exclusion) card.append(makeForm([{name:'reason',label:'Exclusion rationale',required:true,maxLength:1000}], 'Exclude evidence', async data => {
    if (!data.reason.trim()) throw new UserError('Enter an exclusion rationale.');
    const result = await clusterRequest(`/evidence/${e.id}/exclude`, {method:'POST',body:data});
    document.dispatchEvent(new CustomEvent('clusters-changed'));
    refresh(result);
  }));
  return card;
}
// Progressive DOM disclosure preserves all returned material without huge layouts.
function paged(host, values, build, label, size=50) {
  let offset = 0;
  const more = action(`Show more ${label}`, () => append());
  function append() {
    more.remove();
    values.slice(offset, offset + size).forEach(value => host.append(build(value)));
    offset += size;
    if (offset < values.length) host.append(more);
  }
  append();
}
export function clusterCard(snapshot, historical=false) {
  const card = panel(`Technical cluster ${snapshot.id} / version ${snapshot.version}`, disclaimer);
  card.dataset.clusterId = snapshot.id; card.dataset.clusterVersion = snapshot.version;
  card.append(element('p', `${snapshot.chain} ? ${snapshot.heuristic} ? ${snapshot.status}`));
  card.append(element('p', `Created ${snapshot.created_at}; version captured ${snapshot.recomputed_at}`));
  card.append(element('p', snapshot.limitations, 'bounded-note'));
  card.append(element('p', 'Inputs listed together in an accepted evidence item have direct heuristic support. Other members are connected transitively; no direct transaction between them is asserted.'));
  const members = element('details'); members.append(element('summary', `Members (${snapshot.members.length})`));
  members.addEventListener('toggle', () => {
    if (members.open && !members.dataset.loaded) {
      members.dataset.loaded = 'true';
      paged(members, snapshot.members, address => {
        const row = element('p', address, 'full-address');
        row.append(action('Investigate wallet', async () => (await import('./wallet.js')).investigate(snapshot.chain,address)));
        return row;
      }, 'members');
    }
  });
  card.append(members);
  const evidence = element('details'); evidence.append(element('summary', `Supporting / excluded transactions (${snapshot.evidence.length})`));
  evidence.addEventListener('toggle', () => {
    if (evidence.open && !evidence.dataset.loaded) {
      evidence.dataset.loaded = 'true';
      paged(evidence, snapshot.evidence, e => evidenceCard(e, historical ? null : showAnalysis), 'evidence');
    }
  });
  card.append(evidence);
  if (!historical) {
    card.append(action('Pin this version to Case', async () => {
      const {listCases} = await import('./case_actions.js');
      const cases = await listCases();
      if (!cases.length) throw new UserError('Create a Case first.');
      const picker = makeForm([{name:'case_id',label:'Case',options:cases.map(c=>[c.id,c.title])}], 'Confirm version pin', async data => {
        await clusterRequest(`/cases/${data.case_id}/pin`, {method:'POST',body:{cluster_id:snapshot.id,version:snapshot.version}});
        picker.replaceChildren(element('p', `Pinned version ${snapshot.version}; later recomputation cannot change it.`));
      });
      card.append(picker);
    }));
    card.append(makeForm([{name:'version',label:'Historical version',type:'number',min:1,max:snapshot.version,required:true,value:snapshot.version}], 'Inspect historical version', async data => {
      const old = await clusterRequest(`/clusters/${snapshot.id}?version=${Number(data.version)}`);
      card.append(clusterCard(old,true));
    }));
  }
  return card;
}
function showAnalysis(data) {
  const host = byId('cluster-results'); host.replaceChildren();
  host.append(element('p', `${data.stored_rows_analyzed} stored rows analyzed. ${data.empty_message || ''}`));
  paged(host, data.clusters, c=>clusterCard(c), 'clusters',10);
  const excluded = data.evidence.filter(e=>e.excluded);
  const section = panel(`Excluded transactions (${excluded.length})`, 'Excluded evidence remains available even if no cluster is generated.');
  paged(section, excluded, e=>evidenceCard(e,showAnalysis), 'excluded evidence');
  host.append(section);
}
export function walletClustering(chain,address) {
  const host = element('div');
  if (!supported.includes(chain)) return host;
  host.append(action('Analyze technical cluster', async () => {
    const result = await clusterRequest('/analyze',{method:'POST',body:{chain}});
    navigate('clustering'); showAnalysis(result);
    document.dispatchEvent(new CustomEvent('clusters-changed'));
  }));
  const summary = element('p', 'Loading stored technical cluster summary...', 'muted small'); host.append(summary);
  clusterRequest(`/wallet/${chain}/${encodeURIComponent(address)}`).then(data => {
    summary.textContent = data.clusters.length ? data.clusters.map(c=>`${c.id} / version ${c.version} / ${c.members.length} members`).join('; ') : 'No stored technical cluster for this wallet.';
    if(data.clusters.length) host.append(action('Inspect technical cluster',()=>{navigate('clustering');byId('cluster-results').replaceChildren(...data.clusters.map(c=>clusterCard(c)));}));
  }).catch(()=>{summary.textContent='Technical clustering storage is unavailable. Explicit migration may be required.';});
  return host;
}
export function clusterOverlay({tools,svg,graph,chain,detail}) {
  if (!supported.includes(chain)) return;
  let enabled = false, epoch = 0;
  const control = action('Technical Cluster overlay: OFF', async () => {
    enabled = !enabled; control.textContent = `Technical Cluster overlay: ${enabled ? 'ON' : 'OFF'}`;
    control.setAttribute('aria-pressed', String(enabled));
    const token = ++epoch;
    svg.querySelectorAll('.cluster-badge').forEach(n=>n.remove());
    svg.querySelectorAll('.has-technical-cluster').forEach(n=>n.classList.remove('has-technical-cluster'));
    if (!enabled) return;
    const focus = graph.nodes.find(n=>n.is_focus);
    if(!focus) return;
    const data = await clusterRequest(`/wallet/${chain}/${encodeURIComponent(focus.id)}`);
    if(token !== epoch || !svg.isConnected) return;
    for(const snapshot of data.clusters) {
      const members = new Set(snapshot.members);
      for(const node of svg.querySelectorAll('.graph-node')) {
        if(!members.has(node.dataset.nodeId)) continue;
        node.classList.add('has-technical-cluster');
        const badge = document.createElementNS('http://www.w3.org/2000/svg','text');
        badge.setAttribute('class','cluster-badge'); badge.setAttribute('x','12'); badge.setAttribute('y','-8');
        badge.textContent = `Cluster ${snapshot.id.slice(0,8)} / v${snapshot.version}`;
        const title = document.createElementNS('http://www.w3.org/2000/svg','title');title.textContent=snapshot.id;badge.append(title);
        node.append(badge);
      }
      detail.replaceChildren(clusterCard(snapshot));
    }
    if (!data.clusters.length) detail.replaceChildren(element('p','No stored technical cluster for the focus wallet. Run analysis explicitly in Wallet or Technical clusters.'));
  });
  control.setAttribute('aria-pressed','false'); tools.append(control);
  const invalidate = () => {
    if(!svg.isConnected) {document.removeEventListener('clusters-changed',invalidate);return;}
    if(enabled) control.click();
  };
  document.addEventListener('clusters-changed',invalidate);
}
