# Narcotics Network Intelligence (NARC-1)

NARC-1 connects selected Cases, chain-scoped wallets, reviewed public-source aliases/domains,
marketplaces, explicit Attribution entities, technical clusters, stored Fund Flow steps,
substances/precursors, consignments, logistics and analyst-entered geography. It is a local
cross-domain linkage workspace built on Cases, not another Case system or collection provider.

Open **Cases → Narcotics intelligence**, or the **Narcotics intelligence** workspace.
Select an existing Case. Save an optional profile, add substances and logistics objects,
generate an MO fingerprint, and explicitly select **Find related Cases**. Inspect **Why linked?**,
review individual links, select up to 20 Cases for a Nexus Graph, and run Network Priority.
Pin each useful analysis to the selected Case; generate reports in the existing Cases workspace.
There is no automatic crawling or analysis on keystrokes.

## Structured facts and provenance

Profiles are optional and partially populated. Blank/unknown stays unknown. Broad courier/platform
vocabularies offer `other` plus notes. Names, categories, quantities (decimal strings), units,
precursor type and notes remain exactly analyst supplied. No slang-to-chemical conversion occurs.
Location is explicitly entered country/region/city; it is never inferred residence or live tracking.
Logistics objects preserve lawful references, service, dispatch/interception timestamps,
packaging/concealment, weight/unit and optional wallet/Case Entity associations.

Every fact has provenance: analyst entry, Case note, pinned Public Source Capture, Discovery,
Attribution, sanctions or blockchain reference. Except for analyst entry, provide a compatible
source ID from **this Case**. The source snapshot is retained with the fact. A source reference
does not verify the assertion. Advanced profile JSON supports multiple objects and individual
provenance. Each save appends a profile revision and Case timeline event; older facts remain intact.
Archived Cases are readable and selectable as historical inputs; restore them before new profile
writes, reviews or pins. Cases and source histories cannot be deleted through this workspace.

## Versioned MO fingerprints

`narc1-mo-1` stores selected attributes, normalization, per-attribute provenance, weights,
source Case revision/fingerprint, profile ID and calculation time. Repeating identical input
produces the same content fingerprint, with a separate immutable run ID. Later Case/profile edits
produce a new source fingerprint. Historical comparisons use their stored fingerprints.

Default weights: wallet 40; exact alias, domain and marketplace account 20 each; marketplace 4;
platform, payment, logistics, concealment, packaging, delivery/drop, sender/recipient pattern,
MO tag and substance/precursor 2 each; origin/destination country/region/city 1 each.
The fingerprint/related endpoint accepts explicit integer overrides from 1–100 for these fields.
Weights are recorded, never hidden. When strong identifiers are comparable, all weaker fields
together are capped at half the smallest comparable strong weight. Thus numerous generic
matches cannot outweigh an isolated strong contradiction. Disjoint wallet sets are an attribute
mismatch, not evidence of a different offender; partial set overlap is shown explicitly.

Similarity is `100 × matched effective weight / comparable effective weight`. Unknown or absent
on either side contributes neither positive nor negative weight. Zero comparable fields gives
an unknown score, not zero or 100. Exact source strings are `EXACT MATCH`; normalized contextual
strings are `NORMALIZED MATCH`; disjoint comparable sets are `NO MATCH`; missing fields are
`UNKNOWN`. No fuzzy text match is implemented in this increment (`SIMILAR` is not inferred from
alias resemblance). A score is a weighted match fraction, never same-offender probability.
All contributions, denominator, configured/effective weights and matched values are exposed.
Activity periods yield UNKNOWN/BEFORE/AFTER/OVERLAPPING, without causation.

## Candidate links and reviews

Typed links explain exact chain-scoped wallet/alias reuse, domain/marketplace account reuse,
same pinned BTC/LTC cluster version/member, explicit Entity overlap, stored Flow counterparties,
and contextual origin/destination, concealment, logistics, substances and MO matches.
Wallet keys are `(chain, canonical address)`; identical EVM text on different chains stays distinct.
Alias/account reuse is exact entered text, not identity. Domains/context use Unicode normalization,
case folding and safe whitespace normalization; organization name resemblance is not Entity overlap.
Exact cluster versions are strong technical links, never ownership. Supported, current-at-pin
Attribution assessments can be moderate; rejected, weak or review-required claims remain context,
with relationships and supporting/contradicting/withdrawn link state visible. Reviewed Relevant
Discovery candidates may be moderate; unreviewed candidates remain context and cannot contribute
as verified MO fields. Irrelevant candidates are not newly promoted into candidate links.

Strength is STRONG/MODERATE/WEAK/CONTEXT_ONLY. Every candidate starts UNREVIEWED. Reviews append
RELEVANT/IRRELEVANT/UNREVIEWED, rationale, sequence and time without changing source evidence.
Irrelevant links and earlier reviews remain in history. Related-Cases searches are explicitly
bounded to 100 by default (maximum 200), with selected IDs or indexed current-profile strong
identifiers first and then stored Case ID order, and an explicit
truncation flag. They never automatically create identity/common-cartel/operator/person claims.

## Nexus Graph and Network Priority

Nexus is separate from blockchain and Discovery graphs. Select 1–20 Cases, optionally a comparison
run whose Cases are all selected. It uses typed Case, wallet, transaction, cluster, alias, marketplace,
domain, public profile, Entity, substance/precursor, consignment/logistics, location and source nodes.
Relationships retain Case IDs, source records, provenance, observation times, link strength/review.
Co-recorded alias/marketplace facts explicitly do not establish account control. Review state is
captured at graph creation; recomputing creates a new graph run.

Node layout uses multi-source BFS from Case nodes, hop bands, stable type/label/ID ordering, and
nonoverlapping fixed cards with wrapped columns. Parallel edges are offset, retaining every record.
Drag/pin/auto/reset/fit/zoom/pan use browser presentation state only; coordinates never enter
the analysis or evidence. Filters (type, Case, strength, review, observed time, geography/substance
text, crypto/logistics) affect the display only. Unfiltered saved records remain inspectable.
Runs have at most 300 nodes/1200 edges (defaults 250/800) and expose available counts and truncation.
They describe selected stored records, not complete blockchain or historic Case coverage.

`narc1-priority-brandes-1` calculates undirected structural degree, weighted degree, bounded Brandes
betweenness, Case recurrence, reviewed strong links, distinct source groups and observed time range.
Case reference insertion times are not treated as blockchain observation timestamps.
Public sources are conservatively grouped by hostname; repeated pages/manual assertions are not
new independent sources. Stored blockchain event references are grouped by event identity. This
count does not prove source independence or reliability. Priority is capped at 100: 20 per extra Case,
up to 20 for source groups (4 each), up to 20 for betweenness, up to 10 for reviewed strong links
(2 each). HIGH ≥60, MEDIUM ≥30, otherwise LOW. Complete metrics and reasons are visible.
The run stores selected Cases, exact graph fingerprint/version/bounds and calculation time.
It writes neither Risk nor Attribution. **Network Priority is not Risk, guilt/criminality or
leadership probability.** It never recommends arrest, raid, detention or interrogation.

## Pins, reporting, privacy and migration

Pin MO fingerprints, comparisons, reviewed links, Nexus and Priority runs to participating Cases.
Pins retain exact snapshots, versions, source IDs, review state, capture time and fingerprints.
Recomputation/review changes cannot change older pins. Reports capture the current profile at
generation and optional pinned analyses with denominator/explanations and limitations; already
generated JSON/HTML/Markdown/PDF bytes remain immutable. Untrusted analyst text is escaped/literal,
and existing secret/credential/unsafe URL redaction is reused.

Only local Case facts, lawful public sources, explicit Attribution and blockchain observations
are used. There are no private carrier, private KYC/phone/social, leaked credential, device tracking,
people-search or covert monitoring integrations. There are no sample/canned runtime results.

Migration `20261013_01_narcotics_network_intelligence` follows `20261012_02_case_history`.
NARC tables are migration-only and append-only, with SQLite update/delete/replace guards.
No automatic startup migration or seeded data is provided. This implementation's tests and browser
verification migrate only temporary databases; the configured user database is not inspected.

Local API namespace: `/api/greedy-collector/narcotics` (see `/docs` for request schemas).
