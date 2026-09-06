# BH-R11 independent repair closure

Review date: `2026-09-06` (UTC). This review covers the code tree at
`0f0bcc646f95ce760aed9821e0578d84caf3dc20` / tree
`5716735cbb53b65a35f18664ce6fa08888cfcec1`. The audited commit
`7cd7ab14652458608386d940bdc7764910044f6a` is an ancestor of that commit.
No base reset, history rewrite, remote mutation, provider/browser-profile
access, deployment, or production activation was performed.

## Verdict

- `REPAIR_REGRESSION_GATE: PASS` for the named offline counterexamples.
- `SCOPED_INTEGRATION_GATE: HOLD`; ordinary/idempotent/gap SQLite behavior and
  18 supplemental backend process-crash boundaries passed, but the complete
  inherited `CONFLICT-01` successor scenario and real spool path remain open.
- `LEGACY_FULL_QUALIFICATION: HOLD`.
- `SECURITY_REVIEW: NOT_REVIEWED` for the repair commit.
- `LIVE_DISCOVERY_AUTHORITY: NONE`; `PRODUCTION_AUTHORITY: NONE`;
  `MONEY_AUTHORITY: NONE`.

The full required inventory is exact and terminal, but not complete in
execution: 111 IDs produce 17 `PASS` and 94 `NOT_IMPLEMENTED`. The 94 consist
of all 46 inherited crash IDs and 48 of 65 clock IDs. Six clock mutations ran,
all six had verifiable evidence, and zero survived. This is a truthful `HOLD`,
not 111 successful executions.

## Audit finding disposition

| Finding | Status at reviewed code | Independent closure evidence |
| --- | --- | --- |
| BH-AUDIT-01 | **FIXED for the false-PASS route; broader durability BLOCKED** | The historical byte-verified runner accepted both `0/0/0` and `999999/999999/999999` while persisting only readiness JSON. Current regressions require an actual reader, reject actual zero against expected 999999, reject stale/wrong checkpoint identity, reader failure, missing storage and child failure. Actual SQLite integrity corruption is rejected. Scoped backend crash tests use owned SIGKILL, trusted child argv/hash, recovery and read-only DB inspection. The inherited 46-case full crash release remains `NOT_IMPLEMENTED`, and the complete `CONFLICT-01` successor state remains a contract HOLD rather than fabricated evidence. |
| BH-AUDIT-02 | **UNFIXED / BLOCKED_ENVIRONMENT_AND_IMPLEMENTATION** | The old false proof cannot pass: direct invocation of the legacy IndexedDB matrix stops before workspace creation with `E_ACTUAL_STATE_READER_REQUIRED`. However, `run_indexeddb_crash_matrix.py` still names the Node child, the child is an intentional contract stub, and `extension/src/spool.ts::Spool.append` is unimplemented. The latest real isolated Chrome probe was visibly skipped with `E_EXTENSION_TARGET_UNAVAILABLE` (`chrome-error:`), so no extension-origin write/SIGKILL/restart/readback occurred. |
| BH-AUDIT-03 | **FIXED for false coverage; full clock qualification BLOCKED** | The clock runner now emits one row per governed ID, verifies artifacts and registered oracles, and does not count missing handlers. Fresh evidence is 17 executed `PASS`, 48 `NOT_IMPLEMENTED`, result `HOLD`. Missing-case evidence fails, and two evaluators returning the same wrong RTT fail the independent numeric oracle even with zero cross-language drift. |
| BH-AUDIT-04 | **FIXED** | The audited high-RTT input (`999900` us versus `250000` limit) no longer becomes eligible through supplied derived fields. Raw derivation and stored-mapping validation are separate; wrong expected metadata does not affect the evaluator. Python and TypeScript are checked against an independent arithmetic oracle. |
| BH-AUDIT-05 | **FIXED for portable replay; full replay BLOCKED** | The documented portable command ran offline from the checkout and passed all four checks: TypeScript compile, registry self-check, 67 implemented repair tests, and collection of 207 repair tests. The separate full command returned `HOLD`/exit 2 and did not invoke the authoritative controller because pack/evidence/external tests/caches/browser were not configured and controller configuration is unbound. Hosted CI and its manual browser job have not run. |

There is no remaining expected-as-observed or count-only success route in the
scoped runners exercised here. That statement does not upgrade the blocked
IndexedDB path, unimplemented inherited cases, or product stubs.

## Counterexamples and regression execution

The supplied audit archive was extracted to an isolated `/tmp` directory and
its two original scripts were rerun unchanged:

- `python3 .../betting-helper-audit/reproduce.py` — exit 0; both contradictory
  expected states returned `PASS`, reproducing BH-AUDIT-01 on the exact audited
  excerpts.
- `python3 .../betting-helper-audit/reproduce_clock.py` — exit 0; raw RTT
  `999900` was rejected but the same timestamps with derived overrides returned
  `ACCEPT`, reproducing BH-AUDIT-04 on the audited excerpt.

After compiling the repository's existing TypeScript test target, seven
current counterexample nodes passed: legacy ready-only without reader, actual
zero versus expected 999999, audited high-RTT bypass, wrong expected metadata,
SQLite integrity corruption, missing required evidence, and identical wrong
Python/TypeScript outputs. The initial precompile attempt had 1 failure because
the restored `.test-build` evaluator was stale; the required
`pnpm --dir extension exec tsc -p tsconfig.test.json` completed with exit 0,
after which the same seven-node command passed. Generated output was restored
to committed bytes after verification and was not committed.

## Fresh commands

All commands ran in
`/home/thenam176/betting-helper/discovery-runtime-v6.3.6` using installed local
dependencies. Full logs are ignored under `.local/bh-repair/BH-R11/`.

| Command | UTC interval | Exit | Result |
| --- | --- | ---: | --- |
| `python3 /tmp/bh-r11-audit.rKKJDa/betting-helper-audit/reproduce.py` | 11:01:39–11:01:39 | 0 | Historical false PASS reproduced |
| `python3 /tmp/bh-r11-audit.rKKJDa/betting-helper-audit/reproduce_clock.py` | 11:01:46–11:01:47 | 0 | Historical derived override reproduced |
| `pnpm --dir extension exec tsc -p tsconfig.test.json` | 11:04:46–11:04:50 | 0 | Existing test target compiled |
| Seven named independent counterexample pytest nodes | 11:05:08–11:05:16 | 0 | 7 passed |
| `uv run --frozen --offline python -m pytest -q tests/repairs -o cache_dir=.local/bh-repair/pytest-cache` | 11:05:24–11:08:17 | 0 | 206 passed, 1 skipped |
| `uv run --frozen --offline python tools/verify_local.py --profile portable` | 11:08:42–11:09:38 | 0 | `PASS`; four checks exited 0 |
| `uv run --frozen --offline python tools/verify_local.py --profile full` | 11:09:48–11:09:48 | 2 | Expected `HOLD`; controller `NOT_EXECUTED` |
| Required 46-crash + 65-clock aggregation | 11:10:11–11:10:18 | 0 | Exact inventory; aggregate `HOLD` |

The one repair-suite skip was the real-browser integration test and exposed
`E_EXTENSION_TARGET_UNAVAILABLE`; it is not counted as browser durability.

## Evidence binding and provenance

Relevant reviewed hashes:

- `tools/inspect_restart_state.py`:
  `c484314025d63c74b3af2698dc472b59477e1e70ac7979eb0f78479be52996ff`
- `tools/run_clock_vector_qualification.py`:
  `98cca19052ae85bf8e860805c950e2da0ce15f94a72709f3ec33a44f2d5717fa`
- `tools/verify_repair_evidence.py`:
  `3cd1fbf222ca0af7794eb621e87453977b03b23981cbd217e4e9e3e5227ce286`
- `tools/verify_local.py`:
  `cb49b774d016eda057f4ee59ba0b2a1d318d5179f264bc0184764ed85870c636`
- `schema-lock.json` / `uv.lock` / `pnpm-lock.yaml`:
  `769444c9da87a8eb6bd2dba992b351bc7143dc17c02e94c4e8a65ccac70940ad`,
  `876853e6c71f8e33606d99353838437f8e8c223a98fa7899c25c31146339a974`,
  `a721d88235ee25457a5b525de72a83b252478ff85c26cb3eb8ebce8d049396e7`
- vendor tree hash recorded by the unchanged lock:
  `615da45ffdf210b10f64e1b7fad3e2cdc4e51625a445bcd485a2bbfe4ab6bf37`.

Actual persistence evidence came from temporary SQLite databases built with
the governed DDL, reopened through the read-only restart-state reader. No
actual IndexedDB spool evidence exists for this review.

Existing Review A, Review B and P10 records were inspected but not promoted to
repair evidence. They bind an older sealed pack/repo0 receipt (pack SHA-256
`00480f69151d656c20863ca08f0604f0e684fc84d97fd1f2f80bd11e7d60a599`)
and an authoring receipt at commit
`47c63d2123429c000c6d954f3d744447c3c8238f`, not the reviewed repair commit.
Their P10 observation time is `2026-09-06T03:48:10Z`. In particular, the old
cybersecurity Review B `PASS` is not a cybersecurity review of these changed
bytes; current repair security therefore remains `NOT_REVIEWED`. No historical
receipt was edited.

## Unexecuted coverage and limits

- Real extension-origin IndexedDB spool/ACK crash cases and R05.
- The 46 inherited full crash owners and 48 clock lifecycle/hash/selection/
  closure/release/acceptance evaluators marked `NOT_IMPLEMENTED`.
- Native Windows termination, power-loss, controller/filesystem-failure and
  whole-run destruction behavior.
- External `authoring-tests`, current candidate receipts, and authoritative
  controller execution.
- Hosted portable CI and the approved disposable-runner browser job.
- Cybersecurity review of the repair commit.
- Authenticated Mise-o-jeu, provider, real browser profile, WDL, wager,
  Cashout, deployment, live discovery, and production paths.

BH-R11 supports selecting **BH-S01 only** as the next separately authorized,
synthetic-only offline task. It does not satisfy BH-S02's real spool dependency
and does not authorize any live or monetary work.
