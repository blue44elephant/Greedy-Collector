import {capturePinCard} from './public_source_capture.js';
import {broadSnapshotCard} from './discovery_broad.js';
import {flowCard} from './fund_flow.js';
import {clusterCard} from './clustering.js';
import {openLabel} from "./label_ui.js";
import {caseAttribution} from './case_attribution.js';
import {api} from "./api.js";
import {byId, element, panel, table, shortValue, dateText, details, fields, action, run, UserError, chains} from "./ui.js";
import {investigate} from "./wallet.js";
import {casePath, caseRequest, listCases, openGraph, openAlert} from "./case_actions.js";
import {completionSections,noteEditors,pinNavigation} from './case_completion.js';
import {caseListQuery} from './case_presenter.js';

export function initCases() {
  const host = byId("cases-workspace");
  let selectedId = null;
  let filters = {};
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
  const search=editor('case-search',[
    {name:'q',label:'Search title, wallet or pinned entity/claim name',maxLength:255},
    {name:'status',label:'Status',options:[['','All statuses'],'Open','Paused','Closed']},
    {name:'include_archived',label:'Include archived cases',type:'checkbox'},
    {name:'sort',label:'Sort',options:[['updated','Updated'],['created','Created'],['title','Title'],['status','Status']]}
  ],'Search cases',async data=>{filters=data;await refresh();});
  sidebar.append(search,list,create); layout.append(sidebar,selected); host.append(top,message,layout);
  top.append(button("Refresh cases", refresh));
  async function refresh() {
    const rows = await listCases(caseListQuery(filters));
    list.replaceChildren(element("h2", "Stored cases"));
    if (!rows.length) list.append(element("p", "No cases have been created.", "empty"));
    for (const row of rows) {
      const item = element("article", undefined, "case-list-item");
      const choose = button(row.title, async () => {selectedId=row.id; await loadDetail();});
      choose.dataset.caseId=row.id; choose.setAttribute("aria-pressed", String(row.id === selectedId));
      item.append(choose, element("p", row.description, "prose small"), element("p", row.id, "full-address small"),
        element("p",row.status+(row.archived_at?' · Archived':''),'badge'),
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
    const pins={items:row.sanctions_pins||[]};
    if (pins.items?.length) {
      const section=panel('Pinned OFAC screening','Historical evidence retains the captured source snapshot even after later refreshes.');
      for (const pin of pins.items) {
        const screening=pin.record.screening;
        section.append(element('p',`${screening.listing_state} ? ${screening.match_type} ? ${screening.chain} ? ${screening.address}`),
          element('p',`Captured: ${dateText(pin.captured_at)} ? Snapshot: ${screening.snapshot?.id || 'unavailable'} ? SHA-256: ${screening.snapshot?.sha256 || 'unavailable'}`,'muted small'),
          details('Source associations and programs',screening.associations));
        section.append(details('View pinned sanctions snapshot',pin.record));
        for(const association of screening.associations||[])section.append(action('Open OFAC source record',()=>document.dispatchEvent(new CustomEvent('open-sanctions',{detail:{entity_id:association.entity.source_entity_id,snapshot_id:association.snapshot_id}}))));
      }
      selected.append(section);
    }
    list.querySelectorAll("button").forEach(node => node.setAttribute("aria-pressed", String(node.dataset.caseId === row.id)));
  }
  function render(row) {
    const additions=completionSections(row,{editor,button,reload:loadDetail,refresh});
    const overview = panel(row.title); overview.id="case-overview";
    overview.append(element("p", row.description, "prose"), element("p", `Case ID: ${row.id}`, "full-address"),
      element("p", `Status: ${row.status} · Created: ${dateText(row.created_at)} · Updated: ${dateText(row.updated_at)}`, "muted small"),
      element("p", "Live references open current stored objects. Pinned historical snapshots retain their exact earlier state. Case references do not establish identity or ownership.", "bounded-note"),
      element('p',`Revision ${row.version}${row.archived_at?' · Archived':''}`,'badge'),additions.counts);
    const entities = panel("Entities", "References do not automatically retrieve or expand blockchain history."); entities.id="case-entities";
    for (const reference of row.entities) {
      if(reference.entity_type === 'fund_flow' && reference.metadata_json?.fund_flow_pin) entities.append(flowCard(reference.metadata_json.fund_flow_pin,true));
      if(reference.entity_type === "technical_cluster" && reference.metadata_json?.cluster_pin) entities.append(clusterCard(reference.metadata_json.cluster_pin,true));
    }
    const attachments = row.entities.filter(item => item.entity_type === "attachment");
    for(const kind of [...new Set(row.entities.map(e=>e.entity_type))].filter(k=>!['attachment','entity','attribution_claim','discovery_observation','risk_assessment'].includes(k))){
    const group=panel(kind.replaceAll('_',' '));group.dataset.caseMaterial=kind;
    group.append(table(["Type", "Reference", "Metadata", "Actions"], row.entities.filter(item => item.entity_type===kind).map(item => {
      const controls = element("div", undefined, "toolbar"); const chain=item.metadata_json?.chain;
      if (item.entity_type === "wallet") {
        controls.append(button('Pin stored risk assessment',async()=>{await caseRequest(casePath(row.id)+'/risk-pins',{method:'POST',body:{chain,address:item.entity_ref}});await loadDetail();}));
        controls.append(action("Investigate wallet", () => investigate(chain,item.entity_ref)));
        if (chains.some(([value]) => value === chain)) controls.append(action("Open graph", () => openGraph(chain,item.entity_ref)));
      }
      if (item.entity_type === "label") controls.append(action("Open label", () => openLabel(item.entity_ref)));
      if (item.entity_type === "transaction") controls.append(action("Open transaction", () => investigate(chain,item.entity_ref)));
      controls.append(pinNavigation(item));
      return [item.entity_type, shortValue(item.entity_ref), details("Stored metadata", item.metadata_json), controls];
    }), "No references in this group."));entities.append(group);
    }
    if(!row.entities.length)entities.append(element('p','This Case is empty. Add wallets or transactions here, and pin analytical results from their source workspaces.','empty'));
    entities.append(editor("case-entity", [{name:"entity_type", label:"Entity type", options:["wallet","transaction","label","graph_snapshot"]},
      {name:"entity_ref", label:"Reference", required:true, maxLength:255}, {name:"chain", label:"Chain (wallet or transaction)", options:chains},
      {name:'event_key',label:'Transaction event key (when applicable)',maxLength:160},
      {name:'note',label:'Analyst reference note',type:'textarea'}], "Add entity", async data => {
      let reference=data.entity_ref.trim(), metadata={};
      if (!reference) throw new UserError("Enter an entity reference.");
      if (["wallet","transaction"].includes(data.entity_type)) {
        const resolved=await api("/resolve", {method:"POST",body:{input:reference,chain_hint:data.chain}});
        if (resolved.kind !== (data.entity_type === "wallet" ? "address" : "transaction") || resolved.chain !== data.chain) throw new UserError("The reference does not match the selected entity type and chain. Supported wallet or transaction identifiers are required.");
        reference=resolved.normalized; metadata={chain:resolved.chain,[data.entity_type === "wallet" ? "address" : "tx_hash"]:reference};
      }
      if(data.event_key.trim())metadata.event_key=data.event_key.trim();
      if(data.note.trim())metadata.note=data.note.trim();
      await caseRequest(`${casePath(row.id)}/entities`, {method:"POST",body:{entity_type:data.entity_type,entity_ref:reference,metadata}}); await loadDetail();
    }));
    const alerts = panel("Associated alerts", "Alerts inherit case assignment from their monitoring watch when generated. Assigning a watch does not retroactively move existing alerts."); alerts.id="case-alerts";
    alerts.append(table(["Status", "Severity", "Wallet", "Trigger", "Transaction", "Explanation", "Timestamp (UTC)", "Actions"], row.alerts.map(item => {
      const controls=element("div",undefined,"toolbar"); controls.append(action("Open alert", () => openAlert(item.id)),action("Investigate wallet",()=>investigate(item.chain,item.wallet)));
      if(item.tx_hash) controls.append(action("Open transaction",()=>investigate(item.chain,item.tx_hash)));
      return [item.status,item.severity,shortValue(item.wallet),item.trigger_type,item.tx_hash ? shortValue(item.tx_hash) : "No transaction reference",item.explanation,dateText(item.timestamp),controls];
    }), "No alerts are associated with this case."));
    const notes=panel("Analyst notes"); notes.id="case-notes";
    notes.append(table(["Note", "Author", "Created / updated (UTC)", "Version / state"],row.notes.map(item=>[element("p",item.body,"prose"),item.author,dateText(item.created_at)+' / '+dateText(item.updated_at),item.version+(item.archived_at?' · Archived':'')]),"No analyst notes."));
    notes.append(noteEditors(row,{editor,button,reload:loadDetail}));
    notes.append(editor("case-note",[{name:"body",label:"Note",type:"textarea",required:true}],"Add note",async data=>{
      if(!data.body.trim()) throw new UserError("Enter a note.");
      await caseRequest(`${casePath(row.id)}/notes`,{method:"POST",body:{body:data.body}}); await loadDetail();
    }));
    const files=panel("Attachments", "Immutable local bytes; 20 MiB maximum. Every upload creates a new file. Downloads are attachments, never active previews."); files.id="case-attachments";
    files.append(table(["Original filename", "Content type / size", "SHA-256", "Download"],attachments.map(item=>{
      const m=item.metadata_json,link=element('a','Download attachment');link.href='/api/greedy-collector'+casePath(row.id)+'/attachments/'+encodeURIComponent(item.id);link.download=m.original_filename||m.filename;
      return [m.original_filename||m.filename,m.content_type+' / '+(m.size??'unrecorded')+' bytes',shortValue(m.sha256||'Not recorded before CASE-2'),link];
    }),"No attachments."));
    files.append(editor("case-upload",[{name:"file",label:"Attachment",type:"file",required:true},{name:'note',label:'Attachment note',type:'textarea'}],"Upload attachment",async data=>{
      if (!(data.file instanceof File) || !data.file.name) throw new UserError("Choose an attachment.");
      const filename=data.file.name; // Server creates unique names; preserve original.
      const body=new FormData(); body.append("file",data.file,filename);
      body.append('note',data.note);
      await caseRequest(`${casePath(row.id)}/attachments`,{method:"POST",body}); await loadDetail();
    }));
    const reports=panel("Reports", "Each generation stores a new immutable output of this Case revision and its historical pins. Complete wallet history is not implied."); reports.id="case-reports";
    reports.append(editor("case-report",[{name:"format",label:"Format",options:[["markdown","Markdown"],["html","HTML"],["json","JSON"],["pdf","PDF"]]}],"Download report",async data=>{
      const extension={markdown:"md",html:"html",json:"json",pdf:"pdf"}[data.format];
      if(!extension) throw new UserError("Choose a supported report format.");
      const blob=await caseRequest(`/reports/${encodeURIComponent(row.id)}?format=${data.format}`,{binary:true});
      const url=URL.createObjectURL(blob); const link=element("a"); link.href=url; link.download=`case-${row.id}.${extension}`;
      document.body.append(link); link.click(); link.remove(); setTimeout(()=>URL.revokeObjectURL(url),1000);
      await loadDetail();
    }));
    const broadPins=row.entities.filter(e=>e.entity_type==='broad_discovery'&&e.metadata_json?.broad_discovery_pin).map(e=>broadSnapshotCard(e.metadata_json.broad_discovery_pin));
    const sourceObservations=panel('Source observations','Explicit investigation references; not acceptance of an identity claim.');sourceObservations.id='case-source-observations';
    sourceObservations.append(table(['Source','Wallet',''],row.entities.filter(e=>e.entity_type==='discovery_observation').map(e=>{const m=e.metadata_json||{};return [m.title||m.source_type,m.address,action('Open Discovery observation',()=>document.dispatchEvent(new CustomEvent('open-discovery',{detail:{action:'open_observation',observation_id:e.entity_ref,run_id:m.run_id,result_id:m.result_id}})))];}),'No source observations associated.'));
    const capturePins=row.entities.filter(e=>e.entity_type==='public_source_capture'&&e.metadata_json?.public_source_capture_pin).map(e=>capturePinCard(e.metadata_json.public_source_capture_pin));
    selected.replaceChildren(overview,additions.lifecycle,additions.summary,entities,additions.pins,...broadPins,...capturePins,sourceObservations,caseAttribution(row.id),alerts,notes,files,reports,additions.history,additions.timeline);
  }
  return id => {if(host.dataset.busy === "true") return; if(id) selectedId=id; return perform(refresh);};
}
