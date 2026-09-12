# AT-2: explicit manual attribution HTTP API

AT-2 exposes the [AT-1 services](ATTRIBUTION_AT1.md) through typed FastAPI routes. It adds no Attribution workspace, automatic records, provider calls, source URL retrieval, risk integration, or schema migration. The original [architecture](ATTRIBUTION_ARCHITECTURE.md) remains authoritative; this document specifies the implemented HTTP contract.

All paths below have prefix **`/api/greedy-collector/attribution`**. Interactive request and response schemas are available in `/docs`; `/openapi.json` describes every success and attribution error response. There are 26 operations across 21 attribution paths. Application OpenAPI path count increased from 29 to 50.

## Deployment

Attribution requires the existing Alembic revision **20260912_01**, FK enforcement, compatible columns and all AT-1 immutability triggers. The API constructs a request-scoped `AttributionService` with a dedicated database session and the normal guard; it never enables `metadata_only`, creates tables, stamps a database or runs migrations.

An unmigrated/incompatible database receives HTTP 503 from attribution routes. Existing seven workspaces and normal scheduler startup/shutdown remain available. Follow AT-1's migration guidance: verify an unstamped legacy schema before any deliberate stamp/upgrade. This task did not migrate the user's database. No new migration is required or provided.

## Exact routes and schemas

Creation returns 201; reads and updates/actions return 200. Names below refer to `greedy_collector/attribution/schemas.py` and OpenAPI components. `Page[T]` is the common pagination envelope.

### Entities

| Method | Suffix | Request | Response |
| --- | --- | --- | --- |
| POST | `/entities` | EntityCreate | EntityRead |
| GET | `/entities` | Pagination; search, entity_type, include_archived | Page[EntityRead] |
| GET | `/entities/{entity_id}` | ID | EntityRead |
| PATCH | `/entities/{entity_id}` | EntityUpdate | EntityRead |
| POST | `/entities/{entity_id}/archive` | VersionAction | EntityRead |
| POST | `/entities/{entity_id}/restore` | VersionAction | EntityRead |

`EntityCreate`: canonical_name (nonblank, max 255), entity_type (default unknown), description (max 8,000, default empty), aliases (up to 50 nonblank strings, max 255 each). Types: organization, person, service, protocol, public_body, online_identity, unknown. Same-name records are permitted; no automatic merge or wallet association.

`EntityUpdate`: expected_version, reason, **descriptor: EntityCreate**. This narrow PATCH replaces the descriptor component in full. Omitted descriptor fields receive their normal defaults, including empty aliases/description. It cannot change ID, lifecycle, actor, timestamps or version directly. The server's normalized name search key is not part of EntityRead.

`EntityRead`: id, canonical_name, entity_type, description, aliases, created_by, created_at, updated_at, archived_at, version.

### Claims

| Method | Suffix | Request | Response |
| --- | --- | --- | --- |
| POST | `/claims` | ClaimCreate | ClaimDetail |
| GET | `/claims` | Pagination and claim filters below | Page[ClaimRead] |
| GET | `/claims/{claim_id}` | ID | ClaimDetail |
| PATCH | `/claims/{claim_id}/scope` | ScopeUpdate | ClaimRead |
| POST | `/claims/{claim_id}/assessment` | AssessmentUpdate | ClaimRead |
| POST | `/claims/{claim_id}/archive` | VersionAction | ClaimRead |
| POST | `/claims/{claim_id}/restore` | VersionAction | ClaimRead |

`ClaimCreate`: entity_id, subject_type (wallet only, default wallet), chain (bitcoin/ethereum), subject_ref, relationship, valid_from/valid_to (optional dates), scope_note (nonblank, max 4,000). Relationships are only operated_by, controlled_by, publicly_declared_by. No assessment, actor or server-derived fields can be supplied at creation.

AT-1 reuses local chain validators, trims outer whitespace, lowercases Ethereum/accepted bc1 forms and preserves Bitcoin Base58 case. This is supported syntax validation, not proof of checksum validity, control or existence. No provider request or Address row is required. Initial state is unassessed, needs_review=true, version=1.

The logical key is `(subject_type, chain, canonical subject_ref, relationship, entity_id)`. Duplicates, including Ethereum case variants and archived/rejected claims, return 409 with `detail.existing_id`. The existing record must be explicitly restored/reassessed. Changing entity/relationship/subject requires a separate claim; identity fields cannot be patched.

`ScopeUpdate`: expected_version, reason, **scope: {valid_from, valid_to, scope_note}**. This replaces the scope component; omitted dates become null. Reversed date bounds are rejected. A scope revision preserves the last assessment and marks it for review.

`ClaimRead`: id, subject_type, chain, subject_ref, entity_id, relationship, valid_from, valid_to, scope_note, assessment, assessment_rationale, assessed_at, assessed_by, needs_review, created_by, created_at, updated_at, archived_at, version.

`ClaimDetail` adds the referenced EntityRead as `entity`, `entity_archived`, `active_evidence_counts` with supports/contradicts/context counts, and `active_evidence: Page[LinkDetail]`. Counts cover all active links; the embedded page contains the first 50. Its total/next_offset explicitly indicate further material. Follow the separate evidence list route to inspect remaining pages and gather every active link ID before assessment. No events or remote material are fetched implicitly.

Claim filters: chain, subject_ref (requires chain and uses AT-1 normalization), entity_id, relationship, assessment, needs_review, include_archived. Default lists exclude archived claims and claims whose entities are archived. `include_archived=true` includes both active and archived records; it does not mean archived-only. Entity detail shows parent lifecycle. Entity filters support literal normalized-name substring search, type and include_archived. SQL performs filtering, counting, sorting and pagination.

### Evidence

| Method | Suffix | Request | Response |
| --- | --- | --- | --- |
| POST | `/evidence` | EvidenceCreate | EvidenceRead |
| GET | `/evidence` | Pagination; source_catalog_id, origin | Page[EvidenceRead] |
| GET | `/evidence/{evidence_id}` | ID | EvidenceRead |

`EvidenceCreate` reuses AT-1 validation for title, summary, excerpt, evidence_type, source_name, source_url/source_locator, source_catalog_id, origin, published_on, observed_on, analyst_note, source_reliability, reliability_rationale, origin_group and metadata_json. Fields and bounds are explicit in OpenAPI.

Public capture types: official_disclosure, public_record, explorer_annotation, public_post, repository_record, analyst_observation. Origins: public_osint and analyst_added only. Commercial/proprietary and privileged/nonpublic ingestion are rejected. Label/research snapshot types and origin IDs are reserved for AT-5 and rejected here. Actor, capture time, collection_method, IDs and fingerprint are generated by the service, never accepted from callers.

Except for analyst_observation, a public HTTP(S) source URL or citation locator is required. Analyst observations require an explanatory analyst_note. URLs are never fetched, resolved or treated as verified source authenticity. Credentials in URLs and filesystem locators are rejected. Assessed reliability (reliable/uncertain/unreliable) requires a rationale; unassessed is the default.

`EvidenceRead` exposes the complete immutable capture: all approved material fields plus id, captured_at, captured_by, collection_method, origin_label_id/origin_match_id (null for these manual captures), and content_sha256. This fingerprint describes sanitized stored content, not authenticity or independent corroboration. Listing filters are exactly the existing service's source_catalog_id/origin filters; withdrawal is a property of an individual claim link, not the capture.

### Claim evidence

| Method | Suffix | Request | Response |
| --- | --- | --- | --- |
| GET | `/claims/{claim_id}/evidence` | Pagination; stance, include_withdrawn | Page[LinkDetail] |
| POST | `/claims/{claim_id}/evidence` | LinkCreate | LinkResult |
| POST | `/claims/{claim_id}/evidence/capture` | CaptureAndLink | LinkResult |
| PATCH | `/claims/{claim_id}/evidence/{link_id}` | LinkUpdate | LinkResult |
| POST | `/claims/{claim_id}/evidence/{link_id}/withdraw` | VersionAction | LinkResult |
| POST | `/claims/{claim_id}/evidence/{link_id}/restore` | VersionAction | LinkResult |
| POST | `/claims/{claim_id}/evidence/{link_id}/replace` | EvidenceReplacement | ReplacementResult |

`LinkFields`: stance (supports/contradicts/context), directness (direct/indirect/context), rationale (nonblank, max 8,000). Context stance requires context directness. The role belongs to the link, not the immutable capture.

`LinkCreate`: expected_version, evidence_id, link: LinkFields. `CaptureAndLink`: expected_version, evidence: EvidenceCreate, link: LinkFields. Capture-and-link runs the existing single atomic AT-1 command; stale versions/failures leave no orphan capture or partial event.

`LinkUpdate`: expected_version, reason, link: LinkFields. It changes relevance only; it cannot mutate evidence, retarget the link or change actors/timestamps. There is one link per claim/evidence pair, irrespective of stance/withdrawal. Duplicate linking returns 409 and existing_id; explicitly restore a withdrawn link or edit its relevance.

`LinkRead`: id, claim_id, evidence_id, stance, directness, rationale, added_by, added_at, updated_at, withdrawn_at. `LinkDetail` adds a concise evidence summary (id, title, type, source name/URL/locator, origin, reliability, captured_at); GET the evidence ID for full captured material. `LinkResult` returns the updated ClaimRead and LinkRead. Links have no independent version: all operations require the parent claim's version.

`EvidenceReplacement`: expected_version, reason, evidence: EvidenceCreate, link: LinkFields. It is exposed because AT-1 already implements an explicit atomic replacement command: capture new immutable material, withdraw the old link, add the new link and append a claim event with one version increment. `ReplacementResult` adds withdrawn_link to LinkResult. Original evidence and history remain inspectable. Other claims using the old capture are untouched and require their own deliberate decisions.

### Events

| Method | Suffix | Response |
| --- | --- | --- |
| GET | `/claims/{claim_id}/events` | Page[EventRead] |
| GET | `/entities/{entity_id}/events` | Page[EventRead] |
| GET | `/evidence/{evidence_id}/events` | Page[EventRead] |

`EventRead`: id, entity_id/claim_id/evidence_id (exactly one target), sequence, event_type, actor_kind, actor_ref, occurred_at, reason, payload. Typed payload identifies schema_version=1, before/after JSON snapshots and preserves additional event-specific JSON (reviewed links, entity version, link changes). Streams are ordered by sequence; evidence has a creation event only. HTTP uses consistent offset pagination through a read-only service query; the existing Python `event_history` sequence-cursor behavior is unchanged.

No POST/PATCH/DELETE routes exist on these history paths. No public event mutation operation exists anywhere in this namespace. Database/ORM immutability protections remain unchanged.

## Assessment and review safeguards

`AssessmentUpdate` requires expected_version, assessment, rationale, reviewed_link_ids and acknowledged_contradictions. The two arrays have no implicit defaults: callers must deliberately supply them, including empty arrays when appropriate. Maximum 10,000 IDs per array; over-limit requests receive safe 422 rather than silent truncation. conflict_discussion and source_verification are bounded strings (max 8,000 each).

Categories are unassessed, possible, supported, strongly_supported, rejected. No confirmed or numeric confidence exists. AT-1 requires every active link to have been reviewed and every active contradicting link to be explicitly acknowledged. Contradictions require written conflict_discussion. Missing/stale reviewed link sets return 409; missing contradiction acknowledgement/discussion returns 422. The HTTP layer never inserts acknowledgement on behalf of the caller.

Possible needs active supporting evidence. Supported needs direct support with assessed reliability. Strongly supported additionally needs reliable direct evidence and written source_verification. Structural checks do not prove the source or reasoning is true. Rejection and resetting to unassessed remain explicit rationale-bearing decisions; prior assessments remain in events.

Linking/editing/withdrawing/restoring/replacing material preserves the last assessment and sets needs_review=true, including when contradictory material is added. Descriptor/scope changes and restoration also flag review according to AT-1. The API never automatically downgrades, rejects, promotes or rescales a claim.

## Versions, archive and actors

`VersionAction`: expected_version (strict positive integer, no string/boolean coercion) and nonblank reason (max 8,000). Every mutation of an existing entity/claim uses optimistic concurrency; links use their parent's claim version. Successful commands return the incremented version and transactional audit history. On 409, GET the current record (and all relevant evidence), reconsider the intended command, then submit its current version. Conflict responses never guess a current version outside the command's transaction.

Entity/claim archival retains claims, evidence links and all events. Restore requires compatible parent/lifecycle state and flags review as AT-1 specifies. Archived state and rejected assessment are independent. There are no hard-delete endpoints. Evidence cannot be globally archived, rewritten or deleted; withdraw its individual claim link instead.

Explicit actions record the server-supplied **local_analyst**. System review invalidations retain **attribution.review_invalidation**. This application has no authentication: these values identify local operations, not verified people. Actor fields in requests are rejected; no authentication system is introduced.

## Pagination

All list routes, including evidence links and each history stream, use:

```json
{"items": [], "limit": 50, "offset": 0, "total": 0, "next_offset": null}
```

Default limit=50, maximum=200, minimum=1; offset>=0. total counts all matching rows independent of the page offset. next_offset is null when no further page exists. Entities/claims/evidence/links retain AT-1 stable creation/capture time + ID order; events use sequence order. Mutations between requests can change offset pages; reload after conflicts. No unbounded Python full-table scans or hidden dropped evidence.

## Error and serialization contract

Errors use `{"detail":{"code":"...","message":"...","existing_id":"..."}}`; existing_id is present only when the service identifies a duplicate. Request-validation errors deliberately omit raw input and exception context, which can contain credentials.

| HTTP | Code | Meaning |
| --- | --- | --- |
| 404 | not_found | Referenced local record or correctly scoped link absent |
| 409 | conflict | Duplicate claim/link, stale version or reviewed link set, incompatible archived/withdrawn state, AT-1 transactional constraint/busy conflict |
| 422 | invalid_request | Schema/JSON/enum/format/provenance/bounds or assessment prerequisite failure |
| 503 | schema_unavailable | Migration/column/FK/immutability guard not satisfied |
| 503 | storage_unavailable | SQLAlchemy read/service-construction storage failure |
| 500 | internal_error | Unexpected failure; no raw exception details |

Forbidden methods receive the normal HTTP 405. The safe handler is scoped to attribution routes; existing workspace error contracts are unchanged. SQL, IntegrityError text, stack traces, filesystem paths, arbitrary pasted invalid values and configured secrets are not returned. AT-1 mutations roll back on command failure.

Typed date/datetime fields serialize as ISO-8601 (UTC may use `Z`); nested Python timestamps captured through AT-1 normalize to UTC `+00:00`. HTTP JSON itself has no datetime type: timestamp strings in metadata remain strings with their supplied offset. Date-only citations remain YYYY-MM-DD and unknown dates remain null. Nested metadata uses AT-1 finite JSON, depth and 32 KiB bounds; credential-like values are redacted before persistence/fingerprinting. No arbitrary str(datetime) conversion is added.

## Synthetic developer example (documentation only)

The values below do not assert a real attribution and are never seeded into runtime state. `0x1111111111111111111111111111111111111111` is a syntax-only synthetic example, not a claim about a private person.

1. POST `/entities` with `{"canonical_name":"Synthetic Example Service","entity_type":"service"}`; retain returned entity ID.
2. POST `/claims` with:

```json
{
  "entity_id": "<returned entity ID>",
  "chain": "ethereum",
  "subject_ref": "0x1111111111111111111111111111111111111111",
  "relationship": "publicly_declared_by",
  "scope_note": "Synthetic documentation example; no real-world attribution asserted."
}
```

3. POST `/claims/{claim_id}/evidence/capture` with:

```json
{
  "expected_version": 1,
  "evidence": {
    "evidence_type": "analyst_observation",
    "title": "Synthetic workflow observation",
    "summary": "Illustrates manual capture only.",
    "source_name": "Synthetic local observation",
    "origin": "analyst_added",
    "analyst_note": "This example supplies context, not evidence of real control."
  },
  "link": {
    "stance": "context",
    "directness": "context",
    "rationale": "Documentation workflow context only."
  }
}
```

4. Inspect `/claims/{claim_id}` and `/claims/{claim_id}/events`. A positive assessment of this context-only example would be rejected. To explicitly reject the synthetic proposition, POST `/claims/{claim_id}/assessment` with the returned version, assessment=rejected, a reason, all current reviewed_link_ids and acknowledged_contradictions=[].

## Boundaries and verification

AT-1 services own every mutation, normalization, prerequisite and transactional event. Added service functions only assemble bounded claim/link details and consistently paginated event reads. No changes to models, migrations, risk rules, providers, monitoring, labels, research, graph, cases, reports, frontend or dependencies. All examples/fixtures are documentation or test-only data. No runtime seed entity, claim, evidence or automatic cross-workspace conversion exists.

API regressions use migrated temporary SQLite with the normal service guard and blocked external HTTP. They cover creation/detail/filter/pagination, permitted updates, every assessment category, contradictions, archive/restore, link replacement and original-material retention, immutable HTTP surfaces, stale/late-failure rollback, safe errors, timestamps/redaction, OpenAPI enums/models, large evidence pages and risk/label/research boundaries. Existing AT-1 tests remain authoritative. Its unmigrated startup test now expects guarded AT-2 routes while retaining no automatic schema/workspace checks. A separate migrated startup test verifies normal scheduler start/stop and zero attribution rows.

Verification results are recorded in the task completion report. AT-3 frontend work requires a separate task.
