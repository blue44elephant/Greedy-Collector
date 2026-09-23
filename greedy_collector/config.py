from functools import lru_cache
import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel


# Load before class defaults and cached settings are evaluated. Never search the
# caller's directory or override values supplied by the process environment.
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)


class GreedyCollectorSettings(BaseModel):
    database_url: str = os.getenv(
        "GREEDY_COLLECTOR_DATABASE_URL",
        "sqlite:///./data/greedy_collector.db",
    )
    etherscan_api_key: str = os.getenv("ETHERSCAN_API_KEY", "")
    alchemy_api_key: str = os.getenv("ALCHEMY_API_KEY", "")
    tron_pro_api_key: str = os.getenv("TRON_PRO_API_KEY", "")
    opensanctions_api_key: str = os.getenv("OPENSANCTIONS_API_KEY", "")
    urlscan_api_key: str = os.getenv("URLSCAN_API_KEY", "")
    virustotal_api_key: str = os.getenv("VIRUSTOTAL_API_KEY", "")
    sec_user_agent: str = os.getenv(
        "SEC_USER_AGENT", "Greedy Collector research contact@example.invalid"
    )
    request_timeout: float = float(os.getenv("GREEDY_COLLECTOR_TIMEOUT", "20"))
    ethereum_monitor_minutes: int = int(
        os.getenv("GREEDY_COLLECTOR_ETH_MONITOR_MINUTES", "10")
    )
    bitcoin_monitor_minutes: int = int(
        os.getenv("GREEDY_COLLECTOR_BTC_MONITOR_MINUTES", "20")
    )
    tron_monitor_minutes: int = int(
        os.getenv("GREEDY_COLLECTOR_TRON_MONITOR_MINUTES", "10")
    )
    graph_backend: str = os.getenv(
        "GREEDY_COLLECTOR_GRAPH_BACKEND", "sqlite"
    ).lower()
    neo4j_url: str = os.getenv("GREEDY_COLLECTOR_NEO4J_URL", "")
    neo4j_user: str = os.getenv("GREEDY_COLLECTOR_NEO4J_USER", "neo4j")
    neo4j_password: str = os.getenv("GREEDY_COLLECTOR_NEO4J_PASSWORD", "")
    monitoring_backend: str = os.getenv(
        "GREEDY_COLLECTOR_MONITORING_BACKEND", "apscheduler"
    ).lower()
    redis_url: str = os.getenv(
        "GREEDY_COLLECTOR_REDIS_URL", "redis://localhost:6379/0"
    )


@lru_cache(maxsize=1)
def get_settings() -> GreedyCollectorSettings:
    return GreedyCollectorSettings()
