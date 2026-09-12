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
from greedy_collector.chains import BitcoinAdapter, EthereumAdapter
from greedy_collector.kyc.engine import KycScreeningEngine
from greedy_collector.schemas import NormalizedTransaction
from greedy_collector.chains.base import ChainDataError

# Browser checks use explicit manual monitoring, with no scheduler or external network access.
main.start_monitoring = lambda: None
main.stop_monitoring = lambda: None

counts = {}
async def balance(address, *, chain):
    if address == "provider-error" or address == "0x" + "6" * 40:
        raise ChainDataError("https://provider.invalid/v2/browser-test-only-key")
    if address == "missing-ethereum-key" or address == "0x" + "5" * 40:
        raise ChainDataError("ETHERSCAN_API_KEY missing")
    adapter = EthereumAdapter() if chain == "ethereum" else BitcoinAdapter()
    adapter.validate_address(address)
    return {"balance_native": "1.000000000000000001", "source_api": "etherscan" if address.startswith("0x") else "blockstream"}

async def transactions(address):
    if address == "0x" + "9" * 40:
        return []
    chain = "ethereum" if address.startswith("0x") else "bitcoin"
    counts[address] = counts.get(address, 0) + 1
    other = "0x" + "2" * 40 if chain == "ethereum" else "1BoatSLRHtKNngkdXEeobR76b53LETtpyT"
    base = dict(chain=chain, from_address=other, to_address=address, value_native="1", token_symbol="ETH" if chain == "ethereum" else "BTC", timestamp=datetime(2026, 9, 11, tzinfo=timezone.utc), block_number="123", direction="incoming", source_api="etherscan" if chain == "ethereum" else "blockstream")
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
    if chain == "bitcoin":
        rows.insert(0, NormalizedTransaction(tx_hash="c" * 64, **{**base, "timestamp": None, "block_number": ""}))
    else:
        rows.append(NormalizedTransaction(tx_hash="d" * 64, **{**base, "token_symbol": "TEST", "value_native": "1.234567"}))
    return rows

async def transaction(tx_hash, *, chain):
    return NormalizedTransaction(chain=chain, tx_hash=tx_hash,
        from_address="0x"+"1"*40 if chain == "ethereum" else "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
        to_address="0x"+"2"*40 if chain == "ethereum" else "1BoatSLRHtKNngkdXEeobR76b53LETtpyT",
        value_native="1.000000000000000001", token_symbol="ETH" if chain == "ethereum" else "BTC",
        block_number="123", fee="0.00001", timestamp=datetime(2026,9,11,tzinfo=timezone.utc),
        source_api="etherscan" if chain == "ethereum" else "blockstream")

for adapter in [BitcoinAdapter, EthereumAdapter]:
    adapter.lookup_transaction = AsyncMock(side_effect=partial(transaction, chain=adapter.chain))
    adapter.lookup_address = AsyncMock(side_effect=partial(balance, chain=adapter.chain))
    adapter.transactions = AsyncMock(side_effect=transactions)

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
