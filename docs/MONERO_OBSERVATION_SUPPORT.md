# Monero observation-only support

Monero is registered as a privacy-family chain for local public-address reference work. Its
address resolver is offline: it checks CryptoNote Base58 encoding, decoded payload size,
mainnet address prefix, Keccak checksum, and the Edwards-point encoding of both public keys.
It accepts standard addresses, subaddresses, and integrated addresses. It does not contact a
Monero node or explorer.

## Available operations

The declared capabilities are address validation, local Labels, Cases, Attribution, and generic
Discovery. Manual analyst source capture and public GitHub code-mention discovery can use the
chain-qualified address subject. ENS remains Ethereum-only, and GraphSense remains limited to
Bitcoin and Ethereum. These observations are candidate evidence, not identity or ownership
claims.

## Public-data limitations

The application does not retrieve Monero balances, address-level transaction history,
counterparties, transaction details, or graphs. It does not support Monero monitoring, pending
transactions, token transfers, or transaction case references. The Wallet workspace shows an
observation-only state and does not send an address to a provider. A report states that public
address-level transaction reconstruction is unavailable; this limitation does not indicate
inactivity.

No private key, seed, recovery phrase, or view key is requested, stored, or accepted for these
operations. Integrated-address payment data is not exposed as a separate field. Any future
provider-based collection or private view-key feature requires a separate, reviewed capability
and task.
