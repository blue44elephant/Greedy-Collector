from datetime import datetime, timedelta, timezone

from greedy_collector.risk import ExplainableRiskEngine
from greedy_collector.schemas import NormalizedTransaction


def tx(index: int, direction: str = "outgoing", value: str = "10"):
    return NormalizedTransaction(
        tx_hash=f"tx-{index}",
        chain="ethereum",
        from_address="0xfocus" if direction == "outgoing" else f"0xsender{index}",
        to_address=f"0xtarget{index}" if direction == "outgoing" else "0xfocus",
        value_native=value,
        token_symbol="ETH",
        timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc) + timedelta(minutes=index),
        direction=direction,
        source_api="test",
    )


def test_direct_sanctions_exposure_is_explainable():
    transactions = [tx(1)]
    labels = [
        {
            "address": "0xtarget1",
            "label": "Official list entry",
            "type": "Sanctioned",
            "source": "Official test fixture",
            "confidence": 1.0,
        }
    ]
    result = ExplainableRiskEngine().evaluate("0xfocus", transactions, labels)
    finding = next(item for item in result["findings"] if item["rule_id"] == "direct_sanctioned")
    assert finding["score_contribution"] == 40
    assert finding["evidence"]["tx_hash"] == "tx-1"
    assert "does not prove" in result["disclaimer"]


def test_behavioral_rules_do_not_exceed_one_hundred():
    transactions = [
        tx(index, "outgoing", str(200 - index * 10)) for index in range(25)
    ]
    result = ExplainableRiskEngine().evaluate("0xfocus", transactions, [])
    assert 0 <= result["score"] <= 10
    assert result["level"] == "Low"
    ids = {item["rule_id"] for item in result["findings"]}
    assert {"high_velocity", "one_to_many", "peel_chain"}.issubset(ids)


def test_indirect_exposure_explains_intermediary_uncertainty():
    result = ExplainableRiskEngine().evaluate(
        "0xfocus",
        [tx(1)],
        [],
        [
            {
                "hops": 2,
                "terminal_type": "Mixer",
                "confidence": 0.8,
                "path": ["0xfocus", "0xmiddle", "0xmixer"],
            }
        ],
    )
    finding = next(item for item in result["findings"] if item["rule_id"] == "indirect_exposure")
    assert "may be unrelated" in finding["explanation"]
