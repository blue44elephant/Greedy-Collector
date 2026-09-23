# MC-1 multi-chain foundation

Greedy Collector registers **Bitcoin (`bitcoin`) and Ethereum (`ethereum`) only**.
IDs are stable persisted identifiers. MC-1 adds no chain, network provider, fake
runtime data, token standard, bridge inference or new risk rule.

## Registry and adapter boundary

`chains/registry.py` contains an ordered internal registry of frozen, typed
`ChainDefinition` records: ID, display name, native symbol/precision, UTXO or
account family, EVM compatibility, adapter class and bounded `Capability` flags.
Registration rejects duplicate IDs, missing adapters and inconsistent operations.
Optional methods on the existing `ChainAdapter` raise `unsupported_chain_capability`.
Unknown IDs raise `unsupported_chain`; neither falls back to Ethereum.

Syntax validation/normalization, transaction recognition and monitoring baseline
policy belong to adapters. Generic callers use the registry; provider dispatch
constructs only the selected adapter. Current provider transport, ordering,
pagination and fallback remain inside Bitcoin/Ethereum adapters. Existing
ETHERSCAN_API_KEY, ALCHEMY_API_KEY and monitoring environment variables are unchanged.

`GET /api/greedy-collector/chains` exposes a deliberate safe metadata projection,
never adapter objects, settings, credentials or request URLs. Browser modules load
this once before initializing workspaces and reuse it for selectors, symbols,
capabilities and case comparison. No frontend build dependency was added.

## Identity and resolution

Wallet identity is `(chain_id, canonical_address)`. Ethereum folds case; Bitcoin
Bech32 folds case; Base58 remains case-sensitive. Existing legacy spelling is not
rewritten. New wallet storage normalizes addresses; reads recognize historical
spelling using adapter comparison rules. Labels retain explicit `any` scope and
chain-specific labels do not leak between chains. Watchlists, alerts, Attribution
claims and Discovery subjects retain chain context. Cases retain chain in reference
metadata and historical pins; old cases are not rewritten. Research remains independent.

Transaction identity includes chain and transaction ID; stored transfer identity
also includes endpoints, token and amount. Graph traversal retains individual stored
rows for one hash. Graph node maps include chain; mixed internal graph outputs qualify
node IDs, while single-chain API node IDs remain addresses. SQLite queries and Neo4j
wallet identities are chain-scoped. Cache/query fingerprints already include the
canonical Discovery subject namespace; MC-1 does not change those fingerprints.

`resolve_identifier(value, chain_hint=None)` consults registered adapter syntax
without network calls. Existing unqualified BTC/ETH addresses and transaction IDs
resolve as before (including response spelling and transaction precedence). An
explicit hint selects one registered adapter; mismatch gives the existing unknown
result. Multiple matching adapters return `ambiguous` with chain/kind possibilities.
The browser passes chain hints on investigation handoffs. No syntax-only assumption
is made that an EVM address uniquely identifies a future network.

## Capabilities and Discovery

Application capabilities describe supported operations, not provider configuration.
BTC pending history and ETH token transfers remain distinct. Monitoring jobs are
generated from capable registry entries; BTC confirmed-only initial baseline and
ETH newest-record baseline remain adapter-owned. A limited chain cannot run Wallet
risk evaluation or monitoring without explicitly declaring those capabilities.
The existing deterministic risk engine is unchanged and never implicitly enabled
for a future chain.

Discovery chain support and transform compatibility remain separate. Generic wallet
transforms materialize compatible registered chains at startup; execution checks
the declared capability as well. Local Labels requires label support. ENS explicitly
declares Ethereum only. GraphSense explicitly declares Bitcoin/Ethereum only;
upstream coverage is not widened. Manual capture and generic subject schemas use
registry validation. Internal eligibility metadata is excluded from existing
descriptor snapshots/fingerprints. No ownership/claim semantics change.

`chains/evm.py` shares only EVM address/transaction syntax and case normalization.
Ethereum mainnet endpoints, chainid=1, provider configuration, ERC-20 parsing and ENS
stay Ethereum-specific. EVM compatibility does not imply ENS support. Native/token
amounts remain exact strings; decimals belong to adapters/assets, never generic math.

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
