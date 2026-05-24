from __future__ import annotations

import tkinter as tk

from app.settings_panel.desktop import SettingsPanelApp
from app.settings_panel.i18n import TEXTS


def test_settings_panel_builds_pages_and_switches_language() -> None:
    root = tk.Tk()
    root.withdraw()
    try:
        app = SettingsPanelApp(root)
        for page in ["workflow", "apps", "open_bind", "capture", "observe", "locate", "execute", "models"]:
            app._show_page(page)
        assert hasattr(app, "response_text")
        assert app.prompt_texts["observe"] is not app.prompt_texts["locate"]
        assert app.small_model_var is not app.large_model_var
        app._set_language("en-US")
        assert app.i18n.t("main") == TEXTS["en-US"]["main"]
        app._set_language("zh-CN")
        assert app.i18n.t("main") == TEXTS["zh-CN"]["main"]
    finally:
        root.destroy()
