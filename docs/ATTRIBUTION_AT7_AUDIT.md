# AT-7 capability audit (before production changes)

Baseline supplied by the operator: Python 1854/1854, frontend 77/77, Alembic
`20261012_01_risk_labels_v3`. No full baseline suite or operator database was opened.

| Capability | Actual delivered behavior | Audit conclusion |
|---|---|---|
| Entities | Local create/read, descriptor replacement, aliases, type, description, archive/restore; versioned before/after events and actor | Complete lifecycle. Same-name entities remain distinct; no fuzzy merge. Search currently ignores aliases: real gap. |
| Aliases | Literal strings in an analyst-authored entity descriptor, replaced under entity expected_version; old descriptors retained in immutable events | No standalone source-derived alias records. Removing an alias withdraws it from the current descriptor; its original descriptor/event remains. Source-derived aliases must remain evidence, not an identity merge. |
| Claims | Wallet-only subjects, canonical `(chain,address)`, explicit target entity, operated_by/controlled_by/publicly_declared_by; scope/time bounds, version and archive/restore | Complete declared V1 lifecycle. Rejected is an assessment; archive is lifecycle state. Claim withdrawal is represented by archive plus its reason, not a separate unsupported status. |
| Relationships | operated_by: operation; controlled_by: technical control; publicly_declared_by: explicit public declaration by the target | All are assertions requiring evidence and scope. owned_by/associated_with remain deferred. |
| Subject identity | Wallet-only transport and DB check; adapter normalization; same EVM text on different networks has distinct claim keys | No automatic chain, cluster, domain or transaction identity equivalence. Technical-cluster subjects are deferred; an exact cluster ID/version may be retained as contextual evidence for a wallet claim. |
| Evidence | Immutable source/excerpt/origin/reliability/metadata/hash, UTC capture actor/time; UPDATE/DELETE/replacement guards; reusable across claims | Manual Evidence cannot impersonate server-owned label/research/discovery captures. Restricted origins remain reserved and blocked on ingestion. |
| Claim evidence | supports/contradicts/context, directness and rationale; version-checked link/relevance/withdraw/restore/replacement; retained events | Duplicate link returns a safe conflict with existing ID, never an extra capture/link. Correction creates new evidence and withdraws the old link. |
| Assessments | Reviewed-link inventory required; contradictions explicitly acknowledged with conflict discussion; Supported requires assessed direct support, Strongly supported reliable direct support plus verification | Existing guards are adequate. Capture promotion fixes reliability as unassessed with no analyst selection, making a captured-source-only Supported workflow impossible: real gap. |
| Events/concurrency | SQLite serialized write transaction, expected versions, atomic event/state commits, sequence-ordered append-only history | Existing core tests cover stale writers, rollback, FK and enum failures. No redesign needed. |
| Discovery promotion | Explicit Relevant review and matching exact wallet/chain; immutable observation fingerprint; permanent per-observation/per-claim identity | No candidate automatically creates Entity/Claim. OFAC local observations are not in the eligible material matcher: real integration gap. |
| Public Source Capture | Literal excerpt, capture/body hash, URLs, times, search origin and review stored in promoted evidence; recapture creates new record | Promotion currently creates identical new evidence for each claim instead of reusing it: real gap. Old capture remains valid when a source disappears. |
| Label / Research | Explicit preview fingerprint + claim version + chosen relevance; server-read source snapshots | Preserved boundary; source confidence/match score does not become attribution probability. |
| OFAC | Local source observation has snapshot hash, entity/programs/raw identifier, match/listing state; no ownership claim creation | Add explicit reviewed promotion using the existing Discovery route. OFAC provenance currently falls through to GitHub UI: real gap. |
| Wallet/workspace | Entity and claim filters, grouped supports/contradicts/context, review checklist, archive/history, Case controls | Wording says Attributed entity before assessment; use Claimed entity. Add explicit wallet navigation. App's investigate-wallet event invokes an undefined function: confirmed navigation defect. |
| Cases | Server-owned immutable entity/claim/version/relevance pin, historical links, immutable evidence references; bounded batched report reads | Existing exact historical pin remains interpretable after entity/claim updates. No schema change needed. |
| Reports | All four formats preserve pinned relationship/assessment/rationale and grouped contradictions; JSON contains full capture metadata | Text/PDF representations omit evidence hash and structured capture/OFAC reference details: real reproducibility gap. |
| Graph | Separate typed Attribution edges, claims distinguished from transaction/Discovery edges; no proximity inference | Preserve; no topology or clustering changes. |
| Search/performance | Paginated local queries, batch capture summaries; entity descriptors fetched once per distinct bounded-page entity | No structural/index gap demonstrated. Alias lookup needs a local JSON search; no new search provider. |

Completion work is restricted to the listed gaps, focused regression coverage, and
current architecture/analyst documentation. No new inference engine, relationship,
claim subject type, restricted-origin ingestion, entity merge or migration is needed.
