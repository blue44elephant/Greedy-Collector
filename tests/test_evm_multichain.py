"""Provider-contract tests for descriptor-configured Etherscan V2 networks."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from greedy_collector.chains import get_chain_adapter, list_chains
from greedy_collector.chains.registry import Capability
from greedy_collector.config import GreedyCollectorSettings
from greedy_collector.resolver import resolve_identifier

ADDRESS = "0x" + "a" * 40
TX_HASH = "0x" + "b" * 64
NETWORKS = {
    "ethereum": (1, "ETH", "Ethereum", "https://etherscan.io"),
    "base": (8453, "ETH", "Base", "https://basescan.org"),
    "arbitrum": (42161, "ETH", "Arbitrum One", "https://arbiscan.io"),
    "bsc": (56, "BNB", "BNB Smart Chain", "https://bscscan.com"),
    "polygon": (137, "POL", "Polygon", "https://polygonscan.com"),
}

@pytest.mark.parametrize("chain,config", NETWORKS.items())
def test_evm_network_descriptors_are_safe_and_capable(chain, config):
    chain_id,symbol,name,explorer=config
    definition = next(item for item in list_chains() if item.chain_id == chain)
    metadata = definition.public_metadata()
    assert metadata["evm_chain_id"] == chain_id
    assert metadata["native_symbol"] == symbol
    assert metadata["display_name"] == name and metadata["explorer_url"] == explorer
    assert {Capability.BALANCE, Capability.TRANSACTION_HISTORY, Capability.TRANSACTION_LOOKUP,
            Capability.TOKEN_TRANSFERS, Capability.GRAPH, Capability.MONITORING,
            Capability.LABELS, Capability.CASES, Capability.ATTRIBUTION, Capability.DISCOVERY} <= definition.capabilities
    adapter=definition.adapter()
    assert adapter.validate_address(ADDRESS) == ADDRESS
    assert adapter.evm_chain_id==chain_id and adapter.native_symbol==symbol
    assert adapter.display_name==name and adapter.explorer_url==explorer
    assert "api_key" not in json.dumps(metadata).lower() and "secret" not in json.dumps(metadata).lower()

@pytest.mark.parametrize("chain,expected", [(chain, chain) for chain in NETWORKS])
def test_evm_address_and_hash_require_explicit_network_hint(chain, expected):
    assert resolve_identifier(ADDRESS)["kind"] == "ambiguous"
    assert resolve_identifier(ADDRESS, chain_hint=chain)["chain"] == expected
    assert resolve_identifier(TX_HASH)["kind"] == "ambiguous"
    tx = resolve_identifier(TX_HASH, chain_hint=chain)
    assert tx["kind"] == "transaction" and tx["chain"] == expected

def test_resolution_is_local_and_preserves_bare_bitcoin_hash(monkeypatch):
    monkeypatch.setattr("httpx.AsyncHTTPTransport.handle_async_request", lambda *a, **k: pytest.fail("resolution must not call a provider"))
    assert resolve_identifier("A" * 64)["kind"] == "ambiguous"
    assert resolve_identifier("unrecognized arbitrary text")["kind"] == "unknown"

@pytest.mark.parametrize("chain,config", NETWORKS.items())
def test_etherscan_v2_requests_and_native_amounts_are_chain_configured(monkeypatch, chain, config):
    chain_id,symbol,name,explorer=config
    adapter = get_chain_adapter(chain)
    adapter.settings = GreedyCollectorSettings(etherscan_api_key="test-only-key")
    calls = []
    async def fake_get(url, **kwargs):
        calls.append((url, kwargs["params"]))
        action = kwargs["params"]["action"]
        if action == "balance": return {"status":"1", "message":"OK", "result":str(10**18)}
        if action == "txlist":
            return {"status":"1", "message":"OK", "result":[{"hash":TX_HASH,"from":ADDRESS,"to":"0x"+"c"*40,"value":str(10**18),"timeStamp":"1700000000","blockNumber":"123","gas":"21000","gasUsed":"21000","gasPrice":"1"}]}
        if action == "tokentx":
            return {"status":"1", "message":"OK", "result":[{"hash":TX_HASH,"from":ADDRESS,"to":"0x"+"d"*40,"value":"2500000","tokenSymbol":"USDC","tokenName":"USD Coin","tokenDecimal":"6","contractAddress":"0x"+"e"*40,"logIndex":"7","timeStamp":"1700000000","blockNumber":"123"}]}
        raise AssertionError(action)
    monkeypatch.setattr(adapter, "_get", fake_get)
    balance = asyncio.run(adapter.lookup_address(ADDRESS))
    rows = asyncio.run(adapter.transactions(ADDRESS))
    assert balance["balance_native"] == "1" and balance["chain"] == chain
    assert {row[1]["chainid"] for row in calls} == {str(chain_id)}
    assert all(row[0] == "https://api.etherscan.io/v2/api" for row in calls)
    assert all(row[1]["apikey"] == "test-only-key" for row in calls)
    native = next(row for row in rows if row.token_symbol == symbol)
    token = next(row for row in rows if row.token_symbol == "USDC")
    assert native.value_native == "1" and native.chain == chain and native.source_api == "etherscan"
    assert token.value_native == "2.5" and token.chain == chain and token.event_index == "7"
    assert token.asset_contract == "0x" + "e"*40

def test_chain_api_exposes_descriptors_and_default_resolution_only():
    import main
    with TestClient(main.app) as client:
        rows = client.get("/api/greedy-collector/chains").json()["chains"]
        assert {row["id"] for row in rows} >= set(NETWORKS) | {"bitcoin", "tron"}
        assert client.post("/api/greedy-collector/resolve", json={"input":ADDRESS}).json()["kind"] == "ambiguous"
        assert client.post("/api/greedy-collector/resolve", json={"input":ADDRESS,"chain_hint":"base"}).json()["chain"] == "base"
        assert client.get("/api/greedy-collector/status").json()["backends"]["monitoring"]["chain_intervals"]["polygon"] == 10


def test_wallet_search_hint_is_dynamic_and_optional():
    from pathlib import Path
    html = Path("static/index.html").read_text(encoding="utf-8")
    wallet = Path("static/js/wallet.js").read_text(encoding="utf-8")
    assert 'id="chain-hint"' in html and 'value="">Auto-detect' in html
    assert 'for (const [id, name] of chains)' in wallet
    assert 'chain_hint:selectedHint' in wallet
    assert all(f'"{chain}"' not in wallet for chain in ("base", "arbitrum", "bsc", "polygon"))


@pytest.mark.parametrize("chain,config", NETWORKS.items())
def test_transaction_lookup_api_dispatches_to_selected_network(monkeypatch, chain, config):
    import main
    from greedy_collector.chains.base import ChainAdapter
    chain_id,symbol,name,explorer=config
    monkeypatch.setattr("greedy_collector.chains.base.get_settings", lambda: GreedyCollectorSettings(etherscan_api_key="test-only-key"))
    calls=[]
    async def fake_get(self,url,**kwargs):
        calls.append(kwargs["params"])
        return {"status":"1","message":"OK","result":{"hash":TX_HASH,"from":ADDRESS,"to":"0x"+"c"*40,
            "value":hex(10**18),"blockNumber":hex(123),"gas":hex(21000),"gasPrice":"0x1"}}
    monkeypatch.setattr(ChainAdapter,"_get",fake_get)
    with TestClient(main.app) as client:
        response=client.post("/api/greedy-collector/lookup/tx",json={"chain":chain,"tx_hash":TX_HASH})
    assert response.status_code==200
    result=response.json()
    assert result["chain"]==chain and result["token_symbol"]==symbol and result["value_native"]=="1"
    assert calls[0]["chainid"]==str(chain_id) and calls[0]["apikey"]=="test-only-key"
    assert "test-only-key" not in response.text

def test_network_configuration_error_is_safe_and_chain_specific(monkeypatch):
    import main
    from greedy_collector.chains.base import ChainAdapter
    monkeypatch.setattr("greedy_collector.chains.base.get_settings", lambda: GreedyCollectorSettings(etherscan_api_key=""))
    monkeypatch.setattr(ChainAdapter,"_get",lambda *args,**kwargs: pytest.fail("must fail locally before provider request"))
    with TestClient(main.app) as client:
        response=client.post("/api/greedy-collector/lookup/tx",json={"chain":"base","tx_hash":TX_HASH})
    assert response.status_code==502
    assert response.json()["detail"]=="Base provider configuration is unavailable."
    assert "ETHERSCAN_API_KEY" not in response.text
