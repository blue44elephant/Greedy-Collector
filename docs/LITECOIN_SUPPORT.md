# Litecoin transparent-chain support

Greedy Collector supports Litecoin mainnet transparent addresses and UTXO records. It does
not claim to inspect all Litecoin history. The chain uses the existing UTXO normalization,
storage, deterministic risk, graph, and monitoring workflows.

## Address and identifier handling

Local validation accepts mainnet Base58Check P2PKH (version 48), the shared script-address
prefix 5, Litecoin's alternate script prefix 50, and SegWit addresses using `ltc1` Bech32 or
Bech32m. MWEB addresses are not accepted: this integration only covers transparent address
history, and the configured public address API does not document MWEB address-level history.

Bare 64-hex transaction IDs continue to resolve as Bitcoin under the established resolver
precedence. Select the Litecoin network hint to look up a Litecoin transaction ID. A prefix-5
script address is valid syntax on both Bitcoin and Litecoin and may be reported as ambiguous;
select the intended network rather than guessing. Resolution makes no provider request.

## Provider and bounds

The read-only adapter uses LitecoinSpace's Esplora-compatible JSON API. `LITECOIN_API_URL`
sets the HTTPS API base and defaults to `https://litecoinspace.org/api`; it is server-side
configuration, is never sent to the browser, and requires no API key. The adapter performs
bounded GET requests only.

Balances use integer litoshi inputs and exact decimal strings. The provider's reported address
transaction count is separate metadata. Address history returns at most 75 confirmed records
from three pages and up to 50 initial mempool records. This is bounded provider history, not a
wallet's total lifetime transactions. Transaction lookup uses the provider's transaction
endpoint.

For multi-input or multi-output UTXO transactions, the normalized sender/recipient edge is
omitted unless provider data gives one distinct input address and one distinct output address.
The original provider participants remain in the stored transaction payload for inspection.
An emitted arrow represents observed transaction direction; it does not establish ownership
or wrongdoing.

Litecoin has no token-transfer capability. Its adapter opts out of the existing chain-specific
behavioral risk indicators; deterministic shared rules remain available. Monitoring uses
provider-returned history and the existing confirmed-boundary behavior. A graph contains stored
relationships only and is not complete chain coverage.

