"""Shared Excel styling so every generated report looks like one product."""

from __future__ import annotations

from openpyxl.styles import Border, Side

HEADER_BG = "2E74B5"   # modern blue header
HEADER_FG = "FFFFFF"

THIN = Side(style="thin", color="D0D0D0")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
