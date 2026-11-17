"""Write small Excel fixtures without pandas."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl import Workbook


def table(columns: dict[str, list[Any]]) -> list[list[Any]]:
    """A header row followed by the column values, row by row."""
    return [list(columns), *map(list, zip(*columns.values()))]


def write_workbook(path: Path, sheets: dict[str, list[list[Any]]], *, start_rows: dict[str, int] | None = None) -> Path:
    """Write ``rows`` per sheet; ``start_rows`` gives a 0-based first row per sheet."""
    book = Workbook()
    book.remove(book.active)
    for name, rows in sheets.items():
        sheet = book.create_sheet(name)
        offset = (start_rows or {}).get(name, 0)
        for row_index, row in enumerate(rows, start=offset + 1):
            for column_index, value in enumerate(row, start=1):
                if value not in (None, ""):
                    sheet.cell(row=row_index, column=column_index, value=value)
    book.save(path)
    return path
