"""Resolver API tests use real validators and prohibit provider I/O."""
import pytest
from fastapi.testclient import TestClient
import main
from greedy_collector.chains import BitcoinAdapter, EthereumAdapter, TronAdapter
from greedy_collector.chains.base import ChainAdapter


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "start_monitoring", lambda: None)
    monkeypatch.setattr(main, "stop_monitoring", lambda: None)
    def forbidden(*args, **kwargs):
        pytest.fail("Resolver attempted a provider operation")
    for adapter in [BitcoinAdapter, EthereumAdapter, TronAdapter]:
        monkeypatch.setattr(adapter, "lookup_address", forbidden)
        monkeypatch.setattr(adapter, "lookup_transaction", forbidden)
        monkeypatch.setattr(adapter, "transactions", forbidden)
    monkeypatch.setattr(ChainAdapter, "_get", forbidden)
    monkeypatch.setattr(ChainAdapter, "_post", forbidden)
    # No startup scheduler needed for pure resolver routes.
    with TestClient(main.app) as result:
        yield result


@pytest.mark.parametrize("value,chain,kind", [
    ("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", "bitcoin", "address"),
    ("3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy", "bitcoin", "address"),
    ("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kygt080", "bitcoin", "address"),
    ("0x" + "A1" * 20, "ethereum", "address"),
    ("a" * 64, "bitcoin", "transaction"),
    ("0x" + "B" * 64, "ethereum", "transaction"),
    ("bc1" + "a" * 61, "bitcoin", "transaction"),
])
def test_supported_identifier(client, value, chain, kind):
    response = client.post("/api/greedy-collector/resolve", json={"input": value})
    assert response.status_code == 200
    assert response.json() == {"kind":kind, "chain":chain, "normalized":value.lower() if kind == "transaction" else value, "lookup_type":kind}


def test_resolver_reuses_adapter_validation(client, monkeypatch):
    original = EthereumAdapter.validate_address
    seen = []
    def validate(self, value):
        seen.append(value)
        return original(self, value)
    monkeypatch.setattr(EthereumAdapter, "validate_address", validate)
    value = "0x" + "1" * 40
    assert client.post("/api/greedy-collector/resolve", json={"input":" \n\t" + value + "\r\n"}).json()["normalized"] == value
    assert seen == [value]


@pytest.mark.parametrize("value", ["", "  ", "unrecognized research identifier", "0x1234", "0x" + "g" * 40,
                                  "0x" + "a" * 63, "a" * 63, "0x" + "1" * 20 + " " + "1" * 20])
def test_unknown_returns_safe_result_without_lookup(client, value):
    response = client.post("/api/greedy-collector/resolve", json={"input":value})
    assert response.status_code == 200
    assert response.json()["kind"] == "unknown"
    assert len(response.json()["supported"]) == 6
    assert "normalized" not in response.json()


def test_resolution_does_not_expose_credentials(client, monkeypatch):
    secret = "dummy-secret-that-must-not-be-reflected"
    monkeypatch.setattr(main.settings, "etherscan_api_key", secret)
    for value in [secret, "0x" + "1" * 40]:
        response = client.post("/api/greedy-collector/resolve", json={"input":value})
        assert secret not in response.text
