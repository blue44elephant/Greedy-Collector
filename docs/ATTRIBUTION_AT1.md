# AT-1 attribution persistence and service foundations

Implemented scope: explicit Python services, five ORM models, one additive migration, local validation, immutable evidence/history, and focused tests. There are no attribution HTTP endpoints or frontend controls. The [architecture](ATTRIBUTION_ARCHITECTURE.md) remains the design authority; later phase APIs/UI/handoffs are not implemented here.

## Schema and migration

Revision **20260912_01**, parent **20260630_01**. The parent migration is unchanged. The new revision uses explicit Alembic create_table/create_index operations and named constraints, without metadata.create_all or imports of mutable application models.

| Table / ORM model | Purpose / identity |
| --- | --- |
| attribution_entities / AttributionEntity | Reusable descriptors, aliases, normalized search name, archive state, timestamps and version. Names are not unique |
| attribution_claims / AttributionClaim | Wallet/chain/relationship/entity proposition, scoped dates/note, categorical assessment/rationale, review state, actor/timestamps/version |
| attribution_evidence / AttributionEvidence | Immutable citation/content/provenance capture, reliability rationale, dates, JSON metadata and content fingerprint |
| attribution_claim_evidence / AttributionClaimEvidence | Per-claim stance/directness/rationale, capture reference, actor/times, withdrawal state |
| attribution_events / AttributionEvent | Append-only, single-target entity/claim/evidence streams with ordered sequence, actor, reason and before/after material state |

Column types, nullability, server defaults, indexes, unique/FK/CHECK constraints follow architecture section 6. UUIDs and UTC timestamps use the existing helpers. Entity/claim uniqueness and indexes use exactly the documented columns. Evidence references to labels and research matches are schema foundations only; capture handoffs are deferred to AT-5.

All new FKs use RESTRICT and no destructive cascade. Duplicate claims are unique across `(subject_type,chain,subject_ref,relationship,entity_id)`, including archived/rejected claims. One link per `(claim_id,evidence_id)`; stance changes update that link with an event. Each event has exactly one target FK and a unique sequence within its stream. The evidence creation stream has sequence 1 only.

Six SQLite triggers protect evidence and event rows: UPDATE, DELETE, and replacement INSERT guards for each table. The INSERT guards also protect event target/sequence uniqueness against INSERT OR REPLACE with a different ID. Ordinary ORM updates/deletes of evidence/events raise a clear error. The protections preserve application history, not non-repudiation against a database administrator who can remove triggers.

The migration refuses downgrade if any attribution table contains rows. Empty-schema downgrade and re-upgrade are tested. No user database was migrated by this task.

## Service contract

Import `AttributionService` from `greedy_collector.attribution.service`. Construct it with a **dedicated SQLAlchemy Session** backed by the existing FK-enabled SQLite engine. No user/actor or provider dependency is injected.

By default construction checks the expected migration revision, all five table/column sets, exact immutability trigger definitions, and PRAGMA foreign_keys. Missing/incompatible schema raises SchemaUnavailable without creating or stamping tables. The explicit `metadata_only=True` option is for tests/development databases constructed from current metadata; it skips only the Alembic stamp requirement, not table/column/trigger/FK checks.

| Operations | Behavior |
| --- | --- |
| create_entity, get_entity, list_entities | Explicit descriptor creation/retrieval, name/type/archive filtering, aliases round-trip; duplicate names permitted |
| update_entity | Full validated descriptor replacement with expected_version/reason; transactional linked-claim review invalidations |
| archive_entity | Archive or restore=True; archived entities' claims excluded from default active lists; restore flags their claims for review |
| create_claim, get_claim, list_claims | Explicit unassessed wallet proposition; existing active entity; local canonical subject; duplicate conflict with existing ID |
| update_claim_scope | Versioned dates/scope revision; immutable subject/entity/relationship fields are not accepted |
| change_assessment | Explicit category/rationale command with expected version, complete reviewed active link IDs and acknowledged contradiction IDs |
| archive_claim | Archive or restore=True, retaining assessment and history; restore requires active entity and new review |
| create_evidence, get_evidence, list_evidence | Immutable analyst-entered capture and JSON-safe copies; no general content-edit/delete operation |
| link_evidence, list_claim_evidence | Reusable evidence attached with a separate role/directness/rationale; active and withdrawn views |
| create_and_link_evidence | Atomic capture plus link and both target audit streams |
| update_evidence_link | Versioned relevance/directness/rationale correction; no evidence-content mutation |
| withdraw_evidence | Withdraw or restore=True; original row/material remains in history |
| replace_evidence | Atomic new capture, old-link withdrawal, new link and one parent-version increment; old snapshot retained |
| event_history | Ordered, bounded single-target event stream with sequence cursor |

Entity, claim, evidence and link list operations expose items, total and next_offset (default limit 50, maximum 200); ordering is stable by creation/capture time and ID. AT-1 uses explicit Python offset pagination as its minimal foundation. No future HTTP cursor contract is exposed yet. Event history uses after_sequence/next_sequence.

Each mutation owns one transaction and commits on success, rolls back on failure. Use a dedicated Session; pending unrelated new/dirty/deleted state is rejected. SQLite BEGIN IMMEDIATE acquires the write transaction before reading mutable parent states. Updates additionally use `WHERE id = ... AND version = expected_version`; stale writers raise Conflict instead of overwriting. Every affected entity/claim advances once per command and its event sequence equals the version. Parent changes and events commit together, including all targets of descriptor-change invalidation. Link operations use the parent claim's version.

Safe domain errors are AttributionError, NotFound, Conflict (optional existing_id), and SchemaUnavailable. They have no HTTP coupling. Input schemas forbid unknown fields, including supplied actor/timestamps/hash/assessment at creation. Constraint, busy-storage and validation errors do not echo database statements or arbitrary supplied secrets. The future route layer must map these errors explicitly; no endpoints are introduced here.

## Enums and assessment

- Entity types: organization, person, service, protocol, public_body, online_identity, unknown.
- Relationships: operated_by, controlled_by, publicly_declared_by.
- Assessments: unassessed, possible, supported, strongly_supported, rejected.
- Stances: supports, contradicts, context. Directness: direct, indirect, context; context stance requires context directness.
- Origins: public_osint, analyst_added, commercial_proprietary, privileged_nonpublic. Services accept only the first two; restricted ingestion is unavailable.
- Evidence types: official_disclosure, public_record, explorer_annotation, public_post, repository_record, research_snapshot, label_snapshot, analyst_observation. The two snapshot types are reserved in schema but rejected by AT-1 capture services.
- Collection methods: analyst_entry, label_snapshot, research_snapshot; AT-1 service sets analyst_entry itself.
- Source reliability: unassessed, reliable, uncertain, unreliable; assessed reliability requires its own rationale.
- Events: created, descriptor_changed, scope_changed, evidence_linked, evidence_changed, evidence_withdrawn, evidence_restored, assessment_changed, review_required, archived, restored.
- Actors: analyst/system event kinds. Explicit commands record local_analyst; automatic review invalidation identifies attribution.review_invalidation. Neither represents authenticated identity.

There is no confidence/probability field and no Confirmed/owned_by/associated_with value. Creating/linking evidence never changes assessment automatically: it marks needs_review while preserving the last category/rationale. Scope/descriptor changes and restore also require review.

Possible needs active support. Supported needs direct support with assessed reliability. Strongly supported additionally needs reliable direct support and a written source_verification statement. All current contradiction links must be acknowledged and accompanied by conflict_discussion. These two command arguments are appended to the persisted assessment rationale and audit event; they add no new model columns or scoring. Structural guards cannot authenticate a source or prove the analyst's reasoning true. Downgrades and rejection remain explicit and retain prior conclusions.

## Normalization and evidence safety

Normalization is local: reuse existing adapter format validation, trim surrounding whitespace, lowercase Ethereum hex, preserve Bitcoin Base58 case, and lowercase the currently accepted bc1 address form. The adapter's permissive Bech32 regex remains the acceptance baseline; no new checksum/existence/control claim or provider call is introduced. Claim DB checks prevent noncanonical Ethereum/bc1 casing from bypassing logical uniqueness. `any` and unsupported chains/subjects are rejected. No Address record is created to hold a claim.

Evidence URLs are formatted as HTTP(S) citations, never fetched or remotely validated. Userinfo, credential query/fragment keys, configured secrets and malformed URLs are rejected. Filesystem source locators are rejected. Evidence metadata accepts finite JSON values and explicit date/datetime conversion; nested datetimes normalize to UTC ISO-8601, dates retain YYYY-MM-DD. Unknown dates stay null. Arbitrary objects, NaN/infinity, deep nesting and metadata above 32 KiB fail explicitly. Source excerpts remain bounded text.

Credential-like fields and known configured secrets are redacted before capture persistence, fingerprinting and audit snapshots. Public evidence survives redaction. Fingerprints use canonical sanitized citation/content JSON and exclude generated capture identity/time/actor; equal fingerprints are not evidence of independent corroboration or source authenticity. Returned records are JSON-safe copies; changing a returned dictionary does not edit immutable stored material.

## Deployment clarification

Original architecture: migration/version protection must precede startup create_all, and normal existing workflows must remain intact. Implementation issue: GreedyCollectorService is constructed during import and creates all registered Base tables, while AT-1 introduces no attribution routes or workspace.

Selected correction: the existing startup initializer creates **only legacy tables**. It cannot silently create attribution tables on a real unversioned database. AttributionService requires a valid migrated schema before any command. Explicit test/development `Base.metadata.create_all` installs the same six SQLite triggers through table DDL hooks; metadata_only is a deliberate service-construction option for that setup. This preserves current application startup and prevents an attribution schema/trigger bypass without automatically migrating or stamping user data.

Normal future deployment uses the new Alembic revision. Existing unstamped legacy databases still require verified schema comparison before any explicit stamp; AT-1 does not implement an automatic stamp/upgrade tool. The original baseline revision is immutable. Once AT-2 exposes attribution routes, use the existing service guard rather than metadata_only.

## Boundaries and verification

No automatic attribution from labels, research, wallet lookup, graph, monitoring, alerts or cases. No new provider calls, fake runtime fixtures, risk inputs/points/rescoring, label/research backfill, CaseEntity types, report changes or graph/UI changes. All new records require explicit service commands; no startup rows are seeded.

Tests cover creation/reuse, enums, address normalization, duplicate claims/links, evidence relevance and immutability (including replacement statements), assessment prerequisites/contradictions/downgrades, optimistic writes, ordered audit streams, archival/restoration, late transactional failures, JSON/secret safety, parent FKs, baseline-to-head migration, clean migration, ORM schema/default/index/constraint/trigger equivalence, FK integrity and existing-workflow boundaries. Browser verification uses the existing seven-workspace harness with temporary DB/provider fixtures.

Verification: starting suite 242/242; 82 added cases; final `python -m pytest tests/ -q` result **324/324 passed**. Existing seven-workspace `node tests/browser_smoke.cjs` passed with isolated providers and SQLite. Migration tests compare columns/types/nullability/defaults, PKs, indexes, unique/CHECK/FK constraints and trigger SQL, and verify zero foreign-key violations. Deprecation warnings come from the existing FastAPI/Starlette lifecycle/client setup and Alembic's existing path-separator configuration; dependencies were not changed.

Next phase is AT-2: an independently authorized task for the manual HTTP API around these foundations. No frontend or automatic evidence handoff is implied by completion of AT-1.
