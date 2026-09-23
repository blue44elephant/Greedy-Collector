import {supportedChain} from './chains.js';
import {api, ApiError} from "./api.js";
import {addCaseAttribution} from './case_attribution.js';
import {element, fields, run, UserError, action} from "./ui.js";

export const casePath = id => `/cases/${encodeURIComponent(id)}`;
export async function caseRequest(path, options) {
  try { return await api(path, options); }
  catch (error) {
    if (error instanceof ApiError) {
      if (error.status === 404) throw new UserError("This case no longer exists. Refresh the case list.");
      if (error.status === 422) throw new UserError("The case operation was not accepted. Check the reference, fields, file, or report format.");
    }
    throw new UserError("The case operation could not be completed. Refresh and try again.");
  }
}
export async function listCases() {
  const data = await caseRequest("/cases");
  if (!Array.isArray(data?.cases) || !data.cases.every(row => typeof row.id === "string" && typeof row.title === "string")) {
    throw new UserError("The server returned an unexpected case list. Refresh and try again.");
  }
  return data.cases;
}
export const caseOptions = rows => [["", "No case"], ...rows.map(row => [row.id, `${row.title} (${row.id})`])];
export function openCase(id) { document.dispatchEvent(new CustomEvent("open-case", {detail:{id}})); }
export function openAlert(id) { document.dispatchEvent(new CustomEvent("open-alert", {detail:{id}})); }
export function openGraph(chain, address) {
  const form = document.querySelector("#graph-workspace form");
  if (form.dataset.busy === "true") throw new UserError("A graph is loading. Wait for it to finish.");
  if (!supportedChain(chain)) throw new UserError("This reference has no supported chain metadata.");
  document.dispatchEvent(new CustomEvent("wallet-selected", {detail:{chain,address}}));
  document.querySelector('[data-workspace="graph"]').click(); form.requestSubmit();
}
export function addToCaseButton(kind, chain, reference, metadata = null) {
  return action("Add to case", async () => {
    if (document.getElementById("case-picker")) return;
    const dialog = element("dialog"); dialog.id = "case-picker";
    dialog.setAttribute("aria-labelledby", "case-picker-title");
    const heading = element("h2", "Add to case"); heading.id = "case-picker-title";
    const form = element("form", undefined, "editor");
    dialog.append(heading, element("p", `${kind} · ${chain}`, "muted small"), element("p", reference, "full-address"), form);
    document.body.append(dialog);
    const close = element("button", "Cancel", "secondary"); close.type = "button";
    close.addEventListener("click", () => dialog.close());
    dialog.addEventListener("close", () => dialog.remove());
    dialog.addEventListener("cancel", event => {if (dialog.dataset.busy === "true") event.preventDefault();});
    form.append(close); dialog.showModal();
    await run(dialog, async () => {
      const cases = await listCases();
      if (!cases.length) {form.prepend(element("p", "No cases have been created. Create a case in Cases, then return here.")); return;}
      form.prepend(fields([{name:"case_id", label:"Target case", options:[["", "Choose a case"], ...caseOptions(cases).slice(1)], required:true}]));
      const save = element("button", "Add reference"); save.type = "submit"; form.append(save);
      form.addEventListener("submit", event => {
        event.preventDefault(); const id = form.elements.case_id.value;
        run(dialog, async () => {
          if(['entity','attribution_claim'].includes(kind))await addCaseAttribution(id,kind,reference,metadata.expected_version);
          else await caseRequest(`${casePath(id)}/entities`, {method:"POST", body:{entity_type:kind, entity_ref:reference,
            metadata:metadata || {chain, [kind === "wallet" ? "address" : "tx_hash"]:reference}}});
          form.replaceChildren(element("p", "Reference added to the selected case."), action("Open case", () => {dialog.close(); openCase(id);}), close);
        }, "Adding reference…");
      });
    }, "Loading cases…");
  });
}
