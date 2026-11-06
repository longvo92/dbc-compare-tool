# DBC Compare Tool

**Phiên bản {version}** · Phát triển bởi **Long Vo Thien** · Giấy phép MIT

[Repo gốc: longvo92/dbc-compare-tool](https://github.com/longvo92/dbc-compare-tool)

DBC Compare Tool so sánh hai phiên bản cơ sở dữ liệu CAN. Tool giúp bạn kiểm tra message, signal và route ECU nào thay đổi giữa baseline OLD và NEW trước khi tích hợp DBC mới.

## Bạn có thể làm gì

- **So sánh file hoặc folder.** Xem message và signal được thêm, xóa, sửa hoặc đổi tên trong hai file DBC hoặc toàn bộ hai folder baseline.
- **Xem chi tiết thay đổi.** Đối chiếu giá trị OLD và NEW của CAN ID, vị trí bit, hệ số scale và các thuộc tính khác, cùng thông tin Tx/Rx của ECU.
- **Tập trung vào ECU cần kiểm tra.** Chọn một hoặc nhiều node để xem thay đổi liên quan đến Tx/Rx ở cả hai baseline. Có thể ghép cặp các node ECU đã đổi tên.
- **Chia sẻ report Excel.** Xem tổng số thay đổi, chi tiết message và signal, cùng cảnh báo nếu có file không đọc được trong chế độ so sánh folder.

Dùng GUI trên Windows để kiểm tra trực tiếp hoặc dùng CLI để chạy từ script. GUI và report Excel có thể chọn English hoặc Tiếng Việt riêng.

## Tải bản phát hành và góp ý

[Tải bản phát hành](https://github.com/longvo92/dbc-compare-tool/releases) · [Báo lỗi](https://github.com/longvo92/dbc-compare-tool/issues)
