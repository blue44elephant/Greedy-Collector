# RISK-2 pre-change audit: `deterministic-v2`

This records the implemented model before RISK-2 changes. The repository, not an
external wallet tracker, is the source for these mechanics.

## Why a listed wallet could score low

SANC-1 returned `sanctions_screening` alongside `risk`, but the fresh lookup passed
only transactions, labels on their endpoints, and stored transaction paths to
`ExplainableRiskEngine.evaluate`. It did not pass the queried wallet's OFAC
screening result. A wallet with few ordinary transactions therefore scored 0 or
another low number even when the separate screening panel showed a direct current
OFAC match. `direct_sanctioned` meant contact with a counterparty bearing a
mutable GC `Sanctioned` Label, not direct OFAC listing of the queried wallet.

## Numeric model and persisted history

`SCORING_MODEL = deterministic-v2`. A finding is retained once per rule ID, with
distinct observations in evidence. Direct labelled-counterparty exposure gets
40 (`Sanctioned`), 30 (`Scam`), or 25 (`Mixer`) points. Multiple classifications
of one counterparty use the strongest; the exposure category caps at 95.
Two-hop and three-hop labelled paths contribute at most 10 and 5 respectively;
indirect points are suppressed when direct risky-counterparty exposure is present.
The behavioral category caps at 10; context contributes zero. The total caps at
100. Thresholds are Low 0–30, Medium 31–70, High 71–100. Label confidence is
shown but is not multiplied into points. A manual/source Label is therefore an
assertion from its named source, not authoritative OFAC verification.

`RiskResult` stores score, level, findings, and calculation time; versioned v2
findings permit reconstruction of category totals. Older results without
versioned findings are returned unchanged. `Address` stores only the latest
score/level. Case wallet references and reports did not automatically pin a
versioned risk assessment.

## Rule inventory and chain/coverage caveats

| Rule | v2 trigger | Points/cap | Caveat |
|---|---|---:|---|
| `direct_sanctioned`, `direct_scam`, `direct_mixer` | Returned transaction endpoint has matching GC Label | 40/30/25; exposure 95 | Label provenance is evidence, not official listing; failed transfers and wallet-relative UTXO endpoints need care. |
| `indirect_exposure` | Stored path reaches a risky Label at 2 or 3 hops | 10/5; exposure 95 | Transaction adjacency is not ownership or guilt. |
| `peel_chain` | Four positive outgoing same-symbol amounts with three chronological decreases | 8; behavioral 10 | Symbol alone is not unique asset identity; sequence does not prove peeling. Applied without an explicit chain-family gate. |
| `rapid_pass_through` | At least five dated returned records within one hour | 5; behavioral 10 | A rapid sequence does not prove value passed through. |
| `dormant_reactivated` | Returned history has a gap of at least 180 days | 4; behavioral 10 | Bounded history does not establish true dormancy or recency. |
| `high_velocity`, `many_to_one`, `one_to_many`, `round_number_transfers`, `large_transfer`, `fresh_wallet_large_funds`, `repeated_counterparty`, `exchange_pattern`, `cross_chain_bridge` | Counts, amount shapes, or Exchange/Bridge Labels | 0; context | Descriptive only. Different asset units cannot be valued or compared from these rules. |

The engine accepted an `include_behavioral` flag from the chain adapter, but the
result did not expose a complete coverage assessment. Provider history is bounded
and may be partial, truncated, or provider-limited. Failed transactions were not
filtered before behavioral/count rules. Monero has observation-only public-chain
support, so a zero from absent public transactions would be misleading. Labels
have chain/`any` scope and source/confidence fields, but there is no archive flag
or delete API; CSV import can update a duplicate key's type and confidence.

No GraphSense/Discovery result or Attribution claim is itself an authoritative
sanctions finding. Technical clusters and fund-flow paths have no OFAC override.
