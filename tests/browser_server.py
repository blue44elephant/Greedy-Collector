"""Test-only server for browser_smoke.cjs; never imported by production."""
import os
from pathlib import Path
import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from functools import partial

os.environ["PYTHON_DOTENV_DISABLED"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["GREEDY_COLLECTOR_DATABASE_URL"] = "sqlite:///" + (Path.cwd() / "browser-test.db").as_posix()
os.environ["GREEDY_COLLECTOR_GRAPH_BACKEND"] = "sqlite"
os.environ["GREEDY_COLLECTOR_MONITORING_BACKEND"] = "apscheduler"
for key in ["ETHERSCAN_API_KEY", "ALCHEMY_API_KEY", "OPENSANCTIONS_API_KEY", "URLSCAN_API_KEY", "VIRUSTOTAL_API_KEY"]:
    os.environ[key] = "browser-test-only-key"

import main
from greedy_collector.chains import BitcoinAdapter, EthereumAdapter, BaseAdapter, ArbitrumAdapter, BnbAdapter, PolygonAdapter, SolanaAdapter, LitecoinAdapter
from greedy_collector.chains.solana import base58_encode
from greedy_collector.chains.monero import _encode_block, keccak_256
from greedy_collector.kyc.engine import KycScreeningEngine
from greedy_collector.schemas import NormalizedTransaction
from greedy_collector.chains.base import ChainDataError

SOL_ADDRESS = base58_encode(bytes(range(32)))
SOL_OTHER = base58_encode(bytes(range(2, 34)))
SOL_MINT = base58_encode(bytes(range(32, 64)))
SOL_SIGNATURE = base58_encode(bytes(range(64)))
SOL_SIGNATURE_NEW = base58_encode(bytes(range(1, 65)))
LTC_ADDRESS = "LKDyUEtTR1HXamkiEphisSiBJu6o3ZPE34"
LTC_OTHER = "M7uBSTV2qNDHDe2tHfNMqhFkZucgRMpJQk"
_MONERO_KEY = b"\x58" + b"\x66" * 31
_MONERO_PAYLOAD = bytes([18]) + _MONERO_KEY + _MONERO_KEY
_MONERO_PAYLOAD += keccak_256(_MONERO_PAYLOAD)[:4]
MONERO_ADDRESS = "".join(_encode_block(_MONERO_PAYLOAD[index:index + 8]) for index in range(0, len(_MONERO_PAYLOAD), 8))


def solana_events(address, signature=SOL_SIGNATURE):
    common = dict(chain="solana", from_address=address, to_address=SOL_OTHER,
        timestamp=datetime(2026, 9, 11, tzinfo=timezone.utc), block_number="123",
        direction="outgoing", source_api="solana-json-rpc")
    native = NormalizedTransaction(tx_hash=signature, value_native="0.25", token_symbol="SOL",
        fee="0.000005", raw_payload={"_stable_event_key":"solana-ix:0", "_public":{"event_key":"solana-ix:0", "asset_type":"native", "execution_status":"succeeded"}}, **common)
    token = NormalizedTransaction(tx_hash=signature, value_native="1.5", token_symbol="SPL",
        asset_contract=SOL_MINT, raw_payload={"_stable_event_key":"solana-inner:1:0", "_public":{"event_key":"solana-inner:1:0", "asset_type":"spl_token", "token_mint":SOL_MINT, "token_decimals":6, "raw_value":"1500000", "source_token_account":SOL_ADDRESS, "destination_token_account":SOL_OTHER, "source_owner_known":True, "destination_owner_known":True, "amount_basis":"parsed_instruction_amount"}}, **common)
    return [native, token]

# Browser checks use explicit manual monitoring, with no scheduler or external network access.
main.start_monitoring = lambda: None
main.stop_monitoring = lambda: None

counts = {}
async def balance(address, *, chain):
    if address == "provider-error" or address == "0x" + "6" * 40:
        raise ChainDataError("https://provider.invalid/v2/browser-test-only-key")
    if address == "missing-ethereum-key" or address == "0x" + "5" * 40:
        raise ChainDataError("ETHERSCAN_API_KEY missing")
    adapter = next(cls() for cls in [BitcoinAdapter, EthereumAdapter, BaseAdapter, ArbitrumAdapter, BnbAdapter, PolygonAdapter, SolanaAdapter, LitecoinAdapter] if cls.chain == chain)
    adapter.validate_address(address)
    if chain == "solana": return {"balance_native":"1.25", "source_api":"solana-json-rpc"}
    if chain == "litecoin": return {"balance_native":"3.25", "transaction_count":6, "source_api":"litecoinspace"}
    balance_value = "2.5" if chain == "base" else "1.000000000000000001"
    return {"balance_native": balance_value, "source_api": "etherscan" if chain != "bitcoin" else "blockstream"}

async def transactions(address, *, chain):
    if chain == "solana": return solana_events(address)
    if address == "0x" + "9" * 40:
        return []
    counts[address] = counts.get(address, 0) + 1
    other = "0x" + "2" * 40 if chain == "ethereum" else LTC_OTHER if chain == "litecoin" else "1BoatSLRHtKNngkdXEeobR76b53LETtpyT"
    symbol = {"bitcoin":"BTC", "litecoin":"LTC", "ethereum":"ETH"}.get(chain, "ETH")
    source = {"bitcoin":"blockstream", "litecoin":"litecoinspace"}.get(chain, "etherscan")
    base = dict(chain=chain, from_address=other, to_address=address, value_native="1", token_symbol=symbol, timestamp=datetime(2026, 9, 11, tzinfo=timezone.utc), block_number="123", direction="incoming", source_api=source)
    if address == "0x" + "3" * 40:
        baseline = NormalizedTransaction(tx_hash="e" * 64, **base)
        new = NormalizedTransaction(tx_hash="f" * 64, **base)
        if counts[address] == 1:
            return [baseline]
        if counts[address] == 3:
            return [NormalizedTransaction(tx_hash="a" * 64, **base)]
        if counts[address] == 4:
            raise ChainDataError("https://provider.invalid/v2/browser-test-only-key")
        return [new, baseline]
    rows = [NormalizedTransaction(tx_hash="b" * 64, **base)]
    if counts[address] >= 3:
        rows.insert(0, NormalizedTransaction(tx_hash="a" * 64, **base))
    if chain in ("bitcoin", "litecoin"):
        rows.insert(0, NormalizedTransaction(tx_hash="c" * 64, **{**base, "timestamp": None, "block_number": ""}))
    if chain == "ethereum":
        rows.append(NormalizedTransaction(tx_hash="d" * 64, **{**base, "token_symbol": "TEST", "value_native": "1.234567"}))
    return rows

async def transaction(tx_hash, *, chain):
    is_btc = chain == "bitcoin"
    is_ltc = chain == "litecoin"
    return NormalizedTransaction(chain=chain, tx_hash=tx_hash,
        from_address="1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa" if is_btc else LTC_ADDRESS if is_ltc else "0x"+"1"*40,
        to_address="1BoatSLRHtKNngkdXEeobR76b53LETtpyT" if is_btc else LTC_OTHER if is_ltc else "0x"+"2"*40,
        value_native="1.000000000000000001", token_symbol="BTC" if is_btc else "LTC" if is_ltc else "ETH",
        block_number="123", fee="0.00001", timestamp=datetime(2026,9,11,tzinfo=timezone.utc),
        source_api="blockstream" if is_btc else "litecoinspace" if is_ltc else "etherscan")

async def solana_transaction_events(tx_hash):
    return solana_events(SOL_ADDRESS, tx_hash)

solana_monitor_polls = {}
async def solana_monitoring_delta(self, address, previous_identity, *, limit=100):
    solana_monitor_polls[address] = solana_monitor_polls.get(address, 0) + 1
    poll = solana_monitor_polls[address]
    if poll == 1:
        return {"transactions":solana_events(address, SOL_SIGNATURE_NEW), "boundary_found":True}
    if poll == 2:
        return {"transactions":solana_events(address, SOL_SIGNATURE_NEW), "boundary_found":True}
    return {"transactions":[], "boundary_found":False}

for adapter in [BitcoinAdapter, EthereumAdapter, BaseAdapter, ArbitrumAdapter, BnbAdapter, PolygonAdapter, SolanaAdapter, LitecoinAdapter]:
    adapter.lookup_transaction = AsyncMock(side_effect=partial(transaction, chain=adapter.chain))
    adapter.lookup_address = AsyncMock(side_effect=partial(balance, chain=adapter.chain))
    adapter.transactions = AsyncMock(side_effect=partial(transactions, chain=adapter.chain))
SolanaAdapter.lookup_transaction_events = AsyncMock(side_effect=solana_transaction_events)
SolanaAdapter.monitoring_delta = solana_monitoring_delta

async def research_request(url, **kwargs):
    if "opensanctions" in url:
        if kwargs.get("params", {}).get("q") == "No result fixture": return {"results": []}
        return {"results": [{"caption":"Fixture Company", "id":"test-entity", "schema":"Company", "datasets":["test"], "api_key":"browser-test-only-key", "public_evidence":"Retained source evidence"}]}
    if "interpol" in url: return {"_embedded":{"notices":[]}}
    if "sec.gov" in url: return {}
    if "gdelt" in url: return {"articles":[]}
    if "crt.sh" in url: return []
    if "urlscan" in url: raise RuntimeError("https://provider.invalid?api_key=browser-test-only-key")
    if "virustotal" in url: return {"data":{"attributes":{}}}
    raise AssertionError("Unexpected test provider URL")

KycScreeningEngine._request = staticmethod(research_request)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(main.app, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
