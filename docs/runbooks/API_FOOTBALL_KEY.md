# API_FOOTBALL_KEY — Codex phải hướng dẫn khi nào và như thế nào

## Thời điểm
PB-00..PB-17 dùng mock/synthetic và không cần key thật. PB-02 xây và kiểm thử công cụ nhập kín; **PB-18** mới yêu cầu bạn dùng nó, sau khi API client, quota guard và scoped security tests đã sẵn sàng.
Nếu chưa có key, Codex ghi `WAITING_FOR_USER_SECRET`, hoàn tất các task độc lập còn làm được và giữ checkpoint. Không nhắc liên tục, không thêm key giả để báo live PASS. Có key không đồng nghĩa được chạy session120phút: probe và session có phê duyệt riêng.

## Lời nhắn Codex phải gửi tại PB-18
> “Phần code kiểm tra API đã sẵn sàng. Bạn mở dashboard API-Football, vào Account → My Access để lấy API key. Không gửi key vào cuộc trò chuyện. Mở terminal WSL của riêng bạn tại checkout Betting-helper và chạy lệnh bên dưới. Công cụ sẽ hỏi key mà không hiển thị ký tự. Sau khi xong, chỉ gửi trạng thái KEY_CHECK/PROBE_RESULT, không gửi key, header hoặc toàn bộ `/status` response.”

Dashboard path dựa trên hướng dẫn chính thức[A3]; nếu giao diện đổi, Codex hướng dẫn bạn dùng mục API key tương ứng, không tự đăng nhập tài khoản hoặc xin mật khẩu. Gói Pro direct là đề xuất cho phiên đầy đủ, không phải bắt buộc để viết code hoặc thực hiện probe nhỏ; đối chiếu quota còn lại trước probe.

## Lệnh dự kiến do PB-02/PB-14 triển khai
PB-02 đã tạo và kiểm thử launcher nhập kín. Các dispatcher và intent do PB-14 hoàn thiện; chỉ dùng các lệnh dưới ở PB-18 sau khi toàn bộ gate mock đạt. Thiếu runtime owner phải từ chối, không hỏi key.

Tại terminal WSL, cd vào checkout thực rồi:

```bash
uv run --frozen --offline python tools/run_with_api_football_key.py --action probe --config config/live.local.json --intent .local/part-b/intents/provider-probe.json
```

`--offline` ở đây chỉ cấm uv tải dependency; action probe vẫn gọi API thật sau xác nhận người dùng/budget. Tool hiện preview fixture scope, tối đa20 HTTP attempts, tối đa5min và yêu cầu bạn gõ `ALLOW PROVIDER PROBE`. Sau đó mới nhập key kín. Không có command kiểu `export KEY=giá_trị` để key lọt shell history.

Khi profile/provider/platform/security đã được chấp nhận, công cụ có action khác:

```bash
uv run --frozen --offline python tools/run_with_api_football_key.py --action live-readonly --config config/live.local.json --intent .local/part-b/intents/live-one.json
```

Action live-readonly phải preview scope/budget và yêu cầu `START READ ONLY`. Không tự chuyển từ probe sang live. Bạn nhập lại key trong process live mới. Backend dừng thì key không được tự lưu để tái sử dụng.

## Secret contract cho implementer
`SecretValue` là object không có serialization, `repr/str` luôn `[REDACTED]`. Provider client nhận object; key không được đưa vào state/config/telemetry. Tool có `--action` enum đúng2 giá trị, không có arbitrary executable/shell.

1. Mặc định `getpass.getpass('API_FOOTBALL_KEY (hidden): ')` trong terminal riêng do người dùng mở. Require controlling TTY; set `warnings.simplefilter('error', GetPassWarning)`. No-echo không sẵn sàng → từ chối; không fallback sang `input()`.
2. Có thể đọc biến môi trường **đúng tên** API_FOOTBALL_KEY nếu người dùng đã cấp cho process riêng. Không gọi `env`, `printenv`, `set`, dump process environment hoặc đọc `.env` tùy ý. Hai nguồn cùng tồn tại: explicit prompt input wins, không log nguồn giá trị.
3. Validation local chỉ loại rỗng, CR/LF/control chars, độ dài vượt512; không hard-code key là32hex. HTTP success mới xác minh credential thật.
4. Không key trong argv, config file, stdout/stderr, URL, exception, Git, clipboard automation, browser, localStorage, storage.session, fixture, report hoặc hash/fingerprint. Masked suffix/length cũng không cần in.
5. Provider process không khởi tạo browser child với env chứa key. Loại API_FOOTBALL_KEY khỏi subprocess env và giữ key in-process khi có thể. Endpoint redirect/proxy không được chuyển key sang host khác.
6. `/status` được project xuống plan/quota/expiry metadata được allowlist; account/email/subscription identifiers cá nhân bỏ ngay, không print raw response.
7. Stop/KeyboardInterrupt đóng HTTP/client, bỏ references; không tuyên bố Python strings đã được secure-zeroized. Memory access bởi người cùng quyền/root không bị ngăn bởi no-echo.
8. Nếu key từng lộ trong chat/commit/log: dừng requests, yêu cầu user regenerate tại dashboard; không chỉ xóa dòng rồi tiếp tục key cũ.

## Output chỉ nên có
```text
KEY_CHECK: AUTHENTICATED | FAILED | NOT_CHECKED
SUBSCRIPTION_CHECK: CONFIRMED | INSUFFICIENT | UNKNOWN
PROBE_RESULT: PASS | PARTIAL | FAIL
REQUEST_ATTEMPTS: số lần gọi thực tế
MISSING_CAPABILITIES: các mã điều kiện còn thiếu
```
Hai dòng cuối là mô tả định dạng; công cụ in số đếm thực và danh sách mã, không in dữ liệu phản hồi thô. Tool exit0 nghĩa probe kỹ thuật đạt scope, không phải LIVE_READ_ONLY_PASS.

## Tests bắt buộc
Mock getpass; mock HTTP; inject fake recognizable test secret. Quét mọi generated log/config/exception/body/artifact và child env: không có secret, URL-encoded secret hoặc secret hash. NoTTY/GetPassWarning từ chối trước I/O; bad redirect không forward header;401 không retry; key presence không tạo accepted evidence; user chưa nhập phrase thì zero requests. Unit fixtures chỉ dùng fake key rõ nhãn TEST_ONLY.
