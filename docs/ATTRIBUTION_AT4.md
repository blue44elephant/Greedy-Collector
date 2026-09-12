# AT-4: Wallet and Graph attribution

Wallet and selected Graph wallets now summarize persisted attribution through the existing AT-2 API. Attribution remains an explicit analyst claim, separate from labels, deterministic risk, and blockchain relationships. This increment changes no backend services, providers, storage schema, risk rules, or dependencies.

## Wallet and handoffs

The Attribution section shows each claim independently: entity name/type, claimed relationship, last assessment, review-required state, backend supporting/contradicting/contextual evidence counts, and archive state. Counts are context, not votes. The wallet's full address, balance, risk, labels, transactions, and provenance remain intact.

With no records it says “No attribution claims have been recorded for this wallet.” **Open attribution** opens the exact persisted claim. **Create attribution claim** opens the existing Attribution form with wallet subject, chain, and address prefilled. The analyst explicitly chooses an entity and relationship and supplies scope/rationale before saving. Creating an entity within that workflow retains the public subject; it does not submit a claim automatically.

Only IDs and public address context travel through the existing workspace event/navigation mechanism. Attribution remains the detailed editing surface. No evidence bodies are placed in navigation URLs.

## Queries, history, and refresh

Summaries use existing chain/subject filters and AT-1 backend normalization. Ethereum case variants resolve consistently; Bitcoin Base58 case is preserved. The browser does not introduce a new address validator.

Each summary reads a page of ten claims and at most ten corresponding details for entity information and backend evidence counts. Previous/Next retain access to further records. Active non-rejected claims appear by default; **Include archived and rejected claims** exposes other records. The API has no exclusion filter for rejected assessments, so the browser hides those rows within the returned page, without fetching the whole database to fill it. Pagination totals describe stored matching records, and an empty filtered page is distinguished from no records.

Multiple claims and entities remain separate. Review-required claims show both their last assessment and **Review required**. Workspace activation and **Refresh attribution** refresh the summary without polling. Refresh clears stale positive overlay edges immediately; generation checks prevent older responses from replacing newer selections.

## Graph overlay — IMPLEMENTED

Graph rendering alone does not query attribution. Selecting a wallet loads its summary beneath the existing inspector. Open/create handoffs use that selected wallet and retain graph state when returning. Selecting an entity never invokes a blockchain lookup or the identifier resolver.

**Attribution overlay** defaults off. It is a presentation layer for eligible claims on the selected wallet's current summary page, not a graph-wide attribution query. Current Possible, Supported, and Strongly supported claims may appear; unassessed, review-required, rejected, archived-claim, and archived-entity records do not become positive overlay connections. They remain inspectable through the summary and its history filter.

Wallet positions and transaction edges are unchanged. Entity descriptors occupy a separate annotation band below the base graph bounds. Entities are sorted by persisted ID, placed in rows of four at 290-unit horizontal and 130-unit vertical spacing, beginning 60 units below the base bounds. Multiple claims targeting one entity retain independent claim edges and one entity descriptor. No claim records are collapsed into an inferred identity.

Entity rectangles explicitly say **ENTITY**, show the persisted name/type, and differ from wallet nodes. Purple claim edges have arrows; Possible uses dashes. Tooltips and selection show the relationship and assessment in text. Claim edges have no transaction amount, fee, block, transaction hash, or blockchain hop depth. Entity selection shows aliases, archive state, and the number of displayed claims, with **Open in Attribution**. Claim selection opens the exact claim.

Turning the overlay on fits its annotation area; **Fit to graph** includes visible overlay bounds. Turning it off removes only the annotation layer and restores the saved base view. Pan/zoom and ordinary wallet/transaction inspection remain available.

### Existing graph limitations

The existing graph backend can collapse transfer rows sharing a transaction hash, and base graph keys fold address case. AT-4 does not repair or extend those semantics. Overlay identity uses persisted entity/claim IDs and canonical claim subjects, never a transaction hash or graph proximity. If visible Bitcoin Base58 nodes/endpoints expose conflicting case spellings for one folded graph key, selected-node attribution is withheld with an explanation; inspect the exact public address in Wallet or Attribution instead. This guard does not claim to recover information already lost upstream.

Tests preserve base graph snapshots and same-hash records at the overlay boundary. Attribution edges neither add blockchain hops nor imply that stored graph coverage is complete. The overlay is deliberately limited to the selected wallet and current page.

## Failure and data boundaries

An unavailable attribution schema displays “Attribution storage is not initialized for this database.” Other local attribution failures remain confined to that section with a retry action. Wallet data, risk, labels, and graph controls stay usable. No automatic migration, seeding, backfill, assessment, source-URL preview, provider call, or recursive collection is added.

Production displays real API/database records only. Labels and Research evidence handoffs remain AT-5; Cases/report integration remains AT-6. No automatic label-to-claim, research-to-claim, risk adjustment, ownership inference, clustering, or topology rewrite is implemented.

## Verification

Baseline: 443 pytest tests. Ten added pytest cases exercise canonical BTC/ETH filtering and stance counts through real services/API, unchanged graph/risk storage, static integration, and five dependency-free Node overlay tests. Browser checks cover Wallet/Graph empty and populated summaries, competing claims, review/archive/rejection states, explicit handoffs, refresh, entity/claim selection, overlay toggle/view restoration, and non-fatal failures.

Run from the repository with isolated database configuration:

```powershell
$env:GREEDY_COLLECTOR_DATABASE_URL='sqlite:///:memory:'
$env:GREEDY_COLLECTOR_GRAPH_BACKEND='sqlite'
$env:GREEDY_COLLECTOR_MONITORING_BACKEND='apscheduler'
python -m pytest tests/ -q
node tests/browser_smoke.cjs
node tests/browser_attribution.cjs
node tests/browser_attribution.cjs unmigrated
node tests/browser_at4.cjs
node tests/browser_at4.cjs unmigrated
git diff --check
```

Browser harnesses use temporary SQLite and test-only fixtures with external requests blocked. Migrated attribution checks explicitly prepare only their temporary database at `20260912_01`; unmigrated checks verify graceful schema-unavailable handling without creating attribution tables. No user database migration is part of AT-4.
