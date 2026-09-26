// Executed by the existing isolated Chromium runner. Only the test server mocks providers.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

module.exports = async function verifyMonitoring({evaluate, call, work}) {
  const text = selector => evaluate(`document.querySelector(${JSON.stringify(selector)}).innerText`);
  const idle = "waitFor(()=>document.getElementById('monitoring-workspace').dataset.busy==='false')";
  const check = () => evaluate(`button('#monitoring-selected','Check now').click(); ${idle}`);
  await evaluate(`go('monitoring')`);
  assert.ok((await text('#monitoring-list')).includes('No wallets are being monitored.'));
  assert.ok((await text('#monitoring-scheduler')).includes('Not running'));

  await evaluate(`const f=document.getElementById('monitoring-create'); f.elements.address.value='bad-address'; f.requestSubmit(); ${idle}`);
  assert.ok((await text('#monitoring-workspace > .operation-status')).includes('Check the public wallet address'));
  assert.ok((await text('#monitoring-list')).includes('No wallets are being monitored.'));
  await evaluate(`const f=document.getElementById('monitoring-create'); f.elements.chain.value='ethereum'; f.elements.address.value='0x'+'3'.repeat(40); f.elements.label.value='Browser monitored wallet'; f.elements.notes.value='Test-only note'; f.requestSubmit(); ${idle}`);
  assert.ok((await text('#monitoring-list')).includes('Browser monitored wallet'));
  assert.equal(await evaluate("document.querySelector('#monitoring-create [name=enabled]').checked"), true);
  assert.equal(await evaluate("document.querySelector('#monitoring-create [name=priority]').value"), 'normal');
  assert.ok((await text('#monitoring-history')).includes('No monitoring history for this wallet.'));
  assert.ok((await text('#monitoring-alerts')).includes('No alerts for this wallet.'));
  assert.ok((await text('#monitoring-selected')).includes('Not available'));
  assert.equal(await evaluate("document.querySelector('#monitoring-edit [name=notes]').value"), 'Test-only note');

  await evaluate(`const f=document.getElementById('monitoring-edit'); f.closest('details').open=true; f.elements.label.value='Edited watch'; f.elements.priority.value='high'; f.elements.notes.value='Persisted browser note'; f.requestSubmit(); ${idle}`);
  assert.ok((await text('#monitoring-list')).includes('Edited watch'));
  await evaluate(`button('#monitoring-workspace','Refresh monitoring').click(); ${idle}`);
  assert.equal(await evaluate("document.querySelector('#monitoring-edit [name=notes]').value"), 'Persisted browser note');
  assert.equal(await evaluate("document.querySelector('#monitoring-edit [name=priority]').value"), 'high');

  await check();
  assert.ok((await text('#monitoring-result')).includes('Completed'));
  assert.ok((await text('#monitoring-result')).includes('first observation establishes a silent baseline'));
  assert.ok((await text('#monitoring-history')).includes('Stored runs: 1'));
  assert.ok((await text('#monitoring-alerts')).includes('No alerts for this wallet.'));
  assert.equal(await evaluate("document.querySelector('#monitoring-selected .short-value').title"), 'e'.repeat(64));

  await check();
  assert.ok((await text('#monitoring-alerts')).includes('New incoming transaction'));
  assert.equal(await evaluate("document.querySelectorAll('#monitoring-alerts tbody tr').length"), 1);
  assert.equal(await evaluate("document.querySelector('#monitoring-selected .short-value').title"), 'f'.repeat(64));
  await check();
  assert.ok((await text('#monitoring-result')).includes('Continuity loss'));
  assert.ok((await text('#monitoring-result')).includes('Ambiguous activity was not alerted and the previous boundary was preserved.'));
  assert.equal(await evaluate("document.querySelector('#monitoring-selected .short-value').title"), 'f'.repeat(64));
  assert.equal(await evaluate("document.querySelectorAll('#monitoring-alerts tbody tr').length"), 1);
  await check();
  assert.ok((await text('#monitoring-result')).includes('Provider failure'));
  assert.ok((await text('#monitoring-result')).includes('Verify server provider configuration'));
  assert.ok((await text('#monitoring-history')).includes('Continuity loss'));
  assert.ok((await text('#monitoring-history')).includes('Provider failure'));
  assert.equal((await text('#monitoring-workspace')).includes('browser-test-only-key'), false);
  assert.equal((await text('#monitoring-workspace')).includes('https://provider.invalid'), false);

  await evaluate(`button('#monitoring-selected','Disable watch').click(); ${idle}`);
  assert.equal(await evaluate("button('#monitoring-selected','Check now').disabled"), true);
  assert.ok((await text('#monitoring-history')).includes('Stored runs: 4'));
  assert.equal(await evaluate("document.querySelectorAll('#monitoring-alerts tbody tr').length"), 1);
  await evaluate(`button('#monitoring-selected','Enable watch').click(); ${idle}`);
  assert.equal(await evaluate("button('#monitoring-selected','Check now').disabled"), false);

  // Generate real persisted runs via the actual manual endpoint; only providers are mocked.
  for (let index = 0; index < 22; index++) await check();
  assert.ok((await text('#monitoring-history')).includes('Runs returned: 25 · Stored runs: 26'));
  assert.equal(await evaluate("document.querySelectorAll('#monitoring-alerts tbody tr').length"), 1);
  await evaluate(`button('#monitoring-history','Older runs').click(); ${idle}`);
  assert.ok((await text('#monitoring-history')).includes('Runs returned: 1 · Stored runs: 26'));
  assert.equal(await evaluate("button('#monitoring-history','Older runs').disabled"), true);
  await evaluate(`button('#monitoring-history','Newer runs').click(); ${idle}`);
  assert.equal(await evaluate("document.querySelectorAll('#monitoring-history tbody tr').length"), 25);
  await evaluate(`button('#monitoring-selected','Disable watch').click(); ${idle}`);
  await evaluate(`const f=document.getElementById('monitoring-create');f.elements.chain.value='solana';f.elements.address.value='1thX6LZfHDZZKUs92febYZhYRcXddmzfzF2NvTkPNE';f.elements.label.value='Solana test account';f.requestSubmit();${idle}`);
  assert.ok((await text('#monitoring-selected')).includes('Solana test account'));
  await check();
  assert.ok((await text('#monitoring-result')).includes('first observation establishes a silent baseline'));
  assert.ok((await text('#monitoring-alerts')).includes('No alerts for this wallet.'));
  await check();
  assert.equal(await evaluate("document.querySelectorAll('#monitoring-alerts tbody tr').length"), 2);
  assert.ok((await text('#monitoring-alerts')).includes('New outgoing transaction'));
  await check();
  assert.equal(await evaluate("document.querySelectorAll('#monitoring-alerts tbody tr').length"), 2);
  await check();
  assert.ok((await text('#monitoring-result')).includes('Continuity loss'));
  assert.equal(await evaluate("document.querySelectorAll('#monitoring-alerts tbody tr').length"), 2);
  await call('Page.captureScreenshot', {format:'png'}).then(result => fs.writeFileSync(path.join(work,'solana-monitoring.png'), Buffer.from(result.data,'base64')));
  console.log('Solana monitoring browser passed: silent baseline, multiple instruction alerts, and bounded continuity loss.');
  await evaluate(`button('#monitoring-selected','Disable watch').click(); ${idle}`);
  await call('Page.captureScreenshot', {format:'png'}).then(result => fs.writeFileSync(path.join(work,'monitoring.png'), Buffer.from(result.data,'base64')));
  console.log('Monitoring browser passed: empty states, create/edit/refresh, silent baseline, real test alert, continuity loss, sanitized failure, disable/re-enable, deduplication, and run pagination.');
};
