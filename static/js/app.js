import {initSanctions} from './sanctions.js';
import {initFundFlow} from './fund_flow.js';
import {initClustering} from './clustering.js';
import {refreshLabelChains} from './label_ui.js';
import {loadChains} from './chains.js';
import {refreshAttribution} from "./attribution_summary.js";
import {byId} from "./ui.js";
import {initWallet, investigate} from "./wallet.js";
import {initGraph} from "./graph.js";
import {initMonitoring} from "./monitoring.js";
import {initAlerts} from "./alerts.js";
import {initCases} from "./cases.js";
import {initNarcotics} from './narcotics.js';
import {initLabels} from "./labels.js";
import {initResearch} from "./research.js";

import {initAttribution} from "./attribution.js";

import {initDiscovery} from "./discovery.js";

function navigate(name, id, restore = false) {
  if (!byId(`${name}-workspace`)) return;
  document.querySelectorAll(".workspace").forEach(node => { node.hidden = node.id !== `${name}-workspace`; });
  document.querySelectorAll("[data-workspace]").forEach(node => { node.setAttribute("aria-current", String(node.dataset.workspace === name)); });
  if (name === "discovery" && id) discovery.openWallet(id);
  else discovery.setVisible(name === "discovery", restore);
  if (name === "monitoring") loadMonitoring();
  if (name === "alerts") loadAlerts(id);
  if (name === "cases") loadCases(id);
  if (name === "narcotics") loadNarcotics(id);
  if (name === "labels") loadLabels(id);
  if (name === "sanctions") sanctions.load();
  if (name === "research") loadResearch();
  if (name === "attribution") loadAttribution(id);
  if (!restore && name === "wallet" && !byId("results").hidden) refreshAttribution(byId("wallet-workspace"));
  if (!restore && name === "graph") queueMicrotask(() => {
    // A handoff can immediately submit a replacement graph after navigation.
    if (byId("graph-workspace").querySelector("form").dataset.busy !== "true") refreshAttribution(byId("graph-workspace"));
  });
}
await loadChains();
await initClustering(navigate);
await initFundFlow(navigate);
refreshLabelChains();
initWallet(navigate);
initGraph();
const loadMonitoring = initMonitoring();
const loadAlerts = initAlerts(navigate);
const loadCases = initCases();
const loadNarcotics = initNarcotics();
const loadLabels = initLabels();
const sanctions = initSanctions();
const loadResearch = initResearch();
const loadAttribution = initAttribution();
const discovery = initDiscovery();
document.addEventListener("open-discovery", event => navigate("discovery", event.detail));
document.addEventListener("return-discovery", event => {
  if (["wallet","graph"].includes(event.detail?.workspace)) navigate(event.detail.workspace, undefined, true);
});
document.addEventListener("open-attribution", event => navigate("attribution", event.detail));
document.addEventListener("open-label", event => navigate("labels", event.detail.id));
document.addEventListener("open-label-address", event => {
  const form = byId("label-create");
  form.elements.chain.value = event.detail.chain;
  form.elements.address.value = event.detail.address;
  navigate("labels");
});
document.addEventListener("open-case", event => navigate("cases", event.detail.id));
document.addEventListener('open-narcotics',event=>navigate('narcotics',event.detail.case_id));
document.addEventListener("open-alert", event => navigate("alerts", event.detail.id));
document.querySelectorAll("[data-workspace]").forEach(button => button.addEventListener("click", () => navigate(button.dataset.workspace)));
navigate("wallet");

document.addEventListener("return-discovery-promotion", () => navigate("discovery", undefined, true));
document.addEventListener('open-discovery-blockchain-graph',event=>{
  navigate('graph',undefined,true);
  document.dispatchEvent(new CustomEvent('wallet-selected',{detail:event.detail}));
});

document.addEventListener("investigate-wallet", event => {investigate(event.detail.chain,event.detail.address);});
