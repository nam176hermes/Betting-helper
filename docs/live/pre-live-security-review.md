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

No real provider/profile/security evidence has been accepted during implementation.
The Python tests that inject an internal verification seam exercise composition only;
they are synthetic tests and cannot stand in for a host review. Full Part A receipts
remain bound to their old bytes, and the final batch campaign must rerun affected
checks. Physical sleep/power-loss and real-account crash evidence remain separate.
