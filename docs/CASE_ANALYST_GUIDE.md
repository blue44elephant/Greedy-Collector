# Case analyst guide

1. Open **Cases** and create a titled investigation. Keep its stable Case ID.
   Search titles, wallet references and saved entity names; optionally include
   archived Cases. Sort by updated, created, title or status.
2. Add chain-scoped wallet/transaction references. A transaction with several
   stored events needs its exact event key. Transaction result cards offer
   event-specific Add to Case actions.
3. Maintain the **analyst-authored summary**: scope, key findings, unresolved
   questions, limitations and next actions. Greedy Collector writes no conclusions.
4. Pin analytical results deliberately from their workspaces. Adding a wallet
   also retains the latest saved versioned risk when available. Pin stored risk
   assessment captures later stored assessments without requesting providers.
5. Distinguish **LIVE REFERENCE** from **PINNED HISTORICAL SNAPSHOT**. Live navigation
   opens the source object's current state. Historical pins retain earlier risk,
   sanctions, claim/evidence, Discovery/capture, cluster and Fund Flow material.
   A changed live claim can coexist with a supported historical pin.
6. Add notes/decisions. Editing increments note version and retains earlier text
   in the timeline. Archive notes instead of deleting them. If an edit conflicts,
   reload before saving; do not overwrite another revision.
7. Upload attachments up to 20 MiB. Original names remain visible, but unique
   server filenames prevent overwriting earlier files. Hashes identify saved
   bytes. Download is offered; active preview and executable launch are not.
8. Review Case counts, grouped references and timeline. Activity reflects writes
   and explicit pins, not navigation. An empty Case explains what can be added.
9. Choose Markdown, HTML, JSON or PDF and **Download report**. Each generation
   records a new immutable report ID, hash, fingerprint, timestamp and generator.
   Use **Immutable report history** to download earlier bytes. Later live source
   changes never update historical pins or old reports.
10. Rename or set Open/Paused/Closed as needed. **Archive case** hides it from the
    default list without deleting material. Include archived Cases to find it;
    **Restore case** preserves its earlier status, references and report history.

Reports are bounded investigative records, not complete lifetime histories or
proof of guilt/ownership. Risk is a deterministic indicator, clusters are
technical groupings, and source statements are evidence to assess. OFAC state
is the state of the captured local snapshot, not a new live rescreen.

For provenance and explicit migration requirements see
[CASE_ARCHITECTURE.md](CASE_ARCHITECTURE.md). HTML/JSON/Markdown preserve original
UTF-8; PDF writes explicit Unicode code points if a font lacks a glyph.
