import {api} from "./api.js";
import {byId, element, panel, table, shortValue, dateText, details, fields, action, run, UserError, chains} from "./ui.js";
import {investigate} from "./wallet.js";
import {casePath, caseRequest, listCases, openGraph, openAlert} from "./case_actions.js";

export function initCases() {
  const host = byId("cases-workspace");
  let selectedId = null;
  const top = element("div", undefined, "workspace-heading"); top.append(element("h1", "Cases"));
  const message = element("p", undefined, "operation-status"); message.setAttribute("role", "status");
  const layout = element("div", undefined, "cases-layout");
  const sidebar = element("aside");
  const list = panel("Stored cases"); list.id = "cases-list";
  const selected = element("div"); selected.id = "case-detail";
  const perform = (op, pending) => run(host, op, pending || "Loading case material…");
  function button(label, op) {const node = element("button", label, "secondary"); node.type="button"; node.addEventListener("click", () => perform(op)); return node;}
  function editor(id, defs, label, op) {
    const form = element("form", undefined, "editor"); form.id=id; form.append(fields(defs));
    const save = element("button", label); save.type="submit"; form.append(save);
    form.addEventListener("submit", event => {event.preventDefault(); const data=Object.fromEntries(new FormData(form)); perform(() => op(data,form), "Saving case material…");});
    return form;
  }
  const create = panel("Create case");
  create.append(editor("case-create", [{name:"title", label:"Title", required:true, maxLength:255}, {name:"description", label:"Description", type:"textarea"}], "Create case", async (data, form) => {
    if (!data.title.trim()) throw new UserError("Enter a case title.");
    const row = await caseRequest("/cases", {method:"POST", body:{title:data.title.trim(),description:data.description}});
    selectedId=row.id; form.reset(); await refresh();
  }));
  sidebar.append(list,create); layout.append(sidebar,selected); host.append(top,message,layout);
  top.append(button("Refresh cases", refresh));
  async function refresh() {
    const rows = await listCases();
    list.replaceChildren(element("h2", "Stored cases"));
    if (!rows.length) list.append(element("p", "No cases have been created.", "empty"));
    for (const row of rows) {
      const item = element("article", undefined, "case-list-item");
      const choose = button(row.title, async () => {selectedId=row.id; await loadDetail();});
      choose.dataset.caseId=row.id; choose.setAttribute("aria-pressed", String(row.id === selectedId));
      item.append(choose, element("p", row.description, "prose small"), element("p", row.id, "full-address small"),
        element("p", `Created: ${dateText(row.created_at)} · Updated: ${dateText(row.updated_at)}`, "muted small")); list.append(item);
    }
    if (selectedId) await loadDetail();
    else selected.replaceChildren(panel("Case material", "Open a stored case or create one to organize analyst-selected references."));
  }
  async function loadDetail() {
    selected.replaceChildren();
    const row = await caseRequest(casePath(selectedId));
    if (!row || ![row.entities,row.notes,row.alerts].every(Array.isArray)) throw new UserError("The server returned unexpected case material. Refresh and try again.");
    render(row);
    list.querySelectorAll("button").forEach(node => node.setAttribute("aria-pressed", String(node.dataset.caseId === row.id)));
  }
  function render(row) {
    const overview = panel(row.title); overview.id="case-overview";
    overview.append(element("p", row.description, "prose"), element("p", `Case ID: ${row.id}`, "full-address"),
      element("p", `Status: ${row.status} · Created: ${dateText(row.created_at)} · Updated: ${dateText(row.updated_at)}`, "muted small"),
      element("p", "Cases organize analyst-selected references. References do not establish identity or ownership. Updated time is the stored case timestamp, not a latest-evidence timestamp.", "bounded-note"));
    const entities = panel("Entities", "References do not automatically retrieve or expand blockchain history."); entities.id="case-entities";
    const attachments = row.entities.filter(item => item.entity_type === "attachment");
    entities.append(table(["Type", "Reference", "Metadata", "Actions"], row.entities.filter(item => item.entity_type !== "attachment").map(item => {
      const controls = element("div", undefined, "toolbar"); const chain=item.metadata_json?.chain;
      if (item.entity_type === "wallet") {
        controls.append(action("Investigate wallet", () => investigate(chain,item.entity_ref)));
        if (chains.some(([value]) => value === chain)) controls.append(action("Open graph", () => openGraph(chain,item.entity_ref)));
      }
      if (item.entity_type === "transaction") controls.append(action("Open transaction", () => investigate(chain,item.entity_ref)));
      return [item.entity_type, shortValue(item.entity_ref), details("Stored metadata", item.metadata_json), controls];
    }), "No entities have been added to this case."));
    entities.append(editor("case-entity", [{name:"entity_type", label:"Entity type", options:["wallet","transaction","label","graph_snapshot"]},
      {name:"entity_ref", label:"Reference", required:true, maxLength:255}, {name:"chain", label:"Chain (wallet or transaction)", options:chains}], "Add entity", async data => {
      let reference=data.entity_ref.trim(), metadata={};
      if (!reference) throw new UserError("Enter an entity reference.");
      if (["wallet","transaction"].includes(data.entity_type)) {
        const resolved=await api("/resolve", {method:"POST",body:{input:reference}});
        if (resolved.kind !== (data.entity_type === "wallet" ? "address" : "transaction") || resolved.chain !== data.chain) throw new UserError("The reference does not match the selected entity type and chain. Supported wallet or transaction identifiers are required.");
        reference=resolved.normalized; metadata={chain:resolved.chain,[data.entity_type === "wallet" ? "address" : "tx_hash"]:reference};
      }
      await caseRequest(`${casePath(row.id)}/entities`, {method:"POST",body:{entity_type:data.entity_type,entity_ref:reference,metadata}}); await loadDetail();
    }));
    const alerts = panel("Associated alerts", "Alerts inherit case assignment from their monitoring watch when generated. Assigning a watch does not retroactively move existing alerts."); alerts.id="case-alerts";
    alerts.append(table(["Status", "Severity", "Wallet", "Trigger", "Transaction", "Explanation", "Timestamp (UTC)", "Actions"], row.alerts.map(item => {
      const controls=element("div",undefined,"toolbar"); controls.append(action("Open alert", () => openAlert(item.id)),action("Investigate wallet",()=>investigate(item.chain,item.wallet)));
      if(item.tx_hash) controls.append(action("Open transaction",()=>investigate(item.chain,item.tx_hash)));
      return [item.status,item.severity,shortValue(item.wallet),item.trigger_type,item.tx_hash ? shortValue(item.tx_hash) : "No transaction reference",item.explanation,dateText(item.timestamp),controls];
    }), "No alerts are associated with this case."));
    const notes=panel("Analyst notes"); notes.id="case-notes";
    notes.append(table(["Note", "Author", "Created (UTC)", "ID"],row.notes.map(item=>[element("p",item.body,"prose"),item.author,dateText(item.created_at),shortValue(item.id)]),"No analyst notes."));
    notes.append(editor("case-note",[{name:"body",label:"Note",type:"textarea",required:true}],"Add note",async data=>{
      if(!data.body.trim()) throw new UserError("Enter a note.");
      await caseRequest(`${casePath(row.id)}/notes`,{method:"POST",body:{body:data.body}}); await loadDetail();
    }));
    const files=panel("Attachments", "Files are stored locally and listed by reference. Downloads and previews are not available. Unique filename prefixes preserve earlier uploads."); files.id="case-attachments";
    files.append(table(["Filename", "Content type", "Stored reference"],attachments.map(item=>[item.metadata_json?.filename,item.metadata_json?.content_type,shortValue(item.entity_ref)]),"No attachments."));
    files.append(editor("case-upload",[{name:"file",label:"Attachment",type:"file",required:true}],"Upload attachment",async data=>{
      if (!(data.file instanceof File) || !data.file.name) throw new UserError("Choose an attachment.");
      const filename=`${crypto.randomUUID()}-${data.file.name.replace(/[^A-Za-z0-9._-]/g,"_").slice(-150)}`;
      const body=new FormData(); body.append("file",data.file,filename);
      await caseRequest(`${casePath(row.id)}/attachments`,{method:"POST",body}); await loadDetail();
    }));
    const reports=panel("Reports", "Reports summarize the current stored case, entity references, alerts, and notes. They do not automatically include complete wallet histories or expand attachments."); reports.id="case-reports";
    reports.append(editor("case-report",[{name:"format",label:"Format",options:[["markdown","Markdown"],["html","HTML"],["json","JSON"],["pdf","PDF"]]}],"Download report",async data=>{
      const extension={markdown:"md",html:"html",json:"json",pdf:"pdf"}[data.format];
      if(!extension) throw new UserError("Choose a supported report format.");
      const blob=await caseRequest(`/reports/${encodeURIComponent(row.id)}?format=${data.format}`,{binary:true});
      const url=URL.createObjectURL(blob); const link=element("a"); link.href=url; link.download=`case-${row.id}.${extension}`;
      document.body.append(link); link.click(); link.remove(); setTimeout(()=>URL.revokeObjectURL(url),1000);
    }));
    selected.replaceChildren(overview,entities,alerts,notes,files,reports);
  }
  return id => {if(host.dataset.busy === "true") return; if(id) selectedId=id; return perform(refresh);};
}
