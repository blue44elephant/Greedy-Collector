# CL-1 technical wallet clustering

Technical cluster != real-world owner. Observation, annotation, attribution and risk remain
separate. CL-1 never creates an Entity, Claim, Label, risk assessment or watch automatically.
Chain expansion remains frozen at ten chains.

## Source and execution

The Bitcoin and Litecoin normalizers preserve the provider's full `vin`/`vout` in
`transactions.raw_payload`; `persist_normalized_event` stores that JSON durably. CL-1 uses
these original input prevouts, never the lossy representative `from_address`/`to_address`.
Historical or partial records with missing/unresolved prevouts are excluded. Conflicting
wallet-relative views of the same transaction are excluded. Standalone transaction lookup
does not persist records; use existing Wallet collection explicitly when more data is needed.

Use **Technical clusters > Analyze stored evidence** or **Wallet > Analyze technical cluster**.
An analysis covers the selected chain's bounded local store, not just the selected wallet.
There are no provider calls, background clustering, recursive collection, or fake runtime data.
No automatic heuristic is available for Ethereum, Base, Arbitrum, BSC, Polygon, TRON,
Solana or Monero. Monero remains observation-only.

## Heuristic and exclusions

`utxo_common_input_v1` deduplicates valid, canonical spent input addresses. At least two
are necessary. Outputs never become members, and no change-address heuristic is applied.
Union-find combines accepted shared-input sets transitively in approximately linear time.
A shared-input set is direct technical evidence, not a transaction arrow between its inputs.
A-B and B-C can group A/B/C without inventing A-C direct evidence.

Eligibility requires complete input prevouts and output integer values, valid addresses,
and provider-confirmed status. Coinbase/unresolved inputs, incomplete outputs, and pending or
unknown confirmation state are excluded. Existing stored confirmation state may be stale;
CL-1 never changes provider/storage collection behavior to repair it.

Conservative structure checks exclude transactions with **20 or more inputs or outputs** as
`collaborative_spend_possible`, and with **at least three distinct input addresses and at least
three identical positive-valued outputs** as `coinjoin_like`. These are exclusion signals,
not definitive CoinJoin detection. This deliberately sacrifices recall. Small PayJoin,
custodial aggregation and multisig/shared-control arrangements can evade the checks. A
2-input transaction is not declared safe. No numeric ownership probability is assigned.

Exchange, Mixer, Bridge, Service, Custodian and Gambling label categories appear as immutable
counter-indicators on evidence, never as topology instructions. Labels apply only in their
chain or explicit `any` scope. Refreshing label context may create new evidence versions.

An analyst can exclude a transaction with a required 1-1000 character rationale. The evidence,
rationale and ISO-8601 UTC audit time are retained. Exclusion applies across future snapshots
of that chain/transaction so reingestion cannot bypass it. Exclusion immediately recomputes
components and may split/dissolve a cluster. Exclusions cannot be silently edited or removed;
CL-1 has no reinclusion or unrestricted manual merge workflow.

## Identity and history

Persistent UUID cluster IDs are independent of member hashes. Each material change creates
an immutable version containing members, evidence IDs and complete evidence snapshots,
checks, exclusions, warnings and limitations. Unchanged reruns reuse the version. The SHA-256
material fingerprint uses sorted state, excluding generated audit timestamps and random IDs.
Transaction block time remains original epoch seconds from the source; capture/recompute
and analyst-exclusion times use ISO-8601 UTC.

On merge, the lexicographically first overlapping existing cluster ID survives; on split,
the first component in canonical address order retains an available overlapping ID. Others
receive new persistent IDs. Retired IDs receive an empty `superseded_or_dissolved` version.
Prior versions remain accessible; none are silently reinterpreted under a later heuristic.

SQLite `BEGIN IMMEDIATE` serializes writes, exclusions and case pins. Foreign keys and
immutable update/delete triggers protect evidence and historical versions. An explicit
Case action pins cluster ID, version, members and complete evidence/exclusion material;
reports read this pin, never the latest cluster. JSON/Markdown/HTML/PDF retain the disclaimer.
Removing a Case reference does not delete the underlying cluster history.

## Graph and scale bounds

The transaction Graph is unchanged. **Technical Cluster overlay** defaults OFF and badges
returned focus-cluster members with cluster ID/version. It adds no transaction edges and
never collapses nodes. Evidence inspection exposes the original shared-input sets; other
membership is transitive. Reanalysis invalidates an enabled overlay. Unsupported chains
have no dead analysis or overlay button.

Analysis refuses more than **5000 stored transaction rows or 16 MiB of raw JSON** per chain,
or more than **10000 local label rows**. It does not silently truncate and writes no partial
result. Components over **500 members or 1000 associated evidence items** are marked
`review_required`. More than **50000 memberships across component evidence disclosures**
is refused to bound replication of large excluded transactions. Graph pages contain at most
**100 members and 100 direct evidence sets**; counts and next member offset are explicit.
Complete underlying evidence is available from the immutable version endpoint. The UI
progressively renders members/evidence (50 at a time) and clusters (10 at a time), with no
massive automatic layout or pairwise clique generation.

## API and migration

All routes are under `/api/greedy-collector/clustering`:

- `GET /capabilities`
- `POST /analyze` with `chain`
- `GET /clusters/{id}?version=N` (omit version for current)
- `GET /clusters/{id}/graph?version=N&offset=0&limit=100`
- `GET /wallet/{chain}/{address}`
- `POST /evidence/{id}/exclude` with `reason`
- `POST /cases/{case_id}/pin` with `cluster_id` and `version`

Migration `20260927_01` follows `20260923_02`. It creates only dedicated technical cluster
tables, indexes and protection triggers. Historical migrations are unchanged. Startup does
not create these tables or migrate an operator database. Uninitialized clustering returns a
safe unavailable response. Downgrade refuses retained clustering material. Development and
verification use temporary SQLite only; applying this migration to a user database remains
an explicit operator action.

No graph library, provider, chain, frontend framework, signing or private-key capability
was added. CL-1 adds zero risk points and never spreads labels or monitoring across members.
