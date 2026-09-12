# Deterministic risk calibration audit

Baseline: 179 tests passed before changes. Audit performed before recalibration, using the original engine and fixed-clock synthetic tests only. No live wallet/provider queries were made. These controls are not statistically representative of blockchain activity.

## Original rule inventory

Classes: A direct attribution; B risky-entity exposure; C behavioral anomaly; D activity/context. The original engine has **no A rule**. Its `direct_*` names mean direct transaction contact with a labelled counterparty, not attribution of the queried wallet to that entity. A label on the queried wallet alone does not trigger these rules. The existing service selects labels from transaction endpoints, so empty-history labels are not a complete attribution mechanism.

All contributions below are fixed per rule except indirect exposure's hop-based value. Every rule is capped at one retained finding per rule ID by `_deduplicate_findings`; the original global cap is 100. There are no category caps. Label confidence is displayed, not multiplied into the score.

| Rule ID / name | Class | Original trigger | Points / severity / confidence | Evidence | Overlap |
|---|---|---|---|---|---|
| direct_sanctioned / Direct sanctioned exposure | B | Transaction counterparty has Sanctioned label | 40 / high / label confidence, default .5 | hash, counterparty, complete label | Other risky labels on same counterparty; indirect paths |
| direct_scam / Direct scam exposure | B | Counterparty has Scam label | 30 / high / label confidence | hash, counterparty, label | Other risky labels; paths |
| direct_mixer / Direct mixer exposure | B | Counterparty has Mixer label | 25 / high / label confidence | hash, counterparty, label | Other risky labels; paths |
| cross_chain_bridge / Cross-chain bridge interaction | D | Counterparty has Bridge label | 5 / low / label confidence | hash, label | Common DeFi activity; other labels |
| exchange_pattern / Exchange deposit or withdrawal interaction | D | Counterparty has Exchange label | 5 / low / label confidence | hash, label | Consolidation, distribution, repeat counterparties |
| indirect_exposure / N-hop indirect exposure | B | Supplied path reaches risky terminal at 2 or 3 hops | 15 at 2 hops; 10 at 3 / medium / path confidence, default .5 | Complete supplied path | Direct contact, multiple terminal labels/paths |
| high_velocity / High transaction velocity | D | At least 20 returned records, **no time denominator** | 10 / medium / .75 | Returned count | Both fan rules, round amounts, repeats |
| many_to_one / Many-to-one consolidation | D | At least 5 incoming records and 5 unique senders | 8 / low / .7 | Sender count | Count, fan-out, exchange activity |
| one_to_many / One-to-many fan-out | D | At least 5 outgoing records and 5 unique recipients | 8 / low / .7 | Recipient count | Count, fan-in, exchange activity |
| round_number_transfers / Repeated round-number transfers | D | At least 3 positive integral amounts | 5 / low / .65 | First 10 matching hashes | Large amounts, busy wallets |
| large_transfer / Large native-token transfer | D | Any `value_native >= 100`, including ERC-20 token amounts | 10 / medium / .6 | First 10 hashes; threshold | Round amounts, short history; asset units incomparable |
| fresh_wallet_large_funds / Fresh wallet receives large funds | D | Large-amount rule and at most 3 returned records; **no incoming or wallet-age requirement** | 12 / medium / .6 | Returned count; threshold | Entirely nested under large amount |
| peel_chain / Possible peel-chain pattern | C | At least 4 positive outgoing amounts; at least 3 descending adjacent comparisons in input order | 12 / medium / .55 | First 8 values | Provider ordering, mixed asset amounts, fan-out |
| rapid_pass_through / Rapid transaction sequence | C | At least 5 dated records with total span <= 1 hour | 15 / medium / .7 | First/last timestamp | Count, fan-in/out; no actual pass-through tracing |
| dormant_reactivated / Dormant wallet recently active | C | Dated span >=180 days, largest adjacent gap >=180 days, latest <=7 days before wall clock | 12 / medium / .8 | Largest gap in days | Bounded-history gaps; output changes as clock advances |
| repeated_counterparty / Repeated counterparty pattern | D | One nonempty counterparty occurs >=5 times | 5 / low / .65 | Counterparty and count | Count, treasury/exchange activity |

## Proven clustering mechanism

Original score = min(100, sum(max contribution for each distinct rule ID)). Low 0–30, Medium 31–70, High 71–100. No unconditional points, minimum score, normalization, transaction-value totals, or separate high-counterparty rule exist. Count >=20 gives the same 10 points for 20 or 778 records.

The 778-record test produces exactly **10+8+8+5+10+12+5 = 58**: count, fan-in, fan-out, round amounts, large amount, peel heuristic, repeats. A dense one-hour fan-in/out fixture produces **10+8+8+5+15 = 46**. Other unlabeled combinations can reach 73 (add rapid sequence to the 58 combination, if all relevant conditions hold). Thus YES, ordinary unlabeled activity can mechanically reach Medium, even High, without known-risk evidence. The reported real 58 cannot be attributed to this exact combination without its actual findings; the audit proves a mechanism, not that wallet's diagnosis.

Repeated risky-counterparty transactions do NOT themselves stack label points: deduplication keeps one record per rule ID and discards other evidence. Repeated activity can still add count and repeat points. Different risky label types DO stack, even for the same counterparty. Indirect paths retain only the highest-weight path (2-hop wins), but their points additionally stack with direct exposure. Exchange and Bridge contribute 5 each despite being ordinary context.

The `100` threshold is hardcoded, not configurable despite its explanation. It compares amounts in different assets without valuation. Short returned history does not establish a fresh wallet. The peel heuristic compares provider order and mixed units. Dormancy depends on wall-clock time, violating strict same-input determinism.

The `RiskRule` database model is not consulted by this engine; table parameters do not configure these thresholds/weights. Label confidence is descriptive and uncalibrated, not a score multiplier. Existing monitoring still consumes the same finding IDs; this task does not change its alert-trigger policy, including triggers from context findings.

## Chosen recalibration

Use transparent category budgets with deterministic priority allocation, not a new probability or activity score. General activity remains visible in zero-point findings. A second numeric activity score has no calibrated basis and is not introduced.

| Category | Budget | Reason |
|---|---:|---|
| Direct attribution | 0 currently | No supported attribution rule; do not invent evidence |
| Exposure | 95 | Preserve the three existing independent label maxima: 40+30+25. Same-counterparty classifications use only the strongest type; each type still counts once. This is a ceiling, not a baseline. |
| Behavioral | 10 | Reduce peel/rapid/gap weights to 8/5/4; cap their correlated stack at the size of one former weak count contribution. Behavior alone stays well below Medium. |
| Context | 0 | Count, fan-in/out, round/large amounts, short returned history, repeats, Exchange/Bridge describe activity, not evidence of wrongdoing |

Indirect exposure is 10 at 2 hops, 5 at 3, zero outside 2–3. Only the strongest indirect path contributes. It contributes no extra points when direct risky-counterparty exposure exists. Stored graph traversal is unchanged: bounded, undirected endpoint proximity, not a verified fund-flow or ownership path. Existing path-label chain filtering limitations remain outside this calibration; provenance must be reviewed.

Preserve direct contact weights: Sanctioned 40, Scam 30, Mixer 25. Mixed independent contacts can still reach High; a single Scam/Mixer finding retains its existing 30/25 and coarse Low level, and remains visibly high-severity evidence requiring review. No confidence calibration, guilt probability, ownership inference, or sanction determination is claimed. User-created labels are assertions from their named source, not automatically verified attribution.

For deterministic allocation, eligible exposure points are assigned first, then behavioral findings ordered by descending raw points and rule ID up to the behavioral and overall budgets. Points actually applied to findings sum exactly to the displayed score. The original Low/Medium/High thresholds remain unchanged; activity weights are corrected instead of disguising them through wider bands.

Peel comparisons use chronological, same-chain/token-symbol positive outgoing amounts with timestamps. This remains weak: token symbols are not globally unique identities, and no actual peel-chain tracing is inferred. Gap detection describes the largest observed gap without reference to the current clock or claiming true dormancy/recency. Other context thresholds remain observations with corrected wording.

Each finding retains evidence plus model version, category, raw points, applied points, and adjustment explanation. Multiple label/path observations are retained under evidence rather than discarded. Results expose category raw/applied totals and caps. Stored results are not silently recalculated; summaries are reconstructed only from versioned saved findings. Older or empty stored results without versioned findings do not get invented category totals. A fresh lookup uses the new scoring policy.

## Reproducible controls

Fixtures reside only in `tests/risk_controls.py`; the frozen original score/rule contributions are test data. Before/after tables below are generated from those controls. This is a demonstration of mechanics, not a population distribution or empirical validation of these policy weights.

<!-- generated control matrix -->

| Synthetic control | Original rules: points | Before | Revised rules: applied points | After |
|---|---|---|---|---|
| Empty/new | None | 0 / Low | None | 0 / Low |
| Normal low volume | None | 0 / Low | None | 0 / Low |
| Busy 778 records | high_velocity: 10, many_to_one: 8, one_to_many: 8, round_number_transfers: 5, large_transfer: 10, peel_chain: 12, repeated_counterparty: 5 | 58 / Medium | high_velocity: 0, large_transfer: 0, many_to_one: 0, one_to_many: 0, repeated_counterparty: 0, round_number_transfers: 0 | 0 / Low |
| Many counterparties | high_velocity: 10, many_to_one: 8, one_to_many: 8 | 26 / Low | high_velocity: 0, many_to_one: 0, one_to_many: 0 | 0 / Low |
| Exchange-like fan-in/out | high_velocity: 10, many_to_one: 8, one_to_many: 8, round_number_transfers: 5, rapid_pass_through: 15 | 46 / Medium | high_velocity: 0, many_to_one: 0, one_to_many: 0, rapid_pass_through: 5, round_number_transfers: 0 | 5 / Low |
| Dormant/reactivated | dormant_reactivated: 12 | 12 / Low | dormant_reactivated: 4 | 4 / Low |
| Single risky counterparty | direct_scam: 30 | 30 / Low | direct_scam: 30 | 30 / Low |
| Repeated risky exposure | direct_scam: 30, high_velocity: 10, repeated_counterparty: 5 | 45 / Medium | direct_scam: 30, high_velocity: 0, repeated_counterparty: 0 | 30 / Low |
| Known Mixer counterparty | direct_mixer: 25 | 25 / Low | direct_mixer: 25 | 25 / Low |
| Known Scam counterparty | direct_scam: 30 | 30 / Low | direct_scam: 30 | 30 / Low |
| Known Sanctioned counterparty | direct_sanctioned: 40 | 40 / Medium | direct_sanctioned: 40 | 40 / Medium |
| Exchange counterparty | exchange_pattern: 5 | 5 / Low | exchange_pattern: 0 | 0 / Low |
| Bridge counterparty | cross_chain_bridge: 5 | 5 / Low | cross_chain_bridge: 0 | 0 / Low |
| Two-hop exposure | indirect_exposure: 15 | 15 / Low | indirect_exposure: 10 | 10 / Low |
| Three-hop exposure | indirect_exposure: 10 | 10 / Low | indirect_exposure: 5 | 5 / Low |
| Mixed strong exposure | direct_sanctioned: 40, direct_scam: 30, direct_mixer: 25 | 95 / High | direct_mixer: 25, direct_sanctioned: 40, direct_scam: 30 | 95 / High |

Synthetic distribution (16 controls): before {'Low': 11, 'Medium': 4, 'High': 1}; after {'Low': 14, 'Medium': 1, 'High': 1}.
These scenarios are not a statistically representative blockchain sample.
