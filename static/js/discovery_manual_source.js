import {element,panel,table,fields,dateText,action,run,UserError} from './ui.js';
import {discoveryRequest as request} from './discovery_api.js';
import {api} from './api.js';

export function sourceReference(value) {
  if(!value)return element('span','No URL supplied');
  try {
    const url=new URL(value);
    if(!['http:','https:'].includes(url.protocol)||url.username||url.password||[...url.searchParams.keys()].some(k=>/key|token|session|cookie|secret|password|signature|authorization/i.test(k)))return element('span','Unsafe source link withheld');
    if(url.hostname.toLowerCase().replace(/\.$/,'').endsWith('.onion')) {
      const box=element('div');
      box.append(element('p','Onion source — GC does not fetch/open this source.'),element('span',value,'full-address'),action('Copy source URL',async()=>{
        try{await navigator.clipboard.writeText(value);}catch{throw new UserError('Copy the displayed source URL manually.');}
      }));return box;
    }
    const link=element('a',value);link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';link.referrerPolicy='no-referrer';return link;
  }catch{return element('span',value);}
}

export function manualSourceDetail(values,capturedAt) {
  const box=element('section',undefined,'manual-source-detail');
  box.append(element('h3','Manual analyst capture'),element('p','The analyst recorded that this source referenced the wallet. GC did not fetch or independently verify the source. This does not establish source/operator ownership or common ownership.','bounded-note'),
    table(['Field','Captured value'],[['Wallet',`${values.subject?.chain} · ${values.subject?.address}`],['Source type',values.source_type],['Title',values.title],['Marketplace / service',values.service_name],['Vendor / account alias (metadata only)',values.alias],['Source reference',values.source_reference],['Observed at',dateText(values.observed_at)],['Captured at',dateText(capturedAt)],['Analyst note',values.analyst_note]]),
    sourceReference(values.source_url),element('h4','Quoted context'),element('blockquote',values.context));
  if(values.entered_source_url && values.entered_source_url!==values.source_url)box.append(element('p',`Entered source: ${values.entered_source_url}`,'full-address'));
  box.append(table(['Attachment reference','Filename','SHA-256','MIME','Bytes'],(values.attachments||[]).map(a=>[a.reference,a.filename,a.sha256,a.content_type,a.byte_size]),'No attachment references.'),element('p','Attachment references and hashes are analyst supplied. GC has not received, hashed or verified file bytes.','muted small'));
  return box;
}

export function manualSourceAction(wallet,isCurrent=()=>true) {
  return action('Record source observation',()=>{
    if(!isCurrent())throw new UserError('The wallet view has changed. Open it again.');
    document.dispatchEvent(new CustomEvent('open-discovery',{detail:{...wallet,origin:'wallet',action:'manual_source'}}));
  });
}

export function manualSourceForm(wallet,onCaptured) {
  const host=panel('Record source observation','Manual · FREE_LOCAL · No network. Opening this form and previewing create no records.');host.id='manual-source-capture';
  host.append(element('p',`${wallet.chain} · ${wallet.address}`,'full-address'),element('p','Never paste passwords, cookies, authorization headers, session tokens or local file paths. Use a URL or a stable exhibit/source reference.','bounded-note'));
  const form=element('form',undefined,'editor');form.id='manual-source-form';
  form.append(fields([
    {name:'source_type',label:'Source type',options:['webpage','marketplace_listing','marketplace_vendor_page','forum_post','document','other']},
    {name:'source_url',label:'Source URL (optional HTTP/HTTPS, including inert onion)',maxLength:2048},
    {name:'source_reference',label:'Stable source reference (required without a URL)',maxLength:200},
    {name:'title',label:'Page / listing title',maxLength:255},{name:'service_name',label:'Marketplace / service name (optional)',maxLength:200},
    {name:'alias',label:'Vendor / account alias (metadata only)',maxLength:200},
    {name:'observed_at',label:'Observed at (your local timezone)',type:'datetime-local',required:true},
    {name:'context',label:'Quoted / surrounding context',type:'textarea',required:true,maxLength:4000},
    {name:'analyst_note',label:'Analyst note / rationale',type:'textarea',required:true,maxLength:2000},
    {name:'case_id',label:'Existing Case ID (optional)',maxLength:36},
  ]));
  const caseList=element('div');caseList.append(action('Choose existing Case',async()=>{
    const rows=await api('/cases');
    caseList.replaceChildren(table(['Case','Status',''],rows.map(c=>[c.title,c.status,action('Select Case',()=>{form.elements.case_id.value=c.id;invalidate();})]),'No existing Cases.'));
  }));form.append(caseList);
  const attachments=element('details');attachments.append(element('summary','Attachment reference (optional; no upload)'),element('p','Supply an exhibit reference and known SHA-256. GC does not read or verify the file.','muted small'),fields([
    {name:'attachment_reference',label:'Exhibit reference',maxLength:200},{name:'attachment_sha256',label:'SHA-256',maxLength:64},
    {name:'attachment_filename',label:'Original filename (no path)',maxLength:200},{name:'attachment_content_type',label:'MIME type',maxLength:100},
    {name:'attachment_byte_size',label:'Byte size',type:'number',min:0,max:1073741824,step:1},
  ]));form.append(attachments);
  const previewButton=element('button','Preview observation');previewButton.type='submit';form.append(previewButton);
  const preview=element('section');preview.id='manual-source-preview';
  let payload=null,checked=null;
  function invalidate(){payload=checked=null;preview.replaceChildren();}
  form.addEventListener('input',invalidate);form.addEventListener('change',invalidate);
  form.addEventListener('submit',event=>{
    event.preventDefault();const data=Object.fromEntries(new FormData(form));
    run(host,async()=>{
      invalidate();const date=new Date(data.observed_at);if(!data.observed_at||Number.isNaN(date.getTime()))throw new UserError('Enter the time the material was observed.');
      payload={subject:{...wallet},source_type:data.source_type,observed_at:date.toISOString(),context:data.context,analyst_note:data.analyst_note,attachments:[]};
      for(const key of ['source_url','source_reference','title','service_name','alias','case_id'])payload[key]=data[key]||null;
      if(Object.keys(data).some(k=>k.startsWith('attachment_')&&data[k]))payload.attachments.push({reference:data.attachment_reference,sha256:data.attachment_sha256,filename:data.attachment_filename||null,content_type:data.attachment_content_type||null,byte_size:data.attachment_byte_size===''?null:Number(data.attachment_byte_size)});
      checked=await request('/manual-source/preview',{body:payload});
      preview.append(element('h3','Preview — nothing has been saved'),manualSourceDetail(checked.capture),element('p',checked.notice),element('p',`Case: ${checked.case_id||'No association'}`));
      const confirm=element('button','Confirm capture');confirm.type='button';confirm.addEventListener('click',()=>run(host,async()=>{
        if(!checked||!payload)throw new UserError('Preview the current fields before capture.');
        const saved=await request('/manual-source/capture',{body:{capture:payload,expected_preview_fingerprint:checked.preview_fingerprint}});
        invalidate();host.replaceChildren(element('h2',saved.duplicate?'Existing capture retained':'Source observation captured'),element('p',saved.duplicate?'The existing observation and its review history are retained.':'New material starts Unreviewed. Review and Attribution promotion are separate explicit actions.'),element('p',`Captured at ${dateText(saved.captured_at)}`));
        await onCaptured(saved);
      }));preview.append(confirm);
    });
  });
  host.append(form,preview);return host;
}
