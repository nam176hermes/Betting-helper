# Contents, provenance and exclusions

| Location | Contents |
| --- | --- |
| Repository root: `src/`, `tools/`, `tests/`, `extension/`, `contracts/`, `config/`, `docs/`, `vendor/`, registries and lockfiles | Complete 737-file committed runtime snapshot, including inherited Part A/bootstrap code and tracked generated assets |
| `authoring/` | Complete 360-file authoring snapshot at `959439f492b6bd385bfdce57443733a00044aebc`: generators, tests, plan inputs, source ZIPs, normative pack, ownership and controller contracts |
| `original-part-b-plan/` | Recovered supplied PB-00..PB-24 plan, task cards, reference material, original manifest and validation records |
| `evidence/latest-audit/` | Detailed first-live audit, command/exit records, focused tests and synthetic bug diagnostics |
| `evidence/r24/` | Qualification and campaign records, measured durations, full repair/environment aggregate records, selected logs, mock/platform results and review intake assessment |
| `evidence/reviews-r24/` | Exact historical A/B HOLD results and workspace attestations; these are not fresh approval |
| `evidence/sealed-pack-reference/` | Existing sealed pack checksum and public seal attestation; the host pack itself is not in this export |
| `delivery/` | Previously generated Part B extension distribution ZIP and checksum; packaging does not install or authorize it |
| `workspace-tools/` | Local coordinator tools and workflow/implementation documentation used around this workspace |
| `local-generated-output.patch` | Thirteen uncommitted generated-file differences from the source workspace; deliberately not applied |
| `SOURCE_STATE.json`, `SOURCE_PROVENANCE.json` | Source identities, path mapping, per-file original hashes and explicit export limitations |
| `EXPORT_MANIFEST.json`, `verify_export.py` | Complete exported-file integrity inventory and an offline stdlib verifier |
| `ai-packs/` | Repomix reading aids, split by topic/size; not a substitute for raw source or complete test execution |

The runtime history descends from the existing GitHub main
`d4055839e596fc52f0e0df175a6733a64b8fffc1`; no orphan baseline or history rewrite is
used. The authoring snapshot is flattened into this review branch without a nested
Git repository. Its original commit/tree identity is recorded separately.

## Intentionally excluded

- API keys, environment files, Windows Credential Manager data, host private
  signing keys, cookies, browser profiles, session storage, private live configs,
  authenticated provider/operator captures, and real runtime databases.
- `.git` administration from the downloadable archive; dependency installations,
  caches, toolchain binaries and disposable test/browser workspaces.
- The approximately 142 MB host sealed pack and its materialized reviewer
  environments. Their identities are preserved, but this export is not a
  self-contained replacement for the host's full custody/evidence filesystem.
- Historical duplicate runtime/authoring worktrees, backups and abandoned branch
  snapshots. The current runtime already contains the relevant inherited code.
  The older dirty `discovery-runtime-v6.3.6` LV branch is not the Part B candidate.
- The complete local execution-state dump, because it mixes historical aliases,
  local task/session metadata and current fields. The published source-state
  summary and latest audit identify the actual snapshot and remaining blockers.

Original evidence is copied byte-for-byte when included; original files, receipts,
profiles and workspaces remain untouched. References to excluded artifacts are
still references, not proof that those artifacts were delivered or revalidated.

Public schema examples, test sentinels and Chrome extension **public** keys remain
in source. They are not API credentials. A redacted secret-scan summary documents
classified false positives; no credential values are published in that summary.

## Cost and readiness review focus

Trace `tools/launch_part_b.py` → `tools/run_with_api_football_key.py` →
`src/moj_discovery/live_preflight_batched.py` →
`tools/issue_review_launch_authorization.py` before recommending verification reuse.
The measured campaign took approximately 4h28 before reviewer time/user waits.
Do not equate that with the intrinsic duration of a normal match-start operation.

Investigate existing verified-context objects and recheck helpers first. Preserve
scope, bytes, expiry, revocation, boot identity and consent checks. The current
contract only permits explicitly scoped reuse; broader reuse needs a versioned
contract change through the authoring generator, not a hand edit of vendor files.
