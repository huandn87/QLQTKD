# ActiveLife Gym — BPM Web Prototype

Prototype web mô phỏng quy trình TO-BE đăng ký gói tập, tư vấn, ghép PT, ký hợp đồng và thanh toán giả lập.

## Chạy ứng dụng

1. Cài Python 3.10 trở lên.
2. Mở terminal tại thư mục dự án và chạy:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   uvicorn main:app --reload
   ```

3. Mở `http://127.0.0.1:8000`. Tài liệu API ở `http://127.0.0.1:8000/docs`.

## Chạy bằng VS Code

1. Trong VS Code chọn **File → Open Folder...** và mở thư mục chứa `main.py`.
2. Nếu PowerShell báo `python is not recognized`, cài Python Install Manager từ [trang hướng dẫn chính thức của Python](https://docs.python.org/3/using/windows.html) hoặc Microsoft Store. Mở lại VS Code sau khi cài; trong terminal chạy `py install 3.13` để cài Python 3.13, rồi kiểm tra `python --version`.
3. Cài extension **Python** của Microsoft nếu VS Code chưa có.
4. Mở **Terminal → New Terminal**, chạy lần lượt:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   ```

5. Chọn Python trong môi trường `.venv` nếu VS Code hỏi **Select Interpreter**.
6. Mở **Run and Debug** ở thanh bên, chọn **ActiveLife Gym (FastAPI)** rồi nhấn nút chạy màu xanh.
7. Mở `http://127.0.0.1:8000` trong trình duyệt. Để dừng máy chủ, nhấn nút Stop trong VS Code.

Nếu lệnh kích hoạt môi trường bị PowerShell chặn, dùng Command Prompt trong VS Code và chạy `.venv\Scripts\activate.bat`, rồi tiếp tục cài dependencies.

SQLite tự tạo `gym_database.db` khi ứng dụng khởi động lần đầu. Các giao dịch là **demo giả lập**, không kết nối ngân hàng, SMS, cổng thanh toán hoặc dịch vụ AI bên ngoài. Dữ liệu mẫu PT được thêm tự động.

## Luồng demo

Điền khảo sát PAR-Q → phân loại mục tiêu (ngưỡng 0,82) → chọn PT và gói tập → xem/ký hợp đồng → thanh toán demo → nhận token QR hội viên. Nếu điểm phân loại dưới 0,82, duyệt mục tiêu trong khu vực Tư vấn viên trước khi tạo hợp đồng.
