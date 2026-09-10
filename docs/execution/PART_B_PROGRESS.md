# Part B execution progress

Batch: PB-00 through PB-24. Branch: `codex/part-b-batched`.
Starting HEAD: `39b92966c2db6694b31507526b339206f4db2b0d`.
Exact current HEAD, task/evidence/config hashes, commands and exits live in
`.local/part-b/execution-state.json`, `.local/part-b/task-evidence/` and the current
private release report. This tracked pointer avoids a commit/report hash cycle.

PB-00 through PB-17 completed local implementation and mock qualification at
`180da4b19beae2c10bc2adc06cc98fdc181a94d3`. Its old result remains immutable.
Later shared code changes require a new final source-bound campaign.
PB-18 now includes a tested, bounded date lookup before an exact fixture probe.
PB-21/PB-22 recording, manual FT comparisons and prior-scope replay checks are
implemented and locally tested; no real run is claimed. PB-23 release/report
and PB-24 performance-blind manifest code are implemented. The current private
checkpoint records whether final verification has completed on the frozen bytes.

External gates:

- PB-18 WAITING_FOR_USER_SECRET: two user-terminal probes each stopped after one
  STATUS request with SCHEMA_ERROR; key validity remains NOT_CHECKED. Fixed safe
  validator diagnostics are implemented and need a fresh confirmed terminal run.
  Lookup remains league 2/season 2026/date 2026-09-10; fixture ID is unverified.
- PB-19 WAITING_OPERATOR_SAMPLE: dedicated manually logged-in Windows Chrome
  profile, exact tab and separately reviewed <=10-minute fixed DOM observation.
  No real selectors, IDs or settlement are guessed; the admitted index is empty.
- PB-20 WAITING_REVIEW: actual provider/profile evidence and current independent
  external host security receipts are absent. No reviewer signature is invented.
- PB-21/PB-22 WAITING_MATCH_WINDOW: accepted prior inputs and separate bounded
  one/three/five confirmations remain. No real session has executed.
- PB-24 WAITING_DATA_AND_RIGHTS_REVIEW: no real research dataset, settled target
  labels or access-review evidence supplied. No SCOPE0 or Part C activation.

Windows Chrome -> WSL2 is the selected isolated platform. Synthetic browser,
IndexedDB and SQLite observations are separate from real operator/provider proof.
Physical sleep/power loss and the native Side Panel toolbar are NOT_OBSERVED.
Full-source mypy retains 25 pre-existing errors in three unchanged governance
files, reproduced at the starting commit; scoped Part B checks are separate.

Real provider attempts by this worker: 0. Real operator captures: 0.
Observed user-terminal provider attempts: 2 (two failed STATUS calls).
MODEL_ENABLED: false. MONEY_READY: NO. Production authority: NONE.
No pushes, deployments, new baseline, history rewrite, wager or Cashout authority.
