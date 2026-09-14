# ED-5: Wallet and Graph handoffs to Discovery

Wallet and selected supported Graph wallets now offer **Discover public evidence**. This is frontend navigation into the existing Discovery workspace. It adds no backend endpoint, database schema, migration, provider, transform or dependency. Production uses actual Wallet/Graph/API/database state; synthetic fixtures exist only in tests. ED-6 Attribution promotion remains deferred.

## Subject prefill and explicit execution

The shared `discovery_handoff.js` helper passes the full wallet address, known chain, origin workspace and an in-memory validity check. It never reads truncated display labels. Wallet actions appear inside successful fresh/stored wallet results, separate from Attribution. Transaction results, unresolved searches and errors hide the wallet result action.

Discovery checks the subject through the existing local `/resolve` endpoint and requires the resolved chain to match the handoff. After backend validation, the UI mirrors Discovery's existing lowercase Ethereum/accepted-Bech32 convention; the general resolver otherwise preserves Ethereum input case. Base58 case is preserved. This endpoint only classifies/validates syntax and makes no provider request. The Discovery planner remains authoritative; no competing address validator is added.

Every handoff clears old pivot selections, paid authorization values, refresh selection and plan/idempotency intent. Capabilities are read locally, including implemented-but-unconfigured GitHub. **Nothing is automatically selected, planned or executed.** Local Labels is not read as a transform, Google actions are not generated, and GitHub is not queried until the analyst selects pivots, inspects Plan, and explicitly confirms Run. Reading capabilities/history consumes no provider quota and creates no runs, observations or accounting entries.

## Return context

The origin banner shows the full canonical subject and **Back to wallet** or **Back to graph**. Return navigation reveals the existing in-memory view rather than submitting a lookup or reloading graph data. It skips the normal navigation-triggered Attribution refresh so the graph's selection, viewport, topology and overlay remain intact. Other normal workspace navigation still retains the existing Attribution refresh behavior.

The origin action must still belong to the current rendered view. A replaced wallet result, detached selected-node action or changed Graph selection cannot silently restore unrelated state. Stale/missing return context produces a safe explanation and the analyst can use the workspace tabs. No callbacks, URLs, tokens or navigation context are persisted in SQLite.

## Graph boundary

Only supported wallet subjects are eligible. Explicit transaction, entity-overlay and unsupported structural node kinds are excluded. The existing graph's `type` field is a wallet Label category (such as Wallet, Exchange or Unknown), so those annotations do not suppress wallet actions. Transaction connection and Attribution entity inspectors do not gain Discovery actions. The existing AT-4 Bitcoin Base58 case-sibling guard is reused: ambiguous folded graph keys are not passed as an exact wallet identity.

The action uses the full selected node ID and chain. It does not change node positions, edges, hop depth, selection algorithms or overlay meaning. No repositories or Discovery results are inserted into the blockchain graph. Proximity and code mentions do not imply identity or wallet ownership. Existing Attribution summaries, claim actions and overlay controls remain separate.

## Existing and active runs

History remains the existing global paginated list with its visible filters. Matching rows on a loaded page are marked **Current subject**. Handoff does not auto-open or rerun historical records. Existing selected run/result context is retained independently of the new input subject.

An active selected run for a different subject stays selected and continues. The banner explains that it has not been cancelled and a new run must wait for completion or explicit cancellation. Handoff never invokes Cancel. The existing backend single-active-run guard remains authoritative, including runs started elsewhere. Incoming handoffs during an in-progress UI operation are queued; the latest explicit handoff is applied after that operation finishes, rather than silently being dropped.

## Reload, unavailable storage and errors

This application has no persistent URL router for these views. Handoff/return context lasts for the current page session. Reload returns to the normal initial workspace, clears transient form context and never creates or resumes execution automatically; saved runs remain accessible through global history. No router rewrite or browser-storage history subsystem is introduced.

Without initialized Discovery storage, Wallet/Graph remain usable. Handoff still prefills/checks the subject and loads local capabilities, while history/storage reads show **Discovery storage is not initialized for this database.** The origin return button remains available. Neither startup nor handoff migrates the user's database. Invalid context, chain mismatch and stale selections display bounded errors without raw SQL, paths, credentials or stack traces.

## Verification

Starting baseline: **904/904 tests passed**, clean working tree, Alembic head **20260913_01**. Baseline browser regressions passed for all nine workspaces using isolated databases and mocked/blocked providers. AT-4 integration patterns and ED-1 through ED-4B contracts were inspected before implementation.

New lightweight tests cover routes/assets, shared context guards, full identifiers/case preservation, typed Graph eligibility, Bitcoin ambiguity and safe return behavior. Isolated browser modes `handoff`, `handoff_github` and `handoff_unmigrated` exercise actual frontend navigation and real local persistence. Fresh wallet provider responses and optional GitHub HTTP transport are mocked only in test modules. Database digests and provider counters verify zero automatic work; explicit Local Labels/GitHub runs use their production implementations. Graph snapshots compare node/edge positions, viewport, selection and overlay before/after return.

Final verification: **924/924 pytest tests passed** (20 added; the pytest wrapper also runs 7 Node behavior tests), with 29 existing deprecation warnings. All three ED-5 browser modes passed: `handoff`, `handoff_github`, and `handoff_unmigrated`. Existing Discovery production/executor/unmigrated/GitHub modes, the original workspace smoke test, and AT-4/AT-5/AT-6 browser regressions passed, covering all nine workspaces. Route checks passed for `/`, `/health`, `/docs`, `/openapi.json`, Wallet/Graph/Discovery assets, and existing Discovery APIs. Automated verification used isolated databases and test-only provider fixtures; no live external provider calls were made. `git diff --check` passed. Alembic remains at the single head **20260913_01**; no migration or dependency was added and the user database was not migrated. No commit was created.
