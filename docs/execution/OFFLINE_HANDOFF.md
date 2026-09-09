# Offline slice handoff

Lane A OS-00..OS-15 implements synthetic accounting only. Final acceptance is
source-bound and recorded outside tracked source, avoiding a commit self-hash cycle.
A result is valid only when the independent verifier succeeds for the current
HEAD/source, exact 27-case inventory and retained real browser/SQLite evidence.

```sh
BH_CHROME_BINARY=/opt/google/chrome/chrome uv run --frozen --offline python tools/run_offline_slice.py --scenario acceptance --output .local/offline-slice/acceptance
uv run --frozen --offline python tools/verify_offline_slice.py --input .local/offline-slice/acceptance/result.json
uv run --frozen --offline python tools/export_replay_diagnostic.py --input .local/offline-slice/acceptance/result.json
uv run --frozen --offline python tools/live_preflight.py --config config/live.example.json --offline-result .local/offline-slice/acceptance/result.json
```

Existing evidence destinations are exclusive. Resume by independently checking
an existing result, or choose a fresh attempt directory; never overwrite failure
evidence. Checkpoint: `.local/offline-slice/execution-state.json`.
Diagnostic: `<campaign>/diagnostic.html`, with actual counts and SYNTHETIC ONLY.
Preflight exit 2 is expected pending real inputs; it grants no live authority.

The final worker report and ignored checkpoint record actual verified counts,
HEAD, command exits and evidence paths. This document itself grants no PASS.
See `docs/runbooks/START_LIVE_READ_ONLY.md` for the exact separate lane-B inputs.
Legacy qualification remains separate; no signed independent-security review is
claimed. LIVE_READ_ONLY_READY: PENDING_REAL_INPUTS_AND_LIVE_REVIEW.
MONEY_READY: NO. PRODUCTION_AUTHORITY: NONE.
