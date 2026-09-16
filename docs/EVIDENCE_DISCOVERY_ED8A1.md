# ED-8A1: authoritative local ENSIP-15 normalization bridge

This increment supplies backend normalization only. It does not register an ENS Discovery transform, perform resolution, create results, render ENS UI/graph nodes or enable promotion. ENS names remain output-only endpoints. No migration is added.

## Original blocker and dependency verification

ED-8A stopped because Universal Resolver forward verification does not establish that the returned name is normalized. Its Python candidate was archived and advertised Unicode 16; using it or substituting lowercase/IDNA would not meet the current specification. The historical analysis remains in [ED-8A](EVIDENCE_DISCOVERY_ED8A.md).

Verified on 2026-09-17:

| Property | Decision / verified source |
| --- | --- |
| Implementation | `@adraffy/ens-normalize`, explicitly identified as the standard implementation in [ENS Name Processing](https://docs.ens.domains/resolution/names/) |
| Exact package | **1.11.1**, verified with npm registry metadata and the [upstream package manifest](https://github.com/adraffy/ens-normalize.js/blob/19daa8507f95d9432fcf1e59c9ac76131630c6da/package.json) |
| Standard | [ENSIP-15](https://docs.ens.domains/ensip/15/); library handles mapping, Unicode, script/confusable checks, emoji sequences and its own normalization data |
| Unicode | **17.0.0**, CLDR 47, confirmed by the reference implementation and versioned validation corpus |
| Runtime dependencies | **Zero**; the lock contains only the root project and this package |
| License | **MIT**, Copyright (c) 2021 Andrew Raffensperger; a copy accompanies the selected test vectors |
| Node compatibility | Upstream declares no `engines` restriction. GC deliberately requires **Node >=24**, verified locally on **v24.13.1** with Python **3.14**. This is GC's supported runtime floor, not an upstream minimum claim. |

No Python normalizer, viem, ethers or Web3 framework is added. The package and lockfile use the exact version, with npm tarball SHA-512 integrity recorded. The helper verifies the local installed package name/version, root manifest pin and lockfile pin before import. A changed installed version fails closed. This is not a signature verifier for arbitrary local filesystem tampering; install from the reviewed lockfile.

## Installation and process model

From the standalone source checkout:

```powershell
cd "C:\Tools\Inventions\greedy-collector"
npm ci
python -m pytest tests/test_ens_normalization.py -q
npm test
```

If PowerShell blocks `npm.ps1`, use `npm.cmd ci` and `npm.cmd test`. Only installation/tests use npm; production invokes the resolved Node executable directly.

Node and the local dependency are needed only when this normalization capability is called. Other GC startup/workspaces do not require a successful normalizer probe. Startup never installs packages or executes the helper. No `npm run dev`, runtime `npm install`, npx, CDN or daemon is introduced. `node_modules/` is ignored by Git. The existing Python dependency files are unchanged.

`normalize_ens_name(value)` invokes one fixed `scripts/ens_normalize.mjs` process with an argv list, `shell=False`, repository working directory, and the ENS value solely on stdin. Executable discovery uses the fixed `node`/`node.exe` name in absolute operator-PATH directories, excluding relative/current-directory entries; the resolved absolute executable is cached. No API accepts an executable or helper path. On Windows the subprocess window is hidden.

The helper explicitly imports `node_modules/@adraffy/ens-normalize/dist/index.mjs` by absolute file URL. It rejects package/entry links resolving outside that local location. It does not use bare-module search through parent/global directories. It imports the default library with its own NFC implementation, not the optional native-NFC variant.

Each call owns its process, pipes and timeout. Concurrent calls share no request files or mutable result state. No ENS input is written to temporary files. The synchronous bridge should run in a worker thread if later called from an async executor; ED-8A will integrate that lifecycle.

## Protocol, bounds and errors

Request: a JSON object with exactly one string `name`. Success: exactly `ok: true` and `normalized`. Failure: `ok: false` and a fixed `error_type`. The helper emits one JSON response, no incidental logs, and exits. The Python decoder rejects extra/duplicate keys, invalid UTF-8/JSON, wrong field types and malformed success responses.

| Limit | Value |
| --- | --- |
| Raw name | **2,048 UTF-8 bytes**, checked before spawning; no truncation |
| Canonical output name | **2,048 UTF-8 bytes**, compatible with existing endpoint storage size |
| Encoded stdin request | **16 KiB** |
| Captured stdout | **16 KiB** |
| Captured stderr | **4 KiB** |
| Execution timeout | **4 seconds**, then termination with up to one second process wait and one second pipe cleanup |

Independent bounded readers drain both output pipes. Overflow kills the child; a writer thread prevents a child refusing stdin from blocking the calling thread indefinitely. Tests exercise timeout, blocked stdin, oversized stdout/stderr and nonzero exit, including process reaping. This process boundary is not advertised as an OS sandbox for executing untrusted code: only the fixed helper and reviewed local dependency are invoked.

Safe typed `EnsNormalizationError.error_type` values are `normalizer_unavailable`, `invalid_ens_name`, `normalizer_timeout`, and `normalizer_protocol_error`. Messages contain no input, raw stderr, command, local path, environment value or stack trace. Empty names are rejected as GC endpoints even though the reference library accepts the empty ENS root. Other invalid names are rejected without repair or fallback. Successful output is returned unchanged; Python performs no lowercase, casefold, IDNA, punycode or NFC transformation.

## Environment, capability and network

Children inherit only `SystemRoot` and `WINDIR` on Windows, and an empty environment on other platforms. No provider keys, GitHub token, PATH, user profile, npm configuration, NODE_PATH or NODE_OPTIONS are forwarded. Absolute Node/helper paths make a runtime PATH unnecessary. There is no shell, dynamic eval or runtime install in production.

`probe_ens_normalizer()` is a lazy, locked, process-local cached self-test returning installed/usable state, expected/verified package version, Unicode version and safe failure category. It uses the reference library's empty-root identity as its self-test, with no sample endpoint or persistence. `refresh=True` repeats the probe and refreshes Node discovery after an operator installation or PATH change. Ordinary normalization does not run an extra probe. Missing Node or dependency never prevents application startup.

The helper and reference distribution perform local computation only. No Ethereum RPC, resolver, CCIP, npm or other provider request exists in this path. Automated tests block Python external transports and preload a test-only Node network/process guard before dependency import. The guard exits on attempted network access so library exception handling cannot conceal it. Windows TestClient's local asyncio socketpair is allowed; provider transports remain blocked. Dependency installation and research downloads occur only during setup, outside tests/runtime.

## ED-8A0 integration

`normalize_ens_subject(raw_value)` always calls the reference bridge before building an in-memory `ens_name / ethereum` identity. It does not open storage or create a Discovery run/result. Integration tests explicitly store canonical names in an isolated SQLite database, including ZWJ emoji, emoji tag sequences and a Unicode-17 emoji, and compare all other table counts before/after.

The older `canonical_ens_subject` remains an internal canonical-input API, preserving existing identities and historical spelling semantics. It is not a replacement for the raw-name helper. Its former blanket category-C rejection is narrowed only through authoritative validation: a value containing such characters must normalize to exactly itself. This allows valid emoji format sequences and newly assigned Unicode characters without broadly allowing arbitrary controls. That exceptional storage check can require an additional local subprocess; ordinary normalization is one process. If normalization is unavailable, exceptional values fail closed. Existing whitespace, namespace, size and relationship direction checks remain.

ENS still cannot start a Discovery run. `resolves_to` still points from ENS name to an Ethereum wallet. No Entity, Claim, Label, risk, Case, Attribution evidence or Discovery result is automatically created.

## Official-vector verification

The offline corpus selects **26 unmodified entries** from [upstream validate/tests.json](https://github.com/adraffy/ens-normalize.js/blob/19daa8507f95d9432fcf1e59c9ac76131630c6da/validate/tests.json) at the package's git commit. The fixture records original indexes, version metadata, source URL and full-source SHA-256 `7b20fb69f190c07f8b59ff30aea4efcdc0fa592667ff1f7a2a1f7122743d089d`.

Categories include unchanged ASCII, mixed/uppercase input, Unicode mapping, IDNA deviations, script confusables, invalid labels/characters, emoji styling, invalid joiners/tags, valid ZWJ/tag sequences and a Unicode-17 emoji. Python is cross-checked against a direct local-library call for the entire selected corpus. The empty-root exception is explicit. The official ENS docs' mixed-case cycling-emoji example is tested separately. This is selected-vector regression coverage, not a claim to rerun the upstream 38,613-case suite.

## Verification and next step

Baseline: **1075/1075**. Final `python -m pytest tests/ -q`: **1146/1146 passed**, **71 tests added**, 57 warnings, 340.89 seconds. Focused normalizer/endpoint tests passed **108/108**. A clean `npm ci --ignore-scripts --no-audit --no-fund` installed exactly one package from the lock; `npm test` passed **34/34** with the network guard active. Existing frontend tests passed **32/32**.

The existing isolated `browser_smoke.cjs` and `browser_discovery.cjs graph` workflows both passed. They cover Wallet, blockchain Graph, Monitoring, Alerts, Cases, Labels, Research, and Discovery graph with ED-6 Attribution navigation, using temporary SQLite fixtures and blocked external provider transports. No ENS UI is added or claimed.

`git diff --check` passed. Alembic remains **20260916_01 (head)**; no migration changed. No real user database was inspected or migrated, no fake production records were introduced, and Epic Archer was untouched. Ten files are added, four modified, none removed. No commit was created.

After this prerequisite passes, resume ED-8A separately. The future reverse executor must require both forward verification and that the raw returned name equals its normalized form; it must not normalize a different spelling and attach the old forward verification to it. ENS Discovery, graph and promotion are still unimplemented by this increment.

Verdict: **ED8A1_ENS_NORMALIZATION_BRIDGE_COMPLETE**.
