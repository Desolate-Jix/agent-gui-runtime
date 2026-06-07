from __future__ import annotations

from app.core.window_manager import WindowManager


def test_window_title_match_normalization_removes_format_controls() -> None:
    manager = WindowManager()

    assert manager._normalize_match_text("Microsoft\u200b Edge") == "microsoft edge"
