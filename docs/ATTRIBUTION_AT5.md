# AT-5: explicit Label and Research evidence handoffs

AT-5 adds analyst-controlled capture of existing local source records. It uses the AT-1 immutable evidence/link/event schema and the existing Attribution workspace. It does not discover identities, collect new evidence from the internet, create entities or claims automatically, or change assessment/risk rules.

## Workflow

In a selected Label or persisted automated Research match, choose **Use as attribution evidence**. This opens an Attribution handoff panel and reads a sanitized server-side source preview. No write occurs.

Choose a real claim from the paginated list (ten per page), with chain, wallet-address, and relationship filters. Each row shows the wallet, relationship, entity and assessment; the selected claim shows its exact ID/version. Alternatively, choose **Create attribution claim** to use the existing manual workflow. For supported chain-qualified labels, chain/address are prefilled. An `any` label or Research match does not supply an inferred chain/wallet: enter the subject explicitly. Entity, relationship and scope remain explicit choices. A new entity is never generated from label text or research subject text.

After choosing/creating a claim, explicitly choose **Supports**, **Contradicts**, or **Context**, select directness, enter link rationale, and acknowledge reviewing the source and claim. Neither stance nor directness is preselected. Context requires context directness under existing AT-1 rules. **Confirm capture** is the write action. **Open attribution** opens the exact resulting claim.

Source context survives explicit entity/claim creation in the existing workspace. Saving a claim selects it for the pending handoff but does not capture evidence. Cancel handoff abandons the pending operation without writing. Labels/Research remain concise source surfaces; Attribution owns claim selection, capture, and detailed evidence inspection.

## API and authoritative source reads

All routes use `/api/greedy-collector/attribution`:

| Method | Route | Behavior |
| --- | --- | --- |
| GET | `/evidence/sources/{source_kind}/{source_id}` | Read sanitized preview for `label` or `research`; no mutation |
| POST | `/claims/{claim_id}/evidence/from-label/{label_id}` | Atomically capture current Label and link it |
| POST | `/claims/{claim_id}/evidence/from-research/{match_id}` | Atomically capture current Research match/run context and link it |

Both POST bodies contain only `expected_version`, `expected_source_fingerprint`, and `link: {stance, directness, rationale}`. Unknown fields, browser-supplied snapshots, origin IDs, actors, and assessments are rejected. POST returns 201 with the normal LinkResult: updated claim and link. The browser obtains the source fingerprint from the preview and the claim version from explicit selection.

`EvidenceHandoffService` owns source lookup, eligibility, sanitization, validation, capture, duplicate checks and link creation. It reuses the normal migration guard and AT-1 atomic command/event/link mechanisms. Common evidence content validation is shared with manual capture; the manual input and HTTP routes still forbid impersonating Label/Research snapshots.

## Label snapshot and provenance

The snapshot retains the Label's actual ID, chain, address, label, type, original source, annotation confidence, and last_updated. It identifies the source subsystem as **Greedy Collector Label**. Capture time/actor are the evidence record's server-generated captured_at/captured_by, separate from source update time. UTC metadata timestamps use existing ISO-8601 `+00:00` serialization; unknown dates remain null.

Evidence type and collection method are `label_snapshot`; title is **GC Label snapshot**. The original source remains source_name and snapshot metadata. A safe public source URL is retained where available, with the internal `label:<id>` locator preserving the stored annotation reference.

Origin is **analyst_added** for all label snapshots: the captured material is GC's secondary annotation/assertion, even when it cites a public URL. Clicking capture does not authenticate its cited publisher or turn the annotation into a primary-source disclosure. Annotation confidence is preserved only as metadata; source reliability starts unassessed.

A chain-qualified Label must match the selected claim's chain. The source address is validated through AT-1 for that chain; `any` is validated against the explicitly selected claim chain and never fans out. Another wallet on that chain may be cited with the analyst's explicit stance and rationale; it is never silently retargeted to the claim wallet.

## Research snapshot and provenance

The server reads KycMatch plus its parent KycScreeningRun. It requires an existing automated source catalog entry and a parent run recording that source as successfully checked. Manual-source links, unavailable notices and missing/malformed source records are ineligible.

Metadata retains match ID/run ID, provider/source, subject_name, match_score, match_rationale, source_url, categories, sanitized source_data, and captured review_status. Parent context contains its actual ID, query and created_at. Coverage error/debug payloads and manual links are not imported as identity evidence. No research-history browser or new research endpoint is needed.

Evidence type/method are `research_snapshot`; title is **GC Research match snapshot**; origin is **public_osint** for these existing public-source automated matches. source_name uses the catalog's provider name, source_catalog_id retains its ID, and `research-match:<id>` provides a local locator. The safe public source URL remains available.

Research review status and text similarity retain Research meanings. **Confirmed source match does not confirm wallet attribution.** Neither source score nor review status selects an assessment, entity, wallet, relationship or evidence stance.

## Immutability, duplicates, concurrency and transactions

Evidence, its creation event, claim link and claim event commit in one SQLite transaction using existing BEGIN IMMEDIATE and optimistic version checks. Late failures roll back the entire operation, including a flushed capture/event. Existing immutable database/ORM protections remain unchanged.

The source fingerprint is calculated from canonical sanitized evidence content and origin IDs, excluding generated capture ID/time/actor. It includes the exact stored source snapshot, including source update/review timestamps where present. If the source changes between preview and confirmation, capture returns 409; reload the source preview, review it, and select the current claim version before retrying. A stale claim version also returns 409. There is no automatic retry or overwrite.

An identical fingerprint already linked to the same claim returns 409 with the existing link ID, even if withdrawn or a different stance is requested. Inspect/edit relevance or explicitly restore that retained link. This prevents repeated clicks from creating identical copies. A changed sanitized snapshot may be captured as a new immutable record. Capturing for a different claim is permitted; equal fingerprints do not establish independent corroboration. Existing evidence reuse is also available.

Later Label updates or Research review changes never rewrite old evidence. Withdraw an obsolete link, capture the newer source version, or use existing explicit replacement/reuse workflows. No source-following synchronization occurs. Source FKs remain RESTRICT: ordinary deletion of a referenced Label/Research match is blocked rather than silently breaking provenance. There is no source deletion feature added here; missing references before capture return safe 404.

Every new link marks the claim review-required while preserving its last assessment and rationale. Contradictions are first-class evidence and require the existing explicit acknowledgement during later assessment. No support-count voting or automatic promotion/downgrade is added.

## Sanitization and display

The handoff boundary reapplies Research's configured-secret and credential-field redaction, explicitly converts finite JSON/dates, redacts additional credential/debug/internal field names, and withholds local filesystem locators. Public URLs lose userinfo and sensitive query/fragment parameters; unsafe URLs or configured-secret paths are withheld. Sanitization precedes preview, fingerprinting, persistence and events. Unsupported shapes, non-finite values, invalid provenance and metadata exceeding 32 KiB are rejected rather than silently truncating source material.

The preview and captured detail show source subsystem, original Label source or Research provider, annotation confidence or match score, review state, source dates, and public locator as applicable. Complete sanitized metadata remains expandable. Capture time appears in the existing evidence detail. Rendering uses text nodes; citation URLs are never fetched or previewed by the handoff.

## Failure and phase boundaries

Missing source/claim returns 404; duplicate/version/archive conflicts return 409; malformed choices/source records return 422. Schema-unavailable 503 displays **Attribution storage is not initialized for this database.** Labels/Research remain usable. Unexpected failures use bounded safe messages, not SQL, stack traces, credentials or local paths.

No migration, seeding, source update, entity matching, automatic claim/entity creation, risk points, provider quota consumption, research rerun, graph topology change, clustering, or external discovery is added. Production uses real stored records only. All synthetic material is confined to tests. Cases and reports remain AT-6.

## Verification

Starting baseline: **453/453** tests plus all existing isolated browser workflows. Focused tests cover all stances, provenance, immutable source updates, missing/ineligible sources, duplicates/withdrawn links, source/claim version races, rollback/events, redaction, chain compatibility, schema-unavailable behavior and creation/assessment/risk boundaries. Existing manual capture still rejects forged snapshot types/IDs.

Run with isolated database configuration:

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
git diff --check
```

Browser harnesses use isolated temporary SQLite, explicit test-only migration to **20260912_01**, normal application lifecycle, and blocked external HTTP. The AT-5 Research fixture replaces only provider transport; the real engine/service persists the match. The unmigrated mode never upgrades or stamps its database. No screenshot loop or browser framework/dependency is added. The user's real database is not migrated.
