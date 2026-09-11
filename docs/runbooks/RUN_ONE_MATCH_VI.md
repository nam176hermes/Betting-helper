# Một trận thật, chỉ đọc

Mở shortcut Betting Helper trên Windows. Key chỉ cần lưu một lần bằng menu Windows.
Chọn **Mở ứng dụng / tiếp tục** để vào backend WSL2 trong cùng terminal của bạn.

1. Chọn **Chọn 1 trận mới để probe**, nhập league ID, season và fixture ID chính xác
   của API-Football. Cấu hình mới giữ toàn bộ giới hạn quota và để live tắt.
2. Chọn **Probe provider**. Kiểm tra fixture, thời hạn 300 giây và tối đa 20 attempts,
   rồi tự gõ `ALLOW PROVIDER PROBE`. Launcher đọc key đã lưu sau xác nhận này.
   Có key hoặc chọn trận không tự cấp quyền gọi API.
3. Chọn **Kiểm tra các điều kiện còn thiếu**. Worker/controller phải hoàn thành
   hồi quy, sealed pack và review độc lập thực của host cho candidate hiện tại.
   Probe PASS cũ, dữ liệu giả và một câu đồng ý trong chat không thay thế review.
4. Để lấy mẫu lần đầu: mở đúng tab Mise-o-jeu trong Chrome Windows, profile
   Betting-Helper. Dùng menu **Lấy mẫu trang**, cung cấp URL chính xác và đường dẫn
   review công cụ đã được host cấp. Sau khi review được xác minh, tự xác nhận
   `ALLOW OPERATOR OBSERVATION` cho tối đa 10 phút. Không đoán selector hoặc ID.
5. Profile chỉ được chấp nhận khi bằng chứng DOM thật có đủ H/D/A, đội nhà/khách,
   market/horizon và binding đúng fixture. Cần review profile, platform hiện tại,
   provider hiện tại và review bảo mật live riêng. Chọn cấu hình đã được review
   bằng menu **Chọn cấu hình đã được review**; launcher không tự bật live.
6. Chọn **Chạy live chỉ đọc**, kiểm tra phạm vi một fixture, tối đa 120 phút/600
   attempts, rồi tự gõ `START READ ONLY`. Dán mã ghép nối mà terminal in vào Side
   Panel. Đây là mã phiên ngắn hạn, không phải API key. Bấm **Đọc trang đã được duyệt**
   trong đúng tab. Nếu cần mã mới, gõ `PAIR` trong terminal; không mở backend thứ hai.
7. Đối chiếu ba lần H/D/A FT bằng quan sát của bạn, cách nhau ít nhất 30 giây.
   Gõ `CHECK <fixture_id> <H> <D> <A>` trong terminal. Không dùng dữ liệu backend làm
   đáp án đối chiếu. Giữ phiên quan sát đủ cửa sổ kiểm thử đang thi đấu được yêu cầu.
8. Bấm **Dừng phiên**. `CLOSED_PENDING_REPLAY` nghĩa là đã đóng và còn phải replay.
   Dùng menu **Replay phiên đã đóng** với thư mục mà terminal in ra. Chỉ kết quả
   qualification nguồn thật mới có thể cấp `LIVE_READ_ONLY_PASS_ONE`.

Side Panel và workspace dùng chung watchlist/backend. Tạm dừng giữ giá cuối cùng;
mất kết nối phải hiển thị dữ liệu cũ/UNKNOWN. Nhịp API là 15 giây khi 1H/2H, 60 giây
khi HT/trước trận, 30 giây gần kickoff; đây không phải cam kết độ trễ nguồn.
Timestamp kickoff không được diễn giải thành thời điểm cập nhật dữ liệu.

Nếu còn thiếu input: `WAITING_FOR_USER_SECRET`, `WAITING_OPERATOR_SAMPLE`,
`WAITING_PLATFORM`, `WAITING_REVIEW` hoặc `WAITING_MATCH_WINDOW` phải giữ nguyên.
Worker chỉ cần các ID/URL/đường dẫn bằng chứng không bí mật và những xác nhận có
phạm vi trên. Bạn không cần gửi key hoặc JSON tài khoản.

Scope 3 và 5 trận cần xác nhận và run gate riêng. MODEL_ENABLED=false;
MONEY_READY=NO. Không có authority đặt cược, auto-trading, Cashout hoặc Part C.
