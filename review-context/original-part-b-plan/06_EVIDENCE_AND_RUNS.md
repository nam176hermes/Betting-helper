# Evidence, user gates and live qualification

## Capability levels (not interchangeable)
PART_B_MOCK_PASS: offline fixtures, local/browser/security tests pass for new code.
PROVIDER_PROBE_PASS: actual API credential/quota/selected coverage observed; no operator approval implied.
OPERATOR_PROFILE_ACCEPTED: actual sanitized field map and identity reviewed; no generic browser rights.
PLATFORM_BRIDGE_PASS: exact Windows/WSL or Linux/browser topology tested; no wider host guarantee.
LIVE_READ_ONLY_PASS: selected real matches observed, recorded and replayed within admitted scope.
SCOPE0_READY: technical dataset/field-quality view ready for performance-blind scope decision; not training or profitability approval.
Always MODEL_ENABLED=false, MONEY_READY=NO; no automated wager/Cashout authority.

## Local approval mechanics without invented cryptographic authority
PB-14 owns a run-intent CLI that produces a closed nonsecret description: intent_id, stage(PROVIDER_PROBE/OPERATOR_DISCOVERY/LIVE_READ_ONLY), selected IDs/URLs as applicable, max duration, total/minute/daily budget, config/source/profile/platform/security references, issued_at, expires_at and user_confirmation_required=true.
The user-run terminal tool displays and confirms intent interactively; it records `confirmation_kind=LOCAL_TTY_USER_CONFIRMATION`, not a signed independent reviewer receipt. If existing local controller requires signed approval, verify that real external receipt in addition; a typed phrase is not a bypass. Draft intents and chat statements cannot be consumed as live approvals.
First use atomically consumes intent in a local approval ledger before network/capture; consumed intent stays consumed across crashes. Identity/source/config mismatch or expiry denies. Expires15min for start; scope lease <=5min probe/10min discovery/120min live. Extension pairing is run-bound and distinct from API key.

## Break the bootstrap cycle
Provider-probe authorization needs tested provider client, budget/secret controls and explicit user20-call intent—not an already-passed full live session or operator profile. Operator discovery requires reviewed fixed DOM tool, dedicated manual-login tab and explicit10min intent—not prior operator samples. Full live start requires both resulting evidence sets plus current scoped integration/security review. This avoids requiring real samples before a safe discovery tool can ever run.

## Evidence admission
All reports distinguish MOCK/SYNTHETIC from OBSERVED_REAL. Real source artifact contains only normalized projected fields and nonsecret quota metadata. Raw credentials/header/body dumps never become test fixtures. Reports bind exact code consumed by task, contract, profile, platform and run IDs; hashes identify bytes, not proof of trust by themselves.
Independent review = another actual session/reviewer records scope and results. Do not manufacture a signature or claim different run-ID strings prove independent reasoning. Use existing host review authority when required. Self-review allows code iteration, never silent live approval. External reviews remain outside a sealed package; no self-referential hashes.

## One-match qualification
Manual selected league/date/fixture matched on both sources. Start WAITING_FOR_DATA. Observe at least one real in-progress period for a bounded session (target>=15min; user chooses duration; no fabricated event to reach target). Compare at least3 complete FT books manually with displayed prices, separated in time; store sanitized numeric/ID checks, no account screenshot. At least one provider observation from each configured request type; source/receipt ages tracked. All recordings replay offline exactly.
Test known failure transitions with synthetic fixtures separately. Rare real goal/card/suspension not observed=>NOT_OBSERVED, notFAIL merely because rare event absent; restrict coverage accordingly. Reconnect/crash drills on active browser/account need explicit approval; they can be tested with replay/local platform instead, with scope clearly labelled. Never create a bet to generate test evidence.
Stop at budget/duration/capture profile expiry. Failure leaves last state visiblySTALE/CONFLICT/STOPPED and exports evidence. No observer silently continues after stop or opens a new session.

## Scaling3 then5
Two explicitly approved runs in that order after one-match pass. Query sorted IDs in one batch while concurrent. Verify independent per-fixture states/cursors, missing-one response behavior, no cross-tab market contamination, exact per-run/global request totals, backpressure, repeated panel open and hidden tabs. Real timings, request totals and unsupported fields are reported. Five concurrent sessions are not required for the first one-match product gate.

## Release outputs and evidence retention
Each run: `intent.json`, `config-public.json`, `source-bindings.json`, `requests.jsonl`(safe purpose/attempt counts, not headers), `result.json`, replay result, sanitized live.sqlite3 and diagnostic. Use live db/table events as replay source; evidence report has references/hashes; no keys or raw login data. No automatic backup/destruction subsystem is added. Close run and preserve within configured512MiB cap; user manually manages retained private evidence after export verification.
A public GitHub summary can contain commit/case counts/status/limitations, not raw profile/account details. Keep closed failing evidence immutable. Full runtime test gate consumes actual required case records, not returnedPASS strings or collected-test counts.

## Final B gate
- All mock acceptance cases executed with source-bound logs and nonzero relevant integration tests.
- Part A shared-dependency regressions remain verified on current code; old full legacy qualification is separately labelled, not erased.
- API probe actual credential/quota/coverage passed or explicitly partial with blocked functionality.
- Operator profile accepted on actual fixture and current capture source.
- Actual chosen platform, not a different Linux profile substituted for Windows.
- Current independent security review for enabled key/network/DOM/wire surface.
- One real match records football+FT book and replays; H1/H2/3/5 capabilities are separately reported, not blanketPASS.
- No models, transaction actions or synthetic-as-live display.

## Runtime commands (owned by tasks; not runnable at the inspected baseline)
```
uv run --frozen --offline python tools/configure_live_batched.py --output config/live.local.json
uv run --frozen --offline python tools/verify_part_b.py --profile mock --output .local/part-b/mock
uv run --frozen --offline python tools/prepare_part_b_intent.py --stage provider-probe --config config/live.local.json --output .local/part-b/intents/provider-probe.json
uv run --frozen --offline python tools/run_with_api_football_key.py --action probe --config config/live.local.json --intent .local/part-b/intents/provider-probe.json
uv run --frozen --offline python tools/live_preflight_batched.py --config config/live.local.json
uv run --frozen --offline python tools/prepare_part_b_intent.py --stage live-readonly --config config/live.local.json --output .local/part-b/intents/live-one.json
uv run --frozen --offline python tools/run_with_api_football_key.py --action live-readonly --config config/live.local.json --intent .local/part-b/intents/live-one.json
```
Offline/mock commands never read real key values or call provider. Probe/live commands require manual confirmation and are intentionally separate. `live_preflight_batched` is network-free and only validates evidence/presence; it cannot establish API credential validity.

## Approval-store ownership
PB-14 materializes `run-intent.schema.json` and `intent-store.sql` and implements their validation/consumption. The source/config hashes also bind references to profile/platform/security metadata in the config. All needed CLIs are implemented before PB-18 asks for a key. The provider quota bootstrap exception is limited to one explicitly approved status attempt; it does not authorize an unbounded poller.
