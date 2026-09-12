"""Insert deterministic alerts into the isolated browser-test database only."""
from pathlib import Path
import os
import sys
import tempfile

database = Path(sys.argv[1]).resolve()
assert database.name == "browser-test.db" and database.is_file()
assert database.parent.name.startswith("gc-browser-")
assert database.parent.parent == Path(tempfile.gettempdir()).resolve()
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["GREEDY_COLLECTOR_DATABASE_URL"] = "sqlite:///" + database.as_posix()
os.environ["GREEDY_COLLECTOR_GRAPH_BACKEND"] = "sqlite"
os.environ["GREEDY_COLLECTOR_MONITORING_BACKEND"] = "apscheduler"
for key in ["ETHERSCAN_API_KEY", "ALCHEMY_API_KEY", "OPENSANCTIONS_API_KEY", "URLSCAN_API_KEY", "VIRUSTOTAL_API_KEY"]:
    os.environ[key] = "browser-test-only-key"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from greedy_collector.database import SessionLocal
from greedy_collector.models import WalletAlert

with SessionLocal() as db:
    db.add(WalletAlert(wallet="1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", chain="bitcoin", tx_hash="b"*64,
                       counterparty="1BoatSLRHtKNngkdXEeobR76b53LETtpyT", amount="0.00000001", token="BTC",
                       severity="Medium", trigger_type="Browser transaction alert", risk_score=10,
                       explanation="Test-only transaction fixture", dedupe_key="browser-transaction-fixture"))
    db.add(WalletAlert(wallet="0x"+"4"*40, chain="ethereum", severity="High", trigger_type="Browser risk-only alert",
                       risk_score=50, explanation="Test-only risk fixture", dedupe_key="browser-risk-fixture"))
    db.commit()
