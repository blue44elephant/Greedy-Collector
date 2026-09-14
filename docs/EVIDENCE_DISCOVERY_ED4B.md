# ED-4B: Public GitHub code mentions

`wallet.public_code_mentions` now uses the real GitHub REST Search Code API through the ED-2 executor, planner, accounting, cache and immutable observation services. No database migration, dependency or direct executor database write is added. Head remains **20260913_01**. Runtime contains no fixture results. ED-5 Wallet/Graph handoff and ED-6 Attribution promotion remain deferred.

## Verified API contract

Official documentation checked on 2026-09-14:

- [REST Search Code](https://docs.github.com/en/rest/search/search#search-code): authenticated code search, dedicated 10 requests/minute limit, text-match metadata, bounded pagination and incomplete results. Requests use `GET https://api.github.com/search/code` with `Accept: application/vnd.github.text-match+json`.
- [REST versions](https://docs.github.com/en/rest/about-the-rest-api/api-versions): the current version is **2026-03-10**, sent in `X-GitHub-Api-Version`. No unversioned dependency.
- [Legacy code search](https://docs.github.com/en/search-github/searching-on-github/searching-code): REST search uses bounded indexing, default branches and files under 384 KB; punctuation may be ignored. Quoted full-wallet query plus `in:file` expresses exact search intent, but GC independently verifies returned content. Missing results never establish absence from GitHub.
- [Rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api): primary/secondary limits, remaining/reset/resource headers and Retry-After govern safe deferral. No quota-probing request is made.

The endpoint documentation's authentication-required statement is used conservatively despite the fine-grained token subsection also mentioning unauthenticated public resources. GC requires a token; it does not try unauthenticated fallback. No live GitHub requests were made during implementation or verification.

## Configuration and public scope

Set the existing **DISCOVERY_GITHUB_TOKEN** server-side environment variable or repository `.env`. Existing dotenv behavior preserves process-environment precedence. The token is never sent to the browser. Use a dedicated token without private-repository access; broad organizational/repository grants are unnecessary for this feature. Token presence establishes configured capability, not verified authentication or remote availability.

Without a token, GitHub is implemented but not configured/executable; explicit execution remains safely unavailable with zero requests. Local Labels and manual search generation continue to work.

For a later manual real-provider check, configure the token privately, restart the normal standalone server (`uvicorn main:app --reload` from this repository), and open `http://127.0.0.1:8000/`. In Discovery, enter a public wallet, select Public code mentions, choose Plan selected pivots, then Run discovery. Inspect returned context and coverage; zero accepted mentions is a valid result. Use Refresh only when another provider request is intended. Do not paste the token into a wallet field, console, screenshot or report. This manual procedure was not executed during development.

The verified REST/legacy search documentation does not establish an `is:public` qualifier. GC does not invent one or treat unsupported syntax as a security boundary. It sends only the full investigated wallet and `in:file`, with no organization/private repository targeting. A broad token may cause GitHub to return restricted items transiently: GC requires repository `private` to be exactly false and, if supplied, `visibility` to be public **before inspecting fragments**. Unknown/private/internal visibility is omitted, with no candidate or observation retained. Returned provider totals describe search metadata, not a count of accepted public mentions. This response gate cannot prevent GitHub from transmitting a restricted hit to a broadly authorized token; least-privilege token configuration remains necessary.

## Exact evidence and identity

Input reuses Discovery canonical subjects: lowercase Ethereum/accepted Bech32 and case-sensitive Bitcoin Base58. A positive `repository_contains` candidate runs from the numeric GitHub repository identity to the investigated wallet. Stable logical identity includes the file path, subject and predicate. Different files, repositories and returned forks remain separate. Duplicate repository/path hits in one response produce one candidate/run inclusion.

Only a returned `text_matches` fragment with `property=content` can establish `exact_in_excerpt`. GC verifies the full identifier with word boundaries and chain-appropriate case semantics. Path-only, missing, truncated and substring matches are omitted. Provider match indices are not trusted as proof. No raw file, blob, README, arbitrary page or secondary API request is made.

At most one fragment of **1,000 characters** is retained per result, centered on the match. Match context records the full canonical wallet, returned spelling and local excerpt offsets. Obvious credential assignments/tokens incidental to the fragment are redacted; existing snapshot sanitization also removes configured credentials, unsafe URLs/debug material and local paths. If sanitization removes the supporting match, no positive result is emitted.

An allowlisted snapshot preserves public repository ID/full name/URL, file path/name/HTML URL, valid blob SHA when returned, optional fork flag and finite GitHub search score. Citations must be credential-free HTTPS `github.com` URLs within the returned repository. They are never followed automatically. Retrieval time is real UTC API time serialized using the existing ISO-8601 convention; unavailable publication/observation timestamps remain null. The SHA is identified as a blob/file SHA, not invented commit provenance.

GitHub score is ranking metadata, excluded from logical identity and material-change fingerprinting. Score-only refreshes still preserve a new genuine retrieval observation and its score, but do not require re-review. Changed fragment/SHA produces a new immutable material revision. Old observations/reviews survive refresh, movement and disappearance. A search fragment does not establish authorship, ownership, operation or wallet control.

## Bounds, cost and failure behavior

- LIMITED_FREE, not unlimited or monetary pricing.
- Default and maximum **30 results**; one page with `per_page` equal to the requested limit and `page=1`. The maximum fits one API page, so pagination is unnecessary. No extra pages are fetched to compensate for omitted hits.
- **One accounted request** per execution, 15-second HTTP timeout, 30-second framework deadline, 1 MiB decompressed response cap and existing normalized batch cap. Redirects, ambient HTTP proxies and automatic retries are disabled.
- Existing local quota policy: 10 attempts/minute, 100 units/day, 3,000/month; one unit/request. These are GC operating ceilings, not a guarantee of remaining provider allowance. Each request is charged before transport; cancellation is cooperative and the framework owns persistence.
- Safe quota JSON includes remaining, limit, allowlisted resource, UTC reset and Retry-After timestamps when valid. No raw headers, error payload or HTTP internals are retained. Unknown quota remains unknown.
- 401 maps to configuration unavailable; 403 maps to access/entitlement unavailable unless safe headers or the documented rate-limit message identify rate limiting. 429 maps to rate limited. Rate outcomes impose Retry-After/reset or at least one minute without an immediate retry. 422/malformed responses map to invalid provider response; 5xx/network errors to provider transport failure; timeouts to timeout.
- `incomplete_results=true` is preserved in observations and source coverage. Excess provider count produces limit-reached coverage. Successful bounded results do not imply exhaustive GitHub coverage. Independent successful pivots remain preserved when GitHub fails.

The real-session browser check exposed an existing ED-2 persistence defect: `fail_source` assigned the retry deadline, then `transition_source` reloaded the row with `populate_existing`, losing that assignment when application autoflush was disabled. ED-4B adds one explicit flush before the reload. A regression first reproduced the null deadline, then verified persisted Retry-After blocks a subsequent mixed run without another HTTP attempt. No table or quota semantics change was needed.

## Cache and retention

Existing cache reuse applies to successful bounded remote batches only: **24 hours**, or **at most one hour for empty results**. Partial/limit-reached batches are not cached. Explicit Refresh bypasses reuse. Cache hits incur zero requests and preserve original retrieval timestamps. Keys include canonical subject, transform/source versions, limits/parameters and policy/configuration generation.

The former pending-retention descriptor becomes `github-public-excerpt-v1`: only bounded public provenance and a small supporting fragment are permitted for this explicitly authorized investigation workflow. This is GC's restricted storage policy, not a claim that public repository contents have unrestricted reuse rights. Cache expiry does not delete immutable investigation history; existing archive/history behavior is unchanged. No entire files are stored.

## UI and boundaries

Discovery capabilities come from the actual bindings/configuration. Analysts explicitly plan and run the pivot; navigation, planning, review and history never trigger searches. Observation detail shows repository, file path, full wallet, source/retrieval time, optional blob SHA, **GitHub search score**, **Matched code context** and an explicit **Open on GitHub** link (`_blank`, `noopener noreferrer`, no-referrer). Snapshot details remain collapsed. Existing Unreviewed/Relevant/Irrelevant states and reason/version checks remain authoritative; exact matches are not automatically relevant.

No GitHub owner subject, Attribution, Label, Case, graph, KYC or risk mutation occurs. GitHub evidence contributes zero risk points. No secret search, contributor investigation, private-repository feature, recursive collection or Wallet/Graph handoff is introduced.

## Verification

Starting baseline: **835/835 passing**, clean working tree; Alembic head **20260913_01**. Focused tests use the real production executor with `httpx.MockTransport`, actual service/API persistence and isolated SQLite. Fixtures remain under `tests/`. Coverage includes configuration, full identifiers/case, public gating, exact fragments, unsafe metadata, caps/deduplication, quota/auth/errors, accounting/cancellation, mixed runs, cache/refresh/history/material review, routes/assets and unchanged subsystem row counts.

The isolated `node tests/browser_discovery.cjs github` mode uses the production factory/executor and a test-only mocked HTTP transport. It verifies code context/provenance, safe links without visiting GitHub, review, cache, changed material, rate-limit UI and navigation through all nine workspaces. Existing production local/manual, synthetic executor and unmigrated Discovery modes remain separate regressions. No automated test calls live GitHub or Google.

Final verification: **904/904 passed** (835 existing plus **69 new** tests; 29 existing-category dependency deprecation warnings). The Retry-After/session regression and execution checks also passed as a focused 77-test run. GitHub browser mode passed including empty results, retained historical observations, rate limiting and mixed Local Labels success without a second blocked GitHub request. Existing production local/manual, synthetic executor and unmigrated Discovery browser modes passed, along with the original workspace smoke harness and AT-6 Attribution/Case/report regression across all nine workspaces.

Routes `/`, `/health`, `/docs`, `/openapi.json`, Discovery APIs and assets passed isolated verification. `git diff --check` passes; Alembic reports the single head `20260913_01`. No migration or dependency was added, no live external provider call was made, and no production fixture markers were found in the Discovery runtime/frontend audit. Work is limited to the standalone repository and remains uncommitted. ED-4B is complete; stop here before ED-5.
