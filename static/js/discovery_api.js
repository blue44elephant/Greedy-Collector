import {UserError} from './ui.js';

const messages = {
  promotion_schema_unavailable: 'Discovery promotion storage is not initialized for this database.',
  attribution_schema_unavailable: 'Attribution storage is not initialized for this database.',
  promotion_conflict: 'This observation was already promoted, or the preview or claim changed. Reload and review before confirming; no automatic retry was made.',
  promotion_ineligible: 'Promotion requires a Relevant review of this material, a claim for the exact wallet, and valid stance, directness and rationale.',
  schema_unavailable: 'Discovery storage is not initialized for this database.',
  storage_unavailable: 'Discovery storage is temporarily unavailable. Try again later.',
  conflict: 'Discovery conflict: reload the record or make a fresh plan. Another run may be active, or the plan or record version has changed.',
  not_found: 'This Discovery run, result or observation is no longer available.',
  invalid_request: 'Check the supported wallet address, selected pivots, budget and review fields.',
  origin_rejected: 'Discovery requests must use this application’s local origin.',
};
export async function discoveryRequest(path, {body, key, signal} = {}) {
  if (!/^\/(sources|transforms|plan|runs|results|observations|manual-source)(\/|\?|$)/.test(path) || path.includes('..')) throw new UserError('Unsupported Discovery operation.');
  const headers = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (key) headers['Idempotency-Key'] = key;
  let response;
  try {
    response = await fetch('/api/greedy-collector/discovery' + path, {method:body === undefined ? 'GET' : 'POST', headers, body:body === undefined ? undefined : JSON.stringify(body), signal});
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new UserError('Unable to reach Greedy Collector. Check the local server.');
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    if(path.startsWith('/manual-source/') && data?.detail?.code==='invalid_request')throw new UserError('Check the source URL/reference, observed time, context and analyst note. Remove credentials, session headers and local paths; respect the displayed length limits.');
    throw new UserError(messages[data?.detail?.code] || 'The Discovery operation could not be completed. Try again.');
  }
  if (data === null) throw new UserError('Unexpected Discovery response. Reload and try again.');
  return data;
}

// UI refresh only. Lifecycle decisions and deadlines remain on the server.
export function activeRun(row) { return ['queued', 'running'].includes(row?.status); }
export function createRunPoller({read, receive, error, paused, delay = 1500, limit = 80, schedule = setTimeout, unschedule = clearTimeout}) {
  let timer, controller, generation = 0;
  function stop() { generation++; unschedule(timer); controller?.abort(); }
  function start(id) {
    stop(); const token = generation; let count = 0;
    const next = () => { timer = schedule(async () => {
      controller = new AbortController();
      try {
        const row = await read(id, controller.signal);
        if (token !== generation) return;
        await receive(row);
        if (token !== generation || !activeRun(row)) return;
        if (++count >= limit) paused(); else next();
      } catch (e) { if (token === generation && e.name !== 'AbortError') error(e); }
    }, delay); };
    next();
  }
  return {start, stop};
}
