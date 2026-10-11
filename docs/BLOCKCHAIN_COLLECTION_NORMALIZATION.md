# Blockchain collection and normalization (BC-1)

Scope: ten registered mainnet chains; real configured providers and local SQLite only.
No lifetime-history claim, recursive crawling, new chains, or risk-model changes.

## Capability matrix

| Chain | Validation / canonicalization | Balance / history | Token history | Single transaction | Graph / monitoring | Bounds and provider |
|---|---|---|---|---|---|---|
| Bitcoin | Mainnet Base58Check; SegWit Bech32/Bech32m checksum, lower-case SegWit identity | BTC, integer satoshis | Unsupported | Esplora structural record | Stored input/output connectivity; scheduled/manual monitoring | Blockstream then Mempool.space; restart on failure; 20 pages, 500 confirmed + up to 50 initial mempool |
| Ethereum | 40-hex account; lower-case, chain-scoped | ETH, wei | ERC-20 contract/log or bounded observation identity | Etherscan proxy native envelope | Stored events / monitoring | Etherscan V2 chain 1; 10 pages x 1000 per stream; Ethereum-only Alchemy balance fallback |
| Base | Same EVM identity scoped to Base | ETH, wei | ERC-20 | Same envelope | Stored events / monitoring | Etherscan V2 chain 8453; same bounds |
| Arbitrum One | Same EVM identity scoped to Arbitrum | ETH, wei | ERC-20 | Same envelope | Stored events / monitoring | Etherscan V2 chain 42161; same bounds |
| BNB Smart Chain | Same EVM identity scoped to BSC | BNB, wei | ERC-20-compatible | Same envelope | Stored events / monitoring | Etherscan V2 chain 56; same bounds |
| Polygon PoS | Same EVM identity scoped to Polygon | POL, atomic units | ERC-20-compatible | Same envelope | Stored events / monitoring | Etherscan V2 chain 137; same bounds |
| TRON | Base58Check; provider 41-hex converted to Base58Check, never EVM identity | TRX, sun | TRC-20 contract identity; TRC-10 raw units with unknown scaling | Native/TRC-10 envelope; other contract types retained as unsupported observations | Supported transfer records / monitoring | TronGrid; 5 x 200 per native/token stream; opaque fingerprint loop defense |
| Solana | Canonical Base58 32-byte account / 64-byte signature; case-sensitive | SOL, lamports | Parsed SPL Token and Token-2022 transfer/transferChecked; mint identity | Parsed outer/inner instructions; failed/unavailable activity markers | Known participants only / bounded signature monitoring | Configured RPC or public mainnet RPC; 50 signatures default, max 100; confirmed retrieval, finalized balance |
| Litecoin | Mainnet Base58Check prefixes 48/5/50; Bech32/Bech32m, lower-case SegWit | LTC, litoshi | Unsupported | Esplora structural record | Stored input/output connectivity / monitoring | LitecoinSpace; 3 x 25 confirmed + up to 50 initial mempool |
| Monero | Mainnet standard/subaddress/integrated CryptoNote checksum and public-key validation | Unsupported | Unsupported | Unsupported | Unsupported | Observation-only; Discovery, Labels, Cases, Attribution can reference textual addresses |

All chains expose capabilities through `/api/greedy-collector/chains`. Unsupported
operations raise `unsupported_chain_capability`; Monero never returns zero balances or
empty history as a substitute. MWEB is excluded. ENS remains Ethereum-only. No provider
calls occur in resolution. Shared EVM identifiers, bare 64-hex BTC/LTC/TRON IDs, and
other genuine syntax overlaps require an explicit network hint; no default-chain guess.

## Normalized contract

`NormalizedTransaction` retains chain, transaction identifier, participants, exact decimal
text `value_native`, display symbol, UTC timestamp (or unavailable), height/slot, fee,
wallet-relative direction, source API, event index and contract/mint.
Raw provider evidence remains in `Transaction.raw_payload`. `_public` contains asset type,
chain-qualified `asset_id`, raw integer text, scaling metadata, execution status, finality,
and applicable structural facts. `_collection` records requested chain, provider,
retrieval UTC ISO-8601 timestamp and derived event key. Public responses expose this
provenance without exposing the raw provider object or credential-bearing URLs.
Metadata uses existing JSON storage; no schema migration is required.

Unavailable normalized amounts use an empty string in the existing non-null storage
column and JSON null in fresh lookup responses. They are not zero and cannot create
value-flow edges. Missing timestamps and provider zero timestamps are unavailable;
seconds and milliseconds are converted explicitly into aware UTC timestamps. SQLite
naive timestamp reads are interpreted as UTC at the normalization boundary.

Atomic integers are validated before scaling. Decimal tuple construction avoids both
binary floating point and rounding under Decimal's default context, including large
integers and up to 255 decimal places. Fees are not inferred from gas limits. A proxy
transaction response alone does not establish paid fee, execution success or timestamp.

Symbols/names are display metadata only. Native identities are `<chain>:native`;
tokens use `<chain>:token:<canonical contract/mint>`. TRC-10 asset identifiers occupy a
separate `trc10:` namespace. Missing token decimals do not imply zero or eighteen decimals.
Raw units survive when scaling is unavailable. Missing token identity is diagnostic,
never a symbol-based asset merge.

## Event identity and persistence

Uniqueness is `(chain, tx_hash, event_key)`; existing chain/hash, participant, timestamp,
asset and event-index indexes suffice. EVM native records use `tx`, indexed logs use
`evm-log:<index>`, TRON uses canonical provider event material, Solana uses stable outer
and inner instruction paths. UTXO rows use a stable wallet-view key independent of
confirmation metadata and retain wallet input/output atomic sums. Collecting the same
view again updates its observation in place and preserves its row ID. A uniquely matched
legacy view can be upgraded without breaking references. Ambiguous legacy rows are not
silently merged.

Where a provider supplies no protocol event position, token records use available
contract, participant and raw-amount material, excluding mutable symbol/scaling metadata.
Indistinguishable duplicate provider observations cannot establish distinct occurrences;
this is a provider coverage limitation, not a claim of complete token event history.
The integrity diagnostic reports duplicate identities, missing/invalid chain or hash,
chain mismatch, missing token identity/scaling and invalid successful-transfer structure.
It reports questionable records without silently fabricating missing facts.

## Failure, finality and downstream behavior

Explicit EVM/TRON failure and Solana failed metadata survive as evidence. Failed records
are excluded from transfer edges and fund-flow, and do not trigger incoming/outgoing
movement alerts. Unsupported and unscaled records are likewise excluded. Unknown
execution is distinct from successful execution; fund-flow requires supported success
evidence. UTXO finality is confirmed/unconfirmed, EVM inclusion is reported separately
from confirmation, TRON confirmed retrieval retains provider context, and Solana records
use confirmed commitment. No confirmation counts are invented.

Manual lookup and monitoring share preparation/persistence. Finality updates retain
identity. Partial collection does not advance a monitoring boundary or emit new movement
alerts. Existing continuity-loss detection remains explicit for a lost saved boundary.

Bitcoin/Litecoin retain the raw vin/vout, wallet input/output totals and transaction
connectivity. Complex transactions have no guessed single sender/recipient. Stored
queries and traversal include raw structural participants. Graph exposes a separate
input/output connectivity table with no allocation arrows; fund-flow uses the same
raw transaction connectivity and no exact input-to-output amount. Existing clustering
continues to inspect structural input facts without any new heuristic.

## Bounds, diagnostics and provider limitations

Collection summaries record native/token/failed counts, new/reused rows, per-stream
status/reason and integrity diagnostics. The Wallet displays a compact summary.
`COMPLETE_WITHIN_REQUESTED_BOUND` only describes stream termination, never lifetime
coverage. `TRUNCATED` describes a reached page/item bound; `PROVIDER_LIMITED` means
retention or continuation cannot establish coverage; `PARTIAL` preserves available
observations when another stream/page fails; `UNAVAILABLE` identifies failed streams.
Monitoring reports `continuity_loss` when a saved boundary cannot be established.

EVM and TRON streams isolate provider failures. Empty pages terminate, repeated pages
or cursors stop, and page/item limits prevent unbounded retrieval. Bitcoin retries its
bounded history from another provider rather than mixing partial providers. Litecoin
fails explicitly on stalled pagination. Solana signature retrieval is bounded and
missing transaction details retain unavailable observations with raw signature context.

EVM internal/contract-mediated native transfers are not collected. ERC-721/1155,
Solana arbitrary-program balance movements, confidential/token extension behaviors,
MWEB and Monero public tracing are outside this scope. Token-2022 support covers parsed
transfer instructions, not every extension (including net-of-transfer-fee inference).
The corrected program ID follows [Solana's official terminology](https://solana.com/docs/references/terminology).

## Verification and separate backlog

`tests/test_collection_contract.py` covers precision, malformed amounts/timestamps,
asset/event scope, idempotency, finality refresh, structural UTXO retrieval, failed flows,
partial providers, ambiguity, provenance and Monero boundaries. Existing adapter,
pagination, monitoring, graph, fund-flow and migration tests retain their coverage.
All provider fixtures are test-only; configured user databases are never used by tests.

RISK-2 - Sanctions / Risk Calibration Audit: some known sanctioned-wallet tests produced
unexpectedly low GC risk scores. Audit separately; BC-1 does not change risk scoring.

## BC-1 verification checkpoint

62 collection-contract regressions were added and passed focused verification.
Frontend: 71/71; one consolidated `node tests/browser_bc1.cjs` smoke passed using
isolated SQLite and provider fixtures. No migration or configured user DB operation.

First full Python run: 1794 passed, 5 failed. Five invalid/outdated fixtures were
corrected and their exact failing subset passed 5/5.
Permitted final full rerun: 1798 passed, 1 failed, 194 warnings (763.28 seconds).
The remaining case was
`tests/test_discovery_graphsense.py::test_cache_refresh_immutable_material_and_history[True]`:
its second Discovery run creation returned HTTP 409. It passed unchanged in isolation
(1/1). The precise transient conflict cause is unproven; Discovery runtime was not modified.

Completion verdict remains `BLOCKCHAIN_COLLECTION_NORMALIZATION_INCOMPLETE` because
there is no clean final full-suite result. Both authorized full runs are exhausted.
Continuation should investigate only that intermittent Discovery conflict and establish
a clean full-suite result within a newly authorized verification budget. Do not repeat
frontend/browser checks unless subsequent changes require them. No commit was made.


## BC-1 narrow verification continuation (2026-10-06)

The original failing case passed in five separate isolated invocations. A focused
execution/GitHub/GraphSense ordering combination passed 217 tests before the fix;
no predecessor-dependent leak was reproduced. The harness uses a unique pytest
`tmp_path` SQLite database, context-managed sessions, runtime shutdown and engine
disposal. Dependency overrides and environment monkeypatches are restored.

A deterministic second-run reproduction advances the planning clock by one
microsecond across a minute boundary after `/discovery/plan` and before
`/discovery/runs`. It captures the exact internal `Conflict` reason:
`Plan changed or expired; plan again`. The first run is terminal, all executor tasks
are done, no second run is persisted, and a fresh plan succeeds using the same empty
cache. This proves a wall-clock-dependent failure path in the original test helper.
The historical full-suite response had only a generic conflict message, so its exact
internal branch cannot be established retrospectively from that response alone.

The cache/immutable-history test now freezes only `runtime.plan`'s clock through a
function-scoped monkeypatch. Retrieval/cache/deadline clocks remain real. Production
runtime, conflict guards, provider code, cache behavior and immutable history are
unchanged. The explicit expiration regression retains the intentional 409 behavior.
No sleeps, retries or relaxed assertions were added. Discovery runtime predates BC-1
and was not altered by it; the reproduced timing dependency is unrelated to collection
normalization.

Focused reproduction: 1 passed. Focused cache/history/expiration subset: 5 passed,
69 deselected. Post-fix execution/GitHub/GraphSense combination: 218 passed.
The one newly authorized full-suite invocation completed successfully:
`1800 passed, 194 warnings in 812.62s (0:13:32)`; no failures or skips.
This supersedes the earlier incomplete verification checkpoint.
Completion verdict: `BLOCKCHAIN_COLLECTION_NORMALIZATION_100_PERCENT` (repository
verification within BC-1's documented support boundaries, not unlimited coverage).
Frontend 71/71 and BC-1 browser smoke remain previously verified and untouched.
No user database operation, migration or commit was performed.

SANC-1 follows BC-1 with an authoritative, separate OFAC snapshot registry. RISK-2 remains a separate calibration audit; a wallet sourced from a public OFAC tracker previously produced unexpectedly low GC risk. No specific tracker wallet is production seed data.
