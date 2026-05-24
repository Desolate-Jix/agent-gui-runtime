from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageDraw, ImageTk

from app.settings_panel.api_client import RuntimeHttpClient
from app.settings_panel.config_store import (
    ARTIFACT_DIR,
    DEFAULT_PANEL_CONFIG,
    PANEL_CONFIG_PATH,
    ROOT_DIR,
    VISION_CONFIG_PATH,
    load_json,
    save_json,
)
from app.settings_panel.i18n import I18n


class SettingsPanelApp:
    """Stage-by-stage desktop test panel for the local GUI runtime."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.vision_config = load_json(VISION_CONFIG_PATH, default={"vision": {}})
        self.panel_config = load_json(PANEL_CONFIG_PATH, default=DEFAULT_PANEL_CONFIG)
        self.i18n = I18n(str(self.panel_config.get("language") or "zh-CN"))
        self.root.title(self.i18n.t("app_title"))
        self.root.geometry("1280x820")
        self.root.minsize(1120, 720)

        self.pages: dict[str, ttk.Frame] = {}
        self.active_page = "workflow"
        self.workflow_canvas: tk.Canvas | None = None
        self.workflow_nodes: dict[str, int] = {}
        self.preview_photo: ImageTk.PhotoImage | None = None
        self.prompt_texts: dict[str, tk.Text] = {}
        self.last_response: dict[str, Any] | None = None
        self.last_overlay_path = ""

        vision = self.vision_config.get("vision") or {}
        local = vision.get("local") or {}
        local_understanding = vision.get("local_understanding") or vision.get("local_small") or local
        local_grounding = vision.get("local_grounding") or vision.get("local_large") or local
        api = vision.get("api") or {}
        prompt_overrides = self.panel_config.get("prompt_overrides") if isinstance(self.panel_config.get("prompt_overrides"), dict) else {}

        self.language_var = tk.StringVar(value=self.i18n.language)
        self.runtime_base_url_var = tk.StringVar(value=str(self.panel_config.get("runtime_base_url") or "http://127.0.0.1:8000"))
        self.mode_var = tk.StringVar(value=str(self.panel_config.get("mode") or "local_flow"))
        self.timeout_var = tk.StringVar(value=str(vision.get("timeout_seconds") or 180))
        self.small_model_var = tk.StringVar(value=str(local_understanding.get("model_name") or ""))
        self.small_endpoint_var = tk.StringVar(value=str(local_understanding.get("endpoint") or ""))
        self.large_model_var = tk.StringVar(value=str(local_grounding.get("model_name") or ""))
        self.large_endpoint_var = tk.StringVar(value=str(local_grounding.get("endpoint") or ""))
        self.api_provider_var = tk.StringVar(value=str(api.get("provider") or ""))
        self.api_model_var = tk.StringVar(value=str(api.get("model") or ""))
        self.api_endpoint_var = tk.StringVar(value=str(api.get("endpoint") or ""))
        self.api_key_var = tk.StringVar(value="")

        self.app_id_var = tk.StringVar(value="edge")
        self.process_name_var = tk.StringVar(value="msedge.exe")
        self.window_title_var = tk.StringVar(value="Microsoft Edge")
        self.goal_var = tk.StringVar(value="识别当前界面的首页导航栏主页图标")
        self.app_name_var = tk.StringVar(value="browser")
        self.state_hint_var = tk.StringVar(value="top navigation bar")
        self.top_k_var = tk.StringVar(value="5")
        self.image_path_var = tk.StringVar(value="")
        self.roi_x_var = tk.StringVar(value="")
        self.roi_y_var = tk.StringVar(value="")
        self.roi_w_var = tk.StringVar(value="")
        self.roi_h_var = tk.StringVar(value="")
        self.box_x_var = tk.StringVar(value="0")
        self.box_y_var = tk.StringVar(value="0")
        self.box_w_var = tk.StringVar(value="120")
        self.box_h_var = tk.StringVar(value="60")
        self.box_label_var = tk.StringVar(value="target")
        self.workflow_status_var = tk.StringVar(value=self.i18n.t("status_ready"))
        self.response_summary_var = tk.StringVar(value=self.i18n.t("status_ready"))
        self.prompt_default = str(prompt_overrides.get("additional_rules") or "")

        self._configure_style()
        self._build_shell()
        self._show_page("workflow")

    def _configure_style(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("App.TFrame", background="#ffffff")
        style.configure("Side.TFrame", background="#f6f6f7")
        style.configure("Top.TFrame", background="#ffffff")
        style.configure("Card.TFrame", background="#ffffff", relief="solid", borderwidth=1)
        style.configure("Title.TLabel", background="#ffffff", foreground="#111111", font=("Microsoft YaHei UI", 15, "bold"))
        style.configure("Subtitle.TLabel", background="#ffffff", foreground="#5f6673", font=("Microsoft YaHei UI", 9))
        style.configure("CardTitle.TLabel", background="#ffffff", foreground="#111111", font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("Muted.TLabel", background="#ffffff", foreground="#667085", font=("Microsoft YaHei UI", 9))
        style.configure("Side.TLabel", background="#f6f6f7", foreground="#667085", font=("Microsoft YaHei UI", 9))
        style.configure("Nav.TButton", anchor="w", padding=(14, 8), font=("Microsoft YaHei UI", 10))
        style.configure("Primary.TButton", padding=(12, 8), font=("Microsoft YaHei UI", 9, "bold"))

    def _build_shell(self) -> None:
        self.root.configure(bg="#ffffff")
        self.shell = ttk.Frame(self.root, style="App.TFrame")
        self.shell.pack(fill="both", expand=True)

        self.sidebar = ttk.Frame(self.shell, style="Side.TFrame", width=220)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        self.content = ttk.Frame(self.shell, style="App.TFrame")
        self.content.pack(side="left", fill="both", expand=True)

        ttk.Label(self.sidebar, text="Agent GUI Runtime", style="Side.TLabel").pack(anchor="w", padx=22, pady=(20, 18))
        for key, label_key in [
            ("workflow", "workflow"),
            ("apps", "nav_apps"),
            ("open_bind", "nav_open_bind"),
            ("capture", "capture"),
            ("observe", "nav_observe"),
            ("locate", "nav_locate"),
            ("execute", "nav_execute"),
        ]:
            ttk.Button(self.sidebar, text=self.i18n.t(label_key), style="Nav.TButton", command=lambda name=key: self._show_page(name)).pack(
                fill="x", padx=10, pady=2
            )

        ttk.Button(self.sidebar, text=self.i18n.t("settings_nav"), style="Nav.TButton", command=lambda: self._show_page("models")).pack(
            side="bottom", fill="x", padx=10, pady=(2, 18)
        )

        self.topbar = ttk.Frame(self.content, style="Top.TFrame")
        self.topbar.pack(fill="x", padx=28, pady=(18, 0))
        ttk.Button(self.topbar, text=self.i18n.t("language_toggle"), command=self._toggle_language).pack(side="right")

        self.page_container = ttk.Frame(self.content, style="App.TFrame")
        self.page_container.pack(fill="both", expand=True)

        for key in ["workflow", "apps", "open_bind", "capture", "observe", "locate", "execute", "models"]:
            self.pages[key] = ttk.Frame(self.page_container, style="App.TFrame")

        self._build_workflow_page(self.pages["workflow"])
        self._build_apps_page(self.pages["apps"])
        self._build_open_bind_page(self.pages["open_bind"])
        self._build_capture_page(self.pages["capture"])
        self._build_observe_page(self.pages["observe"])
        self._build_locate_page(self.pages["locate"])
        self._build_execute_page(self.pages["execute"])
        self._build_models_page(self.pages["models"])
        self._build_response_panel()

    def _toggle_language(self) -> None:
        self._set_language("en-US" if self.language_var.get() == "zh-CN" else "zh-CN")

    def _set_language(self, language: str) -> None:
        self.i18n.set_language(language)
        self.language_var.set(language)
        self._persist_panel_config(show_message=False)
        current = self.active_page
        self.shell.destroy()
        self.pages = {}
        self.workflow_canvas = None
        self.workflow_nodes = {}
        self._build_shell()
        self._show_page(current)

    def _show_page(self, key: str) -> None:
        self.active_page = key
        for frame in self.pages.values():
            frame.pack_forget()
        self.pages[key].pack(fill="both", expand=True, padx=46, pady=(18, 12))

    def _header(self, parent: ttk.Frame, title_key: str, subtitle_key: str) -> None:
        ttk.Label(parent, text=self.i18n.t(title_key), style="Title.TLabel").pack(anchor="w")
        ttk.Label(parent, text=self.i18n.t(subtitle_key), style="Subtitle.TLabel").pack(anchor="w", pady=(6, 20))

    def _card(self, parent: ttk.Frame) -> ttk.Frame:
        card = ttk.Frame(parent, style="Card.TFrame")
        card.pack(fill="x", pady=(0, 14))
        inner = ttk.Frame(card, style="App.TFrame")
        inner.pack(fill="both", expand=True, padx=16, pady=14)
        return inner

    def _entry_row(self, parent: ttk.Frame, label_key: str, variable: tk.StringVar, *, width: int = 58, show: str | None = None) -> ttk.Entry:
        row = ttk.Frame(parent, style="App.TFrame")
        row.pack(fill="x", pady=5)
        ttk.Label(row, text=self.i18n.t(label_key), style="CardTitle.TLabel", width=18).pack(side="left")
        entry = ttk.Entry(row, textvariable=variable, width=width, show=show)
        entry.pack(side="left", fill="x", expand=True)
        return entry

    def _button_row(self, parent: ttk.Frame, buttons: list[tuple[str, Callable[[], None]]]) -> None:
        row = ttk.Frame(parent, style="App.TFrame")
        row.pack(fill="x", pady=(10, 0))
        for label_key, command in buttons:
            ttk.Button(row, text=self.i18n.t(label_key), style="Primary.TButton", command=command).pack(side="left", padx=(0, 8), pady=4)

    def _build_workflow_page(self, parent: ttk.Frame) -> None:
        self._header(parent, "workflow_title", "workflow_subtitle")
        card = self._card(parent)
        ttk.Label(card, textvariable=self.workflow_status_var, style="Muted.TLabel").pack(anchor="w", pady=(0, 8))
        self.workflow_canvas = tk.Canvas(card, height=390, bg="#ffffff", highlightthickness=0)
        self.workflow_canvas.pack(fill="both", expand=True)
        self.draw_workflow()

    def _build_apps_page(self, parent: ttk.Frame) -> None:
        self._header(parent, "apps_title", "apps_subtitle")
        card = self._card(parent)
        self._entry_row(card, "app_id", self.app_id_var, width=20)
        self._button_row(card, [("apps_list", self.call_apps_list)])

    def _build_open_bind_page(self, parent: ttk.Frame) -> None:
        self._header(parent, "open_bind_title", "open_bind_subtitle")
        card = self._card(parent)
        self._entry_row(card, "app_id", self.app_id_var, width=20)
        self._entry_row(card, "title", self.window_title_var)
        self._entry_row(card, "process", self.process_name_var, width=28)
        self._button_row(card, [("open_app", self.call_open_app), ("bind_window", self.call_bind_window)])

    def _build_capture_page(self, parent: ttk.Frame) -> None:
        self._header(parent, "capture_title", "capture_subtitle")
        capture = self._card(parent)
        self._entry_row(capture, "image_path", self.image_path_var)
        ttk.Label(capture, text=self.i18n.t("roi"), style="CardTitle.TLabel").pack(anchor="w", pady=(8, 0))
        self._small_fields(capture, [("x", self.roi_x_var), ("y", self.roi_y_var), ("w", self.roi_w_var), ("h", self.roi_h_var)])
        self._button_row(capture, [("capture_window", self.call_capture_window), ("choose_image", self.choose_image), ("open_image", lambda: self.open_path(self.image_path_var.get()))])

        box = self._card(parent)
        ttk.Label(box, text=self.i18n.t("manual_box"), style="CardTitle.TLabel").pack(anchor="w")
        self._small_fields(box, [("x", self.box_x_var), ("y", self.box_y_var), ("w", self.box_w_var), ("h", self.box_h_var), ("label", self.box_label_var)])
        self._button_row(box, [("manual_box_button", self.generate_manual_box)])

        preview = self._card(parent)
        ttk.Label(preview, text=self.i18n.t("preview"), style="CardTitle.TLabel").pack(anchor="w")
        self.preview_label = ttk.Label(preview, text=self.i18n.t("no_image"), style="Muted.TLabel")
        self.preview_label.pack(anchor="w", pady=(8, 0))

    def _build_observe_page(self, parent: ttk.Frame) -> None:
        self._header(parent, "observe_title", "observe_subtitle")
        card = self._card(parent)
        self._entry_row(card, "image_path", self.image_path_var)
        self._entry_row(card, "app_name", self.app_name_var, width=26)
        self._entry_row(card, "state_hint", self.state_hint_var)
        ttk.Label(card, text=self.i18n.t("prompt_rules"), style="CardTitle.TLabel").pack(anchor="w", pady=(8, 4))
        self.prompt_texts["observe"] = tk.Text(card, height=7, wrap="word", font=("Consolas", 10), borderwidth=1, relief="solid")
        self.prompt_texts["observe"].pack(fill="x")
        self.prompt_texts["observe"].insert("1.0", self.prompt_default)
        self._button_row(card, [("observe_screen", self.call_observe_screen), ("analyze_api", self.call_analyze_api)])

    def _build_locate_page(self, parent: ttk.Frame) -> None:
        self._header(parent, "locate_title", "locate_subtitle")
        card = self._card(parent)
        self._entry_row(card, "image_path", self.image_path_var)
        self._entry_row(card, "goal", self.goal_var)
        self._entry_row(card, "app_name", self.app_name_var, width=26)
        self._entry_row(card, "state_hint", self.state_hint_var)
        self._entry_row(card, "top_k", self.top_k_var, width=10)
        ttk.Label(card, text=self.i18n.t("prompt_rules"), style="CardTitle.TLabel").pack(anchor="w", pady=(8, 4))
        self.prompt_texts["locate"] = tk.Text(card, height=7, wrap="word", font=("Consolas", 10), borderwidth=1, relief="solid")
        self.prompt_texts["locate"].pack(fill="x")
        self.prompt_texts["locate"].insert("1.0", self.prompt_default)
        self._button_row(card, [("locate_target", self.call_locate_target), ("render_overlay", self.call_render_overlay), ("open_overlay", lambda: self.open_path(self.last_overlay_path))])

    def _build_execute_page(self, parent: ttk.Frame) -> None:
        self._header(parent, "execute_title", "execute_subtitle")
        card = self._card(parent)
        self._entry_row(card, "goal", self.goal_var)
        self._entry_row(card, "app_name", self.app_name_var, width=26)
        self._entry_row(card, "state_hint", self.state_hint_var)
        self._entry_row(card, "top_k", self.top_k_var, width=10)
        self._button_row(card, [("dry_run_click", self.call_dry_run_click), ("render_overlay", self.call_render_overlay)])

    def _build_models_page(self, parent: ttk.Frame) -> None:
        self._header(parent, "models_title", "models_subtitle")
        runtime = self._card(parent)
        ttk.Label(runtime, text=self.i18n.t("runtime"), style="CardTitle.TLabel").pack(anchor="w")
        self._entry_row(runtime, "base_url", self.runtime_base_url_var)
        self._entry_row(runtime, "timeout", self.timeout_var, width=12)

        small = self._card(parent)
        ttk.Label(small, text=self.i18n.t("small_model"), style="CardTitle.TLabel").pack(anchor="w")
        self._entry_row(small, "model_name", self.small_model_var)
        self._entry_row(small, "endpoint", self.small_endpoint_var)

        large = self._card(parent)
        ttk.Label(large, text=self.i18n.t("large_model"), style="CardTitle.TLabel").pack(anchor="w")
        self._entry_row(large, "model_name", self.large_model_var)
        self._entry_row(large, "endpoint", self.large_endpoint_var)

        api = self._card(parent)
        ttk.Label(api, text=self.i18n.t("api_model"), style="CardTitle.TLabel").pack(anchor="w")
        self._entry_row(api, "provider", self.api_provider_var)
        self._entry_row(api, "model_name", self.api_model_var)
        self._entry_row(api, "endpoint", self.api_endpoint_var)
        self._entry_row(api, "api_key", self.api_key_var, show="*")
        ttk.Label(api, text=self.i18n.t("api_key_note"), style="Muted.TLabel").pack(anchor="w", pady=(4, 0))
        ttk.Button(parent, text=self.i18n.t("save"), style="Primary.TButton", command=self.save_model_config).pack(anchor="e")

    def _build_response_panel(self) -> None:
        card = ttk.Frame(self.content, style="Card.TFrame")
        card.pack(side="bottom", fill="x", padx=46, pady=(0, 20))
        inner = ttk.Frame(card, style="App.TFrame")
        inner.pack(fill="both", expand=True, padx=12, pady=10)
        row = ttk.Frame(inner, style="App.TFrame")
        row.pack(fill="x", pady=(0, 6))
        ttk.Label(row, text=self.i18n.t("response_title"), style="CardTitle.TLabel").pack(side="left", padx=(0, 12))
        ttk.Button(row, text=self.i18n.t("copy_json"), command=self.copy_response).pack(side="left", padx=(0, 8))
        ttk.Button(row, text=self.i18n.t("clear"), command=lambda: self.response_text.delete("1.0", "end")).pack(side="left", padx=(0, 8))
        ttk.Button(row, text=self.i18n.t("open_overlay"), command=lambda: self.open_path(self.last_overlay_path)).pack(side="left")
        ttk.Label(inner, textvariable=self.response_summary_var, style="Muted.TLabel").pack(anchor="w", pady=(0, 6))
        self.response_text = tk.Text(inner, height=9, wrap="none", font=("Consolas", 9), borderwidth=1, relief="solid")
        self.response_text.pack(fill="both", expand=True)

    def _small_fields(self, parent: ttk.Frame, fields: list[tuple[str, tk.StringVar]]) -> None:
        row = ttk.Frame(parent, style="App.TFrame")
        row.pack(fill="x", pady=8)
        for label_key, var in fields:
            ttk.Label(row, text=self.i18n.t(label_key), style="Muted.TLabel").pack(side="left", padx=(0, 4))
            ttk.Entry(row, textvariable=var, width=10 if label_key != "label" else 18).pack(side="left", padx=(0, 12))

    def client(self) -> RuntimeHttpClient:
        return RuntimeHttpClient(self.runtime_base_url_var.get())

    def current_prompt_rules(self, stage: str | None = None) -> str:
        text = self.prompt_texts.get(stage or self.active_page)
        if text is not None:
            return text.get("1.0", "end").strip()
        return self.prompt_default

    def metadata(self, stage: str | None = None) -> dict[str, Any]:
        return {
            "ocr_anchors": {"enabled": True, "max_anchors": "all", "min_score": 0.0},
            "prompt_overrides": {"additional_rules": self.current_prompt_rules(stage)},
            "settings_panel": {"language": self.language_var.get()},
        }

    def roi_payload(self) -> dict[str, int] | None:
        values = [self.roi_x_var.get(), self.roi_y_var.get(), self.roi_w_var.get(), self.roi_h_var.get()]
        if not any(item.strip() for item in values):
            return None
        x, y, w, h = [int(float(item)) for item in values]
        return {"x": x, "y": y, "width": w, "height": h}

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None, *, timeout: float = 240.0, summary: str = "", workflow_step: str | None = None) -> dict[str, Any] | None:
        try:
            self.mark_workflow(workflow_step, "active")
            response = self.client().get(path, timeout=timeout) if method == "GET" else self.client().post(path, payload or {}, timeout=timeout)
            self.set_response(response, summary=summary or path, workflow_step=workflow_step)
            return response
        except Exception as exc:
            self.mark_workflow(workflow_step, "error")
            messagebox.showerror(self.i18n.t("failed"), str(exc))
            return None

    def set_response(self, response: dict[str, Any], *, summary: str, workflow_step: str | None = None) -> None:
        self.last_response = response
        self.response_summary_var.set(summary)
        if hasattr(self, "response_text"):
            self.response_text.delete("1.0", "end")
            self.response_text.insert("1.0", json.dumps(response, ensure_ascii=False, indent=2))
        if workflow_step:
            self.mark_workflow(workflow_step, "done" if response.get("success", True) else "error")

    def call_apps_list(self) -> None:
        self.request("GET", "/apps", timeout=20, summary="GET /apps", workflow_step="apps")

    def call_open_app(self) -> None:
        payload = {"app_id": self.app_id_var.get().strip() or None, "bind_after_open": True}
        self.request("POST", "/apps/open", payload, timeout=60, summary="POST /apps/open", workflow_step="open")

    def call_bind_window(self) -> None:
        payload = {"title": self.window_title_var.get().strip() or None, "process_name": self.process_name_var.get().strip() or None}
        self.request("POST", "/session/bind_window", payload, timeout=30, summary="POST /session/bind_window", workflow_step="open")

    def call_capture_window(self) -> None:
        payload: dict[str, Any] = {"save_image": True}
        roi = self.roi_payload()
        if roi is not None:
            payload["roi"] = roi
        response = self.request("POST", "/state/capture_window", payload, timeout=60, summary="POST /state/capture_window", workflow_step="capture")
        image_path = (((response or {}).get("data") or {}).get("image_path")) if response else None
        if image_path:
            self.image_path_var.set(str(image_path))
            self.load_preview(str(image_path))

    def call_observe_screen(self) -> None:
        payload = {
            "task": "observe_screen",
            "app_name": self.app_name_var.get().strip() or None,
            "state_hint": self.state_hint_var.get().strip() or None,
            "provider_mode": "local_understanding",
            "capture_live": not bool(self.image_path_var.get().strip()),
            "image_path": self.image_path_var.get().strip() or None,
            "metadata": self.metadata("observe"),
        }
        self.request("POST", "/vision/observe_screen", payload, timeout=300, summary="POST /vision/observe_screen", workflow_step="observe")

    def call_locate_target(self) -> None:
        payload = {
            "goal": self.goal_var.get().strip(),
            "task": "click_target",
            "app_name": self.app_name_var.get().strip() or None,
            "state_hint": self.state_hint_var.get().strip() or None,
            "provider_mode": "local_grounding",
            "capture_live": not bool(self.image_path_var.get().strip()),
            "image_path": self.image_path_var.get().strip() or None,
            "top_k": int(float(self.top_k_var.get() or 5)),
            "metadata": self.metadata("locate"),
        }
        self.request("POST", "/vision/locate_target", payload, timeout=300, summary="POST /vision/locate_target", workflow_step="locate")

    def call_analyze_api(self) -> None:
        image_path = self.ensure_image_path()
        if not image_path:
            return
        payload = {
            "image_path": image_path,
            "task": "analyze_ui",
            "app_name": self.app_name_var.get().strip() or None,
            "goal": self.goal_var.get().strip(),
            "state_hint": self.state_hint_var.get().strip() or None,
            "provider_mode": "api",
            "metadata": self.metadata("observe"),
        }
        self.request("POST", "/vision/analyze", payload, timeout=300, summary="POST /vision/analyze", workflow_step="observe")

    def call_dry_run_click(self) -> None:
        payload = {
            "goal": self.goal_var.get().strip(),
            "task": "click_target",
            "app_name": self.app_name_var.get().strip() or None,
            "state_hint": self.state_hint_var.get().strip() or None,
            "provider_mode": "local_grounding",
            "capture_live": True,
            "dry_run": True,
            "top_k": int(float(self.top_k_var.get() or 5)),
            "metadata": self.metadata("locate"),
        }
        self.request("POST", "/action/execute_recognition_plan", payload, timeout=300, summary="POST /action/execute_recognition_plan dry_run", workflow_step="gate")

    def call_health(self) -> None:
        self.request("GET", "/health", timeout=8, summary="GET /health")

    def call_render_overlay(self) -> None:
        trace_path = self.extract_trace_path(self.last_response)
        if not trace_path:
            messagebox.showwarning(self.i18n.t("failed"), "No recognition_plan trace_path")
            return
        payload = {"trace_path": trace_path, "include_rejected": True, "include_points": True, "label_candidates": True, "label_reasons": True}
        response = self.request("POST", "/vision/render_recognition_plan_overlay", payload, timeout=60, summary="POST /vision/render_recognition_plan_overlay")
        overlay = (((response or {}).get("data") or {}).get("result") or {}).get("overlay_path") if response else None
        if overlay:
            self.last_overlay_path = str(overlay)
            self.load_preview(str(overlay))

    def save_model_config(self) -> None:
        config = load_json(VISION_CONFIG_PATH, default={"vision": {}})
        vision = config.setdefault("vision", {})
        vision["mode"] = "local"
        vision["timeout_seconds"] = int(float(self.timeout_var.get() or 180))
        vision["local_understanding"] = {
            "model_name": self.small_model_var.get().strip(),
            "endpoint": self.small_endpoint_var.get().strip() or None,
        }
        vision["local_grounding"] = {
            "model_name": self.large_model_var.get().strip(),
            "endpoint": self.large_endpoint_var.get().strip() or None,
        }
        vision.setdefault("local", {})
        vision["local"]["model_name"] = self.large_model_var.get().strip()
        vision["local"]["endpoint"] = self.large_endpoint_var.get().strip() or None
        vision.setdefault("api", {})
        vision["api"]["provider"] = self.api_provider_var.get().strip() or "api"
        vision["api"]["model"] = self.api_model_var.get().strip() or "api_model"
        vision["api"]["endpoint"] = self.api_endpoint_var.get().strip() or None
        save_json(VISION_CONFIG_PATH, config)
        self._persist_panel_config(show_message=True)

    def _persist_panel_config(self, *, show_message: bool) -> None:
        self.panel_config["runtime_base_url"] = self.runtime_base_url_var.get().strip()
        self.panel_config["language"] = self.language_var.get()
        self.panel_config["prompt_overrides"] = {"additional_rules": self.current_prompt_rules()}
        save_json(PANEL_CONFIG_PATH, self.panel_config)
        if show_message:
            messagebox.showinfo(self.i18n.t("saved"), str(PANEL_CONFIG_PATH))

    def choose_image(self) -> None:
        path = filedialog.askopenfilename(
            title=self.i18n.t("choose_image"),
            filetypes=[("Images", "*.png;*.jpg;*.jpeg;*.bmp"), ("All files", "*.*")],
        )
        if path:
            self.image_path_var.set(path)
            self.load_preview(path)

    def ensure_image_path(self) -> str | None:
        image_path = self.image_path_var.get().strip()
        if image_path:
            return image_path
        self.call_capture_window()
        image_path = self.image_path_var.get().strip()
        if not image_path:
            messagebox.showwarning(self.i18n.t("missing_image"), self.i18n.t("missing_image"))
            return None
        return image_path

    def generate_manual_box(self) -> None:
        image_path = self.ensure_image_path()
        if not image_path:
            return
        try:
            x = int(float(self.box_x_var.get()))
            y = int(float(self.box_y_var.get()))
            w = int(float(self.box_w_var.get()))
            h = int(float(self.box_h_var.get()))
            label = self.box_label_var.get().strip() or "target"
            ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
            source = Image.open(image_path).convert("RGB")
            draw = ImageDraw.Draw(source)
            draw.rectangle([x, y, x + w, y + h], outline=(255, 0, 80), width=4)
            draw.text((x + 4, max(0, y - 18)), label, fill=(255, 0, 80))
            output = ARTIFACT_DIR / f"manual-box-{time.strftime('%Y%m%d-%H%M%S')}.png"
            source.save(output)
            self.last_overlay_path = str(output)
            self.load_preview(str(output))
            self.set_response({"manual_overlay_path": str(output), "bbox": {"x": x, "y": y, "w": w, "h": h}}, summary=str(output))
        except Exception as exc:
            messagebox.showerror(self.i18n.t("failed"), str(exc))

    def draw_workflow(self) -> None:
        if not self.workflow_canvas:
            return
        canvas = self.workflow_canvas
        canvas.delete("all")
        self.workflow_nodes = {}
        steps = [
            ("apps", self.i18n.t("wf_apps")),
            ("open", self.i18n.t("wf_open")),
            ("capture", self.i18n.t("wf_capture")),
            ("observe", self.i18n.t("wf_observe")),
            ("decide", self.i18n.t("wf_decide")),
            ("locate", self.i18n.t("wf_locate")),
            ("gate", self.i18n.t("wf_gate")),
            ("execute", self.i18n.t("wf_execute")),
        ]
        x, y, width, height, gap = 28, 48, 170, 72, 36
        for index, (step_id, title) in enumerate(steps):
            row, col = divmod(index, 4)
            x1 = x + col * (width + gap)
            y1 = y + row * (height + 80)
            rect = canvas.create_rectangle(x1, y1, x1 + width, y1 + height, fill="#f5f6f8", outline="#d5d9e2", width=2)
            canvas.create_text(x1 + 14, y1 + 34, text=title, anchor="w", fill="#111111", font=("Microsoft YaHei UI", 10, "bold"), width=width - 24)
            self.workflow_nodes[step_id] = rect
            if index > 0:
                prev_row, prev_col = divmod(index - 1, 4)
                if row == prev_row:
                    sx = x + prev_col * (width + gap) + width
                    sy = y + prev_row * (height + 80) + height // 2
                    ex = x1
                    ey = y1 + height // 2
                else:
                    sx = x + prev_col * (width + gap) + width // 2
                    sy = y + prev_row * (height + 80) + height
                    ex = x1 + width // 2
                    ey = y1
                canvas.create_line(sx, sy, ex, ey, arrow="last", fill="#98a2b3", width=2)

    def mark_workflow(self, step_id: str | None, status: str) -> None:
        if not step_id or not self.workflow_canvas:
            return
        rect = self.workflow_nodes.get(step_id)
        if not rect:
            return
        colors = {
            "active": ("#e9f1ff", "#155eef"),
            "done": ("#ecfdf3", "#12b76a"),
            "error": ("#fff1f3", "#f04438"),
        }
        fill, outline = colors.get(status, ("#f5f6f8", "#d5d9e2"))
        self.workflow_canvas.itemconfig(rect, fill=fill, outline=outline, width=3 if status == "active" else 2)
        self.workflow_status_var.set(step_id)
        self.root.update_idletasks()

    def load_preview(self, path: str) -> None:
        if not hasattr(self, "preview_label"):
            return
        try:
            image = Image.open(path)
            image.thumbnail((760, 250))
            self.preview_photo = ImageTk.PhotoImage(image)
            self.preview_label.configure(image=self.preview_photo, text="")
        except Exception:
            self.preview_label.configure(image="", text=path)

    def open_path(self, path: str) -> None:
        if not path:
            return
        resolved = Path(path)
        if not resolved.is_absolute():
            resolved = ROOT_DIR / resolved
        if resolved.exists():
            os.startfile(str(resolved))  # type: ignore[attr-defined]
        else:
            messagebox.showwarning(self.i18n.t("path_missing"), str(resolved))

    def copy_response(self) -> None:
        if not hasattr(self, "response_text"):
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(self.response_text.get("1.0", "end").strip())

    def extract_trace_path(self, response: dict[str, Any] | None) -> str:
        if not response:
            return ""
        result = ((response.get("data") or {}).get("result") or {})
        plan = result.get("recognition_plan") if isinstance(result.get("recognition_plan"), dict) else result
        return str(plan.get("trace_path") or result.get("recognition_plan_trace_path") or result.get("trace_path") or "")


def main() -> None:
    root = tk.Tk()
    SettingsPanelApp(root)
    root.mainloop()
