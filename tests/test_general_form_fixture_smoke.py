from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import scripts.run_general_form_fixture_smoke as fixture_smoke
from scripts.run_general_form_fixture_smoke import (
    WindowsGeneralFormFixtureRuntime,
    _build_edge_launch_command,
    _is_native_file_name_edit,
    _is_native_open_button,
    run_general_form_choice_fixture_smoke,
    run_general_form_dropdown_fixture_smoke,
    run_general_form_file_upload_fixture_smoke,
    run_general_form_fixture_smoke,
    run_general_form_workflow_fixture_smoke,
)


class FakeRuntime:
    def __init__(self) -> None:
        self.closed = False
        self.dispatched = False

    def start(self) -> None:
        return None

    def capture_current(self) -> dict:
        return {
            "capture_id": "capture-current",
            "image_path": "fixture.png",
            "viewport_size": {"width": 640, "height": 520},
        }

    def locate_first_name_field(self, capture: dict) -> dict:
        assert capture["capture_id"] == "capture-current"
        return {
            "candidate_id": "seeded_general-form-first-name",
            "label": "First name",
            "bbox": {"x": 90, "y": 180, "w": 420, "h": 44},
            "click_point": {"x": 300, "y": 202},
            "candidate_freshness": {
                "capture_id": "capture-current",
                "viewport_size": {"width": 640, "height": 520},
                "source": "windows_uia",
                "freshness": "current_capture",
            },
        }

    def prepare_action_gate(self, candidate: dict) -> dict:
        return {
            "approved_plan_id": "approved-plan-1",
            "action_gate": {
                "contract_version": "pre_click_decision_v1",
                "allowed": True,
                "semantic_action": "fill_field",
                "selected_candidate_id": candidate["candidate_id"],
                "selected_click_point": candidate["click_point"],
            },
            "trace_path": "dry-run-trace.json",
        }

    def dispatch_approved_fill(self, approved_plan_id: str, **kwargs) -> dict:
        assert approved_plan_id == "approved-plan-1"
        assert kwargs["click_before_typing"] is True
        assert kwargs["clear_existing"] is True
        assert kwargs["submit"] is False
        self.dispatched = True
        return {"success": True, "trace_path": "fill-trace.json"}

    def observe_field_projection(self) -> dict:
        assert self.dispatched is True
        return {"value_matches_approved": True, "submit_clicks": 0, "capture_id": "capture-current"}

    def close(self) -> None:
        self.closed = True


def test_fixture_smoke_runs_safe_fill_and_redacts_raw_value(tmp_path: Path) -> None:
    runtime = FakeRuntime()

    report = run_general_form_fixture_smoke(
        runtime=runtime,
        approved_value="PrivateFixtureName",
        out_dir=tmp_path,
    )

    assert report["status"] == "pass"
    assert report["live_fixture_fill_attempted"] == 1
    assert report["fill_effect_success"] is True
    assert report["submit_clicks"] == 0
    assert report["no_submit"] is True
    assert runtime.closed is True
    serialized = json.dumps(report, ensure_ascii=False)
    assert "PrivateFixtureName" not in serialized
    report_text = (tmp_path / "general_form_fixture_smoke_report.json").read_text(encoding="utf-8")
    assert "PrivateFixtureName" not in report_text


def test_fixture_smoke_fails_when_submit_was_clicked(tmp_path: Path) -> None:
    runtime = FakeRuntime()

    def unsafe_projection() -> dict:
        return {"value_matches_approved": True, "submit_clicks": 1, "capture_id": "capture-current"}

    runtime.observe_field_projection = unsafe_projection  # type: ignore[method-assign]
    report = run_general_form_fixture_smoke(runtime=runtime, approved_value="Synthetic", out_dir=tmp_path)

    assert report["status"] == "failed"
    assert report["submit_clicks"] == 1
    assert report["no_submit"] is False


class FakeFileUploadRuntime:
    def __init__(self) -> None:
        self.closed = False
        self.dispatched = False
        self.capture_index = 0
        self.file_path: Path | None = None

    def start(self) -> None:
        return None

    def capture_current(self) -> dict:
        self.capture_index += 1
        return {
            "capture_id": "capture-before-upload" if self.capture_index == 1 else "capture-after-upload",
            "image_path": "fixture.png",
            "viewport_size": {"width": 720, "height": 760},
        }

    def locate_resume_upload(self, capture: dict) -> dict:
        assert capture["capture_id"] == "capture-before-upload"
        return {
            "candidate_id": "fixture-resume-upload",
            "question_id": "fixture-resume-upload",
            "label": "Upload resume",
            "bbox": {"x": 100, "y": 220, "w": 260, "h": 44},
            "click_point": {"x": 230, "y": 242},
            "candidate_freshness": {
                "capture_id": "capture-before-upload",
                "viewport_size": {"width": 720, "height": 760},
                "source": "windows_uia",
                "freshness": "current_capture",
            },
        }

    def prepare_click_action_gate(self, candidate: dict, *, semantic_action: str) -> dict:
        assert semantic_action == "upload_file"
        return {
            "approved_plan_id": "approved-upload-file",
            "action_gate": {
                "contract_version": "pre_click_decision_v1",
                "allowed": True,
                "semantic_action": semantic_action,
                "selected_candidate_id": candidate["candidate_id"],
                "selected_click_point": candidate["click_point"],
            },
            "trace_path": "dry-run-upload.json",
        }

    def dispatch_approved_file_upload(self, approved_plan_id: str, **kwargs) -> dict:
        assert approved_plan_id == "approved-upload-file"
        assert kwargs["click_before_selecting"] is True
        assert kwargs["submit"] is False
        self.file_path = Path(kwargs["file_path"])
        self.dispatched = True
        return {"success": True, "trace_path": "upload-file.json"}

    def observe_file_upload_projection(self) -> dict:
        assert self.dispatched is True
        assert self.file_path is not None
        return {
            "question_id": "fixture-resume-upload",
            "filename_hash": __import__("hashlib").sha256(self.file_path.name.encode("utf-8")).hexdigest(),
            "size_bytes": self.file_path.stat().st_size,
            "submit_clicks": 0,
        }

    def close(self) -> None:
        self.closed = True


def test_file_upload_fixture_smoke_uses_reviewed_file_and_redacts_path(tmp_path: Path) -> None:
    approved_file = tmp_path / "synthetic_resume.pdf"
    approved_file.write_bytes(b"%PDF-1.4\nfixture\n%%EOF\n")
    runtime = FakeFileUploadRuntime()

    report = run_general_form_file_upload_fixture_smoke(
        runtime=runtime,
        approved_file_path=approved_file,
        out_dir=tmp_path / "out",
    )

    assert report["status"] == "pass"
    assert report["fixture_only"] is True
    assert report["live_form_filling"] is False
    assert report["file_upload_attempted"] == 1
    assert report["file_upload_effect_success"] is True
    assert report["submit_clicks"] == 0
    assert report["no_submit"] is True
    assert runtime.closed is True
    serialized = json.dumps(report, ensure_ascii=False)
    assert str(approved_file.resolve()) not in serialized
    assert approved_file.name not in serialized


def test_file_upload_fixture_smoke_fails_when_submit_was_clicked(tmp_path: Path) -> None:
    approved_file = tmp_path / "synthetic_resume.pdf"
    approved_file.write_bytes(b"%PDF-1.4\nfixture\n%%EOF\n")
    runtime = FakeFileUploadRuntime()

    def unsafe_projection() -> dict:
        projection = FakeFileUploadRuntime.observe_file_upload_projection(runtime)
        projection["submit_clicks"] = 1
        return projection

    runtime.observe_file_upload_projection = unsafe_projection  # type: ignore[method-assign]
    report = run_general_form_file_upload_fixture_smoke(
        runtime=runtime,
        approved_file_path=approved_file,
        out_dir=tmp_path / "out",
    )

    assert report["status"] == "failed"
    assert report["file_upload_effect_success"] is True
    assert report["no_submit"] is False


def test_file_upload_fixture_smoke_reports_sanitized_runtime_error(tmp_path: Path) -> None:
    approved_file = tmp_path / "synthetic_resume.pdf"
    approved_file.write_bytes(b"%PDF-1.4\nfixture\n%%EOF\n")
    runtime = FakeFileUploadRuntime()

    def fail_with_private_path(_capture: dict) -> dict:
        raise RuntimeError(f"unable to select {approved_file.resolve()}")

    runtime.locate_resume_upload = fail_with_private_path  # type: ignore[method-assign]
    report = run_general_form_file_upload_fixture_smoke(
        runtime=runtime,
        approved_file_path=approved_file,
        out_dir=tmp_path / "out",
    )

    assert report["status"] == "failed"
    assert report["failure_category"] == "fixture_runtime_error"
    assert report["error_type"] == "RuntimeError"
    assert report["error_message"] == "unable to select [REDACTED_FILE]"
    serialized = json.dumps(report, ensure_ascii=False)
    assert str(approved_file.resolve()) not in serialized
    assert approved_file.name not in serialized


def test_native_file_chooser_matchers_accept_utf8_chinese_labels() -> None:
    assert _is_native_file_name_edit(
        {
            "name": "文件名:",
            "control_type": "Edit",
            "automation_id": "FileNameControlHost",
            "visible": True,
            "enabled": True,
        }
    ) is True
    assert _is_native_open_button(
        {
            "name": "打开",
            "control_type": "Button",
            "visible": True,
            "enabled": True,
        }
    ) is True


def test_native_file_chooser_candidate_handles_include_hosted_form_window() -> None:
    handles = fixture_smoke._native_file_chooser_candidate_handles(
        form_handle=101,
        visible_windows=[
            {"handle": 202},
            {"handle": 101},
            {"handle": 202},
            {"handle": 0},
        ],
    )

    assert handles == [101, 202]


def test_native_file_chooser_snapshot_requires_filename_edit_and_open_button() -> None:
    chooser_snapshot = {
        "controls": [
            {
                "name": "文件名(N):",
                "control_type": "Edit",
                "automation_id": "1148",
                "visible": True,
                "enabled": True,
            },
            {
                "name": "打开(O)",
                "control_type": "Button",
                "automation_id": "1",
                "visible": True,
                "enabled": True,
            },
        ]
    }
    upload_page_only = {
        "controls": [
            {
                "name": "Upload resume: 未选择文件",
                "control_type": "Button",
                "automation_id": "resumeUpload",
                "visible": True,
                "enabled": True,
            }
        ]
    }

    assert fixture_smoke._snapshot_has_native_file_chooser(chooser_snapshot) is True
    assert fixture_smoke._snapshot_has_native_file_chooser(upload_page_only) is False


def test_hosted_native_file_chooser_closes_when_structural_controls_disappear() -> None:
    assert fixture_smoke._native_file_chooser_is_closed(
        dialog_handle=101,
        form_handle=101,
        visible_handles={101, 202},
        hosted_snapshot={"controls": []},
    ) is True
    assert fixture_smoke._native_file_chooser_is_closed(
        dialog_handle=202,
        form_handle=101,
        visible_handles={101},
        hosted_snapshot=None,
    ) is True


def test_native_file_selector_accepts_structurally_verified_chooser_on_form_handle(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from types import SimpleNamespace

    from app.core.window_manager import window_manager
    from app.operation.screen_reading.uia_provider import uia_provider

    reviewed_file = tmp_path / "reviewed.pdf"
    reviewed_file.write_bytes(b"%PDF-1.4\nfixture\n%%EOF\n")
    form_bound = SimpleNamespace(handle=101, title="Form", process_name="msedge.exe")
    other_bound = SimpleNamespace(handle=202, title="Other", process_name="other.exe")
    snapshots_for_form = [
        {
            "controls": [
                {
                    "name": "文件名(N):",
                    "control_type": "Edit",
                    "automation_id": "1148",
                    "bbox": {"x": 100, "y": 200, "w": 300, "h": 20},
                    "visible": True,
                    "enabled": True,
                },
                {
                    "name": "打开(O)",
                    "control_type": "Button",
                    "automation_id": "1",
                    "visible": True,
                    "enabled": True,
                },
            ]
        },
        {"controls": []},
    ]
    typed: list[dict] = []

    monkeypatch.setattr(window_manager, "get_bound_window", lambda: form_bound)
    monkeypatch.setattr(
        window_manager,
        "list_visible_windows",
        lambda: [{"handle": 101}, {"handle": 202}],
    )
    monkeypatch.setattr(
        window_manager,
        "bind_window_by_handle",
        lambda handle: form_bound if int(handle) == 101 else other_bound,
    )

    def snapshot_window(bound, *, max_controls: int):
        assert max_controls == 800
        if int(bound.handle) == 101:
            return snapshots_for_form.pop(0)
        return {"controls": []}

    monkeypatch.setattr(uia_provider, "snapshot_window", snapshot_window)

    def execute_text(payload: dict) -> dict:
        typed.append(payload)
        return {
            "success": True,
            "data": {"result": {"trace_path": "native-file-selection.json"}},
        }

    monkeypatch.setattr(fixture_smoke, "_execute_text_action", execute_text)

    result = fixture_smoke._select_file_in_native_dialog(
        {"file_path": str(reviewed_file.resolve())}
    )

    assert result == {"success": True, "trace_path": "native-file-selection.json"}
    assert len(typed) == 1
    assert typed[0]["metadata"]["semantic_action"] == "select_reviewed_file"
    assert typed[0]["metadata"]["reviewed_file"]["path_redacted"] is True
    assert typed[0]["click_before_typing"] is True
    assert typed[0]["x"] == 250
    assert typed[0]["y"] == 210


def test_upload_gate_uses_explicit_reviewed_file_risk_class(tmp_path: Path) -> None:
    calls: list[dict] = []

    def action_executor(payload: dict) -> dict:
        calls.append(payload)
        return {
            "success": True,
            "data": {
                "result": {
                    "approved_plan_id": "approved-upload-file",
                    "pre_click_decision": {
                        "allowed": True,
                        "selected_candidate_id": "seeded_fixture-resume-upload",
                        "selected_click_point": {"x": 230, "y": 242},
                    },
                    "operation_context": {"semantic_action": "upload_file"},
                    "trace_path": "dry-run-trace.json",
                }
            },
        }

    runtime = WindowsGeneralFormFixtureRuntime(
        fixture_path=Path("tests/fixtures/general_form_file_upload_site/index.html"),
        out_dir=tmp_path,
        action_executor=action_executor,
    )
    runtime.prepare_click_action_gate(
        {
            "candidate_id": "fixture-resume-upload",
            "label": "Upload resume",
            "bbox": {"x": 100, "y": 220, "w": 260, "h": 44},
            "click_point": {"x": 230, "y": 242},
        },
        semantic_action="upload_file",
    )

    assert len(calls) == 1
    assert calls[0]["metadata"]["seeded_candidate_v1"]["risk_class"] == "safe_reviewed_file_upload"


def test_fixture_contains_safe_field_and_final_submit_decoy() -> None:
    html_path = Path("tests/fixtures/general_form_live_site/index.html")
    html = html_path.read_text(encoding="utf-8")

    assert 'id="firstName"' in html
    assert 'id="finalSubmit"' in html
    assert "Submit application" in html
    assert "submit-clicks=0" in html


def test_file_upload_fixture_contains_reviewed_upload_projection_and_submit_decoy() -> None:
    html = Path("tests/fixtures/general_form_file_upload_site/index.html").read_text(encoding="utf-8")

    assert 'id="resumeUpload" type="file"' in html
    assert "upload-state filename-sha256=none size=0" in html
    assert 'id="continueButton"' in html
    assert 'id="finalSubmit"' in html
    assert "continue-clicks=0" in html
    assert "submit-clicks=0" in html


def test_windows_runtime_dispatches_gated_file_upload_without_path_in_action_trace(tmp_path: Path) -> None:
    approved_file = tmp_path / "synthetic_resume.pdf"
    approved_file.write_bytes(b"%PDF-1.4\nfixture\n%%EOF\n")
    action_calls: list[dict] = []
    selector_calls: list[dict] = []

    def action_executor(payload: dict) -> dict:
        action_calls.append(payload)
        return {"success": True, "data": {"result": {"trace_path": "open-picker.json"}}}

    def file_selector(payload: dict) -> dict:
        selector_calls.append(payload)
        return {"success": True, "trace_path": "choose-file.json"}

    runtime = WindowsGeneralFormFixtureRuntime(
        fixture_path=Path("tests/fixtures/general_form_file_upload_site/index.html"),
        out_dir=tmp_path,
        action_executor=action_executor,
        file_selector=file_selector,
    )

    result = runtime.dispatch_approved_file_upload(
        "approved-upload-file",
        file_path=str(approved_file.resolve()),
        x=230,
        y=242,
        click_before_selecting=True,
        submit=False,
    )

    assert result == {"success": True, "trace_path": "choose-file.json"}
    assert len(action_calls) == 1
    assert action_calls[0]["approved_plan_id"] == "approved-upload-file"
    assert action_calls[0]["metadata"]["semantic_action"] == "upload_file"
    assert str(approved_file.resolve()) not in json.dumps(action_calls, ensure_ascii=False)
    assert approved_file.name not in json.dumps(action_calls, ensure_ascii=False)
    assert selector_calls == [{"file_path": str(approved_file.resolve())}]


def test_windows_runtime_clicks_with_approved_plan_before_typing_without_second_click(tmp_path: Path) -> None:
    calls: list[tuple[str, dict]] = []

    def action_executor(payload: dict) -> dict:
        calls.append(("recognition_plan", payload))
        return {"success": True, "data": {"result": {"trace_path": "click-trace.json"}}}

    def text_executor(payload: dict) -> dict:
        calls.append(("type_text", payload))
        return {"success": True, "data": {"result": {"trace_path": "type-trace.json"}}}

    runtime = WindowsGeneralFormFixtureRuntime(
        fixture_path=Path("tests/fixtures/general_form_live_site/index.html"),
        out_dir=tmp_path,
        action_executor=action_executor,
        text_executor=text_executor,
    )
    runtime._goal = "Focus the First name field in the controlled form fixture"
    runtime._approved_value = "Synthetic"

    result = runtime.dispatch_approved_fill(
        "approved-plan-1",
        text="Synthetic",
        x=300,
        y=202,
        click_before_typing=True,
        clear_existing=True,
        submit=False,
        restore_clipboard=True,
    )

    assert result == {"success": True, "trace_path": "type-trace.json"}
    assert [name for name, _ in calls] == ["recognition_plan", "type_text"]
    assert calls[0][1]["approved_plan_id"] == "approved-plan-1"
    assert calls[0][1]["dry_run"] is False
    assert calls[0][1]["metadata"]["semantic_action"] == "fill_field"
    assert calls[1][1]["click_before_typing"] is False
    assert calls[1][1]["clear_existing"] is True
    assert calls[1][1]["submit"] is False


def test_windows_runtime_projects_verified_fill_semantic_action_into_action_gate(tmp_path: Path) -> None:
    def action_executor(payload: dict) -> dict:
        assert payload["metadata"]["semantic_action"] == "fill_field"
        return {
            "success": True,
            "data": {
                "result": {
                    "approved_plan_id": "approved-plan-1",
                    "trace_path": "dry-run-trace.json",
                    "operation_context": {"semantic_action": "fill_field"},
                    "pre_click_decision": {
                        "contract_version": "pre_click_decision_v1",
                        "allowed": True,
                        "selected_candidate_id": "fixture-first-name",
                        "selected_click_point": {"x": 300, "y": 202},
                    },
                }
            },
        }

    runtime = WindowsGeneralFormFixtureRuntime(
        fixture_path=Path("tests/fixtures/general_form_live_site/index.html"),
        out_dir=tmp_path,
        action_executor=action_executor,
    )
    candidate = {
        "candidate_id": "fixture-first-name",
        "bbox": {"x": 90, "y": 180, "w": 420, "h": 44},
        "click_point": {"x": 300, "y": 202},
    }

    prepared = runtime.prepare_action_gate(candidate)

    assert prepared["action_gate"]["semantic_action"] == "fill_field"


def test_windows_runtime_rejects_semantic_action_context_mismatch(tmp_path: Path) -> None:
    def action_executor(_payload: dict) -> dict:
        return {
            "success": True,
            "data": {
                "result": {
                    "approved_plan_id": "approved-plan-1",
                    "operation_context": {"semantic_action": "open_detail"},
                    "pre_click_decision": {
                        "contract_version": "pre_click_decision_v1",
                        "allowed": True,
                        "selected_candidate_id": "fixture-first-name",
                        "selected_click_point": {"x": 300, "y": 202},
                    },
                }
            },
        }

    runtime = WindowsGeneralFormFixtureRuntime(
        fixture_path=Path("tests/fixtures/general_form_live_site/index.html"),
        out_dir=tmp_path,
        action_executor=action_executor,
    )
    candidate = {
        "candidate_id": "fixture-first-name",
        "bbox": {"x": 90, "y": 180, "w": 420, "h": 44},
        "click_point": {"x": 300, "y": 202},
    }

    try:
        runtime.prepare_action_gate(candidate)
    except RuntimeError as exc:
        assert "semantic action" in str(exc).casefold()
    else:
        raise AssertionError("semantic action mismatch must be rejected")


def test_fixture_smoke_script_can_run_directly_from_repo_root() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/run_general_form_fixture_smoke.py", "--help"],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--out" in completed.stdout


def test_edge_fixture_launch_forces_renderer_accessibility(tmp_path: Path) -> None:
    command = _build_edge_launch_command(
        edge_path=Path("msedge.exe"),
        fixture_url="http://127.0.0.1:8765/index.html",
        profile_dir=tmp_path / "edge-profile",
    )

    assert "--force-renderer-accessibility" in command


class FakeDropdownRuntime:
    def __init__(self) -> None:
        self.capture_ids = iter(["capture-closed", "capture-open", "capture-selected"])
        self.gate_actions: list[str] = []
        self.dispatched_actions: list[str] = []
        self.closed = False

    def start(self) -> None:
        return None

    def capture_current(self) -> dict:
        return {
            "capture_id": next(self.capture_ids),
            "image_path": "fixture.png",
            "viewport_size": {"width": 640, "height": 620},
        }

    def locate_country_dropdown(self, capture: dict) -> dict:
        assert capture["capture_id"] == "capture-closed"
        return _fixture_click_candidate(
            candidate_id="fixture-country-dropdown",
            question_id="fixture-country",
            capture_id="capture-closed",
            y=300,
        )

    def locate_country_option(self, capture: dict, *, option_label: str) -> dict:
        assert capture["capture_id"] == "capture-open"
        assert option_label == "New Zealand"
        candidate = _fixture_click_candidate(
            candidate_id="fixture-country-option-new-zealand",
            question_id="fixture-country",
            capture_id="capture-open",
            y=350,
        )
        candidate.update({"option_label": option_label, "enabled": True, "matching_label_count": 1})
        return candidate

    def prepare_click_action_gate(self, candidate: dict, *, semantic_action: str) -> dict:
        self.gate_actions.append(semantic_action)
        return {
            "approved_plan_id": f"approved-{semantic_action}",
            "action_gate": {
                "contract_version": "pre_click_decision_v1",
                "allowed": True,
                "semantic_action": semantic_action,
                "selected_candidate_id": candidate["candidate_id"],
                "selected_click_point": candidate["click_point"],
            },
            "trace_path": f"dry-run-{semantic_action}.json",
        }

    def dispatch_approved_click(self, approved_plan_id: str, *, semantic_action: str, x: int, y: int) -> dict:
        assert approved_plan_id == f"approved-{semantic_action}"
        assert x == 300
        assert y in {322, 372}
        self.dispatched_actions.append(semantic_action)
        return {"success": True, "trace_path": f"click-{semantic_action}.json"}

    def observe_country_projection(self) -> dict:
        return {"selected_value": "New Zealand", "submit_clicks": 0}

    def close(self) -> None:
        self.closed = True


def _fixture_click_candidate(*, candidate_id: str, question_id: str, capture_id: str, y: int) -> dict:
    return {
        "candidate_id": candidate_id,
        "question_id": question_id,
        "bbox": {"x": 90, "y": y, "w": 420, "h": 44},
        "click_point": {"x": 300, "y": y + 22},
        "candidate_freshness": {
            "capture_id": capture_id,
            "viewport_size": {"width": 640, "height": 620},
            "source": "windows_uia",
            "freshness": "current_capture",
        },
    }


def test_dropdown_fixture_smoke_reobserves_between_both_clicks_and_effect_check(tmp_path: Path) -> None:
    runtime = FakeDropdownRuntime()

    report = run_general_form_dropdown_fixture_smoke(
        runtime=runtime,
        approved_option="New Zealand",
        out_dir=tmp_path,
    )

    assert report["status"] == "pass"
    assert report["dropdown_open_attempted"] == 1
    assert report["option_select_attempted"] == 1
    assert report["selection_effect_success"] is True
    assert report["submit_clicks"] == 0
    assert report["no_submit"] is True
    assert report["report_value_redacted"] is True
    assert report["visible_grounding_evidence_may_include_option_labels"] is True
    assert runtime.gate_actions == ["open_dropdown", "select_option"]
    assert runtime.dispatched_actions == ["open_dropdown", "select_option"]
    assert runtime.closed is True
    report_text = (tmp_path / "general_form_dropdown_fixture_smoke_report.json").read_text(encoding="utf-8")
    assert "New Zealand" not in report_text


def test_dropdown_fixture_contains_enabled_choice_disabled_decoy_and_selection_projection() -> None:
    html = Path("tests/fixtures/general_form_live_site/index.html").read_text(encoding="utf-8")

    assert 'id="country"' in html
    assert 'role="combobox"' in html
    assert 'aria-controls="countryOptions"' in html
    assert 'id="countryOptions" role="listbox"' in html
    assert 'role="option" data-value="NZ">New Zealand</button>' in html
    assert 'role="option" data-value="BLOCKED" disabled>Disabled decoy</button>' in html
    assert "country-state length=0" in html


def test_windows_runtime_prepares_semantic_click_gate_for_dropdown_action(tmp_path: Path) -> None:
    calls: list[dict] = []
    candidate = _fixture_click_candidate(
        candidate_id="fixture-country-dropdown",
        question_id="fixture-country",
        capture_id="capture-closed",
        y=300,
    )

    def action_executor(payload: dict) -> dict:
        calls.append(payload)
        semantic_action = payload["metadata"]["semantic_action"]
        return {
            "success": True,
            "data": {
                "result": {
                    "approved_plan_id": "approved-open",
                    "trace_path": "dry-run-open.json",
                    "operation_context": {"semantic_action": semantic_action},
                    "pre_click_decision": {
                        "contract_version": "pre_click_decision_v1",
                        "allowed": True,
                        "selected_candidate_id": candidate["candidate_id"],
                        "selected_click_point": candidate["click_point"],
                    },
                }
            },
        }

    runtime = WindowsGeneralFormFixtureRuntime(
        fixture_path=Path("tests/fixtures/general_form_live_site/index.html"),
        out_dir=tmp_path,
        action_executor=action_executor,
    )

    prepared = runtime.prepare_click_action_gate(candidate, semantic_action="open_dropdown")

    assert calls[0]["task"] == "open_dropdown"
    assert calls[0]["metadata"]["semantic_action"] == "open_dropdown"
    assert prepared["approved_plan_id"] == "approved-open"
    assert prepared["action_gate"]["semantic_action"] == "open_dropdown"


def test_windows_runtime_dispatches_only_the_approved_dropdown_click(tmp_path: Path) -> None:
    calls: list[dict] = []

    def action_executor(payload: dict) -> dict:
        calls.append(payload)
        return {"success": True, "data": {"result": {"trace_path": "click-open.json"}}}

    runtime = WindowsGeneralFormFixtureRuntime(
        fixture_path=Path("tests/fixtures/general_form_live_site/index.html"),
        out_dir=tmp_path,
        action_executor=action_executor,
    )

    result = runtime.dispatch_approved_click(
        "approved-open",
        semantic_action="open_dropdown",
        x=300,
        y=322,
    )

    assert result == {"success": True, "trace_path": "click-open.json"}
    assert len(calls) == 1
    assert calls[0]["approved_plan_id"] == "approved-open"
    assert calls[0]["dry_run"] is False
    assert calls[0]["metadata"]["semantic_action"] == "open_dropdown"


class FakeChoiceRuntime:
    def __init__(self) -> None:
        self.capture_ids = iter(["capture-initial", "capture-radio-selected", "capture-checkbox-selected"])
        self.radio_checked = False
        self.checkbox_checked = False
        self.gate_actions: list[str] = []
        self.dispatched_actions: list[str] = []
        self.closed = False

    def start(self) -> None:
        return None

    def capture_current(self) -> dict:
        return {
            "capture_id": next(self.capture_ids),
            "image_path": "fixture.png",
            "viewport_size": {"width": 640, "height": 620},
        }

    def locate_contact_radio(self, capture: dict, *, option_label: str) -> dict:
        assert option_label == "Email"
        candidate = _fixture_click_candidate(
            candidate_id="fixture-contact-email",
            question_id="fixture-contact-method",
            capture_id=capture["capture_id"],
            y=420,
        )
        candidate.update(
            {
                "option_value": option_label,
                "enabled": True,
                "matching_label_count": 1,
                "checked": self.radio_checked,
            }
        )
        return candidate

    def locate_updates_checkbox(self, capture: dict) -> dict:
        candidate = _fixture_click_candidate(
            candidate_id="fixture-status-updates",
            question_id="fixture-status-updates",
            capture_id=capture["capture_id"],
            y=470,
        )
        candidate.update(
            {
                "option_value": "Receive status updates",
                "enabled": True,
                "matching_label_count": 1,
                "checked": self.checkbox_checked,
            }
        )
        return candidate

    def prepare_click_action_gate(self, candidate: dict, *, semantic_action: str) -> dict:
        self.gate_actions.append(semantic_action)
        return {
            "approved_plan_id": f"approved-{semantic_action}",
            "action_gate": {
                "contract_version": "pre_click_decision_v1",
                "allowed": True,
                "semantic_action": semantic_action,
                "selected_candidate_id": candidate["candidate_id"],
                "selected_click_point": candidate["click_point"],
            },
            "trace_path": f"dry-run-{semantic_action}.json",
        }

    def dispatch_approved_click(self, approved_plan_id: str, *, semantic_action: str, x: int, y: int) -> dict:
        assert approved_plan_id == f"approved-{semantic_action}"
        assert x == 300
        assert y in {442, 492}
        self.dispatched_actions.append(semantic_action)
        if semantic_action == "select_radio":
            self.radio_checked = True
        elif semantic_action == "toggle_checkbox":
            self.checkbox_checked = True
        return {"success": True, "trace_path": f"click-{semantic_action}.json"}

    def observe_choice_projection(self, *, question_id: str) -> dict:
        checked = self.radio_checked if question_id == "fixture-contact-method" else self.checkbox_checked
        return {"question_id": question_id, "checked": checked, "submit_clicks": 0}

    def close(self) -> None:
        self.closed = True


def test_choice_fixture_smoke_reobserves_effect_and_skips_already_selected_click(tmp_path: Path) -> None:
    runtime = FakeChoiceRuntime()

    report = run_general_form_choice_fixture_smoke(runtime=runtime, out_dir=tmp_path)

    assert report["status"] == "pass"
    assert report["radio_select_attempted"] == 1
    assert report["radio_effect_success"] is True
    assert report["checkbox_toggle_attempted"] == 1
    assert report["checkbox_effect_success"] is True
    assert report["already_selected_no_dispatch"] is True
    assert report["submit_clicks"] == 0
    assert report["no_submit"] is True
    assert report["fixture_only"] is True
    assert report["live_form_filling"] is False
    assert runtime.gate_actions == ["select_radio", "toggle_checkbox"]
    assert runtime.dispatched_actions == ["select_radio", "toggle_checkbox"]
    assert runtime.closed is True
    report_text = (tmp_path / "general_form_choice_fixture_smoke_report.json").read_text(encoding="utf-8")
    assert "Email" not in report_text
    assert "Receive status updates" not in report_text


def test_choice_fixture_contains_enabled_choices_disabled_decoy_and_state_projection() -> None:
    html = Path("tests/fixtures/general_form_live_site/index.html").read_text(encoding="utf-8")

    assert 'id="contactEmail" type="radio"' in html
    assert 'id="contactDisabled" type="radio" disabled' in html
    assert 'id="statusUpdates" type="checkbox"' in html
    assert "contact-state checked=false" in html
    assert "updates-state checked=false" in html


def test_windows_runtime_prepares_and_dispatches_choice_semantic_actions(tmp_path: Path) -> None:
    calls: list[dict] = []
    candidate = _fixture_click_candidate(
        candidate_id="fixture-contact-email",
        question_id="fixture-contact-method",
        capture_id="capture-initial",
        y=420,
    )

    def action_executor(payload: dict) -> dict:
        calls.append(payload)
        semantic_action = payload["metadata"]["semantic_action"]
        if payload["dry_run"] is False:
            return {"success": True, "data": {"result": {"trace_path": f"click-{semantic_action}.json"}}}
        return {
            "success": True,
            "data": {
                "result": {
                    "approved_plan_id": f"approved-{semantic_action}",
                    "trace_path": f"dry-run-{semantic_action}.json",
                    "operation_context": {"semantic_action": semantic_action},
                    "pre_click_decision": {
                        "contract_version": "pre_click_decision_v1",
                        "allowed": True,
                        "selected_candidate_id": candidate["candidate_id"],
                        "selected_click_point": candidate["click_point"],
                    },
                }
            },
        }

    runtime = WindowsGeneralFormFixtureRuntime(
        fixture_path=Path("tests/fixtures/general_form_live_site/index.html"),
        out_dir=tmp_path,
        action_executor=action_executor,
    )

    prepared = runtime.prepare_click_action_gate(candidate, semantic_action="select_radio")
    result = runtime.dispatch_approved_click(
        prepared["approved_plan_id"],
        semantic_action="select_radio",
        x=300,
        y=442,
    )

    assert result == {"success": True, "trace_path": "click-select_radio.json"}
    assert [call["metadata"]["semantic_action"] for call in calls] == ["select_radio", "select_radio"]
    assert calls[0]["dry_run"] is True
    assert calls[1]["dry_run"] is False


def test_integrated_workflow_fixture_exposes_reviewed_fields_and_final_review() -> None:
    html = Path("tests/fixtures/general_form_workflow_site/index.html").read_text(encoding="utf-8")

    for control_id in (
        "firstName",
        "country",
        "contactEmail",
        "statusUpdates",
        "resumeUpload",
        "continueToReview",
        "finalSubmit",
    ):
        assert f'id="{control_id}"' in html
    assert "upload-state filename-sha256=none size=0" in html
    assert "real-clicks=0 submit-clicks=0" in html
    assert 'data-form-step="review"' in html


def test_windows_runtime_supports_continue_and_final_review_projection(tmp_path: Path) -> None:
    runtime = WindowsGeneralFormFixtureRuntime(
        fixture_path=Path("tests/fixtures/general_form_workflow_site/index.html"),
        out_dir=tmp_path,
    )
    capture = {
        "capture_id": "capture-final-review",
        "viewport_size": {"width": 720, "height": 900},
    }
    runtime._current_capture = dict(capture)
    runtime._uia_controls = lambda: [
        {
            "automation_id": "continueToReview",
            "control_type": "Button",
            "name": "Continue",
            "visible": True,
            "enabled": True,
            "bbox": {"x": 180, "y": 700, "w": 140, "h": 44},
        },
        {
            "automation_id": "finalSubmit",
            "control_type": "Button",
            "name": "Submit application",
            "visible": True,
            "enabled": True,
            "bbox": {"x": 180, "y": 420, "w": 180, "h": 44},
        },
        {
            "automation_id": "submitState",
            "control_type": "Text",
            "name": "real-clicks=0 submit-clicks=0",
            "visible": True,
            "enabled": True,
            "bbox": {"x": 180, "y": 490, "w": 240, "h": 24},
        },
    ]

    candidate = runtime.locate_continue_button(capture)
    projection = runtime.observe_final_review_projection()

    assert candidate["candidate_id"] == "fixture-continue"
    assert candidate["question_id"] == "fixture-continue"
    assert projection["surface_context"] == "final_review_submit"
    assert projection["actions"] == [
        {
            "id": "finalSubmit",
            "text": "Submit application",
            "role": "button",
            "bbox": {"x": 180, "y": 420, "w": 180, "h": 44},
        }
    ]
    assert projection["real_clicks"] == 0
    assert projection["submit_clicks"] == 0


class FakeWorkflowRuntime:
    def __init__(self) -> None:
        self.closed = False
        self.capture_index = 0
        self.current_capture_id = ""
        self.completed: set[str] = set()
        self.approved_value = ""
        self.approved_option = ""
        self.approved_file: Path | None = None
        self.gate_actions: list[str] = []
        self.dispatched_actions: list[str] = []
        self.on_final_review = False

    def start(self) -> None:
        return None

    def capture_current(self) -> dict:
        self.capture_index += 1
        self.current_capture_id = f"capture-workflow-{self.capture_index}"
        return {
            "capture_id": self.current_capture_id,
            "image_path": f"workflow-{self.capture_index}.png",
            "viewport_size": {"width": 720, "height": 900},
        }

    def _candidate(self, candidate_id: str, question_id: str, label: str, y: int) -> dict:
        return {
            "candidate_id": candidate_id,
            "question_id": question_id,
            "label": label,
            "bbox": {"x": 100, "y": y, "w": 360, "h": 44},
            "click_point": {"x": 280, "y": y + 22},
            "candidate_freshness": {
                "capture_id": self.current_capture_id,
                "viewport_size": {"width": 720, "height": 900},
                "source": "windows_uia",
                "freshness": "current_capture",
            },
        }

    def locate_first_name_field(self, capture: dict) -> dict:
        assert capture["capture_id"] == self.current_capture_id
        return self._candidate("fixture-first-name", "fixture-first-name", "First name", 150)

    def locate_country_dropdown(self, capture: dict) -> dict:
        assert capture["capture_id"] == self.current_capture_id
        return self._candidate("fixture-country-dropdown", "fixture-country", "Country", 220)

    def locate_country_option(self, capture: dict, *, option_label: str) -> dict:
        assert capture["capture_id"] == self.current_capture_id
        self.approved_option = option_label
        candidate = self._candidate(
            "fixture-country-option",
            "fixture-country",
            "Reviewed Country option",
            270,
        )
        candidate.update(
            {
                "enabled": True,
                "matching_label_count": 1,
                "option_label": option_label,
            }
        )
        return candidate

    def locate_contact_radio(self, capture: dict, *, option_label: str) -> dict:
        assert capture["capture_id"] == self.current_capture_id
        candidate = self._candidate(
            "fixture-contact-email",
            "fixture-contact-method",
            "Reviewed contact method",
            340,
        )
        candidate["checked"] = "fixture-contact-method" in self.completed
        candidate["option_value"] = option_label
        candidate["enabled"] = True
        candidate["matching_label_count"] = 1
        return candidate

    def locate_updates_checkbox(self, capture: dict) -> dict:
        assert capture["capture_id"] == self.current_capture_id
        candidate = self._candidate(
            "fixture-status-updates",
            "fixture-status-updates",
            "Reviewed status updates choice",
            410,
        )
        candidate["checked"] = "fixture-status-updates" in self.completed
        candidate["enabled"] = True
        candidate["matching_label_count"] = 1
        candidate["option_value"] = "Receive status updates"
        return candidate

    def locate_resume_upload(self, capture: dict) -> dict:
        assert capture["capture_id"] == self.current_capture_id
        return self._candidate("fixture-resume-upload", "fixture-resume-upload", "Upload resume", 480)

    def locate_continue_button(self, capture: dict) -> dict:
        assert capture["capture_id"] == self.current_capture_id
        return self._candidate("fixture-continue", "fixture-continue", "Continue", 550)

    def prepare_action_gate(self, candidate: dict) -> dict:
        return self.prepare_click_action_gate(candidate, semantic_action="fill_field")

    def prepare_click_action_gate(self, candidate: dict, *, semantic_action: str) -> dict:
        self.gate_actions.append(semantic_action)
        return {
            "approved_plan_id": f"approved-{semantic_action}-{len(self.gate_actions)}",
            "action_gate": {
                "contract_version": "pre_click_decision_v1",
                "allowed": True,
                "semantic_action": semantic_action,
                "selected_candidate_id": candidate["candidate_id"],
                "selected_click_point": candidate["click_point"],
            },
            "trace_path": f"gate-{semantic_action}-{len(self.gate_actions)}.json",
        }

    def dispatch_approved_fill(self, approved_plan_id: str, **kwargs) -> dict:
        assert approved_plan_id.startswith("approved-fill_field-")
        assert kwargs["submit"] is False
        self.approved_value = str(kwargs["text"])
        self.completed.add("fixture-first-name")
        self.dispatched_actions.append("fill_field")
        return {"success": True, "trace_path": "fill-field.json"}

    def dispatch_approved_click(
        self,
        approved_plan_id: str,
        *,
        semantic_action: str,
        x: int,
        y: int,
    ) -> dict:
        assert approved_plan_id.startswith(f"approved-{semantic_action}-")
        assert x >= 0 and y >= 0
        self.dispatched_actions.append(semantic_action)
        if semantic_action == "select_option":
            self.completed.add("fixture-country")
        elif semantic_action == "select_radio":
            self.completed.add("fixture-contact-method")
        elif semantic_action == "toggle_checkbox":
            self.completed.add("fixture-status-updates")
        elif semantic_action == "continue_next_step":
            self.on_final_review = True
        return {"success": True, "trace_path": f"click-{semantic_action}.json"}

    def dispatch_approved_file_upload(self, approved_plan_id: str, **kwargs) -> dict:
        assert approved_plan_id.startswith("approved-upload_file-")
        assert kwargs["submit"] is False
        self.approved_file = Path(kwargs["file_path"])
        self.completed.add("fixture-resume-upload")
        self.dispatched_actions.append("upload_file")
        return {"success": True, "trace_path": "upload-file.json"}

    def observe_field_projection(self) -> dict:
        return {
            "value_matches_approved": bool(self.approved_value),
            "submit_clicks": 0,
            "capture_id": self.current_capture_id,
        }

    def observe_country_projection(self) -> dict:
        return {"selected_value": self.approved_option, "submit_clicks": 0}

    def observe_choice_projection(self, *, question_id: str) -> dict:
        return {"question_id": question_id, "checked": question_id in self.completed, "submit_clicks": 0}

    def observe_file_upload_projection(self) -> dict:
        assert self.approved_file is not None
        return {
            "question_id": "fixture-resume-upload",
            "filename_hash": __import__("hashlib").sha256(self.approved_file.name.encode("utf-8")).hexdigest(),
            "size_bytes": self.approved_file.stat().st_size,
            "submit_clicks": 0,
        }

    def observe_final_review_projection(self) -> dict:
        assert self.on_final_review is True
        return {
            "surface_context": "final_review_submit",
            "active_container": {"x": 70, "y": 70, "w": 580, "h": 760},
            "actions": [
                {
                    "id": "finalSubmit",
                    "text": "Submit application",
                    "role": "button",
                    "bbox": {"x": 180, "y": 420, "w": 180, "h": 44},
                }
            ],
            "real_clicks": 0,
            "submit_clicks": 0,
        }

    def close(self) -> None:
        self.closed = True


def test_integrated_form_workflow_uses_agent_turns_and_stops_before_final_submit(tmp_path: Path) -> None:
    approved_file = tmp_path / "private_resume_name.pdf"
    approved_file.write_bytes(b"%PDF-1.4\ncontrolled workflow fixture\n%%EOF\n")
    runtime = FakeWorkflowRuntime()

    report = run_general_form_workflow_fixture_smoke(
        runtime=runtime,
        approved_first_name="Private Person",
        approved_country="New Zealand",
        approved_file_path=approved_file,
        out_dir=tmp_path / "out",
    )

    assert report["status"] == "pass"
    assert report["fixture_only"] is True
    assert report["live_ats_form_filling"] is False
    assert report["agent_action_sequence"] == [
        "fill_field",
        "select_option",
        "select_option",
        "select_option",
        "upload_file",
        "continue_next_step",
        "safe_stop",
    ]
    assert report["safe_fill_fixture"] == {"passed": 5, "attempted": 5, "rate": 1.0}
    assert report["file_upload_effect_success"] is True
    assert report["final_submit_guard"]["blocked"] is True
    assert report["final_submit_guard"]["reason"] == "final_submit_visible_stop_before_submission"
    assert report["safe_stop"] is True
    assert report["submit_clicks"] == 0
    assert report["real_clicks"] == 0
    assert report["no_submit"] is True
    assert all(step["duration_ms"] >= 0 for step in report["steps"])
    assert report["max_action_duration_ms"] == max(step["duration_ms"] for step in report["steps"])
    assert runtime.closed is True
    serialized = json.dumps(report, ensure_ascii=False)
    assert "Private Person" not in serialized
    assert "New Zealand" not in serialized
    assert approved_file.name not in serialized
    assert str(approved_file.resolve()) not in serialized


def test_cli_workflow_mode_uses_integrated_fixture_and_workflow_runner(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    captured: dict = {}
    runtime_token = object()

    def runtime_factory(*, fixture_path: Path, out_dir: Path):
        captured["fixture_path"] = fixture_path
        captured["out_dir"] = out_dir
        return runtime_token

    def workflow_runner(*, runtime, approved_first_name, approved_country, approved_file_path, out_dir):
        captured.update(
            {
                "runtime": runtime,
                "approved_first_name": approved_first_name,
                "approved_country": approved_country,
                "approved_file_path": approved_file_path,
                "workflow_out_dir": out_dir,
            }
        )
        return {"status": "pass", "contract_version": "general_form_workflow_fixture_smoke_report_v1"}

    monkeypatch.setattr(fixture_smoke, "WindowsGeneralFormFixtureRuntime", runtime_factory)
    monkeypatch.setattr(fixture_smoke, "run_general_form_workflow_fixture_smoke", workflow_runner)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_general_form_fixture_smoke.py",
            "--mode",
            "workflow",
            "--out",
            str(tmp_path),
            "--json",
        ],
    )

    exit_code = fixture_smoke.main()

    assert exit_code == 0
    assert captured["fixture_path"] == Path("tests/fixtures/general_form_workflow_site/index.html")
    assert captured["runtime"] is runtime_token
    assert captured["approved_first_name"] == "Synthetic Fixture Name"
    assert captured["approved_country"] == "New Zealand"
    assert captured["approved_file_path"].is_file()
    assert captured["workflow_out_dir"] == tmp_path
    assert json.loads(capsys.readouterr().out)["status"] == "pass"
