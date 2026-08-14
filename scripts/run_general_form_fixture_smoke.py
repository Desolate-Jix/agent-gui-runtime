from __future__ import annotations

import argparse
import hashlib
import http.server
import json
import re
import shutil
import socketserver
import subprocess
import sys
import threading
import time
from functools import partial
from pathlib import Path
from typing import Any, Callable, Protocol

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.agent.form_answer_planner import plan_form_answer
from app.agent.form_workflow_controller import plan_form_workflow_turn
from app.gate.danger import scoped_final_submit_visible_blocker
from app.gate.form_policy import evaluate_form_action_policy
from app.operation.form_fill_executor import (
    execute_form_choice_select,
    execute_form_dropdown_open,
    execute_form_option_select,
    execute_form_text_fill,
    verify_form_choice_select_effect,
    verify_form_option_select_effect,
)
from app.operation.form_file_upload_executor import execute_form_file_upload, verify_form_file_upload_effect


class GeneralFormFixtureRuntime(Protocol):
    def start(self) -> None: ...

    def capture_current(self) -> dict[str, Any]: ...

    def locate_first_name_field(self, capture: dict[str, Any]) -> dict[str, Any]: ...

    def prepare_action_gate(self, candidate: dict[str, Any]) -> dict[str, Any]: ...

    def dispatch_approved_fill(self, approved_plan_id: str, **kwargs: Any) -> dict[str, Any]: ...

    def observe_field_projection(self) -> dict[str, Any]: ...

    def close(self) -> None: ...


class GeneralFormDropdownFixtureRuntime(Protocol):
    def start(self) -> None: ...

    def capture_current(self) -> dict[str, Any]: ...

    def locate_country_dropdown(self, capture: dict[str, Any]) -> dict[str, Any]: ...

    def locate_country_option(self, capture: dict[str, Any], *, option_label: str) -> dict[str, Any]: ...

    def prepare_click_action_gate(self, candidate: dict[str, Any], *, semantic_action: str) -> dict[str, Any]: ...

    def dispatch_approved_click(
        self,
        approved_plan_id: str,
        *,
        semantic_action: str,
        x: int,
        y: int,
    ) -> dict[str, Any]: ...

    def observe_country_projection(self) -> dict[str, Any]: ...

    def close(self) -> None: ...


class GeneralFormChoiceFixtureRuntime(Protocol):
    def start(self) -> None: ...

    def capture_current(self) -> dict[str, Any]: ...

    def locate_contact_radio(self, capture: dict[str, Any], *, option_label: str) -> dict[str, Any]: ...

    def locate_updates_checkbox(self, capture: dict[str, Any]) -> dict[str, Any]: ...

    def prepare_click_action_gate(self, candidate: dict[str, Any], *, semantic_action: str) -> dict[str, Any]: ...

    def dispatch_approved_click(
        self,
        approved_plan_id: str,
        *,
        semantic_action: str,
        x: int,
        y: int,
    ) -> dict[str, Any]: ...

    def observe_choice_projection(self, *, question_id: str) -> dict[str, Any]: ...

    def close(self) -> None: ...


class GeneralFormFileUploadFixtureRuntime(Protocol):
    def start(self) -> None: ...

    def capture_current(self) -> dict[str, Any]: ...

    def locate_resume_upload(self, capture: dict[str, Any]) -> dict[str, Any]: ...

    def prepare_click_action_gate(self, candidate: dict[str, Any], *, semantic_action: str) -> dict[str, Any]: ...

    def dispatch_approved_file_upload(self, approved_plan_id: str, **kwargs: Any) -> dict[str, Any]: ...

    def observe_file_upload_projection(self) -> dict[str, Any]: ...

    def close(self) -> None: ...


class GeneralFormWorkflowFixtureRuntime(
    GeneralFormFixtureRuntime,
    GeneralFormDropdownFixtureRuntime,
    GeneralFormChoiceFixtureRuntime,
    GeneralFormFileUploadFixtureRuntime,
    Protocol,
):
    def locate_continue_button(self, capture: dict[str, Any]) -> dict[str, Any]: ...

    def observe_final_review_projection(self) -> dict[str, Any]: ...


def _build_edge_launch_command(
    *,
    edge_path: Path,
    fixture_url: str,
    profile_dir: Path,
) -> list[str]:
    return [
        str(edge_path),
        f"--app={fixture_url}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--disable-sync",
        "--force-renderer-accessibility",
    ]


class WindowsGeneralFormFixtureRuntime:
    def __init__(
        self,
        *,
        fixture_path: Path,
        out_dir: Path,
        action_executor: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        text_executor: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        file_selector: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        self.fixture_path = fixture_path.resolve()
        self.out_dir = out_dir.resolve()
        self._action_executor = action_executor or _execute_recognition_action
        self._text_executor = text_executor or _execute_text_action
        self._file_selector = file_selector or _select_file_in_native_dialog
        self._server: socketserver.TCPServer | None = None
        self._server_thread: threading.Thread | None = None
        self._edge_process: subprocess.Popen[bytes] | None = None
        self._goal = "Focus the First name field in the controlled form fixture"
        self._approved_value = ""
        self._approved_option = ""
        self._current_capture: dict[str, Any] = {}
        self._fixture_window_handle: int | None = None

    def start(self) -> None:
        from app.core.window_manager import window_manager

        if not self.fixture_path.exists():
            raise FileNotFoundError(f"Fixture not found: {self.fixture_path}")
        self.out_dir.mkdir(parents=True, exist_ok=True)
        handler = partial(_QuietHTTPRequestHandler, directory=str(self.fixture_path.parent))
        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._server_thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._server_thread.start()
        port = int(self._server.server_address[1])
        edge_path = _find_edge_path()
        profile_dir = self.out_dir / "edge-profile"
        self._edge_process = subprocess.Popen(
            _build_edge_launch_command(
                edge_path=edge_path,
                fixture_url=f"http://127.0.0.1:{port}/{self.fixture_path.name}",
                profile_dir=profile_dir,
            ),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 20.0
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                bound = window_manager.bind_window("msedge.exe", "General Form Safe Fill Fixture")
                self._fixture_window_handle = int(bound.handle)
                window_manager.resize_bound_window(width=720, height=760, left=80, top=80, focus=True)
                return
            except Exception as exc:
                last_error = exc
                time.sleep(0.25)
        raise RuntimeError(f"Controlled fixture window could not be bound: {last_error}")

    def capture_current(self) -> dict[str, Any]:
        from app.core.screenshot import screenshot_service

        capture = screenshot_service.capture_window(
            save_image=True,
            purpose="general_form_fixture_smoke",
            name_hint="general_form_fixture",
        )
        image_path = Path(str(capture.get("image_path") or ""))
        if not image_path.exists():
            raise RuntimeError("Controlled fixture screenshot was not created")
        capture_id = hashlib.sha256(image_path.read_bytes()).hexdigest()
        self._current_capture = {
            "capture_id": capture_id,
            "image_path": str(image_path),
            "viewport_size": dict(capture.get("window_size") or {}),
        }
        return dict(self._current_capture)

    def locate_first_name_field(self, capture: dict[str, Any]) -> dict[str, Any]:
        from app.core.window_manager import window_manager
        from app.operation.screen_reading.uia_provider import uia_provider

        bound = window_manager.get_bound_window()
        if bound is None:
            raise RuntimeError("Controlled fixture window is not bound")
        snapshot = uia_provider.snapshot_window(bound, max_controls=300)
        controls = [item for item in snapshot.get("controls") or [] if isinstance(item, dict)]
        matches = [item for item in controls if _is_first_name_edit(item)]
        if len(matches) != 1:
            raise RuntimeError(f"Expected one First name UIA field, found {len(matches)}")
        bbox = dict(matches[0].get("bbox") or {})
        normalized_bbox = {
            "x": int(bbox.get("x") or 0),
            "y": int(bbox.get("y") or 0),
            "w": int(bbox.get("w") or 0),
            "h": int(bbox.get("h") or 0),
        }
        point = {
            "x": normalized_bbox["x"] + normalized_bbox["w"] // 2,
            "y": normalized_bbox["y"] + normalized_bbox["h"] // 2,
        }
        return {
            "candidate_id": "fixture-first-name",
            "label": "First name",
            "bbox": normalized_bbox,
            "click_point": point,
            "candidate_freshness": {
                "capture_id": capture["capture_id"],
                "viewport_size": capture["viewport_size"],
                "source": "windows_uia",
                "freshness": "current_capture",
            },
        }

    def locate_resume_upload(self, capture: dict[str, Any]) -> dict[str, Any]:
        controls = self._uia_controls()
        matches = [item for item in controls if _is_resume_upload_control(item)]
        if len(matches) != 1:
            raise RuntimeError(f"Expected one reviewed resume upload control, found {len(matches)}")
        return self._click_candidate_from_uia(
            control=matches[0],
            capture=capture,
            candidate_id="fixture-resume-upload",
            question_id="fixture-resume-upload",
            label="Upload resume",
        )

    def locate_continue_button(self, capture: dict[str, Any]) -> dict[str, Any]:
        controls = self._uia_controls()
        matches = [
            item
            for item in controls
            if str(item.get("automation_id") or "").casefold() == "continuetoreview"
            and str(item.get("control_type") or "").casefold() == "button"
            and item.get("visible") is not False
            and item.get("enabled") is not False
        ]
        if len(matches) != 1:
            raise RuntimeError(f"Expected one Continue UIA button, found {len(matches)}")
        return self._click_candidate_from_uia(
            control=matches[0],
            capture=capture,
            candidate_id="fixture-continue",
            question_id="fixture-continue",
            label="Continue",
        )

    def locate_country_dropdown(self, capture: dict[str, Any]) -> dict[str, Any]:
        controls = self._uia_controls()
        matches = [
            item
            for item in controls
            if str(item.get("automation_id") or "").casefold() == "country"
            and str(item.get("control_type") or "").casefold() == "combobox"
            and item.get("visible") is not False
            and item.get("enabled") is not False
        ]
        if len(matches) != 1:
            raise RuntimeError(f"Expected one Country UIA ComboBox, found {len(matches)}")
        return self._click_candidate_from_uia(
            control=matches[0],
            capture=capture,
            candidate_id="fixture-country-dropdown",
            question_id="fixture-country",
            label="Country",
        )

    def locate_country_option(self, capture: dict[str, Any], *, option_label: str) -> dict[str, Any]:
        controls = self._uia_controls()
        normalized_label = " ".join(str(option_label or "").split())
        matches = [
            item
            for item in controls
            if str(item.get("control_type") or "").casefold() == "listitem"
            and " ".join(str(item.get("name") or "").split()) == normalized_label
            and item.get("visible") is not False
        ]
        if not matches:
            raise RuntimeError("Reviewed Country option was not exposed after opening the dropdown")
        chosen = matches[0]
        candidate = self._click_candidate_from_uia(
            control=chosen,
            capture=capture,
            candidate_id="fixture-country-option-reviewed",
            question_id="fixture-country",
            label="Reviewed Country option",
        )
        candidate.update(
            {
                "option_label": normalized_label,
                "enabled": chosen.get("enabled") is True,
                "matching_label_count": len(matches),
            }
        )
        self._approved_option = normalized_label
        return candidate

    def locate_contact_radio(self, capture: dict[str, Any], *, option_label: str) -> dict[str, Any]:
        controls = self._uia_controls()
        normalized_label = " ".join(str(option_label or "").split())
        matches = [
            item
            for item in controls
            if str(item.get("control_type") or "").casefold() == "radiobutton"
            and " ".join(str(item.get("name") or "").split()) == normalized_label
            and item.get("visible") is not False
        ]
        if not matches:
            raise RuntimeError("Reviewed contact-method radio was not exposed by UIA")
        chosen = matches[0]
        candidate = self._click_candidate_from_uia(
            control=chosen,
            capture=capture,
            candidate_id="fixture-contact-email",
            question_id="fixture-contact-method",
            label="Reviewed contact method",
        )
        candidate.update(
            {
                "option_value": normalized_label,
                "enabled": chosen.get("enabled") is True,
                "matching_label_count": len(matches),
                "checked": self._choice_checked_from_projection(
                    controls,
                    prefix="contact-state checked=",
                ),
            }
        )
        return candidate

    def locate_updates_checkbox(self, capture: dict[str, Any]) -> dict[str, Any]:
        controls = self._uia_controls()
        option_value = "Receive status updates"
        matches = [
            item
            for item in controls
            if str(item.get("control_type") or "").casefold() == "checkbox"
            and " ".join(str(item.get("name") or "").split()) == option_value
            and item.get("visible") is not False
        ]
        if not matches:
            raise RuntimeError("Reviewed status-updates checkbox was not exposed by UIA")
        chosen = matches[0]
        candidate = self._click_candidate_from_uia(
            control=chosen,
            capture=capture,
            candidate_id="fixture-status-updates",
            question_id="fixture-status-updates",
            label="Reviewed status updates choice",
        )
        candidate.update(
            {
                "option_value": option_value,
                "enabled": chosen.get("enabled") is True,
                "matching_label_count": len(matches),
                "checked": self._choice_checked_from_projection(
                    controls,
                    prefix="updates-state checked=",
                ),
            }
        )
        return candidate

    @staticmethod
    def _choice_checked_from_projection(controls: list[dict[str, Any]], *, prefix: str) -> bool:
        names = [str(item.get("name") or "") for item in controls]
        state = next((name for name in names if name.startswith(prefix)), "")
        suffix = state[len(prefix) :].strip().casefold() if state.startswith(prefix) else ""
        if suffix not in {"true", "false"}:
            raise RuntimeError(f"Choice state projection is unavailable: {prefix}")
        return suffix == "true"

    def _uia_controls(self) -> list[dict[str, Any]]:
        from app.core.window_manager import window_manager
        from app.operation.screen_reading.uia_provider import uia_provider

        bound = window_manager.get_bound_window()
        if bound is None:
            raise RuntimeError("Controlled fixture window is not bound")
        snapshot = uia_provider.snapshot_window(bound, max_controls=400)
        return [item for item in snapshot.get("controls") or [] if isinstance(item, dict)]

    def _click_candidate_from_uia(
        self,
        *,
        control: dict[str, Any],
        capture: dict[str, Any],
        candidate_id: str,
        question_id: str,
        label: str,
    ) -> dict[str, Any]:
        bbox = dict(control.get("bbox") or {})
        normalized_bbox = {
            "x": int(bbox.get("x") or 0),
            "y": int(bbox.get("y") or 0),
            "w": int(bbox.get("w") or 0),
            "h": int(bbox.get("h") or 0),
        }
        return {
            "candidate_id": candidate_id,
            "question_id": question_id,
            "label": label,
            "bbox": normalized_bbox,
            "click_point": {
                "x": normalized_bbox["x"] + normalized_bbox["w"] // 2,
                "y": normalized_bbox["y"] + normalized_bbox["h"] // 2,
            },
            "candidate_freshness": {
                "capture_id": capture["capture_id"],
                "viewport_size": capture["viewport_size"],
                "source": "windows_uia",
                "freshness": "current_capture",
            },
        }

    def prepare_action_gate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        return self.prepare_click_action_gate(candidate, semantic_action="fill_field")

    def prepare_click_action_gate(
        self,
        candidate: dict[str, Any],
        *,
        semantic_action: str,
    ) -> dict[str, Any]:
        action_specs = {
            "fill_field": (self._goal, "textbox", "focus the reviewed text field"),
            "open_dropdown": (
                "Open the Country dropdown in the controlled form fixture",
                "combobox",
                "expand the reviewed Country dropdown",
            ),
            "select_option": (
                "Select the reviewed Country option in the controlled form fixture",
                "option",
                "select the reviewed option for the Country question",
            ),
            "select_radio": (
                "Select the reviewed contact method in the controlled form fixture",
                "radio",
                "select the reviewed radio option",
            ),
            "toggle_checkbox": (
                "Enable the reviewed status-updates choice in the controlled form fixture",
                "checkbox",
                "set the reviewed checkbox to checked",
            ),
            "upload_file": (
                "Open the reviewed file chooser in the controlled form fixture",
                "button",
                "open the native file chooser for the reviewed upload control",
            ),
            "continue_next_step": (
                "Continue to the final review in the controlled form fixture",
                "button",
                "open the final review without submitting the application",
            ),
        }
        if semantic_action not in action_specs:
            raise ValueError(f"Unsupported controlled fixture action: {semantic_action}")
        goal, role, expected_effect = action_specs[semantic_action]
        risk_class = "safe_reviewed_file_upload" if semantic_action == "upload_file" else "safe_click_allowed"
        metadata = {
            "semantic_action": semantic_action,
            "surface_context": "controlled_form_fixture",
            "seeded_candidate_v1": {
                "contract_version": "seeded_candidate_v1",
                "candidate_id": candidate.get("candidate_id"),
                "source": "current_capture_uia_fixture",
                "label": str(candidate.get("label") or "Reviewed fixture control"),
                "role": role,
                "bbox": candidate["bbox"],
                "click_point": candidate["click_point"],
                "risk_class": risk_class,
                "expected_effect": expected_effect,
            },
            "reviewed_test_execution": {"allow_seeded_candidate_without_model": True},
        }
        response = self._action_executor(
            {
                "goal": goal,
                "task": semantic_action,
                "app_name": "edge",
                "provider_mode": "local_grounding",
                "capture_live": True,
                "enable_post_click_verification": True,
                "dry_run": True,
                "metadata": metadata,
                "write_policy": {"path_graph": False, "element_memory": False, "trace": True},
            }
        )
        result = _result_payload(response)
        raw_action_gate = result.get("pre_click_decision") if isinstance(result.get("pre_click_decision"), dict) else {}
        action_gate = dict(raw_action_gate)
        operation_context = result.get("operation_context") if isinstance(result.get("operation_context"), dict) else {}
        observed_semantic_action = str(operation_context.get("semantic_action") or "").strip()
        if observed_semantic_action != semantic_action:
            raise RuntimeError(f"RecognitionPlan semantic action did not match {semantic_action}")
        action_gate["semantic_action"] = observed_semantic_action
        selected_id = action_gate.get("selected_candidate_id")
        selected_point = action_gate.get("selected_click_point")
        if response.get("success") is not True or action_gate.get("allowed") is not True:
            raise RuntimeError("RecognitionPlan dry-run did not approve the fixture field")
        if selected_id:
            candidate["candidate_id"] = selected_id
        if isinstance(selected_point, dict):
            candidate["click_point"] = {"x": int(selected_point["x"]), "y": int(selected_point["y"])}
        return {
            "approved_plan_id": result.get("approved_plan_id"),
            "action_gate": action_gate,
            "trace_path": result.get("trace_path"),
        }

    def dispatch_approved_click(
        self,
        approved_plan_id: str,
        *,
        semantic_action: str,
        x: int,
        y: int,
    ) -> dict[str, Any]:
        if not approved_plan_id:
            raise ValueError("approved_plan_id is required")
        if semantic_action not in {
            "open_dropdown",
            "select_option",
            "select_radio",
            "toggle_checkbox",
            "continue_next_step",
        }:
            raise ValueError(f"Unsupported controlled fixture click: {semantic_action}")
        if int(x) < 0 or int(y) < 0:
            raise ValueError("Approved click point must be non-negative")
        response = self._action_executor(
            {
                "goal": {
                    "open_dropdown": "Open the Country dropdown in the controlled form fixture",
                    "select_option": "Select the reviewed Country option in the controlled form fixture",
                    "select_radio": "Select the reviewed contact method in the controlled form fixture",
                    "toggle_checkbox": "Enable the reviewed status-updates choice in the controlled form fixture",
                    "continue_next_step": "Continue to the final review in the controlled form fixture",
                }[semantic_action],
                "task": semantic_action,
                "app_name": "edge",
                "approved_plan_id": approved_plan_id,
                "capture_live": True,
                "enable_post_click_verification": True,
                "dry_run": False,
                "metadata": {
                    "semantic_action": semantic_action,
                    "surface_context": "controlled_form_fixture",
                },
                "write_policy": {"path_graph": False, "element_memory": False, "trace": True},
            }
        )
        return {"success": response.get("success") is True, "trace_path": _trace_path(response)}

    def dispatch_approved_fill(self, approved_plan_id: str, **kwargs: Any) -> dict[str, Any]:
        if not approved_plan_id:
            raise ValueError("approved_plan_id is required")
        if kwargs.get("click_before_typing") is not True:
            raise ValueError("The fill contract must request a gated field click")
        if kwargs.get("clear_existing") is not True or kwargs.get("submit") is not False:
            raise ValueError("Controlled fill requires clear_existing=true and submit=false")
        self._approved_value = str(kwargs.get("text") or "")
        click_response = self._action_executor(
            {
                "goal": self._goal,
                "task": "fill_field",
                "app_name": "edge",
                "approved_plan_id": approved_plan_id,
                "capture_live": True,
                "enable_post_click_verification": True,
                "dry_run": False,
                "metadata": {"semantic_action": "fill_field", "surface_context": "controlled_form_fixture"},
                "write_policy": {"path_graph": False, "element_memory": False, "trace": True},
            }
        )
        if click_response.get("success") is not True:
            return {"success": False, "trace_path": _trace_path(click_response)}
        text_response = self._text_executor(
            {
                "text": self._approved_value,
                "click_before_typing": False,
                "clear_existing": True,
                "submit": False,
                "restore_clipboard": True,
                "dry_run": False,
                "metadata": {"semantic_action": "fill_field", "gated_click_trace_path": _trace_path(click_response)},
            }
        )
        return {"success": text_response.get("success") is True, "trace_path": _trace_path(text_response)}

    def dispatch_approved_file_upload(self, approved_plan_id: str, **kwargs: Any) -> dict[str, Any]:
        if not approved_plan_id:
            raise ValueError("approved_plan_id is required")
        if kwargs.get("click_before_selecting") is not True or kwargs.get("submit") is not False:
            raise ValueError("Reviewed upload requires gated picker click and forbids form submit")
        file_path = Path(str(kwargs.get("file_path") or ""))
        if not file_path.is_absolute() or not file_path.is_file():
            raise ValueError("Reviewed upload file must be an existing absolute path")
        click_response = self._action_executor(
            {
                "goal": "Open the reviewed file chooser in the controlled form fixture",
                "task": "upload_file",
                "app_name": "edge",
                "approved_plan_id": approved_plan_id,
                "capture_live": True,
                "enable_post_click_verification": True,
                "dry_run": False,
                "metadata": {
                    "semantic_action": "upload_file",
                    "surface_context": "controlled_form_fixture",
                    "reviewed_file": {
                        "extension": file_path.suffix.casefold(),
                        "size_bytes": file_path.stat().st_size,
                        "sha256": hashlib.sha256(file_path.read_bytes()).hexdigest(),
                        "path_redacted": True,
                    },
                },
                "write_policy": {"path_graph": False, "element_memory": False, "trace": True},
            }
        )
        if click_response.get("success") is not True:
            return {"success": False, "trace_path": _trace_path(click_response)}
        selection = self._file_selector({"file_path": str(file_path)})
        return {
            "success": selection.get("success") is True,
            "trace_path": selection.get("trace_path") or _trace_path(click_response),
        }

    def observe_field_projection(self) -> dict[str, Any]:
        from app.core.window_manager import window_manager
        from app.operation.screen_reading.uia_provider import uia_provider

        bound = window_manager.get_bound_window()
        if bound is None:
            raise RuntimeError("Controlled fixture window is not bound during verification")
        snapshot = uia_provider.snapshot_window(bound, max_controls=300)
        controls = [item for item in snapshot.get("controls") or [] if isinstance(item, dict)]
        names = [str(item.get("name") or "") for item in controls]
        field_state = next((name for name in names if name.startswith("field-state length=")), "")
        submit_state = next((name for name in names if name.startswith("submit-clicks=")), "")
        expected_hash = hashlib.sha256(self._approved_value.encode("utf-8")).hexdigest()
        expected_state = f"field-state length={len(self._approved_value)} sha256={expected_hash}"
        return {
            "value_matches_approved": field_state == expected_state,
            "submit_clicks": _suffix_int(submit_state, "submit-clicks="),
            "capture_id": self._current_capture.get("capture_id"),
        }

    def observe_file_upload_projection(self) -> dict[str, Any]:
        controls = self._uia_controls()
        names = [str(item.get("name") or "") for item in controls]
        upload_state = next((name for name in names if name.startswith("upload-state filename-sha256=")), "")
        submit_state = next((name for name in names if name.startswith("submit-clicks=")), "")
        prefix = "upload-state filename-sha256="
        if not upload_state.startswith(prefix) or " size=" not in upload_state:
            raise RuntimeError("Controlled file-upload state projection is unavailable")
        filename_hash, size_text = upload_state[len(prefix) :].split(" size=", 1)
        return {
            "question_id": "fixture-resume-upload",
            "filename_hash": filename_hash.strip(),
            "size_bytes": _safe_int(size_text),
            "submit_clicks": _suffix_int(submit_state, "submit-clicks="),
        }

    def observe_country_projection(self) -> dict[str, Any]:
        controls = self._uia_controls()
        names = [str(item.get("name") or "") for item in controls]
        country_state = next((name for name in names if name.startswith("country-state length=")), "")
        submit_state = next((name for name in names if name.startswith("submit-clicks=")), "")
        expected_hash = hashlib.sha256(self._approved_option.encode("utf-8")).hexdigest()
        expected_state = f"country-state length={len(self._approved_option)} sha256={expected_hash}"
        return {
            "selected_value": self._approved_option if country_state == expected_state else "",
            "submit_clicks": _suffix_int(submit_state, "submit-clicks="),
        }

    def observe_choice_projection(self, *, question_id: str) -> dict[str, Any]:
        controls = self._uia_controls()
        names = [str(item.get("name") or "") for item in controls]
        submit_state = next((name for name in names if name.startswith("submit-clicks=")), "")
        prefixes = {
            "fixture-contact-method": "contact-state checked=",
            "fixture-status-updates": "updates-state checked=",
        }
        prefix = prefixes.get(question_id)
        if prefix is None:
            raise ValueError(f"Unsupported fixture choice question: {question_id}")
        return {
            "question_id": question_id,
            "checked": self._choice_checked_from_projection(controls, prefix=prefix),
            "submit_clicks": _suffix_int(submit_state, "submit-clicks="),
        }

    def observe_final_review_projection(self) -> dict[str, Any]:
        controls = self._uia_controls()
        final_ids = {
            "finalreviewandsubmit",
            "finalsubmit",
            "finalsend",
            "finalcomplete",
        }
        actions: list[dict[str, Any]] = []
        for item in controls:
            automation_id = str(item.get("automation_id") or "").casefold()
            if (
                automation_id not in final_ids
                or str(item.get("control_type") or "").casefold() != "button"
                or item.get("visible") is False
            ):
                continue
            bbox = dict(item.get("bbox") or {})
            actions.append(
                {
                    "id": str(item.get("automation_id") or ""),
                    "text": " ".join(str(item.get("name") or "").split()),
                    "role": "button",
                    "bbox": {
                        "x": int(bbox.get("x") or 0),
                        "y": int(bbox.get("y") or 0),
                        "w": int(bbox.get("w") or 0),
                        "h": int(bbox.get("h") or 0),
                    },
                }
            )
        if not actions:
            raise RuntimeError("Final-review actions were not exposed by UIA")

        left = min(item["bbox"]["x"] for item in actions)
        top = min(item["bbox"]["y"] for item in actions)
        right = max(item["bbox"]["x"] + item["bbox"]["w"] for item in actions)
        bottom = max(item["bbox"]["y"] + item["bbox"]["h"] for item in actions)
        active_container = {
            "x": max(0, left - 32),
            "y": max(0, top - 96),
            "w": max(1, right - left + 64),
            "h": max(1, bottom - top + 160),
        }

        state_text = next(
            (
                str(item.get("name") or "")
                for item in controls
                if "real-clicks=" in str(item.get("name") or "")
                and "submit-clicks=" in str(item.get("name") or "")
            ),
            "",
        )
        state_match = re.search(r"real-clicks=(\d+)\s+submit-clicks=(\d+)", state_text)
        if state_match is None:
            raise RuntimeError("Final-review click state projection is unavailable")
        return {
            "surface_context": "final_review_submit",
            "active_container": active_container,
            "actions": actions,
            "real_clicks": int(state_match.group(1)),
            "submit_clicks": int(state_match.group(2)),
        }

    def close(self) -> None:
        if self._edge_process is not None:
            self._edge_process.terminate()
            try:
                self._edge_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._edge_process.kill()
            self._edge_process = None
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._server_thread is not None:
            self._server_thread.join(timeout=2)
            self._server_thread = None


def run_general_form_fixture_smoke(
    *,
    runtime: GeneralFormFixtureRuntime,
    approved_value: str,
    out_dir: Path,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "general_form_fixture_smoke_report.json"
    report: dict[str, Any] = {
        "contract_version": "general_form_fixture_smoke_report_v1",
        "status": "failed",
        "fixture_only": True,
        "live_fixture_fill_attempted": 0,
        "fill_effect_success": False,
        "submit_clicks": None,
        "no_submit": False,
        "pii_redacted": True,
        "artifact_is_authorization": False,
    }

    try:
        runtime.start()
        capture = runtime.capture_current()
        candidate = runtime.locate_first_name_field(capture)
        question = {
            "question_id": "fixture-first-name",
            "label": "First name",
            "field_type": "text",
            "required": True,
            "disabled": False,
            "risk": "low",
        }
        evidence = [
            {
                "evidence_id": "reviewed-fixture-first-name",
                "kind": "profile_field",
                "field_key": "first_name",
                "value": approved_value,
                "reviewed": True,
            }
        ]
        answer_decision = plan_form_answer(question=question, evidence=evidence)
        policy_gate = evaluate_form_action_policy(question=question, decision=answer_decision)
        prepared = runtime.prepare_action_gate(candidate)
        action_gate = prepared.get("action_gate") if isinstance(prepared, dict) else None
        approved_plan_id = str(prepared.get("approved_plan_id") or "") if isinstance(prepared, dict) else ""

        def dispatch(**kwargs: Any) -> dict[str, Any]:
            return runtime.dispatch_approved_fill(approved_plan_id, **kwargs)

        fill_result = execute_form_text_fill(
            question=question,
            answer_decision=answer_decision,
            policy_gate=policy_gate,
            candidate=candidate,
            current_capture_id=str(capture.get("capture_id") or ""),
            current_viewport_size=dict(capture.get("viewport_size") or {}),
            approved_value=approved_value,
            action_gate=action_gate if isinstance(action_gate, dict) else {},
            clear_existing=True,
            dispatch=dispatch,
        )
        report["live_fixture_fill_attempted"] = int(fill_result.get("dispatch_attempted") is True)
        projection = runtime.observe_field_projection() if fill_result.get("dispatch_success") is True else {}
        submit_clicks = _safe_int(projection.get("submit_clicks"))
        fill_effect_success = bool(projection.get("value_matches_approved") is True)
        no_submit = submit_clicks == 0
        report.update(
            {
                "status": "pass" if fill_effect_success and no_submit else "failed",
                "fill_effect_success": fill_effect_success,
                "submit_clicks": submit_clicks,
                "no_submit": no_submit,
                "capture_id": capture.get("capture_id"),
                "candidate_id": candidate.get("candidate_id"),
                "policy": answer_decision.get("policy"),
                "policy_gate_reason": policy_gate.get("reason"),
                "action_trace_path": prepared.get("trace_path") if isinstance(prepared, dict) else None,
                "dispatch_trace_path": fill_result.get("dispatch_trace_path"),
                "value_hash": answer_decision.get("value_hash"),
                "value_length": answer_decision.get("value_length"),
                "value_preview": answer_decision.get("value_preview"),
                "blocked_reason": fill_result.get("blocked_reason"),
            }
        )
    except Exception as exc:
        report["failure_category"] = "fixture_runtime_error"
        report["error_type"] = type(exc).__name__
    finally:
        runtime.close()
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def run_general_form_file_upload_fixture_smoke(
    *,
    runtime: GeneralFormFileUploadFixtureRuntime,
    approved_file_path: Path,
    out_dir: Path,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "general_form_file_upload_fixture_smoke_report.json"
    report: dict[str, Any] = {
        "contract_version": "general_form_file_upload_fixture_smoke_report_v1",
        "status": "failed",
        "fixture_only": True,
        "live_form_filling": False,
        "file_upload_attempted": 0,
        "file_upload_effect_success": False,
        "submit_clicks": None,
        "no_submit": False,
        "pii_redacted": True,
        "artifact_is_authorization": False,
    }
    try:
        resolved = approved_file_path.resolve()
        payload = resolved.read_bytes()
        reviewed_file = {
            "contract_version": "reviewed_file_evidence_v1",
            "absolute_path": str(resolved),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size_bytes": len(payload),
            "extension": resolved.suffix.casefold(),
            "human_approved": True,
            "single_use": True,
            "artifact_is_authorization": False,
        }
        runtime.start()
        before_capture = runtime.capture_current()
        candidate = runtime.locate_resume_upload(before_capture)
        question = {
            "contract_version": "form_question_contract_v1",
            "question_id": "fixture-resume-upload",
            "label": "Upload resume",
            "field_type": "file_upload",
            "required": True,
            "disabled": False,
            "risk": "reviewed_file_upload",
            "source_capture_id": before_capture.get("capture_id"),
        }
        prepared = runtime.prepare_click_action_gate(candidate, semantic_action="upload_file")
        action_gate = prepared.get("action_gate") if isinstance(prepared, dict) else {}
        approved_plan_id = str(prepared.get("approved_plan_id") or "") if isinstance(prepared, dict) else ""

        def dispatch(**kwargs: Any) -> dict[str, Any]:
            return runtime.dispatch_approved_file_upload(approved_plan_id, **kwargs)

        upload_result = execute_form_file_upload(
            question=question,
            reviewed_file=reviewed_file,
            candidate=candidate,
            current_capture_id=str(before_capture.get("capture_id") or ""),
            current_viewport_size=dict(before_capture.get("viewport_size") or {}),
            action_gate=action_gate if isinstance(action_gate, dict) else {},
            dispatch=dispatch,
        )
        report["file_upload_attempted"] = int(upload_result.get("dispatch_attempted") is True)
        projection: dict[str, Any] = {}
        effect: dict[str, Any] = {"verified": False, "failure_reasons": ["upload_not_dispatched"]}
        after_capture: dict[str, Any] = {}
        if upload_result.get("dispatch_success") is True:
            after_capture = runtime.capture_current()
            projection = runtime.observe_file_upload_projection()
            effect = verify_form_file_upload_effect(
                upload_result=upload_result,
                current_capture_id=str(after_capture.get("capture_id") or ""),
                observed_question_id=str(projection.get("question_id") or ""),
                observed_filename_hash=str(projection.get("filename_hash") or ""),
                observed_size_bytes=_safe_int(projection.get("size_bytes")),
            )
        submit_clicks = _safe_int(projection.get("submit_clicks"))
        effect_success = effect.get("verified") is True
        no_submit = submit_clicks == 0
        report.update(
            {
                "status": "pass" if effect_success and no_submit else "failed",
                "file_upload_effect_success": effect_success,
                "submit_clicks": submit_clicks,
                "no_submit": no_submit,
                "source_capture_id": before_capture.get("capture_id"),
                "observed_capture_id": after_capture.get("capture_id"),
                "candidate_id": candidate.get("candidate_id"),
                "file_sha256": upload_result.get("file_sha256"),
                "file_size_bytes": upload_result.get("file_size_bytes"),
                "file_extension": upload_result.get("file_extension"),
                "action_trace_path": prepared.get("trace_path") if isinstance(prepared, dict) else None,
                "dispatch_trace_path": upload_result.get("dispatch_trace_path"),
                "blocked_reason": upload_result.get("blocked_reason"),
                "effect_failure_reasons": effect.get("failure_reasons"),
            }
        )
    except Exception as exc:
        report["failure_category"] = "fixture_runtime_error"
        report["error_type"] = type(exc).__name__
        message = str(exc)
        try:
            message = message.replace(str(approved_file_path.resolve()), "[REDACTED_FILE]")
            message = message.replace(approved_file_path.name, "[REDACTED_FILE]")
        except (OSError, RuntimeError, ValueError):
            message = "fixture runtime failed before reviewed file validation"
        report["error_message"] = message
    finally:
        runtime.close()
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def run_general_form_dropdown_fixture_smoke(
    *,
    runtime: GeneralFormDropdownFixtureRuntime,
    approved_option: str,
    out_dir: Path,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "general_form_dropdown_fixture_smoke_report.json"
    report: dict[str, Any] = {
        "contract_version": "general_form_dropdown_fixture_smoke_report_v1",
        "status": "failed",
        "fixture_only": True,
        "live_form_filling": False,
        "dropdown_open_attempted": 0,
        "option_select_attempted": 0,
        "selection_effect_success": False,
        "submit_clicks": None,
        "no_submit": False,
        "pii_redacted": True,
        "report_value_redacted": True,
        "visible_grounding_evidence_may_include_option_labels": True,
        "artifact_is_authorization": False,
    }
    try:
        runtime.start()
        closed_capture = runtime.capture_current()
        question = {
            "question_id": "fixture-country",
            "label": "Country",
            "field_type": "select",
            "required": True,
            "disabled": False,
            "risk": "low",
        }
        evidence = [
            {
                "evidence_id": "reviewed-fixture-country",
                "kind": "derived_answer",
                "question_id": "fixture-country",
                "value": approved_option,
                "reviewed": True,
            }
        ]
        answer_decision = plan_form_answer(question=question, evidence=evidence)
        policy_gate = evaluate_form_action_policy(question=question, decision=answer_decision)

        dropdown_candidate = runtime.locate_country_dropdown(closed_capture)
        open_prepared = runtime.prepare_click_action_gate(
            dropdown_candidate,
            semantic_action="open_dropdown",
        )
        open_plan_id = str(open_prepared.get("approved_plan_id") or "")

        def dispatch_open(**kwargs: Any) -> dict[str, Any]:
            return runtime.dispatch_approved_click(
                open_plan_id,
                semantic_action="open_dropdown",
                **kwargs,
            )

        open_result = execute_form_dropdown_open(
            question=question,
            answer_decision=answer_decision,
            policy_gate=policy_gate,
            candidate=dropdown_candidate,
            current_capture_id=str(closed_capture.get("capture_id") or ""),
            current_viewport_size=dict(closed_capture.get("viewport_size") or {}),
            action_gate=dict(open_prepared.get("action_gate") or {}),
            dispatch=dispatch_open,
        )
        report["dropdown_open_attempted"] = int(open_result.get("dispatch_attempted") is True)
        if open_result.get("dispatch_success") is not True:
            report["blocked_reason"] = open_result.get("blocked_reason")
            return report

        open_capture = runtime.capture_current()
        option_candidate = runtime.locate_country_option(open_capture, option_label=approved_option)
        select_prepared = runtime.prepare_click_action_gate(
            option_candidate,
            semantic_action="select_option",
        )
        select_plan_id = str(select_prepared.get("approved_plan_id") or "")

        def dispatch_select(**kwargs: Any) -> dict[str, Any]:
            return runtime.dispatch_approved_click(
                select_plan_id,
                semantic_action="select_option",
                **kwargs,
            )

        select_result = execute_form_option_select(
            question=question,
            answer_decision=answer_decision,
            policy_gate=policy_gate,
            open_result=open_result,
            candidate=option_candidate,
            current_capture_id=str(open_capture.get("capture_id") or ""),
            current_viewport_size=dict(open_capture.get("viewport_size") or {}),
            approved_option=approved_option,
            action_gate=dict(select_prepared.get("action_gate") or {}),
            dispatch=dispatch_select,
        )
        report["option_select_attempted"] = int(select_result.get("dispatch_attempted") is True)
        if select_result.get("dispatch_success") is not True:
            report["blocked_reason"] = select_result.get("blocked_reason")
            return report

        selected_capture = runtime.capture_current()
        projection = runtime.observe_country_projection()
        effect = verify_form_option_select_effect(
            select_result=select_result,
            current_capture_id=str(selected_capture.get("capture_id") or ""),
            observed_question_id="fixture-country",
            observed_value=str(projection.get("selected_value") or ""),
        )
        submit_clicks = _safe_int(projection.get("submit_clicks"))
        effect_success = effect.get("verified") is True
        no_submit = submit_clicks == 0
        report.update(
            {
                "status": "pass" if effect_success and no_submit else "failed",
                "selection_effect_success": effect_success,
                "submit_clicks": submit_clicks,
                "no_submit": no_submit,
                "closed_capture_id": closed_capture.get("capture_id"),
                "open_capture_id": open_capture.get("capture_id"),
                "selected_capture_id": selected_capture.get("capture_id"),
                "open_action_trace_path": open_prepared.get("trace_path"),
                "open_dispatch_trace_path": open_result.get("dispatch_trace_path"),
                "select_action_trace_path": select_prepared.get("trace_path"),
                "select_dispatch_trace_path": select_result.get("dispatch_trace_path"),
                "value_hash": answer_decision.get("value_hash"),
                "value_length": answer_decision.get("value_length"),
                "value_preview": answer_decision.get("value_preview"),
                "effect_failure_reasons": effect.get("failure_reasons"),
            }
        )
    except Exception as exc:
        report["failure_category"] = "fixture_runtime_error"
        report["error_type"] = type(exc).__name__
    finally:
        runtime.close()
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def run_general_form_choice_fixture_smoke(
    *,
    runtime: GeneralFormChoiceFixtureRuntime,
    out_dir: Path,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "general_form_choice_fixture_smoke_report.json"
    report: dict[str, Any] = {
        "contract_version": "general_form_choice_fixture_smoke_report_v1",
        "status": "failed",
        "fixture_only": True,
        "live_form_filling": False,
        "radio_select_attempted": 0,
        "radio_effect_success": False,
        "checkbox_toggle_attempted": 0,
        "checkbox_effect_success": False,
        "already_selected_no_dispatch": False,
        "submit_clicks": None,
        "no_submit": False,
        "pii_redacted": True,
        "report_value_redacted": True,
        "visible_grounding_evidence_may_include_choice_labels": True,
        "artifact_is_authorization": False,
    }
    try:
        runtime.start()
        initial_capture = runtime.capture_current()
        radio_question = {
            "question_id": "fixture-contact-method",
            "label": "Preferred contact method",
            "field_type": "radio",
            "required": True,
            "disabled": False,
            "risk": "low",
        }
        radio_value = "Email"
        radio_evidence = [
            {
                "evidence_id": "reviewed-fixture-contact-method",
                "kind": "derived_answer",
                "question_id": radio_question["question_id"],
                "value": radio_value,
                "reviewed": True,
            }
        ]
        radio_decision = plan_form_answer(question=radio_question, evidence=radio_evidence)
        radio_policy_gate = evaluate_form_action_policy(question=radio_question, decision=radio_decision)
        radio_candidate = runtime.locate_contact_radio(initial_capture, option_label=radio_value)
        radio_prepared = runtime.prepare_click_action_gate(radio_candidate, semantic_action="select_radio")
        radio_plan_id = str(radio_prepared.get("approved_plan_id") or "")

        def dispatch_radio(**kwargs: Any) -> dict[str, Any]:
            return runtime.dispatch_approved_click(
                radio_plan_id,
                semantic_action="select_radio",
                **kwargs,
            )

        radio_result = execute_form_choice_select(
            question=radio_question,
            answer_decision=radio_decision,
            policy_gate=radio_policy_gate,
            candidate=radio_candidate,
            current_capture_id=str(initial_capture.get("capture_id") or ""),
            current_viewport_size=dict(initial_capture.get("viewport_size") or {}),
            approved_value=radio_value,
            expected_checked=True,
            action_gate=dict(radio_prepared.get("action_gate") or {}),
            semantic_action="select_radio",
            dispatch=dispatch_radio,
        )
        report["radio_select_attempted"] = int(radio_result.get("dispatch_attempted") is True)
        if radio_result.get("dispatch_success") is not True:
            report["blocked_reason"] = radio_result.get("blocked_reason")
            return report

        radio_selected_capture = runtime.capture_current()
        radio_projection = runtime.observe_choice_projection(question_id=radio_question["question_id"])
        radio_effect = verify_form_choice_select_effect(
            choice_result=radio_result,
            current_capture_id=str(radio_selected_capture.get("capture_id") or ""),
            observed_question_id=radio_question["question_id"],
            observed_checked=radio_projection.get("checked"),
        )
        report["radio_effect_success"] = radio_effect.get("verified") is True
        if radio_effect.get("verified") is not True:
            report["effect_failure_reasons"] = radio_effect.get("failure_reasons")
            return report

        refreshed_radio = runtime.locate_contact_radio(radio_selected_capture, option_label=radio_value)
        unexpected_dispatch = False

        def reject_repeat_dispatch(**_kwargs: Any) -> dict[str, Any]:
            nonlocal unexpected_dispatch
            unexpected_dispatch = True
            return {"success": False}

        already_selected = execute_form_choice_select(
            question=radio_question,
            answer_decision=radio_decision,
            policy_gate=radio_policy_gate,
            candidate=refreshed_radio,
            current_capture_id=str(radio_selected_capture.get("capture_id") or ""),
            current_viewport_size=dict(radio_selected_capture.get("viewport_size") or {}),
            approved_value=radio_value,
            expected_checked=True,
            action_gate={},
            semantic_action="select_radio",
            dispatch=reject_repeat_dispatch,
        )
        report["already_selected_no_dispatch"] = bool(
            already_selected.get("status") == "already_satisfied"
            and already_selected.get("dispatch_attempted") is False
            and unexpected_dispatch is False
        )

        checkbox_question = {
            "question_id": "fixture-status-updates",
            "label": "Receive status updates",
            "field_type": "checkbox",
            "required": False,
            "disabled": False,
            "risk": "low",
        }
        checkbox_value = "Receive status updates"
        checkbox_evidence = [
            {
                "evidence_id": "reviewed-fixture-status-updates",
                "kind": "derived_answer",
                "question_id": checkbox_question["question_id"],
                "value": checkbox_value,
                "reviewed": True,
            }
        ]
        checkbox_decision = plan_form_answer(question=checkbox_question, evidence=checkbox_evidence)
        checkbox_policy_gate = evaluate_form_action_policy(
            question=checkbox_question,
            decision=checkbox_decision,
        )
        checkbox_candidate = runtime.locate_updates_checkbox(radio_selected_capture)
        checkbox_prepared = runtime.prepare_click_action_gate(
            checkbox_candidate,
            semantic_action="toggle_checkbox",
        )
        checkbox_plan_id = str(checkbox_prepared.get("approved_plan_id") or "")

        def dispatch_checkbox(**kwargs: Any) -> dict[str, Any]:
            return runtime.dispatch_approved_click(
                checkbox_plan_id,
                semantic_action="toggle_checkbox",
                **kwargs,
            )

        checkbox_result = execute_form_choice_select(
            question=checkbox_question,
            answer_decision=checkbox_decision,
            policy_gate=checkbox_policy_gate,
            candidate=checkbox_candidate,
            current_capture_id=str(radio_selected_capture.get("capture_id") or ""),
            current_viewport_size=dict(radio_selected_capture.get("viewport_size") or {}),
            approved_value=checkbox_value,
            expected_checked=True,
            action_gate=dict(checkbox_prepared.get("action_gate") or {}),
            semantic_action="toggle_checkbox",
            dispatch=dispatch_checkbox,
        )
        report["checkbox_toggle_attempted"] = int(checkbox_result.get("dispatch_attempted") is True)
        if checkbox_result.get("dispatch_success") is not True:
            report["blocked_reason"] = checkbox_result.get("blocked_reason")
            return report

        checkbox_selected_capture = runtime.capture_current()
        checkbox_projection = runtime.observe_choice_projection(question_id=checkbox_question["question_id"])
        checkbox_effect = verify_form_choice_select_effect(
            choice_result=checkbox_result,
            current_capture_id=str(checkbox_selected_capture.get("capture_id") or ""),
            observed_question_id=checkbox_question["question_id"],
            observed_checked=checkbox_projection.get("checked"),
        )
        submit_clicks = _safe_int(checkbox_projection.get("submit_clicks"))
        checkbox_effect_success = checkbox_effect.get("verified") is True
        no_submit = submit_clicks == 0
        report.update(
            {
                "status": "pass"
                if (
                    report["radio_effect_success"]
                    and checkbox_effect_success
                    and report["already_selected_no_dispatch"]
                    and no_submit
                )
                else "failed",
                "checkbox_effect_success": checkbox_effect_success,
                "submit_clicks": submit_clicks,
                "no_submit": no_submit,
                "initial_capture_id": initial_capture.get("capture_id"),
                "radio_selected_capture_id": radio_selected_capture.get("capture_id"),
                "checkbox_selected_capture_id": checkbox_selected_capture.get("capture_id"),
                "radio_action_trace_path": radio_prepared.get("trace_path"),
                "radio_dispatch_trace_path": radio_result.get("dispatch_trace_path"),
                "checkbox_action_trace_path": checkbox_prepared.get("trace_path"),
                "checkbox_dispatch_trace_path": checkbox_result.get("dispatch_trace_path"),
                "radio_value_hash": radio_decision.get("value_hash"),
                "radio_value_length": radio_decision.get("value_length"),
                "checkbox_value_hash": checkbox_decision.get("value_hash"),
                "checkbox_value_length": checkbox_decision.get("value_length"),
                "checkbox_effect_failure_reasons": checkbox_effect.get("failure_reasons"),
            }
        )
    except Exception as exc:
        report["failure_category"] = "fixture_runtime_error"
        report["error_type"] = type(exc).__name__
        report["error_message"] = str(exc)
    finally:
        runtime.close()
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def run_general_form_workflow_fixture_smoke(
    *,
    runtime: GeneralFormWorkflowFixtureRuntime,
    approved_first_name: str,
    approved_country: str,
    approved_file_path: Path,
    out_dir: Path,
) -> dict[str, Any]:
    """在同一受控窗口中验证 Agent 表单决策、Gate、操作和最终安全停止。"""

    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "general_form_workflow_fixture_smoke_report.json"
    report: dict[str, Any] = {
        "contract_version": "general_form_workflow_fixture_smoke_report_v1",
        "status": "failed",
        "fixture_only": True,
        "live_ats_form_filling": False,
        "interpretation": (
            "controlled fixture workflow only; not evidence of live ATS form reliability"
        ),
        "steps": [],
        "agent_action_sequence": [],
        "safe_fill_fixture": {"passed": 0, "attempted": 0, "rate": "not_covered"},
        "file_upload_effect_success": False,
        "final_submit_guard": {},
        "safe_stop": False,
        "real_clicks": None,
        "submit_clicks": None,
        "no_submit": False,
        "pii_redacted": True,
        "artifact_is_authorization": False,
    }
    steps: list[dict[str, Any]] = report["steps"]
    completed: list[str] = []
    approved_file = approved_file_path.resolve()

    questions = [
        {
            "question_id": "fixture-first-name",
            "field_id": "fixture-first-name",
            "label": "First name",
            "field_type": "text",
            "required": True,
            "disabled": False,
            "risk": "low",
        },
        {
            "question_id": "fixture-country",
            "field_id": "fixture-country",
            "label": "Country",
            "field_type": "select",
            "required": True,
            "disabled": False,
            "risk": "low",
        },
        {
            "question_id": "fixture-contact-method",
            "field_id": "fixture-contact-method",
            "label": "Preferred contact method",
            "field_type": "radio",
            "required": True,
            "disabled": False,
            "risk": "low",
        },
        {
            "question_id": "fixture-status-updates",
            "field_id": "fixture-status-updates",
            "label": "Receive status updates",
            "field_type": "checkbox",
            "required": False,
            "disabled": False,
            "risk": "low",
        },
        {
            "contract_version": "form_question_contract_v1",
            "question_id": "fixture-resume-upload",
            "field_id": "fixture-resume-upload",
            "label": "Upload resume",
            "field_type": "file_upload",
            "required": True,
            "disabled": False,
            "risk": "reviewed_file_upload",
        },
    ]
    evidence = [
        {
            "evidence_id": "reviewed-fixture-first-name",
            "kind": "profile_field",
            "field_key": "first_name",
            "value": approved_first_name,
            "reviewed": True,
        },
        {
            "evidence_id": "reviewed-fixture-country",
            "kind": "derived_answer",
            "question_id": "fixture-country",
            "value": approved_country,
            "reviewed": True,
        },
        {
            "evidence_id": "reviewed-fixture-contact-method",
            "kind": "derived_answer",
            "question_id": "fixture-contact-method",
            "value": "Email",
            "reviewed": True,
        },
        {
            "evidence_id": "reviewed-fixture-status-updates",
            "kind": "derived_answer",
            "question_id": "fixture-status-updates",
            "value": "Receive status updates",
            "reviewed": True,
        },
        {
            "contract_version": "reviewed_file_evidence_v1",
            "evidence_id": "reviewed-fixture-resume",
            "kind": "reviewed_file",
            "question_id": "fixture-resume-upload",
            "reviewed": True,
            "human_approved": True,
            "single_use": True,
        },
    ]
    decisions = [plan_form_answer(question=question, evidence=evidence) for question in questions]

    def agent_turn(
        capture: dict[str, Any],
        *,
        continue_visible: bool = True,
        danger_actions: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        capture_id = str(capture.get("capture_id") or "")
        inventory_questions = [dict(question, capture_id=capture_id) for question in questions]
        inventory = {
            "contract_version": "form_question_inventory_v1",
            "form_state": "application_form_step",
            "capture_id": capture_id,
            "questions": inventory_questions,
            "fields": inventory_questions,
            "continue_action": (
                {
                    "action_id": "fixture-continue",
                    "text": "Continue",
                    "action_type": "continue_action",
                    "risk_class": "low_risk_navigation",
                    "capture_id": capture_id,
                }
                if continue_visible
                else None
            ),
            "danger_actions": list(danger_actions or []),
            "artifact_is_authorization": False,
        }
        answer_plan = {
            "contract_version": "form_answer_plan_v1",
            "capture_id": capture_id,
            "decisions": decisions,
            "pii_redacted": True,
            "fill_attempted": False,
            "submit_attempted": False,
            "artifact_is_authorization": False,
        }
        return plan_form_workflow_turn(
            interface_id=("fixture-final-review" if danger_actions else "fixture-application-form"),
            surface_status="ready",
            observation_evidence={
                "capture_id": capture_id,
                "screenshot_sha256": f"sha256:{capture_id}",
                "trace_path": str(capture.get("image_path") or ""),
            },
            inventory=inventory,
            answer_plan=answer_plan,
            completed_question_ids=completed,
        )

    def record_step(
        *,
        step_id: str,
        agent_decision: dict[str, Any],
        started_at: float,
        status: str,
        trace_paths: list[str | None] | None = None,
    ) -> None:
        action_type = str(agent_decision.get("action_type") or agent_decision.get("decision") or "")
        report["agent_action_sequence"].append(action_type)
        steps.append(
            {
                "step_id": step_id,
                "agent_action": action_type,
                "status": status,
                "duration_ms": round((time.monotonic() - started_at) * 1000, 3),
                "trace_paths": [str(item) for item in trace_paths or [] if item],
            }
        )

    try:
        if not approved_file.is_file():
            raise FileNotFoundError("Reviewed fixture file does not exist")
        runtime.start()
        capture = runtime.capture_current()
        safe_fill_passed = 0

        started = time.monotonic()
        decision = agent_turn(capture)
        if decision.get("action_type") != "fill_field":
            raise RuntimeError("Agent did not select the reviewed first-name field")
        candidate = runtime.locate_first_name_field(capture)
        prepared = runtime.prepare_action_gate(candidate)
        fill_result = execute_form_text_fill(
            question=questions[0],
            answer_decision=decisions[0],
            policy_gate=evaluate_form_action_policy(question=questions[0], decision=decisions[0]),
            candidate=candidate,
            current_capture_id=str(capture["capture_id"]),
            current_viewport_size=dict(capture["viewport_size"]),
            approved_value=approved_first_name,
            action_gate=dict(prepared.get("action_gate") or {}),
            clear_existing=True,
            dispatch=lambda **kwargs: runtime.dispatch_approved_fill(
                str(prepared.get("approved_plan_id") or ""), **kwargs
            ),
        )
        projection = runtime.observe_field_projection() if fill_result.get("dispatch_success") is True else {}
        if projection.get("value_matches_approved") is not True:
            raise RuntimeError("First-name fill effect was not verified")
        completed.append("fixture-first-name")
        safe_fill_passed += 1
        record_step(
            step_id="fill_first_name",
            agent_decision=decision,
            started_at=started,
            status="passed",
            trace_paths=[prepared.get("trace_path"), fill_result.get("dispatch_trace_path")],
        )
        capture = runtime.capture_current()

        started = time.monotonic()
        decision = agent_turn(capture)
        if decision.get("action_type") != "select_option" or decision.get("question_id") != "fixture-country":
            raise RuntimeError("Agent did not select the reviewed Country question")
        dropdown_candidate = runtime.locate_country_dropdown(capture)
        open_prepared = runtime.prepare_click_action_gate(dropdown_candidate, semantic_action="open_dropdown")
        open_result = execute_form_dropdown_open(
            question=questions[1],
            answer_decision=decisions[1],
            policy_gate=evaluate_form_action_policy(question=questions[1], decision=decisions[1]),
            candidate=dropdown_candidate,
            current_capture_id=str(capture["capture_id"]),
            current_viewport_size=dict(capture["viewport_size"]),
            action_gate=dict(open_prepared.get("action_gate") or {}),
            dispatch=lambda **kwargs: runtime.dispatch_approved_click(
                str(open_prepared.get("approved_plan_id") or ""),
                semantic_action="open_dropdown",
                **kwargs,
            ),
        )
        if open_result.get("dispatch_success") is not True:
            raise RuntimeError("Country dropdown did not open")
        open_capture = runtime.capture_current()
        option_candidate = runtime.locate_country_option(open_capture, option_label=approved_country)
        select_prepared = runtime.prepare_click_action_gate(option_candidate, semantic_action="select_option")
        select_result = execute_form_option_select(
            question=questions[1],
            answer_decision=decisions[1],
            policy_gate=evaluate_form_action_policy(question=questions[1], decision=decisions[1]),
            open_result=open_result,
            candidate=option_candidate,
            current_capture_id=str(open_capture["capture_id"]),
            current_viewport_size=dict(open_capture["viewport_size"]),
            approved_option=approved_country,
            action_gate=dict(select_prepared.get("action_gate") or {}),
            dispatch=lambda **kwargs: runtime.dispatch_approved_click(
                str(select_prepared.get("approved_plan_id") or ""),
                semantic_action="select_option",
                **kwargs,
            ),
        )
        selected_capture = runtime.capture_current()
        country_projection = runtime.observe_country_projection()
        country_effect = verify_form_option_select_effect(
            select_result=select_result,
            current_capture_id=str(selected_capture["capture_id"]),
            observed_question_id="fixture-country",
            observed_value=str(country_projection.get("selected_value") or ""),
        )
        if country_effect.get("verified") is not True:
            raise RuntimeError("Country selection effect was not verified")
        completed.append("fixture-country")
        safe_fill_passed += 1
        record_step(
            step_id="select_country",
            agent_decision=decision,
            started_at=started,
            status="passed",
            trace_paths=[
                open_prepared.get("trace_path"),
                open_result.get("dispatch_trace_path"),
                select_prepared.get("trace_path"),
                select_result.get("dispatch_trace_path"),
            ],
        )
        capture = selected_capture

        choice_specs = [
            (
                "select_contact_method",
                questions[2],
                decisions[2],
                "select_radio",
                lambda current: runtime.locate_contact_radio(current, option_label="Email"),
                "Email",
            ),
            (
                "toggle_status_updates",
                questions[3],
                decisions[3],
                "toggle_checkbox",
                runtime.locate_updates_checkbox,
                "Receive status updates",
            ),
        ]
        for step_id, question, answer_decision, semantic_action, locate, approved_value in choice_specs:
            started = time.monotonic()
            decision = agent_turn(capture)
            if decision.get("action_type") != "select_option" or decision.get("question_id") != question["question_id"]:
                raise RuntimeError(f"Agent did not select {question['question_id']}")
            candidate = locate(capture)
            prepared = runtime.prepare_click_action_gate(candidate, semantic_action=semantic_action)
            choice_result = execute_form_choice_select(
                question=question,
                answer_decision=answer_decision,
                policy_gate=evaluate_form_action_policy(question=question, decision=answer_decision),
                candidate=candidate,
                current_capture_id=str(capture["capture_id"]),
                current_viewport_size=dict(capture["viewport_size"]),
                approved_value=approved_value,
                expected_checked=True,
                action_gate=dict(prepared.get("action_gate") or {}),
                semantic_action=semantic_action,
                dispatch=lambda _prepared=prepared, _semantic_action=semantic_action, **kwargs: runtime.dispatch_approved_click(
                    str(_prepared.get("approved_plan_id") or ""),
                    semantic_action=_semantic_action,
                    **kwargs,
                ),
            )
            capture = runtime.capture_current()
            choice_projection = runtime.observe_choice_projection(question_id=str(question["question_id"]))
            choice_effect = verify_form_choice_select_effect(
                choice_result=choice_result,
                current_capture_id=str(capture["capture_id"]),
                observed_question_id=str(question["question_id"]),
                observed_checked=choice_projection.get("checked"),
            )
            if choice_effect.get("verified") is not True:
                raise RuntimeError(f"Choice effect was not verified: {question['question_id']}")
            completed.append(str(question["question_id"]))
            safe_fill_passed += 1
            record_step(
                step_id=step_id,
                agent_decision=decision,
                started_at=started,
                status="passed",
                trace_paths=[prepared.get("trace_path"), choice_result.get("dispatch_trace_path")],
            )

        started = time.monotonic()
        decision = agent_turn(capture)
        if decision.get("action_type") != "upload_file":
            raise RuntimeError("Agent did not select the reviewed file upload")
        upload_candidate = runtime.locate_resume_upload(capture)
        upload_prepared = runtime.prepare_click_action_gate(upload_candidate, semantic_action="upload_file")
        reviewed_file = {
            "contract_version": "reviewed_file_evidence_v1",
            "absolute_path": str(approved_file),
            "sha256": hashlib.sha256(approved_file.read_bytes()).hexdigest(),
            "size_bytes": approved_file.stat().st_size,
            "extension": approved_file.suffix.casefold(),
            "human_approved": True,
            "single_use": True,
            "artifact_is_authorization": False,
        }
        upload_result = execute_form_file_upload(
            question=questions[4],
            reviewed_file=reviewed_file,
            candidate=upload_candidate,
            current_capture_id=str(capture["capture_id"]),
            current_viewport_size=dict(capture["viewport_size"]),
            action_gate=dict(upload_prepared.get("action_gate") or {}),
            dispatch=lambda **kwargs: runtime.dispatch_approved_file_upload(
                str(upload_prepared.get("approved_plan_id") or ""), **kwargs
            ),
        )
        capture = runtime.capture_current()
        upload_projection = runtime.observe_file_upload_projection()
        upload_effect = verify_form_file_upload_effect(
            upload_result=upload_result,
            current_capture_id=str(capture["capture_id"]),
            observed_question_id=str(upload_projection.get("question_id") or ""),
            observed_filename_hash=str(upload_projection.get("filename_hash") or ""),
            observed_size_bytes=_safe_int(upload_projection.get("size_bytes")),
        )
        if upload_effect.get("verified") is not True:
            raise RuntimeError("Reviewed file upload effect was not verified")
        completed.append("fixture-resume-upload")
        safe_fill_passed += 1
        report["file_upload_effect_success"] = True
        record_step(
            step_id="upload_reviewed_file",
            agent_decision=decision,
            started_at=started,
            status="passed",
            trace_paths=[upload_prepared.get("trace_path"), upload_result.get("dispatch_trace_path")],
        )

        started = time.monotonic()
        decision = agent_turn(capture)
        if decision.get("action_type") != "continue_next_step":
            raise RuntimeError("Agent did not select Continue after completing reviewed questions")
        continue_candidate = runtime.locate_continue_button(capture)
        continue_prepared = runtime.prepare_click_action_gate(
            continue_candidate,
            semantic_action="continue_next_step",
        )
        point = continue_candidate["click_point"]
        continue_result = runtime.dispatch_approved_click(
            str(continue_prepared.get("approved_plan_id") or ""),
            semantic_action="continue_next_step",
            x=int(point["x"]),
            y=int(point["y"]),
        )
        if continue_result.get("success") is not True:
            raise RuntimeError("Continue action was not dispatched")
        record_step(
            step_id="continue_to_final_review",
            agent_decision=decision,
            started_at=started,
            status="passed",
            trace_paths=[continue_prepared.get("trace_path"), continue_result.get("trace_path")],
        )

        final_capture = runtime.capture_current()
        final_projection = runtime.observe_final_review_projection()
        guard = scoped_final_submit_visible_blocker(
            list(final_projection.get("actions") or []),
            active_container=dict(final_projection.get("active_container") or {}),
            active_flow_started=True,
            surface_context=str(final_projection.get("surface_context") or "final_review_submit"),
        )
        danger_actions = [
            {
                "action_id": str(item.get("id") or "final-submit"),
                "text": str(item.get("text") or ""),
                "action_type": "final_action",
                "risk_class": "final_submit",
                "capture_id": final_capture["capture_id"],
            }
            for item in guard.get("matched_items") or []
        ]
        started = time.monotonic()
        final_decision = agent_turn(
            final_capture,
            continue_visible=False,
            danger_actions=danger_actions,
        )
        if (
            guard.get("blocked") is not True
            or final_decision.get("action_type") != "safe_stop"
            or final_decision.get("unsafe_prevented") is not True
        ):
            raise RuntimeError("Final submit was not converted into a safe stop")
        record_step(
            step_id="final_submit_guard",
            agent_decision=final_decision,
            started_at=started,
            status="safe_stop",
        )

        real_clicks = _safe_int(final_projection.get("real_clicks"))
        submit_clicks = _safe_int(final_projection.get("submit_clicks"))
        no_submit = real_clicks == 0 and submit_clicks == 0
        report.update(
            {
                "status": "pass" if no_submit else "failed",
                "safe_fill_fixture": {
                    "passed": safe_fill_passed,
                    "attempted": 5,
                    "rate": safe_fill_passed / 5,
                },
                "final_submit_guard": guard,
                "safe_stop": True,
                "real_clicks": real_clicks,
                "submit_clicks": submit_clicks,
                "no_submit": no_submit,
                "final_capture_id": final_capture.get("capture_id"),
            }
        )
    except Exception as exc:
        report["failure_category"] = "integrated_fixture_runtime_error"
        report["error_type"] = type(exc).__name__
        message = str(exc)
        for private_value in (
            approved_first_name,
            approved_country,
            str(approved_file),
            approved_file.name,
        ):
            if private_value:
                message = message.replace(private_value, "[REDACTED]")
        report["error_message"] = message
    finally:
        runtime.close()
        durations = [float(step.get("duration_ms") or 0) for step in steps]
        report["max_action_duration_ms"] = max(durations, default=0.0)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


class _QuietHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        return None


def _find_edge_path() -> Path:
    candidates = [
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ]
    command = shutil.which("msedge") or shutil.which("msedge.exe")
    if command:
        candidates.insert(0, Path(command))
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("Microsoft Edge executable was not found")


def _is_first_name_edit(control: dict[str, Any]) -> bool:
    name = " ".join(str(control.get("name") or "").casefold().split())
    control_type = str(control.get("control_type") or "").casefold()
    automation_id = str(control.get("automation_id") or "").casefold()
    return bool(
        control.get("visible") is not False
        and control.get("enabled") is not False
        and ("edit" in control_type or "textbox" in control_type)
        and (name == "first name" or automation_id == "firstname")
    )


def _is_resume_upload_control(control: dict[str, Any]) -> bool:
    name = " ".join(str(control.get("name") or "").casefold().split())
    control_type = str(control.get("control_type") or "").casefold()
    automation_id = str(control.get("automation_id") or "").casefold()
    return bool(
        control.get("visible") is not False
        and control.get("enabled") is not False
        and "button" in control_type
        and (automation_id == "resumeupload" or name in {"choose file", "browse...", "browse"})
    )


def _select_file_in_native_dialog(payload: dict[str, Any]) -> dict[str, Any]:
    from app.core.window_manager import window_manager
    from app.operation.screen_reading.uia_provider import uia_provider

    file_path = Path(str(payload.get("file_path") or ""))
    if not file_path.is_absolute() or not file_path.is_file():
        raise ValueError("Native file selection requires an existing reviewed absolute path")
    form_bound = window_manager.get_bound_window()
    if form_bound is None:
        raise RuntimeError("Controlled form window is not bound before native file selection")
    form_handle = int(form_bound.handle)
    deadline = time.monotonic() + 12.0
    dialog_handle: int | None = None
    file_name_click_point: dict[str, int] | None = None
    while time.monotonic() < deadline and dialog_handle is None:
        matches: list[int] = []
        match_points: dict[int, dict[str, int]] = {}
        visible_windows = window_manager.list_visible_windows()
        for handle in _native_file_chooser_candidate_handles(
            form_handle=form_handle,
            visible_windows=visible_windows,
        ):
            try:
                bound = window_manager.bind_window_by_handle(handle)
                snapshot = uia_provider.snapshot_window(bound, max_controls=800)
            except Exception:
                continue
            chooser_controls = _native_file_chooser_controls(snapshot)
            if chooser_controls is not None:
                point = _control_bbox_center(chooser_controls["file_name_edit"])
                if point is None:
                    continue
                matches.append(handle)
                match_points[handle] = point
        if len(set(matches)) > 1:
            window_manager.bind_window_by_handle(form_handle)
            raise RuntimeError("Multiple native file chooser windows matched; refusing ambiguous selection")
        if matches:
            dialog_handle = matches[0]
            file_name_click_point = match_points[dialog_handle]
            window_manager.bind_window_by_handle(dialog_handle)
            break
        window_manager.bind_window_by_handle(form_handle)
        time.sleep(0.2)
    if dialog_handle is None:
        window_manager.bind_window_by_handle(form_handle)
        raise RuntimeError("Native file chooser was not structurally verified")
    if file_name_click_point is None:
        window_manager.bind_window_by_handle(form_handle)
        raise RuntimeError("Native file chooser filename field has no usable UIA geometry")

    try:
        response = _execute_text_action(
            {
                "text": str(file_path),
                "click_before_typing": True,
                "x": file_name_click_point["x"],
                "y": file_name_click_point["y"],
                "clear_existing": True,
                "submit": True,
                "restore_clipboard": True,
                "dry_run": False,
                "metadata": {
                    "semantic_action": "select_reviewed_file",
                    "surface_context": "native_file_chooser",
                    "reviewed_file": {
                        "extension": file_path.suffix.casefold(),
                        "size_bytes": file_path.stat().st_size,
                        "sha256": hashlib.sha256(file_path.read_bytes()).hexdigest(),
                        "path_redacted": True,
                    },
                },
            }
        )
        if response.get("success") is not True:
            return {"success": False, "trace_path": _trace_path(response)}
        close_deadline = time.monotonic() + 8.0
        while time.monotonic() < close_deadline:
            visible_handles = {
                int(item.get("handle") or 0)
                for item in window_manager.list_visible_windows()
                if item.get("handle") is not None
            }
            hosted_snapshot: dict[str, Any] | None = None
            if dialog_handle == form_handle:
                try:
                    current_bound = window_manager.bind_window_by_handle(form_handle)
                    hosted_snapshot = uia_provider.snapshot_window(
                        current_bound,
                        max_controls=800,
                    )
                except Exception:
                    hosted_snapshot = None
            if _native_file_chooser_is_closed(
                dialog_handle=dialog_handle,
                form_handle=form_handle,
                visible_handles=visible_handles,
                hosted_snapshot=hosted_snapshot,
            ):
                break
            time.sleep(0.2)
        else:
            return {"success": False, "trace_path": _trace_path(response)}
        return {"success": True, "trace_path": _trace_path(response)}
    finally:
        window_manager.bind_window_by_handle(form_handle)


def _native_file_chooser_candidate_handles(
    *,
    form_handle: int,
    visible_windows: list[dict[str, Any]],
) -> list[int]:
    handles = [form_handle] if form_handle > 0 else []
    seen = set(handles)
    for candidate in visible_windows:
        try:
            handle = int(candidate.get("handle") or 0)
        except (TypeError, ValueError):
            continue
        if handle <= 0 or handle in seen:
            continue
        seen.add(handle)
        handles.append(handle)
    return handles


def _snapshot_has_native_file_chooser(snapshot: dict[str, Any] | None) -> bool:
    return _native_file_chooser_controls(snapshot) is not None


def _native_file_chooser_controls(
    snapshot: dict[str, Any] | None,
) -> dict[str, dict[str, Any]] | None:
    controls = [
        item
        for item in (snapshot or {}).get("controls") or []
        if isinstance(item, dict)
    ]
    file_name_edit = next(
        (item for item in controls if _is_native_file_name_edit(item)),
        None,
    )
    open_button = next(
        (item for item in controls if _is_native_open_button(item)),
        None,
    )
    if file_name_edit is None or open_button is None:
        return None
    return {"file_name_edit": file_name_edit, "open_button": open_button}


def _control_bbox_center(control: dict[str, Any]) -> dict[str, int] | None:
    bbox = control.get("bbox") if isinstance(control.get("bbox"), dict) else {}
    try:
        x = int(bbox.get("x") or 0)
        y = int(bbox.get("y") or 0)
        w = int(bbox.get("w") or 0)
        h = int(bbox.get("h") or 0)
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    return {"x": x + w // 2, "y": y + h // 2}


def _native_file_chooser_is_closed(
    *,
    dialog_handle: int,
    form_handle: int,
    visible_handles: set[int],
    hosted_snapshot: dict[str, Any] | None,
) -> bool:
    if dialog_handle != form_handle:
        return dialog_handle not in visible_handles
    if hosted_snapshot is None:
        return False
    return not _snapshot_has_native_file_chooser(hosted_snapshot)


def _is_native_file_name_edit(control: dict[str, Any]) -> bool:
    name = " ".join(str(control.get("name") or "").casefold().split())
    control_type = str(control.get("control_type") or "").casefold()
    automation_id = str(control.get("automation_id") or "").casefold()
    return bool(
        control.get("visible") is not False
        and control.get("enabled") is not False
        and "edit" in control_type
        and (automation_id in {"1148", "filenamecontrolhost"} or name in {"file name:", "file name", "文件名:"})
    )


def _is_native_open_button(control: dict[str, Any]) -> bool:
    name = " ".join(str(control.get("name") or "").casefold().split())
    name = re.sub(r"\s*\(&?[a-z]\)\s*$", "", name)
    control_type = str(control.get("control_type") or "").casefold()
    return bool(
        control.get("visible") is not False
        and control.get("enabled") is not False
        and "button" in control_type
        and name in {"open", "打开"}
    )


def _execute_recognition_action(payload: dict[str, Any]) -> dict[str, Any]:
    from app.api import action as action_api
    from app.api.models.request import ExecuteRecognitionPlanRequest

    response = action_api.execute_recognition_plan(ExecuteRecognitionPlanRequest(**payload))
    return response.model_dump()


def _execute_text_action(payload: dict[str, Any]) -> dict[str, Any]:
    from app.api import action as action_api
    from app.api.models.request import TypeTextRequest

    response = action_api.type_text(TypeTextRequest(**payload))
    return response.model_dump()


def _result_payload(response: dict[str, Any]) -> dict[str, Any]:
    data = response.get("data") if isinstance(response.get("data"), dict) else {}
    result = data.get("result") if isinstance(data.get("result"), dict) else data
    return result if isinstance(result, dict) else {}


def _trace_path(response: dict[str, Any]) -> str | None:
    value = _result_payload(response).get("trace_path")
    return str(value) if value else None


def _suffix_int(value: str, prefix: str) -> int:
    if not value.startswith(prefix):
        return -1
    return _safe_int(value[len(prefix) :])


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the controlled general-form safe-fill fixture smoke.")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--mode",
        choices=("text", "dropdown", "choice", "upload", "workflow"),
        default="text",
    )
    parser.add_argument("--approved-file", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    fixture_path = {
        "upload": Path("tests/fixtures/general_form_file_upload_site/index.html"),
        "workflow": Path("tests/fixtures/general_form_workflow_site/index.html"),
    }.get(args.mode, Path("tests/fixtures/general_form_live_site/index.html"))
    runtime = WindowsGeneralFormFixtureRuntime(
        fixture_path=fixture_path,
        out_dir=args.out,
    )
    if args.mode in {"upload", "workflow"}:
        approved_file = args.approved_file or (args.out / "synthetic_reviewed_resume.pdf")
        if args.approved_file is None:
            approved_file.parent.mkdir(parents=True, exist_ok=True)
            approved_file.write_bytes(b"%PDF-1.4\ncontrolled synthetic fixture\n%%EOF\n")
        if args.mode == "workflow":
            report = run_general_form_workflow_fixture_smoke(
                runtime=runtime,
                approved_first_name="Synthetic Fixture Name",
                approved_country="New Zealand",
                approved_file_path=approved_file,
                out_dir=args.out,
            )
        else:
            report = run_general_form_file_upload_fixture_smoke(
                runtime=runtime,
                approved_file_path=approved_file,
                out_dir=args.out,
            )
    elif args.mode == "choice":
        report = run_general_form_choice_fixture_smoke(
            runtime=runtime,
            out_dir=args.out,
        )
    elif args.mode == "dropdown":
        report = run_general_form_dropdown_fixture_smoke(
            runtime=runtime,
            approved_option="New Zealand",
            out_dir=args.out,
        )
    else:
        report = run_general_form_fixture_smoke(
            runtime=runtime,
            approved_value="Synthetic Fixture Name",
            out_dir=args.out,
        )
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    return 0 if report.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
