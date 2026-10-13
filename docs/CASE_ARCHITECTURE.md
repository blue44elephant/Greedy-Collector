# Cases and Reporting — V1

Cases are analyst-controlled local investigation containers. They never initiate
blockchain collection, recursive Discovery, rescoring or identity inference.
Runtime uses actual stored records and configured providers; synthetic material
is restricted to automated tests.

## Capability audit

The pre-change matrix is in [CASE_CAPABILITY_AUDIT.md](CASE_CAPABILITY_AUDIT.md).
CASE-2 closes lifecycle, note revision, attachment integrity, timeline and report
history gaps. It retains existing analytical services and exact historical pins.
Structured findings, collaboration, import archives and AI narratives are outside
V1. Analyst summary and notes retain human conclusions and next actions.

## Identity and lifecycle

Case UUIDs survive rename. Status is Open, Paused or Closed; archive is an
independent timestamp so restore retains the prior status. Archive preserves
references, analytical pins, notes, attachments, reports and timeline. Archived
Cases are hidden from default lists and included by explicit filter. Archive
does not lock or delete content.

There is no permanent Case or note deletion API. Shared Attribution evidence,
captures, OFAC snapshots, normalized transactions and Discovery observations
are never deleted by Case lifecycle operations.

Case title, description, summary and archive/status updates require
`expected_version`. Notes have their own version. Stale edits fail with HTTP
409. SQLite writer transactions and SQLAlchemy version predicates prevent lost
writes. Content additions update Case revision/time; generating a report records
activity without changing analytical Case state. Reads create no timeline noise.

## Live references and historical pins

Wallet/transaction links are navigation references. They do not claim lifetime
coverage. Chain and canonical identifier define identity; display spelling is
retained separately. The same EVM text on Ethereum and Base is distinct.
Duplicate chain-scoped wallet references are rejected. Transactions retain an
event key, source wallet context and a saved normalized event snapshot when
available. If multiple stored events share a hash, an event key is required.
Provider transaction results expose a separate Add to Case action for each event.

For compatibility, adding a wallet copies its latest **stored versioned** risk
assessment if available. This is historical risk, not a live risk calculation.
An explicit Pin stored risk assessment action can retain later saved assessments.
Unversioned legacy risk is not represented as a verified new-model pin.
Label references preserve their current saved label assertion at addition.

| Material | Historical boundary |
|---|---|
| Risk | Full model/score/tier/components/overrides, OFAC references, coverage and calculated time |
| Sanctions | Screening record, listing/match state, exact snapshot ID/hash, associations/programs and captured time |
| Attribution | Exact entity/claim versions, assessment/rationale and link inventory; immutable evidence and source provenance |
| Discovery | Terminal run definition, providers/source outcomes, observations/results/reviews and fingerprint |
| Broad Discovery | Existing bounded snapshot including candidates/reviews, grouping, cache, partial/truncated state and fingerprint |
| Capture | Capture ID, URLs, retrieval/body hash/type, wallet literal presence, selected excerpt, review and origin |
| Technical cluster | Exact version, members, common-input evidence, exclusions and review-required state |
| Fund Flow | Immutable run with algorithm/parameters, paths/capacities, fingerprint, cutoff, truncation and UTXO provenance |

Later live changes never replace Case pins. Current navigation is explicitly
labeled separately from View pinned snapshot. Case Attribution may compare
current state with historical state; reports contain historical state only.
Report generation does not read current claim/link versions to replace pin data.

## Notes, attachments and timeline

Note edits/archive/restore preserve earlier text and version in append-only
events. Notes order by created time then ID. Cases order deterministically by
the selected sort field then ID. Search is local and literal over titles and
stored reference/pin metadata; no external search infrastructure is used.

Attachment storage is `data/greedy_collector_cases/<case-id>/`. Backend-generated
UUID filenames prevent replacement even when original names repeat. Metadata
retains original filename, sanitized name, MIME, size, SHA-256, added time and
analyst note. Paths, Windows drive names and traversal are rejected, including
raw multipart filenames that parsers otherwise reduce to a basename. Maximum
size is 20 MiB.

Downloads recheck path confinement and hash, force attachment disposition and
application/octet-stream, and apply nosniff/sandbox headers. Arbitrary HTML or
executable attachments are never previewed or launched. New attachments with
missing/changed bytes fail report generation. Replacement is another upload.

The timeline records creation, Case edits, references, explicit pins, notes,
attachments, report generation and archive/restore. It orders by time then
stable event ID. Analytical pin services join the same ORM transaction, so a
failed pin rolls back both material and its event. Events, Case references,
sanctions pins and reports have ORM and SQLite update/delete/replace protection.

## Immutable reports

Four formats share one sanitized historical state: Markdown, HTML, JSON and
PDF. Sections appear only for present material, except Case details, report
metadata and the general analytical disclaimer. Provenance remains with each
material section and a metadata appendix identifies the output.

Report generation obtains one SQLite writer snapshot, validates references and
attachments, captures historical analytical content, renders bytes and persists
the output/event atomically. Each output has its own UUID, format, generated time,
SHA-256, state fingerprint, generator version `case-2.0`, and schema version 2.
The state fingerprint is SHA-256 of the canonical JSON of the **sanitized exact
state used**, excluding report history and generation events. Repeated generation
without content changes can share a state fingerprint while producing different
report IDs and byte hashes.

The byte hash cannot include itself in the hashed output. It is exposed in
report history and `X-Content-SHA256`. JSON embeds report/schema metadata and
preserves typed pin IDs, model versions, timestamps and fingerprints.

The compatibility `GET /reports/{case-id}?format=...` is an explicit generation
command and now stores a new output. `GET /cases/{case-id}/reports` lists history;
`GET /cases/{case-id}/reports/{report-id}` downloads the original immutable bytes
and verifies their hash. These reads do not regenerate reports or add events.
Title changes never influence generated filenames.

Source/analyst text is literal in Markdown, escaped in self-contained HTML, and
escaped/wrapped into page-splittable PDF paragraphs. PDF uses an installed Unicode
font or ReportLab's bundled Vera; unsupported glyphs appear as explicit
`[U+XXXX]` code points instead of missing squares. Original Unicode is retained
in UTF-8 formats. Long hashes/URLs wrap and page footers identify report/page.
Credentials, credential-bearing URL parameters and internal paths are sanitized
before export and fingerprinting. No source scripts or remote assets are embedded.

Reports retain conditional limitations: bounded/provider-limited history,
UTXO allocation, technical cluster not equal to ownership, Discovery/source
statement not equal to identity, deterministic risk not equal to probability,
historical OFAC semantics, and opaque-chain observation-only coverage when
relevant. Attribution is a scoped analytic claim, never automatic ownership.

## Migration and legacy data

Revision `20261012_02_case_history` follows
`20261012_01_risk_labels_v3`. It adds Case/note revisions and lifecycle fields,
reference added time, and immutable event/report tables. Existing Case creation
events use their known created time. Existing note updated time starts at its
known creation time. Previously unrecorded reference added times and attachment
hashes remain explicitly unavailable; the migration does not invent provenance
or read old attachment files.

Downgrade refuses to discard report or mutation history. The migration is
explicit; startup does not upgrade existing columns or create the new history
tables. Testing upgrades only isolated temporary databases. No configured user
database was inspected or migrated during CASE-2.

V1 integrity limits: this is local application/SQLite immutability, not a digital
signature or protection against an operator replacing the database itself.
Restrictive-origin Attribution evidence remains subject to existing export rules.
