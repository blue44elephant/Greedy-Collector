# Explicit Public Source Capture (OSINT-2B)

Broad Discovery retains search-provider metadata. **Capture Public Source** is a
separate, explicit retrieval of the selected observation's URL. Press the action,
read the confirmation, then confirm one capture. Opening results/history, reviewing,
promoting or pinning captures never issues source requests. Capture again creates
a new immutable record. No scheduler, crawler or automatic candidate/link pivots exist.

## Network boundary

Only public HTTP/HTTPS on ports 80/443 is supported; HTTPS is preferred when the
source supplies it. The server chooses the stored observation URL: clients cannot
supply arbitrary URLs, headers, transport settings, credentials or cookies.
Strict parsing rejects credentials, sensitive URL material, ambiguous/unsupported
schemes, local hostnames and .onion before DNS. All DNS answers must be globally
routable unicast addresses. Loopback, private, link-local, reserved, unspecified,
multicast and known address-translation/tunnel forms are rejected, including cloud
metadata ranges. A mixed public/private DNS answer is blocked.

The TCP connection is pinned to a validated numeric address, while the original
Host header and TLS SNI/certificate hostname are preserved. This prevents a second
hostname lookup from bypassing the initial validation (DNS rebinding). TLS
certificate verification stays enabled. See the documented
[HTTPX SNI extension](https://www.python-httpx.org/advanced/extensions/#sni_hostname).
Every redirect is parsed, resolved and validated again; at most five are followed.
A redirect to a blocked destination records a safe reason without credential-bearing
Location text. Ambient proxies are disabled. Each hop uses a fresh client so
Set-Cookie cannot carry into the next request. No Authorization, browser state,
login, form submission, JavaScript, CAPTCHA handling or anti-bot bypass is used.
The identifiable User-Agent is `GreedyCollector/1 PublicSourceCapture`.

Connect timeout: **5 seconds**; per-operation timeout: **10 seconds**; overall
DNS/retrieval deadline: **20 seconds**. Response data streams in 64 KiB chunks and
is rejected beyond **5 MiB**. Oversized declared lengths fail before reading the
body. Only `text/html` and `text/plain` are accepted. `Accept-Encoding: identity`
is requested; compressed/binary/unsupported responses are rejected, not expanded
without bounds. Only status 200 is a successful capture. Authentication-required,
rate-limit, HTTP, DNS, timeout, redirect and parsing failures have separate fixed
messages; upstream exceptions/stack traces are not shown.

## Evidence and extraction

A completed attempt has an immutable record with the originating Discovery
observation/result, provider/query and exact chain/wallet context, requested/final
URLs, safe redirects, retrieval timestamp, HTTP/MIME/length metadata, byte count,
SHA-256, title, readable text, terminal status, truncation/failure and implementation
version. The complete bounded raw body is retained as an **inert SQLite BLOB** for
successful captures. It is never served as HTML or offered by a raw-content URL.
Failed/oversized bodies are not retained and do not receive a complete-body hash.
HTML extraction uses the standard parser, preserves source-derived text, and omits
scripts, styles, noscript, templates, embedded executables and hidden elements.
No linked assets, images, fonts, stylesheets or media are fetched. No LLM rewriting.
Readable text is rendered with textContent, never innerHTML or an iframe.

`wallet_present_in_capture` checks the canonical whole wallet token in captured
readable text with the existing chain case rules. Absence is retained and explained,
not treated as evidence that a historical mention never existed. Captures do not
mutate the provider observation or its exact-match classification. Textual EVM
wallets remain associated with the originating chain. Presence never proves ownership.

Later successful captures compare body SHA-256 with the previous successful capture
of the normalized requested URL: FIRST_CAPTURE, UNCHANGED or CHANGED. Failures are
NOT_COMPARED. No explanation of the change or automatic alert is inferred. Old
body/text/hash/status/provenance are protected by database immutability triggers.
Reviews are separate append-only Unreviewed/Relevant/Irrelevant decisions with notes
and stale-version checks. Capture history is paginated. The Discovery graph displays
up to five latest captures per source result, states the retained count, and links
to full history. The blockchain transaction graph is unchanged.

## Review, Attribution and Cases

Inspect the full capture and record a review. Copy a **literal excerpt of at most
8,000 characters** from readable text. Promote as evidence opens the existing
Attribution handoff: select an existing claim for the exact wallet and chain, choose
stance/directness/rationale, preview and explicitly confirm. Successful captures
must be Relevant; wallet-absent captures permit contextual links only. The server
checks the excerpt against immutable text and rejects stale review/claim versions.
Evidence preserves capture ID, URL/time/hash, wallet state, originating provider/search
provenance, excerpt and review note with origin `public_osint`. Entire pages are not
copied into claims; capture material stays separate. No Entity or Claim is created
automatically, and claim assessments are not automatically changed.

Pin capture to Case explicitly selects a Case and the relevant excerpt. The pin
contains a historical capture/review/provenance snapshot. Later captures or reviews
cannot overwrite it. Case details display it separately from search observations.
Capturing has no effect on risk, Labels, monitoring, watchlists, clusters or fund flow.

## Storage, setup and limitations

Migration `20260929_01_public_source_capture` follows `20260928_01` and adds three
focused tables plus indexes/immutability guards. It creates no captures or runtime
sample data. Apply migrations explicitly using the documented operator workflow;
implementation/tests never migrate the configured user database. Downgrade refuses
to discard retained captures. No new dependency is required.

Public accessibility does **not** grant unrestricted copying or redistribution rights.
Operators must have an applicable lawful/contractual basis for retaining source
material and follow their retention policies. This feature preserves selected analyst
evidence; it is not a website mirror. No automatic deletion of immutable evidence is
implemented in this increment.

Onion references may remain inert in Manual Source Observation, but capture never
resolves .onion, launches Tor or accesses hidden services. Authenticated/private
content and paywall bypass are unsupported. A 200 login page can only be retained as
the returned public page; GC does not authenticate or infer access to protected content.
PDF/documents, XHTML, compression decoding, screenshots/browser capture and recursive
pivots remain deferred. Automated verification uses mocked DNS/HTTP and temporary
SQLite only; no public internet resources are fetched by tests.
