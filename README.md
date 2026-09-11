# Greedy Collector

Greedy Collector is a standalone application for inspecting public Bitcoin and Ethereum
wallet activity. It retrieves records from configured providers, stores normalized results
in SQLite, applies deterministic risk rules, and provides Wallet, Graph, and Monitoring workspaces.
Other existing backend workflows remain accessible through Swagger at `/docs`; they are
not exposed in this frontend increment.

Production operations use real provider responses and database records. There is no
fixture-data mode. An empty database or empty provider response produces an empty state.
Mocks and provider fixtures belong only to automated tests.

## Install and run

Python 3.12 or newer is required.

```powershell
cd "C:\Tools\Inventions\greedy-collector"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -r requirements-dev.txt
Copy-Item .env.example .env
# Edit .env with your server-side configuration before proceeding.
alembic upgrade head
uvicorn main:app --reload
```

Open **http://127.0.0.1:8000/** for the application.
API documentation remains at **http://127.0.0.1:8000/docs**.
Health information is available at `/health` and `/api/greedy-collector/status`.

Greedy Collector automatically reads `.env` beside `main.py` before configuration
is initialized, including when imported by Uvicorn's reload worker or Alembic.
The file is optional. It is resolved from the application location, not the caller's
working directory; unrelated parent directories are never searched.

After `Copy-Item .env.example .env`, edit `.env` with your server-side configuration
before starting the application. **Never commit `.env`**; it is ignored by Git.
Existing process environment variables override `.env` values, including explicitly
empty variables. Normal startup remains `uvicorn main:app --reload`; no `--env-file`
argument is required. Restart the server after changing configuration, since settings
are initialized and cached on import. Migrations use the same configuration loader:

```powershell
alembic upgrade head
```

Use public wallet addresses only. Never enter a private key or recovery phrase.
No provider keys are entered through the browser.

## Providers and configuration

### Bitcoin

Blockstream is the primary public provider; Mempool.space is the fallback. No API key
is normally required. History retrieves up to approximately 500 confirmed records plus
the initial provider mempool set. A failure on any Blockstream history page discards that
attempt and restarts with Mempool.space.

### Ethereum

Full address lookup and transaction retrieval require `ETHERSCAN_API_KEY`.
`ALCHEMY_API_KEY` is optional for balance fallback only; it does not replace Etherscan
transaction retrieval. Alchemy uses HTTP POST JSON-RPC `eth_getBalance`.

Normal ETH transactions and ERC-20 transfers each paginate up to 10 pages of 1,000
records, before normalization and deduplication. A later-page error fails the lookup.
Ethereum pending/mempool monitoring is not implemented; finality is not enforced.

## Workspaces

### Wallet

Choose Bitcoin or Ethereum and enter a public wallet address. **Lookup** calls the
configured providers and shows fresh balance, records, risk findings, counterparties,
and provenance. **View stored** reads local state without fetching provider data.
Fresh lookup uses `POST /api/greedy-collector/lookup/address`. **View stored** reads
`GET /api/greedy-collector/address/{chain}/{address}`, `/transactions`, and `/risk`.
The view displays the profile update timestamp and stored risk calculation timestamp.
No stored risk result and empty transactions have separate empty states.
The `refresh` API input currently does not change lookup behavior: POST lookup always
fetches providers. Counterparty **Investigate** is explicit; no recursive crawling occurs.
Amounts retain their original decimal strings and token units. No USD valuation is
invented. Missing Bitcoin timestamp/block information is presented as unconfirmed.

### Graph

Load one to three hops from stored transactions using
`GET /api/greedy-collector/address/{chain}/{address}/graph?hops=N`. Select a node for its address/type,
read directional edges and their transaction details,
use **Investigate wallet** to fetch that address, and pan/zoom the SVG view. Transactions
are also listed below the graph. A deeper hop request does not fetch counterparties or
guarantee complete blockchain coverage. SQLite is authoritative; optional Neo4j mirrors
can be configured using the `GREEDY_COLLECTOR_NEO4J_*` settings.

### Monitoring

Add a public Bitcoin or Ethereum address without first looking it up. Edit its label,
notes, priority, enabled state, or optional existing case ID. Duplicate addresses return
the existing watch. **Disable watch** preserves its baseline, runs, and alerts;
re-enabling continues from that retained boundary. The UI does not hard-delete watches.

The Scheduler section displays the API's actual configured intervals and local scheduler
state. **Check now** uses the existing server monitoring cycle for the selected enabled
watch; scheduled checks use the same logic. UI state refreshes after actions or through
**Refresh monitoring**. It does not promise continuous updates or verified Celery activity.
Use one application process: the overlap guard is process-local.

The first observation establishes a silent baseline and does not alert historical activity.
Bitcoin uses a confirmed transaction for that initial boundary; empty or mempool-only
history may leave it unset. If a previous boundary disappears from bounded provider history,
the run reports **Continuity loss**, preserves the boundary, and suppresses ambiguous alerts.
Provider failures are displayed separately with sanitized messages.

Run history loads 25 records at a time, newest first. Manual results show actual run fields
and a labelled comparison of pre-check and returned boundaries. The API does not provide
per-run generated-alert counts or historical boundary snapshots. **Wallet alerts** lists
actual stored alerts filtered by the selected address and chain; risk-only alerts may have
no transaction hash. The existing alerts endpoint has no wallet filter or pagination.

Bitcoin requires no API key. Ethereum monitoring requires `ETHERSCAN_API_KEY`;
`ALCHEMY_API_KEY` is only an optional balance fallback and does not replace Etherscan history.
No fake watches, provider results, or alerts are substituted when requests fail.

## Storage and interpretation limits

The default database is `sqlite:///./data/greedy_collector.db`, configured with
`GREEDY_COLLECTOR_DATABASE_URL`. Use Alembic revision `20260630_01` for initialization.
SQLite foreign keys are enabled by the application engine. No Epic Archer installation
or database is required.

- Neither chain guarantees lifetime-complete transaction history.
- Repeated lookup inserts previously unseen transaction identities, updates the address,
  and adds a risk result. Existing transaction rows are not updated, so stored confirmation
  state/direction can differ from fresh lookup data. Direction reflects the lookup that
  first inserted the row. The interface labels stored views; address queries may be
  case-sensitive, so use the original address spelling when inspecting stored state.
- Bitcoin normalization retains representative input/output addresses. Stored queries and
  graph edges are simplified, not a complete Bitcoin input/output model.
- SQLite graph traversal groups rows by transaction hash and may collapse multiple transfers
  sharing that hash. Deeper graphs require additional explicit wallet lookups.
- Provider transaction counts and returned-record counts can have different meanings.
- Risk scores are deterministic indicators, not proof of wrongdoing or ownership.
- External source availability and rate limits can cause failures. Errors never trigger
  substitute data. Configure credentials server-side and retry when appropriate.

## Tests

```powershell
python -m pytest tests/ -q
```

Tests use isolated SQLite state and mocked external providers. Production paths do not
load these fixtures. Optional browser smoke verification uses an installed Chromium browser
and Node without a frontend build or third-party browser-testing package:

```powershell
node tests/browser_smoke.cjs
```

This starts a temporary local test server, uses test-only provider fixtures, checks Wallet/Graph/Monitoring
browser interactions, stored state, explicit investigation, and empty/error states, and shuts down its processes. It does not contact public providers.

## Source structure

- `main.py`: application entry point and lifecycle
- `static/index.html`, `static/app.css`, `static/js/`: browser application
- `greedy_collector/`: provider adapters, storage, services, API, risk, monitoring, research
- `migrations/`: immutable Alembic baseline
- `tests/`: automated checks and test-only fixtures
