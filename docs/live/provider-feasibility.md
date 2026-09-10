# Provider feasibility — PB-18

Status: WAITING_FOR_USER_SECRET for a fresh user-terminal diagnostic probe;
the provider fixture ID remains unverified. PROVIDER_PROBE_PASS: FAIL.
Two user-confirmed runs each attempted STATUS once and stopped with SCHEMA_ERROR.
KEY_CHECK remains NOT_CHECKED, not FAILED; neither a bad credential nor a provider
outage has been established. No raw response was retained, so the failed validator
cannot be recovered from those old records. Real attempts by this worker: 0.

The client now reports a fixed PROVIDER_DIAGNOSTIC validator label through both
lookup and exact-fixture probes. It never includes provider values, raw JSON,
headers or exception text. This change preserves rejection, quota, retry and
authorization rules; it does not claim to repair an unobserved response shape.
Old failed observations remain in their private run directories. A fresh intent
and own-terminal confirmation are required to observe the new diagnostic.

User-selected scope: Champions League 2026/27, Bayern München – Bodø/Glimt,
2026-09-10. Public API documentation identifies league 2 and season 2026;
the fixture ID is not guessed. The tested lookup-only path in
`docs/runbooks/START_LIVE_READ_ONLY.md` can obtain candidate IDs in the user's
terminal after an exact league/season/date confirmation. It permits only STATUS
and LOOKUP, never BUNDLE or events, and remains PARTIAL until a separately
confirmed exact-fixture probe passes. Key presence grants no request authority.

PB-17's complete mock gate passed at commit
`180da4b19beae2c10bc2adc06cc98fdc181a94d3`; the immutable result is
`.local/part-b/mock/result.json`. This verifies code, synthetic Windows browser
observations and Part A regressions, not account access or real source coverage.

Before running a probe, choose the API-Football league ID, season and one fixture
ID. Keep the Windows Chrome → WSL2 selection. In the user's own WSL terminal:

```bash
cd /home/thenam176/betting-helper/discovery-runtime-part-b
uv run --frozen --offline python tools/configure_live_batched.py --platform WINDOWS_CHROME_WSL2 --output config/live.local.json
uv run --frozen --offline python tools/prepare_part_b_intent.py --stage provider-probe --config config/live.local.json --output .local/part-b/intents/provider-probe.json
uv run --frozen --offline python tools/run_with_api_football_key.py --action probe --config config/live.local.json --intent .local/part-b/intents/provider-probe.json
```

The configuration command asks only for the remaining nonsecret IDs. It creates
a disabled configuration and refuses to overwrite one by default. The intent
expires after 15 minutes, binds the current source/config bytes, and is consumed
once before I/O. Code changes require a fresh intent; do not reuse an old one.

Phần code kiểm tra API đã sẵn sàng. Bạn mở dashboard API-Football, vào
Account → My Access để lấy API key. Không gửi key vào cuộc trò chuyện. Mở
terminal WSL của riêng bạn tại checkout Betting-helper và chạy lệnh bên trên.
Công cụ sẽ hỏi key mà không hiển thị ký tự. Sau khi xong, chỉ gửi trạng thái
KEY_CHECK/PROBE_RESULT, không gửi key, header hoặc toàn bộ `/status` response.

The launcher previews the exact scope and requires `ALLOW PROVIDER PROBE` before
reading the key. No TTY/no-echo means refusal. `uv --offline` prevents dependency
downloads; it does not make the explicitly confirmed probe an offline operation.
The probe is bounded to 20 attempts and 300 seconds, including reservations and
retries. Authentication failure stops requests. No purchase or subscription
upgrade is performed by the worker.

The fixed sequence checks projected status/quota, selected league coverage and
two fixture bundles. Its private evidence preserves normalized observations,
section missingness, timing and safe request outcomes. Fallback is OFF; an
events comparison has not been approved or executed. A successful small probe
does not authorize operator observation or the separate live session. Insufficient
quota or missing sections remain explicit PARTIAL results.

The selected real account, fixture coverage, request timings and source latency
have not been observed. The 15-second poll period is not a latency guarantee;
unknown source-update age remains UNKNOWN, and fixture timestamp is kickoff.
