# Cài Betting Helper Part B trên máy Windows/WSL2 này

Gói candidate gồm Chrome extension và launcher. Backend dùng checkout WSL2
`/home/thenam176/betting-helper/part-b-candidate` hiện có, distro `Ubuntu`.
Không cài dependency mới, không đổi firewall, chính sách Chrome hay thiết lập Codex.

1. So sánh SHA-256 của ZIP với sidecar `.sha256`, rồi giải nén ZIP.
2. Trong thư mục `BettingHelper`, chạy `Install.cmd`. Trình cài kiểm tra từng file,
   lưu vào `Documents\BettingHelper\<commit>` và tạo shortcut riêng trên Desktop.
   Một thư mục đã tồn tại sẽ không bị ghi đè.
3. Mở **Chrome trên Windows**, chọn profile **Betting-Helper**, cửa sổ thường.
   Không dùng Guest hoặc Incognito. Chỉ đăng nhập Mise-o-jeu bằng tay.
4. Trong profile đó mở `chrome://extensions`, bật **Developer mode**, chọn
   **Load unpacked** và chọn thư mục `extension` mà trình cài vừa in ra.
5. Ghim extension trên thanh công cụ. Nhấn biểu tượng để mở Side Panel.
6. Mở shortcut Betting Helper, chọn **Lưu hoặc thay API key một lần**.
   Lấy key từ API-Football **Account → My Access**. Nhập tại dòng ẩn trong terminal
   của bạn; không gửi key, header, cookie, mật khẩu, `.env` hoặc JSON tài khoản qua chat.

Key nằm trong Windows Credential Manager của người dùng hiện tại. Các phiên sau
dùng lại key này. Extension, trang web, localStorage và gói ZIP không chứa key.
Không có console/no-echo thì dừng; không có cách nhập thường thay thế.
Thay/xóa key bị khóa khi một phiên đang dùng key. Sau khi thay key phải probe lại;
quota đã dùng không bị đặt lại. Tài khoản Windows khác không dùng chung slot.
Các tiến trình có cùng quyền người dùng hoặc quyền quản trị vẫn nằm ngoài ranh giới
bảo vệ của ứng dụng; không coi Credential Manager là cách cô lập chúng.

Extension dùng `storage`, `sidePanel`, `scripting`, `activeTab`. Quyền đọc trang
Mise-o-jeu được hỏi khi bạn bấm nút đọc trang trong phiên đã được duyệt. Không cấp
quyền cookies, debugger, đọc mọi website hay quyền đặt cược. Nếu máy chặn installer,
giữ nguyên chính sách và báo mã lỗi; không tự đổi chính sách thực thi.

Cài package không cấp quyền API, lấy mẫu hoặc live. Trạng thái
`CANDIDATE_WAITING_REVIEW` trong manifest phải được giữ nguyên cho đến khi có bằng
chứng review thực của host gắn đúng source/config/package. Đọc tiếp RUN_ONE_MATCH_VI.md.
