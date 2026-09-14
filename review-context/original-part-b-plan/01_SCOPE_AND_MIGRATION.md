# Scope, integration decisions and controlled migration

## Basis
Observed repository HEAD: `d4055839e596fc52f0e0df175a6733a64b8fffc1` [R1]. Start from actual checkout; retain newer commits/unrelated work. Existing API config is v1 with two30s polls [R2]. Old LV-01..07 are mapped, not discarded.

## Goals and non-goals
Complete LIVE_READ_ONLY for selected normal-time football WDL markets. FT first; H1/H2 become visible only with verified period/settlement mapping. Exact operator link and optional verified LiveScore link. No wager, stake entry, betslip mutation, account/position/Cashout collector, money, model, predictions endpoint, Vision or Hermes. Codex is the development worker, not runtime decision authority.

## What changes, what remains
- Reuse tested canonicalization, closed schemas, durable storage/ACK principles, browser qualification and fault oracles.
- Preserve `contracts/offline_slice/v1`, `extension/manifest.offline.json`, existing vendor bytes/SQL. Do not send live data as synthetic TERMINAL records.
- Create live-v2 config under `config/live-batched.example.json` and new typed contracts under `contracts/live_readonly/v1/`. Keep old `config/live.example.json` and `check_live_readiness` as legacy v1 compatibility.
- New `LiveCaptureSpool` is a separately named wrapper/database over a shared low-level IndexedDB transaction utility extracted from existing Spool. Keep the old Spool API/schema behavior unchanged and rerun its dependent Part A tests. This is an explicit feature seam, not a parallel fake backend.
- New `LiveStore` holds typed football/book/capture revisions and multi-fixture identity. Existing RunStore DDL is an immutable single-stream synthetic accounting contract; it cannot be silently widened. `LiveStore` uses its own versioned SQLite DDL, verified transactions, same canonical/hash approach and actual-state/replay tests. No historical Part A approval automatically qualifies it.
- Poller uses batched IDs. No default `/fixtures?live=all` or fixed second events poller. Discovery of a chosen competition/date is a separate bounded user search, not a continuous global feed.
- First collector is fixed DOM-read-only code. Network/CDP extraction is a separately reviewed optional extension if visible odds cannot be read; not an automatic escalation.

## Authority and autonomous execution
The start prompt selects PB-00..PB-24 for code/mock/isolated-platform tests. Ordinary local tests, edits, local commits and installed-tool build run continuously where local controller permits. No push, deployment, history rewrite, global config change or automatic provider purchase. Existing AGENTS/host receipts remain; register selected scope before code and do not forge/disable them.

External side effects have three deliberately separate permissions:
1. PROVIDER_PROBE: <=20 total HTTP attempts, <=5min, selected league/season/date/IDs, no operator session.
2. OPERATOR_DISCOVERY: one user-selected tab in dedicated profile, <=10min, read-only field inspection; no provider calls required.
3. LIVE_READ_ONLY_SESSION: one fixture first, <=120min and600 HTTP attempts; accepted provider/profile/platform/security evidence. Restart requires fresh run confirmation/pairing. Three/five fixtures each require a later explicit expanded-scope run.

Code completion is not run authorization. Missing API key blocks real requests, not mock tests. Missing operator samples blocks only real selector/profile tasks; all provider and generic synthetic UI work continues. Missing true Part A acceptance is recorded; code work can proceed on isolated data but live activation stays blocked.

## Execution topology
Preferred user workflow: Windows Chrome dedicated profile → exact local WebSocket → WSL2 backend. Keep listener127.0.0.1; never open LAN/public port as a workaround. Linux Chrome/WSL qualification may be a separate accepted platform, not proof of Windows behavior. PB-15 measures actual topology with synthetic local content before live.

## Paths and lifecycle
Every task path is repo-relative. The package is an input document, not the implementation repository. Stage config in `config/live.local.json` (gitignored); evidence under `.local/part-b/`; provider quota ledger at `.local/part-b/quota.sqlite3`; run dirs immutable after close.
Files assigned to future tasks are declarations, not required to exist at PB-00. Final executable gate runs after their owners materialize them. No future tool is executed before its owner. New schemas are source-owned, old vendor remains governed by existing sync tool.

Part A receipt at entry remains bound to its original commit. At final freeze, rerun affected source tests and the Part A acceptance on the current candidate when shared dependencies changed. Keep old evidence; never edit its hash/commit to make it current. Evidence lives outside tracked source, avoiding commit/report hash cycles.
