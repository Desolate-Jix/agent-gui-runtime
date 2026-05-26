from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageDraw, ImageTk

try:  # Optional runtime dependency used only by the desktop launcher.
    from tkinterdnd2 import DND_FILES, TkinterDnD
except Exception:  # pragma: no cover - depends on local Tk/tkdnd install
    DND_FILES = None
    TkinterDnD = None

from app.settings_panel.api_client import RuntimeHttpClient
from app.settings_panel.config_store import (
    ARTIFACT_DIR,
    DEFAULT_LOCATE_PROMPT,
    DEFAULT_OBSERVE_PROMPT,
    DEFAULT_PANEL_CONFIG,
    MODEL_PROFILE_DIR,
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
        self.preview_labels: list[ttk.Label] = []
        self.prompt_texts: dict[str, tk.Text] = {}
        self.page_bodies: dict[str, ttk.Frame] = {}
        self.page_canvases: dict[str, tk.Canvas] = {}
        self.window_candidates: list[dict[str, Any]] = []
        self.pending_requests: set[str] = set()
        self.async_results: queue.Queue[tuple[str, dict[str, Any] | None, str, str | None, str | None]] = queue.Queue()
        self.async_polling = False
        self.last_response: dict[str, Any] | None = None
        self.last_overlay_path = ""
        self.confirmed_point_source_trace_path = ""

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
        self.window_choice_var = tk.StringVar(value="")
        model_scripts = self.panel_config.get("model_scripts") if isinstance(self.panel_config.get("model_scripts"), dict) else {}
        self.model_start_script_var = tk.StringVar(
            value=str(model_scripts.get("start") or ROOT_DIR / "scripts" / "model_servers" / "start_llama_vision_server.ps1")
        )
        self.model_stop_script_var = tk.StringVar(
            value=str(model_scripts.get("stop") or ROOT_DIR / "scripts" / "model_servers" / "stop_local_vision_server.ps1")
        )
        self.model_profiles = self.load_model_profiles()
        labels = self.model_profile_labels()
        default_profile = labels[0] if labels else ""
        observe_profile = self.preferred_profile_label(local_understanding.get("model_name"), local_understanding.get("endpoint")) or default_profile
        locate_profile = self.preferred_profile_label(local_grounding.get("model_name"), local_grounding.get("endpoint")) or default_profile
        self.observe_model_profile_var = tk.StringVar(value=observe_profile)
        self.locate_model_profile_var = tk.StringVar(value=locate_profile)
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
        self.click_x_var = tk.StringVar(value="0")
        self.click_y_var = tk.StringVar(value="0")
        self.workflow_status_var = tk.StringVar(value=self.i18n.t("status_ready"))
        self.response_summary_var = tk.StringVar(value=self.i18n.t("status_ready"))
        self.model_status_vars = {
            "observe": tk.StringVar(value=self.i18n.t("model_status_unknown")),
            "locate": tk.StringVar(value=self.i18n.t("model_status_unknown")),
        }
        legacy_prompt = str(prompt_overrides.get("additional_rules") or "").strip()
        self.prompt_defaults = {
            "observe": str(prompt_overrides.get("observe_additional_rules") or DEFAULT_OBSERVE_PROMPT),
            "locate": str(prompt_overrides.get("locate_additional_rules") or legacy_prompt or DEFAULT_LOCATE_PROMPT),
        }

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
            self.pages[key], self.page_bodies[key] = self._scroll_page(self.page_container)

        self._build_workflow_page(self.page_bodies["workflow"])
        self._build_apps_page(self.page_bodies["apps"])
        self._build_open_bind_page(self.page_bodies["open_bind"])
        self._build_capture_page(self.page_bodies["capture"])
        self._build_observe_page(self.page_bodies["observe"])
        self._build_locate_page(self.page_bodies["locate"])
        self._build_execute_page(self.page_bodies["execute"])
        self._build_models_page(self.page_bodies["models"])
        self._build_response_panel()

    def _toggle_language(self) -> None:
        self._set_language("en-US" if self.language_var.get() == "zh-CN" else "zh-CN")

    def _set_language(self, language: str) -> None:
        self.i18n.set_language(language)
        self.language_var.set(language)
        for status_var in self.model_status_vars.values():
            status_var.set(self.i18n.t("model_status_unknown"))
        self._persist_panel_config(show_message=False)
        current = self.active_page
        self.shell.destroy()
        self.pages = {}
        self.page_bodies = {}
        self.page_canvases = {}
        self.workflow_canvas = None
        self.workflow_nodes = {}
        self.preview_labels = []
        self._build_shell()
        self._show_page(current)

    def _show_page(self, key: str) -> None:
        self.active_page = key
        for frame in self.pages.values():
            frame.pack_forget()
        self.pages[key].pack(fill="both", expand=True, padx=46, pady=(18, 12))
        if key == "open_bind":
            self.root.after(100, self.auto_refresh_windows)

    def _scroll_page(self, parent: ttk.Frame) -> tuple[ttk.Frame, ttk.Frame]:
        outer = ttk.Frame(parent, style="App.TFrame")
        canvas = tk.Canvas(outer, bg="#ffffff", highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        body = ttk.Frame(canvas, style="App.TFrame")
        window_id = canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        body.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window_id, width=event.width))
        canvas.bind("<Enter>", lambda _event: canvas.bind_all("<MouseWheel>", self._on_mousewheel))
        canvas.bind("<Leave>", lambda _event: canvas.unbind_all("<MouseWheel>"))
        self.page_canvases[str(id(outer))] = canvas
        return outer, body

    def _on_mousewheel(self, event: tk.Event) -> None:
        page = self.pages.get(self.active_page)
        if page is None:
            return
        canvas = self.page_canvases.get(str(id(page)))
        if canvas is not None:
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def load_model_profiles(self) -> list[dict[str, Any]]:
        registry_profiles = self.registry_model_profiles()
        if registry_profiles:
            return self.unique_profiles(registry_profiles)
        legacy = self.panel_config.get("model_profiles")
        legacy_profiles = [item for item in legacy if isinstance(item, dict)] if isinstance(legacy, list) else []
        return self.unique_profiles(legacy_profiles + self.configured_model_profiles() + self.detect_model_profiles())

    def unique_profiles(self, profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_label: dict[str, dict[str, Any]] = {}
        for profile in profiles:
            label = str(profile.get("label") or profile.get("model_name") or profile.get("profile_id") or "").strip()
            if label:
                profile["label"] = label
                by_label.setdefault(label, profile)
        return list(by_label.values())

    def registry_model_profiles(self) -> list[dict[str, Any]]:
        profiles: list[dict[str, Any]] = []
        if not MODEL_PROFILE_DIR.exists():
            return profiles
        for path in sorted(MODEL_PROFILE_DIR.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(payload, dict):
                payload.setdefault("profile_path", str(path.relative_to(ROOT_DIR)))
                profiles.append(payload)
        return profiles

    def configured_model_profiles(self) -> list[dict[str, Any]]:
        vision = self.vision_config.get("vision") or {}
        profiles: list[dict[str, Any]] = []
        for mode, label_prefix in [
            ("local_understanding", "当前小模型"),
            ("local_grounding", "当前大模型"),
            ("local", "当前本地模型"),
        ]:
            local_cfg = vision.get(mode) if isinstance(vision.get(mode), dict) else {}
            model_name = str(local_cfg.get("model_name") or "").strip()
            endpoint = str(local_cfg.get("endpoint") or "").strip()
            if model_name or endpoint:
                profiles.append(
                    {
                        "profile_id": f"configured_{mode}",
                        "label": f"{label_prefix}: {model_name or endpoint}",
                        "model_name": model_name,
                        "endpoint": endpoint or "http://127.0.0.1:1234/v1/chat/completions",
                        "launchable": False,
                    }
                )
        return profiles

    def detect_model_profiles(self) -> list[dict[str, Any]]:
        profiles: list[dict[str, Any]] = []
        models_root = ROOT_DIR / "models"
        if not models_root.exists():
            return profiles
        for model_path in models_root.glob("**/*.gguf"):
            if model_path.name.lower().startswith("mmproj"):
                continue
            mmproj = next((item for item in model_path.parent.glob("mmproj*.gguf")), None)
            profiles.append(
                {
                    "profile_id": model_path.stem,
                    "label": model_path.stem,
                    "model_name": model_path.name,
                    "model_path": str(model_path.relative_to(ROOT_DIR)),
                    "mmproj_path": str(mmproj.relative_to(ROOT_DIR)) if mmproj else "",
                    "endpoint": "http://127.0.0.1:1234/v1/chat/completions",
                    "port": 1234,
                    "context_size": 4096,
                    "gpu_layers": 26,
                    "image_min_tokens": 1024,
                }
            )
        return profiles

    def model_profile_labels(self) -> list[str]:
        return [str(profile.get("label")) for profile in self.model_profiles if profile.get("label")]

    def preferred_profile_label(self, model_name: Any, endpoint: Any) -> str:
        model_text = str(model_name or "").strip()
        endpoint_text = str(endpoint or "").strip()
        for profile in self.model_profiles:
            if model_text and str(profile.get("model_name") or "").strip() == model_text:
                return str(profile.get("label") or "")
        for profile in self.model_profiles:
            if endpoint_text and str(profile.get("endpoint") or "").strip() == endpoint_text:
                return str(profile.get("label") or "")
        return ""

    def selected_model_profile(self, stage: str) -> dict[str, Any] | None:
        selected = self.observe_model_profile_var.get() if stage == "observe" else self.locate_model_profile_var.get()
        for profile in self.model_profiles:
            if str(profile.get("label")) == selected:
                return profile
        return self.model_profiles[0] if self.model_profiles else None

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

    def _model_profile_row(self, parent: ttk.Frame, variable: tk.StringVar) -> None:
        row = ttk.Frame(parent, style="App.TFrame")
        row.pack(fill="x", pady=5)
        ttk.Label(row, text=self.i18n.t("model_profile"), style="CardTitle.TLabel", width=18).pack(side="left")
        combo = ttk.Combobox(row, textvariable=variable, values=self.model_profile_labels(), state="readonly", width=54)
        combo.pack(side="left", fill="x", expand=True)

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
        ttk.Label(card, text=self.i18n.t("window_candidates"), style="CardTitle.TLabel").pack(anchor="w", pady=(8, 4))
        self.window_combo = ttk.Combobox(card, textvariable=self.window_choice_var, state="readonly", width=86)
        self.window_combo.pack(fill="x")
        self.window_combo.bind("<<ComboboxSelected>>", lambda _event: self.apply_selected_window())
        self._entry_row(card, "title", self.window_title_var)
        self._entry_row(card, "process", self.process_name_var, width=28)
        self._button_row(card, [("refresh_windows", self.call_list_windows), ("open_app", self.call_open_app), ("bind_window", self.call_bind_window)])

    def _build_capture_page(self, parent: ttk.Frame) -> None:
        self._header(parent, "capture_title", "capture_subtitle")
        capture = self._card(parent)
        self._entry_row(capture, "image_path", self.image_path_var)
        ttk.Label(capture, text=self.i18n.t("roi"), style="CardTitle.TLabel").pack(anchor="w", pady=(8, 0))
        self._small_fields(capture, [("x", self.roi_x_var), ("y", self.roi_y_var), ("w", self.roi_w_var), ("h", self.roi_h_var)])
        self._button_row(capture, [("capture_window", self.call_capture_window), ("choose_image", self.choose_image), ("open_image", lambda: self.open_path(self.image_path_var.get()))])

        preview = self._card(parent)
        ttk.Label(preview, text=self.i18n.t("preview"), style="CardTitle.TLabel").pack(anchor="w")
        self.preview_label = ttk.Label(preview, text=self.i18n.t("drop_image_hint"), style="Muted.TLabel")
        self.preview_label.pack(anchor="w", pady=(8, 0))
        self.preview_labels.append(self.preview_label)
        self._enable_file_drop(self.preview_label)

    def _build_observe_page(self, parent: ttk.Frame) -> None:
        self._header(parent, "observe_title", "observe_subtitle")
        model = self._card(parent)
        ttk.Label(model, text=self.i18n.t("small_model"), style="CardTitle.TLabel").pack(anchor="w")
        self._model_profile_row(model, self.observe_model_profile_var)
        self._entry_row(model, "model_name", self.small_model_var)
        self._entry_row(model, "endpoint", self.small_endpoint_var)
        self._button_row(
            model,
            [
                ("apply_model_profile", lambda: self.apply_model_profile("observe")),
                ("start_model_server", lambda: self.start_model_server("observe")),
                ("stop_model_server", lambda: self.stop_model_server("observe")),
                ("test_model_endpoint", lambda: self.test_model_endpoint("observe")),
            ],
        )
        ttk.Label(model, textvariable=self.model_status_vars["observe"], style="Muted.TLabel").pack(anchor="w", pady=(8, 0))
        card = self._card(parent)
        self._entry_row(card, "image_path", self.image_path_var)
        self._entry_row(card, "app_name", self.app_name_var, width=26)
        self._entry_row(card, "state_hint", self.state_hint_var)
        ttk.Label(card, text=self.i18n.t("prompt_rules"), style="CardTitle.TLabel").pack(anchor="w", pady=(8, 4))
        self.prompt_texts["observe"] = tk.Text(card, height=7, wrap="word", font=("Consolas", 10), borderwidth=1, relief="solid")
        self.prompt_texts["observe"].pack(fill="x")
        self.prompt_texts["observe"].insert("1.0", self.prompt_defaults["observe"])
        self._button_row(card, [("observe_screen", self.call_observe_screen), ("analyze_api", self.call_analyze_api)])

    def _build_locate_page(self, parent: ttk.Frame) -> None:
        self._header(parent, "locate_title", "locate_subtitle")
        model = self._card(parent)
        ttk.Label(model, text=self.i18n.t("large_model"), style="CardTitle.TLabel").pack(anchor="w")
        self._model_profile_row(model, self.locate_model_profile_var)
        self._entry_row(model, "model_name", self.large_model_var)
        self._entry_row(model, "endpoint", self.large_endpoint_var)
        self._button_row(
            model,
            [
                ("apply_model_profile", lambda: self.apply_model_profile("locate")),
                ("start_model_server", lambda: self.start_model_server("locate")),
                ("stop_model_server", lambda: self.stop_model_server("locate")),
                ("test_model_endpoint", lambda: self.test_model_endpoint("locate")),
            ],
        )
        ttk.Label(model, textvariable=self.model_status_vars["locate"], style="Muted.TLabel").pack(anchor="w", pady=(8, 0))
        card = self._card(parent)
        self._entry_row(card, "image_path", self.image_path_var)
        self._entry_row(card, "goal", self.goal_var)
        self._entry_row(card, "app_name", self.app_name_var, width=26)
        self._entry_row(card, "state_hint", self.state_hint_var)
        self._entry_row(card, "top_k", self.top_k_var, width=10)
        ttk.Label(card, text=self.i18n.t("prompt_rules"), style="CardTitle.TLabel").pack(anchor="w", pady=(8, 4))
        self.prompt_texts["locate"] = tk.Text(card, height=7, wrap="word", font=("Consolas", 10), borderwidth=1, relief="solid")
        self.prompt_texts["locate"].pack(fill="x")
        self.prompt_texts["locate"].insert("1.0", self.prompt_defaults["locate"])
        self._button_row(card, [("locate_target", self.call_locate_target), ("render_overlay", self.call_render_overlay), ("open_overlay", lambda: self.open_path(self.last_overlay_path))])

        box = self._card(parent)
        ttk.Label(box, text=self.i18n.t("manual_box"), style="CardTitle.TLabel").pack(anchor="w")
        self._small_fields(box, [("x", self.box_x_var), ("y", self.box_y_var), ("w", self.box_w_var), ("h", self.box_h_var), ("label", self.box_label_var)])
        self._button_row(box, [("manual_box_button", self.generate_manual_box), ("open_overlay", lambda: self.open_path(self.last_overlay_path))])

        preview = self._card(parent)
        ttk.Label(preview, text=self.i18n.t("candidate_preview"), style="CardTitle.TLabel").pack(anchor="w")
        self.locate_preview_label = ttk.Label(preview, text=self.i18n.t("drop_image_hint"), style="Muted.TLabel")
        self.locate_preview_label.pack(anchor="w", pady=(8, 0))
        self.preview_labels.append(self.locate_preview_label)
        self._enable_file_drop(self.locate_preview_label)

    def _build_execute_page(self, parent: ttk.Frame) -> None:
        self._header(parent, "execute_title", "execute_subtitle")
        card = self._card(parent)
        self._entry_row(card, "goal", self.goal_var)
        self._entry_row(card, "app_name", self.app_name_var, width=26)
        self._entry_row(card, "state_hint", self.state_hint_var)
        self._entry_row(card, "top_k", self.top_k_var, width=10)
        self._button_row(card, [("dry_run_click", self.call_dry_run_click), ("render_overlay", self.call_render_overlay)])

        confirmed = self._card(parent)
        ttk.Label(confirmed, text=self.i18n.t("confirmed_point"), style="CardTitle.TLabel").pack(anchor="w")
        self._small_fields(confirmed, [("x", self.box_x_var), ("y", self.box_y_var), ("w", self.box_w_var), ("h", self.box_h_var), ("label", self.box_label_var)])
        self._small_fields(confirmed, [("click_x", self.click_x_var), ("click_y", self.click_y_var)])
        self._button_row(
            confirmed,
            [
                ("confirmed_point_dry_run", lambda: self.call_confirmed_point(dry_run=True)),
                ("confirmed_point_click", self.call_real_confirmed_point),
            ],
        )

    def _build_models_page(self, parent: ttk.Frame) -> None:
        self._header(parent, "models_title", "models_subtitle")
        runtime = self._card(parent)
        ttk.Label(runtime, text=self.i18n.t("runtime"), style="CardTitle.TLabel").pack(anchor="w")
        self._entry_row(runtime, "base_url", self.runtime_base_url_var)
        self._entry_row(runtime, "timeout", self.timeout_var, width=12)
        self._button_row(runtime, [("test_health", self.call_health)])

        small = self._card(parent)
        ttk.Label(small, text=self.i18n.t("small_model"), style="CardTitle.TLabel").pack(anchor="w")
        self._model_profile_row(small, self.observe_model_profile_var)
        self._entry_row(small, "model_name", self.small_model_var)
        self._entry_row(small, "endpoint", self.small_endpoint_var)
        self._button_row(small, [("apply_model_profile", lambda: self.apply_model_profile("observe"))])

        large = self._card(parent)
        ttk.Label(large, text=self.i18n.t("large_model"), style="CardTitle.TLabel").pack(anchor="w")
        self._model_profile_row(large, self.locate_model_profile_var)
        self._entry_row(large, "model_name", self.large_model_var)
        self._entry_row(large, "endpoint", self.large_endpoint_var)
        self._entry_row(large, "model_start_script", self.model_start_script_var)
        self._entry_row(large, "model_stop_script", self.model_stop_script_var)
        self._button_row(large, [("apply_model_profile", lambda: self.apply_model_profile("locate"))])

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
        selected_stage = stage or self.active_page
        text = self.prompt_texts.get(selected_stage)
        if text is not None:
            return text.get("1.0", "end").strip()
        return self.prompt_defaults.get(selected_stage, self.prompt_defaults["locate"])

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

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float = 240.0,
        summary: str = "",
        workflow_step: str | None = None,
        show_error: bool = True,
    ) -> dict[str, Any] | None:
        try:
            self.mark_workflow(workflow_step, "active")
            response = self.client().get(path, timeout=timeout) if method == "GET" else self.client().post(path, payload or {}, timeout=timeout)
            self.set_response(response, summary=summary or path, workflow_step=workflow_step)
            return response
        except Exception as exc:
            self.mark_workflow(workflow_step, "error")
            if show_error:
                messagebox.showerror(self.i18n.t("failed"), str(exc))
            else:
                self.response_summary_var.set(str(exc))
            return None

    def request_async(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float = 240.0,
        summary: str = "",
        workflow_step: str | None = None,
    ) -> None:
        request_key = workflow_step or path
        if request_key in self.pending_requests:
            self.response_summary_var.set(self.i18n.t("request_already_running"))
            return
        self.pending_requests.add(request_key)
        self.mark_workflow(workflow_step, "active")
        self.response_summary_var.set(self.i18n.t("request_processing").format(action=summary or path))
        self.root.update_idletasks()
        client = self.client()
        if not self.async_polling:
            self.async_polling = True
            self.root.after(50, self._poll_async_results)

        def run_request() -> None:
            try:
                response = client.get(path, timeout=timeout) if method == "GET" else client.post(path, payload or {}, timeout=timeout)
                self.async_results.put((request_key, response, summary or path, workflow_step, None))
            except Exception as exc:
                self.async_results.put((request_key, None, summary or path, workflow_step, str(exc)))

        threading.Thread(target=run_request, daemon=True, name=f"settings-panel-{request_key}").start()

    def _poll_async_results(self) -> None:
        while True:
            try:
                request_key, response, summary, workflow_step, error = self.async_results.get_nowait()
            except queue.Empty:
                break
            self._finish_async_request(request_key, response, summary, workflow_step, error)
        if self.pending_requests:
            self.root.after(50, self._poll_async_results)
        else:
            self.async_polling = False

    def _finish_async_request(
        self,
        request_key: str,
        response: dict[str, Any] | None,
        summary: str,
        workflow_step: str | None,
        error: str | None,
    ) -> None:
        self.pending_requests.discard(request_key)
        if error is not None:
            self.set_response(
                {
                    "success": False,
                    "message": "Request failed",
                    "data": {"request": summary},
                    "error": {"code": "request_failed", "details": error},
                },
                summary=self.i18n.t("request_failed").format(error=error),
                workflow_step=workflow_step,
            )
            return
        self.set_response(response or {}, summary=summary, workflow_step=workflow_step)
        if workflow_step == "locate" and response and response.get("success"):
            self.populate_first_located_candidate(response)

    def set_response(self, response: dict[str, Any], *, summary: str, workflow_step: str | None = None) -> None:
        self.last_response = response
        self.response_summary_var.set(summary)
        if hasattr(self, "response_text"):
            self.response_text.delete("1.0", "end")
            self.response_text.insert("1.0", json.dumps(response, ensure_ascii=False, indent=2))
        if workflow_step:
            self.mark_workflow(workflow_step, "done" if response.get("success", True) else "error")

    def call_apps_list(self) -> None:
        response = self.request("GET", "/apps", timeout=20, summary="GET /apps", workflow_step="apps")
        windows = (((response or {}).get("data") or {}).get("running_windows") or []) if response else []
        if windows:
            self.set_window_candidates(windows)

    def auto_refresh_windows(self) -> None:
        if self.active_page != "open_bind":
            return
        self.call_list_windows(show_error=False)

    def call_list_windows(self, *, show_error: bool = True) -> None:
        response = self.request(
            "GET",
            "/session/windows",
            timeout=20,
            summary="GET /session/windows",
            workflow_step="open",
            show_error=show_error,
        )
        candidates = (((response or {}).get("data") or {}).get("candidates") or []) if response else []
        self.set_window_candidates(candidates)

    def set_window_candidates(self, candidates: list[dict[str, Any]]) -> None:
        self.window_candidates = candidates
        values = [self.window_candidate_label(item) for item in candidates]
        if hasattr(self, "window_combo"):
            self.window_combo.configure(values=values)
        if values:
            self.window_choice_var.set(values[0])
            self.apply_selected_window()
        else:
            self.window_choice_var.set("")

    def window_candidate_label(self, candidate: dict[str, Any]) -> str:
        title = str(candidate.get("title") or "")
        process = str(candidate.get("process_name") or "")
        process_id = candidate.get("process_id") or candidate.get("pid") or ""
        handle = candidate.get("handle") or ""
        prefix = f"{process}#{process_id}".strip("#")
        suffix = f" hwnd={handle}" if handle else ""
        return f"{prefix} | {title}{suffix}".strip()

    def apply_selected_window(self) -> None:
        selected = self.window_choice_var.get()
        for candidate in self.window_candidates:
            if self.window_candidate_label(candidate) == selected:
                title = candidate.get("title")
                process = candidate.get("process_name")
                if title:
                    self.window_title_var.set(str(title))
                if process:
                    self.process_name_var.set(str(process))
                return

    def call_open_app(self) -> None:
        payload = {"app_id": self.app_id_var.get().strip() or None, "bind_after_open": True}
        response = self.request("POST", "/apps/open", payload, timeout=60, summary="POST /apps/open", workflow_step="open")
        windows = (((response or {}).get("data") or {}).get("running_windows") or []) if response else []
        if windows:
            self.set_window_candidates(windows)

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
        self.request_async("POST", "/vision/observe_screen", payload, timeout=300, summary="POST /vision/observe_screen", workflow_step="observe")

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
        self.request_async("POST", "/vision/locate_target", payload, timeout=300, summary="POST /vision/locate_target", workflow_step="locate")

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
        self.request_async("POST", "/vision/analyze", payload, timeout=300, summary="POST /vision/analyze", workflow_step="observe")

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
        self.request_async("POST", "/action/execute_recognition_plan", payload, timeout=300, summary="POST /action/execute_recognition_plan dry_run", workflow_step="gate")

    def populate_first_located_candidate(self, response: dict[str, Any]) -> None:
        result = ((response.get("data") or {}).get("result") or {})
        candidate = result.get("recommended_target") if isinstance(result.get("recommended_target"), dict) else {}
        bbox = result.get("located_bbox")
        point = result.get("located_point")
        if not isinstance(bbox, dict):
            plan = result.get("recognition_plan") if isinstance(result.get("recognition_plan"), dict) else {}
            candidates = ((plan.get("candidate_result") or {}).get("candidates") or []) if isinstance(plan, dict) else []
            candidate = candidates[0] if candidates and isinstance(candidates[0], dict) else {}
            element = candidate.get("element") if isinstance(candidate.get("element"), dict) else {}
            bbox = element.get("bbox")
            point = element.get("click_point")
        if not isinstance(bbox, dict):
            return
        x = int(bbox.get("x", 0))
        y = int(bbox.get("y", 0))
        width = int(bbox.get("w", bbox.get("width", 0)))
        height = int(bbox.get("h", bbox.get("height", 0)))
        if width <= 0 or height <= 0:
            return
        click_point = point if isinstance(point, dict) else {"x": x + int(round(width / 2.0)), "y": y + int(round(height / 2.0))}
        self.box_x_var.set(str(x))
        self.box_y_var.set(str(y))
        self.box_w_var.set(str(width))
        self.box_h_var.set(str(height))
        self.box_label_var.set(str(candidate.get("label") or "target"))
        self.click_x_var.set(str(int(click_point.get("x", x + width // 2))))
        self.click_y_var.set(str(int(click_point.get("y", y + height // 2))))
        self.confirmed_point_source_trace_path = str(result.get("trace_path") or self.extract_trace_path(response) or "")

    def call_confirmed_point(self, *, dry_run: bool) -> None:
        try:
            payload = {
                "x": int(float(self.click_x_var.get())),
                "y": int(float(self.click_y_var.get())),
                "bbox": {
                    "x": int(float(self.box_x_var.get())),
                    "y": int(float(self.box_y_var.get())),
                    "width": int(float(self.box_w_var.get())),
                    "height": int(float(self.box_h_var.get())),
                },
                "label": self.box_label_var.get().strip() or None,
                "source_trace_path": self.confirmed_point_source_trace_path or None,
                "dry_run": dry_run,
            }
        except ValueError as exc:
            messagebox.showerror(self.i18n.t("failed"), str(exc))
            return
        summary = "POST /action/execute_confirmed_point dry_run" if dry_run else "POST /action/execute_confirmed_point real click"
        self.request_async("POST", "/action/execute_confirmed_point", payload, timeout=60, summary=summary, workflow_step="gate")

    def call_real_confirmed_point(self) -> None:
        message = self.i18n.t("confirmed_point_warning").format(x=self.click_x_var.get(), y=self.click_y_var.get())
        if messagebox.askyesno(self.i18n.t("confirmed_point_click"), message):
            self.call_confirmed_point(dry_run=False)

    def call_health(self) -> None:
        self.request("GET", "/health", timeout=8, summary="GET /health")

    def apply_model_profile(self, stage: str) -> None:
        profile = self.selected_model_profile(stage)
        if not profile:
            return
        model_name = str(profile.get("model_name") or Path(str(profile.get("model_path") or "")).name)
        endpoint = str(profile.get("endpoint") or "http://127.0.0.1:1234/v1/chat/completions")
        if stage == "observe":
            self.small_model_var.set(model_name)
            self.small_endpoint_var.set(endpoint)
        else:
            self.large_model_var.set(model_name)
            self.large_endpoint_var.set(endpoint)
        self.write_model_config()
        self._persist_panel_config(show_message=False)

    def start_model_server(self, stage: str = "locate") -> None:
        self.apply_model_profile(stage)
        profile = self.selected_model_profile(stage) or {}
        existing = self.probe_model_endpoint(stage)
        if existing is not None:
            if existing.get("_status") == "loading":
                self.model_status_vars[stage].set(self.i18n.t("model_status_loading"))
                self.set_response(existing, summary=self.i18n.t("model_status_loading"))
                return
            model_id = self.endpoint_model_id(existing)
            self.model_status_vars[stage].set(self.i18n.t("model_status_running").format(model=model_id))
            self.set_response(existing, summary=f"GET {self.local_model_base_url(stage)}/models")
            return
        script = self.resolve_path(str(profile.get("start_script") or self.model_start_script_var.get()))
        if not script.exists():
            messagebox.showwarning(self.i18n.t("path_missing"), str(script))
            return
        if profile.get("launchable") is False and not profile.get("model_path"):
            self.write_model_config()
            self._persist_panel_config(show_message=False)
            messagebox.showwarning(self.i18n.t("not_launchable_model"), self.i18n.t("not_launchable_model"))
            return
        self.write_model_config()
        self.model_status_vars[stage].set(self.i18n.t("model_status_starting"))
        self.root.update_idletasks()
        logs_dir = ROOT_DIR / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_path = logs_dir / f"local-vision-server-{time.strftime('%Y%m%d-%H%M%S')}.log"
        command = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
        ]
        for key, parameter in [
            ("model_path", "-ModelPath"),
            ("mmproj_path", "-MmprojPath"),
            ("server_path", "-ServerPath"),
            ("port", "-Port"),
            ("context_size", "-ContextSize"),
            ("gpu_layers", "-GpuLayers"),
            ("image_min_tokens", "-ImageMinTokens"),
        ]:
            value = profile.get(key)
            if value not in (None, ""):
                command.extend([parameter, str(self.resolve_path(str(value)) if key.endswith("_path") else value)])
        try:
            log_file = log_path.open("a", encoding="utf-8")
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
            process = subprocess.Popen(
                command,
                cwd=str(ROOT_DIR),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                creationflags=creationflags,
            )
            pid_path = self.profile_pid_path(profile)
            pid_path.parent.mkdir(parents=True, exist_ok=True)
            pid_path.write_text(str(process.pid), encoding="utf-8")
            self._persist_panel_config(show_message=False)
            self.set_response(
                {
                    "success": True,
                    "message": "Local vision server start requested",
                    "data": {
                        "pid": process.pid,
                        "stage": stage,
                        "profile": profile,
                        "script": str(script),
                        "log_path": str(log_path),
                        "pid_path": str(pid_path),
                    },
                    "error": None,
                },
                summary=self.i18n.t("start_model_server"),
            )
            self.model_status_vars[stage].set(self.i18n.t("model_status_requested"))
        except Exception as exc:
            if self.model_endpoint_is_loading(exc):
                status = self.i18n.t("model_status_loading")
                self.model_status_vars[stage].set(status)
                self.set_response(
                    {
                        "success": False,
                        "message": "Model is loading",
                        "data": {"stage": stage, "endpoint": self.local_model_base_url(stage)},
                        "error": {"code": "model_loading", "details": str(exc)},
                    },
                    summary=status,
                )
                return
            self.model_status_vars[stage].set(self.i18n.t("model_status_failed").format(error=exc))
            messagebox.showerror(self.i18n.t("failed"), str(exc))

    def stop_model_server(self, stage: str = "locate") -> None:
        profile = self.selected_model_profile(stage) or {}
        script = self.resolve_path(str(profile.get("stop_script") or self.model_stop_script_var.get()))
        if not script.exists():
            messagebox.showwarning(self.i18n.t("path_missing"), str(script))
            return
        command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)]
        if profile.get("port") not in (None, ""):
            command.extend(["-Port", str(profile.get("port"))])
        command.extend(["-PidFile", str(self.profile_pid_path(profile))])
        try:
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            completed = subprocess.run(command, cwd=str(ROOT_DIR), capture_output=True, text=True, creationflags=creationflags, timeout=30)
            response = {
                "success": completed.returncode == 0,
                "message": "Local vision server stop completed",
                "data": {
                    "script": str(script),
                    "returncode": completed.returncode,
                    "stdout": completed.stdout,
                    "stderr": completed.stderr,
                },
                "error": None if completed.returncode == 0 else {"code": "stop_model_server_failed", "details": completed.stderr},
            }
            self.set_response(response, summary=self.i18n.t("stop_model_server"))
            self.model_status_vars[stage].set(
                self.i18n.t("model_status_stopped") if completed.returncode == 0 else self.i18n.t("model_status_failed").format(error=completed.stderr)
            )
        except Exception as exc:
            self.model_status_vars[stage].set(self.i18n.t("model_status_failed").format(error=exc))
            messagebox.showerror(self.i18n.t("failed"), str(exc))

    def test_model_endpoint(self, stage: str = "locate") -> None:
        self.model_status_vars[stage].set(self.i18n.t("model_status_checking"))
        self.root.update_idletasks()
        try:
            base_url = self.local_model_base_url(stage)
            response = RuntimeHttpClient(base_url).get("/models", timeout=5)
            model_id = self.endpoint_model_id(response)
            self.model_status_vars[stage].set(self.i18n.t("model_status_running").format(model=model_id))
            self.set_response(response, summary=f"GET {base_url}/models")
        except Exception as exc:
            if self.model_endpoint_is_loading(exc):
                status = self.i18n.t("model_status_loading")
                self.model_status_vars[stage].set(status)
                self.set_response(
                    {
                        "success": False,
                        "message": "Model is loading",
                        "data": {"stage": stage, "endpoint": self.local_model_base_url(stage)},
                        "error": {"code": "model_loading", "details": str(exc)},
                    },
                    summary=status,
                )
                return
            self.model_status_vars[stage].set(self.i18n.t("model_status_failed").format(error=exc))
            self.set_response(
                {
                    "success": False,
                    "message": "Model service check failed",
                    "data": {"stage": stage, "endpoint": self.local_model_base_url(stage)},
                    "error": {"code": "model_service_unreachable", "details": str(exc)},
                },
                summary=self.i18n.t("model_status_failed").format(error=exc),
            )

    def probe_model_endpoint(self, stage: str) -> dict[str, Any] | None:
        try:
            return RuntimeHttpClient(self.local_model_base_url(stage)).get("/models", timeout=1.0)
        except Exception as exc:
            if self.model_endpoint_is_loading(exc):
                return {
                    "success": False,
                    "message": "Model is loading",
                    "data": {"stage": stage, "endpoint": self.local_model_base_url(stage)},
                    "error": {"code": "model_loading", "details": str(exc)},
                    "_status": "loading",
                }
            return None

    def model_endpoint_is_loading(self, error: Exception) -> bool:
        return "loading model" in str(error).casefold()

    def endpoint_model_id(self, response: dict[str, Any]) -> str:
        data = response.get("data")
        if isinstance(data, list) and data and isinstance(data[0], dict) and data[0].get("id"):
            return str(data[0]["id"])
        models = response.get("models")
        if isinstance(models, list) and models and isinstance(models[0], dict):
            return str(models[0].get("name") or models[0].get("model") or self.i18n.t("model_service"))
        return self.i18n.t("model_service")

    def local_model_base_url(self, stage: str = "locate") -> str:
        endpoint = self.small_endpoint_var.get().strip() if stage == "observe" else self.large_endpoint_var.get().strip()
        endpoint = endpoint or self.large_endpoint_var.get().strip() or self.small_endpoint_var.get().strip()
        if not endpoint:
            return "http://127.0.0.1:1234/v1"
        for suffix in ["/chat/completions", "/completions"]:
            if endpoint.endswith(suffix):
                return endpoint[: -len(suffix)]
        return endpoint.rstrip("/")

    def profile_pid_path(self, profile: dict[str, Any]) -> Path:
        pid_file = str(profile.get("pid_file") or "").strip()
        if pid_file:
            return self.resolve_path(pid_file)
        profile_id = str(profile.get("profile_id") or "local-vision").strip() or "local-vision"
        safe_id = "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in profile_id)
        return ROOT_DIR / "logs" / f"{safe_id}-server.pid"

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
        self.write_model_config()
        self._persist_panel_config(show_message=True)

    def write_model_config(self) -> None:
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

    def _persist_panel_config(self, *, show_message: bool) -> None:
        self.panel_config["runtime_base_url"] = self.runtime_base_url_var.get().strip()
        self.panel_config["language"] = self.language_var.get()
        self.panel_config["prompt_overrides"] = {
            "observe_additional_rules": self.current_prompt_rules("observe"),
            "locate_additional_rules": self.current_prompt_rules("locate"),
        }
        self.panel_config["model_scripts"] = {
            "start": self.model_start_script_var.get().strip(),
            "stop": self.model_stop_script_var.get().strip(),
        }
        self.panel_config["observe_model_profile"] = self.observe_model_profile_var.get()
        self.panel_config["locate_model_profile"] = self.locate_model_profile_var.get()
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

    def _enable_file_drop(self, widget: tk.Widget) -> None:
        if DND_FILES is None or not hasattr(widget, "drop_target_register"):
            return
        try:
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self.handle_image_drop)
        except Exception:
            return

    def handle_image_drop(self, event: Any) -> None:
        paths = self.root.tk.splitlist(event.data)
        for path in paths:
            resolved = self.resolve_path(str(path).strip("{}"))
            if resolved.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp"} and resolved.exists():
                self.image_path_var.set(str(resolved))
                self.load_preview(str(resolved))
                self.set_response(
                    {"success": True, "message": "Image dropped", "data": {"image_path": str(resolved)}, "error": None},
                    summary=self.i18n.t("drop_image_hint"),
                )
                return
        messagebox.showwarning(self.i18n.t("missing_image"), self.i18n.t("missing_image"))

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
        if not self.preview_labels:
            return
        try:
            image = Image.open(path)
            image.thumbnail((760, 250))
            self.preview_photo = ImageTk.PhotoImage(image)
            for label in self.preview_labels:
                label.configure(image=self.preview_photo, text="")
        except Exception:
            for label in self.preview_labels:
                label.configure(image="", text=path)

    def open_path(self, path: str) -> None:
        if not path:
            return
        resolved = self.resolve_path(path)
        if resolved.exists():
            os.startfile(str(resolved))  # type: ignore[attr-defined]
        else:
            messagebox.showwarning(self.i18n.t("path_missing"), str(resolved))

    def resolve_path(self, path: str) -> Path:
        resolved = Path(path).expanduser()
        if not resolved.is_absolute():
            resolved = ROOT_DIR / resolved
        return resolved

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
    root = TkinterDnD.Tk() if TkinterDnD is not None else tk.Tk()
    SettingsPanelApp(root)
    root.mainloop()
