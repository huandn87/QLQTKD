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

- **Khách hàng:** gửi T1; nếu cần thì chờ T5; xem báo giá TV, xác nhận gói TX. Basic đi thẳng đến TC. Classic/VIP đi qua TS, chọn PT và ca TQ, rồi chờ PT xác nhận TP trước khi hệ thống gửi TN và tạo TC.
- **Tư vấn viên:** xử lý hàng đợi có điểm tin cậy dưới 0,82 tại T5. Tiến trình lưu trong SQLite, khách có thể đăng xuất rồi đăng nhập lại để tiếp tục.
- **Quản lý PT:** chỉ nhận các hồ sơ đến nhánh TM sau khi ghép tự động và các phương án TA đã hết lượt; chọn PT lẫn ca trống. PT vẫn cần xác nhận ca tại TP.
- **PT:** xem lịch theo ngày/giờ, cảnh báo sức khỏe và trạng thái ca. Nhận lịch sẽ chốt ca, ghi phác đồ sơ bộ, gửi TN và tạo hợp đồng; từ chối sẽ nhả ca và chuyển TA/TM.
- **Admin:** xem số liệu, đối soát giao dịch, cấu hình giá gói (trong phiên demo) và bật/tắt PT.

Process Tracker đọc trạng thái tiến trình đã lưu, không chỉ đánh dấu ở trình duyệt. Task ES1 là giải phóng lịch PT; ES2 là ghi nhận lý do hủy. Nhánh không ký kết thúc ở E2 và giải phóng lịch nếu có PT. Hủy theo event sub-process ESP được hỗ trợ trước khi thanh toán thành công.

## Cơ sở dữ liệu

File `gym_database.db` có các bảng nghiệp vụ, tiến trình và lịch tập. Danh tính demo nằm trong cấu hình ứng dụng, không thêm bảng tài khoản:

| Bảng | Lưu trữ |
| --- | --- |
| `customers` | Danh tính và thông tin liên hệ, điện thoại/email duy nhất |
| `health_surveys` | 7 câu PAR-Q, cờ y tế, mục tiêu, confidence, trạng thái duyệt và gói chọn |
| `trainers` | Chuyên môn, phong cách, hạng, tải việc, đánh giá và trạng thái khả dụng |
| `trainer_slots` | Ca buổi tập đầu tiên theo ngày/giờ; OPEN, HELD khi chờ PT (tối đa 48 giờ), CONFIRMED sau khi PT nhận |
| `workflow_cases` | Task hiện tại, task đã hoàn tất, lựa chọn gói/PT/ca, số lượt ghép, trạng thái và lý do hủy |
| `contracts` | Mã hợp đồng, khách/PT/ca, giá trị, chữ ký, giữ chỗ, trạng thái và QR hội viên |
| `payments` | Mã giao dịch chống trùng, phương thức, số tiền, trạng thái và số hóa đơn |

Mọi truy vấn sử dụng placeholder tham số; kết nối tự đóng sau mỗi thao tác. PT mẫu được seed lần đầu. Gói Basic, Classic, VIP và giá demo được cấu hình trong `main.py`.

## Thuật toán

### Phân loại mục tiêu (T4/G1)

`classify_goal_intent(text, threshold=0.82)` đếm từ khóa theo bốn nhóm. Từ 2 cụm khớp: `min(0.85 + số_cụm × 0.05, 0.98)`; 1 cụm: `0.825`; không khớp: General Fitness ở `0.65`. `route_by_confidence` rẽ nhánh: `c >= 0.82` tự động duyệt, dưới ngưỡng chuyển T5. Hàm nhận ngưỡng làm tham số để kiểm tra đúng biên `0.820`/`0.819`.

### Ghép huấn luyện viên (TS/GA)

`NSC = 0.30×Goal + 0.20×Schedule + 0.20×Load + 0.15×Style + 0.15×Budget`. Hệ thống chỉ gợi ý PT đạt ít nhất 60 điểm, còn khả dụng và có slot OPEN trong lịch. Khách nhìn thấy ngày/giờ cụ thể cho buổi đầu; TQ giữ ca tối đa 48 giờ trong lúc chờ PT tại TP (timer BE_TP). PT nhận thì slot thành CONFIRMED và chạy TN → M4 → TC; PT từ chối/quá hạn thì TR_Slot → TA → GB, nếu còn lượt sẽ quay lại TS để chấm/lọc lại, đủ ba lượt thì TM. PT xác nhận xong thì 48 giờ giữ tạm kết thúc; khách không ký có thể giải phóng lịch bằng nhánh GD/TR hoặc ES1.

## API ↔ Task

| Task | Endpoint |
| --- | --- |
| AUTH | `POST /api/auth/login`, `GET /api/auth/me`, `POST /api/auth/logout` |
| T1 | `GET /api/survey/questions`, `POST /api/survey/submit` |
| T2–T4, G1 | Xử lý trong `POST /api/survey/submit` |
| T5 | `GET /api/consultant/pending-reviews`, `PUT /api/consultant/verify-goal/{survey_id}` |
| T6 | `POST /api/pricing/calculate` |
| TV/TX | `GET /api/packages`, `POST /api/packages/select` |
| TD/TL | `POST /api/consultant/deep-consult` (khách gửi yêu cầu), `GET /api/consultant/pending-consults`, `POST /api/consultant/complete-consult`, `POST /api/leads/save-drop` |
| TS/GA/TA/GB | `POST /api/matching/find-trainers`, `POST /api/matching/alternative-slots` |
| TM | `GET /api/manager/unassigned-slots`, `GET /api/trainers`, `GET /api/trainers/slots`, `PUT /api/manager/assign-trainer`, `POST /api/manager/close-unassigned` |
| TQ/TR_Slot | `POST /api/slots/hold`, `POST /api/slots/release-expired` (worker định kỳ giải phóng ca hết hạn) |
| TC/TSG/TNR | `POST /api/contracts/generate`, `GET /api/contracts/{id}`, `POST /api/contracts/{id}/sign`, `POST /api/notifications/remind-contract` |
| TP/GC/TN | `GET /api/pt/schedule`, `POST /api/pt/respond-schedule` |
| TPAY/TVF/TRP | `POST /api/payments/checkout`, `POST /api/payments/webhook-verify`, `POST /api/payments/retry-link` |
| TCD/TI | `POST /api/membership/activate`, `POST /api/invoices/generate` (TVF gọi TCD rồi TI tuần tự) |
| TR/ES1–ES2 | `POST /api/contracts/{id}/decline`, `POST /api/cancellation/process` |
| Admin | `GET /api/admin/overview`, `PUT /api/admin/packages/{name}`, `PUT /api/admin/trainers/{id}` |

Thông báo/email/SMS được ghi vào log demo, không gửi ra ngoài. Cổng checkout không thu tiền thật. Khi thanh toán lỗi tại TVF, hệ thống chạy TRP rồi quay lại TPAY; hợp đồng vẫn ở trạng thái SIGNED để khách thử thanh toán lại. Thanh toán thành công chạy riêng các bước TCD kích hoạt QR và TI xuất hóa đơn.

## Kiểm thử

Cài dependencies từ `requirements.txt`, sau đó chạy:

```powershell
pytest -v
```

Bộ test có 5 ca: happy path đi qua chọn gói → ghép PT → giữ ca → PT xác nhận → hợp đồng/QR; ngưỡng confidence; validation và cờ y tế; TVF thất bại rồi thanh toán lại trong khi hợp đồng vẫn SIGNED; idempotency bằng `TXN_TEST_999`. Mỗi test dùng SQLite riêng trong thư mục tạm.
