# ActiveLife Gym · BPM Web Prototype

Prototype mô phỏng quy trình TO-BE MIS3047: đăng ký hội viên, sàng lọc PAR-Q, phân loại mục tiêu, tư vấn, ghép PT, ký hợp đồng, thanh toán giả lập và kích hoạt QR. Đây là ứng dụng demo, không phải hệ thống production.

## Chạy trên Windows / VS Code

### 1. Cài Python nếu lệnh `python` chưa nhận

Cài **Python Install Manager** từ [hướng dẫn Python chính thức cho Windows](https://docs.python.org/3/using/windows.html) hoặc Microsoft Store. Mở lại VS Code sau khi cài. Trong PowerShell chạy `py install 3.13`, sau đó `python --version` để kiểm tra. Nếu `python` vẫn chưa nhận, mở **Manage app execution aliases** trong Start và bật alias **Python (default)**.

### 2. Tạo môi trường và cài thư viện

Mở đúng thư mục dự án (nơi có `main.py`) trong VS Code, chọn **Terminal → New Terminal**, rồi chạy:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Trong VS Code chọn **Python: Select Interpreter** → `.venv\Scripts\python.exe`. Nếu chưa có extension, cài extension **Python** của Microsoft.

### 3. Khởi động

Chạy `.\.venv\Scripts\python.exe main.py` trong PowerShell (không phụ thuộc lệnh `python` toàn hệ thống), hoặc mở **Run and Debug** và chọn **ActiveLife Gym (FastAPI)**. Mở web tại [http://127.0.0.1:8000](http://127.0.0.1:8000), Swagger tại [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs). Dừng bằng `Ctrl+C` hoặc nút Stop trong VS Code.

SQLite tự tạo file `gym_database.db` ở lần chạy đầu. CSDL test nằm trong thư mục tạm và không ghi đè dữ liệu demo.

## Đăng nhập và phân quyền demo

Đăng nhập tại màn hình đầu tiên. Cookie phiên được ký HMAC, có cờ `HttpOnly`, `SameSite=Lax` và hết hạn sau 8 giờ. API tự kiểm tra vai trò từ phiên đăng nhập; giao diện không còn tự đổi quyền bằng dropdown. Các tài khoản demo:

| Vai trò | Tên đăng nhập | Mật khẩu |
| --- | --- | --- |
| Khách hàng | `customer` | `Member@123` |
| Tư vấn viên | `consultant` | `Consult@123` |
| Quản lý PT | `manager` | `Manager@123` |
| Huấn luyện viên | `pt` | `Trainer@123` |
| Admin | `admin` | `Admin@123` |

Đây là tài khoản tĩnh cho bài trình diễn: không có đăng ký người dùng, đổi mật khẩu, khóa tài khoản hay quản lý danh tính trong CSDL. Khóa cookie mặc định cũng dành cho localhost; không dùng cấu hình demo để triển khai công khai.

- **Khách hàng:** nhấn **Nhập dữ liệu mẫu**, gửi khảo sát, chọn PT/gói, ký hợp đồng và chạy thanh toán thành công hoặc thất bại.
- **Tư vấn viên:** xử lý hàng đợi có điểm tin cậy dưới 0,82. Nếu đang chuyển từ một hồ sơ khách hàng trong cùng cửa sổ, sau khi duyệt hãy đăng xuất và vào tài khoản `customer` để tiếp tục wizard.
- **Quản lý PT:** phân PT thủ công cho hồ sơ chưa có hợp đồng.
- **PT:** xem lịch hội viên đã kích hoạt, xem cờ PAR-Q và xác nhận buổi đầu.
- **Admin:** xem số liệu, đối soát giao dịch, cấu hình giá gói (trong phiên demo) và bật/tắt PT.

Process Tracker thay đổi theo từng thao tác: khảo sát/AI, T5, báo giá, ghép PT, ký, thanh toán/QR, xác nhận buổi đầu, nhắc ký, nhánh tư vấn/hồ sơ tiềm năng, phương án thay thế, giải phóng slot, và hủy hợp đồng. Nút **Hủy hợp đồng & giải phóng PT** xuất hiện ở màn hình hợp đồng trước khi thanh toán; sau thanh toán thành công, nhánh hủy demo không cho hủy.

## Cơ sở dữ liệu

File `gym_database.db` có 5 bảng nghiệp vụ chuẩn hóa theo quan hệ chính. Danh tính demo nằm trong cấu hình ứng dụng, không thêm bảng tài khoản:

| Bảng | Lưu trữ |
| --- | --- |
| `customers` | Danh tính và thông tin liên hệ, điện thoại/email duy nhất |
| `health_surveys` | 7 câu PAR-Q, cờ y tế, mục tiêu, confidence, trạng thái duyệt và gói chọn |
| `trainers` | Chuyên môn, phong cách, hạng, tải việc, đánh giá và trạng thái khả dụng |
| `contracts` | Mã hợp đồng, khách/PT, giá trị, chữ ký, giữ chỗ 48 giờ, trạng thái và QR hội viên |
| `payments` | Mã giao dịch chống trùng, phương thức, số tiền, trạng thái và số hóa đơn |

Mọi truy vấn sử dụng placeholder tham số; kết nối tự đóng sau mỗi thao tác. PT mẫu được seed lần đầu. Gói Basic, Classic, VIP và giá demo được cấu hình trong `main.py`.

## Thuật toán

### Phân loại mục tiêu (T4/G1)

`classify_goal_intent(text, threshold=0.82)` đếm từ khóa theo bốn nhóm. Từ 2 cụm khớp: `min(0.85 + số_cụm × 0.05, 0.98)`; 1 cụm: `0.825`; không khớp: General Fitness ở `0.65`. `route_by_confidence` rẽ nhánh: `c >= 0.82` tự động duyệt, dưới ngưỡng chuyển T5. Hàm nhận ngưỡng làm tham số để kiểm tra đúng biên `0.820`/`0.819`.

### Ghép huấn luyện viên (TS)

`NSC = 0.30×Goal + 0.20×Schedule + 0.20×Load + 0.15×Style + 0.15×Budget`. Điểm từng thành phần được trả trong API để nhóm giải trình; danh sách sắp giảm dần theo NSC, tối đa 3 PT.

## API ↔ Task

| Task | Endpoint |
| --- | --- |
| AUTH | `POST /api/auth/login`, `GET /api/auth/me`, `POST /api/auth/logout` |
| T1 | `GET /api/survey/questions`, `POST /api/survey/submit` |
| T2–T4, G1 | Xử lý trong `POST /api/survey/submit` |
| T5 | `GET /api/consultant/pending-reviews`, `PUT /api/consultant/verify-goal/{survey_id}` |
| T6 | `POST /api/pricing/calculate` |
| TV/TX | `GET /api/packages`, `POST /api/packages/select` |
| TD/TL | `POST /api/consultant/deep-consult`, `POST /api/leads/save-drop` |
| TS/G3/TA | `POST /api/matching/find-trainers`, `GET /api/matching/alternative-slots` |
| TM | `GET /api/manager/unassigned-slots`, `PUT /api/manager/assign-trainer` |
| TQ/TR_Slot | `POST /api/slots/hold`, `POST /api/slots/release-expired` (có worker định kỳ) |
| TC/TSG/TNR | `POST /api/contracts/generate`, `GET /api/contracts/{id}`, `POST /api/contracts/{id}/sign`, `POST /api/notifications/remind-contract` |
| TPAY/TVF/TRP/TR | `POST /api/payments/checkout`, `POST /api/payments/webhook-verify`, `POST /api/payments/retry-link`, `POST /api/slots/release-failed-payment` |
| TCD/TI/TN | `POST /api/membership/activate`, `POST /api/invoices/generate`, `POST /api/notifications/notify-schedule` |
| TP/ES1–ES2 | `GET /api/pt/schedule`, `PUT /api/pt/confirm-first-session/{id}`, `POST /api/cancellation/process` |
| Admin | `GET /api/admin/overview`, `PUT /api/admin/packages/{name}`, `PUT /api/admin/trainers/{id}` |

Thông báo/email/SMS được ghi vào log demo, không gửi ra ngoài. Cổng checkout không thu tiền thật. Khi thanh toán thất bại hệ thống ghi giao dịch FAILED, đưa hợp đồng về DRAFT và tạo liên kết retry; giao dịch thành công cấp token `ACTIVELIFE-MEMBER-XXXXXXXX` và hóa đơn demo.

## Kiểm thử

Cài dependencies từ `requirements.txt`, sau đó chạy:

```powershell
pytest -v
```

Bộ test có 5 ca: happy path tới QR; ngưỡng confidence; validation và cờ y tế; checkout thất bại/retry; idempotency bằng `TXN_TEST_999`. Mỗi test dùng SQLite riêng trong thư mục tạm.
