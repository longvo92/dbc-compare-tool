Luật ở đây thắng `~/.claude/CLAUDE.md` khi mâu thuẫn.

## Ràng buộc

- **`requires-python = ">=3.9"`.** CI chạy 3.9, 3.10, 3.12 trên Linux + Windows. Vì hỗ trợ 3.9: mọi module/test phải có `from __future__ import annotations`; **không** dùng `match`, **không** dùng `X | Y` ở runtime (chỉ trong annotation, để future-import biến thành string). `list[str]`/`dict[...]` subscription thì 3.9 chịu được.
- Dependency cứng, không cần hỏi: `cantools>=40.3.0`, `openpyxl>=3.1.0`, `PySide6>=6.7.0`. Thêm dependency **mới** ngoài danh sách này thì nói lý do trước.
- **`PySide6` chỉ được import trong `ui/`.** CI cố tình không cài PySide6 — engine và report phải chạy được khi thiếu Qt. Import Qt ở `core/` hoặc `report/` là làm vỡ CI.
- Layout `src/` (setuptools `packages.find where = ["src"]`). Code mới đặt trong `src/dbc_compare_tool/`.


## Chạy & test

```bash
python -m dbc_compare_tool.cli --old examples/old --new examples/new --out report.xlsx
python -m unittest discover -s tests -v      # KHÔNG phải pytest
python scripts/build.py                       # đóng gói
run_gui.bat / run_cli.bat                     # tiện chạy trên Windows
```

Smoke test của CI là chạy CLI trên `examples/old` vs `examples/new` — chạy lại lệnh đó sau khi sửa engine.
