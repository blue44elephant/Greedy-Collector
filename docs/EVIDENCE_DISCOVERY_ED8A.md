# ED-8A: Ethereum ENS primary-name Discovery

Implemented transform: `wallet.ens_primary_name`, source `ens_ethereum`.
The ED-8A0 storage and ED-8A1 normalization prerequisites remain unchanged.

## Official contract verification (2026-09-17; rechecked 2026-09-22)

The [official Universal Resolver guide](https://docs.ens.domains/resolvers/universal/)
documents mainnet DAO proxy `0xeEeEEEeE14D718C2B47D9923Deab1335E144EeEe`.
GC stores this in `UNIVERSAL_RESOLVER`; it is not analyst-editable.
`reverse(bytes lookupAddress,uint256 coinType)` returns
`(string primary,address resolver,address reverseResolver)`.
[ENSIP-19](https://docs.ens.domains/ensip/19/) specifies raw 20-byte Ethereum
addresses and coin type **60**. This is mainnet primary-name discovery, not
L2/default-EVM resolution or ENSv2-only functionality. Deployment is verified
against current documentation, not a live RPC probe.

[ENSIP-23](https://docs.ens.domains/ensip/23/) and the
[official interface](https://github.com/ensdomains/ens-contracts/blob/staging/contracts/universalResolver/IUniversalResolver.sol)
specify built-in forward verification, an empty primary when unset, and
`ReverseAddressMismatch` when the forward address does not match. ENSIP-23 is
marked draft; the public interface guide and contract were also checked.

## RPC and fixed ABI

Reuse `EthereumAdapter._alchemy` with its existing Alchemy configuration, URL
and JSON-RPC envelope. Its new opt-in bounded path uses the shared httpx
transport, timeout at most 20 seconds, a 16 KiB uncompressed response cap, no
redirects, no automatic retries and no environment proxy. Existing Ethereum
lookup/balance behavior is unchanged. Only one `eth_call`, at `latest`, is
charged through Discovery's execution context; no second forward lookup.

No installed ABI utility was available. A narrow codec handles only this fixed
signature: selector `0x5d78a217`, dynamic bytes offset 64, coin 60, length 20,
raw address bytes and ABI padding. Return decoding requires offset 96, canonical
address padding, bounded length, strict UTF-8, zero string padding and exact
tuple length. Name bytes are capped at ED-8A1's 2048 bytes. Tests pin exact
calldata, tuple decoding and malformed responses. No new dependency was added.

## Normalization and technical verification

Every nonempty primary passes through the existing backend
`normalize_ens_name()` bridge (`@adraffy/ens-normalize` 1.11.1, Unicode 17).
Normalization runs off the async event loop; cancellation is checked before
storage. Its output must equal the raw returned name. No lowercasing, IDNA,
punycode, NFC or repair is performed. ENSIP-19 requires the reverse name to be
already normalized; forward verification of one spelling cannot be transferred
to a changed spelling. The Universal Resolver's literal name encoding is not a
replacement for ENSIP-15 validation.

## Configuration, planning and cache

Requires `ALCHEMY_API_KEY` and usable ED-8A1 Node/local normalization dependency.
Etherscan is not needed for this transform. Capability metadata reports
implemented=true but configured/executable=false if either prerequisite is
missing. Import/startup does not invoke RPC or the normalizer. Capability checks
may perform the cached local normalizer self-test; they consume no RPC quota.

Cost class `LIMITED_FREE`; request unit, maximum one attempt/result per run,
30-second execution deadline, 10 attempts/minute, local reservations capped at
100 units/day and 3000/month. These are GC guardrails, not promises about an
Alchemy subscription. Existing budgets, cancellation, terminal immutability,
idempotency and remote cache are reused. TTL is **3600 seconds**. Refresh bypasses
cache. Empty successes are cacheable; mismatches/unsupported resolution are
incomplete and not cached. Cache hits retain original observation timestamps.

## Safe outcomes

- Empty primary: bounded successful zero results; “No verified ENS primary name returned.”
- `ReverseAddressMismatch` (`0xef9c03ce`): zero positive results and safe
  `reverse_forward_mismatch`; incomplete resolution, not a spoofing judgment.
- [EIP-3668](https://eips.ethereum.org/EIPS/eip-3668) `OffchainLookup`
  (`0x556f1830`): `ccip_read_unsupported`; no gateway URLs, callback chains or
  arbitrary HTTP fetching. Some legitimate ENS records are therefore unavailable.
- Resolver failures retain only closed diagnostics; malformed ABI/JSON-RPC,
  rejected/changed names, timeouts, rate limits, missing configuration and
  transport failures use existing typed execution errors.

Diagnostics occupy the existing source execution metadata (`quota_snapshot`),
with a closed schema; no new database field or error enum is required. Raw
provider messages/revert data, request URLs, credentials, headers and helper
paths are never persisted in results or errors.

## Stored result and identity

Result kind is the existing `candidate_relationship`; **observation** kind is
`name_service_record`. Endpoint `ens_name`, namespace `ethereum`, canonical
value is the verified ENSIP-15 name. Predicate/direction:

`ENS name --resolves_to--> Ethereum blockchain_address`

Fact key is empty; stable relationship identity depends on the canonical name,
wallet and predicate, not retrieval clocks, display formatting or response order.
Observation verification uses existing `technical_verified`; match context and
snapshot record `forward_verified` / `universal_resolver_reverse`.
Provenance contains name, canonical wallet, namespace, coin type, fixed contract,
returned resolvers, provider identifier `alchemy`, and source versions plus
retrieval timestamp in the existing observation/execution model. No confidence
of 1.0 or ownership inference is added.

## UI, graph, review and Attribution

Ethereum wallet handoff only prefills a subject; no pivot is preselected/run.
Bitcoin is incompatible. ENS roots remain output-only. Result details show name,
wallet, Forward verified, source/provider, method, resolver addresses and original
retrieval time. Empty/mismatch/CCIP outcomes display bounded explanations.

Graph ENS cards show name and Ethereum/Forward verified, with an inbound
`resolves_to` arrow to the wallet. Details include full immutable provenance,
run/current observation counts, current review and promotion counts. ENS uses a
deterministic lower lane sorted by node ID, 410px columns and 190px rows, starting
260px below the lowest existing node. Existing wallet/label/code positions are
unchanged; a 100-result page retains every node. Old foundation-only unverified
ENS material remains explicitly unrendered rather than being called verified.

Opening an old run selects its included observation, never the latest name.
A changed primary creates a distinct relationship/observation. Current analytic
status is clearly separate from historical material. A new observation starts
Unreviewed. Only explicitly Relevant verified production material is eligible
for ED-6 promotion. Existing claim selection/creation, explicit stance,
directness, rationale and confirmation remain required; no default Supports.
Capture origin is `public_osint`; snapshot retains all immutable technical
provenance and cannot be rewritten by a later name change.

A verified ENS relationship does **not** establish real-world/legal identity,
wallet operator, beneficial ownership or company ownership. No Entity, Claim,
Label, assessment, risk change or Case inclusion is automatic.

## Boundaries and verification

No text records, avatar, contenthash, ownership history, events/logs, enumeration,
name-owned queries, L2 lookup, signing, wallet connection or transaction/history
collection. Production contains no sample results or fixture imports.

Tests use mocked RPC, the actual local normalizer, isolated SQLite and normal
API/services. Coverage includes capability/configuration, exact calldata, safe
protocol errors, normalization, cache expiry/refresh, provenance, graph direction,
review, explicit promotion and immutable history. `node tests/browser_discovery.cjs ens`
uses a migrated isolated database for positive, changed-name, mismatch, empty and
cached-empty workflows and all nine workspace navigation. No live provider calls.

Alembic remains `20260916_01`. ED-8A adds no migration or user-database migration
step. Missing schema is handled by existing gates. The ENS HTTP tests also bind
application startup to their temporary database, independently of route overrides.
For full-suite verification, explicitly set `PYTHON_DOTENV_DISABLED=1` and
`GREEDY_COLLECTOR_DATABASE_URL` to a temporary SQLite file before running pytest:
older test fixtures can otherwise open the configured database during lifespan.
