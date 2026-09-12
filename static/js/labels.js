import {api} from "./api.js";
import {byId, element, panel, table, shortValue, dateText, fields, action, run, UserError} from "./ui.js";
import {investigate} from "./wallet.js";
import {addToCaseButton, openGraph} from "./case_actions.js";
import {readLabels, labelRequest, labelTypes, labelChains, sourceNode} from "./label_ui.js";

export function initLabels() {
  const host=byId("labels-workspace");let rows=[], selectedId=null;
  const top=element("div",undefined,"workspace-heading");top.append(element("h1","Labels"));
  const message=element("p",undefined,"operation-status");message.setAttribute("role","status");
  const note=element("p","A label is a stored analyst/source annotation, not proof of ownership or confirmed attribution. Confidence describes the source annotation; it is not the risk score.","bounded-note");
  const tools=element("div",undefined,"labels-tools");
  const create=panel("Add label");
  const imports=panel("Import / export CSV","Required: address,label,type,source,confidence. Optional: chain (defaults to any). UTF-8 CSV only.");
  const filters=panel("Filter stored labels");
  const filterForm=element("form",undefined,"editor");filterForm.id="labels-filter";
  filterForm.append(fields([{name:"chain",label:"Chain",options:[["","All chains"],...labelChains]}, {name:"type",label:"Type",options:[["","All types"],...labelTypes]}, {name:"search",label:"Label or source text"}]));
  filterForm.addEventListener("submit",event=>event.preventDefault());filterForm.addEventListener("input",renderList);filterForm.addEventListener("change",renderList);filters.append(filterForm);
  const list=panel("Stored labels");list.id="labels-list";
  const detail=panel("Label detail");detail.id="label-detail";detail.hidden=true;
  const perform=(op,pending="Loading labels…")=>run(host,op,pending);
  function button(label,op) {const node=element("button",label,"secondary");node.type="button";node.addEventListener("click",()=>perform(op));return node;}
  function form(id,definitions,submitLabel,op) {
    const node=element("form",undefined,"editor");node.id=id;node.append(fields(definitions));
    const submit=element("button",submitLabel);submit.type="submit";node.append(submit);
    node.addEventListener("submit",event=>{event.preventDefault();const data=Object.fromEntries(new FormData(node));perform(()=>op(data,node),"Saving labels…");});return node;
  }
  create.append(form("label-create",[{name:"chain",label:"Chain",options:labelChains},{name:"address",label:"Public address",required:true,maxLength:128},
    {name:"label",label:"Label",required:true,maxLength:255},{name:"type",label:"Type",options:labelTypes},
    {name:"source",label:"Source",value:"Manual analyst label",required:true,maxLength:255},{name:"confidence",label:"Confidence (0–1)",type:"number",min:0,max:1,step:"any",value:0.7,required:true}],"Save label",async(data,node)=>{
    const address=data.address.trim();
    if(!address || !data.label.trim() || !data.source.trim())throw new UserError("Enter an address, label, and source.");
    if(data.chain!=="any") {
      const resolved=await api("/resolve",{method:"POST",body:{input:address}});
      if(resolved.kind!=="address" || resolved.chain!==data.chain)throw new UserError("The address does not match the selected supported chain.");
    }
    const confidence=Number(data.confidence);
    if(!Number.isFinite(confidence) || confidence<0 || confidence>1)throw new UserError("Confidence must be between 0 and 1.");
    const row=await labelRequest("/labels/manual",{method:"POST",body:{...data,address,confidence}});
    selectedId=row.id;node.reset();node.elements.source.value="Manual analyst label";node.elements.confidence.value="0.7";
    await refresh();
  }));
  create.append(element("p","Manual creation adds a record. The same chain, address, label name, and source cannot be added twice. CSV import updates type/confidence for that exact key; a different source keeps a separate annotation.","muted small"));
  const importResult=element("p",undefined,"muted small");importResult.id="labels-import-result";
  imports.append(form("label-import",[{name:"file",label:"CSV file",type:"file",accept:".csv,text/csv",required:true}],"Import CSV",async data=>{
    const body=new FormData();body.append("file",data.file);
    const response=await labelRequest("/labels/import",{method:"POST",body});
    importResult.textContent=`Processed ${response.imported} CSV rows (creates and updates).`;await refresh();
  }),importResult,button("Export labels",async()=>{
    const blob=await labelRequest("/labels/export",{binary:true});const url=URL.createObjectURL(blob);
    const link=element("a");link.href=url;link.download="greedy_collector_labels.csv";document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }));
  tools.append(create,imports);host.append(top,message,note,tools,filters,list,detail);top.append(button("Refresh labels",refresh));
  function renderDetail(row) {
    selectedId=row.id;detail.hidden=false;detail.replaceChildren(element("h2",row.label),element("p",row.address,"full-address"));
    const metadata=element("dl",undefined,"metadata");
    for(const [name,value] of [["Chain",row.chain],["Type",row.type],["Source",sourceNode(row.source)],["Confidence",String(row.confidence)],["Last updated (UTC)",dateText(row.last_updated)]]) {
      const item=element("div"),dd=element("dd");dd.append(value instanceof Node ? value : element("span",value));item.append(element("dt",name),dd);metadata.append(item);
    }
    const id=element("details");id.append(element("summary","Stored reference"),element("p",row.id,"full-address"));
    const controls=element("div",undefined,"toolbar");controls.append(action("Investigate wallet",()=>investigate(row.chain,row.address)),action("Open graph",async()=>{
      const resolved=await api("/resolve",{method:"POST",body:{input:row.address}});
      if(resolved.kind!=="address")throw new UserError("This annotation does not reference a supported wallet address.");
      if(row.chain!=="any" && resolved.chain!==row.chain)throw new UserError("This stored label has incompatible chain/address metadata.");
      openGraph(resolved.chain,resolved.normalized);
    }),addToCaseButton("label",row.chain,row.id,{chain:row.chain,address:row.address}));
    detail.append(metadata,controls,id,element("p","Labels influence subsequent risk evaluations according to type. Saved risk findings retain their original evidence until a fresh lookup.","muted small"));
  }
  function renderList() {
    const {chain,type,search}=filterForm.elements;const query=search.value.trim().toLowerCase();
    const visible=rows.filter(row=>(!chain.value||row.chain===chain.value)&&(!type.value||row.type===type.value)&&(!query||`${row.label} ${row.source}`.toLowerCase().includes(query)));
    list.replaceChildren(element("h2","Stored labels"),table(["Label","Address","Chain","Type","Source","Confidence","Updated (UTC)","Action"],visible.map(row=>
      [row.label,shortValue(row.address),row.chain,row.type,sourceNode(row.source),String(row.confidence),dateText(row.last_updated),button("View label details",()=>{renderDetail(row);detail.scrollIntoView({block:"start"});})]),rows.length ? "No labels match the current filters." : "No labels have been stored."));
  }
  async function refresh() {
    rows=await readLabels();renderList();
    const selected=rows.find(row=>row.id===selectedId);
    if(selected)renderDetail(selected);else {detail.hidden=true;if(selectedId)throw new UserError("This label reference is no longer available. Refresh the list.");}
  }
  return id=>{if(host.dataset.busy==="true")return;if(id){selectedId=id;filterForm.reset();}return perform(refresh);};
}
