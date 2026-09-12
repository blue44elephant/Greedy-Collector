import {ApiError} from './api.js';

const prefix = '/api/greedy-collector/attribution';
export const encodeId = value => encodeURIComponent(value);
export const caption = value => String(value ?? '').replaceAll('_', ' ').replace(/^./, c => c.toUpperCase());
export const assessments = ['unassessed', 'possible', 'supported', 'strongly_supported', 'rejected'];
export const relationships = ['operated_by', 'controlled_by', 'publicly_declared_by'];
export const entityTypes = ['organization', 'person', 'service', 'protocol', 'public_body', 'online_identity', 'unknown'];
export const stances = ['supports', 'contradicts', 'context'];
export const origins = ['public_osint', 'analyst_added'];
export const evidenceTypes = ['official_disclosure', 'public_record', 'explorer_annotation', 'public_post', 'repository_record', 'analyst_observation'];
export const options = values => values.map(value => [value, caption(value)]);

// These are domain explanations, not arbitrary exception text from a response.
const safeValidation = new Set([
  'This assessment requires active supporting evidence',
  'Supported assessments require direct support with assessed source reliability',
  'Strong support requires reliable direct evidence',
  'Explicitly acknowledge every contradicting evidence link',
  'A concise nonblank reason is required',
]);

export async function request(path, {method = 'GET', body} = {}) {
  if (!path.startsWith('/') || path.startsWith('//')) throw new Error('Invalid local attribution path');
  let response;
  try {
    response = await fetch(prefix + path, {method, headers: body === undefined ? {} : {'Content-Type': 'application/json'},
      ...(body === undefined ? {} : {body: JSON.stringify(body)})});
  } catch { throw new ApiError(0, 'Unable to reach Greedy Collector. Check the local server and reload.'); }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    let message = 'The attribution operation could not be completed. Reload and try again.';
    if (response.status === 404) message = 'This attribution record is no longer available. Reload the list.';
    if (response.status === 409) message = 'This record changed since you loaded it. Reload before applying your update. Also check its archive or withdrawal state.';
    if (response.status === 422) message = safeValidation.has(data?.detail?.message) ? data.detail.message : 'Check the public address, required fields, dates, evidence provenance and assessment requirements.';
    if (response.status === 503) message = data?.detail?.code === 'schema_unavailable'
      ? 'Attribution storage is not initialized for this database. An administrator must prepare the database explicitly. The browser will not migrate it.'
      : 'Attribution storage is temporarily unavailable. Reload and try again.';
    const error = new ApiError(response.status, message);
    if (response.status === 409 && /^[a-f0-9-]{36}$/i.test(data?.detail?.existing_id || '')) {
      error.existingId = data.detail.existing_id;
      if (path === '/claims') {error.duplicateClaim = true; error.message = 'An attribution claim already exists for this subject, relationship, and entity.';}
      else error.message = 'This evidence is already linked to the claim. Inspect or restore the existing link.';
    }
    throw error;
  }
  if (!data || typeof data !== 'object' || Array.isArray(data)) throw new ApiError(500, 'Unexpected attribution response. Reload and try again.');
  return data;
}

export async function readPage(path, filters = {}, offset = 0, limit = 20) {
  const query = new URLSearchParams({limit: String(limit), offset: String(offset)});
  for (const [key, value] of Object.entries(filters)) if (value !== '' && value != null) query.set(key, String(value));
  const data = await request(`${path}?${query}`);
  if (!Array.isArray(data.items) || !Number.isInteger(data.total) || !Number.isInteger(data.offset)
      || !Number.isInteger(data.limit) || !(data.next_offset === null || Number.isInteger(data.next_offset))) {
    throw new ApiError(500, 'Unexpected attribution page. Reload and try again.');
  }
  return data;
}
