# Start and stop Part B read-only

Run from the Part B checkout with the locked environment. Use a new evidence
directory for every verification. This runbook supplies no live authorization.

```sh
uv run --frozen --offline python tools/verify_part_b.py --profile release --output .local/part-b/release
```

The release command runs mock and isolated Windows Chrome/WSL2 checks and reports
external gates separately. Exit 2 with HOLD is expected when real inputs are
missing. It never reads a key or starts an authenticated source.

If the API-Football fixture ID is unknown, prepare a lookup-only disabled config:

```sh
uv run --frozen --offline python tools/configure_live_batched.py --output config/live.local.json --platform WINDOWS_CHROME_WSL2 --league 2 --season 2026 --lookup-only
uv run --frozen --offline python tools/prepare_part_b_intent.py --stage provider-probe --config config/live.local.json --lookup-date 2026-09-10 --output .local/part-b/intents/fixture-lookup.json
uv run --frozen --offline python tools/run_with_api_football_key.py --action probe --config config/live.local.json --intent .local/part-b/intents/fixture-lookup.json
```

This exact example is Champions League 2026/27 on 10 September 2026. It permits
only status and one league/season/date lookup, at most 20 attempts/300 seconds
including retries. The terminal prints validated fixture IDs/names; it never
automatically selects a match or starts the fixture probe. Successful lookup
returns PARTIAL/exit 2 because selected-fixture feasibility is still untested.
Choose Bayern München – Bodø/Glimt from the actual returned identities. Share
only that nonsecret fixture ID if continuing in chat. Use a fresh intent name
if an old preview expired or was consumed; do not overwrite old evidence.

After the real API-Football fixture ID is known, create a disabled config with
`tools/configure_live_batched.py`. Its user-terminal prompts accept only nonsecret
platform, league, season and fixture choices. Choose WINDOWS_CHROME_WSL2.
If replacing the lookup-only config, explicitly pass `--replace` and the exact
selected `--fixtures` value; all quotas remain unchanged.
Prepare a fresh intent immediately before the intended probe:

```sh
uv run --frozen --offline python tools/prepare_part_b_intent.py --stage provider-probe --config config/live.local.json --output .local/part-b/intents/provider-probe.json
uv run --frozen --offline python tools/run_with_api_football_key.py --action probe --config config/live.local.json --intent .local/part-b/intents/provider-probe.json
```

Bạn lấy key tại API-Football **Account → My Access** và chỉ nhập trong terminal
WSL của chính bạn. Không gửi key, header, cookie, mật khẩu, raw/status JSON hoặc
`.env` vào chat. Launcher hiển thị phạm vi và yêu cầu `ALLOW PROVIDER PROBE` trước
khi đọc key bằng no-echo. Không có TTY/no-echo thì dừng. Tối đa 20 attempts/5 phút;
mọi retry đều tính phí quota. Không tự mua hoặc nâng cấp gói.

For operator observation, first obtain the separate reviewed fixed-tool scope,
dedicated manually logged-in profile, exact chosen tab and at most ten-minute
permission. No guessed selectors or draft profile may be activated. See
`docs/live/operator-capability-report.md` for the current bootstrap limitation.

Only after accepted real provider/profile, current platform/mock evidence and
actual external host security review, bind an enabled config to those hashes.
Check it offline:

```sh
uv run --frozen --offline python tools/live_preflight_batched.py --config config/live.local.json
```

Then prepare a new live-readonly intent with the exact reviewed operator URL(s)
using `--operator-url`. For the first scope, one fixture only:

```sh
uv run --frozen --offline python tools/prepare_part_b_intent.py --stage live-readonly --config config/live.local.json --output .local/part-b/intents/live-one.json --operator-url https://EXACT_REVIEWED_OPERATOR_MATCH_URL
uv run --frozen --offline python tools/run_with_api_football_key.py --action live-readonly --config config/live.local.json --intent .local/part-b/intents/live-one.json
```

The URL above is a placeholder, never an observed selector or approved tab.
The launcher requires `START READ ONLY`. Paste the short-lived local pairing
ticket only into the extension panel; it is distinct from the provider key.
The extension key never enters the provider backend's HTTP header. Start at
WAITING_FOR_DATA, use CHECK for three time-separated FT comparisons, and treat
STALE/CONFLICT/UNKNOWN as unavailable evidence. Source-age UNKNOWN stays unknown.

Pause a fixture with the shared watchlist control. STOP or Ctrl-C ends the owned
session and closes its journal. After an extension worker restart, type PAIR in
the same terminal for a fresh local pairing ticket. No catch-up burst or silent
new session follows sleep or restart. Use the closed-run qualifier only after
shutdown; see `docs/live/read-only-qualification.md`. Three/five need separate
preceding acceptance and confirmations. MODEL_ENABLED=false, MONEY_READY=NO.
