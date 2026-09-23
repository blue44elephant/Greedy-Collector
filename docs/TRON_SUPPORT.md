# TRON mainnet support

Greedy Collector registers TRON mainnet as chain ID `tron`, display name **TRON**,
native asset **TRX**, and account-family precision 6. TRON is not marked as an EVM chain.

## Address and identity

The canonical wallet form is the 34-character user-facing Base58Check `T...` address.
Validation is local: Base58 alphabet, decoded length, `0x41` network prefix, and the
double-SHA-256 checksum are all checked without provider traffic. Internal conversion to
and from exact 42-character `41...` hex is supported. A bare `0x...` Ethereum address is
never accepted as TRON. Matching 20-byte payloads on Ethereum and TRON remain separate
`(chain, address)` identities with no ownership inference.

These assumptions follow the official [TRON address encoding documentation](https://developers.tron.network/docs/encoding).

## Provider and bounds

The adapter uses mainnet TronGrid at `https://api.trongrid.io`. Configure
`TRON_PRO_API_KEY`; the server sends it in the `TRON-PRO-API-KEY` header. It is never
included in browser requests, stored provider metadata, logs, or public errors.

Read-only endpoints:

- `GET /v1/accounts/{address}` for account state and TRX balance;
- `GET /v1/accounts/{address}/transactions` for confirmed TRX/TRC-10 activity;
- `GET /v1/accounts/{address}/transactions/trc20` for confirmed TRC-20 transfers;
- `POST /walletsolidity/gettransactionbyid` for bounded solidified transaction lookup.

The two history streams use `limit=200`, `only_confirmed=true`, newest-first ordering,
and TronGrid fingerprint pagination. Each stream stops after five pages: at most about
1,000 ordinary records plus 1,000 TRC-20 records before deterministic merge and event
deduplication. This is bounded indexed history, not lifetime or consensus-complete
coverage. Safe error categories cover rejected requests, missing/invalid credentials,
not found, rate limiting, provider failures, malformed/oversized responses, timeouts,
and transport failures. Requests are not retried without bound.

Official references: [TronGrid V1 overview](https://developers.tron.network/reference/trongrid-v1-api-overview),
[API key security](https://developers.tron.network/reference/security-settings),
[TRC-20 account history](https://developers.tron.network/reference/get-trc20-transaction-info-by-account-address),
and [confirmation semantics](https://developers.tron.network/docs/confirmation-semantics).

## Amounts and activity

TRX balance and native transfers use exact decimal arithmetic with 1 TRX = 1,000,000 sun.
Ordinary `TransferContract` activity is normalized as TRX. `TransferAssetContract` is
retained as TRC-10 with its returned asset identifier and integer amount. Other contract
types retain an explicit unsupported-type marker without guessed endpoints or values.

TRC-20 rows retain transaction ID, timestamp, endpoints, token contract, symbol, name,
decimals, raw integer value, normalized amount, and confirmed state. Metadata comes from
the indexed response; no token such as USDT is hard-coded. Stable event identities keep
distinct transfers sharing one transaction ID separate through lookup, monitoring, and
graph presentation where the existing storage identity permits them.

## Generic application support

TRON participates in Wallet lookup, counterparties, stored graph traversal, confirmed
watchlist monitoring, chain-scoped Labels (plus `any` scope), Cases, Attribution, manual
source capture, local-label Discovery, and exact-address GitHub code mention Discovery.
ENS remains Ethereum-only. GraphSense remains Bitcoin/Ethereum-only.

The generic label-based risk exposure path remains available. BTC/ETH behavioral rules
are disabled for TRON, and MC-2 adds no new risk heuristic. Monitoring runs only while
the application is running, starts with a silent baseline, deduplicates stable native and
TRC-20 event identities, and reports continuity loss if its bounded prior boundary drops
out of provider history.

Unsupported features include pending/mempool monitoring, internal transactions, NFTs,
staking/resource analytics, arbitrary smart-contract decoding, recursive collection,
signing, broadcasting, and all other blockchain writes.
