# ED-7: Typed Discovery graph

Discovery runs can be visualized as a typed OSINT graph inside the existing ninth workspace. This increment implements the graph deferred from ED-3. The original architecture's later-adapter roadmap is not part of this task: no new transforms, executable subject types, providers, automatic pivots, inference, dependency or schema change is introduced.

## Scope and data source

The analyst chooses a stored run and explicitly switches from **Results** to **Graph**. The graph is a projection of that run's immutable `discovery_run_items`, joined to its included observations and logical results. It does not load the whole Discovery database. Run status, source failures, coverage and manual actions remain visible in the existing Current run panel.

`GET /api/greedy-collector/discovery/runs/{run_id}/graph` returns an explicit `GraphRead` schema with root, result nodes, literal directed edges, current analytic summaries and pagination. Existing result pages omit compact source snapshots and promotion counts; constructing this view through those endpoints would require per-node detail requests. The new endpoint instead batches those joins and aggregates, with no additional persistence. Data query count stays constant as page size grows; schema checks are also constant per request. There is no request per displayed node.

The endpoint defaults to and permits at most **100 logical results per page**, plus the root. Offset pages use stable predicate/result-ID ordering. Multiple included observations of one result produce one node; the representative is the first by run-source ordinal, run-item ordinal and observation ID. All included observations remain accessible through the existing paginated observation inspector. Graph pages show **Showing X of Y Discovery results**, with explicit previous/next controls. The ordinary Results view remains available with its existing pagination. Counts are stored-run counts, not claims of exhaustive public-source coverage.

## Types and literal direction

| Node | Identity and material | Directed relationship |
| --- | --- | --- |
| wallet | `discovery:subject:<id>`; canonical chain-qualified run subject | Focus root, not an attributed entity |
| label_annotation | `discovery:result:<id>`; actual included Label snapshot | Wallet → annotation: `locally_labeled_as` |
| code_location | `discovery:result:<id>`; result-scoped repository/file citation | Code location → wallet: `repository_contains` |

The code edge follows architecture section 9, preserving repository-to-wallet semantics even though execution started from a wallet query. Different files, repositories and conflicting Labels remain separate results. A code-location card is a presentation of the persisted repository/file result, not a newly stored subject or a repository-owner Entity. The graph adds no ownership, Attribution or transaction predicates.

Manual exact-web actions and unexecuted capabilities create no graph nodes or edges. A valid empty run displays its real wallet root and **No Discovery results were returned for this run.** Partial runs display genuinely committed results from successful sources; failures remain in source status, not invented failure nodes.

## Historical material and current analytic status

Node content comes only from observations included in the selected run. Later Label edits, GitHub changes, cache refreshes or new results do not rewrite old run membership or replace its selected material with the newest observation. Cached membership retains the original observation ID and retrieval timestamps.

The graph explicitly distinguishes this historical material from **current** result-wide relevance, renewed-review attention, observation counts across runs and promotion counts. First/last included retrieval times refer to the actual included observations, including their original times for cache reuse. Run observation count and current cross-run observation count are labeled separately.

Unreviewed, Relevant and Irrelevant are visible in node/detail text, including Irrelevant results by default. Changed material shows **Review required** alongside the previous decision. A separate **Promoted: N** badge never replaces relevance. Promotion counts include retained historical promotions, including withdrawn links, and do not select a winning claim.

## Layout and interaction

The dependency-free SVG layout fixes the wallet at `(0, 0)`. Code locations are grouped to the left; Label annotations to the right. Each group sorts by its namespaced result ID. It uses `ceil(sqrt(2 × group count))` rows, 190-unit row spacing, an initial 520-unit horizontal offset and 410-unit column spacing. Cards have fixed 310 × 146 bounds and bounded display labels; full material remains in tooltips/details. The same page membership always produces identical positions. No force simulation, random seed or graph inference is used.

Curved directional arrows connect actual endpoints. Predicates appear on small graphs (up to eight results), on tooltips and in edge detail; large pages avoid overlapping permanent edge text. Nodes differ by text marker, corner shape and background. Focus and selection have distinct styling. All nodes/edges support keyboard Enter/Space selection; Escape selects the root.

Controls provide Fit to graph, Zoom in/out and Reset view. Dragging empty space pans; the mouse wheel zooms. A reachable textual result list exposes the same loaded page. There are no implicit filters or hidden Irrelevant nodes. Large graphs retain all results through explicit pagination and pan/zoom; fitted labels may require zoom for inspection.

Viewport and selection are retained in memory for the eight most recently viewed run/page combinations. Returning from result inspection or Attribution refreshes local analytic metadata while preserving those controls where the selected result remains on the page. A full browser reload clears this transient state. No viewport is stored in SQLite.

## Details and navigation

Wallet detail includes full address, chain and Copy wallet address. **Open blockchain graph** opens the separate blockchain workspace and prefills its wallet; the analyst explicitly uses its existing Load graph action. This navigation makes no wallet/provider request and does not merge graph models.

Result/edge detail includes the literal predicate, result and selected observation IDs, source/transform, included retrieval times and current analytic summaries. Label detail shows annotation type, original source and confidence explicitly as annotation metadata. Code detail shows repository, path, available blob SHA, summary and bounded context. No giant raw snapshot is dumped into graph detail.

**Open result** and **View observations** use the existing Discovery inspector with the exact selected run observation. Review and promotion remain there, using their established reason/version/fingerprint and ED-6 eligibility checks. **Back to Discovery graph** restores the graph. There is no second review or promotion implementation. Promoted result detail can read a bounded ten-row promotion page and open the exact Attribution claim; withdrawn state remains visible.

External source links open only on explicit click with `_blank`, `noopener noreferrer` and no-referrer. No previews, thumbnails, embedded pages or automatic URL fetches exist.

## Lifecycle, compatibility and boundaries

Graph refresh uses the existing run lifecycle: explicit graph/run opening and refresh, terminal completion, review completion or return navigation. No second polling loop is added. Active runs may show their committed partial inventory on explicit refresh. Leaving the workspace aborts pending graph reads; stale responses cannot replace a new run's graph. ED-5 handoffs still prefill only, clear pivot intent and return to the Results view without executing or automatically opening a graph.

At `20260913_01`, basic Discovery graphs work without the promotion table; promotion metadata is explicitly unavailable. At `20260915_01`, current promotion counts and navigation are available. Without Discovery storage, the existing safe initialization message remains and graph access fails safely. No graph control migrates or creates storage.

Graph reads, selection, pan/zoom and navigation call only local GC APIs. They create no runs, Entities, Claims, Labels, Cases, reports or risk findings and consume no provider quota. Repository occurrence and graph proximity do not establish control or common ownership. No clustering, recursive crawling, additional executable pivots or blockchain collection is added.

The boundary re-sanitizes each bounded node using existing secret/URL/path handling. The aggregate page is not treated as a single 16 KiB observation. Runtime contains only genuine persisted data; all synthetic material and mocked providers belong to automated tests.

## Verification

Starting baseline: **1002/1002**, 38 warnings. Final `python -m pytest tests/ -q`: **1028/1028**, 41 warnings, 314.73 seconds. All baseline tests remain; **26 pytest tests were added**, including a wrapper for six Node layout/zoom behavior tests. The focused graph/API/frontend run passed **68/68**. Tests cover literal direction, root and result types, duplicate observations, conflicting Labels, distinct repositories/files, historical content versus current review/promotion state, withdrawn promotion history, deterministic paging/layout, bounds, secret redaction and constant query count. A full-table before/after comparison verifies graph reads do not mutate any subsystem.

All **20 isolated browser runs passed**: three new graph modes (ED-6 head, ED-1 partial migration and unmigrated), ten existing Discovery modes, six migrated/unmigrated AT-4/5/6 runs and the existing workspace smoke harness. The graph scenario exercises real Local Label persistence, mocked GitHub transport, mixed node types, keyboard/node/edge selection, pan/zoom/reset, result and ED-6 promotion handoffs, retained viewport, historical run reopening, a partial run with 101 logical results and two graph pages, manual/empty runs and blockchain-workspace prefill. Existing Wallet, Graph, Monitoring, Alerts, Cases, Labels, Research, Attribution and Discovery workflows remain green. No live external provider calls were made and no extra screenshots were needed.

Isolated route checks returned 200 for `/`, `/health`, `/docs`, `/openapi.json`, Discovery capabilities/history and graph/frontend assets. Missing graph run IDs returned a safe 404; unmigrated graph access returned a safe 503. Production-path audits found no fake/sample/canned graph datasets. `git diff --check` passed.

Starting and final Alembic head: **20260915_01**. ED-7 changes no migration, model, provider, risk rule, dependency or blockchain graph renderer. The real user database was neither inspected nor migrated. Changes remain uncommitted.

Work stops at ED-7. Additional sources, subject types, recursive execution and graph inference remain outside this increment.
