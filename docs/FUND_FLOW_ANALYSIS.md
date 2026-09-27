# FL-1 observed fund-flow and path analysis

Fund flow is observed transaction connectivity, **not ownership, identity, control, intent or
criminality**. It adds zero risk points and creates no Labels, Attribution material, watches
or alerts. The ten-chain registry is unchanged. No provider or frontend dependency was added.

## Scope and source evidence

Only stored SQLite transactions/events are read. There are no provider calls or automatic
collection. Supported chains are Bitcoin, Litecoin, Ethereum, Base, Arbitrum, BSC, Polygon,
TRON and Solana, gated by transparent graph/history capabilities. Monero returns controlled
`unsupported_chain_capability`, never an empty activity claim.

Account edges retain chain, canonical source/target, transaction hash, event key, UTC time,
asset identity, exact stored decimal amount, available raw amount, block and confirmation
metadata. Duplicate `(chain, tx_hash, event_key)` events are not summed twice. Failed/unknown
execution and unresolved participants are excluded with counts. EVM native records require
stored successful status; token-transfer records use the confirmed token-log source and
contract identity (explicit failure flags still exclude them). TRX requires SUCCESS return
metadata; confirmed TRC-20 events and successfully parsed SOL/SPL events are supported.
TRC-10 and unsupported Solana activities are excluded. Older records may lack enough evidence
and must not be interpreted as absence of activity.

For BTC/LTC the analyzer reads full persisted `vin`/`vout`, not representative sender/recipient
columns. Confirmed transactions with complete resolved input addresses and spendable output
addresses form transaction-connectivity hyperedges. OP_RETURN outputs are not wallet nodes.
Each path step identifies its transaction and output index, input count, and observed
output amount. Full input/output participation and original stored event keys are captured once
per transaction in the immutable run; path steps reference that provenance instead of duplicating it. **No input-to-output allocation or path capacity is claimed**, even for simple
UTXO transactions in FL-1. Output amounts never become attributed source amounts. Reusing the
same UTXO transaction to fabricate another hop is forbidden.

## Assets and time

Native identity is `<chain>:native`. Token identity is `<chain>:token:<contract-or-mint>`;
symbols are presentation only. Optional asset input accepts `native` or that full token ID.
Even without an asset filter, each path stays homogeneous and metric totals remain separated
by asset. Arithmetic uses Decimal, never browser floating point. No USD conversion exists.

Chronological mode defaults ON: every edge needs a timestamp, and each timestamp must be
at least the preceding timestamp. Turning it off permits timeless/reverse-time graph
connectivity, not a chronological value-flow claim. Optional start/end times are inclusive
and require timezone-aware API input; UI datetime fields are explicitly UTC. The original
stored graph is unchanged.

## Algorithms and bounds

- `shortest`: bounded breadth-first enumeration of equally shortest simple paths.
- `simple`: bounded breadth-first enumeration of simple paths within the hop limit.
- `widest`: priority queue ranked by the minimum transfer amount along each path. It requires
  one explicitly selected asset and precise account-chain edges. **Observed path capacity**
  does not prove that the same funds traversed all transfers or belong to one owner.

No path revisits an address. Default depth is 3; hard maximum is 6. Default result cap is
20 paths (hard maximum 100), explored-address cap 1000 (hard maximum 5000), and explored
transition cap 10000 (hard maximum 20000). Analysis has a 5-second collection/projection/traversal/metrics
deadline, at most 5000 loaded transaction rows, 16 MiB of raw JSON, and 1000 distinct local
Label targets. `truncated` and `limiting_reasons` expose cutoffs; partial results never claim
exhaustiveness. Hop depth is an explicit query scope, not coverage of the full chain.

Account collection follows bounded outward frontiers using chain/from-address indexes and
reads source-wallet incoming edges for metrics. Case-insensitive EVM queries use expression
indexes. Time and asset filters are applied locally. BTC/LTC needs a bounded chain-local
raw scan because input/output arrays are not separately indexed. A resource cutoff leaves
an explicitly incomplete local dataset. Missing paths may require explicit additional
collection through existing Wallet workflows.

## Metrics and targets

Fan-in/out reports distinct counterparties, distinct events and observed amounts by asset.
Repeated counterparties retain direction, count, first/last observed time and asset-separated
amount. UTXO metrics describe participation/connectivity only and omit allocated amounts.
Consolidation means multiple observed incoming counterparties; it is not an accusation.
Metrics share the selected local-data/time/asset scope and any truncation limitations.
Metric row disclosure is bounded by the selected node cap; omitted rows set `max_metric_rows`.
Self transfers do not count the source as a distinct counterparty.

A wallet, exact local Label, or Label category defines the target set. Chain-specific and
explicit `any` labels are considered; labels never add edges or propagate risk. Source and
target stay on one chain. Bridge inference, Attribution graph nodes, technical-cluster
collapse/target selection, and peel-like heuristics are deferred. Paths remain address-level.

## Reproducibility and historical material

Each explicit request stores an immutable run: parameters, algorithm/version
`observed_flow_v1`, resolved targets, ordered paths, metrics, exclusion counts, truncation,
data fingerprint, snapshot time and latest observed timestamp. Fingerprints use sorted
material, excluding generated run IDs and capture times. The fingerprint covers loaded
source rows, including rows excluded during projection. The cutoff is a SQLite snapshot,
not a claim of finalized or complete blockchain history. Later collection does not rewrite
old runs. Identical data/parameters produce identical ordered results unless a wall-clock
resource cutoff intervenes; timeout-truncated runs explicitly record that limitation.

An explicit Case action pins the complete run snapshot. JSON/Markdown/HTML/PDF reports read
that fixed pin. SQLite triggers protect run and Case-pin updates; no automatic Case inclusion
occurs. Analyst-selected paths use existing blockchain events, not technical-cluster ownership.

## UI and API

Fund Flow provides source, target definition, chain, optional asset, algorithm, depth, UTC
window and temporal mode. Neighborhood mode exposes outward paths and wallet metrics.
Only the selected returned path is drawn at a time, with source/target highlights and event
provenance details; this is progressive disclosure of bounded results, never the whole graph.
Stored runs can be reopened by ID. Pinning is explicit and historical Case views have no
repinning action.

Routes under `/api/greedy-collector/fund-flow`:

- `GET /capabilities`
- `POST /path`
- `POST /neighborhood`
- `GET /runs/{id}`
- `POST /cases/{case_id}/pin` with `run_id`

## Migration and verification

`20260927_02` follows `20260927_01`. It adds only immutable run storage/protection and
composite transaction indexes for chain/from/time, chain/to/time, folded EVM address/time,
and chain/asset/time. Existing unique chain/transaction/event identity remains unchanged.
Startup never creates this subsystem's tables. An explicit operator migration is required;
the configured user database is never inspected or migrated by this work. Empty downgrade
is supported; retained run/pin material blocks destructive downgrade.

Automated tests use isolated temporary SQLite and test-only provider fixtures. Production
contains no canned paths, wallets, transfers or graph datasets.
