import {byId} from "./ui.js";
import {initWallet} from "./wallet.js";
import {initGraph} from "./graph.js";
import {initMonitoring} from "./monitoring.js";
import {initAlerts} from "./alerts.js";
import {initCases} from "./cases.js";
import {initLabels} from "./labels.js";
import {initResearch} from "./research.js";

function navigate(name, id) {
  if (!byId(`${name}-workspace`)) return;
  document.querySelectorAll(".workspace").forEach(node => { node.hidden = node.id !== `${name}-workspace`; });
  document.querySelectorAll("[data-workspace]").forEach(node => { node.setAttribute("aria-current", String(node.dataset.workspace === name)); });
  if (name === "monitoring") loadMonitoring();
  if (name === "alerts") loadAlerts(id);
  if (name === "cases") loadCases(id);
  if (name === "labels") loadLabels(id);
  if (name === "research") loadResearch();
}
initWallet(navigate);
initGraph();
const loadMonitoring = initMonitoring();
const loadAlerts = initAlerts(navigate);
const loadCases = initCases();
const loadLabels = initLabels();
const loadResearch = initResearch();
document.addEventListener("open-label", event => navigate("labels", event.detail.id));
document.addEventListener("open-case", event => navigate("cases", event.detail.id));
document.addEventListener("open-alert", event => navigate("alerts", event.detail.id));
document.querySelectorAll("[data-workspace]").forEach(button => button.addEventListener("click", () => navigate(button.dataset.workspace)));
navigate("wallet");
