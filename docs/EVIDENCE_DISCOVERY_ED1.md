# ED-1: Evidence Discovery persistence and registries

ED-1 implements the seven-table foundation selected in [the architecture](EVIDENCE_DISCOVERY_ARCHITECTURE.md), sections 11.1-11.7. It has no Discovery HTTP routes, UI, provider execution or production fixtures. Existing eight workspaces remain unchanged. Creating or reading a run is local database work, never a request to execute a transform.

## Migration and deployment boundary

The new immutable revision is `20260913_01_discovery.py`, revision ID `20260913_01`, parent `20260912_01`. Previous migrations are unchanged. The clean chain is:

```text
20260630_01 -> 20260912_01 -> 20260913_01
```

The revision creates only:

| Table | Purpose |
| --- | --- |
| discovery_subjects | Canonical typed public identifiers |
| discovery_runs | Historical root run definitions and lifecycle |
| discovery_run_sources | Selected transform/source versions, status, cost and freshness metadata |
| discovery_results | Stable query-scoped candidate facts/relationships |
| discovery_observations | Immutable source material from a particular retrieval |
| discovery_run_items | Append-only per-run-source observation inventory |
| discovery_reviews | Append-only relevance decisions and reasons |

There is no `discovery_promotions` table. Foreign keys use `ON DELETE RESTRICT`; checks, unique constraints and indexes follow the selected design. Empty downgrade is supported. Downgrade refuses any populated Discovery table before dropping anything, to preserve history.

Application startup excludes `discovery_` and `attribution_` tables from legacy `create_all`. Deployment migration remains explicit; this task does not migrate the user's database. A missing Discovery migration does not affect existing workspaces.

`DiscoveryService` checks the seven table/column sets, enabled SQLite foreign keys, exact nine immutable trigger definitions and shipped migration ancestry. `metadata_only=True` is an explicit test setup option, not a route parameter. It still requires the real schema, triggers and foreign keys.

## Attribution migration compatibility

The old exact `20260912_01` equality test rejected a legitimate successor even with complete Attribution tables and triggers. A failing real-service regression demonstrated this before the new revision was added.

The shared `migration_state.supports_revision` walks `down_revision` ancestry in the shipped Alembic script graph. Every recorded head must be the required revision or a known descendant containing it. Unknown IDs, symbolic/abbreviated IDs, unrelated branches, empty stamps and the pre-Attribution baseline do not qualify. Attribution's table/column, exact trigger and foreign-key checks remain intact. A stamp alone never proves initialization.

AT-1 migration tests now explicitly target their own revision, retaining their original schema assertions. The existing startup regression compares the revision before/after startup instead of assuming the old head. ED-1 tests separately verify the actual new head and additive upgrade.

## Subjects and normalization

`blockchain_address` with namespace `bitcoin` or `ethereum` is the only accepted run input. The local Attribution subject normalizer reuses the existing adapter validators. Ethereum becomes lowercase; accepted Bech32 forms use the established lowercase convention; Bitcoin Base58 case remains significant. Outer whitespace is removed, embedded control characters rejected. This validates supported format, not checksum, ownership or blockchain existence.

Output-only kinds are `url`, `domain`, `repository` and `annotation`. URLs normalize scheme/IDNA host/default port and an empty path, preserving query/fragment semantics; credential-bearing and unsafe citations are rejected. Domains use the existing Research domain normalizer. GitHub repositories require a stable positive numeric repository ID. Annotations use source-scoped identifiers (`gc-label` or `explorer`). ENS, transaction, person and other future kinds are not enabled.

Subject identity is SHA-256 of canonical kind, namespace and value. Hash hits compare the actual identity fields before reuse. There is no Address FK, wallet lookup, subject rename or deletion command. URL normalization is citation handling only, not authorization to fetch that URL.

## Runs and source lifecycle

`create_run` stores a validated wallet subject, one to three unique registered transform/source pairs, frozen descriptors and parameters, query/request fingerprints, idempotency key, zero paid budget, nonsecret configuration generation, UTC timestamps and a version. Only the bounded `max_results` parameter is accepted in ED-1. Parent/root lineage columns exist, but root definitions are the only service operation. Actor defaults to `local_analyst`; this is an unauthenticated local actor label, not a verified identity.

The same idempotency key and request returns the existing run. Reusing a key for different intent fails. Runs can be retrieved and paginated by subject/status/archive state. Source rows contain selected transform/source IDs and versions, descriptor snapshot, coverage, provider count (null when unknown), returned count, cache origin/expiry, quota bucket/window, reserved/attempted requests, reserved/consumed units, bounded error category and timestamp fields.

```text
queued -> running -> completed | partial | failed | cancelled | interrupted
queued -> cancelled | interrupted
```

Completion is derived from terminal source outcomes: all success/cache/manual-ready means completed; a mix means partial; no successes means failed. Cancellation/interruption retains committed material and marks only unfinished sources terminal. Terminal runs can be archived/restored; no hard-delete command exists. No worker automatically starts, cancels, restarts or recovers a run in ED-1.

Source vocabulary is `queued`, `running`, `succeeded`, `cache_hit`, `manual_ready`, `unavailable`, `rate_limited`, `budget_exhausted`, `timeout`, `failed`, `cancelled`, `interrupted`. Transitions are validated, never arbitrary assignments. Successful material and status are committed together through `record_batch`; cache hits require `reuse_cache`. A zero-row successful bounded result differs from unavailable. Source failures do not overwrite successful sibling sources. Terminal source commands reject further changes.

Cost/accounting columns are foundations with nonnegative zero defaults. `quota_snapshot` can preserve sanitized reported context; there is no billing, reservation or transport accounting implementation. Manual/cache actions retain zero attempts/consumed units. Paid budget is always zero in run definitions. Unknown upstream quota is not invented.

## Results and observations

Results group a stable candidate fact by queried subject, kind, direction, predicate, canonical endpoints and normalized fact key. They are neither Attribution evidence nor claims. Candidate kinds are `candidate_evidence`, `candidate_identifier`, `candidate_relationship`. Titles, summaries and source locators belong to observations, so a refresh cannot overwrite historical material.

The schema retains the architecture's bounded predicate vocabulary: `mentioned_at`, `repository_contains`, `explorer_labeled_as`, `locally_labeled_as`, `publicly_listed_by`, `reverse_name_record`, `resolves_to`, `registration_record_for`, `certificate_names`, `observed_at`, `archived_at`, `uses_tracking_id`, `advertises_at`. Registered contracts and valid type pairs limit actual acceptance. Initial result-producing descriptors declare only `repository_contains` and `locally_labeled_as`. Reserved predicates enable no execution. Ownership/control predicates are rejected.

`record_batch` accepts trusted normalized material through a dedicated internal service session. It never calls an adapter. It checks the frozen descriptor, retention permission, result cap, endpoint types, query scope, observation kind and real local origin references. Code observations require an explicit public-only fact. Manual navigation cannot produce observations. Production GitHub retention remains unavailable pending later policy verification; tests use their own explicitly permitted registry.

Observations retain execution/source provenance, provider record key, kind, citation/locator, title, summary/excerpt, completeness, verification context, source class, observed/published precision, retrieval time, minimal sanitized JSON snapshot and content fingerprint. A label snapshot requires a real Label FK; optional Research origins reference real stored matches. No automatic Label/Research import runs. Later verified-document kinds are not accepted by the initial descriptors.

Datetime columns and nested snapshot dates serialize using existing UTC ISO-8601 conventions. Day-only source dates remain `YYYY-MM-DD`; unknown timestamps stay null. The 16 KiB snapshot bound and finite JSON/depth constraints apply before insertion; title/excerpt/summary limits are validated. Existing Attribution/Research sanitization removes credentials, local paths and debug fields. Configured Discovery tokens, including URL-encoded values, are additionally redacted. Raw provider response dumps are not stored.

## Immutability, run membership and transactions

Observations, run items and reviews each have ORM update/delete guards plus SQLite UPDATE, DELETE and INSERT replacement guards. Replacement guards protect both primary keys and alternate unique identities, including when SQLite recursive triggers are off. No general update/delete methods exist for historical rows.

Run items associate a source execution with an observation; joins recover its result, run and descriptor. New retrievals attach their own observations. Cache reuse attaches only the original execution's inventory, in stable ordinal order, with `inclusion_kind=cache`. Composite primary keys prevent duplicate membership. Source context is preserved without copying result content.

Mutating service commands use a dedicated clean Session, a short SQLite `BEGIN IMMEDIATE`, optimistic versions, commit/rollback and safe conflict errors. Result creation, observation insertion, run-item attachment and terminal source state are atomic. Review history and current review summary are atomic. Tests inject late failures after material has been written and prove no orphan/partial state survives. No database writer lock spans network work because there is no network work.

## Fingerprints, deduplication and review

| Identity | Inputs and behavior |
| --- | --- |
| Query | Canonical subject; transform/source IDs and versions; parameters/limits; matching, retention and configuration versions. No retrieval clock or credential. |
| Result | Query subject; candidate kind; predicate/direction; canonical endpoints; sanitized normalized fact key. Provider formatting is not raw-hashed. |
| Observation | Sanitized material and source/transform provenance. Excludes generated IDs, retrieval/creation clocks and rank. Material change changes the fingerprint. |

Identical records in the same execution reuse one observation. A later actual retrieval creates a new observation even when its content fingerprint matches; another provider retains independent provenance. Changed or conflicting material remains alongside prior observations. One logical result is reused; materially different facts remain distinct. Hash matches on subjects/results compare underlying identities before merging.

Review states are exactly `unreviewed`, `relevant`, `irrelevant`. Promotion is not a review state. Decisions append actor, reason, timestamp, result-scoped sequence, selected observation and material revision. Submission requires the current result version and selected observation fingerprint. Current review is result-wide; the selected observation records the material inspected when the analyst deliberately reviews that revision.

Previously unseen content increments material revision and exposes `new_material_since_review`, while retaining the old explicit decision and history. Identical refreshes and cache use do not flag new content. Irrelevant results are not deleted; returning to unreviewed also requires an explicit reason.

## Cache and freshness foundation

Cache candidates require the exact query fingerprint, a successful original non-cache execution, bounded coverage, unexpired timestamp and compatible current source/transform version and retention policy. Explicit refresh (including the run's frozen refresh option) bypasses reuse. Partial, failed, unknown-coverage, unapproved and expired entries do not qualify.

Automated bounded success may receive the descriptor's expiry (maximum 24 hours); successful empty results are capped at one hour. Local Label context and manual navigation have no remote cache expiry. Cache replay points directly to the original execution, never a chain, and adds run membership without creating or changing observations. Original observed/retrieved timestamps and first/last genuine seen times remain unchanged. Expiration never deletes historical material.

## Registries and credentials

`registry.py` contains code-owned frozen typed descriptors. It rejects duplicate IDs, invalid versions/types/predicates/costs, incompatible source references and extra callback/module/command fields. There is no executable plugin loader or execute method.

| Transform ID | Source | Mode | Implemented / executable | Cost |
| --- | --- | --- | --- | --- |
| wallet.local_labels | gc_labels | Local | false / false | FREE_LOCAL |
| wallet.manual_exact_web | google | Manual | false / false | FREE_LOCAL |
| wallet.public_code_mentions | github | Automated, future | false / false | LIMITED_FREE |

Descriptors include supported chains/input/output kinds, result and observation contracts, matching/version metadata, request/result/byte/deadline limits and cache policy. Source descriptors separately preserve display/category/mode, credential environment reference, cost unit/class, rate-limit metadata and provenance/retention notes. All four architecture cost classes are recognized: FREE_LOCAL, FREE_REMOTE, LIMITED_FREE, PAID.

Capability introspection is local Python data only. GitHub reads `DISCOVERY_GITHUB_TOKEN` presence as a boolean; its value is never returned. Configured means present, not validated, reachable, entitled or executable. All executable flags remain false. No key is needed for normal startup, no `.env` is added/changed, and no browser/search/SDK is invoked.

## Boundaries and next phase

Creating Discovery subjects/runs/results creates no Attribution, risk findings, Cases, Labels, Research runs or blockchain graph entries. Labels/Research/wallet lookup never auto-populate or start Discovery. No promotion, graph algorithm, recursive pivot, monitoring change, provider transport, HTTP endpoint, Discovery workspace or Wallet/Graph button is included. Production has no sample/canned Discovery data. No dependency was added.

ED-2 is the next separately authorized phase for typed capabilities/plan/run/history/review APIs, a bounded single-worker executor, cancellation/interruption and persistent quota reservation described by the architecture. Provider implementation, UI, promotion and later pivots remain gated by their own phases; ED-1 stops here.

## Verification

Starting baseline: **524/524**. Added: **108 tests**. Final full suite: **632/632 passing** (29 existing-category dependency deprecation warnings). Regression files are `test_revision_ancestry.py`, `test_discovery.py`, `test_discovery_boundaries.py` and `test_discovery_migration.py`. They cover local normalization, lifecycle/validation, atomic failures, provenance/dedupe, all immutable row guards, reviews, cache reuse, descriptor contracts, secret handling, real existing API boundaries and migration-only startup.

Migration tests compare all seven tables' columns/types/nullability/defaults, primary/foreign keys, checks, unique constraints, indexes and exact triggers between clean Alembic and ORM databases. Clean upgrade, upgrade from AT-1 with retained rows, successor Attribution service acceptance, empty downgrade/reupgrade and populated downgrade refusal are tested. `PRAGMA foreign_key_check` returns `[]`.

Startup/shutdown tests use isolated SQLite both with and without the new migration, block external HTTP, verify eight existing workspaces/assets, require no Discovery route and prove no seed records. Automated provider material exists only in tests. The real database is neither queried nor migrated during verification.

The existing `node tests/browser_smoke.cjs` and migrated `node tests/browser_at6.cjs` passed with isolated databases and test-only providers. The former checks Wallet, Graph, Monitoring, Alerts, Cases, Labels and Research; the latter checks Attribution and its Case/report handoffs against the still-supported Attribution revision. New-head compatibility is covered by the migrated API and startup tests. `alembic heads` reports only `20260913_01 (head)`; `git diff --check` passes. The starting isolated in-memory database was unversioned (`alembic current` returned no revision); the real database was not inspected. A 133-file starting hash inventory confirms only the six documented existing files changed for ED-1; the other 127, including earlier migrations, providers, risk and frontend assets, are unchanged. No files were removed and no commit was created.

```powershell
$env:GREEDY_COLLECTOR_DATABASE_URL='sqlite:///:memory:'
$env:GREEDY_COLLECTOR_GRAPH_BACKEND='sqlite'
$env:GREEDY_COLLECTOR_MONITORING_BACKEND='apscheduler'
python -m pytest tests/ -q
python -m alembic heads
git diff --check
```
