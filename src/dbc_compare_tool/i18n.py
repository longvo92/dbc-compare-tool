"""Translations for the application shell.

The comparison and report strings live in :mod:`dbc_compare_tool.dbc_compare.i18n`,
which is vendored with the engine; they are merged in here.
"""

from __future__ import annotations

from .dbc_compare.i18n import LANGUAGES, reason_render, render
from .dbc_compare.i18n import VI as COMPARE_VI

__all__ = ["LANGUAGES", "VI", "reason_text", "translate"]


def translate(language: str, key: str, **parameters: object) -> str:
    return render(VI, language, key, **parameters)


def reason_text(language: str, reason: str) -> str:
    return reason_render(VI, language, reason)


SHELL_VI = {
    "Settings": "Cài đặt",
    "Settings…": "Cài đặt…",
    "Language": "Ngôn ngữ",
    "GUI Language": "Ngôn ngữ GUI",
    "Report Language": "Ngôn ngữ report",
    "Follow GUI": "Theo GUI",
    "Appearance": "Giao diện",
    "Theme": "Chủ đề",
    "Follow Windows": "Theo Windows",
    "Light": "Sáng",
    "Dark": "Tối",
    "Help": "Trợ giúp",
    "User Guide": "Hướng dẫn sử dụng",
    "Release note": "Ghi chú phát hành",
    "About": "Giới thiệu",
    "Quit": "Thoát",
    "Task Running": "Đang chạy",
    "A task is still running. Quit anyway?": "Một tác vụ vẫn đang chạy. Bạn có muốn thoát không?",
    "Unable to open help file: {error}": "Không mở được file trợ giúp: {error}",
    "Unable to open the release notes: {error}": "Không mở được ghi chú phát hành: {error}",
    "No release notes available.": "Chưa có ghi chú phát hành.",
}

VI = {**COMPARE_VI, **SHELL_VI}
