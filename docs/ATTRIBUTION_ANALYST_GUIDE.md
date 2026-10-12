# Attribution / Evidence analyst guide

1. Open the chain-scoped wallet's Attribution panel, or search Entities by name or
   alias in Attribution. Names are not unique: inspect the ID before selecting.
2. Create a scoped `operated_by`, `controlled_by` or `publicly_declared_by` Claim
   for the explicitly selected Entity. Creating an Entity creates no wallet claim.
3. Capture a cited public record or analyst observation, reuse existing Evidence,
   or explicitly promote reviewed Discovery/public-capture material. Choose
   **Supports**, **Contradicts** or **Context**, directness and rationale yourself.
4. For server-captured sources, optionally describe reliability and give its
   rationale at promotion time. The default is Unassessed. Source reliability and
   wallet-string presence are not identity probability or claim assessment.
5. Review every active evidence link. Acknowledge every contradiction and discuss
   it. Supported needs assessed direct evidence; Strongly supported additionally
   needs reliable direct evidence and source-verification rationale. A stronger
   conclusion never hides contradictions.
6. Pin the Claim to a Case when relying on its current version. Reports distinguish
   the historical pin from later current state. Reassessment or Entity changes do
   not rewrite the Case pin; new material requires a new explicit review.

**Corrections and disagreement:** reject an unsupported Claim without deleting its
history. Archive a Claim when ceasing to advance it, recording the reason. Withdraw
or replace a wrong evidence link; replacement captures new immutable material.
Restore explicitly when appropriate. Old excerpts, hashes and events remain visible.
If a write returns Conflict, reload and inspect the current version before retrying.

**Provenance:** Inspect capture shows original source material, dates, hash, chosen
excerpt and subsystem references. Public Source Capture retains its original body
hash and URLs even if the source disappears or a later capture changes. OFAC shows
the exact stored source snapshot, raw identifier, programs and listing state at
observation. OFAC source association alone does not establish ownership; unresolved
or other-chain associations can only be Context. Label and Research source scores
remain source metadata.

**Declared V1 limits:** Claim subjects are supported wallets. Cluster/transaction /
domain subjects, fuzzy entity merging, source-derived alias objects and restricted
commercial/privileged ingestion are deferred. Analyst-added cluster context should
cite an exact cluster ID/version; it does not propagate to members or new versions.
No automated source polling or identity inference is performed. Entity alias changes
are descriptor revisions with before/after history, not automatic identity merges.

Use **Claim history** / **Entity history** for ordered transitions, reasons and local
actor metadata. **Investigate wallet** explicitly opens a real wallet lookup; source
links are explicit browser actions. Cases export Markdown, HTML, JSON and PDF with
historical relevance and source provenance. Actor `local_analyst` describes a local
operation; it is not an authenticated person's identity.
