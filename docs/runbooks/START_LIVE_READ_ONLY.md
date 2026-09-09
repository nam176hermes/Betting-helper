# Future read-only lane: inputs and manual operation

Lane A implements preflight only. Production authority is NONE; money readiness is NO.
No offline synthetic result qualifies observed match data, a real provider, or live security.

Copy config/live.example.json to an ignored local configuration, then run:

```sh
uv run --frozen --offline python tools/live_preflight.py --config config/live.local.json --offline-result .local/offline-slice/acceptance/result.json
```

Exit 2 means pending real inputs/review; exit 1 rejects configuration/evidence.
Preflight checks environment-variable presence only; it never reads the key value,
opens an operator profile, or calls a provider. Its offline verifier opens only owned test profiles.

Required next inputs for separately authorized lane B:

- Accepted browser/OS platform qualification; Linux offline evidence is not Windows qualification.
- Manual operator login in a separately approved dedicated profile. Never paste passwords or cookies into chat.
- Explicit competition and fixture selection.
- Local API_FOOTBALL_KEY provision, actual quota and bounded request budget, provider feasibility/protocol approval.
- Accepted capture profile with exact origin, routes and permitted fields (LV-01).
- Current live protocol/security review and explicit bounded read-only run authorization.
- Current independently verified offline acceptance result with matching source and artifacts.

The future command below is NOT IMPLEMENTED by lane A and must not be run as a current feature:

```sh
python tools/run_live_readonly.py --config config/live.local.json --operator-session .local/live-session.json
```

Future startup is manual and begins WAITING_FOR_DATA. Missing sources stay absent;
stale/conflicting data must remain visibly stale/conflicting, never promoted to fresh.
Manual stop closes only owned processes and retains evidence for read-only diagnosis.
There is no automated wager, Cashout, account mutation, odds recommendation, model or money activation.
