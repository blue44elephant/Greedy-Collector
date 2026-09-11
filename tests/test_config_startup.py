"""Fresh-process configuration checks; never load the real repository's .env."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
KEYS = ["ETHERSCAN_API_KEY", "ALCHEMY_API_KEY", "OPENSANCTIONS_API_KEY",
        "URLSCAN_API_KEY", "VIRUSTOTAL_API_KEY"]


@pytest.fixture
def isolated_app(tmp_path):
    project = tmp_path / "application"
    project.mkdir()
    shutil.copy2(ROOT / "main.py", project / "main.py")
    for directory in ["greedy_collector", "static"]:
        shutil.copytree(ROOT / directory, project / directory,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    caller = tmp_path / "unrelated-caller"
    caller.mkdir()
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("GREEDY_COLLECTOR_")
           and key not in [*KEYS, "SEC_USER_AGENT", "PYTHON_DOTENV_DISABLED"]}
    env["PYTHONPATH"] = str(project)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return project, caller, env


def run_python(app, code, process_values=None):
    project, caller, env = app
    result = subprocess.run([sys.executable, "-B", "-c", code], cwd=caller,
                            env={**env, **(process_values or {})}, capture_output=True,
                            text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return result


def test_repository_dotenv_loads_all_existing_settings(isolated_app):
    project, caller, _ = isolated_app
    # Neither the caller's file nor a parent-directory file may supply credentials.
    (caller / ".env").write_text("ETHERSCAN_API_KEY=wrong-caller\n", encoding="utf-8")
    (project.parent / ".env").write_text("ETHERSCAN_API_KEY=wrong-parent\n", encoding="utf-8")
    values = {key: "dummy-file-" + key.lower() for key in KEYS}
    values.update({"GREEDY_COLLECTOR_DATABASE_URL": "sqlite:///:memory:",
                   "GREEDY_COLLECTOR_GRAPH_BACKEND": "SQLITE",
                   "GREEDY_COLLECTOR_MONITORING_BACKEND": "APSCHEDULER",
                   "GREEDY_COLLECTOR_TIMEOUT": "7.5",
                   "GREEDY_COLLECTOR_ETH_MONITOR_MINUTES": "31",
                   "GREEDY_COLLECTOR_BTC_MONITOR_MINUTES": "32",
                   "GREEDY_COLLECTOR_REDIS_URL": "redis://localhost:6379/4",
                   "GREEDY_COLLECTOR_NEO4J_URL": "http://localhost:7474",
                   "GREEDY_COLLECTOR_NEO4J_USER": "test-user",
                   "GREEDY_COLLECTOR_NEO4J_PASSWORD": "dummy-password",
                   "SEC_USER_AGENT": "Test contact@example.invalid"})
    (project / ".env").write_text("\n".join(f"{k}={v}" for k, v in values.items()), encoding="utf-8")
    run_python(isolated_app, '''
import main
from greedy_collector.config import get_settings
from greedy_collector.database import engine
s = get_settings()
assert main.settings is s
assert str(engine.url) == "sqlite:///:memory:"
for name in ["etherscan", "alchemy", "opensanctions", "urlscan", "virustotal"]:
    assert getattr(s, name + "_api_key") == "dummy-file-" + name + "_api_key"
assert s.graph_backend == "sqlite" and s.monitoring_backend == "apscheduler"
assert s.request_timeout == 7.5
assert (s.ethereum_monitor_minutes, s.bitcoin_monitor_minutes) == (31, 32)
assert s.redis_url == "redis://localhost:6379/4"
assert s.neo4j_url == "http://localhost:7474"
assert s.neo4j_user == "test-user" and s.neo4j_password == "dummy-password"
assert s.sec_user_agent == "Test contact@example.invalid"
''')


@pytest.mark.parametrize("value", ["dummy-process-value", ""])
def test_process_environment_wins_even_when_empty(isolated_app, value):
    project, _, _ = isolated_app
    (project / ".env").write_text("ETHERSCAN_API_KEY=dummy-file-value\nGREEDY_COLLECTOR_TIMEOUT=17\n", encoding="utf-8")
    run_python(isolated_app, '''
import os
from greedy_collector.config import get_settings
assert get_settings().etherscan_api_key == os.environ["EXPECTED_TEST_VALUE"]
assert get_settings().request_timeout == 9
''', {"ETHERSCAN_API_KEY": value, "EXPECTED_TEST_VALUE": value,
      "GREEDY_COLLECTOR_TIMEOUT": "9", "GREEDY_COLLECTOR_DATABASE_URL": "sqlite:///:memory:"})


def test_missing_dotenv_starts_without_scanning_other_directories(isolated_app):
    project, caller, _ = isolated_app
    for directory in [caller, project.parent]:
        (directory / ".env").write_text("ETHERSCAN_API_KEY=wrong-location\n", encoding="utf-8")
    run_python(isolated_app, '''
import main
from greedy_collector.chains import BitcoinAdapter
from greedy_collector.config import get_settings
assert get_settings().etherscan_api_key == ""
assert get_settings().alchemy_api_key == ""
assert BitcoinAdapter().validate_address("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa")
from fastapi.testclient import TestClient
with TestClient(main.app) as client:
    assert client.get("/health").status_code == 200
''', {"GREEDY_COLLECTOR_DATABASE_URL": "sqlite:///:memory:"})


def test_dotenv_reaches_ethereum_and_remains_private(isolated_app):
    project, _, _ = isolated_app
    lines = [f"{key}=dummy-private-{key.lower()}" for key in KEYS]
    lines.append("GREEDY_COLLECTOR_DATABASE_URL=sqlite:///:memory:")
    (project / ".env").write_text("\n".join(lines), encoding="utf-8")
    run_python(isolated_app, '''
import main
from greedy_collector.chains import EthereumAdapter
from fastapi.testclient import TestClient
adapter = EthereumAdapter()
assert adapter.settings.etherscan_api_key == "dummy-private-etherscan_api_key"
assert adapter._require_key() == "dummy-private-etherscan_api_key"
with TestClient(main.app) as client:
    for path in ["/", "/health", "/docs", "/openapi.json", "/api/greedy-collector/status",
                 "/static/js/api.js", "/static/js/app.js", "/static/js/wallet.js", "/static/js/graph.js"]:
        response = client.get(path)
        assert response.status_code == 200
        assert "dummy-private-" not in response.text
''')
