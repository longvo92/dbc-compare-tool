# Hướng dẫn sử dụng

Cửa sổ chính là workspace so sánh. **Cài đặt → Cài đặt…** gồm ngôn ngữ GUI, ngôn ngữ report
và chủ đề (theo Windows, Sáng hoặc Tối).

## So sánh hai baseline

1. Chọn chế độ **File** hoặc **Folder**, rồi chọn hai baseline OLD và NEW cùng loại.
2. Để trống đường dẫn report để lưu cạnh NEW với tên `compared_<old>_vs_<new>.xlsx`, hoặc chọn đường dẫn `.xlsx` riêng.
3. Trong chế độ Folder, dùng **Ghép cặp DBC thủ công…** khi cần chọn cặp cụ thể hoặc đánh dấu file OLD đã xóa.
4. Dùng **Ghép cặp ECU…** để ghép các node đã đổi tên; report giữ tên node gốc.
5. Bật **ECU focus** để quét node trong hai baseline, rồi chọn node cần xem. Dùng **Chọn ECU…** để sửa danh sách. Đổi input hoặc cặp ECU sẽ xóa lựa chọn focus.
6. Report gồm tất cả loại thay đổi trong phạm vi ECU hiện tại. Bật **Gồm mục không đổi** để xuất thêm message và signal không đổi.
7. Chọn **Chạy so sánh** rồi **Mở report**.

## Ghép cặp

`classic-v067` ghép trước các DBC cùng đường dẫn, sau đó tìm file đã đổi tên. Trong cặp file,
message ghép theo frame key, rồi theo tên, rồi theo điểm rename. Trong cặp message, signal ghép
theo tên rồi theo điểm rename. Ngưỡng điểm: 0.55 cho DBC, 0.60 cho message, 0.65 cho signal và
0.55 cho signal dạng event. Mục không ghép được thành Thêm mới/Đã xóa. Mức tin cậy
**Cao/Trung bình/Thấp** là ước lượng; khi có nhiều ứng viên, mức tin cậy giảm. Message chuyển
giữa các DBC hoặc signal chuyển giữa các message hiện thành Thêm mới/Đã xóa.

## ECU focus và report

- Tool xét route ở cả OLD và NEW để thấy cả trường hợp ECU có thêm hoặc mất Tx/Rx. Với Tx, focus gồm mọi signal do ECU phát. Với Rx, focus chỉ gồm từng signal ECU nhận, cùng các thay đổi cấp message liên quan.
- Chọn một đầu của cặp ECU đã đổi tên sẽ gồm đầu tương ứng ở baseline còn lại. Node cùng tên được áp dụng trên mọi DBC đã chọn.
- Sheet **Tổng quan** ghi đường dẫn baseline, danh sách node focus, tổng thay đổi, coverage và lỗi đọc DBC. Trong chế độ focus, **Tổng quan DBC** chỉ liệt kê các cặp file có dòng detail được xuất; số message/signal tại đó vẫn tính trên toàn DBC.
- **Chưa đầy đủ** nghĩa là có file không đọc được. Kiểm tra lỗi trong sheet **Tổng quan** hoặc log. So sánh trực tiếp hai file sẽ dừng nếu một file lỗi.
- Lọc sheet chi tiết theo loại thay đổi, CAN ID hoặc ECU Tx/Rx. **Thuộc tính thay đổi** hiển thị giá trị cũ và mới, ví dụ `Start Bit: 56->57`. Đóng file Excel trước khi xuất lại cùng đường dẫn.

Logic matching mới có test hồi quy trên dữ liệu tổng hợp; chưa có bộ dữ liệu thực tế đã gán nhãn cặp đúng.
