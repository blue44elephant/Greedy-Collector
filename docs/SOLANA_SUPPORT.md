# Solana mainnet support

Greedy Collector registers Solana as `solana`, an account-family chain with native asset `SOL` and 9 decimal places. It is not EVM-compatible. The adapter is read-only and does not create or use keys, sign, submit transactions, stake, vote, or connect to wallets.

## Identifier and RPC assumptions

Solana account addresses are base58 strings that decode to exactly 32 bytes. This includes public keys and program-derived account addresses; Solana addresses do not use Bitcoin-style Base58Check. Transaction identity is the first transaction signature: a base58-encoded 64-byte Ed25519 signature. Address and signature validation are local and make no provider request. Unqualified addresses/signatures are considered Solana only after higher-priority supported BTC, EVM, and TRON syntax has not matched.

`SOLANA_RPC_URL` selects a private JSON-RPC endpoint. It is treated as sensitive because credentials may be embedded in its URL; the application does not return or log the configured URL. If unset, the adapter uses `https://api.mainnet.solana.com`. Solana documents this public mainnet endpoint as rate-limited, without production guarantees or an SLA. Use dedicated infrastructure for production workloads.

Balance reads use `getBalance` at `finalized` commitment. Integer lamports are divided by 1,000,000,000 using decimal arithmetic. Signature discovery uses `getSignaturesForAddress` at `confirmed` commitment; each returned signature is then retrieved with `getTransaction`, `encoding: jsonParsed`, and `maxSupportedTransactionVersion: 1`. This decodes legacy, v0, and current documented v1 transactions. Unknown future versions and RPC rejections are retained as safe activity metadata without interpreting transfers. Parsed account keys include versioned lookup-table addresses; the normalizer also accepts RPC `loadedAddresses` metadata. Inner-instruction group indexes identify their originating outer instruction.

The initial history lookup is limited to 50 signatures. An explicit adapter collection limit is capped at 100 per page, and pagination uses the `before` signature cursor. There is no block scan and no unlimited/lifetime-history claim. Requests are sequential and bounded. 403, 429, timeouts, transport/server errors, malformed JSON-RPC, and unavailable transactions become sanitized provider errors. At most one retry is made when a numeric/date `Retry-After` requests a delay of two seconds or less; longer or missing delays end the retrieval without a retry.

## Normalized transfers

Successful System Program `transfer` instructions are normalized from top-level and CPI inner instructions. SOL values use integer lamports and exclude the transaction fee; the fee is metadata and never a counterparty flow. Failed transactions remain activity metadata and do not create transfer edges.

Fungible SPL Token and Token-2022 `transfer` and `transferChecked` instructions are parsed only when mint, integer amount, and decimals are available from parsed instruction fields or transaction token-balance metadata. The mint is the asset identity. Symbols are display metadata, never token identity. Token-2022 extension effects can change the amount made available to a recipient; the saved amount is identified as the parsed instruction amount and is not a claim of net credited balance. NFTs, token portfolios, and extension-specific decoding are not implemented.

Source and destination token-account addresses are retained as provenance. Owner wallet addresses are used for graph/counterparty endpoints only when the transaction's `preTokenBalances` or `postTokenBalances` explicitly supplies those owners for the matching token account and mint. Missing ownership remains unknown; no owner is derived from account naming or instruction authority.

Each event uses a stable instruction path: top-level `solana-ix:<outer-index>` or CPI `solana-inner:<outer-index>:<inner-index>`. Thus distinct transfers in one signature remain separately persistable and alert-deduplicated, while repeating the same instruction path is idempotent. The graph shows only normalized asset transfers. Program invocation, shared program use, and shared mints do not establish common ownership.

## Monitoring and other workspaces

Solana monitoring uses the registry's explicit monitoring capability, a silent first baseline, confirmed signature history, and a bounded 100-signature catch-up window. Later polls fetch transactions only for signatures newer than the saved signature boundary; multiple events in a transaction remain distinct. Missing boundaries produce the existing continuity-loss status rather than silent advancement. Monitoring requires the application or configured scheduler to be running.

Local Labels, chain-scoped Cases/Attribution references, manual source observations, and generic exact-address GitHub code search accept Solana addresses through registry validation. ENS remains Ethereum-only and GraphSense remains BTC/Ethereum-only. No Solana-specific behavioral risk heuristics are enabled; generic sourced-label evidence remains available.

There is no database migration. NFTs, recursive collection, staking/voting, signing or transfer operations, token-balance portfolio display, program decompilation, ownership inference, and Solana-specific risk rules are out of scope.

## Official documentation checked

- [Accounts](https://solana.com/docs/core/accounts) and [Terminology](https://solana.com/docs/references/terminology): account-address and signature identity.
- [getBalance](https://solana.com/docs/rpc/http/getbalance), [getSignaturesForAddress](https://solana.com/docs/rpc/http/getsignaturesforaddress), [getTransaction](https://solana.com/docs/rpc/http/gettransaction), and [RPC JSON structures](https://solana.com/docs/rpc/json-structures): commitment, cursors, parsed transaction fields, versions, inner instructions, and loaded keys.
- [Clusters and public RPC endpoints](https://solana.com/docs/references/clusters): mainnet URL, public rate limits, and production limitation.
- [Transactions](https://solana.com/docs/core/transactions), [Token Extensions](https://solana.com/docs/tokens/extensions), and [Transfer Fees](https://solana.com/docs/tokens/extensions/transfer-fees): instruction model and extension-aware transfer boundaries.
