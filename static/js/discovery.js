import {graphSenseDetail} from './discovery_graphsense.js';
import {manualSourceForm,manualSourceDetail,sourceReference} from './discovery_manual_source.js';
import {promotionDetail} from './discovery_promotion.js';
import {initDiscoveryGraph} from './discovery_graph.js';
import {api} from './api.js';
import {walletContext,returnFromDiscovery} from './discovery_handoff.js';
import {byId, element, panel, table, fields, details, dateText, UserError} from './ui.js';
import {discoveryRequest as request, activeRun, createRunPoller} from './discovery_api.js';

const costNames = {FREE_LOCAL:'Free local', FREE_REMOTE:'Free remote', LIMITED_FREE:'Limited free', PAID:'Paid'};
const reasons = {eligible:'Eligible', not_implemented:'Not implemented', configuration_unavailable:'Not configured', retention_not_permitted:'Storage permission unavailable', disabled:'Disabled', budget_exhausted:'Budget unavailable', rate_limited:'Rate limited', timeout:'Timed out', transport_failed:'Provider error', invalid_provider_response:'Invalid provider response', entitlement_unavailable:'Source entitlement unavailable', unsupported_input:'Unsupported subject', cancelled:'Cancelled', interrupted:'Interrupted', storage_unavailable:'Storage unavailable'};
const label = value => String(value || 'Not available').replaceAll('_', ' ').replace(/^./, c => c.toUpperCase());
const reason = value => reasons[value] || 'Source unavailable';
const sourceReason = source => source.quota_snapshot?.eligibility === 'not_implemented' ? reason('not_implemented') : reason(source.error_code);
const encode = encodeURIComponent;
function reference(value) {
  if (!value) return element('span', 'No source reference returned');
  if (/^https?:/i.test(value)) return sourceReference(value);
  // Text remains copyable. Opening a source is always an explicit user action.
  try {
    const url = new URL(value);
    if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password || [...url.searchParams.keys()].some(k => /key|token|secret|password|signature|authorization/i.test(k))) return element('span', 'Unsafe source link withheld');
    const a = element('a', value); a.href = url.href; a.target = '_blank'; a.rel = 'noopener noreferrer'; a.referrerPolicy = 'no-referrer'; return a;
  } catch { return element('span', value); }
}
function reviewText(row) {
  if (row.new_material_since_review && row.reviewed_material_revision > 0) return `Review needed — previous decision: ${label(row.review_status)}`;
  return label(row.review_status);
}

export function initDiscovery() {
  const host = byId('discovery-workspace');
  let visible = false, loaded = false, busy = false, transforms = [], sources = [], subject = null;
  let plan = null, intent = null, runKey = null, current = null, result = null, observation = null;
  let resultsOffset = 0, historyOffset = 0, observationsOffset = 0, reviewsOffset = 0;
  const choices = [];
  let entry = null, pendingHandoff = null;
  const entryPanel = element('section',undefined,'panel'); entryPanel.id = 'discovery-entry'; entryPanel.hidden = true;
  const capturePanel=element('div');
  function openCapture(){
    if(!subject)throw new UserError('Check a supported wallet subject first.');
    capturePanel.replaceChildren(manualSourceForm(subject,async saved=>{
      await perform(async()=>{await selectRun(saved.run_id);await openResult(saved.result_id,saved.observation_id);await loadHistory(0);});
    }));capturePanel.scrollIntoView({block:'start'});
  }
  const top = element('div', undefined, 'workspace-heading');
  top.append(element('h1', 'Discovery'), element('span', 'Public-source pivots & candidate evidence', 'muted'));
  const message = element('p', '', 'operation-status'); message.setAttribute('role', 'status'); message.id = 'discovery-message';
  const query = panel('New discovery', 'Use a public Bitcoin or Ethereum address. Never enter a private key or recovery phrase.');
  const form = element('form', undefined, 'editor'); form.id = 'discovery-subject';
  form.append(fields([{name:'address', label:'Public wallet address', required:true, maxLength:128}]));
  form.elements.address.autocomplete = 'off'; form.elements.address.spellcheck = false;
  const identify = element('button', 'Check subject'); identify.type = 'submit'; form.append(identify);
  const detected = element('p', 'Enter a wallet to check its supported format locally.', 'muted'); detected.id = 'discovery-detected';
  query.append(form, detected);
  const pivots = panel('Available pivots'); pivots.id = 'discovery-transforms';
  const sourcePanel = panel('Source capabilities', 'Configured means credential availability, not implementation or provider reachability.'); sourcePanel.id = 'discovery-sources';
  const planning = panel('Plan', 'Planning validates the subject, eligibility and budget locally. It does not query providers or produce results.'); planning.id = 'discovery-plan';
  const options = element('div', undefined, 'editor');
  options.append(fields([{name:'refresh', label:'Refresh sources', type:'checkbox'}]));
  options.append(element('p', 'Bypasses reusable Discovery cache and runs eligible pivots again.', 'muted small'));
  const planned = element('div'); planned.id = 'discovery-plan-detail';
  const currentPanel = panel('Current run'); currentPanel.id = 'discovery-run';
  const results = panel('Results', 'Candidate public evidence does not establish wallet control. Relationships retain their literal source meaning.'); results.id = 'discovery-results';
  const detail = panel('Result detail'); detail.id = 'discovery-detail'; detail.hidden = true;
  const history = panel('Run history', 'Opening history reads stored records only. Archiving retires a run from normal history; observations and results are preserved.'); history.id = 'discovery-history';
  const filters = element('form', undefined, 'editor');
  filters.append(fields([{name:'status', label:'Status', options:[['','All statuses'], ...['queued','running','completed','partial','failed','cancelled','interrupted'].map(v => [v,label(v)])]}, {name:'subject_id',label:'Subject ID (optional)'}, {name:'include_archived',label:'Include archived',type:'checkbox'}]));
  const filterButton = element('button', 'Load history'); filterButton.type = 'submit'; filters.append(filterButton);
  const historyRows = element('div'); historyRows.id = 'discovery-history-rows'; history.append(filters, historyRows);
  const graphPanel=element('section',undefined,'panel discovery-graph');graphPanel.id='discovery-graph-panel';graphPanel.hidden=true;
  const graph=initDiscoveryGraph(graphPanel,{openResult:async(id,observationId)=>{await perform(()=>openResult(id,observationId));detail.scrollIntoView({block:'start'});}});
  const views=element('div',undefined,'toolbar');views.setAttribute('aria-label','Discovery result views');
  const resultView=button('Results',()=>setResultView(false)),graphView=button('Graph',()=>setResultView(true));
  views.append(resultView,graphView);
  async function setResultView(showGraph){results.hidden=showGraph;resultView.setAttribute('aria-pressed',String(!showGraph));graphView.setAttribute('aria-pressed',String(showGraph));await graph.show(showGraph);}
  resultView.setAttribute('aria-pressed','true');graphView.setAttribute('aria-pressed','false');
  host.append(top, message, entryPanel, query, capturePanel, pivots, sourcePanel, planning, currentPanel, views, results, graphPanel, detail, history);

  function showError(e) { message.textContent = e instanceof UserError ? e.message : 'The Discovery operation could not be completed. Try again.'; message.className = 'operation-status error'; message.setAttribute('role','alert'); }
  async function perform(fn) {
    if (busy) return;
    busy = true; host.dataset.busy = 'true'; host.setAttribute('aria-busy','true'); message.textContent = 'Working…'; message.className = 'operation-status'; message.setAttribute('role','status'); poller.stop(); syncButtons();
    try { await fn(); message.textContent = ''; } catch (e) { showError(e); }
    finally { busy = false; host.dataset.busy = 'false'; host.setAttribute('aria-busy','false'); syncButtons(); if (pendingHandoff) queueMicrotask(() => openWallet(pendingHandoff, false)); else resume(); }
  }
  function button(text, fn) { const b = element('button', text, 'secondary'); b.type = 'button'; b.addEventListener('click', () => perform(fn)); return b; }
  const planButton = button('Plan selected pivots', () => makePlan()); planButton.id = 'discovery-plan-button';
  const runButton = button('Run discovery', startRun); runButton.id = 'discovery-run-button';
  planning.append(options, planButton, planned, runButton);
  top.append(button('Refresh capabilities', async () => { invalidate(); await capabilities(); }));
  currentPanel.append(element('p', 'No run selected.', 'empty'));
  results.append(element('p', 'Select a stored run to inspect its candidate results.', 'empty'));
  const poller = createRunPoller({
    read:(id,signal) => request(`/runs/${encode(id)}`, {signal}),
    receive:async row => { if (!visible || row.id !== current?.id) return; current = row; renderRun(); if (!activeRun(row)) { await loadResults(resultsOffset); } },
    error:showError,
    paused:() => { message.textContent = 'Automatic status refresh paused. Use Refresh run to check again.'; },
  });
  function resume() { if (visible && activeRun(current)) poller.start(current.id); }
  function syncButtons() {
    planButton.disabled = busy || !subject || !choices.some(c => c.check.checked);
    runButton.hidden = !plan || !plan.selections.some(p => p.eligibility === 'eligible');
    runButton.disabled = busy || !plan || plan.selections.some(p => p.eligibility !== 'eligible') || activeRun(current);
    host.querySelectorAll('button').forEach(b => { if (b !== planButton && b !== runButton) b.disabled = busy || b.dataset.unavailable === 'true'; });
    form.querySelectorAll('input').forEach(n => { n.disabled = busy; });
    choices.forEach(c => { c.check.disabled = busy || !subject || !c.available || !c.transform.chains.includes(subject.chain); c.budget.disabled = busy; });
    options.querySelectorAll('input').forEach(n => { n.disabled = busy; });
  }
  function invalidate() { plan = intent = runKey = null; planned.replaceChildren(element('p', 'Prepare a plan after selecting eligible pivots.', 'muted')); syncButtons(); }
  form.elements.address.addEventListener('input', () => { entry = null; renderEntry(); subject = null; detected.textContent = 'Check this subject before planning.'; choices.forEach(c => { c.check.checked = false; }); invalidate(); });
  async function checkSubject(expectedChain) {
    invalidate(); subject = null;
    const value = form.elements.address.value.trim();
    if (!value) throw new UserError('Enter a public Bitcoin or Ethereum wallet address.');
    let resolved;
    try { resolved = await api('/resolve', {method:'POST', body:{input:value}}); }
    catch { throw new UserError('Could not identify a supported Bitcoin or Ethereum wallet address.'); }
    if (resolved.kind === 'unknown') throw new UserError('Could not identify a supported Bitcoin or Ethereum wallet address.');
    if (resolved.kind !== 'address' || !['bitcoin','ethereum'].includes(resolved.chain)) throw new UserError('Discovery currently accepts Bitcoin and Ethereum wallet addresses only.');
    if (expectedChain && resolved.chain !== expectedChain) throw new UserError('The wallet handoff does not match its chain. Open the wallet again.');
    // After backend validation, mirror Discovery's canonical case convention
    // (the general resolver preserves ETH input case). Base58 stays exact.
    const address = resolved.chain === 'ethereum' || /^bc1/i.test(resolved.normalized) ? resolved.normalized.toLowerCase() : resolved.normalized;
    subject = {chain:resolved.chain,address};
    form.elements.address.value = subject.address;
    detected.textContent = `${label(subject.chain)} · ${subject.address} · Format checked locally; the Discovery planner remains authoritative.`;
  }
  form.addEventListener('submit', event => { event.preventDefault(); perform(() => checkSubject()); });
  options.addEventListener('change', invalidate);
  async function capabilities() {
    [transforms, sources] = await Promise.all([request('/transforms'), request('/sources')]); loaded = true; choices.length = 0;
    pivots.replaceChildren(element('h2','Available pivots'));
    if (!transforms.some(t => t.executable)) pivots.append(element('p','No automated Discovery pivots are executable in this build yet.','bounded-note'));
    for (const t of transforms) {
      const card = element('article', undefined, 'discovery-pivot'); card.dataset.transform = t.id;
      card.append(element('h3', t.display_name), element('p',t.id,'muted small'), element('p',t.description));
      card.append(element('p', `${label(t.mode)} · ${costNames[t.cost_class]} · ${t.implemented ? 'Implemented' : 'Not implemented'} / ${t.executable ? t.mode === 'manual' ? 'Manual action generation available' : 'Executable' : 'Not executable'} · ${t.configured ? 'Configured' : 'Not configured'}`));
      if(t.capture_only){
        card.append(element('p','Manual · FREE_LOCAL · No network. Preview and confirm capture; no source retrieval.','bounded-note'),button('Record source observation',openCapture));pivots.append(card);continue;
      }
      if (t.mode === 'manual') card.append(element('p','Manual pivot: Run generates an outbound search action only. The search engine was not queried by Greedy Collector.','bounded-note'));
      if (t.mode === 'local') card.append(element('p','Always reads current stored annotations; no external requests.','muted small'));
      card.append(element('p', `Result limit ${t.max_results} · Request limit ${t.max_requests} · Cache window ${t.cache_seconds} seconds. Cache compatibility is decided by the backend.`, 'muted small'));
      for (const sid of t.source_ids) {
        const source = sources.find(s => s.id === sid);
        const available = t.executable && source?.executable;
        const row = element('div', undefined, 'discovery-choice');
        const wrap = element('label'); const check = element('input'); check.type = 'checkbox'; check.dataset.source = sid;
        wrap.append(check, element('span', `Select ${source?.display_name || sid} (${sid})`)); row.append(wrap);
        const budgetWrap = element('label', `Paid authorization for ${sid} (source units)`); const budget = element('input'); budget.type = 'number'; budget.min = '0'; budget.max = '1000000'; budget.step = '1'; budget.value = '0'; budgetWrap.append(budget); budgetWrap.hidden = t.cost_class !== 'PAID'; row.append(budgetWrap);
        // PAID capabilities use zero default consent. Inspect availability through a plan;
        // only explicitly implemented paid pairs can request a nonzero authorization.
        const paidCandidate = t.implemented && t.cost_class === 'PAID' && t.unavailable_reason === 'budget_exhausted' && source?.configured;
        choices.push({transform:t, source:sid, check, budget, available:available || paidCandidate});
        check.addEventListener('change', invalidate); budget.addEventListener('input', invalidate);
        if (!available) {
          row.append(element('span', reason(t.unavailable_reason), 'muted'));
          row.append(button('Why unavailable — diagnostic plan', () => makePlan([{transform_id:t.id,source_id:sid}], true)));
        }
        card.append(row);
      }
      pivots.append(card);
    }
    sourcePanel.replaceChildren(element('h2','Source capabilities'), element('p','Configured does not mean implemented, reachable or entitled. No credentials are displayed.','muted small'));
    const expand = element('details'); expand.append(element('summary', `${sources.length} registered sources`));
    expand.append(table(['Source','Mode / cost','State','Capability notes'],sources.map(s => [s.display_name + ' (' + s.id + ')',`${label(s.mode)} / ${costNames[s.cost_class]}`,`${s.configured ? 'Configured' : 'Not configured'} / ${s.executable ? 'Executable' : 'Not executable'}`,s.provenance_note]))); sourcePanel.append(expand); syncButtons();
  }
  async function makePlan(selections, diagnostic = false) {
    if (!subject) throw new UserError('Check a supported wallet subject first.');
    invalidate();
    const chosen = choices.filter(c => c.check.checked);
    selections ||= chosen.map(c => ({transform_id:c.transform.id,source_id:c.source}));
    if (!selections.length) throw new UserError('Select an executable pivot first.');
    const paid_units = {};
    for (const c of chosen.filter(c => c.transform.cost_class === 'PAID')) {
      const amount = Number(c.budget.value);
      if (!Number.isSafeInteger(amount) || amount < 0 || amount > 1000000) throw new UserError('Paid authorization must be a bounded nonnegative integer.');
      if (!diagnostic) paid_units[c.source] = amount;
    }
    const payload = {subject:{...subject}, selections, refresh:options.querySelector('[name=refresh]').checked, budget:{allow_free_local:true,allow_free_remote:true,allow_limited_free:true,paid_units}};
    const response = await request('/plan',{body:payload});
    plan = response; intent = payload; runKey = crypto.randomUUID();
    planned.replaceChildren(element('h3',diagnostic ? 'Diagnostic plan — no execution' : 'Plan ready for inspection'), element('p', `${label(plan.subject.namespace)} · ${plan.subject.canonical_value}`, 'full-address'));
    planned.append(table(['Pivot / source','Eligibility','Cost / authorization','Allowed limits','Cache'],plan.selections.map(p => [`${p.transform_id} / ${p.source_id}`,reason(p.eligibility),`${costNames[p.cost_class]} · Maximum ${p.max_units} ${p.cost_unit}; paid authorized ${plan.budget.paid_units[p.source_id] || 0}`,`${p.parameters.max_results} results / ${p.max_requests} requests`,plan.refresh ? 'Explicit refresh; reuse bypassed' : `Compatible cache may be reused (${p.cache_seconds}s window)`])));
    planned.append(element('p',`Expires ${dateText(plan.expires_at)}. Planning did not query providers. Confirm Run discovery to execute eligible pivots.`, 'muted small'));
    if (plan.selections.some(p => transforms.find(t => t.id === p.transform_id)?.mode === 'manual')) planned.append(element('p','Selected manual pivots generate search actions only. GC does not conduct the search or collect webpages.','bounded-note'));
    if (!plan.selections.some(p => p.eligibility === 'eligible')) planned.append(element('p','No selected pivots are currently executable.','bounded-note'));
    syncButtons();
  }
  async function startRun() {
    if (!plan || !plan.selections.length || plan.selections.some(p => p.eligibility !== 'eligible')) throw new UserError('Create a plan with executable selected pivots first.');
    const row = await request('/runs',{body:{...intent,expected_plan_fingerprint:plan.fingerprint},key:runKey});
    invalidate(); await selectRun(row.id, row); await loadHistory(0);
  }
  function renderEntry() {
    entryPanel.hidden = !entry;
    entryPanel.replaceChildren();
    if (!entry) return;
    entryPanel.append(element('h2',`From ${label(entry.origin)}`),element('p',`${label(entry.chain)} · ${entry.address}`,'full-address'),
      element('p','Subject prefill only. Select pivots, Plan, then Run explicitly. Existing runs remain in global history.','muted small'),
      button(entry.origin === 'graph' ? 'Back to graph' : 'Back to wallet', () => returnFromDiscovery(entry)));
    if (activeRun(current) && (current.subject.namespace !== entry.chain || current.subject.canonical_value !== subject?.address)) {
      entryPanel.append(element('p','You have an active run for another subject. It remains selected below and is not cancelled. A new run must wait for it to finish or be explicitly cancelled.','bounded-note'));
    }
  }
  function openWallet(value, activate = true) {
    if (activate) visible = true;
    pendingHandoff = value;
    if (busy) return;
    return perform(async () => {
      const incoming = pendingHandoff; pendingHandoff = null;
      await setResultView(false);
      if(incoming?.action==='open_observation'){
        await capabilities();await selectRun(incoming.run_id);
        subject={chain:current.subject.namespace,address:current.subject.canonical_value};
        form.elements.address.value=subject.address;entry=null;renderEntry();invalidate();
        detected.textContent=`${label(subject.chain)} · ${subject.address} · Stored observation wallet.`;
        await openResult(incoming.result_id,incoming.observation_id);return;
      }
      entry = walletContext(incoming);
      subject = null; choices.forEach(c => { c.check.checked = false; c.budget.value = '0'; });
      options.querySelector('[name=refresh]').checked = false; invalidate(); renderEntry();
      if (!entry) throw new UserError('Discovery handoff requires a supported wallet and origin workspace.');
      if (entry.isCurrent && !entry.isCurrent()) throw new UserError('The selected wallet view has changed. Select it again before opening Discovery.');
      form.elements.address.value = entry.address;
      await checkSubject(entry.chain); entry.address = subject.address; renderEntry();
      await capabilities();
      // Read global history only; never auto-open a previous run or execute a pivot.
      await loadHistory(historyOffset);
      if(incoming.action==='manual_source')openCapture();
    }).then(() => { if (visible && !busy) form.elements.address.focus(); });
  }
  function renderRun() {
    renderEntry();
    currentPanel.replaceChildren(element('h2','Current run'));
    if (!current) { currentPanel.append(element('p','No run selected.','empty')); return; }
    currentPanel.dataset.status = current.status; currentPanel.dataset.runId = current.id;
    currentPanel.append(element('p',`${label(current.status)}${current.archived_at ? ' · Archived' : ''}`, 'badge'),element('p',current.id,'full-address'),element('p',`${label(current.subject.namespace)} · ${current.subject.canonical_value}`));
    currentPanel.append(element('p',`Started: ${dateText(current.started_at)} · Created: ${dateText(current.created_at)} · Records returned: ${current.returned_count}`));
    currentPanel.append(button('Refresh run', () => selectRun(current.id)));
    if (activeRun(current)) {
      currentPanel.append(button('Cancel', async () => {
        // Worker progress can advance the optimistic version between polls.
        current = await request(`/runs/${encode(current.id)}`);
        if (activeRun(current)) current = await request(`/runs/${encode(current.id)}/cancel`,{body:{expected_version:current.version}});
        renderRun(); await loadResults(resultsOffset);
      }));
      currentPanel.append(element('p','Cancellation is cooperative. An in-flight operation may not stop immediately; committed results and consumed units remain.','muted small'));
    } else currentPanel.append(button(current.archived_at ? 'Restore run' : 'Archive run', async () => { current = await request(`/runs/${encode(current.id)}/${current.archived_at ? 'restore' : 'archive'}`,{body:{expected_version:current.version}}); renderRun(); await loadHistory(historyOffset); }));
    if (current.status === 'partial') currentPanel.append(element('p','Some source work was incomplete or unsuccessful. Results from successful sources remain available.','bounded-note'));
    if (current.cancel_requested_at) currentPanel.append(element('p',`Cancellation requested: ${dateText(current.cancel_requested_at)}`));
    currentPanel.append(table(['Pivot / source','Status / reason','Coverage / records','Cache','Accounting'],current.sources.map(s => [`${s.transform_id} / ${s.source_id}`,`${label(s.status)}${s.error_code ? ' · '+sourceReason(s) : ''}${s.retry_after_at ? ' · Retry after '+dateText(s.retry_after_at) : ''}`,`${label(s.coverage)} / ${s.returned_count}${s.provider_total == null ? '' : ' (provider count '+s.provider_total+')'}`,s.cache_from_id ? 'Cached observations — original retrieval times below' : 'No cache reuse',`Requests ${s.requests_attempted} attempted / ${s.requests_reserved} reserved; ${s.units_consumed} ${s.cost_unit} consumed / ${s.units_reserved} reserved; provider quota remaining: ${s.quota_snapshot?.remaining ?? 'Unknown'}`])));
    currentPanel.append(details('Run budget authorization', current.budget)); syncButtons();
    for(const source of current.sources||[])if(source.transform_id==='wallet.graphsense_public_tags' && ['succeeded','cache_hit'].includes(source.status) && source.returned_count===0)currentPanel.append(element('p','No matching GraphSense public tag was returned within the bounded search.','empty'));
    const ensDiagnostics={empty_primary_name:'No verified ENS primary name returned.',reverse_forward_mismatch:'Reverse and forward addresses did not match. No verified ENS primary name returned.',ccip_read_unsupported:'This ENS resolution requires CCIP-Read, which is not supported.',invalid_ens_name:'ENS returned a name that could not be accepted by the normalizer.'};
    for(const source of current.sources) if(source.source_id==='ens_ethereum') {
      const diagnostic=source.quota_snapshot?.diagnostic;
      if(diagnostic)currentPanel.append(element('p',(ensDiagnostics[diagnostic]||'ENS resolution could not be completed.')+' ('+diagnostic+')','bounded-note'));
      else if(['succeeded','cache_hit'].includes(source.status)&&source.returned_count===0)currentPanel.append(element('p','No verified ENS primary name returned.','empty'));
    }
    for (const source of current.sources) for (const a of source.manual_actions || []) {
      const manual = element('section',undefined,'discovery-pivot'); manual.classList.add('discovery-manual-action');
      manual.append(element('h3','Manual action available — not queried by Greedy Collector'),element('p',`Source: ${a.source_name}`),element('p',a.query,'full-address'),reference(a.url),element('p',a.note,'bounded-note'),element('p','Opening this link leaves GC for the external search site. No web results or observations were collected.','muted small'));
      currentPanel.append(manual);
    }
  }
  async function selectRun(id, row) { poller.stop(); current = row || await request(`/runs/${encode(id)}`); result = observation = null; detail.hidden = true; renderRun(); await loadResults(0); }
  function pager(page, load) {
    const bar = element('div',undefined,'toolbar discovery-pagination'); bar.append(element('span', `${page.total ? page.offset + 1 : 0}–${Math.min(page.offset + page.items.length,page.total)} of ${page.total}`));
    if (page.offset > 0) bar.append(button('Previous page', () => load(Math.max(0,page.offset-page.limit))));
    if (page.next_offset !== null) bar.append(button('Next page', () => load(page.next_offset))); return bar;
  }
  async function loadResults(offset = 0) {
    if (!current) return;
    const page = await request(`/runs/${encode(current.id)}/results?limit=20&offset=${offset}`); resultsOffset = offset;
    results.replaceChildren(element('h2','Results'),element('p','Candidate relationships are not ownership claims. Review summaries are current; observations retain their historical material.','muted small'));
    results.append(table(['Candidate / relationship','Reference / source','Original observation times','Review','Provenance','Action'],page.items.map(item => {
      const r = item.result, o = item.observation;
      return [`${o.title} · ${label(r.kind)} · ${r.predicate}`,reference(o.source_url || o.source_locator),`${item.inclusion_kind === 'cache' ? 'Cached observation · ' : ''}${o.kind==='analyst_capture'?'Captured':'Retrieved'} ${dateText(o.kind==='analyst_capture'?(o.created_at||o.retrieved_at):o.retrieved_at)} · Observed ${o.observed_on || dateText(o.observed_at)} · ${o.source_id}`,reviewText(r),`${item.provenance_count} observations`,button('Inspect result', () => openResult(r.id, o.id))];
    }), activeRun(current) ? 'This run is active. No candidate records are stored yet.' : 'No candidate results were returned for this run.'),pager(page,loadResults));
    await graph.setRun(current.id);
  }
  async function openResult(id, selectedObservation) {
    result = await request(`/results/${encode(id)}`); observation = null; detail.hidden = false;
    detail.replaceChildren(element('h2','Result detail'),element('p',`${label(result.kind)} · ${result.predicate}`),element('p',reviewText(result),'badge'));
    if (result.new_material_since_review && result.reviewed_material_revision > 0) detail.append(element('p','Source material changed since the previous review. Renewed review is needed.','bounded-note'));
    detail.append(details('Normalized candidate and directed subject references', {id:result.id, fact_key:result.fact_key,from_subject_id:result.from_subject_id,to_subject_id:result.to_subject_id,first_seen_at:result.first_seen_at,last_seen_at:result.last_seen_at,material_revision:result.material_revision,reviewed_material_revision:result.reviewed_material_revision}));
    const observations = element('div'); observations.id = 'discovery-observations'; const selected = element('div'); selected.id = 'discovery-observation'; const reviews = element('div'); reviews.id = 'discovery-reviews';
    detail.append(button('Reload result', () => openResult(id, observation?.id)),button('Back to Discovery graph',async()=>{await setResultView(true);graphPanel.scrollIntoView({block:'start'});}),observations,selected,reviews);
    await loadObservations(0); await loadReviews(0); if (selectedObservation) await openObservation(selectedObservation);
  }
  async function loadObservations(offset) {
    const page = await request(`/results/${encode(result.id)}/observations?limit=20&offset=${offset}`); observationsOffset = offset;
    byId('discovery-observations').replaceChildren(element('h3','Observations'),table(['Source / pivot','Title / verification','Retrieved / observed','Inspect'],page.items.map(o => [`${o.source_id} / ${o.transform_id}`,`${o.title} · ${label(o.verification)}`,`${dateText(o.retrieved_at)} / ${o.observed_on || dateText(o.observed_at)}`,button('Inspect observation', () => openObservation(o.id))])),pager(page,loadObservations));
  }
  async function openObservation(id) {
    observation = await request(`/observations/${encode(id)}`); const o = observation;
    const target = byId('discovery-observation');
    target.replaceChildren(element('h3',o.title),element('p',o.summary),reference(o.source_url || o.source_locator),element('p',`Source ${o.source_id} · Pivot ${o.transform_id} · ${label(o.kind)} · ${label(o.verification)}`),element('p',`${o.kind==='analyst_capture'?'Captured':'Retrieved'} ${dateText(o.kind==='analyst_capture'?(o.created_at||o.retrieved_at):o.retrieved_at)} · Observed ${o.observed_on || dateText(o.observed_at)} · Published ${o.published_on || dateText(o.published_at)}`));
    if(o.source_snapshot?.provider==='GraphSense' && o.kind==='verified_page_observation')target.append(graphSenseDetail(o.source_snapshot,o.retrieved_at));
    if(o.kind==='analyst_capture' && o.source_id==='manual_source')target.append(manualSourceDetail(o.source_snapshot,o.created_at));
    if (o.kind === 'name_service_record' && o.source_id === 'ens_ethereum') {
      const s=o.source_snapshot||{};
      target.append(element('h4','ENS primary name'),table(['Field','Observed value'],[['Name',s.primary_name],['Wallet',s.wallet],['Namespace',s.namespace],['Verification',s.verification==='forward_verified'?'Forward verified':'Not verified'],['Method',s.verification_method],['Source','ENS / Ethereum'],['Provider',s.provider],['Universal Resolver',s.universal_resolver],['Resolver',s.resolver],['Reverse resolver',s.reverse_resolver]]),element('p','A technical public naming relationship does not establish real-world identity or wallet control.','bounded-note'));
    }
    if (o.kind === 'code_search_result' && o.source_id === 'github') {
      const s = o.source_snapshot || {};
      target.append(element('h4','GitHub code mention'),table(['Field','Returned source value'],[['Repository',s.repository_full_name],['File path',s.file_path],['Matched full wallet',o.match_context?.matched_wallet],['GitHub search score',s.github_search_score ?? 'Not returned'],['Blob SHA',s.blob_sha ?? 'Not returned'],['Provider incomplete results',String(s.incomplete_results)]]),element('p','GitHub search score is ranking metadata, not ownership probability, Attribution confidence or a GC risk score. A code mention does not establish wallet control.','bounded-note'));
      const link = reference(s.file_html_url);
      if (link.tagName === 'A') link.textContent = 'Open on GitHub';
      target.append(link,element('h4','Matched code context'));
    }
    if (o.excerpt) target.append(element('blockquote',o.excerpt),element('p',o.excerpt_complete ? 'Source marks this excerpt complete.' : 'Bounded excerpt; not a complete document.','muted small'));
    if (o.kind === 'local_label_snapshot' && o.source_snapshot?.record) {
      const r = o.source_snapshot.record;
      target.append(element('h4','Stored Label provenance'),table(['Field','Stored annotation value'],[['Label ID',r.id],['Label',r.label],['Type',r.type],['Original annotation source',r.source],['Annotation confidence (metadata only)',r.confidence],['Stored chain',r.chain],['Stored address',r.address],['Last updated',dateText(r.last_updated)]]),element('p','Confidence is stored annotation metadata, not wallet ownership probability, Attribution assessment or a Discovery risk score.','bounded-note'),element('p',o.source_snapshot.scope_note));
    }
    target.append(details('Sanitized immutable observation details',{source_locator:o.source_locator,source_record_key:o.source_record_key,source_class:o.source_class,match_context:o.match_context,source_snapshot:o.source_snapshot,content_sha256:o.content_sha256}));
    target.append(element('p','Relevance applies to the candidate’s current material revision. This selected observation records what you inspected; other observations may differ.','bounded-note'));
    const review = element('form',undefined,'editor'); review.id = 'discovery-review';
    review.append(fields([{name:'status',label:'Relevance decision',options:[['unreviewed','Unreviewed'],['relevant','Relevant'],['irrelevant','Irrelevant']],value:result.new_material_since_review ? 'unreviewed' : result.review_status},{name:'reason',label:'Review reason',type:'textarea',required:true,maxLength:4000}]));
    const save = element('button','Save review'); save.type = 'submit'; review.append(save);
    review.addEventListener('submit',e => { e.preventDefault(); const status = review.elements.status.value, reason = review.elements.reason.value.trim(); perform(async () => {
      if (!reason) throw new UserError('A review reason is required.');
      await request(`/results/${encode(result.id)}/review`,{body:{expected_version:result.version,observation_id:o.id,expected_source_fingerprint:o.content_sha256,status,reason}});
      await loadResults(resultsOffset); await openResult(result.id,o.id);
    }); }); target.append(review);
    await promotionDetail(target,o);
  }
  async function loadReviews(offset) {
    const page = await request(`/results/${encode(result.id)}/reviews?limit=20&offset=${offset}`); reviewsOffset = offset;
    byId('discovery-reviews').replaceChildren(element('h3','Review history'),table(['Decision','Reason','Material revision / observation','Recorded'],page.items.map(r => [label(r.status),r.reason,`${r.material_revision} / ${r.observation_id}`,dateText(r.occurred_at)]),'No relevance decisions recorded.'),pager(page,loadReviews));
  }
  async function loadHistory(offset = 0) {
    const params = new URLSearchParams({limit:'20',offset:String(offset),include_archived:String(filters.elements.include_archived.checked)});
    if (filters.elements.status.value) params.set('status',filters.elements.status.value);
    if (filters.elements.subject_id.value.trim()) params.set('subject_id',filters.elements.subject_id.value.trim());
    const page = await request('/runs?'+params); historyOffset = offset;
    // Summaries omit addresses/counts. Enrich only this bounded page, four local
    // reads at a time, on explicit history loading; never poll historical runs.
    const rows = [];
    for (let i = 0; i < page.items.length; i += 4) {
      rows.push(...await Promise.all(page.items.slice(i,i+4).map(r => request(`/runs/${encode(r.id)}`))));
    }
    historyRows.replaceChildren(table(['Subject','Created','Status','Records / pivots','Archived','Action'],rows.map(r => [`${subject?.chain === r.subject.namespace && subject?.address === r.subject.canonical_value ? "Current subject · " : ""}${label(r.subject.namespace)} · ${r.subject.canonical_value}`,dateText(r.created_at),label(r.status),`${r.returned_count} / ${r.sources.length}`,r.archived_at ? 'Archived' : 'No',button('Open run', () => selectRun(r.id))]),'No Discovery runs are stored in this history view.'),pager(page,loadHistory));
  }
  filters.addEventListener('submit',e => { e.preventDefault(); perform(() => loadHistory(0)); });
  invalidate();
  return {openWallet,setVisible(value, restore = false) {
    const entering = value && !visible; visible = value;
    if (!visible) { poller.stop(); graph.pause(); return; }
    if (entering && restore && graph.active) perform(()=>graph.refresh());
    if (entering && !restore) perform(async () => { if (!loaded) await capabilities(); if (current) await selectRun(current.id); await loadHistory(historyOffset); });
  }};
}
