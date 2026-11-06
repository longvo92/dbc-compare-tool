# Hướng dẫn sử dụng

## GUI

1. Chọn chế độ **File** hoặc **Folder**, rồi chọn hai baseline OLD và NEW.
2. Mở **Cài đặt → Ngôn ngữ…** để chọn **Ngôn ngữ GUI** và **Ngôn ngữ report**. Report mặc định theo GUI.
3. Để trống đường dẫn report để lưu cạnh NEW với tên `compared_<old>_vs_<new>.xlsx`. Tên tự động dùng tên folder hoặc tên file bỏ đuôi `.dbc`. Chọn đường dẫn `.xlsx` nếu muốn đặt tên riêng.
4. Trong chế độ Folder, dùng **Ghép cặp DBC thủ công…** khi cần chọn cặp cụ thể hoặc đánh dấu file OLD đã xóa. Dùng **Ghép cặp ECU…** để ghép các node đã đổi tên. Report giữ tên node gốc.
5. Bật **ECU focus** để quét node trong hai baseline. Chọn một hoặc nhiều node. Dùng **Chọn ECU…** để sửa danh sách. Đổi input hoặc cặp ECU sẽ xóa lựa chọn focus.
6. Chọn loại thay đổi. **Gồm mục không đổi** bỏ qua bộ lọc loại thay đổi và vẫn áp dụng ECU focus.
7. Chọn **Chạy so sánh** rồi **Mở report**.

## ECU focus và report

- Tool xét route ở cả OLD và NEW để thấy cả trường hợp ECU có thêm hoặc mất Tx/Rx. Với Tx, focus gồm mọi signal do ECU phát. Với Rx, focus chỉ gồm từng signal ECU nhận, cùng các thay đổi cấp message liên quan.
- Chọn một đầu của cặp ECU đã đổi tên sẽ gồm đầu tương ứng ở baseline còn lại. Node cùng tên được áp dụng trên mọi DBC đã chọn.
- Sheet **Tổng quan** ghi đường dẫn baseline, danh sách node focus, tổng thay đổi, coverage và lỗi đọc DBC. Trong chế độ focus, **Tổng quan DBC** chỉ liệt kê các cặp file có dòng detail được xuất. Số message/signal tại đó vẫn tính trên toàn DBC.
- **Chưa đầy đủ** nghĩa là có file không đọc được. Kiểm tra lỗi trong sheet **Tổng quan** hoặc log. So sánh trực tiếp hai file dừng nếu một file lỗi.
- Lọc sheet chi tiết theo loại thay đổi, CAN ID hoặc ECU Tx/Rx. **Thuộc tính thay đổi** hiển thị giá trị cũ và mới, ví dụ `Start Bit: 56->57`. Đóng file Excel trước khi xuất lại cùng đường dẫn.

## CLI

```powershell
.\run_cli.bat --old "folder cũ" --new "folder mới" --list-ecus
.\run_cli.bat --old "folder cũ" --new "folder mới" --ecu-focus BCM --ecu-focus ECM --report-language vi
```

| Tùy chọn | Cách dùng |
|---|---|
| `--old PATH`, `--new PATH` | Hai folder hoặc hai file DBC. Đặt đường dẫn có khoảng trắng trong dấu ngoặc kép. |
| `--out PATH` | Đường dẫn report `.xlsx` tự chọn. |
| `--list-ecus` | Quét và liệt kê node OLD/NEW, không xuất report. |
| `--ecu-focus NODE` | Lọc theo Tx/Rx. Lặp lại để chọn nhiều node. |
| `--ecu-pair OLD=NEW` | Ghép cặp node đổi tên. Có thể lặp lại. |
| `--include-unchanged` | Xuất cả mục không đổi trong phạm vi đã chọn. |
| `--report-language {en,vi}` | Chọn ngôn ngữ report. CLI mặc định English. |
| `--help` | Xem trợ giúp lệnh. |

Mã thoát: **0** hoàn tất, **1** lỗi đọc file trực tiếp hoặc lỗi xử lý/xuất, **2** input hoặc mapping không hợp lệ, **3** đã xuất report hoặc quét ECU nhưng có file DBC bị bỏ qua.
