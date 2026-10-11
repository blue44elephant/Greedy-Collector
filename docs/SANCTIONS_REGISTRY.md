# Authoritative sanctions registry (SANC-1)

Greedy Collector synchronizes the **OFAC SDN** list only when an analyst selects
**Refresh OFAC data** or calls `POST /api/greedy-collector/sanctions/sync`.
Wallet screening then reads the local SQLite registry. It makes no OFAC or
blockchain provider request. The system never creates watches, alerts, labels,
Attribution claims, or risk points during sync.

## Official source and parser

The source adapter uses the supported [OFAC SDN XML product](https://ofac.treasury.gov/sdn-list-data-formats-data-schemas/frequently-asked-questions-on-advanced-sanctions-list-standard)
from the [Sanctions List Service](https://ofac.treasury.gov/sanctions-list-service),
using `https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.XML`.
It requires the [current OFAC XML namespace](https://ofac.treasury.gov/recent-actions/20240507_44)
and exact `Digital Currency Address - ASSET` ID fields. This is the complete
SDN XML file, not the consolidated non-SDN list or a delta file. The parser
rejects changed roots, DTDs, invalid XML, duplicate IDs, empty identifiers, and
implausibly small production lists. The byte limit is 80 MiB. OFAC's endpoint
currently redirects to its pinned SLS publication bucket; the fetcher permits
only that exact host and a `/Published/.../SDN.XML` path. Redirects elsewhere fail.
The canonical source URL, not a signed bucket URL, is stored in provenance.

Every complete fetch gets a local SHA-256. [OFAC publishes signatures alongside
SLS downloads](https://ofac.treasury.gov/specially-designated-nationals-list-sdn-list/hash-values-for-ofac-sanctions-list-files),
but no stable machine-readable signature endpoint was identified for this XML
product. Automatic sync records official integrity as **unavailable**. The service
can verify an officially supplied SHA-256 when available to a trusted adapter;
a mismatch fails before activation. It never presents a local hash as an OFAC
verified signature.

## Immutable snapshots and screening

A successful sync stages one snapshot, its source entities, programs, aliases,
and all digital-currency IDs in one database transaction. Only after validation
does the current-snapshot pointer change. Failed attempts receive a separate
failure event; the previous complete snapshot stays current. A database lease
rejects concurrent sync. The lease expires after five minutes after an abrupt
process failure. Every complete snapshot remains auditable even when source
bytes are identical.

Screening accepts `(chain, canonical wallet address)` and returns a listing
state plus a match type. A direct match requires an authoritative asset/network
label mapped to that same GC chain and a valid adapter-canonical address.
`EXACT_TEXT_MATCH_CHAIN_UNRESOLVED` and `TEXT_MATCH_OTHER_CHAIN` are separate
review signals. They are not direct matches. Multiple OFAC entity associations
and programs remain separate. When an identifier disappears from a later
**complete** snapshot, GC labels it historically listed. `observed_removed_at`
is the first local snapshot where absence was observed, not OFAC's official
delisting date. A failed sync cannot infer removal. An unsynchronized registry
returns `REGISTRY_NOT_SYNCED`; a no-match against a snapshot older than 72 hours
returns `REGISTRY_STALE` and the snapshot date is visible.

Explicit XBT/BTC, ETH, LTC, TRX, SOL and XMR labels map to GC chains after
adapter validation. An explicit supported EVM network label maps only to that
network. Generic USDT/USDC and unsupported asset labels are retained with raw
source text and unresolved/unsupported chain mapping. The same `0x` text on
Ethereum and Base does not become a direct Base match from an ETH ID.
Monero addresses can be screened locally even though public-chain tracing is
unsupported.

## Workflows

The Sanctions workspace shows source and retrieval metadata, local SHA-256,
entity/identifier counts, asset and chain counts, unresolved IDs, sync state,
and bounded search by address, entity, alias, program, asset, chain, and
current/historical snapshot status. The Wallet panel shows direct matches
prominently and historical matches with different wording, alongside the
existing independent behavioral risk score. Stored Wallet and Monero observation
views call only the local screening endpoint.

`wallet.ofac_sdn_match` is a local Discovery transform with zero external
requests. It retains the source snapshot, identifier, entity, programs, match
type, and listing state as reviewable source material. It does not create an
Attribution entity or claim. A separate analyst action can pin the full
screening result to a Case; the pin remains an immutable historical record
through later OFAC refreshes. The registry is distinct from GC Labels and
from risk scoring. RISK-2 will audit how sanctions status should interact with
risk; SANC-1 does not change that model.

## Operator use

Run the focused Alembic migration as part of normal application setup:

```powershell
cd "C:\Tools\Inventions\greedy-collector"
alembic upgrade head
uvicorn main:app --reload
```

Open `http://127.0.0.1:8000/`, select **Sanctions**, and click **Refresh OFAC
data**. Review the snapshot ID, retrieved time, SHA-256, counts, and integrity
state before screening a known public address. This is an optional explicit
live operator check; automated tests use local XML fixtures and temporary SQLite.
Do not enter private keys or recovery phrases.
