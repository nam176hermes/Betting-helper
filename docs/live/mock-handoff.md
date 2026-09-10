# Part B mock handoff

Run from this checkout with the locked environment:

```bash
uv run --frozen --offline python tools/verify_part_b.py --profile mock --output .local/part-b/mock
```

Use a fresh output directory on every rerun. The verifier records each actual
command, exit, elapsed time and log hash. It requires every BCASE-01 through
BCASE-39 mapping, executed Python cases, seven compiled TypeScript tests, scoped
static checks, registry self-check, shared Part A regressions and new OFF-01
through OFF-27 acceptance plus its verifier. Missing or skipped observations
cannot pass. Expected assertions remain separate from browser and SQLite data.

The user selected Chrome on Windows with a WSL2 backend. Full mock runs use the
owned native Windows process/Job Object harness and disposable profiles, including
IndexedDB crash/restart, DOM capture, two UI views and loopback repair. The fixture
data is synthetic; no operator login or provider credential is involved. Part A
regressions retain their separately qualified Linux Chrome environment. Physical
sleep/power loss and the native Side Panel toolbar are not observed by this gate.

`--profile portable` runs non-browser units, compiled TypeScript and scoped static
checks. Its `PORTABLE_UNIT_PASS` never implies `PART_B_MOCK_PASS`. Push/PR CI uses
that profile; the full browser job requires an explicitly provisioned
`part-b-approved-windows-wsl2` self-hosted runner and manual workflow dispatch.
No remote workflow was dispatched by the implementation worker.

Full-source mypy has 25 pre-existing failures in unchanged governance files,
reproduced at the starting commit. The Part B gate checks its source and tools;
it does not claim full repository static or legacy qualification PASS.

## External inputs after the mock gate

- PB-18: chosen real league, season and fixture IDs; a fresh bounded provider
  probe intent; explicit own-terminal confirmation; API-Football key entered
  only through the PB-02 no-echo launcher in the user's terminal. The maximum is
  20 attempts and five minutes. A key's presence grants no request authority.
- PB-19: a manually logged-in dedicated operator profile, one exact chosen tab,
  fixed read-only capture approval for at most ten minutes, observed complete
  H/D/A identities/settlement and an actual host review receipt. Draft profiles
  remain inactive. Synthetic selectors cannot become a real accepted profile.
- PB-20/21: current accepted provider/profile/platform/Part A/security evidence
  plus a separate one-fixture intent, at most 120 minutes and 600 attempts, and
  a suitable match window. Independent security review needs the configured
  external host's real receipt; local tests and self-review do not supply it.
- PB-22: separate bounded confirmations and preceding real evidence for three,
  then five simultaneous fixtures. Sequential windows and retries consume more
  requests. Expanded scope never follows automatically from a mock result.

All final evidence is outside tracked source in `.local/part-b/`. Exact current
HEAD, source/config hashes, completed tasks, command records and external holds
are indexed by `.local/part-b/execution-state.json`. Old Part A receipts retain
their original bytes and commit binding; changed candidate inputs require new
acceptance evidence. The tracked progress file is a pointer, not a mutable
receipt or an assertion that an external gate ran.

Provider, operator, one/three/five live verdicts and independent security review
remain separate. MODEL_ENABLED is false, MONEY_READY is NO, and no model, wager,
stake, EV, trading or Cashout authority is granted by this handoff.
