# Betting-helper — Part B: Live Read-Only, batched API-Football

Gói này thay thế **phần B cũ** về polling/config/task breakdown, không viết lại Part A và không mở Part C. Đây là thiết kế và implementation plan, không phải source đã triển khai.

**Mục tiêu:** một trận thật với football state + FT H/D/A từ Mise-o-jeu trong Side Panel; lưu/replay được; sau nghiệm thu mới mở lên 3 và 5 trận. H1/H2 hiện khi market đã được xác minh. Chưa tính xác suất, EV, gợi ý cược hoặc Cashout.

**Cách dùng:** đưa toàn bộ gói cho Codex tại checkout Betting-helper và dùng `CODEX_PART_B_AUTORUN_PROMPT.md`. Model đang cấu hình được giữ nguyên. Các task code/mock tự tiếp tục; cần bạn ở các checkpoint nguồn thật, không phải sau mỗi task.

## Đọc theo thứ tự
1. `01_SCOPE_AND_MIGRATION.md`
2. `02_PROVIDER_AND_BUDGET.md`
3. `03_KEY_GUIDE_VI.md`
4. `04_LIVE_CONTRACTS.md`
5. `05_OPERATOR_AND_UI.md`
6. `06_EVIDENCE_AND_RUNS.md`
7. `IMPLEMENTATION_PLAN.md` và task đang làm trong `tasks/`

**API_FOOTBALL_KEY:** chưa cần trong các bước code/mock. PB-18 mới yêu cầu bạn nhập vào terminal riêng bằng công cụ getpass được PB-02 xây và kiểm thử. Không paste key vào Codex/ChatGPT; không commit `.env`; không đưa key vào extension. Key dùng trong process backend, hết process phải nhập lại.

**Polling:** một backend poller cho cả watchlist; `/fixtures?ids=...`; hiệp 1/2 mỗi 15 giây, nghỉ giữa hiệp mỗi 60 giây, trước trận mỗi 60 giây; events fallback tắt mặc định. API hỗ trợ tối đa 20 IDs/request theo nguồn chính thức; sản phẩm giai đoạn này vẫn giới hạn 1 → 3 → 5.

**Quota:** gợi ý Pro direct nếu cần theo dõi trọn trận; plan không mua hộ. Ngân sách ứng dụng đề xuất: 6.000 request/ngày, 600/phiên, 6/phút, một request in-flight. Thực tế phải đối chiếu quota tài khoản trước khi chạy. Khoảng 485 calls cho nhóm trận cùng cửa sổ 120 phút ở chu kỳ 15 giây, chưa retry/fallback; không nhân đồng thời nhưng phải cộng cửa sổ nối tiếp.

**Trạng thái cuối có thể đạt:** `LIVE_READ_ONLY_PASS` cho đúng scope đã chạy. `MONEY_READY=NO`, `MODEL_ENABLED=false`, không tự chuyển Part C.

**Giới hạn:** các selectors/operator IDs hiện chưa được quan sát; task PB-19 bắt buộc thu mẫu sanitize. Gói không giả định capture toàn catalog. Metadata/DOM hiện tại không chứng minh odds đủ mới để dùng tiền thật.
