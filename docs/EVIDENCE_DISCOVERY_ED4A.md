# ED-4A: Local Labels and manual exact-web pivots

ED-4A introduces the first real local/manual Discovery implementations through the ED-2 planner and run orchestration. It adds no migration, dependency, remote transport or runtime fixtures. Head remains **20260913_01**. The user's database is not inspected or migrated.

## Production implementations

| Transform | Implemented / executable capability | Mode / source / cost | Network behavior |
| --- | --- | --- | --- |
| wallet.local_labels | true / true | local / gc_labels / FREE_LOCAL | Read-only existing SQLite Labels; zero remote calls |
| wallet.manual_exact_web | true / true for action generation | manual / google / FREE_LOCAL | Generate one outbound link locally; no search request |
| wallet.public_code_mentions | false / false | automated descriptor / github / LIMITED_FREE | Unavailable; no code-search implementation |

Capabilities indicate registered implementation/configuration and local budget eligibility; they do not probe storage or remote reachability. Run creation still requires the existing initialized-Discovery-schema guard. Unmigrated storage returns the existing safe 503 message. No API key is needed for either implemented pivot.

`production_executors(sessions)` creates one `LocalLabelsExecutor` bound to the selected application database and one separate `ManualBinding` for exact search-action generation. Construction performs no reads or execution. Custom test registries remain explicitly injectable; no test binding is imported by production startup. Static descriptors cannot assert their own implementation state; runtime capabilities derive it from the registered code.

## Exact Label matching

The executor uses canonical chain/address supplied by Discovery, backed by existing validators. Ethereum and accepted Bech32 use the project's lowercase convention. Bitcoin Base58 remains case-sensitive. Only matching address-linked rows with the requested chain or `any` qualify. Outer ASCII whitespace is ignored for matching, preserving the original stored address in provenance. A canonical validation check confirms each returned match. No fuzzy matching, label-text search or cross-chain inference occurs.

`any` rows retain their original scope with an explicit chain-unspecified annotation note. They do not become chain-specific Labels. The bounded SQL read sorts by Label ID and reads at most the requested limit plus one. Overflow is reported as `limit_reached` and a partial run, without claiming complete Label coverage or inventing a provider count.

## Candidate and provenance semantics

Each actual Label row produces `candidate_evidence` with `locally_labeled_as`, from the queried wallet to a source-scoped `gc-label` annotation reference. Fact identity includes the Label ID; it never emits ownership/control predicates. Distinct rows and conflicting annotations remain separate candidates, with no selected winner or averaged confidence.

The immutable `local_label_snapshot` records the real Label ID, text, type, original source, confidence, stored chain/address and last-updated timestamp. Discovery source is `gc_labels`; original annotation source remains a separate field. Source update time is retained as observed time, while retrieval time records the new local read, using the existing UTC ISO-8601 serializer. A safe HTTP(S) source URL is retained when applicable; otherwise the stable `label:<id>` locator remains.

Existing sanitization removes credential query parameters/userinfo, configured secrets and local paths before normalization, fingerprinting and storage. No missing source URL, publication time or confidence is invented. Confidence is original annotation metadata, not identity probability, Attribution assessment or new risk points. Verification is `not_applicable`: local annotation retrieval is not independent public corroboration.

## Freshness, dedupe and history

Local Labels have **zero cache seconds and always execute fresh**. Normal runs and explicit refresh both read current persisted rows; remote cache semantics are unchanged. No match is successful bounded execution with zero results.

An unchanged Label reuses the candidate identity and content fingerprint while recording a separate genuine retrieval observation. A changed Label produces a changed immutable observation under its stable row identity and raises the existing renewed-review flag. Prior observations and review history remain intact. Legitimate CSV upsert changes type/confidence using the existing Label API; this task adds no edit/delete Label endpoint. New distinct Label rows remain distinct candidates.

## Manual exact-web generation

The analyst selects the manual pivot, plans it, then explicitly confirms a run. The manual handler receives the canonical full wallet and produces a quoted exact-search query. The URL is fixed to `https://www.google.com/search` with only the URL-encoded `q` parameter. Ethereum uses its full canonical lowercase address; Bitcoin preserves canonical case semantics. No truncation, API credential, user-provided destination or local path is inserted.

The source becomes **manual_ready**, with zero result count, zero requests/reservations/consumed units, unknown provider coverage and no provider total. The existing quota JSON stores the bounded generated action. `SourceRead.manual_actions` is a small typed response extension exposing that action in current and historical run detail. No new endpoint or table is necessary. Generated actions never become DiscoveryResult or DiscoveryObservation rows.

Manual `executable=true` means **the local action generator can run**, not that a web search can execute. `allow_free_local=false` blocks both local and manual work. Manual registry registration is code-owned, version checked and restricted to manual/FREE_LOCAL/zero-request descriptors. Async remote-style callbacks cannot register as manual handlers.

The page states: **The search engine was not queried by Greedy Collector.** It shows the full quoted query, source and explicit outbound link with `target="_blank"`, `rel="noopener noreferrer"` and no-referrer policy. Nothing auto-opens. Clicking leaves GC for Google; automated tests deliberately do not follow it. Quoted query intent is not a guarantee of exact search-engine matching or complete coverage. Manual webpage ingestion remains deferred.

## Analyst workflow and boundaries

The normal Discovery selection/plan/run flow now enables Local Labels and manual generation using actual capabilities. Label detail prominently distinguishes original annotation source and confidence metadata. Manual panels are clearly separated from candidate evidence. GitHub remains visibly unavailable even if a token is configured.

Opening Discovery, checking a wallet, planning, browsing history or reviewing results does not execute either pivot or call providers. Only explicit Run reads Labels or generates actions. No Wallet/Graph handoff, recursive collection, graph visualization, promotion, entity/claim creation, Case inclusion, risk recalculation or change to Label semantics is added. Discovery never modifies Labels. ED-4B is the separately authorized public-code transform phase; GitHub is not implemented here.

## Verification

Starting full-suite baseline: **793/793 passing**. Tests use isolated SQLite and blocked external transports. Production implementation tests cover supported address forms/case/scope, exact matching, no-label success, conflicting annotations, preserved provenance and confidence, sanitized source URLs, bounded results, unchanged/changed fingerprints, always-fresh execution, explicit refresh and immutable history. Manual tests verify full encoded BTC/ETH queries, fixed HTTPS origin, zero observations/results, unchanged other subsystems and code-binding guards.

Browser production mode uses the real ED-4A implementations with Labels created/updated through the existing API in a temporary migrated database. It covers Label inspection/review/history, refreshed material and original observations, manual links without following them, and all three capability states. Synthetic executor mode remains a separate ED-3 framework regression. Unmigrated mode retains its safe storage message and zero auto-created Discovery tables.

No live external provider calls, real database migration or automatic commit are part of verification.

Final verification: **835/835 tests passed** (42 added; 29 existing-category dependency deprecation warnings). All six Node frontend behavior tests passed. Production local/manual, synthetic-framework and unmigrated Discovery browser modes passed, as did the original workspace smoke harness and AT-6 Attribution/Case/report regression. Routes `/`, `/health`, `/docs`, `/openapi.json`, Discovery APIs and assets remain successful under isolated tests. Alembic still reports the single head `20260913_01`; `git diff --check` passes. No production fixture names or external request implementation were found in the new runtime paths. Existing uncommitted ED-3 work is retained; this phase creates no commit.
