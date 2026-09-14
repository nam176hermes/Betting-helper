# Sources and design attribution

Checked 2026-09-09. Official guidance is evidence, not proof that an authenticated match/plan behaves identically.

## R1 — Current main identity
**Kind:** REPOSITORY

https://github.com/nam176hermes/Betting-helper/tree/d4055839e596fc52f0e0df175a6733a64b8fffc1

Inspected on 2026-09-09. The execution worker must compare its actual HEAD; never reset newer work.

## R2 — Existing live example configuration
**Kind:** REPOSITORY

https://github.com/nam176hermes/Betting-helper/blob/d4055839e596fc52f0e0df175a6733a64b8fffc1/config/live.example.json

v1 currently has two 30-second pollers, 500 calls/run, 8/minute and max_matches=1. PB-01 creates a separate v2 schema/config; no silent reinterpretation.

## R3 — Repository authoring rules
**Kind:** REPOSITORY

https://github.com/nam176hermes/Betting-helper/blob/d4055839e596fc52f0e0df175a6733a64b8fffc1/AGENTS.md

Vendor source synchronization and real-session restrictions remain binding. This plan does not forge host approvals or rewrite historical receipts.

## R4 — Offline projector, spool and wire
**Kind:** REPOSITORY

https://github.com/nam176hermes/Betting-helper/tree/d4055839e596fc52f0e0df175a6733a64b8fffc1/extension/src

Offline types accept synthetic terminal observations. A new live typed seam is required, not live values disguised as TERMINAL.

## R5 — Offline handoff
**Kind:** REPOSITORY

https://github.com/nam176hermes/Betting-helper/blob/d4055839e596fc52f0e0df175a6733a64b8fffc1/docs/execution/OFFLINE_HANDOFF.md

Final offline evidence is outside Git; it was not re-executed while authoring this package.

## A1 — API-Football quota optimization, 2026-07-27
**Kind:** OFFICIAL_WEB

https://www.api-football.com/news/post/how-to-optimize-api-sports-calls-and-quota-usage

Backend centralization, up to 20 ids, coverage checks, quota headers, errors and avoiding duplicate polls. Actual selected competition still requires a probe.

## A2 — World Cup API guide, 2026-04-13
**Kind:** OFFICIAL_WEB

https://www.api-football.com/news/post/fifa-world-cup-2026-guide-to-using-data-with-api-sports

Documents fixtures ids batching and embedded events/lineups/statistics/players, plus 15-second fixture/event refresh. Not a latency SLA or universal completeness guarantee.

## A3 — API-Football getting started, 2026-03-13
**Kind:** OFFICIAL_WEB

https://www.api-football.com/news/post/how-to-get-started-with-api-football-the-complete-beginners-guide

Account → My Access, x-apisports-key, base URL, response wrapper, status codes, timestamp=kickoff, elapsed=minutes.

## A4 — API-Football pricing
**Kind:** OFFICIAL_WEB

https://www.api-football.com/pricing

Observed listing: Free100/day; Pro $19/month7500/day. Currency/tax/payment terms must be checked at checkout; no automatic purchase.

## A5 — API-Football rate limits, 2026-06-12
**Kind:** OFFICIAL_WEB

https://www.api-football.com/news/post/how-ratelimit-works

Per-plan server caps and progressive retry guidance; application cap is intentionally much lower.

## A6 — API v3 reference
**Kind:** OFFICIAL_WEB

https://www.api-football.com/documentation-v3

Official specification entry point. Dynamic page did not expose the full schema to text browsing. Do not claim every response field was independently inspected; PB-18 verifies retained fields against real response.

## A7 — Multiple fixture details tutorial, 2024-12-12
**Kind:** OFFICIAL_WEB

https://www.api-football.com/news/post/how-to-get-all-fixtures-data-from-one-league

Shows /fixtures?ids= with <=20 IDs and detailed objects. Its historical code uses marketplace headers; this plan explicitly uses direct API-Sports header from A3 instead.

## C1 — Chrome Side Panel API
**Kind:** OFFICIAL_WEB

https://developer.chrome.com/docs/extensions/reference/api/sidePanel

User-gesture opening and extension panel integration.

## C2 — Chrome service-worker lifecycle
**Kind:** OFFICIAL_WEB

https://developer.chrome.com/docs/extensions/develop/concepts/service-workers/lifecycle

Workers can terminate. State must not depend on an open panel or only global variables.

## C3 — Chrome scripting API
**Kind:** OFFICIAL_WEB

https://developer.chrome.com/docs/extensions/reference/api/scripting

Bundled isolated-world script injection; use fixed files, not source strings supplied by pages/backend.

## C4 — Chrome message passing
**Kind:** OFFICIAL_WEB

https://developer.chrome.com/docs/extensions/develop/concepts/messaging

Validate untrusted messages and sender identity. Different entry points have different trust.

## P1 — Python3.12 getpass
**Kind:** OFFICIAL_WEB

https://docs.python.org/3.12/library/getpass.html

No-echo input; GetPassWarning means fallback can echo. Treat warning/no controlling TTY as refusal, not fallback.

## P2 — Python3.12 urllib.request
**Kind:** OFFICIAL_WEB

https://docs.python.org/3.12/library/urllib.request.html

Standard-library HTTPS client. Plan-specific policy disables proxy inheritance and redirects and bounds bytes/time.

## P3 — SQLite atomic commit
**Kind:** OFFICIAL_WEB

https://www.sqlite.org/atomiccommit.html

Atomic transaction principle; no claim of hardware/power-loss durability beyond actual platform evidence.

## P4 — WebSocket server API
**Kind:** OFFICIAL_WEB

https://websockets.readthedocs.io/en/stable/reference/asyncio/server.html

Use existing locked websockets17.1 in repo. Browsed stable documentation identifies17.0.1; verify installed17.1 hook signatures with local tests, do not replace the lock based on page version.

## P5 — JSON canonicalization RFC8785
**Kind:** OFFICIAL_WEB

https://www.rfc-editor.org/rfc/rfc8785

Canonical bytes and domain-separated hashes; preserve existing NFC-rejection policy rather than normalize during hashing.

## P6 — HTTP semantics RFC9110
**Kind:** OFFICIAL_WEB

https://www.rfc-editor.org/rfc/rfc9110

Retry-After supports delta seconds and HTTP dates; this plan defines bounded retry admission.

## W1 — Microsoft WSL networking
**Kind:** OFFICIAL_WEB

https://learn.microsoft.com/en-us/windows/wsl/networking

Windows access to WSL apps through localhost, subject to environment. Must test actual Chrome/WSL topology; never widen listener to0.0.0.0 as fallback.

## Supplied project sources
- `04_LIVE_PLAN.md` and `07_LIVE_IMPLEMENTATION_TASKS.md`: retain LV-01..LV-07 goals, one fixture then3/5, exact links, no model/transactions, observed evidence before activation.
- `NEXT_LIVE_INPUTS.md`: seven external-input requirements, dedicated profile, API budget and separate read-only run.
- Prior Part A pack: immutable historical input, not rewritten by this package.

## Explicit NEW DESIGN decisions (not provider promises)
PB task decomposition; fastest-active shared batching for <=5; a600-request session cap;6/minute local rate cap; two post-FT checks; first probe20 calls; DOM-only first capture adapter; typed live store/wire separate from synthetic-only contracts; freshness displays; finite authorization stages; ephemeral key entry. These are implementation choices in this package.

## Corrections to the earlier recommendation
15-second polling reduces the application's sampling interval, not guaranteed data age by a factor of two. Embedded fields may be absent/delayed despite endpoint support. Five concurrent fixtures can share calls only while watched in one batch/window; five sequential matches do not cost one match's quota. Statistics freshness is not implied by the fixture poll period. Every retry/fallback/setup call is budgeted.
