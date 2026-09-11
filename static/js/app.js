import {byId} from "./ui.js";
import {initWallet} from "./wallet.js";
import {initGraph} from "./graph.js";

function navigate(name) {
  if (!byId(`${name}-workspace`)) return;
  document.querySelectorAll(".workspace").forEach(node => { node.hidden = node.id !== `${name}-workspace`; });
  document.querySelectorAll("[data-workspace]").forEach(node => { node.setAttribute("aria-current", String(node.dataset.workspace === name)); });
}
initWallet(navigate);
initGraph();
document.querySelectorAll("[data-workspace]").forEach(button => button.addEventListener("click", () => navigate(button.dataset.workspace)));
navigate("wallet");
