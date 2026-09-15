# ED-6: Explicit Discovery promotion into Attribution

Reviewed Discovery observations can be explicitly promoted into Attribution evidence. This is a local capture/link workflow over stored material, with no source refresh, entity inference, automatic claim creation, assessment change, risk update or Case/Label mutation. Production contains no seeded promotions or synthetic evidence. No dependency was added.

## Migration and compatibility

Revision **20260915_01**, parent **20260913_01**, adds `discovery_promotions` and the architecture-required Attribution evidence extension. Previous revisions are unchanged. `discovery_snapshot` is an explicit evidence type and collection method; `origin_discovery_observation_id` is a nullable RESTRICT FK with an index. Existing methods require that origin to be null; Discovery captures require it and forbid Label/Research origin FKs on the evidence itself. Underlying Label provenance remains in the immutable observation and capture metadata.

The dedicated Alembic connection rebuilds the evidence table in one explicit SQLite write transaction, preserving old columns, values, indexes, constraints and child references. Its evidence triggers are reinstalled before commit; existing event triggers remain intact. Foreign-key validation precedes completion. Migration is an offline deployment operation, not application startup. The user's database is not inspected or migrated. Downgrade refuses retained ED-6 captures/promotions; an empty ED-6 extension can be removed while retaining earlier Attribution history.

| Database revision | Available behavior |
| --- | --- |
| 20260912_01 | Existing Attribution works; Discovery persistence and promotion report unavailable |
| 20260913_01 | Existing Attribution and Discovery work; promotion alone reports not initialized |
| 20260915_01 | Attribution, Discovery and explicit promotion available |

Known successor ancestry remains required. The new origin column is deferred and server-owned in the ORM; legacy capture INSERTs omit it and legacy evidence serialization supplies null without reading an absent column. Pagination counts select record IDs because a Core subquery otherwise expands deferred ORM columns and breaks pre-ED-6 evidence lists. The guard accepts the old column set only before the ED-6 revision. Tests exercise real capture, detail and paginated reads at each supported revision. Discovery's seven-table guard remains independent of promotion initialization.

## Promotion record and history

The table follows architecture section 11.8: ID, observation/claim/evidence/link FKs, source/capture fingerprints, claim versions before/after, local actor and creation timestamp. The result is unambiguously obtained through the immutable observation. Stance, directness and rationale remain in the Attribution link and its versioned audit event; they are not duplicated into a competing mutable interpretation record.

`UNIQUE(observation_id, claim_id)` is permanent. Repeated promotion returns 409 with the existing promotion ID even if its link has been withdrawn or replaced. Restore/relevance changes belong to Attribution. A new observation can be promoted separately; another claim for the same canonical wallet can use the same observation with its own explicit link decisions. A complete identical capture fingerprint reuses existing evidence, avoiding a second copy being mistaken for independent corroboration.

SQLite UPDATE/DELETE/REPLACE triggers and ORM guards protect promotion identity. A fourth INSERT trigger checks that observation, evidence, link, claim and capture fingerprint agree. Indexes support claim history, evidence and link references; version/hash/actor checks enforce scalar invariants. Promotion history joins only the requested result's page to current link state. It shows current stance/directness/rationale and withdrawal state, while the referenced claim event at `claim_version_after` retains the original promotion decisions. No generic update/delete API exists.

## Review and selected material

Promotion requires a **Relevant** review of the selected material. Review and promotion remain separate actions. The latest explicit review associated with the selected observation's content fingerprint authorizes that material; identical genuine retrievals may share that review. A result-wide Relevant badge cannot authorize different new content.

New observation B with changed material is blocked until reviewed. Explicitly selecting reviewed retained observation A remains possible even if B is awaiting review. A later Irrelevant/Unreviewed decision for A's material blocks new promotion of A; prior captures are retained unchanged. Preview fingerprints include the reviewed material, review identity and promotion policy. A changed decision/policy between preview and confirmation conflicts; a newer immutable observation alone does not silently replace the selected ID.

## Evidence mapping and immutable snapshot

| Stored source | Evidence origin | Type / collection method |
| --- | --- | --- |
| wallet.local_labels / local_label_snapshot | analyst_added | discovery_snapshot |
| wallet.public_code_mentions / code_search_result | public_osint | discovery_snapshot |
| wallet.manual_exact_web | NOT PROMOTABLE | No captured observation or evidence |

Titles distinguish **GC Discovery - Local Label** and **GC Discovery - GitHub code mention**. Local Label capture retains the same underlying record field names used by AT-5: ID, annotation, original source, confidence and update time. Discovery remains the immediate provenance; it does not masquerade as a direct AT-5 Label handoff.

GitHub capture retains actual repository/file/URL/blob SHA, bounded matched context, full wallet, retrieval time, source/pivot versions, verification and coverage metadata. Search score stays provider metadata. Code occurrence does not establish repository owner control. Exact code excerpts permit all three explicit stances with existing directness validation; unverified code material is context-only. General search/page transforms remain unsupported. No full document verification is inferred from a code excerpt.

Common capture metadata includes result and observation IDs, observation content fingerprint, canonical query subject, predicate/candidate kind, fact key, source/execution/run references, versions, coverage and the selected sanitized observation. Reliability starts **unassessed**. No inferred reliability, assessment, positive stance or manufactured rationale is supplied.

The promotion boundary sanitizes again before preview, hash or insertion, including configured Discovery credentials, nested token/header/cookie/debug fields, credential-bearing URLs and local locators. Bounds fail explicitly rather than silently truncating provenance. Stored timestamps use existing UTC ISO-8601 conventions; date-only values retain their precision. Capture time and local actor are generated by Attribution.

Later Label edits, GitHub changes, Discovery refresh/review changes and claim assessments never rewrite the capture. Withdrawal/replacement preserves the original promotion references. AT-6 pins and all four report formats retain the original immutable evidence and historical link role; later link state is shown separately.

## Transaction boundary

`PromotionService` composes the existing Attribution atomic decorator and internal capture/event/link helpers. One dedicated Session acquires `BEGIN IMMEDIATE` before mutable-state checks. It validates the selected result/observation, review and source policy, exact claim wallet/chain, current expected claim version and explicit link choices. Evidence, evidence event, link, claim event/version and promotion row commit together or all roll back.

There are no nested service commits or network calls. Concurrent duplicates serialize under SQLite and the permanent uniqueness constraint. A stale claim returns 409 without retry. Linking flags review required and preserves the existing assessment. Promotion creates no Entity, Claim, Label, Case reference, Research result, graph edge or risk point and changes no quota accounting.

## API

All routes are under `/api/greedy-collector/discovery`:

| Method | Route | Behavior |
| --- | --- | --- |
| GET | /observations/{observation_id}/promotion-preview | Authoritative sanitized capture, exact material/review, eligibility and fingerprint; no write |
| POST | /observations/{observation_id}/promote | Explicit atomic promotion; 201 with promotion and updated claim |
| GET | /results/{result_id}/promotions | Bounded history with current link state; default 20, maximum 100 |

POST accepts only `result_id`, `claim_id`, `expected_claim_version`, `expected_source_fingerprint` and `link: {stance, directness, rationale}`. No actor, time, arbitrary snapshot, Entity, relationship or assessment fields are accepted. Missing IDs return safe 404, stale/duplicate intent 409, invalid eligibility/choices 422, unavailable schemas 503 and unexpected failures generic 500. Same-origin/JSON request protections remain active. No response exposes raw SQL, provider exceptions or credentials.

## Frontend workflow and return context

Observation detail loads one local preview and a bounded promotion-history page. There is no promotion/claim-history fan-out from the main results list. An eligible selected observation offers **Use as attribution evidence**, opening the existing Attribution handoff panel. Missing promotion storage is a local explanatory state; Discovery inspection/review remains usable.

The handoff shows the exact observation and provenance. The analyst selects an existing claim from server-paginated, chain/address/relationship-filtered records, or uses **Create attribution claim** and the existing explicit Entity/relationship/scope forms. Wallet context may be prefilled; candidate names never choose an Entity or relationship. Pending observation and link choices survive that claim-creation path.

Stance and directness begin unselected. A rationale and review acknowledgement are required. **Preview promotion** refreshes the server source preview and displays the selected claim/version and decisions. **Confirm promotion** is the only write. Editing choices invalidates confirmation; errors do not automatically retry. After success, **Open attribution** opens the exact claim, whose existing controls own assessment, evidence detail, contradiction handling and withdrawal/replacement.

**Back to Discovery** restores the retained result/observation view without rerunning its source. Use **Reload result** to refresh promotion history after returning. Navigation context is in-memory and does not survive a full page reload. Reload cannot launch or promote a run. The separate Promoted count does not replace Relevant/Irrelevant review states.

## Verification

Baseline: **924/924**, 29 warnings. Final `python -m pytest tests/ -q`: **1002/1002**, 38 warnings, 351.57 seconds; **78 tests added**, all previous tests retained. Focused promotion/migration/report/concurrency, frontend and old-schema checks passed. The AT-5 browser regression exposed a pre-ED-6 evidence-count query reading the new deferred column; an isolated failing regression reproduced it, then the identity-only count correction passed at all supported revisions.

All **17 isolated browser runs passed**: ten Discovery modes (ED-6 promotion/partial/unmigrated plus production local/manual, executor, unmigrated, GitHub and three ED-5 handoffs), six migrated/unmigrated AT-4/5/6 runs, and the existing workspace smoke harness. Coverage includes Local Label/GitHub immutable capture, all three stances, changed material, duplicate protection, explicit claim creation with retained decisions, return to Discovery and bounded promotion history. The existing smoke harness covers Wallet, Graph, Monitoring, Alerts, Cases, Labels and Research; dedicated suites cover Attribution and Discovery. Fixtures and mocked transports exist only in tests. External provider requests were blocked throughout.

Isolated route verification returned 200 for `/`, `/health`, `/docs`, `/openapi.json`, Discovery/Attribution assets and their applicable collection APIs. A missing observation returned a safe 404 with the ED-6 schema initialized. No fixture credential appeared in those responses. Production-path searches found no fake/sample/canned promotion, wallet, transaction or graph datasets. No dependency, provider, risk-rule or prior migration change was introduced.

Isolated baseline `alembic current` was unversioned; previous repository head was **20260913_01**. Final `alembic heads` reports exactly **20260915_01 (head)**. The real user database was neither inspected nor migrated. `git diff --check` passed. Changes remain uncommitted.

Work stops at ED-6. Discovery graph, additional transforms, automatic attribution and risk integration remain deferred.
