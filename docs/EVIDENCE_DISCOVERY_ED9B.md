# ED-9B: GraphSense Public TagPack Discovery

Discovery can query GraphSense public TagPacks for source-backed BTC/ETH address
annotations. Transform `wallet.graphsense_public_tags` is automated,
`LIMITED_FREE`, explicitly selected, and uses the existing `github` source account.
It does not establish ownership or implement clustering.

## Upstream verification and assumptions (2026-09-22)

The upstream [repository](https://github.com/graphsense/graphsense-tagpacks) is
public, uses the `master` branch, and keeps TagPacks under
[`packs/`](https://github.com/graphsense/graphsense-tagpacks/tree/master/packs).
Its [license](https://github.com/graphsense/graphsense-tagpacks/blob/master/LICENSE)
is MIT, copyright Iknaio Cryptoasset Analytics GmbH and AIT Austrian Institute of
Technology. Repository guidelines require public-source provenance. GC stores
selected metadata and pointers, not a redistributed TagPack corpus. License and
source attribution remain attached to each observation.

The [TagPack guide](https://github.com/graphsense/graphsense-tagpacks/wiki/GraphSense-TagPacks)
documents YAML headers, a `tags` list, inheritance and per-tag overrides.
The [current tool schema](https://github.com/graphsense/graphsense-tagpack-tool/blob/master/src/tagpack/conf/tagpack_schema.yaml)
also includes `network`, `actor`, `concepts`, `tag_type` and transaction tags;
the older wiki's embedded schema is not the complete current schema.
The [current implementation](https://github.com/graphsense/graphsense-tagpack-tool/blob/master/src/tagpack/tagpack.py)
defaults missing network to currency separately at header and tag level.
GC follows that fallback for historical packs, while requiring an explicit
currency. An explicit network must match. This compatibility does not make BSC
an Ethereum network. Transaction-only tags are outside ED-9B.

The inspected [BITB pack](https://github.com/graphsense/graphsense-tagpacks/blob/master/packs/BITB_etf.yaml)
uses inherited creator, category, confidence, actor, source, date and cluster
metadata with a per-address label, and omits network. No addresses or annotations
from this verification are seeded into GC.

## Transport, exact query and bounds

Reuse ED-4B's `github.api_json` transport, timeout, token, safe errors, request
charging and rate headers. The configured environment variable is
**`DISCOVERY_GITHUB_TOKEN`**, the existing GC name for the GitHub token; there is
no new GraphSense login or parallel token setting. Missing token means unavailable.
The token stays server-side; use one without private-repository access.

`GET https://api.github.com/search/code` uses the complete canonical address:

```text
"<canonical wallet>" repo:graphsense/graphsense-tagpacks path:packs in:file
```

GitHub documents that its REST API uses
[legacy code-search syntax](https://docs.github.com/en/search-github/searching-on-github/searching-code).
Indexing is bounded to searchable default-branch content, not complete repository
history. Search case/punctuation behavior is not proof of a tag match.

Candidate metadata must explicitly identify the approved public repository,
a safe `packs/` YAML path and a 40-character blob SHA. Secondary retrieval uses
the official [Git blobs API](https://docs.github.com/en/rest/git/blobs), constructed
locally as `/repos/graphsense/graphsense-tagpacks/git/blobs/<sha>`.
GC verifies returned size, encoding, SHA and the Git object content hash.
It does not use a supplied download URL. Blob SHA is not called a commit SHA.

- One search, at most **nine candidate files** and ten requests total. Nine is
  deliberately smaller than ten files to fit the existing ten-attempt/minute account.
- **256 KiB** decoded per file, **1 MiB** aggregate parsed file content.
- Search JSON at most 1 MiB; blob JSON at most base64 expansion plus 16 KiB.
- At most 100 returned observations, a 900 KiB validated-record budget beneath
  the existing 1 MiB serialized batch limit (inherited metadata can expand),
  and a 60-second execution deadline. Individual sanitized snapshots retain the
  existing 16 KiB limit.
- No redirects, proxies, automatic retry, source-site fetching, actor lookup,
  Tor, recursive address retrieval or blockchain-provider request.

GitHub `incomplete_results`, omitted candidates, malformed/unsupported content,
failed secondary retrieval and exhausted bounds yield partial coverage.
Valid observations already obtained survive a failed secondary fetch. An empty
bounded success means only: **No matching GraphSense public tag was returned
within the bounded search.** It is not a clean-wallet or unknown-owner judgment.

## Safe parsing and exact matching

PyYAML **6.0.3** was already installed; requirements now explicitly pin it rather
than rely on a transitive installation. A bounded subclass of `SafeLoader`
rejects aliases, duplicate/non-text mapping keys, unsafe/custom tags, excessive
depth and more than 20,000 YAML nodes. No object construction, includes, CSV
references or parent-directory traversal. Unsupported includes are reported as
incomplete; GC never resolves or fetches them. UTF-8 text is required.

A positive observation requires an actual address entry after supported field
inheritance, canonicalized by GC's existing wallet normalizer. Ethereum and
accepted Bitcoin Bech32 case normalize; Base58 spelling remains case-sensitive.
Prose matches, substrings and transaction tags produce no address annotation.
BTC investigation accepts BTC currency/network; ETH accepts ETH. BCH, LTC, SOL,
BSC and explicit conflicting networks are not equivalents. This is format and
published-tag matching, not independent verification of the attribution.

Preserved fields, when supplied and safely typed: label, title, creator, category,
confidence, actor, source, lastmod, is_cluster_definer, currency/network, abuse,
tag_type and bounded concepts. YAML dates/datetimes become ISO-8601 strings.
GC does not invent confidence or cluster-definer defaults. Missing optional
fields are absent. Only matching-wallet metadata is retained; raw YAML, prose
and other-wallet entries are discarded.

Published source pointers may be text or safe HTTP(S) URLs. Existing URL and
credential safety checks apply. Ordinary links require explicit opening;
onion references remain inert/copyable under the existing component. GC does
not fetch or independently validate the published source. Unsafe matching
material is omitted with incomplete coverage, rather than saved with credentials.

## Identity, history, cache and account limits

Endpoint type `annotation`, namespace `graphsense`, contains the actual published
label. Result kind is `candidate_relationship`; observation kind is the existing
`verified_page_observation`, with `exact_in_document` meaning only the structured
`tags.address` match. It is not identity verification.

```text
wallet --publicly_labeled_as--> annotation(graphsense)
```

The logical fact includes queried wallet, provider, repository/path, label,
source pointer and predicate. Different packs or sources remain distinct, even
when their labels conflict. Identical material is deduplicated; there is no
winner selection. A material change under one fact creates an immutable new
observation and renewed review requirement. Old runs, original retrieval times
and promoted evidence remain unchanged.

The snapshot identifies the canonical wallet, selected tag, repository, path,
blob SHA, observed branch/ref, MIT license and exact-match method. Retrieval time
uses the existing observation timestamp. Mutable branch links may show newer
content later; the retained blob SHA identifies the fetched content.

TTL is **24 hours** for bounded positive responses. Existing empty-cache policy
caps successful zero-result reuse at **one hour**. Partial results are not cached.
Explicit Refresh bypasses cache. Both code mentions and GraphSense use
`github:1`: the same ten-attempt/minute ledger, 100/day and 3000/month reservation
guardrails and retry deadlines. There is no independent GraphSense quota.
Search/core resource headers are retained separately in typed execution metadata;
Retry-After and exhausted-resource reset times stop further fetching and block
the shared account. No uncontrolled retries occur.

## UI, graph and explicit promotion

Public tags are labeled **Third-party public annotation**, distinct from stored
GC Labels. Result, graph and Attribution detail show selected metadata, source
pointer, repository provenance and original retrieval time. Source confidence
is never relabeled as an Attribution assessment or ownership probability.

Graph `public_annotation` cards use a distinct tinted/dashed outline and an
outer-right lane. Stable IDs sort into rows, spaced 190 units vertically and
410 horizontally, starting 520 units right of every existing lane. Existing
code/Label/ENS/manual-source coordinates do not move. Arrows go wallet to tag.
The existing pagination, selection, keyboard inspection, fit, pan and zoom remain.
Graph metadata belongs to the chosen historical run; review/promotion counts
are explicitly current analytic status.

New material starts Unreviewed. Only explicit Relevant review allows ED-6
promotion. Claim, Supports/Contradicts/Context, directness, rationale and final
confirmation remain explicit. Origin is **`public_osint`**. The evidence snapshot
means GraphSense published this annotation; it does not say GC confirmed its truth.
Source material is never rewritten when upstream changes.

## Hard boundaries

Actor and `is_cluster_definer` are metadata only. They never create Entities,
Claims, wallet links, clusters, common ownership, recursive discovery or other
wallet ingestion. Sharing a label, actor or pack does not connect wallets.
Conflicting annotations remain inspectable independently.

No automatic GC Label, Case/report inclusion, assessment, risk points, watchlist,
monitoring change or alert. Public tags do not prove beneficial ownership, legal
ownership, natural-person identity or current wallet control. Existing explicit
Attribution/Case workflows and existing local Labels/risk behavior remain authoritative.
Production has no seeded, sample or canned GraphSense responses.

## Migration and verification

One revision **20260922_02**, parent **20260922_01**, adds only
`publicly_labeled_as` to the Discovery Result predicate CHECK. No tables/columns,
previous migration edits or seed data. Run creation checks the actual constraint
and shipped revision ancestry before any GitHub request. Stamping alone is
insufficient. ED-9A remains usable on its own valid prior schema. Downgrade refuses
while public annotations are retained. The configured user database was not
inspected or migrated; the operator must migrate it explicitly before use.

Tests use isolated temporary SQLite and mocked GitHub through the real executor,
service, API, review, graph and promotion code. They cover transport allowlists,
exact chain/address matching, conflicts, parsing attacks/bounds, account/cache
behavior, source metadata, side-effect boundaries, historical immutability,
clean/populated migration parity, retained ENS/manual predicates, FKs and downgrade.
`node tests/browser_discovery.cjs graphsense` verifies both chains, conflicting
packs, cluster-definer isolation, graph inspection, Context promotion, refresh,
empty/cache results and all nine workspaces without external requests.

## Final verification (2026-09-23)

Baseline: **1275 Python / 70 Node tests passed**, Alembic head `20260922_01`.
Final: **1352/1352 Python tests passed** (77 added), **72/72 Node tests passed**
(2 added). The full `python -m pytest tests/ -q` run completed in 460.14 seconds.
Existing deprecation warnings remain outside this task.

Consolidated browser modes passed: `production`, `github`, `handoff_github`,
`graph`, `ens`, `manual_source`, `graphsense`. This includes all nine workspaces,
BTC/ETH public tags, conflicting packs, no cross-wallet links from shared actors,
explicit Context promotion and unchanged historical evidence. Browser checks
also returned HTTP 200 for `/`, `/health`, `/docs`, `/openapi.json` and the new
frontend asset. Every browser server used temporary SQLite and blocked live
external transports; GraphSense responses came only from test fixtures.

Final source audit found no production fake/sample/canned GraphSense data or
test-fixture imports. Head is `20260922_02`. No user database was inspected or
migrated, no prior migration was edited, and no commit was created.
