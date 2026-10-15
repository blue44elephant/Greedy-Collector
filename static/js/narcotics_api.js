import {ApiError,API} from './api.js';
export const narcoticsPath=(caseId,suffix='')=>'/cases/'+encodeURIComponent(caseId)+suffix;
export async function narcoticsRequest(path,{method='GET',body}={}) {
  let response;
  try {response=await fetch(API+'/narcotics'+path,{method,headers:{'Content-Type':'application/json'},...(body===undefined?{}:{body:JSON.stringify(body)})});}
  catch {throw new ApiError(0,'Unable to reach local Narcotics intelligence storage.');}
  const value=await response.json().catch(()=>null);
  if(!response.ok)throw new ApiError(response.status,({404:'The selected Case, reference, or analysis is unavailable.',409:'The Case is archived or material changed. Reload before saving or reviewing.',422:'Check the structured fields, controlled values, timezone timestamps, and Case-scoped source references.',503:'Narcotics intelligence storage requires the NARC-1 migration.'})[response.status]||'Narcotics intelligence request failed.');
  return value;
}
