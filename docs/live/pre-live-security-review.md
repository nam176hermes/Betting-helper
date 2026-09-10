# Part B evidence admission and security review

The v2 preflight is implemented separately from legacy v1. Its decision function
does not contact a provider, open a browser, inspect credentials or consume an
intent. `key_present=True` means PRESENT_NOT_AUTHENTICATED. The evidence loader
reads only configured public artifact paths. Missing, synthetic, changed or expired
evidence leaves a named condition pending. No boolean or JSON PASS claim grants
an admitted run.

```bash
uv run --frozen --offline python tools/verify_part_b.py --profile security --output .local/part-b/security-candidate
uv run --frozen --offline python tools/live_preflight_batched.py --config config/live.local.json
```

The security command executes secret-entry/nonleakage, fixed provider HTTP,
wire-role/replay, profile and one-use intent tests, plus preflight denial tests.
Real HTTP transport uses one owned backend child for the complete DNS/TLS/header/
body operation, capped by the remaining run lease and ten-second attempt deadline.
The credential travels only over private stdin; child environment and argv contain
no key. WSL/Linux SIGALRM and the parent's deadline terminate only that child. Tests
exercise a real sleeping child and a real Python worker with an injected local HTTP
reply; these are not real provider probes. Live requests still reserve quota before
this worker is created, and the same backend lock permits only one attempt at a time.
It retains actual pytest case results, command exits and log hashes. This is
**SELF_ONLY**, never an independent security receipt. The mock profile additionally
compiles and executes TypeScript and requires PB-17's explicit acceptance inventory.
Empty, skipped or failed test results cannot become a PASS.

## Existing host review boundary

Real capture and live admission consume the repository's existing descendant v2
review authorization and execution receipt. The configured host public key, trust
epoch, boot binding, current candidate, isolated review context and signature are
verified through the existing owners. This implementation never initializes host
authority, reads its private key, signs a receipt or launches a review session.
The reviewer must be a real independent session under that host mechanism.

A private `part-b-review-evidence/v1` envelope contains exactly `scope`, `result`,
`authorization`, `receipt` and `schema_version`. The result is the existing closed
`DescendantCybersecurityReviewResult`, with all security verdicts YES, no blocking
finding and production authority NONE. Its nonblocking `PART-B-SCOPE` finding names
exactly one evidence ID: `sha256:` plus SHA-256 of the RFC8785 canonical scope.
The host-signed receipt binds that result. This uses the existing evidence-ID field;
vendor schemas and signatures are not extended or fabricated.

The CAPTURE_PROFILE scope contains `kind`, `source_tree_sha256`,
`capture_source_sha256`, canonical `profile_sha256`, exact `bindings`, `sample_refs`
(private relative path → file SHA-256), `expires_at` and `max_matches`. Actual
OBSERVED_REAL samples must match the admitted profile, fixture IDs and orientation.

The LIVE_SECURITY scope contains `kind`, `source_tree_sha256`, `config_sha256`,
`artifacts` (raw file hashes for provider/capture/profile/platform/offline),
`max_matches`, `expires_at` and `previous_scope_refs`. Stage one uses an empty
preceding-scope map; larger scopes additionally require the preceding actual run
verifier. Expiry is finite and no more than a day ahead. These private bundles are
external inputs, not files the implementation worker fills with approval claims.

Provider evidence retains its original full config/source hashes and its operational
provider configuration. Publishing evidence paths or enabling a reviewed final
config does not change the probe's HTTP/budget/fixture scope. Any provider option,
fixture, duration or capacity change requires a matching probe. This breaks the
probe → final evidence-path publication cycle without silently reinterpreting v1.
Platform observations bind the actual selected topology and current extension/tool
source; synthetic match data is appropriate for this isolated bridge check only.

The live launcher freshly loads the evidence, consumes the user's live intent once,
and binds the run, exact extension Origin, per-fixture streams and profile. Every
real provider attempt rechecks the consumed receipt, source and retained admission
artifacts, plus current host public trust/boot binding. Review authorization expiry
also bounds admission. An altered receiver Origin or stream cannot reuse the admission object.
The backend still enforces quota and expiry independently.

The private checkpoint distinguishes historical provider PASS from current
source-bound admission. No real operator profile or independent live security
review has been accepted.
The Python tests that inject an internal verification seam exercise composition only;
they are synthetic tests and cannot stand in for a host review. Full Part A receipts
remain bound to their old bytes, and the final batch campaign must rerun affected
checks. Physical sleep/power-loss and real-account crash evidence remain separate.

## First-sample tool scope

OPERATOR_DISCOVERY_TOOL uses the same existing external review verifier, without
requiring an accepted profile or prior normalized operator samples. Its closed
scope binds current source/capture/config hashes, one provider fixture, exact
operator URL, restricted selector map, user-supplied profile name, <=600 seconds,
zero provider attempts and finite expiry. This review approves a bounded read
operation, not the correctness of the eventual profile or participant orientation.
Missing actual mapping remains pending; synthetic selectors are not substituted.

The keyless terminal launcher checks review before prompting, then consumes its
one-use intent before opening the pinned loopback listener. The browser explicitly
selects its tab through the extension action; a fixed isolated reader returns
one unadmitted sample. Both sides reject extra fields and invalid scope/MACs.
Review is rechecked before plan delivery and before evidence persistence.
The sample result is never a live-wire MarketBook, CAPTURE_PROFILE review or
permission to poll providers. Tests with an injected review seam are SYNTHETIC
and cannot satisfy the real host review gate.

## Discovery tool repair candidate

Prior isolated source analysis on bf1ba38 found the selector bootstrap dependency,
hidden descendant text and unavailable discovery Stop. The repair adds a bounded
selected-region candidate map, rejects hidden descendants before text extraction,
and routes discovery cancellation outside the live command queue. Both mapped
and selector-based results remain unadmitted; no actual profile or fixture binding
is inferred. Synthetic Chrome/loopback tests exercise these seams and cannot grant
operator or host authority. Current commands, exits and hashes are in the private
execution checkpoint and candidate manifest.

Host review must assess the selected-region scope explicitly, including untrusted
page-controlled selection, root/selector limits, visibility limitations, cancellation
races and the unchanged consent/host-receipt verifier. Existing review-b.v2 config
still references the older v6.3.6 runtime and seal. A source candidate ZIP is not a
controller-sealed host pack. Do not repoint generated registries, reuse old receipts,
initialize a signer, or claim host launch eligibility from this implementation.
