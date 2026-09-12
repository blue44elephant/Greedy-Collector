# AT-3: Attribution workspace

The eighth workspace, **Attribution — Evidence-backed entity claims**, is a vanilla JavaScript frontend for the existing [AT-2 manual API](ATTRIBUTION_AT2.md). It reads and writes real SQLite attribution records. No automatic attribution, source retrieval, provider requests, seeded entities, or example evidence exists in production runtime.

## Layout and navigation

The workspace has two primary views: **Claims** and **Entities**. Evidence and read-only history are inspected within claim detail; a modest paginated capture picker supports evidence reuse. There are no separate database-table CRUD tabs. Opening other workspaces retains Attribution's local view/form state. Attribution initially reads claims only when its navigation button is selected; it performs no requests on application initialization.

Claims list subject/address, chain, relationship, attributed entity, last assessment, review-needed state, archive state and update time. The full address is available through focus/tooltip and always shown in detail. A claim's address remains distinct from its entity name. Current-page entity descriptors are fetched by ID; the complete entity database is never preloaded.

Both lists use real AT-2 filtering and offset pagination (20 rows per page). Entity pickers, linked-evidence groups, evidence reuse, review checklists, related claims and histories use 10 rows per page. Previous/Next controls show server totals and stop at next_offset=null. No filtering of an incomplete client-side dataset is used.

Claim filters: chain, subject address (requires chain), relationship, assessment, explicitly selected entity, and include archived claims/entities. Entity filters: canonical-name substring, type and include archived. Include archived means active plus archived, matching the API. Entity names are not assumed unique: selection shows type and ID.

## Entity workflow

Create a canonical descriptor with type, optional aliases (one per line) and description. Creating a descriptor creates no wallet association. Entity detail shows aliases, description, type, version, actor, timestamps, archive state and ID. Related wallet claims are separately paginated, including archived claims.

**Edit descriptor** sends the full permitted descriptor component and its loaded expected_version, with a required reason. Omitted values are not silently retained contrary to AT-2 replacement semantics: the form is prefilled with the current complete descriptor. Backend review invalidations are displayed when affected claims are next retrieved.

**Create claim for entity** selects this existing entity in the manual claim form. It does not create the claim until the analyst submits it. The entity picker can also select an existing descriptor; **Create a new entity** leads to the entity form. No entity is generated from another workspace's text.

## Claim workflow

The analyst chooses an existing/new entity, wallet subject type, Bitcoin/Ethereum chain, public address, one of the three supported relationships, scope/rationale, and optional date bounds. Relationships are only operated_by, controlled_by, publicly_declared_by. Backend validation and normalization remain authoritative; the browser makes no wallet lookup or resolver/provider request.

Creation starts unassessed with review required, as AT-1 specifies. Claim detail shows the normalized full subject, chain, relationship, entity/type, last assessment and rationale, version, review/archive states, actors, timestamps and date bounds. **Revise scope** sends only the allowed scope component, expected_version and reason.

A duplicate 409 with a validated returned existing ID displays a specific duplicate-claim message and **Open existing claim**. The browser never guesses an ID. Duplicate evidence linking has its own message explaining that the existing link should be inspected/restored.

## Assessment and contradictions

**Review assessment** reads the current claim version and opens a separately paginated checklist of all active links. The analyst must explicitly mark each reviewed link. Contradicting links have an additional unchecked **I acknowledge this contradiction** checkbox, including on later pages. Selections persist while paging; no select-all or automatic acknowledgement exists.

The form offers exactly Unassessed, Possible, Supported, Strongly supported and Rejected. It requires a rationale and sends the version loaded for that review, explicit reviewed_link_ids and explicit acknowledged_contradictions. Written contradiction discussion is required when current contradictions exist. Source verification is available for strongly supported assessment. The server remains authoritative for support/directness/reliability/source-verification prerequisites and stale link/version checks.

The frontend prevents submission until every active link is marked reviewed and every contradiction is acknowledged; it does not infer that opening a record means it was read. It does not continuously refresh the version underneath an in-progress assessment. Material changes preserve the last category and visibly show **Review required** until a successful explicit assessment clears that state.

Assessments are always text, not green/red truth indicators. Strongly supported does not mean legal proof, ownership, or verified identity. Actor strings such as local_analyst and attribution.review_invalidation describe operations; GC does not currently authenticate individual analysts.

## Evidence capture, inspection and reuse

Three sections label **Supporting evidence**, **Contradicting evidence** and **Contextual evidence**. Each card has an explicit stance badge, source/origin, directness, link rationale, capture time and active/withdrawn state. The text distinctions remain visible without color. Full summary, excerpt, citation, reliability rationale, actor, dates, fingerprint and captured JSON can be inspected on demand through **Inspect capture**.

**Capture evidence** uses the atomic capture-and-link endpoint. The analyst explicitly chooses stance and directness and writes a link rationale. The form exposes the six permitted manual capture types, public_osint/analyst_added origins, title, source name/URL/locator, summary/excerpt, publication/observation dates, analyst note and reliability/rationale. Optional structured metadata and source catalog/origin-group fields are under an advanced disclosure; common workflows require no raw JSON.

Restricted origins and future Label/Research snapshot capture types are not ingestion options. If a historical restricted-origin capture is returned, the UI identifies its origin and does not render detailed captured material. No evidence URL is fetched or previewed. Public citation links use target=_blank, rel="noopener noreferrer" and no-referrer; malformed/credential-bearing links are not made clickable. All rendered material uses textContent/DOM nodes rather than HTML injection.

**Link existing evidence** opens a bounded evidence library with origin/source-catalog filters, source, title, capture time and explicit capture selection. The submitted link has its own stance, directness and rationale. Reuse creates no new copy of the capture and does not imply independent corroboration.

## Immutability, withdrawal and replacement

There is no evidence-content edit or delete control and no event mutation control. **Change link relevance** edits only the relation's stance/directness/rationale with the parent claim version and a reason.

**Withdraw link** removes the material from the claim's active evidence without deleting the capture or association. **Include withdrawn links** makes retained links available for inspection and restoration. Withdraw/restore requires a reason and a separate lifecycle confirmation checkbox; it preserves history and flags review through the existing backend.

**Replace evidence** clearly identifies the original capture, explains that it remains in history, and presents an empty new-capture form. It uses the tested AT-2 replacement command to create a new immutable record, withdraw the old claim link, create the replacement link and append history atomically. It never presents replacement as an edit in place; other claims reusing the original remain unchanged.

## History and archive/restore

Claim and entity histories are explicit read-only paginated sections, showing sequence/type, timestamp, actor, reason and expandable before/after/event material. The browser exposes no event creation, editing or deletion action.

Entity and claim archive/restore forms require a reason and explicit acknowledgement that records/history are retained. They send the loaded expected_version. Archived records remain discoverable through filters. Entity archive affects the default visibility of its claims according to AT-1; restoration and material changes require review. No hard delete exists.

## Concurrency and errors

Version conflicts display **This record changed since you loaded it. Reload before applying your update.** No automatic retry or overwrite occurs. **Reload** deliberately retrieves fresh state and closes stale edit forms; the analyst must reconsider and submit a new command. Duplicate claims and duplicate links use distinct messages when the server identifies them.

404, 422, storage 503, network failures, malformed responses and unexpected failures display bounded local messages. Only a small allowlist of fixed assessment-prerequisite messages may be shown verbatim. Raw SQL, stack traces, exception paths, arbitrary response text and credential values are never displayed as errors.

## Unmigrated database

An attribution schema-unavailable 503 shows **Attribution storage is not initialized for this database** and explains that an administrator must prepare the database explicitly. Other workspaces remain operational. Reload retries a read only. There is no browser migration command, automatic stamp/upgrade, or database initialization action. The user's real database was not migrated by AT-3; see [AT-1 deployment guidance](ATTRIBUTION_AT1.md).

## Limitations and phase boundaries

Attribution is evidence-backed analyst assessment. It is not automatic wallet-owner discovery. There are no Wallet/Graph handoffs or overlays (AT-4), Label/Research evidence handoffs (AT-5), Case/report integration (AT-6), clustering (separately gated AT-7), ENS attribution, external providers, risk changes or authenticated analyst accounts. Addresses are entered manually. Claim assessment does not change risk or create labels/research records.

Pagination is offset-based and reflects current records, not an immutable search snapshot. Changes between requests can shift pages; optimistic version/link checks protect mutations. API limits, including the maximum reviewed-link ID count, remain authoritative. The frontend does not infer truth from record counts or hide later-page contradictions to satisfy a review.

## Verification

Starting baseline: 424/424 pytest tests and all seven existing browser workflows passed. New lightweight tests cover navigation/assets, allowed wording/controls, local-only request paths, explicit version/acknowledgement fields and schema-unavailable responses. Existing lifecycle tests now expect eight workspaces while retaining their schema/no-seed assertions. No AT-1/AT-2 mutation or safety assertions were removed.

Run:

```powershell
python -m pytest tests/ -q
node tests/browser_smoke.cjs
node tests/browser_attribution.cjs
node tests/browser_attribution.cjs unmigrated
git diff --check
```

The attribution harness creates a separate temporary SQLite database, explicitly migrates only its migrated test variant to 20260912_01, and starts the normal scheduler/application lifecycle. Browser-created and API fixture records remain test-only. External HTTP is blocked, request paths are audited, non-attribution row counts are checked unchanged, and screenshots are saved under the printed temporary artifact directory. The unmigrated variant verifies the safe 503 message and continued absence of attribution tables after Reload.

The browser workflow exercises descriptor creation/editing and real stale conflict, normalized claim creation/duplicate recovery, all three stances, immutable capture inspection, explicit contradiction acknowledgement (including later pages), successful assessment, event paging, withdrawal/restoration/replacement, original retention, claim/entity archival/restoration, capture reuse, duplicate links, filters/pagination and sanitized failures. Existing seven-workspace browser workflows remain separate; only their navigation assertion was updated to include the eighth workspace.

No dependencies or migrations were added. Migration head remains 20260912_01. Final verification counts are recorded in the completion report.
