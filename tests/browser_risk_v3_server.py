"""Isolated RISK-2 browser fixture: temporary SQLite and no external requests."""
import importlib
import os
import sys
import tempfile
from pathlib import Path

work = Path.cwd().resolve()
assert work.is_relative_to(Path(tempfile.gettempdir()).resolve())
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["GREEDY_COLLECTOR_DATABASE_URL"] = "sqlite:///" + (work / "risk-v3.db").as_posix()
os.environ["GREEDY_COLLECTOR_GRAPH_BACKEND"] = "sqlite"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
import requests
import uvicorn
import main
from greedy_collector.database import engine
from greedy_collector.models import Base
from greedy_collector.sanctions.ofac import OfacSdnSource, parse_sdn_xml
from tests.test_sanctions_registry import source

Base.metadata.create_all(engine)
main.start_monitoring = lambda: None
main.stop_monitoring = lambda: None

def blocked(*args, **kwargs):
    raise AssertionError("External request during browser fixture")

requests.Session.request = blocked
httpx.AsyncHTTPTransport.handle_async_request = blocked
httpx.HTTPTransport.handle_request = blocked

A, B, C, D = ("0x" + character * 40 for character in "abcd")
snapshots = [source([(1, "Fixture listing", ["CYBER2"], [("ETH", A)])]),
             source([(2, "Replacement listing", ["CYBER2"], [("ETH", B)])])]
state = {"calls": 0}

def fetch(self):
    index = min(state["calls"], len(snapshots) - 1)
    state["calls"] += 1
    return snapshots[index], None

OfacSdnSource.fetch = fetch
OfacSdnSource.parse = lambda self, data: parse_sdn_xml(data, minimum_entities=1)

services = importlib.import_module("greedy_collector.services")
original_adapter = services.get_chain_adapter

# Each lookup receives its own adapter. The wrapper records the requested test
# address, then the adapter factory labels coverage without changing production code.
requested = {"address": None}
def fixture_adapter(chain):
    adapter = original_adapter(chain)
    if chain == "ethereum":
        adapter.collection_streams = {"native": {"status": "PARTIAL" if requested["address"] == D else "COMPLETE"}}
    return adapter

services.get_chain_adapter = fixture_adapter
router = importlib.import_module("greedy_collector.router")
actual_lookup = router.service.lookup_address
actual_paths = router.service._exposure_paths

def fixture_paths(db, chain, address, hops):
    if address == C:
        return [{"hops": 2, "terminal_type": "Sanctioned", "confidence": .8,
                 "path": [C, B, A], "source": "Test-only Label path"}]
    return actual_paths(db, chain, address, hops)

router.service._exposure_paths = fixture_paths

async def wallet(db, payload):
    requested["address"] = payload.address
    return await actual_lookup(db, payload,
        profile_override={"balance_native": "0", "source_api": "test-only"}, transactions_override=[])

router.service.lookup_address = wallet

if __name__ == "__main__":
    uvicorn.run(main.app, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
