# Provider feasibility — PB-18

Status: PROVIDER_PROBE_PASS. KEY_CHECK: AUTHENTICATED.
SUBSCRIPTION_CHECK: CONFIRMED. Exact-fixture PROBE_RESULT: PASS.
The user-confirmed run for fixture 1635632, Bayern München - Bodo/Glimt,
completed STATUS, COVERAGE and two BUNDLE requests in four attempts within its
300-second limit. Network-free evidence admission accepts the retained real
observations against the current source and unchanged provider scope.
The preceding two-request lookup supplied the exact fixture identity, league 2,
season 2026 and kickoff 2026-09-10T19:00:00Z.

The status projection observed an active PRO plan with limit 7500/day and 7499
remaining at that observation. These are observed values, not a promise of quota
remaining later. Provider acceptance is freshness-bound and is rechecked before
live admission. Worker real attempts: 0. The local configuration remains disabled;
operator observation and live sessions require their own gates and confirmations.
Actual cumulative counts, hashes and immutable references are in the checkpoint.

The status parser previously assumed results == 1. STATUS carries an object,
so results is now checked as bounded nonnegative integer metadata; authentication
requires validated subscription and request-quota fields. Fixture/list counts,
paging, errors, secret-echo rejection, reservations and retry limits stay enforced.
Expiry accepts dates and ISO timestamps with timezone; absent/invalid expiry stays
unknown and grants no authority. The timestamp form appears in the provider's
[archived documentation, page 2](https://www.duckweeds7.com/posts/pdf-to-cursor-skills-with-marker/API-Football%20-%20Documentation.pdf),
a third-party-hosted copy dated 2026-02-03, not current live-account evidence.

Fixed PROVIDER_DIAGNOSTIC labels include no provider values, raw JSON, headers or
exception text. Synthetic compatibility cases are distinct from the real failed
response, whose raw bytes were not retained. Old failures remain immutable. The
later real lookup and exact-fixture probe succeeded on the repaired client.
Provider feasibility is accepted for this scope; no live session is authorized.

User-selected scope: Champions League 2026/27, Bayern München – Bodø/Glimt,
2026-09-10. Fixture ID 1635632 was observed in the authenticated provider lookup,
not guessed. The tested lookup-only path in
`docs/runbooks/START_LIVE_READ_ONLY.md` can obtain candidate IDs in the user's
terminal after an exact league/season/date confirmation. It permits only STATUS
and LOOKUP, never BUNDLE or events, and remains PARTIAL until a separately
confirmed exact-fixture probe passes. Key presence grants no request authority.

PB-17's complete mock gate passed at commit
`180da4b19beae2c10bc2adc06cc98fdc181a94d3`; the immutable result is
`.local/part-b/mock/result.json`. This verifies code, synthetic Windows browser
observations and Part A regressions, not account access or real source coverage.

The existing disabled config selects fixture 1635632 and Windows Chrome → WSL2.
Create a fresh exact-fixture intent in the user's own WSL terminal:

```bash
cd /home/thenam176/betting-helper/discovery-runtime-part-b
probe_intent=".local/part-b/intents/fixture-1635632-$(date -u +%Y%m%dT%H%M%SZ).json"
uv run --frozen --offline python tools/prepare_part_b_intent.py --stage provider-probe --config config/live.local.json --output "$probe_intent" &&
uv run --frozen --offline python tools/run_with_api_football_key.py --action probe --config config/live.local.json --intent "$probe_intent"
```

The intent expires after 15 minutes, binds the current source/config bytes, and is consumed
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

Authentication, fixture identity, declared coverage, two bundled observations and
configured-session budget feasibility have been observed. Sustained polling,
in-play transitions and source latency remain unverified. The 15-second poll period is not a latency guarantee;
unknown source-update age remains UNKNOWN, and fixture timestamp is kickoff.
