# AT-6: Case attribution references and reports

Cases can explicitly include existing attribution claims and entity descriptors. Attribution remains the detailed evidence-review workspace. There is no automatic case population, entity inference, risk integration, evidence collection, or new provider.

## Schema and migration decision

**NO MIGRATION REQUIRED.** Existing `CaseEntity` has a string entity_type, string entity_ref, and JSON metadata_json with no database enum/check restricting reference kinds. Existing case references use wallet, transaction, label, graph_snapshot and attachment; notes are separate AnalystNote rows. AT-6 uses distinct `entity` and `attribution_claim` kinds and their actual attribution UUIDs. It never overloads a wallet/label/graph reference.

The dedicated attribution case API validates targets and generates the pin. The generic legacy `/cases/{id}/entities` input continues to reject these new kinds, preventing arbitrary browser metadata from impersonating a server-generated pin. No models or previous migrations changed. Head remains **20260912_01**. The user's real database is not migrated.

Direct evidence CaseEntity rows are not added: claim pins carry their complete historical link inventory and immutable evidence IDs. An entity reference means relevance to the case, without automatically attaching its wallet claims or asserting control over case wallets.

## API

Prefix: `/api/greedy-collector/attribution`.

| Method | Route | Contract |
| --- | --- | --- |
| POST | `/cases/{case_id}/references` | CaseAttributionCreate -> CaseAttributionReference, HTTP 201 |
| GET | `/cases/{case_id}/references` | Page[CaseAttributionReference], HTTP 200 |

Creation accepts only `reference_type` (`entity` or `attribution_claim`), `target_id`, and strict positive `expected_version`. It requires an existing case and target at the version the analyst selected. Arbitrary pins, assessment fields, metadata, and actor overrides are rejected. Archived/rejected records can be explicitly referenced with their status retained.

The response has reference ID, case ID, `pinned`, `current`, and `pinned_evidence_counts`. Pin fields are explicitly typed: schema_version=1, reference_type, target_id, captured_at, EntityRead, optional ClaimRead, and LinkRead inventory. Current state contains the current entity/claim and a changed flag. Counts distinguish supports/contradicts/context among links active at pin time. Unknown/missing current records do not replace historical fields.

Lists default to 20, maximum 200, and expose total/offset/next_offset. The UI uses ten rows per page. Missing references return safe 404; duplicate or stale selections return 409; malformed input returns 422; schema-unavailable uses the existing safe 503. New success/error bodies have explicit OpenAPI schemas.

## Pinning and historical fidelity

Pinning occurs **when the analyst confirms adding the reference to the case**. The backend stores the selected entity descriptor/version, claim state/version/assessment/rationale/scope/review/archive/timestamps where applicable, and every current link's ID, immutable evidence ID, stance/directness/rationale, and active/withdrawn state. Evidence content is not duplicated into CaseEntity metadata; reports dereference immutable captures.

Reference creation and pin persistence use the existing dedicated-session atomic transaction convention. SQLite BEGIN IMMEDIATE serializes writers before duplicate/version checks. A late failure rolls back the reference and pin together. This operation does not mutate Attribution or append Attribution events: it records a case association only.

The same `(case, reference kind, target ID)` cannot be added twice through AT-6, even after the target changes. A duplicate returns 409 and preserves the first pin. No repin/update/removal action is introduced. Current Cases have no clean reference-removal API; AT-6 adds no destructive behavior. A later separately designed repin/history workflow may be useful.

Source claim/entity edits, assessment rejection, link withdrawal or relevance changes never rewrite the saved pin. Cases show pinned and current assessment/version/review/archive state distinctly. An archived or rejected claim is displayed as such; an entity descriptor is never presented as a proven wallet owner.

## Frontend workflows

**Case -> Add attribution:** choose Claims or Entities, apply real server filters, select a record, and confirm. Claims support chain/address/relationship filters; entities support name filtering; archived records require an explicit filter. No entire attribution database is loaded. A selected case has a separate Attribution panel alongside its existing references, notes, attachments, alerts and reports.

**Attribution -> Add to case:** selected claim/entity uses the existing case-selection dialog, requires choosing a case and confirming, then offers Open case. The selected target version accompanies the request. Duplicate/stale errors remain local and understandable.

**Case -> Open attribution:** opens the exact claim or entity by ID. Evidence inspection, assessment changes, contradictions and history remain in Attribution. Cases do not duplicate that editor. No wallet containing a matching claim automatically gains a case association.

## Report representation

Markdown, escaped HTML, JSON and PDF all include **Attribution Assessment**, while retaining existing case references, notes, alerts and disclaimer. Human formats share one attribution content builder; JSON preserves structured pins, current summaries, immutable captures and link states. Human reports avoid raw metadata dumps.

Each claim reports full chain/address, relationship, pinned entity/version, pinned assessment/version/rationale/time/actor, scope/date bounds, review/archive state and pin time. Current state is explicitly separate, including later rejection, review required, archival and descriptor changes. Report generation time is recorded separately from pin/capture times.

Evidence is organized into **Supporting evidence**, **Contradicting evidence**, and **Contextual evidence**. Citations retain ID, title, source, safe URL/locator, origin/method, summary/excerpt, publication/observation/capture dates, reliability, and the pinned link's directness/rationale. Links withdrawn at pin time are historical, excluded from active counts, and labelled. Links withdrawn after pin retain their historical role alongside current withdrawn status. Changed current relevance is identified. Contradictions beyond the first evidence page are retained.

The historical inventory is explicitly limited to what was pinned. Later-added evidence is not silently inserted into that history; current version/review warnings direct analysts to Attribution for newer material. No full event-history traversal is needed because the required claim/entity/link state was pinned explicitly.

Reports are downloaded artifacts, not newly persisted report rows. An already downloaded report remains unchanged. Regenerating an export retains the same pinned material but intentionally obtains a new generated timestamp and current-state comparison. The application does not claim byte-identical regenerated exports, a stored report archive, digital signing or tamper-proofing.

Report reads use one explicit SQLite read transaction across case, references, current state and immutable evidence. Current entities/claims are batched; evidence/link queries use batches of 200 IDs. Case pins allow up to 10,000 links per claim; reports allow 1,000 attribution references per case. Excess/incompatible material fails explicitly rather than silently dropping evidence. No provider or citation URL is retrieved.

## Safety and boundaries

Pins and report material pass the existing AT-5 sanitization boundary. Credential-like nested fields, configured secrets, unsafe URLs, debug/internal data and local locators are redacted/withheld. Restricted-origin captures cannot be exported; a report fails safely instead of silently dropping that evidence. HTML/PDF text is escaped. JSON includes complete sanitized capture metadata; human reports show concise citations. Reports state:

> Attribution assessments are evidence-backed analytic judgments and do not by themselves establish legal ownership or identity.

If attribution storage is uninitialized, the Case Attribution panel shows the safe initialization message while existing notes, attachments, alerts, references and all report formats remain usable. Reports identify attribution as unavailable. No startup migration or seeding occurs.

No automatic entity/claim creation, Label/Research conversion, case notes, alert changes, source collection, graph topology changes or risk points are added. Attribution inclusion/report generation does not change saved wallet risk or Attribution records. Production uses real local records; synthetic data exists only in automated tests.

## Verification

Baseline: **494/494** tests and all existing browser regressions passed. Focused API/report tests cover reference kinds, duplicate/missing/stale/forged requests, existing-schema pins, late rollback, pagination, current/pinned changes, historical rejection/withdrawal in all four formats, later-page contradictions, provenance/redaction, non-mutating reports, risk/creation boundaries and unmigrated operation.

The isolated AT-6 browser workflow tests case-to-claim selection/confirmation, exact Attribution navigation, reverse case selection, direct entity references, duplicate handling, notes, all report downloads, Supported -> Rejected history, review-required/current-state display, and unmigrated non-fatal behavior. External HTTP is blocked. No screenshots are taken by this workflow.

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
node tests/browser_at5.cjs
node tests/browser_at5.cjs unmigrated
node tests/browser_at6.cjs
node tests/browser_at6.cjs unmigrated
git diff --check
```

All attribution browser harnesses create isolated temporary SQLite. Only their migrated variant explicitly upgrades to 20260912_01; the unmigrated variant does not stamp or migrate. No frontend framework or dependency is added. Clustering, discovery and other future phases remain outside AT-6.
