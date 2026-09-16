import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, mkdtempSync, mkdirSync, copyFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {spawnSync} from 'node:child_process';

const root = fileURLToPath(new URL('..', import.meta.url));
const helper = path.join(root, 'scripts', 'ens_normalize.mjs');
const guard = path.join(root, 'tests', 'ens_no_network.mjs');
const corpus = JSON.parse(readFileSync(new URL('./fixtures/ens_normalization_vectors.json', import.meta.url)));
const env = Object.fromEntries(['SystemRoot', 'WINDIR'].filter(k => process.env[k]).map(k => [k, process.env[k]]));
function run(input, file = helper) {
  const result = spawnSync(process.execPath, ['--import', pathToFileURL(guard).href, file], {
    input, encoding:'utf8', env, timeout:5000, maxBuffer:16384, windowsHide:true,
  });
  assert.equal(result.error, undefined);
  assert.equal(result.status, 0);
  assert.equal(result.stderr, '');
  return JSON.parse(result.stdout);
}
test('exact local package and lock pin', () => {
  const declared = JSON.parse(readFileSync(path.join(root, 'package.json')));
  const locked = JSON.parse(readFileSync(path.join(root, 'package-lock.json')));
  assert.equal(declared.dependencies['@adraffy/ens-normalize'], '1.11.1');
  assert.equal(locked.packages['node_modules/@adraffy/ens-normalize'].version, '1.11.1');
  assert.equal(Object.keys(locked.packages).length, 2);
  assert.deepEqual(run('{"probe":true}'), {ok:true,package:'@adraffy/ens-normalize',version:'1.11.1',unicode_version:'17.0.0'});
});
for (const vector of corpus.vectors) {
  test(`official vector ${vector.index}: ${vector.comment ?? 'Unicode'}`, () => {
    const actual = run(JSON.stringify({name:vector.name}));
    if (vector.error || vector.name === '') assert.deepEqual(actual, {ok:false,error_type:'invalid_ens_name'});
    else assert.deepEqual(actual, {ok:true,normalized:vector.norm ?? vector.name});
  });
}
for (const input of ['{}', '[]', '{bad', '{"name":4}', '{"name":"a.eth","eval":"x"}', 'x'.repeat(16385)]) {
  test('bounded invalid protocol ' + input.slice(0, 30), () => {
    const actual = run(input);
    assert.equal(actual.ok, false);
    assert.ok(['normalizer_protocol_error','invalid_ens_name'].includes(actual.error_type));
  });
}
test('missing local dependency never uses parent/global installation', () => {
  const work = mkdtempSync(path.join(tmpdir(), 'gc-ens-missing-'));
  const scripts = path.join(work, 'scripts');
  mkdirSync(scripts);
  copyFileSync(helper, path.join(scripts, 'ens_normalize.mjs'));
  assert.deepEqual(run('{"probe":true}', path.join(scripts, 'ens_normalize.mjs')),
    {ok:false,error_type:'normalizer_unavailable'});
});
