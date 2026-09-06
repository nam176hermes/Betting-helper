# BH-R00 audit reproduction baseline

Recorded at `2026-09-06T06:09:59Z` on Linux WSL2 x86_64. This is a local,
offline diagnosis record. It is not a release receipt, a clean-checkout
qualification, or authority to run discovery.

## Checkout identity and scope

- Repository: `/home/thenam176/betting-helper/discovery-runtime-v6.3.6`
- Audited base and pre-write `HEAD`:
  `7cd7ab14652458608386d940bdc7764910044f6a`
- Base subject: `Hybrid Discovery v6.3.6 baseline`
- Branch: `repair/bh-audit-01-05`
- Remotes: none configured (`git remote -v` returned no entries, exit 0).
- Worktree topology: the repository is the only listed worktree and retains
  ordinary ancestor history; no new baseline or zero-parent repository was
  created.
- Pre-write worktree state was dirty only because BH-R01 work was already
  carried in:
  `M tools/inspect_restart_state.py` and
  `?? tests/repairs/test_restart_evidence_boundary.py`.
  BH-R00 did not edit, stage, or commit either path.
- BH-R00's only tracked deliverable is this file. No vendor, lock, source,
  audit-archive, runtime, browser, provider, remote, or production state was
  modified.

The audit ZIP is bound to the same full base commit. The later documentation
commit containing this record is expected to be a descendant of that base; it
does not change the audited code identity stated above.

## Pinned tools and local caches

| Item | Observed | Checkout pin / status |
| --- | --- | --- |
| Node | `v22.23.0` | matches `extension/package.json` |
| pnpm | `10.33.2` | matches `extension/package.json` |
| Python | `3.12.3` | matches `pyproject.toml` |
| uv | `0.11.7` | matches `pyproject.toml` |
| Python environment | `.venv` available | no dependency sync performed |
| Node dependencies | `extension/node_modules` available | no install performed |
| uv cache | `/home/thenam176/.cache/uv` | available |
| pnpm store | `/home/thenam176/.local/share/pnpm/store/v10` | available |
| repair cache root | `.local` | available |

All reproduction and focused verification commands used installed tools and
offline inputs. Nothing was downloaded.

## Governed source and external evidence inventory

The actual v6.3.6 source pack is available at
`/home/thenam176/betting-helper/hybrid-discovery-v6.3.6-authoring/pack`.
The controlling source map is
`docs/registries/normative-source-map.v1.json` under that pack, with SHA-256
`923dd50b94b159fb260ff9128457e87bb8125e673f57756fb9085c9222eb2da1`.
The vendored copy has the same hash. It declares
`normative-source-map/v1`, owner phase `MIG0`, 38 inherited entries, 68 plan
entries, and 2 graph overrides.

`uv run --frozen --offline python tools/sync_pack_assets.py --check --pack
/home/thenam176/betting-helper/hybrid-discovery-v6.3.6-authoring/pack` returned
exit 0. The inherited source DDL at
`docs/inherited/v6.2/sql/discovery-store-v1.sql` and the runtime vendor DDL at
`vendor/hybrid-discovery-v6.3.6/sql/discovery-store-v1.sql` both have SHA-256
`7a308df230f4492085f94daee9d11bc2a4e887e12b02d201a3faf4a1bd4f51a8`.
`schema-lock.json` records vendor tree SHA-256
`615da45ffdf210b10f64e1b7fad3e2cdc4e51625a445bcd485a2bbfe4ab6bf37`
and `production_authority: NONE`.

The configured external pytest path `../authoring-tests` is missing (and
`/home/thenam176/betting-helper/authoring-tests` is also missing). Therefore a
fresh execution of that external suite is unavailable and remains UNKNOWN;
its absence is not failure proof and is not an inferred PASS.

External evidence is present at
`/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6`:
60 top-level JSON files, a bootstrap receipt, and a pytest cache were observed.
`CANDIDATE_QUALIFICATION.json` declares
`candidate-qualification-receipt/v1`, 45 command IDs, and
`production_authority: NONE`. Those pre-existing receipts were inventoried
only. They were not replayed or accepted as current evidence for this dirty
repair worktree, and BH-R00 did not rewrite them.

## Audit archive integrity and isolated replay

Input:
`/tmp/bh-r01-work-package.XloqyN/betting-helper-next-implementation-plan/evidence/betting-helper-code-audit-7cd7ab1.zip`

- ZIP SHA-256 before and after replay:
  `9f2d506f1658fd545498482eeaf17c016b6aa570ca6605d48c9f5f95524d97d5`.
- Path-safety inspection found 9 unique, relative, NFC-normalized,
  non-symlink members, with no backslashes, absolute paths, dot components,
  or traversal components.
- All 8 files listed by `MANIFEST.json` matched their recorded SHA-256.
- Extraction/replay location: `/tmp/bh-r00-audit.lZpVGP/betting-helper-audit`.
  This is outside tracked source.
- `python3 reproduce.py` returned exit 0. Both contradictory synthetic
  expected states (`0/0/0` and `999999/999999/999999`) returned `PASS`; each
  run persisted only its readiness JSON. The direct comparator control
  rejected unequal states with `E_RESTART_STATE_MISMATCH`.
- `python3 reproduce_clock.py` returned exit 0. With raw timestamps producing
  RTT `999900` against limit `250000`, the unmodified vector returned
  `E_MAX_NETWORK_RTT_EXCEEDED`, while supplying derived overrides
  (`network_rtt_us=1`, interval `[100,101]`, uncertainty `0`) returned
  `ACCEPT`.

These results reproduce historical audited code excerpts whose Git blob IDs
were checked by the supplied scripts. They are not a full repository test,
browser test, power-loss proof, or live-runtime security test.

Equivalent offline probes against the current working tree produced:

- Restart counterexamples at both values were refused with
  `E_ACTUAL_STATE_READER_REQUIRED`. This is the carried-in, uncommitted BH-R01
  containment change, not proof that a real persistence/restart path exists.
- The clock override counterexample still returned `ACCEPT`; BH-AUDIT-04 is
  reproduced against the current module.
- The README command
  `uv run --frozen --offline python tools/run_command_registry.py --mode baseline`
  returned exit 2 because the only accepted mode is
  `candidate-qualification`.

## Finding classification

| Finding | Classification | Current evidence and boundary |
| --- | --- | --- |
| BH-AUDIT-01 | `REPRODUCED` at audited `HEAD`; `ALREADY_FIXED` only for immediate false-PASS containment in the carried-in BH-R01 worktree | The supplied historical replay accepted mutually contradictory expectations. The working-tree runner now requires an independent reader, but the shared store/ingest/restart implementation remains absent, so full durability is not verified. |
| BH-AUDIT-02 | `SOURCE_CONFIRMED` | The IndexedDB matrix invokes the compiled Node child through the shared crash runner, while the child contains a sentinel helper but its audited CLI path is readiness/hold orchestration. No real isolated extension-origin browser matrix was executed. |
| BH-AUDIT-03 | `SOURCE_CONFIRMED` | The clock runner inventories 65 IDs but executes only the golden mapping and `mapping_negative_vectors`, checks Python/TypeScript parity and accepted survivors, then reports aggregate zero skips. Full per-ID semantic dispatch was not executed. |
| BH-AUDIT-04 | `REPRODUCED` | Both the historical script and the current module accepted the same high-RTT timestamps after caller-supplied derived overrides. |
| BH-AUDIT-05 | `REPRODUCED` | README identifies a v6.2 REPO0 runtime although the governed vendor is v6.3.6; its documented `--mode baseline` command fails with exit 2; `pyproject.toml` contains an absolute cache path and missing external `../authoring-tests`. The exact v6.3.6 source pack itself is available and passed the read-only byte check. |
| BH-AUDIT-06 | `SOURCE_CONFIRMED` | Bootstrap reports `READY_TO_IMPLEMENT_DISCOVERY_PACK:NO` and `AUTHORIZED_PRODUCTION_PHASES:NONE`; store, ingest, provider, spool, and security paths still contain explicit not-implemented contracts. This is an intentional product-readiness gap, not evidence of a live defect or completed product. |

No finding is inferred from a missing host artifact. `SOURCE_CONFIRMED` means
the reported code shape was observed; it does not mean the behavior was fully
executed or repaired.

## Execution status and limitations

Executed offline: Git identity/status, tool versions/cache locations, audit
ZIP path and manifest checks, the two supplied historical reproductions,
equivalent current-module restart and clock probes, the README CLI mismatch
probe, and governed-source byte checking.

`NOT_EXECUTED`:

- the missing `../authoring-tests` suite;
- legacy full candidate qualification and all controller/archive/seal flows;
- the full 46-case durability matrix and 65-vector semantic dispatch;
- receipt requalification, clean-clone replay, Windows-native replay, and
  power-loss/filesystem-corruption testing;
- any provider, model, odds, betting, money, cashout, or live discovery path.

`BLOCKED_ENVIRONMENT` for this task: real isolated Chrome/Chromium extension-
origin qualification was not provisioned or authorized. No browser was
launched, downloaded, or attached, and no real user profile was accessed.

## Authority boundaries

- Selected authority: local BH-R00 diagnosis/documentation and one local
  commit of this file only.
- BH-R01 changes are carried-in user/parallel-worker state and remain outside
  this task's commit.
- `REPAIR_REGRESSION_GATE`: BH-R00 inventory/reproduction only; no runtime gate
  is granted.
- `SCOPED_INTEGRATION_GATE`: `NOT_RUN`.
- `LEGACY_FULL_QUALIFICATION`: `NOT_RUN`.
- Live discovery authorization: `NO`.
- Authenticated operator access: `NO`.
- Provider/browser execution authority: `NONE`.
- Production authority: `NONE`.
- No remote mutation, push, deploy, source sync, new baseline, seal, or
  retrospective receipt edit was performed.
