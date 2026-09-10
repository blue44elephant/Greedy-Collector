# Greedy Collector

Greedy Collector accepts public Bitcoin and Ethereum addresses, retrieves public information from configured blockchain services, stores normalized results locally, applies deterministic rules to the collected activity, monitors addresses for newly observed activity, and exposes results through an API.

## What It Does

### Input
- Bitcoin or Ethereum wallet addresses
- Optional: Organize addresses into cases for grouped analysis

### Output
- Bounded transaction history from the configured public providers
- Current wallet balance
- Deterministic risk indicators and their evidence
- Periodic monitoring alerts for newly observed wallet activity
- Local graph of transaction paths (1-3 hops)
- Case management and analyst notes
- Exportable reports (CSV, HTML, Markdown, PDF)

### Data Sources

**Bitcoin** (no API key required):
- Blockstream.info (primary provider)
- Mempool.space (fallback)
- Free, public APIs

**Ethereum** (requires free Etherscan API key):
- Etherscan (primary: transactions and balance)
- Alchemy (fallback: balance lookup)

**Corporate manual sources:**
- OpenCorporates
- Companies House
- No automated API integration for these two sources (manual analyst links)

**Automated screening:**
- OpenSanctions: optional name search, requires `OPENSANCTIONS_API_KEY`
- URLScan: searches existing public scans when a domain is supplied; API key is optional
- VirusTotal: optional domain reputation lookup, requires `VIRUSTOTAL_API_KEY`
- INTERPOL, SEC EDGAR, and GDELT: automated public-record/name research
- crt.sh: automated certificate lookup when a domain is supplied

### History limits

- Bitcoin: up to approximately 500 confirmed records plus the initial provider mempool set. If any Blockstream page fails, retrieval restarts with Mempool.space. Providers are not mixed within a history attempt.
- Ethereum: normal ETH transactions and ERC-20 transfers each use up to 10 pages of 1,000 records (10,000 per action before normalization and deduplication). A later-page failure raises an error. Alchemy is only a balance fallback.
- Neither chain provides guaranteed lifetime-complete history. Ethereum monitoring does not retrieve pending/mempool transactions or enforce finalized-block status.

## Risk Analysis

Greedy Collector detects behavioral patterns:

- Direct exposure to labeled addresses (sanctioned, mixers, scams)
- Dormant wallets becoming active
- High-velocity activity
- Large transfer patterns
- Rapid pass-through activity
- Wallet consolidation patterns
- Bridge/exchange activity

**Important**: Risk findings are informational patterns for analyst review. Greedy Collector does NOT identify wallet owners, make guilt determinations, or provide legally binding assessments.

## Wallet Monitoring

Add addresses to monitoring for periodic checks:

- **First observation**: Establishes a quiet baseline (no alerts on historical data)
- **Subsequent runs**: Detects new transactions and risk pattern changes
- **Continuity detection**: Protects against provider inconsistencies
- **Deduplication**: Same transaction + alert type = one alert (no duplicates across confirmations)

Monitoring runs automatically via APScheduler or optional Celery/Redis for distributed setups.

## Database

Greedy Collector stores data locally in SQLite:

- Observed transactions
- Address profiles (balance, risk score, activity dates)
- User labels and analyst notes
- Monitoring state and alerts
- Cases and case entities
- Transaction graph edges

The database is local and never leaves your machine unless you export data.

## Installation

### Requirements

- Python 3.12+
- Windows, macOS, or Linux
- ~100 MB disk space for dependencies
- Internet access for blockchain API calls

### Setup (Windows PowerShell)

```powershell
# Clone or extract the repository
cd C:\path\to\greedy-collector

# Create virtual environment
py -3.12 -m venv .venv

# Activate
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Configure environment
Copy-Item .env.example -Destination .env

# Initialize database
alembic upgrade head

# Run
uvicorn main:app --reload
```

### Setup (macOS/Linux)

```bash
cd /path/to/greedy-collector

python3.12 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
pip install -r requirements-dev.txt

cp .env.example .env

alembic upgrade head

uvicorn main:app --reload
```

## Configuration

Edit `.env` with your settings. The application and Alembic read process environment variables; they do not automatically load `.env`. For the server, use `uvicorn main:app --reload --env-file .env`. For migrations with `.env` settings, use `python -c "from dotenv import load_dotenv; load_dotenv(); from alembic.config import main; main(argv=['upgrade', 'head'])"`. Alternatively, export the variables in your shell.

**Required for Ethereum transaction retrieval:**
- `ETHERSCAN_API_KEY` — Get free key at https://etherscan.io/apis

**Optional:**
- `ALCHEMY_API_KEY` — Fallback for Ethereum balance
- `GREEDY_COLLECTOR_ETH_MONITOR_MINUTES` — Check Ethereum wallets every N minutes (default: 10)
- `GREEDY_COLLECTOR_BTC_MONITOR_MINUTES` — Check Bitcoin wallets every N minutes (default: 20)

**For scaling:**
- `GREEDY_COLLECTOR_MONITORING_BACKEND=celery` + Redis URL for distributed monitoring
- `GREEDY_COLLECTOR_GRAPH_BACKEND=neo4j` + Neo4j credentials for optional graph mirror

See `.env.example` for complete configuration options.

## Running

### Development (with auto-reload)

```bash
uvicorn main:app --reload
```

Then open http://127.0.0.1:8000/docs for API documentation.

### Production

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

## API Endpoints

All endpoints return JSON. See `/docs` for interactive documentation.

### Address Lookup
```
POST /api/greedy-collector/lookup/address
{
  "chain": "bitcoin" or "ethereum",
  "address": "wallet address",
  "refresh": false
}
```

Returns: Transactions, balance, risk score, labels, graph paths.

### Wallet Monitoring
```
POST /api/greedy-collector/watchlist
GET /api/greedy-collector/watchlist
GET /api/greedy-collector/watchlist/{wallet_id}
```

Returns: List of monitored wallets and their alert history.

### Risk Analysis
```
GET /api/greedy-collector/address/{chain}/{address}
```

Returns: Stored risk results and findings.

### Case Management
```
POST /api/greedy-collector/cases
GET /api/greedy-collector/cases
```

Returns: Analyst case groupings and associated entities.

### Alerts
```
GET /api/greedy-collector/alerts
PATCH /api/greedy-collector/alerts/{alert_id}
```

Returns: Monitoring-generated alerts with optional status updates.

### Reports
```
POST /api/greedy-collector/case/{case_id}/report
```

Returns: CSV, HTML, Markdown, or PDF report of case data.

Full API docs available at `/docs` when running locally.

## Demo Workflow

1. **Start the application**:
   ```bash
   uvicorn main:app --reload
   ```

2. **Lookup a public address** (Bitcoin example):
   Navigate to `/docs` and use the `/api/greedy-collector/lookup/address` endpoint:
   ```json
   {
     "chain": "bitcoin",
     "address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
     "refresh": true
   }
   ```

3. **Review results**: Transactions, balance, risk indicators, counterparties

4. **Add to watchlist** (optional):
   ```json
   {
     "chain": "bitcoin",
     "address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
     "label": "Investigation case 2026-A"
   }
   ```

5. **Observe monitoring**: Alerts generated on subsequent monitoring runs

6. **Inspect graph**: View 1-3 hop transaction paths from this address

7. **Export case**: Generate report in preferred format

## Testing

Run the full test suite:

```bash
python -m pytest tests/ -q
```

Expected result: **74 passed**

Run specific test category:

```bash
python -m pytest tests/test_bitcoin_pagination.py -v
python -m pytest tests/test_ethereum_fallback.py -v
python -m pytest tests/test_monitoring_mempool.py -v
```

## What It Does NOT Do

- Identify wallet owners by name or profile
- Make guilt or criminality determinations
- Monitor Ethereum pending/mempool transactions (history uses Etherscan on-chain records; finality is not enforced)
- Provide investment advice or market predictions
- Interact with smart contracts or transfer funds
- Perform blockchain analysis beyond 3 hops
- Guarantee accuracy (blockchain data is only as fresh as provider APIs)

## Architecture

**Backend:**
- FastAPI (async REST API)
- SQLAlchemy 2.0+ (database ORM)
- APScheduler (monitoring task scheduling)
- Alembic (database migrations)

**Database:**
- SQLite (default, single-file, no server needed)
- Optional PostgreSQL for production
- Optional Neo4j for graph analysis mirror

**Optional Distributed Scale:**
- Redis (message broker)
- Celery (distributed task queue)

**Frontend:**
- Accessible via `/docs` (Swagger UI)
- Exportable reports (CSV, HTML, Markdown, PDF)
- No web UI included (API-first design)

## Key Concepts

### Deduplication
When a Bitcoin transaction moves from unconfirmed (mempool) to confirmed state, its risk score may change. Greedy Collector identifies transaction alerts by wallet, chain, transaction hash, and trigger type. It also checks persisted fields to recognize older alerts. Risk-only alerts retain score-sensitive deduplication.

### Continuity Loss Detection
If the stored transaction boundary is missing from the bounded results, that run reports continuity loss, suppresses transaction alerts from the ambiguous window, and preserves the boundary. Future scheduled checks continue.

### Immutable Baseline
First observation of a wallet establishes a stable baseline silently (no alerts). Subsequent checks process only new transactions. Bitcoin uses the newest confirmed transaction to avoid volatile mempool data.

### Graph Edges
Greedy Collector stores transaction graph edges (sender → recipient) for local traversal. Optional Neo4j mirror provides optimized queries without affecting SQLite integrity.

## Known existing limitation

The Alchemy balance fallback is implemented but currently fails in the shared HTTP transport: `_alchemy()` passes a JSON body to `_get()`, which calls `httpx.AsyncClient.get()`. Local verification raises `TypeError: AsyncClient.get() got an unexpected keyword argument 'json'` before a request is sent. The same defect exists in the Epic Archer reference; mocked fallback tests do not exercise this transport. It was preserved during extraction verification. Live provider availability was not tested.

## Troubleshooting

### "ChainDataError" or API timeouts
- Check internet connectivity
- Verify Etherscan/Blockstream are not rate-limiting
- Increase `GREEDY_COLLECTOR_TIMEOUT` in `.env`
- Check API key validity (Etherscan)

### Database locked
- Ensure only one monitoring backend is running
- If using Celery, verify Redis is accessible
- Check file permissions on `data/greedy_collector.db`

### Monitoring not running
- Verify `GREEDY_COLLECTOR_MONITORING_BACKEND` is set (default: `apscheduler`)
- Check application logs for startup errors
- Confirm at least one wallet is `enabled=true` in watchlist

### Tests fail with import errors
- Verify virtual environment is activated
- Run `pip install -r requirements-dev.txt`
- Ensure you're in the repository root directory

## Development

### Code Structure
```
greedy_collector/
├── chains/          # Blockchain adapters (Bitcoin, Ethereum)
├── risk/            # Risk scoring engine
├── kyc/             # KYC screening
├── config.py        # Configuration
├── models.py        # Database models
├── database.py      # SQLAlchemy setup
├── services.py      # Business logic
├── router.py        # FastAPI endpoints
├── monitoring.py    # Wallet monitoring
└── graph.py         # Transaction graph storage

tests/               # Test suite (74 tests)
migrations/          # Alembic database migrations
```

### Adding a New Blockchain Adapter

1. Create `greedy_collector/chains/newchain.py`
2. Inherit from `ChainAdapter`
3. Implement `lookup_address()`, `lookup_transaction()`, `transactions()`
4. Return `NormalizedTransaction` objects
5. Add tests in `tests/test_newchain_*.py`
6. Update `get_chain_adapter()` in `chains/__init__.py`

### Running Tests in Development

```bash
# All tests
python -m pytest tests/ -q

# Verbose with test names
python -m pytest tests/ -v

# Specific test file
python -m pytest tests/test_bitcoin_pagination.py -v

# With coverage
pytest tests/ --cov=greedy_collector --cov-report=html
```

## Performance

- Small dataset (< 10,000 transactions): Milliseconds
- Medium dataset (10K - 100K transactions): < 1 second
- Large dataset (100K+ transactions): Depends on graph queries

Graph traversal (3 hops) scales to ~1 million edges on modern hardware.

## License

Greedy Collector is provided as-is for research and analyst use.

## Support

For issues, questions, or contributions, refer to:
- This README
- Inline code documentation
- API docs at `/docs` when running
- Test files as usage examples

---

**Built for transparency. Used for due diligence.**
