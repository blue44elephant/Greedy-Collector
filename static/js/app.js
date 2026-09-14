import {refreshAttribution} from "./attribution_summary.js";
import {byId} from "./ui.js";
import {initWallet} from "./wallet.js";
import {initGraph} from "./graph.js";
import {initMonitoring} from "./monitoring.js";
import {initAlerts} from "./alerts.js";
import {initCases} from "./cases.js";
import {initLabels} from "./labels.js";
import {initResearch} from "./research.js";

import {initAttribution} from "./attribution.js";

import {initDiscovery} from "./discovery.js";

function navigate(name, id, restore = false) {
  if (!byId(`${name}-workspace`)) return;
  document.querySelectorAll(".workspace").forEach(node => { node.hidden = node.id !== `${name}-workspace`; });
  document.querySelectorAll("[data-workspace]").forEach(node => { node.setAttribute("aria-current", String(node.dataset.workspace === name)); });
  if (name === "discovery" && id) discovery.openWallet(id);
  else discovery.setVisible(name === "discovery");
  if (name === "monitoring") loadMonitoring();
  if (name === "alerts") loadAlerts(id);
  if (name === "cases") loadCases(id);
  if (name === "labels") loadLabels(id);
  if (name === "research") loadResearch();
  if (name === "attribution") loadAttribution(id);
  if (!restore && name === "wallet" && !byId("results").hidden) refreshAttribution(byId("wallet-workspace"));
  if (!restore && name === "graph") queueMicrotask(() => {
    // A handoff can immediately submit a replacement graph after navigation.
    if (byId("graph-workspace").querySelector("form").dataset.busy !== "true") refreshAttribution(byId("graph-workspace"));
  });
}
initWallet(navigate);
initGraph();
const loadMonitoring = initMonitoring();
const loadAlerts = initAlerts(navigate);
const loadCases = initCases();
const loadLabels = initLabels();
const loadResearch = initResearch();
const loadAttribution = initAttribution();
const discovery = initDiscovery();
document.addEventListener("open-discovery", event => navigate("discovery", event.detail));
document.addEventListener("return-discovery", event => {
  if (["wallet","graph"].includes(event.detail?.workspace)) navigate(event.detail.workspace, undefined, true);
});
document.addEventListener("open-attribution", event => navigate("attribution", event.detail));
document.addEventListener("open-label", event => navigate("labels", event.detail.id));
document.addEventListener("open-case", event => navigate("cases", event.detail.id));
document.addEventListener("open-alert", event => navigate("alerts", event.detail.id));
document.querySelectorAll("[data-workspace]").forEach(button => button.addEventListener("click", () => navigate(button.dataset.workspace)));
navigate("wallet");
