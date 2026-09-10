# Part B handoff

The selected batch is PB-00 through PB-24. Source changes are local commits on
`codex/part-b-batched`; no push, deployment or history rewrite is authorized.
The typed live v2 store/wire remains separate from the old synthetic-only
RawObservation seam. Root/vendor registries and old receipts retain their bytes.

Use `docs/runbooks/START_LIVE_READ_ONLY.md` for the own-terminal workflow.
`tools/verify_part_b.py --profile release --output .local/part-b/release` runs a
fresh source-bound campaign and writes a private final report. A new output
directory is required on reruns. Its results identify actual commit/source,
config/profile hashes, command exits, evidence hashes and observed limitations.
The execution-state checkpoint indexes task-specific failed and passing logs.
Do not update this tracked file with a receipt that would invalidate itself.

Capabilities are reported independently: PART_B_MOCK_PASS,
PROVIDER_PROBE_PASS, OPERATOR_PROFILE_ACCEPTED, PLATFORM_BRIDGE_PASS,
LIVE_READ_ONLY_PASS_ONE, LIVE_READ_ONLY_PASS_THREE, LIVE_READ_ONLY_PASS_FIVE,
SCOPE0_READY_FOR_REVIEW and INDEPENDENT_LIVE_SECURITY_REVIEW. Synthetic browser
and SQLite tests establish only their tested local behavior. A real provider
probe, accepted operator profile and real live run remain external gates.

Current selected target is Champions League 2026/27, Bayern München – Bodø/Glimt,
10 September 2026; provider fixture ID is not yet verified. Platform selection
is Windows Chrome → WSL2 at 127.0.0.1. No authenticated provider request or real
operator observation has been performed by the worker. No independent host
signature has been created or reviewer identity impersonated.

Polling every 15 seconds during H1/H2 is application cadence, not a provider
latency guarantee. HT/pre-match use 60 seconds, near kickoff 30 seconds, with
bounded terminal confirmations. Unknown source timestamps remain UNKNOWN;
fixture.timestamp is kickoff. One shared cohort may contain 1/3/5 selected IDs;
sequential windows, setup and retries consume additional quota. Fallback is OFF.

Read-only controls expose no model/probability/EV/stakes/betting/Cashout action.
PB-24 supplies a performance-blind data manifest with explicit missing rights,
history and outcome-label inputs. Existing SCOPE0 approval requirements remain;
RS-01 and Part C are not activated. MODEL_ENABLED=false; MONEY_READY=NO;
production authority is NONE.
