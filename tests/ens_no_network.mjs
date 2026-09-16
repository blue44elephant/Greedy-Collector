// Test-only guard: load before the dependency/helper, including subprocess tests.
import net from 'node:net';
import tls from 'node:tls';
import http from 'node:http';
import https from 'node:https';
import http2 from 'node:http2';
import dns from 'node:dns';
import dgram from 'node:dgram';
import childProcess from 'node:child_process';
import {syncBuiltinESMExports} from 'node:module';

const blocked = () => {
  // Fail the process so a dependency cannot swallow a thrown guard exception.
  process.stderr.write('Normalizer test attempted network or a child process\n');
  process.exit(97);
};
for (const [module, keys] of [
  [net, ['connect', 'createConnection', 'createServer']], [tls, ['connect', 'createServer']],
  [http, ['request', 'get', 'createServer']], [https, ['request', 'get', 'createServer']],
  [http2, ['connect', 'createServer', 'createSecureServer']], [dgram, ['createSocket']],
  [childProcess, ['exec', 'execSync', 'execFile', 'execFileSync', 'spawn', 'spawnSync', 'fork']],
]) for (const key of keys) module[key] = blocked;
net.Socket.prototype.connect = blocked;
for (const key of Object.keys(dns)) {
  if (key === 'lookup' || key === 'lookupService' || key.startsWith('resolve') || key === 'reverse') {
    dns[key] = blocked;
    if (key in dns.promises) dns.promises[key] = blocked;
  }
}
globalThis.fetch = blocked;
globalThis.WebSocket = blocked;
syncBuiltinESMExports();
