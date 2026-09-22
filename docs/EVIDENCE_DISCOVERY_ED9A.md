# ED-9A — Manual Source Observation Capture

Analysts can manually preserve where a wallet address was observed, including source context and provenance. This is a historical analyst assertion, not source verification or an ownership claim.

## Workflow and API

From a successfully resolved Wallet, choose **Record source observation**. Discovery also offers the action after **Check subject**. Opening the form performs only local subject resolution and reads stored history/capabilities. Enter the source material, **Preview observation**, inspect it, then **Confirm capture**. Preview stores nothing.

- `POST /api/greedy-collector/discovery/manual-source/preview`
- `POST /api/greedy-collector/discovery/manual-source/capture`

The capture request contains the original `capture` input and the server's `expected_preview_fingerprint`. The server recomputes and compares the preview. It chooses all persisted identities, fingerprints and timestamps. Same-origin, bounded JSON and safe error handling use the existing Discovery router.

`wallet.manual_source_observation` / `manual_source` is **Manual, FREE_LOCAL, No network**. It is a dedicated capture binding, not a provider executor or a selectable `/plan` pivot. `wallet.manual_exact_web` remains a separate navigation-only action.

## Material and validation

Required: one canonical Bitcoin/Ethereum wallet, source type, `observed_at`, quoted `context` (1–4000 characters), and `analyst_note` (1–2000). A safe source URL or stable source reference is required. Optional: title (255), service name (200), alias (200), source reference (200), existing Case ID and up to five attachment references. The form exposes one attachment reference; the API accepts five. Discovery's 16 KiB sanitized material bound also applies.

Source types: `webpage`, `marketplace_listing`, `marketplace_vendor_page`, `forum_post`, `document`, `other`. These are descriptive provenance, not categories of legality or risk. Aliases remain metadata; no Entity is inferred.

Existing wallet normalization remains authoritative: Ethereum is canonicalized, Bitcoin Base58 spelling is preserved, Bech32 is normalized. Transaction hashes, WalletConnect URIs, arbitrary hex and ENS names cannot become capture wallet roots.

`observed_at` is analyst supplied, must include an offset, is normalized to UTC and may be historical. Times more than five minutes ahead of the server are rejected. The UI interprets its datetime field in the analyst browser's local timezone and submits ISO-8601 UTC. `captured_at` is the immutable observation's server-created timestamp, distinct from observed time. The existing observation API exposes `created_at`; retrieval accounting internally uses the capture clock, with the UI labeling manual material as captured.

## URL safety and onion handling

HTTP(S) references are validated locally; there is **no DNS lookup, HTTP request, source-existence check, scraping, Tor integration, login or browser automation**. URL userinfo, credential/session parameters, controls, unsafe schemes, local/private hosts and oversized values are rejected. Safe entered spelling is retained alongside the canonical URL. No cookie/header import or local-path ingestion is supported. Context and metadata reject identifiable credentials, pasted authentication headers and local paths; analysts must still avoid entering private material.

Syntactically valid 56-character base32 `.onion` hostnames are accepted as inert references. They are not checked for existence or cryptographic validity. The UI displays **Onion source — GC does not fetch/open this source.** and **Copy source URL**, with no anchor or Tor launch. Ordinary HTTP(S) links may be opened explicitly with `noopener noreferrer` and no referrer.

## Persistence and migration

The existing URL/annotation subjects, DiscoveryRun, source accounting, Result, Observation and RunItem records are reused. URL-less sources use the explicit `manual-source` annotation namespace and a deterministic source-reference identity.

Exact relationship: **source --mentions_wallet--> blockchain_address**. Wallet-root investigation does not reverse the predicate. The old predicate vocabulary could not express this incoming literal mention, so one focused revision **20260922_01**, parent **20260916_01**, adds `mentions_wallet` to the existing Result CHECK constraint. No new tables/columns or seed data. Old migrations are unchanged. Capture checks the actual constraint plus shipped revision ancestry. Merely stamping the version cannot enable capture. Older Discovery features remain usable at their existing revisions.

Explicit operator migration is required for capture. Application startup does not migrate storage, and ED-9A development/testing does not migrate the configured user database. Downgrade refuses to discard retained manual-source results.

Capture is one SQLite transaction: canonical subject, completed manual run, source with zero attempts/units, result, immutable observation, run membership and optional Case reference. Failure rolls back all new material. No provider execution is fabricated.

## History, duplicate handling and review

Substantive material is deterministically fingerprinted; server capture times, random IDs, UI ordering and Case association are excluded. Attachment ordering is canonicalized. Repeated identical capture reuses the existing observation/run and original capture time. Repeated Case association is idempotent. A changed context/title/alias/note/attachment creates new immutable material. Changed source URL/reference changes source identity; old observations remain retained.

New captures begin Unreviewed. A change under the same result marks current material as requiring renewed review. Relevant/Irrelevant decisions use the existing review path. Previously reviewed historical material remains explicitly selectable, without authorizing changed material. SQL/ORM immutability protections are retained.

## Attachments: reference/hash only

Existing Case uploads use mutable caller-selected filenames without bounded-size/hash guarantees. Reusing that storage safely would require an unrelated redesign. ED-9A therefore implements the authorized **reference/hash-only** option, with no upload endpoint or new file store.

Each reference has a stable exhibit reference, analyst-supplied SHA-256, optional original filename, MIME and byte size. Paths/unsafe filenames and malformed hashes are rejected. References are copied into the immutable observation and promotion snapshot; replacement is new material. GC does **not** receive file bytes, compute or verify their hashes, guarantee external file retention, preview, OCR or upload anything externally. The server capture timestamp applies to the recorded metadata.

## Graph and Attribution

Typed Discovery graph adds `source_page` presentation cards in a deterministic upper lane. Stable node IDs sort into square-grid columns, 410 units apart and rows 190 units apart, above prior lanes by 260 units. Existing code/label/ENS coordinates remain stable. Source arrows point toward the focus wallet. Selection exposes source metadata, context, note, observed/captured times, attachment hashes and literal predicate. Existing pagination, fit, pan and zoom remain.

Historical graphs select their run's immutable observation. Review and promotion counts remain current analytic status. A source node is a presentation of a result; canonical source subjects may be shared across wallet captures, but separate wallet-root graphs are not merged. Two wallets at one source never imply common ownership or a cluster.

Relevant manual observations use the existing ED-6 **Use as attribution evidence** workflow. Claim selection, Supports/Contradicts/Context, directness, rationale and confirmation remain explicit. Origin is **`analyst_added`**. The immutable evidence snapshot preserves wallet, source type/URL/reference/title, service/alias, context, note, observed/captured times and attachment references/hashes. This records what the analyst observed; it does not claim an alias owns a wallet.

## Cases and boundaries

An optional existing Case receives a `discovery_observation` reference, created atomically with capture. Case detail has a compact **Source observations** section and **Open Discovery observation**. Case references do not accept an identity claim. No Case creation/status change, claim inclusion or report regeneration occurs. Report generation remains unchanged; a generic explicitly associated entity reference may appear under existing report behavior, without automatically expanding Discovery history.

No Entity, Claim, Label, risk score, assessment, monitoring wallet, alert rule or research request is automatically created. Capture and promotion add zero risk points. The optional Monitoring handoff is deferred; use the existing separate Monitoring flow explicitly.

## Verification and isolation

Pytest sets `PYTHON_DOTENV_DISABLED=1` and a unique temporary SQLite startup URL in `tests/conftest.py` before application imports. A SQLAlchemy pre-connect guard rejects non-SQLite connections and SQLite files outside temporary storage. Existing per-test temporary/in-memory fixtures remain in use. A regression test attempts a forbidden repository database connection and verifies the file is never opened/created.

Capture API tests block HTTP clients, socket connection and DNS entry points. Migration tests use isolated SQLite to compare schema, every retained row and immutability triggers. The optional `node tests/browser_discovery.cjs manual_source` test uses a temporary database, test-only wallet providers and blocked external transports. It verifies Wallet → preview → capture → graph → Relevant review → ED-6 Context promotion, Case navigation, inert onion references and all nine workspaces. Runtime contains no synthetic source material. No new dependency is required.
