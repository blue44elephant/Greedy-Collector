# Multi-chain registry and adapter architecture

Greedy Collector registers **Bitcoin (`bitcoin`)**, **Ethereum (`ethereum`)**, **Base (`base`)**,
**Arbitrum One (`arbitrum`)**, **BNB Smart Chain (`bsc`)**, **Polygon (`polygon`)**, and
**TRON (`tron`)**, and **Solana (`solana`)**. IDs are stable persisted identifiers. The four added EVM networks share
one descriptor-configured Etherscan V2 adapter; Solana uses a separate read-only JSON-RPC adapter. No database migration or fake runtime data is used.

## Registry and adapter boundary

`chains/registry.py` contains an ordered internal registry of frozen, typed
`ChainDefinition` records: ID, display name, native symbol/precision, UTXO or
account family, EVM compatibility and chain ID, explorer URL, adapter class and bounded
`Capability` flags.
Registration rejects duplicate IDs, missing adapters and inconsistent operations.
Optional methods on the existing `ChainAdapter` raise `unsupported_chain_capability`.
Unknown IDs raise `unsupported_chain`; neither falls back to Ethereum.

Syntax validation/normalization, transaction recognition and monitoring baseline
policy belong to adapters. Generic callers use the registry; provider dispatch
constructs only the selected adapter. Current provider transport, ordering,
pagination and fallback remain inside each provider adapter. TRON uses the server-side
`TRON_PRO_API_KEY`; credentials never enter registry metadata or browser code.
Solana uses `SOLANA_RPC_URL` or the documented rate-limited public mainnet endpoint;
the credential-bearing URL never enters responses or logs.

`GET /api/greedy-collector/chains` exposes a deliberate safe metadata projection,
never adapter objects, settings, credentials or request URLs. Browser modules load
this once before initializing workspaces and reuse it for selectors, symbols,
capabilities and case comparison. No frontend build dependency was added.

## Identity and resolution

Wallet identity is `(chain_id, canonical_address)`. EVM addresses fold case; Bitcoin
Bech32 folds case; Base58 remains case-sensitive. Existing legacy spelling is not
rewritten. New wallet storage normalizes addresses; reads recognize historical
spelling using adapter comparison rules. Labels retain explicit `any` scope and
chain-specific labels do not leak between chains. Watchlists, alerts, Attribution
claims and Discovery subjects retain chain context. Cases retain chain in reference
metadata and historical pins; old cases are not rewritten. Research remains independent.

Transaction identity includes chain and transaction ID; stored transfer identity
also includes endpoints, token and amount. Graph traversal retains individual stored
rows for one hash. Graph node maps include chain; mixed internal graph outputs qualify
node IDs, while single-chain API node IDs remain addresses. A TRON Base58Check address
and an Ethereum address derived from the same 20-byte payload remain distinct identities;
no ownership or graph relationship is inferred. SQLite queries and Neo4j
wallet identities are chain-scoped. Cache/query fingerprints already include the
canonical Discovery subject namespace; MC-1 does not change those fingerprints.

`resolve_identifier(value, chain_hint=None)` consults registered adapter syntax
without network calls. Bare 64-hex transaction IDs resolve to Bitcoin; `0x` plus 40
hex resolves to Ethereum by default; `0x` plus 64 hex resolves to Ethereum by default.
Since supported EVM networks share syntax, an explicit hint is required to route an EVM
identifier to Base, Arbitrum, BNB Smart Chain or Polygon. A hint selects one adapter;
mismatch returns unknown. Existing TRON transaction IDs also use an explicit hint.
Solana base58 accounts and 64-byte transaction signatures resolve locally when no
higher-priority existing chain syntax matches.
The Wallet workspace populates the optional selector from `/chains`; investigation handoffs
carry the selected chain directly.

## Capabilities and Discovery

Application capabilities describe supported operations, not provider configuration.
BTC pending history remains distinct; all five registered EVM networks expose bounded
native history and token transfers through Etherscan V2. Monitoring jobs are generated
from capable registry entries; BTC confirmed-only initial baseline and newest-record
account-chain baselines remain adapter-owned. A limited chain cannot run Wallet
risk evaluation or monitoring without explicitly declaring those capabilities.
TRON uses generic source-backed label exposure but opts out of the existing BTC/ETH
behavioral indicators. Solana also opts out of chain-specific behavioral risk rules.
No TRON- or Solana-specific heuristic or neutral evidence is invented.

Discovery chain support and transform compatibility remain separate. Generic wallet
transforms materialize compatible registered chains at startup; execution checks
the declared capability as well. Local Labels requires label support. ENS explicitly
declares Ethereum only. GraphSense explicitly declares Bitcoin/Ethereum only;
upstream coverage is not widened. Manual capture and generic subject schemas use
registry validation. Query and result fingerprints retain the chain-qualified
subject namespace, so existing Bitcoin/Ethereum identities remain unchanged.
No ownership/claim semantics change.

Solana's adapter supports bounded parsed history and instruction-derived SOL/SPL events.
See [Solana support](SOLANA_SUPPORT.md) for RPC bounds, version support, ownership limits,
event keys, and monitoring behavior.

`chains/evm.py` owns common EVM address/transaction syntax and case normalization.
`chains/etherscan_v2.py` owns shared V2 balance, bounded transaction/token pagination,
normalization and transaction lookup. Network descriptors supply Etherscan `chainid`,
native symbol/precision and explorer URL. `EthereumAdapter` alone adds the optional
Alchemy mainnet balance fallback; ENS remains Ethereum-only. TRON is an account-family
chain but is not marked EVM-compatible. Native/token amounts remain exact strings;
decimals belong to adapters/assets, never generic floating-point math.
Etherscan V2 uses a shared account key, but eligible plan coverage can vary by chain.
See [generic EVM multi-chain support](EVM_MULTICHAIN_SUPPORT.md) for current IDs,
provider-plan notes and identifier routing.

## Storage and audit

Migration `20260923_01` follows `20260922_02`. It replaces just the Attribution claim
chain whitelist and Discovery blockchain namespace whitelist with structural checks:
1-32 lowercase ASCII letters/digits/underscore, starting with a letter. Application
validation still rejects unregistered chains. Existing normalization checks and all
unrelated enums, uniqueness, foreign keys and immutability triggers are retained.
No rows are seeded or rewritten. Downgrade refuses retained additional-chain rows.
Tests use temporary SQLite; the configured user database is neither inspected nor migrated.

Audit categories:

| Category | Decision |
| --- | --- |
| A: chain-specific algorithms | Retain BTC/ETH address patterns, pagination, provider parsing, ENS and GraphSense network mappings. |
| B: presentation | Centralize selectors, names, symbols and pending capability; retain accurate Bitcoin provider-count and representative-endpoint explanations. |
| C: generic logic | Registry dispatch, schemas, resolver hints, monitoring policies, chain-scoped graph/labels and reusable subject validation. |
| D: storage | Two extensible identifier constraints; retain existing chain-specific canonicalization protections and semantic enums. |
| E: tests | Fixtures remain test-only; add limited third-chain contract and isolated migration/browser checks. |

## Adding a new chain

1. Choose a stable canonical ID and add one typed descriptor to the built-in registry.
2. Implement address/transaction validation and canonical identity rules.
3. Implement provider operations inside its adapter, with bounded retrieval and safe errors.
4. Declare only capabilities supported by implemented operations; assess risk explicitly.
5. Normalize provider records into existing native/token amount string fields.
6. Add adapter, resolver ambiguity, identity and provider contract tests.
7. If monitoring is supported, define interval and stable baseline policy, then test continuity.
8. If token transfers are supported, implement that chain's actual asset semantics.
9. Opt into compatible Discovery transforms; never inherit ENS or GraphSense coverage.

Normal additions do not require rewriting generic workspaces or a chain-enum migration.
New algorithms, providers, token semantics or transforms still require their own tests.

## Transaction event identity

Migration `20260923_02` gives normalized transaction rows an `event_key` and uses
`(chain, tx_hash, event_key)` for storage uniqueness. Native transactions use one
`tx` event; EVM token logs use a validated canonical log index; TRON keeps its
provider event ID; Bitcoin keeps stable wallet-relative activity identity. The
nullable `event_index` and `asset_contract` columns preserve provider event
metadata when available. Solana uses validated `solana-ix:<outer>` and
`solana-inner:<outer>:<inner>` keys. See [Transaction event identity](TRANSACTION_EVENT_IDENTITY.md)
for migration and downgrade behavior.
