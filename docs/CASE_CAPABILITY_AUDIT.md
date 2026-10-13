# CASE-2 pre-change capability audit

Baseline trusted: Python 1865; frontend 81; migration 20261012_01_risk_labels_v3.

| Capability | Existing behavior | Completion gap |
|---|---|---|
| Identity/lifecycle | UUID, title, description, Open status, timestamps; create/read/list | Rename, controlled status/archive/restore, stale-write checks, summary, search/sort |
| Wallet/transaction/label/graph/alerts | Generic CaseEntity references and assigned alerts; wallet copies stored risk | Chain identity, event context, explicit risk pin and reference semantics |
| Attribution | Server-owned versioned claim/entity/link snapshot; immutable evidence; current comparison | Preserve historical inventory in report snapshot; timeline integration |
| Sanctions | Separate snapshot/hash screening pins | Report integration and timeline |
| Broad Discovery | Immutable run/result/review snapshot and fingerprint | Non-broad run pin, organized overview |
| Public captures | Immutable capture/hash/excerpt/review pin | All-format reporting integration |
| Clusters / Fund Flow | Exact version/run pins; independent source data | Case navigation/counts/timeline |
| Notes | Append only with created time | Safe edit/archive and retained revisions |
| Attachments | Sanitized filename, local file, minimal metadata | Duplicate overwrite, traversal, size/hash, download confinement |
| Reports | Markdown, HTML, JSON, PDF, risk and Attribution provenance | Persistent immutable history, hash, state fingerprint, complete sections, safe literal Markdown, PDF Unicode |
| History | Analytical snapshot protections only | Case events, Case/note revisions, report immutability |
| Deletion | No Case deletion endpoint | Retain archive-only lifecycle; never delete shared source material |

Implementation boundary: Case storage/services/routes/UI and report rendering. Existing analysis/provider logic remains authoritative. Focused migration for Case/note fields and immutable event/report tables. No configured database access. Structured findings and portable archive/import are outside declared V1; analyst summary/notes retain human decisions.
