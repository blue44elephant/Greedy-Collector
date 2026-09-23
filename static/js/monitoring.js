import {chainMetadata, hasCapability} from './chains.js';
import {api, ApiError} from "./api.js";
import {byId, element, panel, table, shortValue, dateText, fields, chainAddress, run} from "./ui.js";

import {listCases, caseOptions} from "./case_actions.js";

const PAGE_SIZE = 25;
const CONTINUITY = "Greedy Collector could not locate the previous monitoring boundary within the current bounded provider history. Ambiguous activity was not alerted and the previous boundary was preserved.";
const FAILED = "Monitoring check failed. Verify server provider configuration and try again. The provider may be unavailable or rate limited.";
const watchPath = id => `/watchlist/${encodeURIComponent(id)}`;

// Never render arbitrary persisted exception text, even in a historical run.
function runStatus(value) {
  return {completed:"Completed", continuity_loss:"Continuity loss", failed:"Provider failure", running:"Running"}[value] || "Unknown status";
}
function runExplanation(value) {
  if (value === "continuity_loss") return CONTINUITY;
  if (value === "failed") return FAILED;
  if (value === "completed") return "Check completed. Zero new transactions or alerts is a valid result.";
  return "No completed result is available yet.";
}
function metadata(entries) {
  const list = element("dl", undefined, "metadata");
  for (const [label, value] of entries) {
    const item = element("div");
    const description = element("dd");
    description.append(value instanceof Node ? value : element("span", value));
    item.append(element("dt", label), description); list.append(item);
  }
  return list;
}
function boundary(value) { return value ? shortValue(value) : element("span", "Not recorded"); }
function balance(wallet) {
  return wallet.balance_native == null ? "Not available" : `${wallet.balance_native} ${chainMetadata(wallet.chain)?.native_symbol ?? ""}`;
}
async function request(path, options) {
  try { return await api(path, options); }
  catch (error) {
    if (error instanceof ApiError) {
      if (error.status === 404) throw new ApiError(404, "The watch or assigned case was not found. Refresh and check the selection.");
      if (error.status === 409) throw new ApiError(409, "The watch must be enabled and no other check for this chain can be running. Refresh and try again.");
      if (error.status === 422) throw new ApiError(422, "Check the public wallet address, selected chain, and watch fields.");
    }
    throw error;
  }
}

export function initMonitoring() {
  const host = byId("monitoring-workspace");
  let cases = [];
  let wallets = [], selectedId = null, offset = 0;
  const top = element("div", undefined, "workspace-heading");
  top.append(element("h1", "Monitoring"));
  const statusMessage = element("p", undefined, "operation-status");
  statusMessage.setAttribute("role", "status");
  const scheduler = panel("Scheduler"); scheduler.id = "monitoring-scheduler";
  const createPanel = panel("Add wallet", "Use public wallet addresses only. Never enter a private key or recovery phrase. A prior lookup is not required.");
  const list = panel("Watchlist"); list.id = "monitoring-list";
  const selected = panel("Selected wallet"); selected.id = "monitoring-selected"; selected.hidden = true;
  const lastResult = panel("Last manual check"); lastResult.id = "monitoring-result"; lastResult.hidden = true;
  const history = panel("Run history"); history.id = "monitoring-history"; history.hidden = true;
  const alerts = panel("Wallet alerts"); alerts.id = "monitoring-alerts"; alerts.hidden = true;
  host.append(top, statusMessage, scheduler, createPanel, list, selected, lastResult, history, alerts);

  const perform = (operation, pending = "Loading monitoring state…") => run(host, operation, pending);
  function button(label, operation, disabled = false) {
    const node = element("button", label, "secondary"); node.type = "button"; node.disabled = disabled;
    node.addEventListener("click", () => perform(operation, label === "Check now" ? "Checking selected wallet…" : "Loading monitoring state…")); return node;
  }
  function editor(definitions, label, submit) {
    const form = element("form", undefined, "editor"); form.append(fields(definitions));
    const save = element("button", label); save.type = "submit"; form.append(save);
    form.addEventListener("submit", event => {
      event.preventDefault();
      const data = Object.fromEntries(new FormData(form));
      perform(() => submit(data, form), "Saving watch…");
    });
    return form;
  }
  function editable(wallet = {}) {
    return [
      {name:"label", label:"Label", value:wallet.label || "", maxLength:255},
      {name:"priority", label:"Priority", options:["low", "normal", "high", "critical"], value:wallet.priority || "normal"},
      {name:"notes", label:"Notes", type:"textarea", value:wallet.notes || ""},
      {name:"case_id", label:"Case (optional)", options:caseOptions(cases).concat(wallet.case_id && !cases.some(row => row.id === wallet.case_id) ? [[wallet.case_id,"Unavailable case (current assignment)"]] : []), value:wallet.case_id || ""},
      {name:"enabled", label:"Enabled", type:"checkbox", value:wallet.enabled ?? true},
    ];
  }
  const payload = data => ({label:data.label, priority:data.priority, notes:data.notes, case_id:data.case_id.trim() || null, enabled:data.enabled === "on"});
  const createForm = editor([...chainAddress(), ...editable()], "Add watch", async (data, form) => {
    const wallet = await request("/watchlist", {method:"POST", body:{chain:data.chain, address:data.address.trim(), ...payload(data)}});
    selectedId = wallet.id; offset = 0; selected.hidden = history.hidden = alerts.hidden = lastResult.hidden = true;
    form.reset();
    form.elements.priority.value = "normal";
    form.elements.enabled.checked = true;
    await refresh();
  });
  createForm.id = "monitoring-create"; createPanel.append(createForm);
  createPanel.append(element("p", "Case assignment applies to future alerts generated by the watch; it does not move existing alerts.", "muted small"));
  createPanel.append(element("p", "The first observation establishes a silent baseline; historical activity does not automatically become alerts. Adding an existing address returns its existing watch—use Edit watch to change it.", "bounded-note"));
  top.append(button("Refresh monitoring", refresh));

  function renderScheduler(state) {
    scheduler.replaceChildren(element("h2", "Scheduler"));
    const backend = {apscheduler:"APScheduler", celery:"Celery", disabled:"Disabled"}[state.active] || "Unknown";
    scheduler.append(metadata([
      ["Configured backend", backend],
      ["Local scheduler", state.scheduler_running === true ? "Running" : "Not running"],
      ["Ethereum interval", typeof state.ethereum_interval_minutes === "number" ? `${state.ethereum_interval_minutes} minutes` : "Not available"],
      ["Bitcoin interval", typeof state.bitcoin_interval_minutes === "number" ? `${state.bitcoin_interval_minutes} minutes` : "Not available"],
    ]));
    scheduler.append(element("p", "Values reflect the last refresh. Celery worker/beat activity is not verified by this status. Use one application process: overlap protection is process-local. Changes appear after an explicit refresh or action.", "muted small"));
  }
  function snapshot(wallet) {
    return metadata([
      ["Case assignment", cases.find(row => row.id === wallet.case_id)?.title || wallet.case_id || "None"], ["Last checked", dateText(wallet.last_checked)],
      ["Last seen transaction", boundary(wallet.last_seen_tx)], ["Last seen block", wallet.last_seen_block || "Not recorded"],
      ["Stored balance", balance(wallet)], ["Stored last activity", dateText(wallet.last_activity)],
      ["Stored risk score", wallet.risk_score], ["Last run status", wallet.last_monitoring_status ? runStatus(wallet.last_monitoring_status) : "No runs"],
    ]);
  }
  function renderList() {
    list.replaceChildren(element("h2", "Watchlist"));
    list.append(table(["Label", "Chain", "Address", "State", "Priority", "Stored snapshot", "Alert count", "Action"], wallets.map(wallet => {
      const details = element("details"); details.append(element("summary", "State details"), snapshot(wallet));
      return [wallet.label || "Unlabelled", wallet.chain, shortValue(wallet.address), wallet.enabled ? "Enabled" : "Disabled",
        wallet.priority, details, wallet.alert_count, button("Select wallet", async () => {
          selectedId = wallet.id; offset = 0; history.hidden = alerts.hidden = lastResult.hidden = true; renderSelected(wallet); await loadDetails();
          selected.scrollIntoView({block:"start"});
        })];
    }), "No wallets are being monitored. Add a public wallet address to begin."));
    list.append(element("p", "Stored balance and risk may predate the latest check. Expand State details for each wallet. Refresh to retrieve current local state.", "muted small"));
  }
  function renderSelected(wallet) {
    selected.hidden = false;
    selected.replaceChildren(element("h2", wallet.label || "Selected wallet"), element("p", wallet.address, "full-address"),
      element("p", `${wallet.chain} · ${wallet.enabled ? "Enabled" : "Disabled"} · ${wallet.priority} priority`), snapshot(wallet));
    const controls = element("div", undefined, "toolbar");
    controls.append(button("Check now", () => checkNow(wallet.id), !wallet.enabled),
      button(wallet.enabled ? "Disable watch" : "Enable watch", async () => {
        await request(watchPath(wallet.id), {method:"PATCH", body:{enabled:!wallet.enabled}}); await refresh();
      }));
    selected.append(controls, element("p", "Disabling preserves the baseline, run history, and alerts. Re-enabling continues from the retained boundary.", "muted small"));
    const edit = element("details"); edit.append(element("summary", "Edit watch"));
    const form = editor(editable(wallet), "Save watch", async data => {
      await request(watchPath(wallet.id), {method:"PATCH", body:payload(data)}); await refresh();
    });
    form.id = "monitoring-edit"; edit.append(form); selected.append(edit);
  }
  async function refresh() {
    const [state, response, caseRows] = await Promise.all([request("/status"), request("/watchlist"), listCases()]);
    cases = caseRows;
    const choice = createForm.elements.case_id, previous = choice.value;
    choice.replaceChildren(...caseOptions(cases).map(([value,label]) => {const option=element("option",label); option.value=value; return option;}));
    choice.value = cases.some(row => row.id === previous) ? previous : "";
    wallets = response.wallets; renderScheduler(state.backends.monitoring); renderList();
    const wallet = wallets.find(item => item.id === selectedId);
    if (wallet) { renderSelected(wallet); await loadDetails(); }
    else { selectedId = null; selected.hidden = history.hidden = alerts.hidden = lastResult.hidden = true; }
  }
  async function loadDetails() {
    const wallet = wallets.find(item => item.id === selectedId);
    if (!wallet) return;
    // Run history is paginated. The existing alerts API has no wallet filter.
    const [page, response] = await Promise.all([
      request(`${watchPath(wallet.id)}/runs?limit=${PAGE_SIZE}&offset=${offset}`), request("/alerts"),
    ]);
    history.hidden = alerts.hidden = false;
    history.replaceChildren(element("h2", "Run history"));
    history.append(table(["Status", "Started (UTC)", "Completed (UTC)", "New transactions", "Result"], page.runs.map(item =>
      [runStatus(item.status), dateText(item.started_at), dateText(item.completed_at), item.new_transactions, runExplanation(item.status)]), "No monitoring history for this wallet."));
    history.append(element("p", `Runs returned: ${page.runs.length} · Stored runs: ${page.total}. Newest first. Historical runs do not include boundary snapshots or per-run alert counts.`, "muted small"));
    const pager = element("div", undefined, "toolbar");
    pager.append(button("Newer runs", async () => {offset = Math.max(0, offset - PAGE_SIZE); await loadDetails();}, offset === 0),
      button("Older runs", async () => {offset += PAGE_SIZE; await loadDetails();}, offset + PAGE_SIZE >= page.total));
    history.append(pager);
    const rows = response.alerts.filter(item => item.wallet === wallet.address && item.chain === wallet.chain);
    alerts.replaceChildren(element("h2", "Wallet alerts"), element("p", `${rows.length} stored alerts for this wallet. These are not a per-run generated count.`, "muted small"));
    alerts.append(table(["Trigger", "Severity", "Transaction", "Counterparty", "Amount", "Token", "Risk score", "Explanation", "Status", "Timestamp (UTC)"], rows.map(item =>
      [item.trigger_type, item.severity, item.tx_hash ? shortValue(item.tx_hash) : "No transaction reference", shortValue(item.counterparty), item.amount, item.token, item.risk_score, item.explanation, item.status, dateText(item.timestamp)]), "No alerts for this wallet."));
    alerts.append(element("p", "Risk indicators are not proof of wrongdoing. Risk-only alerts may have no transaction reference.", "bounded-note"));
  }
  async function checkNow(id) {
    // Capture the latest stored state for an explicitly labelled comparison.
    const before = (await request("/watchlist")).wallets.find(item => item.id === id);
    const result = await request(`${watchPath(id)}/check`, {method:"POST"});
    const item = result.run;
    lastResult.hidden = false;
    lastResult.replaceChildren(element("h2", "Last manual check"),
      element("p", runStatus(item.status), "badge"),
      element("p", runExplanation(item.status), item.status === "failed" ? "error" : "bounded-note"),
      metadata([["Started", dateText(item.started_at)], ["Completed", dateText(item.completed_at)], ["New transactions", item.new_transactions],
        ["Pre-check boundary snapshot", boundary(before?.last_seen_tx)], ["Returned boundary", boundary(result.wallet.last_seen_tx)],
        ["Returned boundary block", result.wallet.last_seen_block || "Not recorded"]]));
    if (!before?.last_seen_tx && item.status === "completed") {
      lastResult.append(element("p", "No boundary was recorded in the pre-check snapshot. The first observation establishes a silent baseline without historical alerts. Empty history or Bitcoin mempool-only activity may leave the boundary unset.", "bounded-note"));
    }
    lastResult.append(element("p", "Boundary comparison uses the pre-check snapshot and returned wallet state; concurrent scheduled activity may occur. See Wallet alerts for the actual stored alerts.", "muted small"));
    offset = 0;
    try { await refresh(); }
    catch { throw new ApiError(0, "The check returned a result, but refreshing stored state failed. The returned result is shown; use Refresh monitoring to retry."); }
  }
  return () => perform(refresh);
}
