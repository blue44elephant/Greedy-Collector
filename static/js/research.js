import {api, ApiError} from "./api.js";
import {evidenceHandoffButton} from './attribution_handoff.js';
import {byId, element, panel, table, fields, details, run, UserError} from "./ui.js";

const statuses=["Unreviewed","Potential match","False positive","Confirmed source match"];
function sourceLink(value) {
  if(!value)return element("span","No source URL returned");
  try {
    const url=new URL(value);
    const secretNames=/^(api[_-]?key|key|token|access[_-]?token|authorization|password|secret|signature|x-amz-signature)$/i;
    if(!["https:","http:"].includes(url.protocol)||url.username||url.password||[...url.searchParams.keys()].some(key=>secretNames.test(key)))return element("span","Source URL withheld because it is unsafe to open.");
    const link=element("a",value);link.href=url.href;link.target="_blank";link.rel="noopener noreferrer";link.referrerPolicy="no-referrer";return link;
  } catch {return element("span","No usable source URL returned");}
}
async function request(path, options) {
  try {return await api(path,options);}
  catch(error) {
    if(error instanceof ApiError && error.status===404)throw new UserError("This research match is no longer available.");
    if(error instanceof ApiError && error.status===422)throw new UserError("Check the name, domain (without a URL, path, or port), and selected review status.");
    if(error instanceof ApiError && [429,502,503,504].includes(error.status))throw new UserError("Research is temporarily unavailable or rate limited. Try again later.");
    throw new UserError("The research operation could not be completed. Try again.");
  }
}
function validMatch(row) {
  return row && ["id","source","subject_name","match_rationale","review_status"].every(key=>typeof row[key]==="string") && typeof row.match_score==="number" && Array.isArray(row.categories) && row.source_data && typeof row.source_data==="object";
}

export function initResearch() {
  const host=byId("research-workspace");let sources=[],current=null,selectedId=null,loaded=false;
  const top=element("div",undefined,"workspace-heading");top.append(element("h1","Research"),element("span","Public records & screening","muted"));
  const message=element("p",undefined,"operation-status");message.setAttribute("role","status");
  const queryPanel=panel("Research query","Submit a name; optionally add a domain for certificate, public scan, and reputation sources. Research does not identify wallet owners or create wallet labels.");
  const form=element("form",undefined,"editor");form.id="research-query";
  form.append(fields([{name:"name",label:"Name",required:true,maxLength:255},{name:"domain",label:"Domain (optional)",maxLength:253},{name:"include_manual_sources",label:"Include manual research links",type:"checkbox",value:true}]));
  const submit=element("button","Run research");submit.type="submit";form.append(submit);queryPanel.append(form);
  const capabilities=panel("Source capabilities","Configuration indicates credential availability, not provider reachability. Research only runs when you submit the form.");capabilities.id="research-capabilities";
  const coverage=panel("Current research run");coverage.id="research-coverage";coverage.hidden=true;
  const matches=panel("Automated matches","Match score is case-insensitive text similarity (0–1), not identity probability, domain safety, or wallet risk. Some domain results compare the queried domain to itself and therefore score 1.");matches.id="research-matches";
  matches.append(element("p","Run a query to retrieve available public records.","empty"));
  const unavailable=panel("Unavailable sources");unavailable.id="research-unavailable";unavailable.hidden=true;
  const manual=panel("Manual research","These links were generated for analyst use. Greedy Collector has not queried these services.");manual.id="research-manual";manual.hidden=true;
  const detail=panel("Match detail");detail.id="research-detail";detail.hidden=true;
  const limitation=element("p","Previous research-run browsing is not currently exposed. Runs and match reviews are persisted, but this workspace keeps only the current result in this browser page. Copy useful results before closing or reloading the page.","bounded-note");
  host.append(top,message,queryPanel,capabilities,coverage,matches,detail,unavailable,manual,limitation);
  const perform=(op,pending="Loading research capabilities…")=>run(host,op,pending);
  function button(label,op) {const node=element("button",label,"secondary");node.type="button";node.addEventListener("click",()=>perform(op,label));return node;}
  const name=id=>sources.find(source=>source.id===id)?.name || id;
  const category=id=>sources.find(source=>source.id===id)?.category || "Not available";
  top.append(button("Refresh capabilities",loadCapabilities));
  async function loadCapabilities() {
    const response=await request("/kyc/sources");
    if(!Array.isArray(response?.sources))throw new UserError("Unexpected source capability response. Refresh and try again.");
    sources=response.sources;loaded=true;
    capabilities.replaceChildren(element("h2","Source capabilities"),element("p","Configured credentials do not guarantee provider availability. Manual sources are links only.","muted small"));
    const catalog=element("details");catalog.append(element("summary",`${sources.length} sources: ${sources.filter(source=>source.mode==="api").length} automated, ${sources.filter(source=>source.mode==="manual").length} manual — inspect capabilities`));
    catalog.append(table(["Source","Category","Mode","Credentials","Inputs used"],sources.map(source=>[
      source.name,source.category,source.mode==="manual"?"Manual research link":"Automated",
      source.credential_configured===null?"No API key required":source.credential_configured?"Configured":source.credential_required?"Not configured — credential required":"Not configured — public mode available",
      source.input_fields.length?source.input_fields.join(", "):"Fixed portal; no query inserted",
    ])));capabilities.append(catalog);
  }
  form.addEventListener("submit",event=>{
    event.preventDefault();const payload=Object.fromEntries(new FormData(form));
    perform(async()=>{
      const queryName=payload.name.trim();if(queryName.length<2)throw new UserError("Enter a name of at least two characters.");
      const domain=payload.domain.trim();
      if(domain && (/[\s/:@?#]/.test(domain)||!domain.includes(".")))throw new UserError("Enter a domain name without a URL, path, or port.");
      const result=await request("/kyc/screen",{method:"POST",body:{name:queryName,domain:domain||null,include_manual_sources:payload.include_manual_sources==="on"}});
      if(!result || !Array.isArray(result.matches) || !result.matches.every(validMatch) || ![result.checked_sources,result.unavailable_sources,result.manual_sources].every(Array.isArray))throw new UserError("Unexpected research response. The previous successful result remains available.");
      current=result;selectedId=null;detail.hidden=true;renderResults();
    },"Running research across available sources…");
  });
  function renderResults() {
    coverage.hidden=false;coverage.replaceChildren(element("h2","Current research run"),element("p",`${current.query.name}${current.query.domain ? " · " + current.query.domain : ""}`,"prose"));
    const ref=element("details");ref.append(element("summary","Run reference"),element("p",current.run_id,"full-address"));coverage.append(ref);
    coverage.append(element("p",`Successfully checked: ${current.checked_sources.length} · Automated matches: ${current.matches.length} · Unavailable: ${current.unavailable_sources.length} · Manual links: ${current.manual_sources.length}`,"muted small"));
    coverage.append(table(["Successfully checked source"],current.checked_sources.map(row=>[name(row.id)]),"No sources completed successfully."));
    if(!current.query.domain)coverage.append(element("p",`Not run — no domain supplied: ${sources.filter(source=>source.domain_required).map(source=>source.name).join(", ")}.`,"muted small"));
    coverage.append(element("p",current.disclaimer || "Public-record matches do not establish identity or wallet ownership.","bounded-note"));
    matches.replaceChildren(element("h2","Automated matches"),element("p","Match score is case-insensitive text similarity (0–1), not identity probability, wallet risk, or domain safety. Domain results may compare the domain to itself and score 1.","muted small"));
    matches.append(table(["Source","Subject","Match score (0–1)","Categories","Review status","Action"],current.matches.map(row=>[
      name(row.source),row.subject_name,String(row.match_score),row.categories.join(", "),row.review_status,button("View match",()=>{renderDetail(row);detail.scrollIntoView({block:"start"});}),
    ]),"No automated matches were returned."));
    unavailable.hidden=current.unavailable_sources.length===0;
    unavailable.replaceChildren(element("h2","Unavailable sources"),table(["Source","Reason"],current.unavailable_sources.map(row=>[name(row.id),String(row.reason).includes("API_KEY is not configured")?"Required optional credential is not configured.":"Source unavailable. Check server configuration or try again later."])));
    manual.hidden=current.manual_sources.length===0;
    manual.replaceChildren(element("h2","Manual research"),element("p","Links only: Greedy Collector has not queried these services.","muted small"),table(["Source","Category","Research link","Note"],current.manual_sources.map(row=>[row.name,row.category,sourceLink(row.url),row.note])));
    const selected=current.matches.find(row=>row.id===selectedId);if(selected)renderDetail(selected);
  }
  function renderDetail(row) {
    selectedId=row.id;detail.hidden=false;
    detail.replaceChildren(element("h2",row.subject_name),element("p",`${name(row.source)} · ${category(row.source)} · Match score ${row.match_score} / 1`),sourceLink(row.source_url),
      element("h3","Rationale"),element("p",row.match_rationale,"prose"),element("p",`Categories: ${row.categories.join(", ") || "None returned"}`),details("Source evidence",row.source_data));
    detail.append(element("p","Confirmed source match records an analyst assessment of the researched subject and source record. It does not confirm ownership of a blockchain wallet.","bounded-note"));
    if(row.id && sources.some(source=>source.id===row.source&&source.mode==='api'))detail.append(evidenceHandoffButton('research',row.id));
    const review=element("form",undefined,"editor");review.id="research-review";review.append(fields([{name:"review_status",label:"Analyst review",options:statuses,value:row.review_status}]));
    const save=element("button","Save review");save.type="submit";review.append(save);
    review.addEventListener("submit",event=>{
      event.preventDefault();const review_status=review.elements.review_status.value;
      perform(async()=>{
        const updated=await request(`/kyc/matches/${encodeURIComponent(row.id)}`,{method:"PATCH",body:{review_status}});
        if(!validMatch(updated))throw new UserError("Unexpected review response. Do not assume the update succeeded.");
        current.matches=current.matches.map(item=>item.id===updated.id?updated:item);renderResults();
      },"Saving analyst review…");
    });
    const copy=element("textarea");copy.readOnly=true;copy.hidden=true;copy.setAttribute("aria-label","Result text to copy");
    detail.append(review,element("p","Cases currently have no research-match entity type. Copy the result and add an analyst note manually; it is not automatically linked to a case or wallet.","muted small"),button("Copy result",async()=>{
      const value=JSON.stringify({run_id:current.run_id,...row},null,2);
      try {await navigator.clipboard.writeText(value);}
      catch {copy.value=value;copy.hidden=false;copy.focus();copy.select();}
    }),copy);
  }
  return ()=>loaded?Promise.resolve():perform(loadCapabilities);
}
