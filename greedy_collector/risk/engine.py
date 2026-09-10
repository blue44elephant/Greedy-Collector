from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from ..schemas import NormalizedTransaction


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
    ) -> dict:
        findings: list[dict] = []
        label_map: dict[str, list[dict]] = {}
        for label in labels:
            label_map.setdefault(label["address"].lower(), []).append(label)

        for tx in transactions:
            counterparty = (
                tx.to_address if tx.direction == "outgoing" else tx.from_address
            ).lower()
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
                            5,
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
                            5,
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
                weight = max(5, 25 - (hops * 5))
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

        self._behavioral_findings(address, transactions, findings)
        findings = self._deduplicate_findings(findings)
        score = min(100, sum(int(item["score_contribution"]) for item in findings))
        level = "Low" if score <= 30 else "Medium" if score <= 70 else "High"
        return {
            "score": score,
            "level": level,
            "findings": findings,
            "disclaimer": (
                "Risk scoring does not prove criminal "
                "activity or identify real-world ownership."
            ),
        }

    def _behavioral_findings(
        self,
        address: str,
        transactions: list[NormalizedTransaction],
        findings: list[dict],
    ) -> None:
        dated = sorted([tx for tx in transactions if tx.timestamp], key=lambda tx: tx.timestamp)
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
                    "High transaction velocity",
                    "medium",
                    0.75,
                    10,
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
                    8,
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
                    8,
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
                    5,
                    f"{len(round_transfers)} transfers used whole native-token amounts.",
                    {"tx_hashes": [tx.tx_hash for tx in round_transfers[:10]]},
                )
            )

        large = [tx for tx in transactions if _decimal(tx.value_native) >= Decimal("100")]
        if large:
            findings.append(
                self._finding(
                    "large_transfer",
                    "Large native-token transfer",
                    "medium",
                    0.6,
                    10,
                    "At least one transfer exceeded the configurable 100 native-token threshold.",
                    {"tx_hashes": [tx.tx_hash for tx in large[:10]], "threshold": "100"},
                )
            )
            if len(transactions) <= 3:
                findings.append(
                    self._finding(
                        "fresh_wallet_large_funds",
                        "Fresh wallet receives large funds",
                        "medium",
                        0.6,
                        12,
                        "The fetched history is short and includes a transfer over the configured threshold.",
                        {
                            "fetched_transaction_count": len(transactions),
                            "threshold": "100",
                        },
                    )
                )

        decreasing = [
            _decimal(tx.value_native)
            for tx in outgoing
            if _decimal(tx.value_native) > 0
        ]
        if len(decreasing) >= 4:
            descending_steps = sum(
                decreasing[index] < decreasing[index - 1]
                for index in range(1, len(decreasing))
            )
            if descending_steps >= 3:
                findings.append(
                    self._finding(
                        "peel_chain",
                        "Possible peel-chain pattern",
                        "medium",
                        0.55,
                        12,
                        "At least four outgoing values show a repeatedly decreasing sequence.",
                        {"sample_values": [str(value) for value in decreasing[:8]]},
                    )
                )

        if len(dated) >= 2:
            span = dated[-1].timestamp - dated[0].timestamp
            if span <= timedelta(hours=1) and len(dated) >= 5:
                findings.append(
                    self._finding(
                        "rapid_pass_through",
                        "Rapid transaction sequence",
                        "medium",
                        0.7,
                        15,
                        f"{len(dated)} transactions occurred within one hour.",
                        {
                            "first": dated[0].timestamp.isoformat(),
                            "last": dated[-1].timestamp.isoformat(),
                        },
                    )
                )
            if span >= timedelta(days=180) and (
                datetime.now(timezone.utc) - dated[-1].timestamp
            ) <= timedelta(days=7):
                gaps = [
                    dated[index].timestamp - dated[index - 1].timestamp
                    for index in range(1, len(dated))
                ]
                if gaps and max(gaps) >= timedelta(days=180):
                    findings.append(
                        self._finding(
                            "dormant_reactivated",
                            "Dormant wallet recently active",
                            "medium",
                            0.8,
                            12,
                            "A gap of at least 180 days preceded recent activity.",
                            {"largest_gap_days": max(gaps).days},
                        )
                    )

        repeated = Counter(cp.lower() for cp in counterparties if cp)
        if repeated and repeated.most_common(1)[0][1] >= 5:
            cp, count = repeated.most_common(1)[0]
            findings.append(
                self._finding(
                    "repeated_counterparty",
                    "Repeated counterparty pattern",
                    "low",
                    0.65,
                    5,
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
        unique = {}
        for finding in findings:
            current = unique.get(finding["rule_id"])
            if current is None or finding["score_contribution"] > current["score_contribution"]:
                unique[finding["rule_id"]] = finding
        return list(unique.values())
