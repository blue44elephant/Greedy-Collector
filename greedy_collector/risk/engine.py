from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json

from fastapi.encoders import jsonable_encoder

from ..chains import get_chain_adapter
from ..collection import transfer_eligible
from ..schemas import NormalizedTransaction
from ..transaction_identity import build_event_key


SCORING_MODEL = "deterministic-v3"
LEGACY_CATEGORY_CAPS = {"direct_evidence": 0, "exposure": 95, "behavioral": 10, "context": 0}
CATEGORY_CAPS = {"direct_evidence": 40, "exposure": 95, "behavioral": 10, "context": 0}
BEHAVIOR_RULES = {"peel_chain", "rapid_pass_through", "dormant_reactivated"}
DIRECT_WEIGHTS = {"direct_sanctioned": 40, "direct_scam": 30, "direct_mixer": 25}
SELF_LABEL_WEIGHTS = {"Sanctioned": 35, "Scam": 30, "Mixer": 25}
OFAC_DIRECT_FLOOR = 95
PEEL_CHAINS = frozenset({"ethereum", "base", "arbitrum", "bsc", "polygon"})


def contribution_summary(findings: list[dict], *, model: str = SCORING_MODEL) -> dict:
    """Summarize already-applied versioned findings, including persisted results."""
    caps = LEGACY_CATEGORY_CAPS if model == "deterministic-v2" else CATEGORY_CAPS
    return {category: {
        "raw": sum(item["raw_score_contribution"] for item in findings if item["category"] == category),
        "applied": sum(item["score_contribution"] for item in findings if item["category"] == category),
        "cap": cap,
    } for category, cap in caps.items()}


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


RISK_TYPES = {"Sanctioned", "Mixer", "Scam"}


def _decimal(value: str | None) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except InvalidOperation:
        return Decimal("0")


class ExplainableRiskEngine:
    """Deterministic, reviewable indicators. It does not make guilt determinations."""

    def evaluate(
        self,
        address: str,
        transactions: list[NormalizedTransaction],
        labels: list[dict],
        exposure_paths: list[dict] | None = None,
        include_behavioral: bool = True,
        *,
        chain: str | None = None,
        sanctions: dict | None = None,
        coverage: dict | None = None,
    ) -> dict:
        chain = chain or (transactions[0].chain if transactions else None)
        adapter = get_chain_adapter(chain) if chain else None
        key = adapter.address_key if adapter else lambda value: value
        # Duplicate normalized events and failed executions are not evidence of
        # repeated successful transfers or transaction-derived exposure.
        unique = {}
        for tx in transactions:
            if transfer_eligible(tx):
                unique.setdefault((tx.chain, tx.tx_hash, build_event_key(tx)), tx)
        transactions = list(unique.values())
        # Canonical ordering makes bounded evidence samples independent of input order.
        transactions = sorted(transactions, key=lambda tx: (
            _utc(tx.timestamp).isoformat() if tx.timestamp else "", tx.chain,
            tx.tx_hash, tx.from_address, tx.to_address, tx.token_symbol, tx.value_native, tx.direction))
        findings: list[dict] = []
        label_map: dict[str, list[dict]] = {}
        for label in labels:
            if label.get("active", True) is False or label.get("chain") not in (None, "any", chain):
                continue
            label_map.setdefault(key(label["address"]), []).append(label)

        focal = label_map.get(key(address), [])
        for kind, weight in SELF_LABEL_WEIGHTS.items():
            matches = [item for item in focal if item.get("type") == kind]
            if matches:
                findings.append(self._finding(
                    f"wallet_{kind.lower()}_label", f"GC Label: {kind} on queried wallet",
                    "high", max(float(item.get("confidence", 0.5)) for item in matches),
                    weight, f"The queried wallet has a GC {kind} Label. This is a source/analyst annotation, not an authoritative sanctions listing.",
                    {"labels": sorted(matches, key=lambda item: (str(item.get("source")), str(item.get("id"))))},
                ))

        for tx in transactions:
            counterparty = (
                tx.to_address if tx.direction == "outgoing" else tx.from_address
            )
            counterparty = key(counterparty) if counterparty else ""
            if not counterparty or counterparty == key(address):
                continue
            for label in label_map.get(counterparty, []):
                if label.get("type") in RISK_TYPES:
                    weight = {"Sanctioned": 40, "Mixer": 25, "Scam": 30}[label["type"]]
                    findings.append(
                        self._finding(
                            f"direct_{label['type'].lower()}",
                            f"Direct {label['type'].lower()} exposure",
                            "high",
                            float(label.get("confidence", 0.5)),
                            weight,
                            (
                                f"Transaction {tx.tx_hash} directly references an address "
                                f"labeled {label['type']} by {label['source']}."
                            ),
                            {
                                "tx_hash": tx.tx_hash,
                                "counterparty": counterparty,
                                "label": label,
                            },
                        )
                    )
                elif label.get("type") == "Bridge":
                    findings.append(
                        self._finding(
                            "cross_chain_bridge",
                            "Cross-chain bridge interaction",
                            "low",
                            float(label.get("confidence", 0.5)),
                            0,
                            (
                                f"Transaction {tx.tx_hash} references an address labeled "
                                f"as a bridge by {label['source']}."
                            ),
                            {"tx_hash": tx.tx_hash, "label": label},
                        )
                    )
                elif label.get("type") == "Exchange":
                    findings.append(
                        self._finding(
                            "exchange_pattern",
                            "Exchange deposit or withdrawal interaction",
                            "low",
                            float(label.get("confidence", 0.5)),
                            0,
                            (
                                f"Transaction {tx.tx_hash} references an address labeled "
                                f"as an exchange by {label['source']}."
                            ),
                            {"tx_hash": tx.tx_hash, "label": label},
                        )
                    )

        for path in exposure_paths or []:
            hops = int(path.get("hops", 0))
            if 1 < hops <= 3 and path.get("terminal_type") in RISK_TYPES:
                weight = 10 if hops == 2 else 5
                findings.append(
                    self._finding(
                        "indirect_exposure",
                        f"{hops}-hop indirect exposure",
                        "medium",
                        float(path.get("confidence", 0.5)),
                        weight,
                        (
                            f"A public transaction path of {hops} hops reaches a "
                            f"{path.get('terminal_type')} label. Intermediaries may be unrelated."
                        ),
                        path,
                    )
                )

        if include_behavioral:
            self._behavioral_findings(address, transactions, findings, chain)
        findings = self._deduplicate_findings(findings)
        self._apply_budgets(findings)
        base_score = sum(item["score_contribution"] for item in findings)
        direct_ofac = bool(sanctions and sanctions.get("listing_state") == "CURRENTLY_LISTED"
                           and sanctions.get("match_type") == "DIRECT_CHAIN_MATCH")
        score = max(base_score, OFAC_DIRECT_FLOOR) if direct_ofac else base_score
        level = "Critical" if direct_ofac else "Low" if score <= 30 else "Medium" if score <= 70 else "High"
        if chain == "monero" and not findings and not direct_ofac:
            score, level = None, "Unassessed"
        status = [] if sanctions is None else [{
            "source": "OFAC SDN", "listing_state": sanctions.get("listing_state"),
            "match_type": sanctions.get("match_type"), "stale": bool(sanctions.get("stale")),
            "snapshot_id": (sanctions.get("snapshot") or {}).get("id"),
            "snapshot_sha256": (sanctions.get("snapshot") or {}).get("sha256"),
            "snapshot_retrieved_at": (sanctions.get("snapshot") or {}).get("retrieved_at"),
            "associations": [{"source_entity_id": (item.get("entity") or {}).get("source_entity_id"),
                              "name": (item.get("entity") or {}).get("name")}
                             for item in sanctions.get("associations") or []],
        }]
        overrides = ([{"rule_id": "authoritative_sanctions_current", "score_floor": OFAC_DIRECT_FLOOR,
                       "reason": "Overall score elevated by current direct authoritative sanctions match."}]
                     if direct_ofac else [])
        coverage_status = (coverage or {}).get("status", "UNKNOWN")
        limitations = []
        if coverage_status in {"PARTIAL", "TRUNCATED", "PROVIDER_LIMITED", "CONTINUITY_LOST"}:
            limitations.append(f"Collection coverage is {coverage_status}; absence of observed behavior is not evidence of absence.")
        if not include_behavioral:
            limitations.append("Public-chain behavioral assessment is unavailable for this chain.")
        elif not transactions:
            limitations.append("No eligible transfers were returned in this bounded lookup; this does not establish that the wallet is safe or inactive.")
        if sanctions is not None:
            state = sanctions.get("listing_state")
            if state in {"REGISTRY_NOT_SYNCED", "REGISTRY_STALE", "SCREENING_UNRESOLVED"} or sanctions.get("stale"):
                limitations.append("OFAC screening is unavailable or stale; no-match cannot be concluded from this state.")
            elif state == "HISTORICALLY_LISTED":
                limitations.append("This identifier appeared in an earlier local OFAC snapshot, not the current one.")
            elif sanctions.get("match_type") in {"EXACT_TEXT_MATCH_CHAIN_UNRESOLVED", "TEXT_MATCH_OTHER_CHAIN"}:
                limitations.append("An exact source text match lacks a direct match for this wallet's chain.")
            elif sanctions.get("match_type") == "NO_MATCH":
                limitations.append("No exact match in the synchronized OFAC dataset does not establish safety or absence from other lists.")
        return jsonable_encoder({
            "scoring_model": SCORING_MODEL,
            "model_version": SCORING_MODEL,
            "category_contributions": contribution_summary(findings),
            "score": score,
            "level": level,
            "overall_score": score,
            "overall_tier": "MODERATE" if level == "Medium" else level.upper(),
            "behavioral_exposure_score": base_score if chain != "monero" else None,
            "behavioral_score": contribution_summary(findings)["behavioral"]["applied"] if include_behavioral else None,
            "components": [{"rule_id": item["rule_id"], "category": item["category"],
                            "raw": item["raw_score_contribution"], "applied": item["score_contribution"],
                            "cap": CATEGORY_CAPS[item["category"]]} for item in findings],
            "authoritative_status": status,
            "overrides": overrides,
            "data_coverage": {"status": coverage_status, "records_returned": (coverage or {}).get("records_returned", len(transactions)),
                              "behavioral_supported": include_behavioral},
            "limitations": limitations,
            "findings": findings,
            "disclaimer": (
                "GC risk score is analytical prioritization/compliance risk, not a probability, confidence percentage, "
                "and does not prove criminal activity or real-world ownership. General activity is not inherently suspicious; "
                "labels and bounded-history indicators require source and context review."
            ),
        })

    def _behavioral_findings(
        self,
        address: str,
        transactions: list[NormalizedTransaction],
        findings: list[dict],
        chain: str | None,
    ) -> None:
        dated = sorted([tx for tx in transactions if tx.timestamp], key=lambda tx: _utc(tx.timestamp))
        outgoing = [tx for tx in transactions if tx.direction == "outgoing"]
        incoming = [tx for tx in transactions if tx.direction == "incoming"]
        counterparties = [
            tx.to_address if tx.direction == "outgoing" else tx.from_address
            for tx in transactions
        ]

        if len(transactions) >= 20:
            findings.append(
                self._finding(
                    "high_velocity",
                    "Returned transaction count",
                    "low",
                    0.75,
                    0,
                    f"{len(transactions)} transactions were observed in the fetched window.",
                    {"transaction_count": len(transactions)},
                )
            )

        if len(incoming) >= 5 and len({tx.from_address for tx in incoming}) >= 5:
            findings.append(
                self._finding(
                    "many_to_one",
                    "Many-to-one consolidation",
                    "low",
                    0.7,
                    0,
                    "Funds arrived from at least five distinct public addresses.",
                    {"distinct_senders": len({tx.from_address for tx in incoming})},
                )
            )

        if len(outgoing) >= 5 and len({tx.to_address for tx in outgoing}) >= 5:
            findings.append(
                self._finding(
                    "one_to_many",
                    "One-to-many fan-out",
                    "low",
                    0.7,
                    0,
                    "Funds were sent to at least five distinct public addresses.",
                    {"distinct_recipients": len({tx.to_address for tx in outgoing})},
                )
            )

        round_transfers = [
            tx for tx in transactions if _decimal(tx.value_native) > 0
            and _decimal(tx.value_native) == _decimal(tx.value_native).to_integral()
        ]
        if len(round_transfers) >= 3:
            findings.append(
                self._finding(
                    "round_number_transfers",
                    "Repeated round-number transfers",
                    "low",
                    0.65,
                    0,
                    f"{len(round_transfers)} transfers used whole asset amounts; units differ across assets.",
                    {"tx_hashes": [tx.tx_hash for tx in round_transfers[:10]]},
                )
            )

        large = [tx for tx in transactions if _decimal(tx.value_native) >= Decimal("100")]
        if large:
            findings.append(
                self._finding(
                    "large_transfer",
                    "Large asset-unit amount",
                    "low",
                    0.6,
                    0,
                    "At least one returned asset amount is at least 100 units. This fixed context threshold is not a valuation and units differ across assets.",
                    {"tx_hashes": [tx.tx_hash for tx in large[:10]], "threshold": "100"},
                )
            )
            if len(transactions) <= 3:
                findings.append(
                    self._finding(
                        "fresh_wallet_large_funds",
                        "Short returned history with a large asset amount",
                        "low",
                        0.6,
                        0,
                        "At most three records were returned, including an amount of at least 100 asset units. Bounded history does not establish wallet age or receipt of funds.",
                        {
                            "fetched_transaction_count": len(transactions),
                            "threshold": "100",
                        },
                    )
                )

        # Values from different assets are not comparable. This remains a weak heuristic,
        # not actual peel-chain tracing; token symbols themselves may not be unique.
        by_asset = {}
        for tx in outgoing:
            if tx.timestamp and _decimal(tx.value_native) > 0:
                by_asset.setdefault((tx.chain, tx.token_symbol), []).append(tx)
        for (asset_chain, token), rows in sorted(by_asset.items()):
            if asset_chain not in PEEL_CHAINS:
                continue
            rows.sort(key=lambda tx: (_utc(tx.timestamp), tx.tx_hash, tx.value_native))
            values = [_decimal(tx.value_native) for tx in rows]
            descending_steps = sum(right < left for left, right in zip(values, values[1:]))
            if len(values) >= 4 and descending_steps >= 3:
                findings.append(self._finding(
                    "peel_chain", "Decreasing outgoing asset amounts", "medium", 0.55, 8,
                    "Same-symbol outgoing amounts have at least three chronological decreases. This weak pattern does not establish a peel chain or ownership.",
                    {"chain": asset_chain, "token_symbol": token, "sample_values": [str(value) for value in values[:8]]},
                ))

        if len(dated) >= 2:
            span = _utc(dated[-1].timestamp) - _utc(dated[0].timestamp)
            if span <= timedelta(hours=1) and len(dated) >= 5:
                findings.append(
                    self._finding(
                        "rapid_pass_through",
                        "Rapid transaction sequence",
                        "medium",
                        0.7,
                        5,
                        f"{len(dated)} transactions occurred within one hour.",
                        {
                            "first": dated[0].timestamp.isoformat(),
                            "last": dated[-1].timestamp.isoformat(),
                        },
                    )
                )
            if span >= timedelta(days=180):
                gaps = [
                    _utc(dated[index].timestamp) - _utc(dated[index - 1].timestamp)
                    for index in range(1, len(dated))
                ]
                if gaps and max(gaps) >= timedelta(days=180):
                    findings.append(
                        self._finding(
                            "dormant_reactivated",
                            "Long gap in returned activity",
                            "medium",
                            0.8,
                            4,
                            "Returned records contain a gap of at least 180 days. This does not establish true wallet dormancy or current recency.",
                            {"largest_gap_days": max(gaps).days},
                        )
                    )

        adapter = get_chain_adapter(chain) if chain else None
        repeated = Counter((adapter.address_key(cp) if adapter else cp) for cp in counterparties if cp)
        if repeated and repeated.most_common(1)[0][1] >= 5:
            cp, count = sorted(repeated.items(), key=lambda item: (-item[1], item[0]))[0]
            findings.append(
                self._finding(
                    "repeated_counterparty",
                    "Repeated counterparty pattern",
                    "low",
                    0.65,
                    0,
                    f"The same counterparty appears in {count} transactions.",
                    {"counterparty": cp, "count": count},
                )
            )

    @staticmethod
    def _finding(
        rule_id: str,
        rule_name: str,
        severity: str,
        confidence: float,
        score_contribution: int,
        explanation: str,
        evidence: dict,
    ) -> dict:
        return {
            "rule_id": rule_id,
            "rule_name": rule_name,
            "severity": severity,
            "confidence": round(confidence, 2),
            "score_contribution": score_contribution,
            "explanation": explanation,
            "evidence": evidence,
        }

    @staticmethod
    def _deduplicate_findings(findings: list[dict]) -> list[dict]:
        # Keep one scored rule while retaining all distinct supporting observations.
        grouped = {}
        for finding in jsonable_encoder(findings):
            grouped.setdefault(finding["rule_id"], []).append(finding)
        result = []
        for rule_id, rows in sorted(grouped.items()):
            rows.sort(key=lambda row: (-row["score_contribution"], json.dumps(row, sort_keys=True)))
            selected = rows[0]
            observations = {json.dumps(row["evidence"], sort_keys=True): row["evidence"] for row in rows}
            if len(observations) > 1:
                selected["evidence"] = {**selected["evidence"], "observations": [observations[key] for key in sorted(observations)]}
            result.append(selected)
        return result

    @staticmethod
    def _apply_budgets(findings: list[dict]) -> None:
        # A counterparty with multiple risk classifications contributes its strongest
        # classification, not several descriptions of the same contact.
        best_by_counterparty = {}
        for item in findings:
            if item["rule_id"] not in DIRECT_WEIGHTS:
                continue
            evidence = item["evidence"]
            for observation in evidence.get("observations", [evidence]):
                cp = observation["counterparty"]
                rule = item["rule_id"]
                previous = best_by_counterparty.get(cp)
                if previous is None or DIRECT_WEIGHTS[rule] > DIRECT_WEIGHTS[previous]:
                    best_by_counterparty[cp] = rule
        eligible_direct = set(best_by_counterparty.values())
        used = dict.fromkeys(CATEGORY_CAPS, 0)
        for item in sorted(findings, key=lambda row: (
            0 if row["rule_id"] in DIRECT_WEIGHTS else 1 if row["rule_id"] == "indirect_exposure" else 2,
            -row["score_contribution"], row["rule_id"])):
            rule = item["rule_id"]
            category = "direct_evidence" if rule.startswith("wallet_") and rule.endswith("_label") else "exposure" if rule in DIRECT_WEIGHTS or rule == "indirect_exposure" else "behavioral" if rule in BEHAVIOR_RULES else "context"
            raw = item["score_contribution"]
            eligible = raw
            adjustment = "Full rule contribution applied."
            if category == "context":
                adjustment = "Activity/context only; no risk points."
            elif rule in DIRECT_WEIGHTS and rule not in eligible_direct:
                eligible = 0
                adjustment = "A stronger risk classification covers the same counterparty exposure."
            elif rule == "indirect_exposure" and eligible_direct:
                eligible = 0
                adjustment = "Indirect proximity adds no points when direct risky-counterparty exposure is present."
            applied = min(eligible, CATEGORY_CAPS[category] - used[category], 100 - sum(used.values()))
            if applied < eligible:
                adjustment = "Contribution limited by the category or overall score cap."
            used[category] += applied
            item.update(scoring_model=SCORING_MODEL, category=category, raw_score_contribution=raw,
                        score_contribution=applied, score_adjustment=adjustment)
