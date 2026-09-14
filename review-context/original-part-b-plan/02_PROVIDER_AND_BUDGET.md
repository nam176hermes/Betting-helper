# API-Football adapter, batching and quota algorithm

## Evidence versus implementation policy
[A1,A2,A7] document up to20 fixture IDs per `/fixtures?ids=...` request and available embedded detail. [A2,A3] describe15s refresh of fixture/event data. These are not end-to-end delivery SLAs, proof that all fields exist for every match, or an instruction to poll unavailable data forever. PB-18 records actual coverage and payload behavior.

## Direct API boundary
- Fixed HTTPS authority: `v3.football.api-sports.io:443`.
- Header: `x-apisports-key` from a `SecretValue` supplied only to backend HTTP code; never query parameter, user-agent, exception, browser, URL or artifact.
- GET only. Use existing Python stdlib `urllib.request`; no new HTTP dependency. Explicit `ProxyHandler({})`, standard verified TLS context, no redirect following, `Accept-Encoding: identity`, socket timeout10s, decoded response limit8MiB. Status/login response fields containing account names/email never leave memory.
- Run blocking I/O in one owned worker, await completion; never spawn unbounded retries/threads. At most one in-flight provider request across poller, probes, manual refresh and fallbacks.
- Allowlisted API calls below only. No `/predictions`, bookmaker odds, players/standings endpoints, arbitrary URL or all-league background polling.

| Purpose | Request | Cadence/limit |
|---|---|---|
| account feasibility | `/status` | once at probe/start and when a quota inconsistency demands it; reserve1 local budget even if provider does not bill it |
| league coverage | `/leagues?id={positive_int}&season={year}` | once per approved league/season, cache24h |
| user-selected date lookup | `/fixtures?league={id}&season={year}&date={YYYY-MM-DD}` | only on explicit search, cache60s, selected league only |
| watched details | `/fixtures?ids={sorted_unique_IDs_joined_by_hyphen}` | one global poller,1..20 IDs/API request; runtime watchlist<=5 |
| event fallback | `/fixtures/events?fixture={selected_id}` | OFF default; only a probe-demonstrated need and explicit profile/config approval;60s per fallback fixture |

The `ids` request includes a single ID too; never accidentally use league IDs. Pagination is inspected. A detail response with multiple pages or unexpected IDs is invalid, not silently truncated. Date lookup has a user-approved paging cap; no unbounded page loop.

## Response-to-state mapping
Validate the response wrapper and nonempty `errors` even for HTTP200. Empty list/dict errors mean no declared provider error; all other shapes reject. Map error to finite code, never log arbitrary provider messages. Check each returned fixture ID is selected, unique and of integer-not-bool type; compare league/season and participant identity to accepted binding.

Retain only:
- fixture.id; fixture.date/fixture.timestamp as **kickoff**, never source update time;
- status.short; elapsed/extra as nullable source minutes; no invented seconds;
- league.id/season; teams.home/away.id and bounded display names;
- goals.home/away; score.halftime/fulltime, separately nullable nonnegative integers;
- permitted event rows: elapsed/extra, team.id, optional player.id/assist.id, event type/detail mapped to closed enums;
- embedded section availability enums for events/lineups/statistics/players; drop detailed player/stats payload in Part B after checking availability.
Provider transport can carry unknown extra fields; project a strict output instead of rejecting the entire API response merely for unrelated new fields. Malformed REQUIRED fields reject that fixture. No API key/headers/account fields/HTML/remote logos are retained.

A response omitting fixture B does not erase A/C or treat B as0–0. A/C may update individually with one shared batch observation ID; B records MISSING_IN_RESPONSE and eventually becomes STALE. Never combine provider and operator participants by display order.

## Events and corrections
Embedded events missing/null = UNKNOWN_SECTION, not empty timeline. Empty array is OBSERVED_EMPTY; not evidence to activate fallback. For received arrays, normalize permitted fields, sort deterministically and preserve multiplicity. Digest the full normalized multiset and issue a new local revision only when it changes; retain a separate observation receipt even when unchanged. Provider event IDs are not invented when absent.
Reordered equal arrays have same semantic digest. A removed/modified goal/card produces CORRECTION or EVENT_SET_CHANGED and invalidates the match context. Do not promise unique real-world incident matching from minute/team/type alone. Direct red and second-yellow dismissals use player IDs and profile-tested rules; ambiguous duplicates/missing player info yield red_card_state=UNKNOWN, not an inferred zero/count. Last-known score and timeline are independently retained; disagreement is visible. Unknown event detail maps OTHER with a quality flag; never execute a string.

## Deterministic status/cadence table (project policy)
- NS: PREGAME. >=10min before scheduled kick-off:60s. Within10min:30s.
- 1H/2H: H1/H2;15s.
- HT: HALFTIME;60s.
- FT: preserve regular-time score; schedule2 confirmation observations at+30s and+120s from first observed FT, then stop. These checks do not guarantee all future corrections are captured.
- SUSP/INT: BLOCKED_DISPLAY;60s; keep last state explicitly blocked.
- PST/CANC/ABD/AWD/WO: TERMINAL_UNSUPPORTED; stop after current record, no automatic betting settlement.
- ET/BT/P/AET/PEN: OUT_OF_SCOPE_NORMAL_TIME; retain visible source state but stop WDL-market eligibility. Do not substitute extra-time/final score for normal-time FT.
- TBD/LIVE/any unknown code: UNKNOWN_PERIOD;60s for at most5min then stop that fixture and report; never infer H1/H2 from clock alone.

## One poller for the watchlist
Backend owns the selected-ID set; UI subscribes, never owns polling. Sort unique numeric IDs. Runtime limit stages1,3,5 are separate accepted scopes; protocol capacity20 is not permission to enable20 users/fixtures.
For <=5 IDs, at every successful poll select the earliest next deadline of ANY active fixture and fetch ALL selected non-stopped IDs in one request. Thus an HT fixture may be refreshed at15s while another fixture is playing; this is intentional and still one call. Terminal confirmation is included in an existing batch when due; otherwise it schedules its own bounded call. Removing a fixture stops its future inclusion but does not delete history.
No catch-up burst: after slow response/sleep/restart choose next eligible future deadline; do not replay missed HTTP polls. On wake mark previous observations stale, then fresh poll when budget allows. Native monotonic clock controls schedule; UTC is used only for display/quota-day reconciliation.
Cache is a per-source revision/response cache, not a way to renew source freshness. A re-render or panel open causes no API request. Manual refresh is coalesced with next shared request, respects the same minimum gap and budget, and does not create a second poller.

```python
# Design pseudocode: fixture state deadlines are stored by the scheduler owner.
ids_to_fetch = sorted(set(watched) - stopped)
if not ids_to_fetch:
    return STOPPED
if now < next_global_due or request_in_flight:
    return WAIT
# Budget reservation commits BEFORE I/O; every retry is another reservation.
if not quota.reserve_attempt(now, scope_id, purpose='BUNDLE'):
    return BUDGET_PAUSED
response = await client.get_fixture_bundle(ids_to_fetch)
apply_per_fixture_observations(response)
next_global_due = max(now_after_response + 10, earliest_fixture_deadline())
```

## Quota policy
Default planned Pro budget: daily app soft cap6000, session hard cap600, sliding60s local cap6, minimum inter-request start gap10s, in-flight1. Per-plan API limits come from observed status/headers, not constants granting entitlement. First probe <=20 attempts over<=5min, fixture poll30s, exact selected scope.
For normal polling, effective available requests = min(local remaining day, local remaining session, max(0, observed provider daily remaining - ceil(0.20 * observed provider daily limit))). The 20% provider-quota reserve is a fixed share of the observed daily allocation, not a repeatedly compounded percentage of remaining quota. The independent 20% retry reserve in preflight inflates a predicted request count; it is not a second subtraction from provider quota. Failed calls, retries, timeouts and redirects all consume an **attempt reservation**, even when billing is uncertain. Same credential slot across processes shares one durable ledger and lock; two backends cannot each claim the full daily cap. Slot name is `api-football-primary`, not a hash of the secret.
Daily boundary: keep local buckets keyed by UTC day but do not infer new provider quota merely from local midnight. Refresh quota evidence and reconcile server headers; wall-clock rollback or unexplained remaining-count increase triggers reconciliation, not automatic allowance. Keys can be used outside the app, so provider-reported remaining caps the local estimate. Never auto-upgrade plan or raise config cap after429.
Persist reservation before I/O and finalize outcome after; crash/unknown outcome is NOT refunded. One reservation row per attempt, idempotent UUID. A single poller lock owner is required per ledger. Rolling-minute attempts are counted including probes/manual refresh/fallbacks.

Header names, case-insensitive [A1]: `x-ratelimit-requests-limit`, `x-ratelimit-requests-remaining`, `x-ratelimit-limit`, `x-ratelimit-remaining`. They are distinct daily/minute fields, not aliases. Bootstrap exception: after explicit user confirmation, one budget-reserved `/status` attempt is permitted when no provider quota evidence exists. It consumes the probe allowance and the local minute/day ledger. If valid daily quota cannot be established from its projected response/headers, stop the probe as QUOTA_UNKNOWN; do not issue fixture calls. Malformed/missing quota evidence prevents a normal polling session; a previously confirmed bounded balance can continue conservatively within its remaining reservation, never assume the purchased plan.

## Retry behavior
401/403 or auth body error: stop provider, emit AUTH_FAILED, ask user to check key/subscription; no loop. Parameter/schema error: stop that request family and show finite code. Empty legitimate response is not automatic retry.
429: honor Retry-After delta/date; without it wait60s.5xx/499/timeout: at most2 retries after the original; earliest retry delays2s then4s+jitter0..250ms, further restricted by10s minimum gap/6per60s. Every retry consumes quota. If delay exceeds run deadline, stop; do not send early. Persistent failures yield STALE and a circuit-open60s; max3 failed cycles then require explicit user restart. No overlapping calls.

## Fallback events
OFF initially. PB-18 can compare at most2 explicitly budgeted `/fixtures/events` calls with bundled details when section quality is unknown. Neither array emptiness nor lack of a goal by itself activates fallback. An accepted fallback profile names exact fixtures, observed reason,60s cadence, expiry, additional quota. The preflight recomputes budget and can refuse insufficient600 cap rather than increasing it. Direct event feed cannot automatically override conflicting bundle score.

## Request arithmetic, not SLA
Periodic count over half-open interval[0,T): ceil(T/d). The t0 call is included; do not add it twice. For a120min constant15s window:480 bundle calls. Conservative example adds3 setup calls and2 terminal confirmation calls:485.20% reserve gives582, fitting600.
Five simultaneously monitored fixtures in one group can still be485 TOTAL with these assumptions. Five separate120min windows cost approximately2425. Staggered games cost the union of active monitored windows, not exactly480/day. Fallback60s for n fixtures over120min adds120*n calls;5fallback fixtures add600, so the default600 session cap must reject that configuration.
Adaptive illustrative window:10min at60s +100min at15s +15min HT at60s =425 periodic; +5 overhead=430. It is a125min illustration, not a promise that every match lasts that long. The120min session cap requires renewed user duration approval if exceeded.
Expected data sampling wait from our poll alone may fall when changing30s→15s; unknown provider latency and caching remain. No claim of twice-as-fresh match facts.
