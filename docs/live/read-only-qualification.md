# Recorded one-fixture qualification

Status: WAITING_REVIEW and WAITING_MATCH_WINDOW. No real session has run.

After current PB-20 admission and a separate user-terminal confirmation for one
fixture, at most 120 minutes and 600 attempts, the existing launcher starts the
shared read-only service. It initially displays WAITING_FOR_DATA. In that terminal,
compare the exact fixture, FT market and HOME/DRAW/AWAY selection IDs and type
`CHECK fixture_id home_price draw_price away_price` using the three visible prices.
Record at least three distinct current captures, at least 30 seconds apart.
The service refuses stale, duplicate, mismatched and out-of-scope checks.
These are user observations, never independent security approval.

Stop with the panel STOP control or Ctrl-C in the owning terminal. Then run:

```sh
uv run --frozen --offline python tools/qualify_live_readonly.py --run-dir .local/part-b/live-one
```

The qualifier replays the closed SQLite journal into a new sibling directory,
compares original config/intent bytes, fixture bindings, external start reviews,
durable intent consumption, global quota rows and recorded manual comparisons.
Missing authority or synthetic labels produce HOLD. The source database and old
receipts remain unchanged. Replaying alone does not qualify a real session.

Qualification requires an observed in-progress period. A 15-minute session is the
target, within the user's chosen bound. Goals, cards, suspensions and recovery
drills are NOT_OBSERVED unless actual records show them. FT qualification does not
qualify H1/H2 settlement. Models remain disabled and MONEY_READY is NO.
