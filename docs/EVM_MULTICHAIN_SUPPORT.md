# Generic EVM multi-chain support (MC-3B)

Greedy Collector now supports public address, bounded transaction history, native
balance, token-transfer, transaction lookup, monitoring, graph, risk, labels, cases,
Attribution and generic Discovery workflows for Ethereum, Base, Arbitrum One, BNB Smart
Chain, and Polygon. The application continues to use its existing SQLite state and
chain-qualified identities. No migration or data rewrite is required.

| Registry ID | Network | EVM chain ID | Native asset | Explorer |
| --- | --- | ---: | --- | --- |
| `ethereum` | Ethereum | 1 | ETH | [Etherscan](https://etherscan.io) |
| `base` | Base | 8453 | ETH | [Basescan](https://basescan.org) |
| `arbitrum` | Arbitrum One | 42161 | ETH | [Arbiscan](https://arbiscan.io) |
| `bsc` | BNB Smart Chain | 56 | BNB | [BscScan](https://bscscan.com) |
| `polygon` | Polygon | 137 | POL | [PolygonScan](https://polygonscan.com) |

## Shared Etherscan V2 provider

The five networks use the existing `ETHERSCAN_API_KEY` setting and the Etherscan V2
endpoint. Each adapter sends its descriptor's numeric `chainid`; native balance,
`txlist`, `tokentx`, and transaction lookup stay server-side. History remains bounded
to ten pages of 1,000 rows per account-history stream. Amounts are normalized with
`Decimal` and returned as strings. The API key never appears in public chain metadata
or browser code.

Etherscan V2 supports one account key across chain endpoints, but API-plan coverage,
limits and quotas are not identical across networks. Check the provider's current
[Supported Chains](https://docs.etherscan.io/supported-chains) and account plan before
enabling network retrieval. Missing server configuration is reported as a safe
chain-specific configuration error. Alchemy remains an optional **Ethereum mainnet
balance fallback only**; it is not used for the other four networks or Etherscan history.
Bitcoin and TRON provider configuration is unchanged.

## Identifier routing

The resolver is local and performs no provider request. Bitcoin addresses use the
existing Bitcoin adapter validator; all five EVM networks use the shared existing EVM
syntax validator. Shared EVM address/hash syntax and bare BTC/LTC/TRON transaction IDs
now return explicit ambiguity. Choose the Wallet **Network hint** before provider retrieval.
No chain is selected merely because it was historically the default.
Other text is reported as an unknown supported identifier; no provider is queried.

`GET /api/greedy-collector/chains` supplies the current chain selector options and safe
metadata, including EVM chain ID, native symbol/precision, capabilities, and explorer
link. Local syntax validation and stored-data work do not require provider keys; live
retrieval does.

## Capability and coverage boundaries

The new descriptors opt into existing generic graph traversal, scheduled monitoring,
local Labels, cases, Attribution and Discovery mechanisms. Discovery's generic local
labels, manual-source and GitHub transforms derive eligible chains from capabilities.
GraphSense remains explicitly limited to Bitcoin/Ethereum. ENS remains explicitly
limited to Ethereum. No recursive collection, new heuristics, ownership inference,
new data source, or chain-specific discovery transform is added.

Transaction history is bounded by provider/API limits and pagination; it is not a claim
of lifetime-complete records. Graphs represent relationships currently stored in Greedy
Collector, not complete chain coverage. Native and token amounts retain exact decimal
strings; no floating-point conversion is used. Monitoring interval defaults for the new
EVM networks use the existing Ethereum monitoring interval setting.

## Verification scope

Automated provider tests replace HTTP reads with deterministic test-only payloads.
Production paths contain no seeded wallet, transaction, graph or provider fixture data.
