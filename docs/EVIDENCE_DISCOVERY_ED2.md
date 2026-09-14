# ED-2: Discovery execution framework and bounded API

ED-2 follows [the selected architecture](EVIDENCE_DISCOVERY_ARCHITECTURE.md) and reuses [ED-1 persistence](EVIDENCE_DISCOVERY_ED1.md). Alembic head remains **20260913_01**. There is no model, migration, provider, frontend or dependency change in this phase. The real database is not migrated during development or verification.

## Production executor state

**Zero production Discovery executors are registered.** `wallet.local_labels`, `wallet.manual_exact_web` and `wallet.public_code_mentions` remain descriptor-only. Actual Label execution, manual search-link generation and the public GitHub adapter belong to ED-4. ED-2 does not fetch pages, query search engines, open browsers or call wallet/Research providers.

Requested unimplemented descriptors produce source state `unavailable`, the existing `configuration_unavailable` error category and explicit `quota_snapshot.eligibility=not_implemented`. Capabilities expose `implemented=false`, `executable=false`, `unavailable_reason=not_implemented`. All-unavailable runs end `failed`; mixed successful/unavailable selections end `partial`. No manual-ready action or finding is fabricated. Synthetic executors exist only in tests and are injected into isolated runtimes.

## Executor interface and storage boundary

`executors.py` separates immutable descriptors from code-owned `Binding` objects. Each binding identifies exact transform/source versions, an async `TransformExecutor.execute(context)` implementation and a frozen `QuotaPolicy`. Registration rejects unknown pairs, version mismatches, duplicates, synchronous callbacks and inconsistent policies for one source. No environment, HTTP or database input can register Python code.

The execution context supplies the canonical public subject, validated parameters, source ID, deadline and cooperative cancellation checks. It contains no Session or credential/settings dump. Reviewed code must use `await context.request(operation, request_class)` for every remote attempt. That boundary checks cancellation and charges persisted accounting before awaiting the operation. Request classes are query, page, confirmation and retry. This is a contract for trusted code, not a sandbox for arbitrary Python or an API callback feature.

Executors return a strict `Batch` of typed candidates, bounded coverage, optional provider count and typed quota metadata. Candidates contain normalized endpoints, kind/predicate, fact key and ED-1 `ObservationInput`. `ExecutionService` remains authoritative for persistence and composes ED-1 normalization, fingerprints, dedupe, cache, immutable observations, reviews and optimistic lifecycle methods. No executor gets storage mutation methods.

## Plan and create-and-execute model

The architecture selected POST-to-run/202. There is therefore no separate execute route:

1. `POST /plan` validates a Bitcoin/Ethereum subject, one to three explicit registered transform/source pairs, parameters, refresh and budget. It writes no database rows and makes no provider requests.
2. The response includes per-source eligibility, maximum requests/units, query fingerprints and an expiring plan fingerprint. The fingerprint covers canonical intent, descriptors and operator configuration, plus a minute validity window. Expiry is the next minute boundary.
3. `POST /runs` requires the same intent and `expected_plan_fingerprint`. It recomputes the plan and rejects stale consent before atomically creating subject/run rows.
4. It returns `202 RunRead` and starts a process-owned asyncio task. Capabilities, GET/list, wallet lookup and selection never start work.

`Idempotency-Key` is an optional header bounded to 128 characters; omission generates a UUID. Identical canonical intent with the same key returns the existing run, even after completion/interruption, without replay. Different intent with that key conflicts. Intent includes refresh and budget, not just wallet identity. Expired planning consent does not prevent returning an already accepted identical idempotent run.

Only wallet root inputs are accepted. A source is inferred only when its transform has exactly one compatible source. Duplicate pairs, unrelated sources, unsupported inputs, unknown parameters, unselected budget sources and excessive limits fail before execution. `max_results` is the only current transform parameter.

ED-1 atomic commands now compose within an outer transaction, so a late creation failure cannot leave an orphan subject/run. Original standalone ED-1 service operations retain their behavior.

## Lifecycle, isolation and limits

Run states remain queued, running, completed, partial, failed, cancelled and interrupted. Sources retain ED-1 states. Sources execute sequentially within one active run. Each successful batch and source completion commits independently; another source's failure cannot roll back that material.

All successful bounded/cache/manual-ready outcomes mean completed. Useful material with unsuccessful sources or incomplete coverage means partial. No successful source means failed. Bounded empty results are successful operations, not claims of complete web coverage. Valid provider_incomplete, limit_reached or unknown coverage remains visible and makes the run partial.

Malformed or excessive output fails the entire source batch with invalid_provider_response. No item is silently discarded and no partial result/observation/run-item writes survive. Prior successful sources remain. Counts come from committed membership. Tests inject late failures after writes to prove rollback.

Limits are one active run, three selected pairs, at most 100 observations per pair, at most 12 attempts and at most 60 seconds per run; descriptors may be tighter. Callers can only reduce max_results. Returned batches exceeding result or byte caps are rejected. Unknown predicates/kinds, unsafe locators, missing provenance, nonfinite/non-JSON content, private-code material and oversized fields fail before commit. ED-1 sanitization and immutable triggers remain active. Future adapters must also bound upstream response bytes before constructing a Batch.

## Budget and quota enforcement

The request budget contains allow_free_local, allow_free_remote, allow_limited_free and paid_units (per-source strict nonnegative integers). Omitted paid allowance is zero. There is no currency conversion, billing or payment processing; unlike source units are never summed into a fabricated amount.

A PAID executor requires a positive allowance sufficient for its maximum declared units. The ledger shares that allowance across transforms using the same source; they cannot each spend it independently. Disabled free-class permissions also prevent execution. Code-owned source policies supply daily/monthly caps, maximum units per request, enabled state and a nonsecret operator account generation. The framework contains no provider-specific quota constants.

Quota accounts are source ID plus operator generation, independent of selected transforms, parameters and refresh. Changing a search cannot reset its allowance. Bindings sharing a source must share policy. Configuration identity used for cache fingerprints is also independent of the caller's selection subset.

Before invocation, a short SQLite transaction checks daily/monthly usage and reserves maximum units/requests. Active reservations plus terminal consumed units form the ledger. Before each mediated attempt, another transaction charges conservative units and appends time/request-class/charged-units metadata. No writer transaction spans awaited provider work. Exceptions, cancellation and uncertain outcomes do not refund charges.

Successful quota reports and source completion are atomic with the batch. Known remaining/reset values and reported units are retained. Lower reported units do not refund conservatively charged units; a report exceeding its reserved contract is rejected. Unknown remaining quota stays null. These caps cover Discovery, not other tools or existing Research using an account. Deadlines stop at the next UTC day boundary so reservations cannot cross daily/monthly windows.

## Cache, refresh and configuration

An eligible source checks ED-1 cache compatibility before invocation: canonical query, transform/source versions, parameters/limits, configuration/retention, successful bounded coverage and expiry. Adding another selected source does not change the existing source's logical query.

Cache hits call no executor, consume no remote units and attach original observations through a direct original-source reference. Observed/retrieved times and first/last genuine seen times remain unchanged. Explicit refresh bypasses reuse without deleting old observations. Identical later retrievals retain separate history; changed material remains separately observable and flags renewed review attention.

Executor existence, enabled state, required credential presence, retention permission and budget eligibility are checked before invocation. Configured is boolean presence only, not a validity/reachability probe. HTTP capabilities omit credential environment names and values. No token is required for startup. All production executors remain absent regardless of configuration.

## Rate limits, timeouts and retries

The rolling-minute limiter counts persisted attempts, including failed prior attempts, against the source descriptor's ceiling. A persisted future Retry-After blocks another attempt. Executors can signal typed rate-limit, timeout, transport, invalid-response, budget or configuration outcomes with bounded quota metadata.

There are no automatic framework retries. A future reviewed adapter may request another mediated attempt only inside reserved request/unit/deadline bounds. There is no unbounded retry, fallback provider, key rotation or automatic paid replay. Errors use existing bounded ED-1 categories; raw exceptions, SQL, tracebacks, headers and credential URLs are neither returned nor persisted as error text.

Async execution uses asyncio.timeout with the tighter descriptor/run deadline. Implementations must cooperate with cancellation and bound I/O; synchronous executors are rejected. The framework cannot terminate a blocking thread or undo an already sent request.

## Cancellation, recovery and overlap

Cancellation requires the current version. Queued cancellation prevents execution. Running cancellation persists cancelled state, marks only unfinished sources terminal, signals the event and requests task cancellation. Committed results and charges remain. Repeated terminal cancellation conflicts. A still-active task blocks replacement work until it finishes.

Normal startup performs guarded recovery: persisted queued/running work becomes interrupted; terminal history stays unchanged; nothing is replayed. Missing Discovery schema is nonfatal. Shutdown signals/cancels owned tasks, waits up to two seconds and marks remaining work interrupted. A temporarily unavailable database is recovered on the next startup. Non-cooperative implementations are unsupported; no unsafe thread kill is attempted.

Deployment supports one application process/worker. asyncio locks and task ownership are process-local; SQLite admission and idempotency are secondary protections, not distributed leases. Multiple workers with independent recovery are unsupported. Both same-query and different-query overlap conflict under the selected one-active-run policy. Different subjects run independently once the active run finishes.

## HTTP API

All suffixes are under `/api/greedy-collector/discovery`:

| Group | Method and suffix | Result |
| --- | --- | --- |
| Capabilities | GET /sources | Safe source capability metadata |
| Capabilities | GET /transforms | Implementation/configuration capability |
| Planning | POST /plan | Local validated expiring plan |
| Runs | POST /runs | Create and execute; 202 |
| Runs | GET /runs | Paged subject/status/archive filters |
| Runs | GET /runs/{run_id} | Subject, lifecycle, budget, sources and counts |
| Runs | POST /runs/{run_id}/cancel | Versioned cancellation |
| Runs | POST /runs/{run_id}/archive | Archive terminal history |
| Runs | POST /runs/{run_id}/restore | Restore archived history |
| Results | GET /runs/{run_id}/results | Paged historical inventory/current review summary |
| Results | GET /results/{result_id} | Stable normalized result/review revision |
| Results | GET /results/{result_id}/observations | Paged observation summaries/provenance |
| Results | GET /observations/{observation_id} | Sanitized immutable detail |
| Review | GET /results/{result_id}/reviews | Paged append-only review history |
| Review | POST /results/{result_id}/review | Versioned relevance decision |

There is no /execute, /promote, executor-registration, generic CRUD, graph or recursive-pivot endpoint. Every success response has an explicit Pydantic model. OpenAPI exposes run/source/review/cost/error enums, modes and candidate contracts. SQL pagination defaults to 20, maximum 100, with items/total/limit/offset/next_offset. Summaries omit source snapshots; immutable detail has its own route.

Reviews reuse ED-1 result-version and selected-observation fingerprint checks. States are exactly unreviewed, relevant, irrelevant; promotion is not a review state. Changed content preserves earlier decisions with new_material_since_review. No review creates Attribution evidence.

## HTTP safety and unavailable schema

Mappings: 404 missing records; 409 stale plan/version, duplicate intent, overlap or lifecycle conflict; 422 invalid subject/selection/parameters/budget/body; 503 unavailable schema/storage/executor; 500 unexpected error. Fixed messages never echo supplied secrets or raw exceptions.

Discovery mutations validate Origin when supplied, reject cross-site fetch metadata and require JSON bodies bounded to 32 KiB. Cross-origin mutation returns 403. Local CLI clients may omit Origin. Existing CORS/Attribution behavior is unchanged. This is not authentication; local-bind/single-analyst deployment assumptions remain.

Capabilities and planning stay local and usable without migrated storage. Persistence routes return safe 503. Startup never creates Discovery tables or runs Alembic, and the eight existing workspaces remain usable.

## Boundaries and verification

Creation/execution/review changes no Attribution, risk, Cases, Labels, Research, monitoring or blockchain collection. Wallet lookup never starts Discovery. There are no production fixtures, fake results, frontend changes, external provider implementations or new dependencies.

Baseline: **632/632**. Added: **117 tests**. Final full suite: **749/749 passing**, with 29 dependency deprecation warnings. Tests use isolated SQLite, blocked external transports, test-only executors, real service/API serialization, OpenAPI and startup/shutdown checks. Coverage includes source isolation, budget/account identity, shared allowances, quota/rate limits, cache/refresh/provenance, malformed batches and late rollback, cancellation (including shutdown before a worker starts), restart interruption, idempotency and review boundaries. The ED-1 startup test now expects guarded Discovery routes instead of their earlier absence; schema/no-seeding checks remain. Attribution's OpenAPI regression checks its unchanged legacy surface separately from Discovery; Discovery-specific error schema names preserve existing Attribution schema references.

Verification confirms 15 Discovery operations across 14 paths, explicit success/error schemas, the existing 54 non-Discovery paths, all eight workspace assets and normal migrated/unmigrated startup/shutdown. Head remains `20260913_01`; migration/ORM/FK checks remain green. `git diff --check` passes. A 145-file starting hash inventory confirms seven existing files changed and the other 138 are byte-identical, including all migrations, models, Attribution implementation, providers, risk and frontend assets. Eight files were added; none removed. The README's existing bytes were preserved, including legacy punctuation encoding. No real database was inspected/migrated, no live provider request or browser screenshot was made, and no commit was created.

No screenshots or browser loops are used. Verification commands use isolated settings:

```powershell
$env:GREEDY_COLLECTOR_DATABASE_URL='sqlite:///:memory:'
$env:GREEDY_COLLECTOR_GRAPH_BACKEND='sqlite'
$env:GREEDY_COLLECTOR_MONITORING_BACKEND='apscheduler'
python -m pytest tests/ -q
python -m alembic heads
git diff --check
```

ED-3 is the next separately authorized phase: the vanilla Discovery workspace and typed graph over local APIs. Initial transform implementations remain ED-4. This increment stops at ED-2; no commit is created automatically.
