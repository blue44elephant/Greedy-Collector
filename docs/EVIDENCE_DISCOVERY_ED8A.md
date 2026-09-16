# ED-8A: ENS primary-name Discovery prerequisite review

Historical status: **ED8A_ENS_NORMALIZATION_DEPENDENCY_BLOCKER**.

ED-8A1 update (2026-09-17): the separately implemented and verified [local reference-library bridge](EVIDENCE_DISCOVERY_ED8A1.md) resolves the normalization prerequisite when Node and the pinned local dependency are installed. The rest of ED-8A remains unimplemented. The findings below preserve the original stop decision; resume from RPC/executor integration, using the bridge and checking that a returned primary name already equals its normalized form.

Reviewed 2026-09-16/17. Implementation stopped at the task's explicit normalization gate. ENS Discovery is **not implemented or enabled**. This document records verified assumptions and a continuation checkpoint, not completed functionality.

## Official contract verified

The [Universal Resolver guide](https://docs.ens.domains/resolvers/universal/) recommends the DAO-owned proxy **`0xeEeEEEeE14D718C2B47D9923Deab1335E144EeEe`**. Its interface is `reverse(bytes lookupAddress, uint256 coinType)`, returning `(string primary, address resolver, address reverseResolver)`. This is the documented address, not a deployment independently checked through live RPC. Recheck before implementation.

[ENSIP-19](https://docs.ens.domains/ensip/19/) specifies **coin type 60** for Ethereum Mainnet. A primary name must already be normalized and resolve forward to the queried address. No L2/default-EVM primary-name support is intended here.

[ENSIP-23](https://docs.ens.domains/ensip/23/) documents built-in forward verification, `ReverseAddressMismatch` on mismatch, and an empty name with zero forward resolver when no primary is set. CCIP-Read can be required during either phase. The specification is marked draft; the interface guide and upstream implementation were also inspected.

## Why reverse success is not normalization proof

ENSIP-23 explicitly treats an unnormalized returned name and resolver as invalid. ENSIP-19 requires clients to reject an unnormalized reverse name. These rules do not establish that a successful EVM return guarantees normalization.

In [AbstractUniversalResolver](https://github.com/ensdomains/ens-contracts/blob/staging/contracts/universalResolver/AbstractUniversalResolver.sol), `reverseNameCallback` decodes the name and passes its literal bytes through `NameCoder.encode`. `reverseAddressCallback` compares the forward address against the query. [NameCoder.encode](https://github.com/ensdomains/ens-contracts/blob/staging/contracts/utils/NameCoder.sol) performs DNS framing and label-size checks, not ENSIP-15 Unicode validation. This source inspection supports the conclusion that GC must separately establish that the returned string is already normalized.

The eventual boundary must reject a name if normalization would change it. Attaching the original forward verification to a changed name would verify different material. A redundant forward call does not solve the missing normalization implementation.

## Dependency decision and blocker

[ENSIP-15](https://docs.ens.domains/ensip/15/) currently specifies **Unicode 17.0.0**. Lowercasing, IDNA/UTS-46, generic NFC and ED-8A0's canonical-input checks do not implement that specification.

The Python implementation linked by the reference project, [namehash/ens-normalize-python](https://github.com/namehash/ens-normalize-python), was archived on **2026-08-05**. Its README advertises Unicode **16.0** compatibility. [PyPI release 3.0.10](https://pypi.org/project/ens-normalize/3.0.10/) lists Python 3.14 in its classifiers; this does not resolve the independent maintenance and current-specification failures. No package was installed or executed, and Python 3.14 compatibility was not independently tested.

The maintained [JavaScript reference](https://github.com/adraffy/ens-normalize.js) advertises Unicode 17.0.0 and full validation-suite coverage. A compliant JavaScript implementation therefore exists. However, a supported Python 3.14 backend integration was not established: this application has no production JavaScript execution boundary. A server-side JS runtime/embedding needs a separate dependency assessment; it was not silently substituted for the requested Python assessment. Browser-only normalization cannot protect server-side persistence.

No suitable maintained, current-spec Python implementation was verified. Following the explicit stop condition, **no ENS executor, partial normalizer, runtime, ABI dependency or Web3 framework was added**. Resumption requires a compliant maintained backend integration verified against current official vectors on Python 3.14. This is a scoped dependency blocker, not a claim that ENS normalization is impossible in other languages.

## ENSv2 boundary

The [official overview](https://docs.ens.domains/ensv2/overview/) describes deployment on Sepolia. The [2026-08-12 beta announcement](https://ens.domains/blog/post/ensv2-beta-public-testing) places mainnet after public testing without a fixed launch date. The [2026-02-06 update](https://ens.domains/blog/post/ens-staying-on-ethereum) supersedes the old Namechain/L2 plan: ENSv2 is intended for Ethereum L1. Use the documented Universal Resolver proxy as the compatibility boundary, not ENSv2-only interfaces.

## Repository inspection and continuation

The architecture-approved transform ID is **`wallet.ens_binding`**. Reuse existing Discovery planning, capabilities, executors, quota, cancellation, cache, immutable history and run-source state.

The Ethereum adapter already constructs generic Alchemy JSON-RPC POSTs. `.env` uses `override=False`; process environment wins. `ALCHEMY_API_KEY` stays server-side. No credential or RPC URL setting was added. Reuse requires bounded `eth_call` handling and safe errors: the current helper exposes provider error text internally, and the shared HTTP transport follows redirects. Do not persist raw RPC responses or credential URLs. There is no vetted existing CCIP client; future offchain paths must return `ccip_read_unsupported` without fetching resolver-controlled URLs.

After resolving the normalization gate:

- Register an explicitly selected Ethereum-only remote pivot using existing LIMITED_FREE accounting and an initial one-hour cache TTL; Refresh bypasses cache.
- Obtain UR forward verification without another forward lookup. Empty primary is zero-result success. Mismatch produces no endpoint, graph node or promotion candidate and a safe diagnostic. Bound and classify remaining resolver/RPC failures.
- Persist `ens_name / ethereum / canonical name --resolves_to--> blockchain_address / ethereum / wallet`, with `name_service_record`, existing `technical_verified` metadata, verification method, resolver addresses, source versions and retrieval time. No new enum or migration is planned.
- ED-8A1 now handles protocol-valid format characters through the authoritative normalizer. Use its raw-name integration helper; the low-level canonical-input function still does not normalize ordinary strings.
- Preserve historical observations and run membership when names change. Require Relevant review and ED-6 promotion with explicit claim, stance, directness and rationale; use public_osint origin.
- Add actual result presentation and deterministic ENS graph cards without moving existing node groups. ENS remains output-only. Opening Discovery makes no RPC call.
- Complete the requested mocked protocol, semantic, cache, graph, promotion and isolated browser tests. No ownership inference, text-record collection, name enumeration, or automatic Entities, Claims, Labels, risk or Cases.

## Verification and checkpoint

- Baseline `python -m pytest tests/ -q`: **1075 passed**, 57 warnings, 326.87 seconds, exit 0.
- Added tests: **0**; runtime code is unchanged. No second suite run was needed after documentation-only edits.
- `alembic heads`: **20260916_01 (head)**. No migration added or old migration changed.
- Frontend/browser/workspace checks were not rerun after the explicit pre-implementation stop. No ENS browser success is claimed.
- No live ENS/Ethereum call was made. Web access was for documentation/source research; tests used existing isolated fixtures.
- No production ENS data, credentials, real-database inspection/migration or automatic commit was introduced. Epic Archer was not modified.
- Changes are this document and a README status link. Resume at the normalization gate, not from an assumed implemented transform.

Verdict: **ED8A_ENS_PRIMARY_NAME_DISCOVERY_INCOMPLETE**.
