# Discovery diagnostics (UX-1)

Each transform card shows type, implementation, configured/executable state,
supported chains, network behavior, cost, bounds and cache window where relevant.
What does this do? explains the source and evidential limits. Incompatible cards
remain visible with a chain-specific explanation and disabled selection.

- Local Labels: reads current stored annotations, no network.
- Manual Exact Web: creates an outbound exact-address search link; GC does not search.
- Manual Source Observation: explicit analyst capture; GC does not fetch the source.
- GitHub code mentions: bounded automated GitHub API search.
- GraphSense Public Tags: bounded GitHub-backed public TagPacks; third-party annotations.
- ENS Primary Name: Ethereum RPC / Universal Resolver only, forward-verified naming.

Missing configuration shows environment variable names, never values. Set the
named variable server-side in environment/.env and restart GC. ENS also needs the
existing Node 24+ locked local normalizer; its unavailability is distinguished
from a missing Alchemy key. Configured does not establish reachability, key
validity or entitlement. There is no browser secret editor.

Unavailable same-chain transforms may be selected for a diagnostic preflight.
Select at most three pivots per run. Plan separates eligible execution/manual actions from unavailable selections;
planning consumes no provider quota and creates no run. Run discovery requires
at least one eligible selection. The existing executor skips unavailable sources
and records their reasons; manual pivots only generate links. No provider behavior
has changed. Changed configuration/budget or expired plans require replanning.

Run summaries distinguish requested transforms, actual execution/attempts,
unavailable transforms, returned records, partial/failed/incomplete sources,
cache hits, manual links and explicit refresh requests. Cache hits and generated
manual links are not counted as new remote executions. Source rows retain exact
request accounting and original retrieval times. Explicit refresh means cache
bypass was requested, not that a failed source successfully retrieved data.

Zero-result explanations appear only for succeeded/cached sources. Unavailable,
failed or incomplete retrieval is never evidence that no identity exists, that
a wallet is clean, or that ownership has been established. Bounded successful
empty results also do not imply exhaustive coverage.

## Deferred: OSINT-2 - Broad Wallet-to-Identity Public Discovery

Goal: wallet -> broad lawful/public-source search -> candidate aliases/entities/
infrastructure -> analyst review -> Attribution evidence. No implementation yet:
no broad search engine, crawler, social enumeration, recursive transforms, Tor,
darknet collection or automatic wallet-to-identity inference is added by UX-1.
