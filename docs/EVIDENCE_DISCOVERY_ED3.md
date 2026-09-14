# ED-3: Discovery analyst workspace

Discovery is the ninth workspace in the existing vanilla HTML/CSS/JavaScript application. It uses the ED-2 local API and the existing local identifier resolver. There is no new framework, dependency, provider, migration or production dataset. The user's database is neither inspected nor migrated.

## Current production limitation

**Zero production Discovery transforms are executable.** The execution framework is present; real Discovery transforms are introduced in ED-4 and later.

The catalog is read from `/discovery/transforms` and `/discovery/sources`, never reproduced in JavaScript. `wallet.local_labels`, `wallet.manual_exact_web` and `wallet.public_code_mentions` all show **Not implemented / Not executable**, plus actual mode, configuration, source, cost, limits and cache window. Configured credentials do not make a descriptor executable. The manual pivot never opens Google, and the local pivot does not substitute a Labels request.

Unavailable checkboxes are disabled. **Why unavailable — diagnostic plan** sends an explicit local planning request for that pair; it does not create a run. An all-unavailable plan has no normal execution action. Empty history/results remain empty.

## Layout and subject workflow

The workspace contains New discovery, Available pivots, Source capabilities, Plan, Current run, Results, Result detail and Run history. It follows existing panels, tables, typography and neutral colors. Statuses have visible text, all inputs have labels, full references remain copyable and immutable source snapshots start collapsed.

Enter in the single public-address form checks format through `POST /resolve`. Only supported Bitcoin/Ethereum addresses proceed. Unknown inputs and recognized transaction hashes receive distinct safe explanations. No blockchain provider lookup is made. The Discovery planner remains authoritative; format acceptance does not prove on-chain existence or control. Editing the subject clears its checked state and selections and invalidates prior planning consent.

## Planning, confirmation and budget

Explicit pivot selection followed by **Plan selected pivots** calls `POST /discovery/plan`. The plan shows canonical subject, each pivot/source, eligibility, cost class, authorized paid units, maximum requests/units/results, cache window and server expiry. Planning is visibly distinct from results and does not imply source work occurred.

**Run discovery** requires an all-eligible plan and a separate confirmation click. It posts the same intent with `expected_plan_fingerprint` to `/discovery/runs`, using a per-plan idempotency key. There is no browser executor, `/execute` call or automatic run when editing/opening the workspace. Server conflict errors require reloading or replanning; an uncertain same-plan retry retains its key. Changing selection, subject, refresh or paid authorization invalidates consent.

Cost classes are Free local, Free remote, Limited free and Paid. Paid units default to zero and must be explicitly entered for a selected implemented paid capability before planning can authorize it. No currency prices or total of unlike source units are invented. Backend eligibility and accounting remain authoritative.

## Runs, refresh and cancellation

Current run shows the actual server lifecycle, run ID, full subject, creation/start time, returned count, source outcomes/coverage, cache origin, retry-after when returned, cancellation time, budget authorization, attempted/reserved requests, consumed/reserved source units and known/unknown provider remaining quota.

Only the selected queued/running run is polled, every 1.5 seconds, with at most 80 consecutive reads. A terminal state, failure, navigation away or replacement selection stops polling; an in-flight read is aborted and its late response ignored. At the bound the analyst can use **Refresh run**. Returning to Discovery reloads the selected run locally. History is not continuously polled. Result pages are refreshed on terminal completion or explicit run refresh, not every status tick.

Cancel uses the current version and existing cancel endpoint. The page explains cooperative cancellation, preservation of committed material and charged units. Partial runs show both useful successful results and sanitized failed-source reasons; zero bounded results differ from unavailable sources.

Compatible cache use is the default. **Refresh sources** defaults off and explicitly bypasses reuse through a new plan/run. Cached records say **Cached observation** and display the original retrieval and source-observation timestamps. Cache windows are capability metadata, not claims that a particular plan has already found cached records. ED-2 determines actual reuse during execution.

## Results, observations and reviews

Each run-result page uses `/runs/{id}/results`, with 20 records and backend offsets/totals. It shows candidate kind, literal predicate, observation title/reference/source, original observed/retrieved time, inclusion/cache state, provenance count and current review attention. No relationship is translated into ownership/control language.

Result detail loads the normalized result and individually paginated observations and review history. Selecting an observation reads its dedicated immutable detail, including source/pivot, summary, citation, verification, timestamps, excerpt completeness and collapsed sanitized snapshot. References are text or explicit safe HTTP(S) links with `noopener noreferrer`; the frontend never fetches source URLs or previews. Endpoint IDs are shown as IDs because ED-2 does not return expanded typed endpoint subjects.

Reviews are exactly **Unreviewed / Relevant / Irrelevant**, with a required reason, current result version, selected observation ID and its content fingerprint. Save uses the real review API and reloads persisted state. Observation/review history has no edit/delete control. Relevance is not Attribution support.

When previously reviewed material changes, the earlier decision is labeled as previous, a renewed-review notice appears, and the review form defaults to Unreviewed rather than silently confirming the old decision. Historical run material remains its original observation inventory while the current result-level review is labeled separately.

## History, archive and storage availability

History uses backend status, subject-ID and include-archived filters. Pagination is server-side. ED-2 summary rows omit wallet addresses/counts, so the UI enriches only the current 20-row page using run-detail reads in groups of four. This displays actual subjects, dates, statuses, record/pivot counts and archive state without scanning all history or calling providers.

Opening a historical run reads its source outcomes and exact result inventory; it never reruns a transform. Archive/restore use current versions and preserve all observations/results. The page explains archival as retiring normal history, not deletion.

An uninitialized Discovery schema shows **Discovery storage is not initialized for this database.** Capabilities and diagnostic planning remain available. No button creates tables or runs a migration. The other eight workspaces keep their own state and behavior. Other errors use fixed local messages for missing records, invalid fields, conflicts, temporary storage failure and unexpected errors; raw exception text is never rendered.

## Focused backend defect found during browser verification

The application uses `SessionLocal(autoflush=False, expire_on_commit=False)`. ED-2 tests used default autoflush-enabled sessions. Reservation changed the source's quota fields and then entered `transition_source`, whose `populate_existing` read replaced those unflushed changes. The subsequent charged attempt failed because its quota snapshot lacked `policy`.

`test_discovery_session_boundary.py` first reproduced a failed run with the actual application session options. The sole production backend correction is an explicit flush of the reservation before that nested reload, inside the same transaction. No quota rules, units, cache policy or lifecycle semantics change. The regression verifies successful execution and preserved reservation/charge accounting; the existing executor suite remains green.

## Deferred boundaries

Discovery graph: **DEFERRED**. Although the original architecture grouped a graph with ED-3, this task explicitly permits deferral and prioritizes runs/results/history/reviews. ED-2 has no graph/expanded-subject endpoint. A separately scoped visualization can follow alongside real transforms; no placeholder graph or new API is introduced.

Attribution promotion: **DEFERRED to ED-6**. Wallet/Graph prefills remain ED-5. Real Label/manual/GitHub execution remains ED-4. No risk, Cases, Labels, Research, monitoring, provider, graph traversal or Attribution semantics are changed.

## Verification

Starting baseline: **749/749**, plus existing isolated browser smoke and AT-6 browser regressions. New tests cover static workspace contracts, local request/error boundaries, bounded polling, selection replacement and navigation cleanup, and the application-session reservation regression.

Final full suite: **793/793 passing** (44 added; 29 existing-category dependency deprecation warnings). All six Node frontend behavior tests pass. The three Discovery browser modes and both existing browser regression harnesses pass. `/`, `/health`, `/docs`, `/openapi.json` and Discovery assets return 200 in isolated route checks; existing Discovery API regressions remain green. The single Alembic head is unchanged at `20260913_01`. `git diff --check` and the production fixture-name audit pass. Nine files were added, eleven modified and none removed; no commit was created.

Browser verification uses temporary SQLite, explicitly migrated to **20260913_01** only inside test fixtures. Production-like mode keeps the empty production executor registry. Executor mode injects synthetic bindings exclusively from `tests/browser_discovery_server.py`, exercising real planning, execution, persistence, reviews, cache, refresh, partial failure and cancellation. Unmigrated mode proves zero Discovery tables after visiting the workspace. HTTP provider transports are blocked and browser request destinations audited. Synthetic records never enter production imports/startup.

Commands:

```powershell
$env:GREEDY_COLLECTOR_DATABASE_URL='sqlite:///:memory:'
$env:GREEDY_COLLECTOR_GRAPH_BACKEND='sqlite'
$env:GREEDY_COLLECTOR_MONITORING_BACKEND='apscheduler'
python -m pytest tests/ -q
node --test tests/discovery.test.cjs
node tests/browser_discovery.cjs production
node tests/browser_discovery.cjs executor
node tests/browser_discovery.cjs unmigrated
node tests/browser_smoke.cjs
node tests/browser_at6.cjs
git diff --check
```

No migration, dependency or commit is added. This phase stops at ED-3.
