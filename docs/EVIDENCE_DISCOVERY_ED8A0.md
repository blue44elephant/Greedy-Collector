# ED-8A0: Typed ENS endpoint foundation

This prerequisite removes the storage blocker found before ED-8A. It does not implement ENS Discovery. No ENS RPC, reverse/forward resolution, ENSIP-15 library, CCIP-Read, executor, provider, frontend rendering or promotion is added. Production contains no seeded ENS material. The failed ED-8A attempt did not create `EVIDENCE_DISCOVERY_ED8A.md`; that document remains absent.

## Type and identity

The subject kind is **`ens_name`**. Although the existing namespace column could support a generic naming-service type, the specific kind follows the architecture's approved ENS vocabulary and enables only the requested protocol. Namespace **`ethereum`** restricts it to the application's current Ethereum Mainnet scope. No new column or unrelated subject kind is needed.

Identity continues to hash canonical kind, namespace and value. Display strings, UUIDs and retrieval clocks do not determine logical identity. Existing subject/query/result/observation fingerprint algorithms remain unchanged for previously supported inputs. Fixed pre-change wallet, Label and GitHub hashes are regression fixtures.

`canonical_ens_subject` is an **internal canonical-input boundary**, not a user-facing name resolver or an ENSIP-15 normalizer. It preserves supplied Unicode and case exactly, rejects empty/overlong values, whitespace and the existing category-C control/format policy, and requires the Ethereum namespace. It performs no lowercase, IDNA, NFC or other protocol normalization. Callers must not interpret acceptance as proof that a value is a valid normalized ENS name. ED-8A must supply protocol-correct normalization and review this conservative storage-boundary policy, including any protocol-permitted format characters, before enabling an executor.

## Relationship and execution boundaries

The only new enabled pair is:

```text
ens_name (ethereum) --resolves_to--> blockchain_address (ethereum)
```

The run's query subject remains the wallet. `record_batch` already accepts the queried subject at either end, so no direction workaround is required. Reverse direction, Bitcoin targets, unrelated endpoint kinds and ownership/control predicates remain rejected. Existing `candidate_relationship` and reserved `name_service_record` are sufficient; no result-kind, observation-kind or predicate CHECK expansion is needed.

ENS endpoints remain output-only. Public `/plan` and `/runs` still accept only Bitcoin/Ethereum wallet addresses. Internal `create_run` also rejects ENS subjects. No production ENS source/transform is registered, and no existing pivot begins emitting ENS material. Technical naming conveys no civil identity or wallet ownership.

## Migration and compatibility

Revision **`20260916_01`**, parent **`20260915_01`**, rebuilds only `discovery_subjects` using Alembic's SQLite batch operation. It widens `ck_discovery_subjects_1` by adding `ens_name` and adds `ck_discovery_subjects_8` requiring namespace `ethereum` for that kind. ORM checks match exactly. All columns, defaults, timestamps, IDs, PK/unique constraints and indexes are retained. There are no subject-table triggers to recreate; child tables and their immutable-history triggers are untouched.

The migration follows the existing ED-6 deployment pattern: a dedicated Alembic connection, an explicit SQLite write transaction spanning the rebuild, and `PRAGMA foreign_key_check` before commit. It refuses application connections with FK enforcement already enabled rather than toggling their integrity mode. Application connections continue enabling foreign keys. No migration runs at startup, and no user database is inspected or migrated by this task.

Downgrade restores the previous checks only if **zero ENS subjects exist**, including unreferenced subjects. Otherwise it fails before rebuilding or deleting anything. Populated legacy history can survive downgrade and re-upgrade. Earlier migrations remain unchanged.

At `20260915_01`, current Discovery, Attribution and promotion remain available. ENS storage raises a specific schema-unavailable error. At `20260916_01`, the existing ancestry guards accept the successor. ENS writes additionally check both installed constraints and revision ancestry; a stamp alone is insufficient. Explicit metadata-only test setups still require the actual new constraints.

## Graph handling

ED-7's wallet, Label and code node/edge formats remain unchanged. A correctly typed stored `resolves_to` / `name_service_record` can be read without rejecting the whole graph. Its result/observation IDs appear in bounded `unrendered_results` with endpoint type `ens_name` and reason `presentation_not_implemented`. It remains included in total counts and normal page offsets. No ENS visual node/edge is manufactured, and unknown/invalid relationship types still fail validation. Existing result/observation APIs retain access to the stored material. ED-8A will implement the actual presentation.

## Verification

Starting baseline: **1028/1028 passed**, 41 warnings. Final `python -m pytest tests/ -q`: **1075/1075 passed**, 57 warnings, 342.48 seconds; **47 tests added**. The focused schema, migration, graph and compatibility run passed **82/82**. Warnings remain in the existing dependency/deprecation categories.

Verification uses isolated SQLite and blocked external transports. Coverage includes new/old types, internal storage versus root rejection, literal direction, namespace restrictions, stable identity and legacy hashes, API planning, graph deferral, populated migration with Label/GitHub observations/reviews/promotions, exact Discovery/Attribution ORM/Alembic parity, FK enforcement, downgrade protection and successor compatibility. A deliberately corrupt test input proves failed FK validation rolls back the rebuilt table and revision without changing retained rows. The populated-upgrade test compares every application table before/after. Unrelated legacy ORM/server-default differences are preserved, not repaired.

All **six isolated browser regressions passed**: the existing workspace smoke harness, Discovery graph and promotion at the new head, partial-schema and unmigrated graph modes, and AT-6. Together they cover Wallet, Graph, Monitoring, Alerts, Cases, Labels, Research, Attribution and Discovery. Fixtures and provider mocks remain test-only; external transports are blocked. Startup/shutdown, `/`, `/health`, `/docs`, `/openapi.json`, workspace assets and applicable APIs also pass the existing isolated regression checks.

Alembic reports one head, **20260916_01**, with the full expected ancestry. Foreign-key checks return `[]` on valid migrated databases. Older migrations are byte-identical to the starting files. The file-hash audit limits existing-file changes to the nine documented task files; no provider, risk, monitoring, Case, Label, frontend or dependency implementation changed. No ENS fixture values or test source registrations appear in production paths. `git diff --check` passes.

Four files are added (this document, the migration and two test modules), nine existing files modified, and none removed. No dependency or commit is added. The real user database is neither inspected nor migrated. Work stops at ED-8A0.

## Next task

ED-8A remains a separate increment for official ENS contract verification, correct normalization, bounded configured RPC, mandatory forward verification, cache/provenance, graph/result presentation and explicit reviewed promotion. This foundation does not claim those features work.
