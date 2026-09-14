# Semantic validation beyond JSON Schema

JSON Schema validates record shape. These additional checks are mandatory and have named owners. Schema validity, a boolean flag, or the mere existence of an evidence hash never grants live authority.

## Config and source records — PB-01, PB-05, PB-11

- A real run requires selected fixture IDs. IDs are unique; their count cannot exceed the accepted max_matches stage. Fallback IDs must be a subset of selected IDs. When fallback is disabled its ID list must be empty.
- Real profile/platform/review paths must exist and match the admitted hashes. A disabled draft may contain missing external values. Paths must not escape the designated private evidence root or traverse symbolic links.
- Reject bool where an integer is required. Canonical decimal strings fit signed 64-bit storage. Scores above the engineering limit of 100 reject; do not clamp them. Home and away IDs differ. Names are bounded display data and never identity keys.
- A VERIFIED FixtureBinding requires actual evidence and exact source ID/competition/date/participant matching. Only exact approved origin/path entries are admitted; do not expand to an unreviewed regular expression.
- Odds use Decimal, are finite and strictly greater than 1, and have at most six fractional digits. A book contains exactly three distinct HOME/DRAW/AWAY selections for one market, horizon and binding revision. Display-coherent evidence is not an accepted wager price or native atomic revision.
- Provider update time remains null unless an actual verified field supplies it. fixture.timestamp is kickoff, never last-update time. Events missing/null are UNKNOWN_SECTION; an observed empty array is OBSERVED_EMPTY. Missing fixtures never become 0–0 records.
- Existing synthetic accounting records must never enter a live stream. ET/BT/P/AET/PEN cannot authorize normal-time FT settlement. Unknown status/detail is visible rather than coerced into a familiar state.

## Direction and role matrix — PB-08, PB-12

HELLO and READY originate from the client. WELCOME and READY_ACK originate from the backend. CAPTURE_BATCH, HEALTH and STOP_CAPTURE are restricted to the CAPTURE_PRODUCER client. WATCHLIST_ADD, WATCHLIST_REMOVE, SELECT_ACTIVE, REFRESH and STOP_SESSION are restricted to the UI_SUBSCRIBER after an explicit user action. ACK, NACK and PROJECTION originate from the backend. PING/PONG are allowed in both authenticated directions.

CAPTURE_BATCH accepts only MarketBook operator events, despite the general record schema also defining ProviderState. A browser cannot inject provider state or backend CONTROL events. Every captured book must fit the admitted profile, tab, binding and fixture. Recompute canonical content hashes and MACs; never trust a supplied checksum as validation.

## Local intent records — PB-14

The exact schema is `assets/contracts/live_readonly/v1/run-intent.schema.json`. The local ledger DDL is `intent-store.sql`. The user-terminal launcher owns consumption, under a committed SQLite transaction before network/capture. A key's presence does not replace intent validation or the user's confirmation.

Check issued_at <= now <= expires_at and expires_at - issued_at <= 15 minutes for start. Reject source/config drift, stage mismatch, duplicate consumption and unsupported scope. PROVIDER_PROBE is at most 20 attempts/300 seconds with no operator URL. OPERATOR_DISCOVERY is at most 600 seconds/one exact tab URL with zero provider attempts. LIVE_READ_ONLY is at most 7200 seconds/600 attempts and additionally requires admitted provider, capture, platform and current security evidence.

The consumed record contains only intent/run/source/config/stage/time and `LOCAL_TTY_USER_CONFIRMATION`; it never claims an independent signature. If the host controller also requires signed authorization, that real authorization must be supplied and verified. Local confirmation cannot bypass it.

## Quota bootstrap and accounting — PB-03, PB-18

Count actual local attempts independently of vendor billing. The first user-approved, reserved /status call may discover quota. An unsuccessful quota discovery cannot authorize fixtures polling. Use the exact reserve and retry rules in `02_PROVIDER_AND_BUDGET.md`.

Status may be unbilled by the provider but still counts as one local attempt. Observe remaining-quota changes where possible; unrelated usage of the same account can also change them. Request estimates are planning arithmetic, not an invoice or proof of the user's subscription. Embedded event/detail availability is tested per selected coverage; missing sections do not automatically trigger extra calls.
