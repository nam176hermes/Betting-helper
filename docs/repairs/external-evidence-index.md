# External evidence retained outside portable verification

The portable profile is deliberately checkout-local. It does not delete,
replace, or satisfy the v6.3.6 verification topology's external obligations.
Missing inputs are `HOLD`, never an inferred pass.

| Obligation | Authoritative source | Portable treatment | Full prerequisite |
| --- | --- | --- | --- |
| Governed v6.3.6 source bytes and root registry | Explicit `--pack`; `docs/registries/normative-source-map.v1.json` | Vendored bytes and root registry are self-checked | Pack is checked byte-for-byte against the checkout with the sole sync implementation in check mode; no write or reseal |
| Bootstrap evidence | `<evidence-root>/bootstrap/authoring-repository-receipt.json` | Not replayed | Receipt shape, Git identities, clean status, and binding to the explicit pack's authoring root must validate |
| Candidate qualification evidence | `<evidence-root>/V636-P07-T01.json` and `CANDIDATE_QUALIFICATION.json` | Old receipt is not accepted for changed repair bytes | Existing receipt validator must bind the command evidence and current checkout inventory |
| External authoring tests | Verification topology group `authoring`: `authoring-tests` | Absent from pytest defaults; obligation remains listed and unexecuted | Explicit absolute `--authoring-tests` directory must exist |
| Installed Python and Node inputs | Pinned `uv.lock`, `extension/pnpm-lock.yaml`, explicit uv cache and pnpm store | Reuses already installed tools; no sync/install/download | Explicit absolute cache/store directories must exist |
| Real extension-origin browser qualification | Browser-required repair cases and the inherited durability topology | Cases are collected only; no Chrome launch | Explicit executable `--chrome` must match `--chrome-sha256`; actual browser evidence remains a separate qualification result |

The inherited required groups remain: `bootstrap`, `authoring`,
`materialization`, `contracts`, `durability`, `clock`, `review`, `security`,
`release`, `seal`, and `test-harness`. Their governed locations and exact
command IDs remain in
`vendor/hybrid-discovery-v6.3.6/docs/registries/verification-topology.v1.json`
and the generated root command registry. In particular:

- `plan-input/bootstrap/test_bootstrap_tools.py` and `authoring-tests` are
  external to this checkout;
- repo-local Python groups under `tests/` and TypeScript groups under
  `extension/test/` remain governed full-qualification obligations;
- `extension/test-harness` is included by `extension/tsconfig.test.json` and is
  compiled before portable Python parity checks;
- a collected test, a skipped browser case, or an intentional
  `NOT_IMPLEMENTED` result is not converted to `PASS`.

`tools/verify_local.py --profile full` prints its prerequisite report first.
It delegates to the existing `candidate-qualification` controller only when
every listed item passes. It has no fallback pack, no private-path guess, no
receipt refresh, no seal step, and no live/provider authority.

Status boundaries are independent:

- `REPAIR_REGRESSION_GATE`: named repair behavior executed locally.
- `SCOPED_INTEGRATION_GATE`: only the implemented scope supported by its own
  evidence.
- `LEGACY_FULL_QUALIFICATION`: authoritative topology and receipts; `HOLD`
  whenever any required input or case is missing, stale, blocked, or
  unimplemented.
- Live discovery authorization and production authority: `NONE`.
