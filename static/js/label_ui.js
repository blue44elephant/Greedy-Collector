import {api, ApiError} from "./api.js";
import {element, action, UserError} from "./ui.js";

export const labelTypes = ["Exchange", "Mixer", "Bridge", "Scam", "Sanctioned", "Unknown"];
export const labelChains = [["bitcoin", "Bitcoin"], ["ethereum", "Ethereum"], ["any", "Any (unvalidated address scope)"]];
export async function labelRequest(path, options) {
  try {return await api(path,options);}
  catch(error) {
    if(error instanceof ApiError && error.status === 409) throw new UserError("This label already exists for the same chain, address, name, and source. CSV import can update its type and confidence.");
    if(error instanceof ApiError && error.status === 422) throw new UserError("Check the chain, public address, label type, source, and confidence (0 to 1). CSV requires address,label,type,source,confidence; chain is optional.");
    throw new UserError("The label operation could not be completed. Refresh and try again.");
  }
}
export async function readLabels() {
  const data = await labelRequest("/labels");
  if (!Array.isArray(data?.labels) || !data.labels.every(row => typeof row.id === "string" && typeof row.address === "string" && typeof row.label === "string")) throw new UserError("Unexpected label response. Refresh and try again.");
  return data.labels;
}
export function labelsFor(rows, chain, address) {
  const key = value => chain === "ethereum" ? value.toLowerCase() : value;
  return rows.filter(row => (row.chain === chain || row.chain === "any") && key(row.address) === key(address))
    .sort((a,b) => String(b.last_updated || "").localeCompare(String(a.last_updated || "")) || String(a.id).localeCompare(String(b.id)));
}
export function openLabel(id) {document.dispatchEvent(new CustomEvent("open-label",{detail:{id}}));}
export function sourceNode(source) {
  try {
    const url=new URL(source);
    if (["http:","https:"].includes(url.protocol) && !url.username && !url.password) {
      const link=element("a",source);link.href=url.href;link.target="_blank";link.rel="noopener noreferrer";link.referrerPolicy="no-referrer";return link;
    }
  } catch {}
  return element("span",source);
}
export function labelCards(rows, empty = "") {
  const host=element("div",undefined,"label-cards");
  if(!rows.length) {if(empty) host.append(element("p",empty,"muted small"));return host;}
  for(const row of rows) {
    const card=element("article",undefined,"label-card");
    const head=element("div",undefined,"toolbar");head.append(element("strong",row.label),element("span",row.type,"badge"));
    card.append(head,element("p",row.address,"full-address small"));
    const source=element("p",undefined,"small");source.append(element("span","Source: "),sourceNode(row.source));
    card.append(source,element("p",`Confidence: ${row.confidence} · Chain: ${row.chain || "Not recorded"}`,"muted small"));
    if(row.id)card.append(action("View label details",()=>openLabel(row.id)));
    host.append(card);
  }
  return host;
}
