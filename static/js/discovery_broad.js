import {captureControl} from './public_source_capture.js';
import {element,table,fields,dateText,UserError} from './ui.js';
import {discoveryRequest as request} from './discovery_api.js';
import {listCases} from './case_actions.js';
import {sourceReference} from './discovery_manual_source.js';

export function broadMatches(group,filters,candidates){
  const obs=group.observations;
  return obs.some(o=>(!filters.provider||o.provider===filters.provider)&&(!filters.category||(o.source_snapshot?.source_category||o.source_class)===filters.category)&&(!filters.review||o.review_status===filters.review)) &&
    (!filters.search||JSON.stringify([group,candidates.filter(c=>obs.some(o=>o.id===c.observation_id))]).toLowerCase().includes(filters.search.toLowerCase()));
}
export function broadAction({chain,address},origin,isCurrent=()=>true){
  const b=element('button','Broad Discovery','secondary');b.type='button';
  b.addEventListener('click',()=>{if(b.isConnected&&isCurrent())document.dispatchEvent(new CustomEvent('open-discovery',{detail:{origin,chain,address,broad:true,isCurrent}}));});return b;
}
export function broadSnapshotCard(snapshot){
  const card=element('details');card.append(element('summary',`Pinned Broad Discovery ${snapshot.run.id}`),element('p','Historical source/review snapshot. Later searches do not change this Case material.'),element('pre',JSON.stringify(snapshot,null,2)));return card;
}
export function renderBroad(host,snapshot,{openResult,perform,reload}){
  host.replaceChildren(element('h2','Broad Discovery results'),element('p','Public metadata and candidate pivots, not verified identity, ownership or source allegations.'),
    element('p',`Exact quoted wallet search: ${snapshot.query.text} | Chain: ${snapshot.query.chain}`),element('p',`Run ${snapshot.run.id} | ${snapshot.run.status} | ${snapshot.groups.length} canonical results | ${snapshot.run.returned_count} observations | Truncated/incomplete: ${snapshot.truncated}`));
  const btn=(label,fn)=>{const b=element('button',label,'secondary');b.type='button';b.addEventListener('click',()=>perform(fn));return b;};
  const filter=element('form',undefined,'editor'),rows=element('div');filter.id='broad-filters';
  const observations=snapshot.groups.flatMap(g=>g.observations),options=key=>[['','All'],...[...new Set(observations.map(key).filter(Boolean))].sort().map(v=>[v,v])];
  filter.append(fields([{name:'search',label:'Search returned metadata locally'}, {name:'provider',label:'Provider',options:options(o=>o.provider)}, {name:'category',label:'Source category',options:options(o=>o.source_snapshot?.source_category||o.source_class)}, {name:'review',label:'Review',options:[['','All'],['unreviewed','Unreviewed'],['relevant','Relevant'],['irrelevant','Irrelevant']]}]));
  filter.addEventListener('submit',e=>e.preventDefault());filter.addEventListener('input',draw);filter.addEventListener('change',draw);
  host.append(filter,rows);
  const groupName=category=>['government/regulator','court/legal','sanctions/watchlist'].includes(category)?'Official / legal sources':['blockchain explorer'].includes(category)?'Crypto intelligence':category==='code repository'?'Code repositories':['news/media','research/report'].includes(category)?'News / research':category==='forum/community'?'Forums / community':'Other web';
  function draw(){
    const filters=Object.fromEntries(new FormData(filter));rows.replaceChildren();const grouped=new Map();
    for(const g of snapshot.groups.filter(g=>broadMatches(g,filters,snapshot.candidates))){const category=g.observations[0].source_snapshot?.source_category||g.observations[0].source_class;const name=groupName(category);if(!grouped.has(name))grouped.set(name,[]);grouped.get(name).push(g);}
    for(const name of [...grouped.keys()].sort()){const section=element('section');section.append(element('h3',name));rows.append(section);
      for(const group of grouped.get(name)){const card=element('article',undefined,'discovery-pivot');card.dataset.broadResult=group.result_ids[0];section.append(card);
        card.append(element('h4',group.observations[0].title),sourceReference(group.canonical_url));
        for(const o of group.observations){const s=o.source_snapshot||{};card.append(element('p',`${o.provider} | ${o.cache_state} | Rank: ${o.rank??'Not returned'} | ${o.review_status} | ${dateText(o.retrieved_at)}`),element('p',s.exact_match===false?'Non-exact search candidate - not wallet evidence':s.exact_match===true?'Exact wallet token present in returned metadata':'Source-specific observation; inspect provenance'),element('blockquote',o.excerpt||o.summary),btn('Inspect / review source',()=>openResult(o.result_id,o.id)));
          if(o.kind==='search_result')card.append(captureControl(o));
          const detail=element('details');detail.append(element('summary','Query, bounds and source quality'),element('pre',JSON.stringify(s,null,2)));card.append(detail);
          for(const c of snapshot.candidates.filter(c=>c.observation_id===o.id)){const view=element('section');view.dataset.candidateId=c.id;view.append(element('p',`${c.kind} candidate: ${c.value} | ${c.material.confidence_type} | ${c.status}`),element('p','Source-bound candidate; no identity claim or automatic follow-up search.'));
            const form=element('form',undefined,'editor');form.append(fields([{name:'status',label:'Candidate relevance',options:['unreviewed','relevant','irrelevant'],value:c.status},{name:'note',label:'Candidate review note',required:true,maxLength:2000}]));const save=element('button','Save candidate review');save.type='submit';form.append(save);
            form.addEventListener('submit',e=>{e.preventDefault();perform(async()=>{await request(`/broad/candidates/${c.id}/review`,{body:{status:form.elements.status.value,note:form.elements.note.value,expected_version:c.version}});await reload();});});view.append(form);card.append(view);
          }
        }
      }
    }
    if(!grouped.size)rows.append(element('p','No results match these local filters.','empty'));
  }
  const pinHost=element('div');host.append(btn('Pin Broad Discovery to Case',async()=>{
    const cases=await listCases();pinHost.replaceChildren();if(!cases.length)throw new UserError('Create a Case first.');
    const form=element('form',undefined,'editor');form.append(fields([{name:'case_id',label:'Case',options:cases.map(c=>[c.id,c.title])}]));const save=element('button','Confirm Broad Discovery pin');save.type='submit';form.append(save);
    form.addEventListener('submit',e=>{e.preventDefault();perform(async()=>{await request(`/broad/cases/${encodeURIComponent(form.elements.case_id.value)}/pin`,{body:{run_id:snapshot.run.id}});pinHost.replaceChildren(element('p','Broad Discovery snapshot pinned.'));});});pinHost.append(form);
  }),pinHost);draw();
}
