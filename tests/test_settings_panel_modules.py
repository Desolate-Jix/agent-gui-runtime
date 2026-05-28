from __future__ import annotations

import tkinter as tk
import time

from app.settings_panel.desktop import SettingsPanelApp
from app.settings_panel.i18n import TEXTS


class _FakeClient:
    def get(self, path: str, *, timeout: float = 20.0):
        assert path == "/session/windows"
        return {
            "success": True,
            "data": {
                "candidates": [
                    {"title": "Auto Window", "process_name": "auto.exe", "process_id": 321, "handle": 654}
                ]
            },
        }


class _FakeModelClient:
    def get(self, path: str, *, timeout: float = 20.0):
        assert path == "/models"
        return {"data": [{"id": "demo-vision.gguf"}]}


class _FakeLoadingModelClient:
    def get(self, path: str, *, timeout: float = 20.0):
        assert path == "/models"
        raise RuntimeError("HTTP 503: Loading model")


class _FakeAsyncClient:
    def post(self, path: str, payload: dict, *, timeout: float = 240.0):
        assert path == "/vision/observe_screen"
        assert "compact index of independently clickable controls" in payload["metadata"]["prompt_overrides"]["additional_rules"]
        assert "do not repeat OCR boxes" in payload["metadata"]["prompt_overrides"]["additional_rules"]
        assert "next precise localization state_hint" in payload["metadata"]["prompt_overrides"]["additional_rules"]
        return {"success": True, "message": "observed", "data": {"result": {"suggested_state_hint": "job results list"}}, "error": None}


def test_settings_panel_builds_pages_and_switches_language() -> None:
    root = tk.Tk()
    root.withdraw()
    try:
        app = SettingsPanelApp(root)
        for page in ["workflow", "apps", "open_bind", "capture", "observe", "locate", "execute", "models"]:
            app._show_page(page)
        assert hasattr(app, "response_text")
        assert len(app.page_canvases) == len(app.pages)
        assert len(app.preview_labels) == 2
        assert app.prompt_texts["observe"] is not app.prompt_texts["locate"]
        assert app.small_model_var is not app.large_model_var
        app.large_endpoint_var.set("http://127.0.0.1:1234/v1/chat/completions")
        assert app.local_model_base_url() == "http://127.0.0.1:1234/v1"
        assert app.model_profile_labels()
        assert len(app.model_profile_labels()) == 2
        assert "Qwen3.6 35B A3B IQ4_XS" in app.model_profile_labels()
        assert "Qwen3-VL 8B Q4_K_M" in app.model_profile_labels()
        app.local_model_base_url = lambda stage="locate": "http://127.0.0.1:1240/v1"  # type: ignore[method-assign]
        import app.settings_panel.desktop as desktop_module

        original_client = desktop_module.RuntimeHttpClient
        desktop_module.RuntimeHttpClient = lambda _base_url: _FakeModelClient()  # type: ignore[assignment]
        try:
            app.test_model_endpoint("observe")
            assert "demo-vision.gguf" in app.model_status_vars["observe"].get()
        finally:
            desktop_module.RuntimeHttpClient = original_client
        desktop_module.RuntimeHttpClient = lambda _base_url: _FakeLoadingModelClient()  # type: ignore[assignment]
        try:
            app.test_model_endpoint("observe")
            assert "正在加载" in app.model_status_vars["observe"].get()
            assert app.last_response and app.last_response["error"]["code"] == "model_loading"
        finally:
            desktop_module.RuntimeHttpClient = original_client
        app.write_model_config = lambda: None  # type: ignore[method-assign]
        app._persist_panel_config = lambda show_message: None  # type: ignore[method-assign]
        app.apply_model_profile = lambda _stage: None  # type: ignore[method-assign]
        app.probe_model_endpoint = lambda _stage: {"data": [{"id": "already-running.gguf"}]}  # type: ignore[method-assign]
        original_popen = desktop_module.subprocess.Popen
        desktop_module.subprocess.Popen = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("duplicate launch"))  # type: ignore[assignment]
        try:
            app.start_model_server("observe")
            assert "already-running.gguf" in app.model_status_vars["observe"].get()
        finally:
            desktop_module.subprocess.Popen = original_popen
        app.probe_model_endpoint = lambda _stage: {"_status": "loading", "message": "Model is loading"}  # type: ignore[method-assign]
        desktop_module.subprocess.Popen = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("duplicate launch while loading"))  # type: ignore[assignment]
        try:
            app.start_model_server("observe")
            assert "正在加载" in app.model_status_vars["observe"].get()
        finally:
            desktop_module.subprocess.Popen = original_popen
        app.observe_model_profile_var.set("Qwen3-VL 8B Q4_K_M")
        SettingsPanelApp.apply_model_profile(app, "observe")
        assert app.small_model_var.get() == "Qwen3VL-8B-Instruct-Q4_K_M.gguf"
        SettingsPanelApp.apply_model_profile(app, "locate")
        assert app.large_model_var.get()
        app.set_window_candidates([{"title": "Demo Window", "process_name": "demo.exe", "process_id": 123, "handle": 456}])
        assert app.window_title_var.get() == "Demo Window"
        assert app.process_name_var.get() == "demo.exe"
        app.client = lambda: _FakeClient()  # type: ignore[method-assign]
        app.call_list_windows()
        assert app.window_title_var.get() == "Auto Window"
        assert app.process_name_var.get() == "auto.exe"
        app._set_language("en-US")
        assert app.i18n.t("main") == TEXTS["en-US"]["main"]
        app._set_language("zh-CN")
        assert app.i18n.t("main") == TEXTS["zh-CN"]["main"]
    finally:
        root.destroy()


def test_observe_request_runs_without_blocking_panel_and_uses_understanding_prompt() -> None:
    root = tk.Tk()
    root.withdraw()
    try:
        app = SettingsPanelApp(root)
        observe_prompt = app.prompt_texts["observe"].get("1.0", "end")
        locate_prompt = app.prompt_texts["locate"].get("1.0", "end")
        assert "compact index of independently clickable controls" in observe_prompt
        assert "do not repeat OCR boxes" in observe_prompt
        assert "next precise localization state_hint" in observe_prompt
        assert "Precision-localization stage only" in locate_prompt
        assert 'text_inclusion_policy="exclude_text"' in locate_prompt
        assert "grounding_constraints.edge_constraints" in locate_prompt
        app.client = lambda: _FakeAsyncClient()  # type: ignore[method-assign]
        app.call_observe_screen()
        assert "observe" in app.pending_requests
        deadline = time.monotonic() + 2.0
        while "observe" in app.pending_requests and time.monotonic() < deadline:
            root.update()
            time.sleep(0.01)
        assert "observe" not in app.pending_requests
        assert app.last_response and app.last_response["success"] is True
        assert app.state_hint_var.get() == "job results list"
    finally:
        root.destroy()


def test_locate_response_autofills_candidate_review_and_coordinate_gate() -> None:
    root = tk.Tk()
    root.withdraw()
    try:
        app = SettingsPanelApp(root)
        response = {
            "success": True,
            "data": {
                "result": {
                    "trace_path": "logs/traces/vision/qq-locate.json",
                    "located_bbox": {"x": 792, "y": 13, "w": 16, "h": 26},
                    "located_point": {"x": 800, "y": 26},
                    "recommended_target": {"label": "close window button"},
                }
            },
        }

        app._finish_async_request("locate", response, "POST /vision/locate_target", "locate", None)

        assert app.box_x_var.get() == "792"
        assert app.box_y_var.get() == "13"
        assert app.box_w_var.get() == "16"
        assert app.box_h_var.get() == "26"
        assert app.box_label_var.get() == "close window button"
        assert app.click_x_var.get() == "800"
        assert app.click_y_var.get() == "26"

        captured: dict[str, object] = {}

        def fake_request_async(method, path, payload, **kwargs):
            captured.update({"method": method, "path": path, "payload": payload, **kwargs})

        app.request_async = fake_request_async  # type: ignore[method-assign]
        app.call_confirmed_point(dry_run=True)

        assert captured["path"] == "/action/execute_confirmed_point"
        assert captured["payload"]["x"] == 800  # type: ignore[index]
        assert captured["payload"]["bbox"] == {"x": 792, "y": 13, "width": 16, "height": 26}  # type: ignore[index]
        assert captured["payload"]["dry_run"] is True  # type: ignore[index]
    finally:
        root.destroy()
