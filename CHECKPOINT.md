# Greedy Collector — resume checkpoint

Saved 2026-09-11 at the user's request to stop after the current subtask.
Resume when the user says **Continue**. Do not restart implementation.

## Scope and request

Work only in `C:\Tools\Inventions\greedy-collector`. Never modify Epic Archer.
The active request is the attachment:
`C:\Users\user\.codex\attachments\df0ce606-df21-4baf-a909-ce3987d7cefe\pasted-text.txt`.
Read it for the full final-report requirements.

It supersedes the prior seven-workspace interface request. This increment exposes only
Wallet and Graph, using the real existing API, providers, and SQLite state. Mocks belong
only in automated tests. No monitoring/backend/provider/risk/schema changes in this task.
No automatic commit. Final verdict, once verification is complete:
`WALLET_GRAPH_UI_COMPLETE` or `WALLET_GRAPH_UI_INCOMPLETE`.

## State at task start

Starting suite was **124/124 passing**, including previous backend work. The worktree
was already dirty with these tracked files: `.env.example`, `README.md`,
`greedy_collector/config.py`, `greedy_collector/monitoring.py`,
`greedy_collector/router.py`, `greedy_collector/schemas.py`,
`greedy_collector/services.py`, and `main.py`.
Already-untracked files included `static/`, `tests/test_ui.py`,
`tests/test_monitoring_api.py`, `tests/browser_server.py`, and `tests/browser_smoke.cjs`.
Preserve those pre-existing backend changes. None were changed during this resumed task.

## Completed changes

- Root already served the real plain HTML/CSS/vanilla JS app; retained that route.
- Restricted navigation and initialization to Wallet and Graph.
- Deleted only the five out-of-scope frontend modules:
  `static/js/monitoring.js`, `static/js/alerts.js`, `static/js/cases.js`,
  `static/js/labels.js`, `static/js/research.js`.
- Wallet uses actual POST lookup and separate stored profile/transactions/risk GETs.
  Added stored-data limitations, risk calculation timestamp, distinct missing-risk state,
  fresh/stored transaction captions, and a permanent rule-based risk clarification.
  Existing exact balance strings, token amounts, mempool state, evidence details,
  full-value tooltips, provenance allowlist, and explicit counterparty lookup remain.
- API frontend errors use fixed safe messages and only exact known validation details.
  Removed unused download/source-link functions associated with removed workspaces.
- Graph uses actual stored nodes/edges for hops 1–3. Added directional SVG arrows and
  self-transfer loops, timestamp tooltips, precise truthfulness text, and blank-input
  handling. Existing node selection/investigation and pan/zoom remain.
- README now documents Wallet/Graph only, real endpoints, server-side credentials,
  bounded histories, persistence limitations, and optional existing browser test.
- Expanded UI contract tests to cover persisted lookup fields, missing stored risk,
  and real SQLite graph shapes for both chains at each hop depth. Replaced five removed
  asset-positive tests with five tests asserting those workspaces/assets are absent.
- Refocused the existing browser smoke test on Wallet/Graph. Provider fixtures remain
  solely under tests. Added test-only empty, mempool/token, and safe-error cases; disabled
  scheduler startup only in this temporary browser test server.

Files modified in this task (relative to its starting worktree):
`README.md`, `static/index.html`, `static/js/app.js`, `static/js/api.js`,
`static/js/wallet.js`, `static/js/graph.js`, `tests/test_ui.py`,
`tests/browser_server.py`, `tests/browser_smoke.cjs`.
`static/app.css`, `static/js/ui.js`, `main.py`, and all backend files were unchanged.
This checkpoint is the only newly added repository file in this resumed task.

## Verification already completed

1. Starting full suite: 124 passed.
2. Focused `tests/test_ui.py`: **30 passed** (eight additional cases; backend tests retained).
3. All production JS modules and browser script passed `node --check`.
4. `git diff --check` passed; only existing LF/CRLF notices in backend files.
5. Preliminary static scan found no fake/canned/mock datasets or extra workspace controls.
6. Latest browser smoke test **PASSED** after fixing a test fixture that selected the
   validation chain from address spelling instead of the mocked adapter's chain.
   Verified BTC/ETH, exact decimals, ERC-20 units, Bitcoin mempool, stored timestamps,
   explicit counterparty investigation, graph hops/selection/investigation/zoom/reset,
   empty transactions/risk/counterparties/graph, missing stored address, blank/invalid
   input, missing Ethereum configuration, provider errors, and restored controls.
   No uncaught browser exceptions. Only test providers and temporary SQLite were used.
   Screenshot: `C:\Users\user\AppData\Local\Temp\gc-browser-448b0q\wallet.png`.
   Browser and temporary test server were shut down by the script's finally handler.

## Remaining work on Continue

1. Inspect current git status for any intervening user changes; preserve them.
2. Optionally view the saved screenshot. Do not rerun successful browser checks unless
   further changes or an unresolved concern justify it.
3. Run the final full suite. Expected total: **132**, not yet verified at this checkpoint.
   Previous run command avoided cache/database writes outside the sandbox:
   ```powershell
   $env:GREEDY_COLLECTOR_DATABASE_URL='sqlite:///:memory:'
   python -B -m pytest tests/ -q -p no:cacheprovider
   ```
   The user's requested command is `python -m pytest tests/ -q`; the equivalent flags
   above only suppress bytecode/pytest cache output. Use isolated test state.
4. Finish real-data/credential audit without printing secret values. Scan production
   runtime and assets; compare configured key values from environment/.env against assets
   privately. Confirm production never imports browser fixture code. No live provider
   calls during automated tests.
5. Confirm route status: `/`, `/health`, `/docs`, `/openapi.json`,
   `/api/greedy-collector/status`, CSS and all five JS modules. Focused tests already
   cover these, but summarize explicit route results for the completion report.
6. Recheck `git diff --check` and exact file status. Distinguish this task's modifications
   from the earlier backend changes already in the working tree.
7. Deliver the requested final report covering Wallet, fresh/stored state, transactions,
   risk, counterparties, graph, errors, runtime-data YES/NO audit, test counts, exact
   added/modified/removed files, routes, git status, and final verdict. Do not commit.

## Sandbox and staging notes

The session cwd/writable root was Epic Archer, although the task is standalone. All tool
commands were explicitly run with the standalone workdir. Required standalone writes
and GUI browser execution used `sandbox_permissions: require_escalated`; approvals
succeeded. Never bypass sandbox permissions or write task files into Epic Archer.

Temporary staged files/scripts are in
`C:\Users\user\AppData\Local\Temp\gc-wallet-graph-work`.
`manifest.json` contains start-of-task hashes useful to confirm backend files unchanged.
Do NOT rerun `prepare.py`, `finish_stage.py`, or `sync_stage.py`: edits are already applied,
and those scripts are preparation artifacts rather than a repeatable build process.
The browser server fixture received one later correction directly in its staged file
and was copied into the repo. Current staged and repo browser_server.py match.

No commit or live production provider lookup was performed. Work is deliberately paused,
not marked complete, in response to the user's checkpoint request.
