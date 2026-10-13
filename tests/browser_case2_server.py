"""CASE-2 isolated browser server. All sources are test-only local fixtures."""
import os
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
work = Path.cwd().resolve()
assert work.is_relative_to(Path(tempfile.gettempdir()).resolve())
sys.path.insert(0, str(root))
os.environ.update(PYTHON_DOTENV_DISABLED="1",
    GREEDY_COLLECTOR_DATABASE_URL="sqlite:///" + (work/"case2.db").as_posix(),
    GREEDY_COLLECTOR_GRAPH_BACKEND="sqlite", TAVILY_KEYLESS_ENABLED="false",
    BRAVE_SEARCH_STORAGE_ALLOWED="true", BRAVE_SEARCH_API_KEY="case2-test-only")
from alembic import command
from alembic.config import Config
cfg = Config(str(root/"alembic.ini"))
cfg.set_main_option("script_location", str(root/"migrations"))
command.upgrade(cfg, "head")
import httpx
import requests
import main
from greedy_collector.database import engine
from tests.case2_material import seed, mutate

main.start_monitoring = lambda: None
main.stop_monitoring = lambda: None
def blocked(*args, **kwargs):
    (work/"external-request-attempted").write_text("Provider/source request attempted")
    raise AssertionError("CASE-2 browser must never request live providers")
httpx.HTTPTransport.handle_request = blocked
httpx.AsyncHTTPTransport.handle_async_request = blocked
requests.Session.request = blocked
material = seed(engine)

@main.app.get("/test-case2-material")
def fixture_material():
    return material

@main.app.post("/test-case2-mutate")
def change_fixture():
    mutate(engine, material)
    return {"changed": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(main.app, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
