# Betting-helper Part B — Implementation Plan

> Agentic worker: use a test-first task workflow and persistent checkpoints. The batch prompt selects the full Part B coding queue; external-source actions retain explicit user gates. Do not create another architecture pack instead of implementing these tasks.

**Goal:** a real read-only match/FT odds workspace and provider batching, then qualified three- and five-match watchlists.
**Architecture:** API-Football backend batch poller + a narrow observed Mise-o-jeu DOM profile + live typed journal/replay + one shared Side Panel/workspace read model. Part A and Part C remain distinct.
**Tech stack:** existing locked Python 3.12/uv/SQLite, TypeScript/pnpm, current locked websockets; standard-library HTTP/getpass. No new web framework, browser automation dependency, model/provider SDK, native relay or model change by default.
**Spec:** `01_SCOPE_AND_MIGRATION.md` through `06_EVIDENCE_AND_RUNS.md`, plus `CONTRACT_SEMANTICS.md` and supplied assets.

## Global constraints
Preserve actual checkout history, vendor/source governance and unrelated work. No live source invocation until relevant user/platform/security gate. No credentials in transcripts/files/browser. No arbitrary operator interaction. All required code/tests must exist before final qualification, no zero-parent baseline or sealing bureaucracy restart. Local commits only under granted scope. No remote push/deploy.

## Task map
- **PB-00** [Reconcile Part A evidence and register the Part B implementation scope](tasks/PB-00.md) — depends on none; external gate `NONE`.
- **PB-01** [Create source-owned live contracts, v2 config and fixed endpoint/fixture registries](tasks/PB-01.md) — depends on PB-00; external gate `NONE`.
- **PB-02** [Build a user-operated no-echo API key launcher and secret handling tests](tasks/PB-02.md) — depends on PB-01; external gate `NONE`.
- **PB-03** [Implement global attempt reservation, shared quota ledger and estimator](tasks/PB-03.md) — depends on PB-01; external gate `NONE`.
- **PB-04** [Implement the fixed direct API client with bounded GET and safe response handling](tasks/PB-04.md) — depends on PB-02, PB-03; external gate `NONE`.
- **PB-05** [Normalize football snapshots and preserve correction/missingness lineage](tasks/PB-05.md) — depends on PB-04; external gate `NONE`.
- **PB-06** [Implement one adaptive ProviderBundlePoller for the complete watchlist](tasks/PB-06.md) — depends on PB-03, PB-04, PB-05; external gate `NONE`.
- **PB-07** [Implement typed multi-fixture LiveStore and independent replay](tasks/PB-07.md) — depends on PB-01, PB-05; external gate `NONE`.
- **PB-08** [Add live capture spool and separate authenticated live wire](tasks/PB-08.md) — depends on PB-01, PB-07; external gate `NONE`.
- **PB-09** [Build an inert extraction-profile validator using synthetic DOM samples](tasks/PB-09.md) — depends on PB-01; external gate `NONE`.
- **PB-10** [Implement fixed DOM reader, complete book assembly and document identity guards](tasks/PB-10.md) — depends on PB-08, PB-09; external gate `NONE`.
- **PB-11** [Implement fixture bindings, market epochs and freshness as a pure reducer](tasks/PB-11.md) — depends on PB-05, PB-07, PB-09; external gate `NONE`.
- **PB-12** [Connect the shared live service and projection subscriptions with mocks](tasks/PB-12.md) — depends on PB-06, PB-08, PB-10, PB-11; external gate `NONE`.
- **PB-13** [Build Side Panel and multi-match workspace without model placeholders](tasks/PB-13.md) — depends on PB-12; external gate `NONE`.
- **PB-14** [Implement configuration wizard, scope preview and user-confirmed run intents](tasks/PB-14.md) — depends on PB-02, PB-03, PB-12; external gate `NONE`.
- **PB-15** [Qualify the actual browser-to-backend platform using synthetic local data](tasks/PB-15.md) — depends on PB-08, PB-10, PB-13, PB-14; external gate `USER_PLATFORM_SELECTION`.
- **PB-16** [Implement live preflight evidence admission and executable security checks](tasks/PB-16.md) — depends on PB-12, PB-14, PB-15; external gate `NONE`.
- **PB-17** [Run the complete mock Part B gate and prepare the exact external-input checklist](tasks/PB-17.md) — depends on PB-06, PB-07, PB-08, PB-09, PB-10, PB-11, PB-12, PB-13, PB-14, PB-15, PB-16; external gate `NONE`.
- **PB-18** [Guide user key entry, confirm scope and execute the bounded real provider probe](tasks/PB-18.md) — depends on PB-17; external gate `USER_SECRET_AND_PROVIDER_PROBE_APPROVAL`.
- **PB-19** [Observe one dedicated operator tab and admit a real sanitized extraction profile](tasks/PB-19.md) — depends on PB-17; external gate `USER_OPERATOR_SESSION_AND_PASSIVE_OBSERVATION_APPROVAL`.
- **PB-20** [Bind real sources, review enabled surfaces and admit a single-fixture run](tasks/PB-20.md) — depends on PB-18, PB-19; external gate `CURRENT_INDEPENDENT_SECURITY_REVIEW_AND_RUN_SELECTION`.
- **PB-21** [Run, record and replay one real football match with FT odds](tasks/PB-21.md) — depends on PB-20; external gate `USER_LIVE_ONE_RUN_CONFIRMATION`.
- **PB-22** [Scale accepted watchlist from one to three then five concurrent matches](tasks/PB-22.md) — depends on PB-21; external gate `USER_EXPANDED_SCOPE_RUN_CONFIRMATION`.
- **PB-23** [Freeze source-bound Part B release evidence and user startup/shutdown runbook](tasks/PB-23.md) — depends on PB-21, PB-22; external gate `NONE`.
- **PB-24** [Prepare performance-blind data and research-scope handoff without building models](tasks/PB-24.md) — depends on PB-23; external gate `NONE`.

## Execution policy
Run lowest-numbered ready task, sequential source editing by default. After a task passes, continue automatically. If a task has missing external data, record WAITING_INPUT and execute other independent ready tasks. Do not endlessly retry the same environment failure. Context/quota expiration writes checkpoint; resume verifies current HEAD and last evidence before continuing. Do not change Codex model/reasoning settings.

PB-00..17: implement and verify code using mock/synthetic/local platform data; key not required. PB-18: user-guided real API probe. PB-19: dedicated operator observation. PB-20: current source binding and independent live-surface review. PB-21: first real one-match session. PB-22: separate three- then five-match sessions. PB-23/24: source-bound handoff and performance-blind data manifest.

## Mapping retained LV goals
LV-01 = PB-09,10,19. LV-02 = PB-02..06,14,18. LV-03 = PB-07,11,20. LV-04 = PB-08,12,14..16,20. LV-05 = PB-13,22. LV-06 = PB-15..17,20..23. LV-07 = PB-24.

No Part C training/calibration/EV/money task is selected. Future model input data may be retained, but the app displays MODEL_NOT_QUALIFIED.
