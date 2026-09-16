// One local, bounded request. No RPC, HTTP, subprocesses, or package installation.
import {readFileSync, realpathSync, writeSync} from 'node:fs';
import {fileURLToPath, pathToFileURL} from 'node:url';
import path from 'node:path';

const PACKAGE = '@adraffy/ens-normalize';
const VERSION = '1.11.1';
const UNICODE = '17.0.0';
const INPUT_BYTES = 2048;
const REQUEST_BYTES = 16384;
const RESPONSE_BYTES = 16384;

function finish(response) {
  const bytes = Buffer.from(JSON.stringify(response) + '\n', 'utf8');
  if (bytes.length > RESPONSE_BYTES) {
    writeSync(1, '{"ok":false,"error_type":"normalizer_protocol_error"}\n');
  } else {
    writeSync(1, bytes);
  }
  process.exit(0);
}
function fail(error_type) { finish({ok:false, error_type}); }

async function library() {
  if (Number(process.versions.node.split('.')[0]) < 24) throw Error();
  const root = realpathSync(fileURLToPath(new URL('..', import.meta.url)));
  const directory = path.join(root, 'node_modules', '@adraffy', 'ens-normalize');
  const entry = path.join(directory, 'dist', 'index.mjs');
  // Absolute local imports only. Reject links to parent/global installations.
  if (realpathSync(directory) !== directory || realpathSync(entry) !== entry) throw Error();
  const manifest = JSON.parse(readFileSync(path.join(directory, 'package.json'), 'utf8'));
  const declared = JSON.parse(readFileSync(path.join(root, 'package.json'), 'utf8'));
  const locked = JSON.parse(readFileSync(path.join(root, 'package-lock.json'), 'utf8'));
  if (manifest.name !== PACKAGE || manifest.version !== VERSION ||
      Object.keys(manifest.dependencies ?? {}).length !== 0 ||
      declared.dependencies?.[PACKAGE] !== VERSION ||
      locked.packages?.['']?.dependencies?.[PACKAGE] !== VERSION ||
      locked.packages?.['node_modules/' + PACKAGE]?.version !== VERSION) throw Error();
  const {ens_normalize} = await import(pathToFileURL(entry).href);
  if (typeof ens_normalize !== 'function') throw Error();
  return ens_normalize;
}

async function main() {
  const chunks = [];
  let size = 0;
  for await (const chunk of process.stdin) {
    size += chunk.length;
    if (size > REQUEST_BYTES) fail('normalizer_protocol_error');
    chunks.push(chunk);
  }
  let request;
  try {
    request = JSON.parse(new TextDecoder('utf-8', {fatal:true}).decode(Buffer.concat(chunks)));
  } catch { fail('normalizer_protocol_error'); }
  if (!request || typeof request !== 'object' || Array.isArray(request) ||
      Object.keys(request).length !== 1) fail('normalizer_protocol_error');
  const probe = request.probe === true;
  if (!probe && !Object.hasOwn(request, 'name')) fail('normalizer_protocol_error');
  if (!probe && (typeof request.name !== 'string' || !request.name.length ||
      !request.name.isWellFormed() || Buffer.byteLength(request.name, 'utf8') > INPUT_BYTES)) {
    fail('invalid_ens_name');
  }
  let normalize;
  try { normalize = await library(); } catch { fail('normalizer_unavailable'); }
  if (probe) {
    // Empty string is the reference library's root, not a GC endpoint or seed.
    if (normalize('') !== '') fail('normalizer_protocol_error');
    finish({ok:true, package:PACKAGE, version:VERSION, unicode_version:UNICODE});
  }
  let normalized;
  try { normalized = normalize(request.name); } catch { fail('invalid_ens_name'); }
  if (!normalized.length || Buffer.byteLength(normalized, 'utf8') > INPUT_BYTES) fail('invalid_ens_name');
  finish({ok:true, normalized});
}

main().catch(() => fail('normalizer_protocol_error'));
