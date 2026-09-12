import {api, ApiError} from "./api.js";
import {byId, element, panel, table, shortValue, dateText, fields, run, UserError} from "./ui.js";
import {investigate} from "./wallet.js";

import {listCases, openCase} from "./case_actions.js";

const statuses = ["New", "Reviewed", "Dismissed", "Escalated"];
const badge = (value, type) => {
  const known = {New:"new", Reviewed:"reviewed", Dismissed:"dismissed", Escalated:"escalated", Critical:"critical", High:"high", Medium:"medium", Low:"low"};
  return element("span", value, `badge alert-${type} ${known[value] || "unknown"}`);
};
function validAlert(value) {
  return value && typeof value === "object" &&
    ["id", "wallet", "chain", "status", "severity", "trigger_type", "explanation", "notes", "timestamp"].every(key => typeof value[key] === "string") &&
    ["tx_hash", "counterparty", "amount", "token", "case_id"].every(key => value[key] == null || typeof value[key] === "string") &&
    typeof value.risk_score === "number";
}
const malformed = () => new ApiError(500, "The server returned an unexpected alerts response. Refresh and try again.");
async function request(path, options) {
  try { return await api(path, options); }
  catch (error) {
    if (error instanceof ApiError && error.status === 404) throw new ApiError(404, "This alert no longer exists. Refresh the alert list.");
    if (error instanceof ApiError && error.status === 422) throw new ApiError(422, "The alert update was not accepted. Check the status and notes.");
    throw error;
  }
}

export function initAlerts(navigate) {
  const host = byId("alerts-workspace");
  let selectedId = null, caseRows = [];
  const heading = element("div", undefined, "workspace-heading"); heading.append(element("h1", "Alerts"));
  const message = element("p", undefined, "operation-status"); message.setAttribute("role", "status");
  const filters = panel("Review alerts", "Alerts are monitoring indicators and investigation workflow records, not proof of wrongdoing. The first monitoring observation is silent; no alerts does not mean a wallet was never checked.");
  const filter = element("select"); filter.id = "alerts-status";
  for (const name of ["All", ...statuses]) {const option = element("option", name); option.value = name === "All" ? "" : name; filter.append(option);}
  const label = element("label", "Status"); label.htmlFor = filter.id;
  const filterRow = element("div", undefined, "toolbar"); filterRow.append(label, filter); filters.append(filterRow);
  const list = panel("Stored alerts"); list.id = "alerts-list";
  const detail = panel("Alert detail"); detail.id = "alert-detail"; detail.hidden = true;
  host.append(heading, message, filters, list, detail);
  const perform = (operation, pending = "Loading alerts…") => run(host, operation, pending);
  function button(title, operation) {
    const node = element("button", title, "secondary"); node.type = "button";
    node.addEventListener("click", () => perform(operation)); return node;
  }
  heading.append(button("Refresh alerts", () => load()));
  filter.addEventListener("change", () => {selectedId = null; detail.hidden = true; perform(() => load());});

  function renderDetail(alert, outsideFilter = false) {
    selectedId = alert.id; detail.hidden = false;
    detail.replaceChildren(element("h2", alert.trigger_type));
    const badges = element("div", undefined, "toolbar"); badges.append(badge(alert.status,"status"), badge(alert.severity,"severity")); detail.append(badges);
    if (outsideFilter) detail.append(element("p", "Saved alert no longer matches the current list filter. Its updated record is shown below.", "bounded-note"));
    const metadata = element("dl", undefined, "metadata");
    for (const [name, value] of [["Alert ID", alert.id], ["Wallet", alert.wallet], ["Chain", alert.chain],
      ["Transaction", alert.tx_hash || "No transaction reference"], ["Counterparty", alert.counterparty || "Not available"],
      ["Amount", alert.amount ?? "Not available"], ["Asset", alert.token || "Not available"], ["Risk score", alert.risk_score],
      ["Timestamp (UTC)", dateText(alert.timestamp)], ["Associated case", caseRows.find(row => row.id === alert.case_id)?.title || (alert.case_id ? "Case title unavailable" : "None")], ["Case ID", alert.case_id || "None"]]) {
      const row = element("div"); row.append(element("dt", name), element("dd", value)); metadata.append(row);
    }
    detail.append(metadata, element("h3", "Explanation"), element("p", alert.explanation, "prose"));
    const actions = element("div", undefined, "toolbar");
    if (alert.wallet) {
      actions.append(button("Investigate wallet", () => investigate(alert.chain, alert.wallet)));
      actions.append(button("Open graph", () => {
        const form = byId("graph-workspace").querySelector("form");
        if (form.dataset.busy === "true") throw new UserError("A graph is loading. Wait for it to finish and try again.");
        document.dispatchEvent(new CustomEvent("wallet-selected", {detail:{chain:alert.chain, address:alert.wallet}}));
        navigate("graph"); form.requestSubmit();
      }));
    }
    if (alert.tx_hash) actions.append(button("Open transaction", () => investigate(alert.chain, alert.tx_hash)));
    if (alert.case_id) actions.append(button("Open case", () => openCase(alert.case_id)));
    detail.append(actions, element("h3", "Review status and analyst notes"));
    const form = element("form", undefined, "editor"); form.id = "alert-review";
    form.append(fields([{name:"status", label:"Status", options:statuses, value:alert.status},
      {name:"notes", label:"Analyst notes", type:"textarea", value:alert.notes}]));
    const save = element("button", "Save review"); save.type = "submit"; form.append(save);
    form.addEventListener("submit", event => {
      event.preventDefault(); const payload = Object.fromEntries(new FormData(form));
      perform(async () => {
        const updated = await request(`/alerts/${encodeURIComponent(alert.id)}`, {method:"PATCH", body:payload});
        if (!validAlert(updated)) throw malformed();
        renderDetail(updated, Boolean(filter.value && filter.value !== updated.status));
        try { await load(updated); }
        catch { throw new ApiError(0, "Review saved, but refreshing the list failed. The saved record is shown; use Refresh alerts to retry."); }
      }, "Saving review…");
    });
    detail.append(form);
  }
  async function load(saved = null) {
    list.replaceChildren(element("h2", "Stored alerts"), element("p", "Loading alerts…", "muted small"));
    const response = await request(filter.value ? `/alerts?status=${encodeURIComponent(filter.value)}` : "/alerts");
    if (!response || !Array.isArray(response.alerts) || !response.alerts.every(validAlert)) throw malformed();
    // Preserve backend ordering and identity; only suppress repeated DOM IDs.
    caseRows = response.alerts.some(row => row.case_id) ? await listCases().catch(() => []) : [];
    const rows = [...new Map(response.alerts.map(alert => [alert.id,alert])).values()];
    list.replaceChildren(element("h2", "Stored alerts"));
    list.append(element("p", `${rows.length} returned alerts. Newest first. The current API does not paginate alerts.`, "muted small"));
    list.append(table(["Status", "Severity", "Chain", "Wallet", "Trigger", "Transaction", "Counterparty", "Amount", "Asset", "Risk", "Timestamp (UTC)", "Review"], rows.map(alert =>
      [badge(alert.status,"status"), badge(alert.severity,"severity"), alert.chain, shortValue(alert.wallet), alert.trigger_type,
        alert.tx_hash ? shortValue(alert.tx_hash) : "No transaction reference", shortValue(alert.counterparty), alert.amount, alert.token, alert.risk_score, dateText(alert.timestamp),
        button("View alert", () => {renderDetail(alert); detail.scrollIntoView({block:"start"});})]), filter.value ? "No alerts match this status." : "No alerts have been generated."));
    if (!rows.length && !filter.value) list.append(element("p", "Alerts are created by monitored-wallet checks when configured rules are triggered.", "muted small"));
    const selected = rows.find(alert => alert.id === selectedId);
    if (selected) renderDetail(selected);
    else if (saved) renderDetail(saved, true);
    else {selectedId = null; detail.hidden = true;}
  }
  return id => {
    if (host.dataset.busy === "true") return;
    if (id) {filter.value=""; selectedId=id;}
    return perform(async () => {await load(); if(id && selectedId !== id) throw new UserError("This alert no longer exists. Refresh the alert list.");});
  };
}
