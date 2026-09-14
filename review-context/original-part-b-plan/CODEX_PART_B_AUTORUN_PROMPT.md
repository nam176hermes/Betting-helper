You are the implementation worker for the existing nam176hermes/Betting-helper project.
MODE: PART B IMPLEMENTATION, not another planning-only pass.

Use the supplied betting-helper-part-b-batched-plan package. Read README_VI.md,
01_SCOPE_AND_MIGRATION.md,02_PROVIDER_AND_BUDGET.md,03_KEY_GUIDE_VI.md,
04_LIVE_CONTRACTS.md,05_OPERATOR_AND_UI.md,06_EVIDENCE_AND_RUNS.md,
CONTRACT_SEMANTICS.md and the current task card before changing its code.
Sources are classified in SOURCES.md. The last inspected main was
 d4055839e596fc52f0e0df175a6733a64b8fffc1.
Inspect actual HEAD/status and AGENTS/nested rules; do not reset newer work.

I select PB-00 through PB-24 as one continuous implementation batch for all
code, mock, synthetic and approved isolated-platform work. Register this exact
scope with the existing local controller. I authorize ordinary local task commits
and the files explicitly owned by these tasks, subject to any host-enforced gate.
No remote pushes, deployments, new zero-parent baseline, history rewrite or
unrelated changes. Do not edit vendor or root generated registries directly.

Keep my currently configured Codex model and reasoning settings unchanged.
Do not stop after PB-00 or each task to ask whether to continue.
Use focused tests first, implement, inspect output, fix ordinary failures,
record evidence/checkpoints, and automatically select the next ready task.
Do not reply with only a new architecture or implementation plan.

OBJECTIVES
- One backend ProviderBundlePoller for selected fixture IDs, /fixtures?ids=...
  (documented API maximum20; product scope1→3→5 only after its run gate).
-15s while1H/2H,60s HT/pre-match,30s near kickoff, terminal confirmation policy.
- No duplicate per-widget/per-tab/per-fixture API loops.
- Events fallback OFF unless real feasibility evidence and its budget approve it.
- Daily/session/minute reservation guards, no secret leaks, no generic HTTP proxy.
- Narrow observed Mise-o-jeu DOM profile, complete H/D/A and exact fixture binding.
- Read-only Side Panel/shared watchlist, real storage and replay.
- No models/probabilities/EV/stakes/betting/Cashout/Part C activation.

CREDENTIAL INSTRUCTIONS ARE MANDATORY
Do NOT ask for API_FOOTBALL_KEY while code/mock tasks PB-00..17 are unfinished.
PB-02 must first implement and test the no-echo user-terminal key launcher.
At PB-18, send the Vietnamese instructions in 03_KEY_GUIDE_VI.md and the exact
user-terminal command. The user obtains the key from API-Football Account→My Access
and enters it only in their own local terminal, NOT in this conversation.
Never ask them to paste a key, header, cookie, password, raw/status JSON or .env.
Never execute printenv/env, display the key, read arbitrary secrets or fingerprint it.
If no TTY/no-echo is available, fail closed; never fallback to input().
A key found in environment is not permission to send a real request.
Do not make purchases or subscribe/upgrade on the user's behalf.

LIVE SIDE-EFFECT GATES
This prompt authorizes code/mock work, NOT automatic authenticated live access.
Real provider probe: user confirmation, exact scope and<=20attempts/<=5min.
Operator observation: dedicated profile manually logged in, exact chosen tab,
fixed read-only capture and separate<=10min permission.
Live session: accepted provider/profile/platform/current security evidence and
explicit user confirmation for1fixture/<=120min/<=600attempts. Expanded3/5 scopes
require separate bounded confirmations. Use real external host receipts if required;
do not invent signatures or declare yourself an independent reviewer.

When an external gate is reached, ask only for the concrete missing input once.
Set WAITING_FOR_USER_SECRET / WAITING_OPERATOR_SAMPLE / WAITING_PLATFORM /
WAITING_REVIEW / WAITING_MATCH_WINDOW as appropriate. Continue other independent
ready code tasks. Do not substitute synthetic fixtures to claim a real-source PASS.

QUALITY RULES
- Respect the explicit v2/live seam; old synthetic RawObservation remains closed.
- No guessed operator selectors/IDs/settlement. Draft profiles remain inactive.
- Existing Part A evidence is bound to its old bytes. Run affected regressions on
  new shared code; do not change old receipts. Final evidence outside tracked code.
- Expected oracle stays separate from actual browser/SQLite/API observations.
-1,3,5 simultaneous matches can share calls; sequential windows and retries cost more.
-15s is our polling period, not guaranteed source latency. Source-age unknown stays
  UNKNOWN. fixture.timestamp is kickoff, never a last-update timestamp.
- No key in extension/browser/localStorage/artifacts/argv; only provider backend.
- Keep all configured quotas, no0.0.0.0 workaround, no catch-up storm after sleep.
- Browser-required cases run real isolated browser; mocks never prove that gate.

CHECKPOINTS
Maintain docs/execution/PART_B_PROGRESS.md and
.local/part-b/execution-state.json with actual HEAD, completed tasks,
current task, evidence refs and external blockers (no secrets).
If context/quota/session ends, write a resumable checkpoint instead of restarting.
One working-tree editor by default; reviewers read isolated copies only.

FINAL REPORT
Report separately:
PART_B_MOCK_PASS
PROVIDER_PROBE_PASS
OPERATOR_PROFILE_ACCEPTED
PLATFORM_BRIDGE_PASS
LIVE_READ_ONLY_PASS_ONE
LIVE_READ_ONLY_PASS_THREE
LIVE_READ_ONLY_PASS_FIVE
SCOPE0_READY_FOR_REVIEW
INDEPENDENT_LIVE_SECURITY_REVIEW
MODEL_ENABLED: false
MONEY_READY: NO
No auto-trading/Cashout authority.

Include actual commit/source/config/profile/evidence hashes, commands/exits,
request counts and all not-executed/not-observed limitations. Never mark the full
Part B complete when only mocks pass or the API key/profile has not been supplied.
Begin PB-00, then automatically continue every ready task.
