# Greedy Collector

Greedy Collector is a standalone application for inspecting public Bitcoin and Ethereum
wallet activity. It retrieves records from configured providers, stores normalized results
in SQLite, applies deterministic risk rules, and provides Wallet, Graph, Monitoring, Alerts, Cases, and Labels workspaces.
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

Unified search automatically resolves supported blockchain identifiers:
Bitcoin addresses (forms accepted by the existing adapter), Ethereum addresses,
bare 64-hex Bitcoin transaction IDs, and `0x` + 64-hex Ethereum transaction hashes.
`0x` + 40-hex is an Ethereum address. Paste an identifier and press **Search** or Enter.
The local `POST /api/greedy-collector/resolve` endpoint classifies syntax without provider
requests. Unknown values produce a supported-types message and no lookup request.
Support can be extended later; other blockchains and naming systems are not implemented.

Addresses dispatch to the existing `/lookup/address` API; transaction hashes use
`/lookup/tx`. Transaction results show only returned normalized fields and allow explicit
wallet investigation. Transaction lookup itself does not store a wallet graph.
Wallet results retain exact decimal balances, activity, risk/evidence, counterparties,
and provenance. **View stored** reads profile, transactions, and risk through the existing
address GET endpoints, without claiming they are live. **Open graph** carries the selected
wallet into the Graph workspace. Provider requirements remain unchanged.

### Graph

Graphs use the existing stored endpoint with `hops=1`, `2`, or `3`. A deterministic layout
places returned focus entities first, then groups nodes by minimum undirected hop depth
from the focus solely for visualization. Stable parent ordering and address tie-breaks
keep placement repeatable. Each depth uses non-overlapping cards, with at most 12 rows
before wrapping into additional columns. Labels are bounded visually; full labels and
addresses remain accessible. Disconnected returned nodes receive their own group.

Blue cards identify focus; amber outlines identify selection. Curved arrows preserve
direction. Parallel records with the same ordered source/target share one visual connection;
select it to inspect every underlying transaction separately, without summing token amounts.
Reverse directions remain separate. Select a node for details and **Investigate wallet**
to return through unified search. Selection alone makes no provider request.

Fit, focus centering, reset, pan, and zoom operate within a fixed viewport. Large graphs
start centered on focus; all returned nodes and records remain available. The expandable
complete transaction table also retains records whose endpoints cannot be positioned.
This is a view of stored relationships, not complete blockchain coverage, ownership
inference, or automatic crawling. Bitcoin relationships remain simplified endpoints.

### Monitoring

Add a public Bitcoin or Ethereum address without first looking it up. Edit its label,
notes, priority, enabled state, or an optional case selected from stored cases. Duplicate addresses return
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

### Alerts

The global Alerts workspace lists actual stored monitoring alerts, newest first. Filter
by All, New, Reviewed, Dismissed, or Escalated using the existing status-filtered API.
Select a record to inspect its explanation, transaction fields, case reference, and notes.
Save review status and analyst notes through the existing PATCH endpoint; returning to
New is supported. No alert deletion is exposed.

Explicit actions investigate a wallet or transaction through unified search, or open the
wallet's stored graph. Selecting an alert itself makes no provider request. Risk-only
alerts may have no transaction hash, counterparty, or amount. Severity and review status
are indicators/workflow states, not proof of wrongdoing. First-run monitoring is silent:
absence of alerts does not mean a wallet was never checked, and historical activity is
not automatically turned into alerts. The current alert API is not paginated.

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

## Cases

The Cases workspace organizes real, analyst-selected investigation references in the local database. Create a case, attach wallet/transaction/label/graph references, and add analyst notes. Wallet, transaction, and selected graph-wallet results provide **Add to case**, with an explicit existing-case choice. References do not imply identity or ownership and do not automatically collect more data.

Monitoring offers a dropdown of stored cases. A watch's case assignment applies to alerts generated thereafter; it does not retroactively move existing alerts. Associated alerts can open their case or the Alerts review workspace.

Uploaded attachments are stored locally. The browser adds a unique filename prefix to avoid collisions; direct API uploads retain existing filename semantics. The current API provides metadata/references, not attachment downloads or active previews. Do not upload private keys or provider credentials.

Download reports as **Markdown, HTML, JSON, or PDF** using the existing report backend. HTML is downloaded, never injected into the application. Reports summarize current stored case material (case, entity references, alerts, notes); they do not automatically expand every wallet's complete blockchain history or attachment contents. No case deletion or multi-user identity is provided.

## Risk interpretation and calibration

Wallet risk is a deterministic investigative indicator, not a probability, proof of wrongdoing, or identification of real-world ownership. General activity is not inherently suspicious. Transaction count, fan-in/out, repeated counterparties, round/large asset amounts, short returned history, and Exchange/Bridge interactions now remain visible as **zero-point context**.

Known-risk counterparty exposure weighs more than volume: Sanctioned/Scam/Mixer contacts retain 40/30/25 points. Overlapping classifications of one counterparty use the strongest classification; each risk type contributes at most once. Independent types can contribute up to 95. Two-/three-hop stored proximity contributes at most 10/5, and adds no points on top of direct risky contact. Labels are sourced assertions requiring review, not automatically verified attribution. There is currently no direct wallet-attribution rule.

Weak chronological same-asset decreasing amounts, rapid sequences, and long observed gaps contribute 8/5/4, with a combined behavioral cap of 10. No current-clock dependency or second activity score is introduced. Overall cap remains 100; levels remain Low 0–30, Medium 31–70, High 71–100. A Low aggregate level does not negate a specific high-severity label finding.

The Wallet view shows applied category totals, raw points, caps, and per-finding adjustments. Applied points sum to the displayed score; evidence remains inspectable. Existing stored scores are preserved, and historical unversioned results are identified as lacking a category breakdown. Use a fresh lookup to apply the current model. No migration or background rescoring occurs.

See [the full risk audit](docs/RISK_CALIBRATION.md) for every original rule, overlap analysis, policy rationale, limitations, and the synthetic before/after matrix. Reproduce that matrix without provider calls using `python -m tests.risk_calibration_report`. These controls demonstrate scoring mechanics, not real-world statistical accuracy.

## Labels

The Labels workspace manages real local address annotations: **Exchange, Mixer, Bridge, Scam, Sanctioned, Unknown**. Create a manual label, filter by chain/type or label/source text, inspect provenance and confidence, investigate its wallet, open the stored graph, or add its existing label ID to a case. Wallet and Graph show stored names alongside addresses and link back to label details. Cases open the referenced label record.

Manual creation defaults to source **Manual analyst label** and confidence **0.7**. Confidence remains the stored 0–1 value; it is not the risk score. Sources remain visible, with HTTP(S) URLs safely linked. Bitcoin/Ethereum addresses are validated locally without provider calls. `any` preserves unvalidated address-scope semantics; it does not establish chain membership. Unsupported chains are rejected on new writes. Existing records are not migrated or rewritten.

CSV import requires `address,label,type,source,confidence`; `chain` is optional and defaults to `any`. Use UTF-8 `.csv` files. The full file is validated before writes. The result counts processed rows, including updates, not only newly created labels. Export downloads the existing backend CSV with `chain,address,label,type,source,confidence,last_updated`; JavaScript does not reconstruct or reimport the file.

The exact, case-sensitive storage key is `(chain,address,label,source)`. Manual duplicates return a conflict, including when only type/confidence differs. CSV import updates type/confidence and the timestamp for that key, retaining its ID. A different source creates a separate annotation. Duplicate CSV keys are processed in order, so the last row wins. There is no label edit/delete endpoint or automatic versioning in this increment.

The calibrated risk policy is unchanged: Sanctioned/Scam/Mixer counterparty contact has raw contributions of **40/30/25**, subject to existing overlap/category caps. Exchange/Bridge/Unknown contribute **0**. A label on the queried wallet is not a newly introduced attribution rule. Wallet risk cards show the label evidence and applied contribution; current annotations may differ from historical saved findings. Labels do not automatically rescore stored results or issue external research requests.

A label is an analyst/source annotation associated with an address, not proof of ownership or confirmed attribution. The separate Attribution workspace organizes explicit claims and immutable evidence; Labels offer an explicit Use as attribution evidence handoff; no automatic conversion occurs. No automatic attribution, sanctions ingestion, or sample labels are included here.

## Research — public records & screening

Research submits a **name**, optionally a **domain**, to the existing server-side screening engine. Only **Run research** makes provider requests; typing, changing workspaces, and opening match details do not rerun screening. Accepted API fields aliases, country, date of birth, and identifier are currently unused by adapters and are omitted from this form.

The capability panel reports automated/manual modes, actual inputs, and credential-configured booleans. Configuration is not a provider health check. Seven sources have automated adapters:

| Source | Input used | Credentials |
| --- | --- | --- |
| OpenSanctions | Name | `OPENSANCTIONS_API_KEY` required for this optional integration |
| INTERPOL Public Notices | Name | No API key |
| SEC EDGAR | Name | No API key; configured `SEC_USER_AGENT` request header |
| GDELT | Name | No API key |
| crt.sh | Domain | No API key |
| urlscan.io | Domain | `URLSCAN_API_KEY` optional; public mode otherwise |
| VirusTotal | Domain | `VIRUSTOTAL_API_KEY` required for this optional integration |

Without a domain, the three domain adapters are skipped, not reported as failed. Results separately show successfully checked sources, automated matches, unavailable sources, and manual links. A partial source failure preserves successful results. Missing credentials and provider failures are reported safely; credential values and raw exceptions are not displayed.

The 18 **manual-link-only** sources are OpenScreening, OFAC, UN Security Council Consolidated List, UK Sanctions List/OFSI, EU Sanctions Map, U.S. Consolidated Screening List, FIU-India, OpenCorporates, Companies House UK, Open Ownership Register, OCCRP Aleph, India MCA Master Data, GST Taxpayer Search, ICANN Lookup, ARIN RDAP/WHOIS, Google Search Operators, Google Alerts, and Local News/Court/Regulator Searches. Greedy Collector generates links; it has not queried those services. In particular, OpenCorporates and Companies House have no automated integration here. Links open in a new tab without opener/referrer access.

Inspect a match for its source, source URL, rationale, categories, review status, and expandable evidence. **Match score** is the engine's case-insensitive text similarity (`SequenceMatcher`, rounded to three decimals, 0–1). It is not identity probability, wallet risk, or domain safety. A domain compared to itself can score 1 regardless of reputation.

Analysts can persist **Unreviewed**, **Potential match**, **False positive**, or **Confirmed source match**. Confirming a source record does not establish wallet ownership. Research does not automatically create wallet labels, associate wallets, or infer attribution. Useful evidence is retained; credential-bearing fields are redacted before API output and new screening persistence.

Cases currently have no research-match entity type. Use **Open source** / **Copy result**, then explicitly add an analyst note in Cases; no automatic case association occurs. Previous research-run browsing is not currently exposed. Runs and reviews are stored in SQLite, but this page retains only the current result until reload/close. Copy material needed for investigation before closing. Existing stored runs are not rewritten.

The existing endpoints remain `GET /api/greedy-collector/kyc/sources`, `POST /api/greedy-collector/kyc/screen`, and `PATCH /api/greedy-collector/kyc/matches/{match_id}`. There are no new sources, migrations, attribution rules, or frontend dependencies. See [the complete source capability audit](docs/RESEARCH_CAPABILITIES.md) for every source's exact inputs, outputs, URL behavior, and failure handling. Research browser checks use only temporary SQLite state and test-only provider fixtures.

## Attribution � evidence-backed entity claims

The Attribution workspace provides paginated **Claims** and **Entities** views for explicit manual investigation. Create an entity descriptor, enter a public Bitcoin/Ethereum wallet claim, capture or reuse immutable evidence, and record an assessment after reviewing supporting, contradicting, and contextual material. Contradictions require explicit acknowledgement and discussion. History, version conflicts, archival, link withdrawal/restoration, and evidence replacement remain inspectable.

Attribution is evidence-backed analyst assessment. It is not automatic wallet-owner discovery. Creating attribution does not change risk or automatically derive claims from Labels, Research, blockchain activity, or Cases. No source URLs or external providers are queried by this workspace.

Attribution requires a database explicitly prepared through the existing migration **20260912_01**. If the schema is unavailable, the workspace displays an initialization message; it does not migrate or seed the database. Follow the existing migration guidance before preparing a legacy database. Other workspaces remain usable.

See [the Attribution workspace guide](docs/ATTRIBUTION_AT3.md) for workflows, evidence immutability, concurrency, limitations, and isolated browser verification.

## Wallet and Graph attribution (AT-4)

Wallet and selected Graph wallets show persisted claims, separate entities and relationships, assessments, review-required state, and evidence stance counts. Open an exact claim or explicitly create one with the public wallet subject prefilled; choose the entity, relationship, and rationale before saving. Summaries refresh on workspace return or manual refresh, with pagination and an archived/rejected toggle.

Graph offers an optional attribution overlay, off by default, for current assessed claims on the selected wallet and current summary page. Distinct entity nodes and claim arrows supplement the unchanged wallet/transaction graph; claims are not transactions or blockchain hops. No graph-wide attribution fetch, ownership inference, provider request, or automatic assessment is added. Attribution failures or an unmigrated database leave ordinary Wallet/Graph investigation usable.

See [AT-4 behavior, boundaries, and isolated verification](docs/ATTRIBUTION_AT4.md), including existing graph limitations. Labels/Research evidence handoffs are available through AT-5; Cases/report integration is available through AT-6 with explicit pinned references.

## Label and Research evidence handoffs (AT-5)

Use as attribution evidence opens a server-read preview of a selected Label or persisted automated Research match. Choose an existing claim or explicitly create one, select Supports/Contradicts/Context and directness, write a rationale, and confirm capture. Entity and relationship choices remain manual. Research does not supply an inferred wallet.

Captured evidence retains immutable sanitized source provenance. Later label edits or research review changes do not rewrite it. Identical repeat handoffs conflict; source or claim changes require renewed review. Source scores and review statuses do not become attribution assessments or risk points. No provider calls or automatic migration occur during handoff; Labels/Research remain usable without attribution storage.

See [AT-5 workflows, snapshot semantics, and verification](docs/ATTRIBUTION_AT5.md). Manual research links and unavailable-source notices are not eligible automated evidence. Cases/report integration is available through AT-6.

## Case attribution and reports (AT-6)

Cases can explicitly pin existing Attribution claims or entity descriptors. Use Add attribution in Cases or Add to case from Attribution. Choose the target and confirm; wallets, Labels and Research do not populate case attribution automatically. Duplicate references preserve the first pin.

Case detail separates pinned assessment/version from current assessment, review and archive state. Markdown, HTML, JSON and PDF reports retain pinned supporting, contradicting and contextual evidence, with historical/current withdrawal status and provenance. Later claim changes do not rewrite the pin or an already downloaded report. A newly generated export adds a fresh timestamp and current-state comparison.

No migration, report archive, repinning/removal workflow, provider request or risk change is introduced. Cases and reports remain usable when attribution storage is uninitialized. See [AT-6 pinning, report semantics and verification](docs/ATTRIBUTION_AT6.md).


## Discovery API foundation (ED-2)

Developer APIs under `/api/greedy-collector/discovery` provide local capabilities/planning, explicit bounded runs, stored history and review. Use one application worker. All production transforms remain unimplemented; no Discovery provider is queried and no Discovery workspace is available yet. Storage requires the existing explicit ED-1 migration (`20260913_01`); startup does not migrate it. See [ED-2 contracts, budgets, cancellation and limitations](docs/EVIDENCE_DISCOVERY_ED2.md). Existing workspaces remain unchanged.
