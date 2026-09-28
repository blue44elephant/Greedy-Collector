# Broad Wallet Discovery (OSINT-2)

From a Wallet, choose **Broad Discovery**, inspect preflight, then explicitly run
selected sources. The detailed transform view remains available. Opening the
workspace, planning, filtering results, and selecting graph nodes issue no provider
requests. A run federates applicable Local Labels, GitHub exact mentions,
GraphSense public tags, Ethereum ENS and broad web search through the existing
Discovery executor, quota, run, result and immutable observation architecture.
Manual Exact Web and Manual Source Observation remain explicit manual operations.
Unrelated Research APIs are not queried with arbitrary wallet strings.

## Optional official search provider

Brave Web Search uses its documented server-side API at
`https://api.search.brave.com/res/v1/web/search`. Set `BRAVE_SEARCH_API_KEY` in the
server environment. GC persists search metadata, so enable
`BRAVE_SEARCH_STORAGE_ALLOWED=true` **only after obtaining appropriate storage
rights from Brave**. Without both settings this provider is unavailable; the rest
of GC continues to work. No browser receives the key. Restart after configuration.

The UI cost category is LIMITED_FREE, not a guarantee of free usage. Available
credits, paid requests and storage entitlements depend on your provider plan.
Check [Brave API documentation](https://api-dashboard.search.brave.com/api-reference/web/search/post)
and [storage guidance](https://api-dashboard.search.brave.com/documentation/resources/help-feedback).
No new library or runtime CDN is used.

## Queries, provenance and candidates

`DiscoveryProvider`, `DiscoveryQuery`, `DiscoveryObservation`,
`DiscoveryCandidate` and `DiscoveryExecutionResult` define the narrow provider
boundary. Existing source/transform descriptors own configuration, supported
chains, versions, costs, network behavior and cache policy. Typed query kinds are
EXACT_WALLET, EXACT_TXID, EXACT_ALIAS, DOMAIN, URL and ENTITY_NAME. Only EXACT_WALLET
executes today. The canonical address is quoted; chain and wallet remain separate
identity fields even where EVM search text is identical across chains.

Returned URL/title/snippet must contain the full canonical wallet token (using
existing chain case semantics) to qualify as exact wallet metadata. A fuzzy hit is
labelled `exact_match=false`, has a search-candidate graph edge, and cannot be
promoted as wallet evidence. Snippets are not full source content. GC does not
fetch arbitrary search result URLs. URLs are normalized, fragments removed, unsafe
schemes, credentials and private IP literals rejected. No DNS or WHOIS enrichment.
Hostname is retained; registrable domain is explicitly unavailable because GC does
not guess public-suffix boundaries.

Categories describe source type, never reliability: explorer, code, community,
news, government, legal, sanctions publication, research, marketplace, social or
other. Descriptive quality fields include exact token presence, metadata structure,
institutional hostname, timestamps, unknown primary/secondary status and
reachability **not checked**. No ownership or identity probability is calculated.

Domain candidates come from URL hostnames. Alias/entity candidates require explicit
labelled text such as `alias: ...` or `organization: ...` in exact-match metadata.
Candidates preserve literal text, extraction method, confidence **type**, source
observation, URL and chain-scoped wallet. They do not become Attribution entities,
claims, Labels, risk inputs, clusters, watchlists or alerts. No recursive alias,
domain, person or other follow-up execution is implemented.

Canonical URL groups retain individual provider observations/ranks and result IDs.
Existing Discovery fingerprints retain first/last seen, source versions, historical
observations and cache inclusion. Results have local provider/category/relevance/text
filters and descriptive groups. Discovery graph adds wallet-to-source and
source-to-alias/entity/domain edges; the blockchain graph is unchanged.

## Review, promotion and Cases

Inspect a source and explicitly record Relevant, Irrelevant or Unreviewed with a
note. Candidate reviews are independent and cannot authorize source promotion.
ED-6 promotion requires a Relevant review of the selected immutable source material,
then explicit selection of an existing analyst-created Attribution claim and link.
No Entity or Claim is automatically created. Evidence origin is `public_osint`;
query, URL, title, snippet, category, retrieval time, provider and analyst note are
retained. Matching a publication does not mean GC verified its allegations.

Pin a terminal broad run to a Case to preserve wallet, run dates, provider set,
versions, bounds, cache/partial status, observations, candidates, source/candidate
reviews and source-data fingerprint. Case reports read this immutable snapshot;
later searches or reviews do not rewrite it. Existing source inspection and review
summaries remain current outside the Case snapshot.

## Bounds, failures and cache

Default web limit: 20 results; hard maximum: 50. Up to 6 source selections and 200
aggregate results are permitted per broad run. Each existing provider retains its
own stricter limits. Brave permits at most 3 requests per execution, 15 seconds per
HTTP operation, a 45-second executor deadline and 1 MiB response per request. Run
deadline is 60 seconds; no retries or hidden background searches. Operator limits
are 100 requests/day and 1000/month for Brave. More results, omitted unsafe URLs or
later-page failures are reported as incomplete; prior successful pages are retained.
A failed/unavailable provider does not erase successful sources. Preflight exposes
availability and cost without network requests.

Complete positive web results cache for 6 hours; empty results for at most 1 hour.
Incomplete/failed results are not reused. Explicit Refresh sources bypasses cache.
Provider retention entitlement is checked before execution/cache reuse. No universal
coverage or comprehensive identity discovery is claimed.

## Migration and boundaries

Revision `20260928_01`, parent `20260927_02`, adds source-bound candidates and their
append-only reviews, indexes and immutable Broad Discovery Case-pin guards. It does
not add a parallel run/evidence model. Startup does not apply it. Apply migrations
only through your normal explicit operator workflow; development verification uses
temporary databases and leaves the configured user database untouched.

No Tor, crawler, arbitrary content capture, authenticated private account access,
breached data, private KYC or covert tracking. Onion citations stay inert. Manual
Source Observation remains the mechanism for analyst-observed onion material.
OSINT-2B may later add explicit safe public-source capture; dedicated legal datasets
and additional search providers need documented APIs and retention policies first.

## Verification and optional operator check

Automated tests use isolated SQLite and test-only HTTP fixtures. Consolidated smoke:
`node tests/browser_osint2.cjs`. No production runtime imports fixture data.
For an optional live check, configure an entitled Brave account, open a public Wallet,
choose Broad Discovery, inspect the exact quoted query and bounds, select only Brave,
and explicitly Run discovery once. This consumes provider quota; it is not automated.
