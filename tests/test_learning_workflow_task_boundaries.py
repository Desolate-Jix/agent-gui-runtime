from __future__ import annotations

import importlib
import inspect
import json
import os
import subprocess
import sys
import textwrap

from PIL import Image

from app.learn.workflow_contracts import LearningTaskResult


def test_learn_task_application_modules_have_no_api_dependency() -> None:
    module_names = (
        "app.learn.workflow_contracts",
        "app.learn.workflow_task_result_adapter",
        "app.learn.workflow_tasks.model_review",
        "app.learn.workflow_tasks.observe",
        "app.learn.workflow_tasks.recognition",
        "app.learn.workflow_tasks.two_stage",
    )

    modules = [importlib.import_module(name) for name in module_names]

    assert all("app.api" not in inspect.getsource(module) for module in modules)
    assert callable(modules[2].run_model_review_task)
    assert callable(modules[3].run_observe_task)
    assert callable(modules[4].run_recognition_task)
    assert callable(modules[5].run_two_stage_understanding_task)


def test_worker_observe_branch_does_not_import_api() -> None:
    from app.learn import workflow_worker

    source = inspect.getsource(workflow_worker.execute_learning_stage_worker_task)
    observe_branch = source.split(
        'elif normalized_kind == "vision_observe_screen":',
        maxsplit=1,
    )[1].split(
        "else:",
        maxsplit=1,
    )[0]

    assert "app.api" not in observe_branch
    assert "run_observe_task" in observe_branch


def test_observe_worker_subprocess_does_not_load_api() -> None:
    script = textwrap.dedent(
        """
        import json
        import sys

        from app.learn import workflow_worker as worker

        worker._ensure_learning_stage_model_ready = (
            lambda *args, **kwargs: None
        )
        response = worker.execute_learning_stage_worker_task(
            "vision_observe_screen",
            {"capture_live": False},
        )
        print(
            json.dumps(
                {
                    "success": response["success"],
                    "error_code": response["error"]["code"],
                    "api_modules": sorted(
                        name
                        for name in sys.modules
                        if name == "app.api" or name.startswith("app.api.")
                    ),
                }
            )
        )
        """
    )
    environment = dict(os.environ)
    environment["AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH"] = ":memory:"
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=os.getcwd(),
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["success"] is False
    assert report["error_code"] == "observe_screen_failed"
    assert report["api_modules"] == []


def test_run_model_review_task_returns_safe_stopped_result(tmp_path) -> None:
    from app.learn.workflow_contracts import ModelReviewTaskInput
    from app.learn.workflow_tasks.model_review import run_model_review_task

    result = run_model_review_task(
        ModelReviewTaskInput(
            two_stage_report_path="input.json",
            screenshot_path="screen.png",
            composite_overlay_path="overlay.png",
        ),
        project_root=tmp_path,
        review_runner=lambda **_kwargs: {
            "status": "safe_stop",
            "calibration_permission": False,
            "integrity_gate": {"status": "failed"},
        },
        trace_writer=lambda **_kwargs: "logs/traces/review.json",
    )

    assert result.outcome == "safe_stopped"
    assert result.failure is None
    assert result.payload["status"] == "safe_stop"
    assert result.payload["real_clicks"] == 0
    assert result.payload["live_fills"] == 0
    assert result.payload["live_submits"] == 0
    assert result.payload["trace_path"] == "logs/traces/review.json"


def test_run_recognition_task_returns_display_only_result(tmp_path) -> None:
    from app.learn.workflow_contracts import RecognitionTaskInput
    from app.learn.workflow_tasks.recognition import run_recognition_task

    result = run_recognition_task(
        RecognitionTaskInput(
            app_name="sample_app",
            state_hint="home",
            observation_evidence={
                "screen_size": {"width": 800, "height": 600},
            },
        ),
        project_root=tmp_path,
        trial_builder=lambda **_kwargs: {
            "status": "ready",
            "screen_inventory": [],
            "classification": {"summary": {}},
            "learning_draft": {
                "workflow_draft": {
                    "states": [],
                    "action_templates": [],
                    "verification_rules": [],
                },
                "interface_draft": {"regions": []},
                "blockers": [],
                "safety": {},
            },
        },
        grounding_adapter=lambda **_kwargs: {},
        trial_saver=lambda _payload, *, app_name, project_root: (
            f"artifacts/{app_name}/trial.json"
        ),
        trace_writer=lambda **_kwargs: "logs/traces/recognition.json",
    )

    assert result.outcome == "completed"
    assert result.failure is None
    assert result.payload["trial_path"] == "artifacts/sample_app/trial.json"
    assert result.payload["trace_path"] == "logs/traces/recognition.json"
    assert result.payload["artifact_is_authorization"] is False
    assert result.payload["execute_binding_enabled"] is False
    assert result.payload["real_clicks"] == 0
    assert result.payload["live_safe_fill_attempted"] == 0
    assert result.payload["final_submit_forbidden"] is True


def test_recognition_task_preserves_model_interface_classification(tmp_path) -> None:
    from app.learn.workflow_contracts import RecognitionTaskInput
    from app.learn.workflow_tasks.recognition import run_recognition_task

    captured_bundle = {}
    interface_classification = {
        "category": "feed_workspace",
        "confidence": 0.97,
        "reason": "visible article feed",
        "structure_signals": {
            "feed_items": True,
            "news_items": True,
        },
    }

    def build_trial(**kwargs):
        captured_bundle.update(kwargs["observe_bundle"])
        return {
            "status": "ready",
            "screen_inventory": [],
            "classification": {"summary": {}},
            "learning_draft": {
                "workflow_draft": {
                    "states": [],
                    "action_templates": [],
                    "verification_rules": [],
                },
                "interface_draft": {"regions": []},
                "blockers": [],
                "safety": {},
            },
        }

    result = run_recognition_task(
        RecognitionTaskInput(
            app_name="browser_news",
            state_hint="feed",
            observation_evidence={
                "screen_size": {"width": 1280, "height": 720},
                "interface_classification": interface_classification,
            },
        ),
        project_root=tmp_path,
        trial_builder=build_trial,
        grounding_adapter=lambda **_kwargs: {},
        trial_saver=lambda _payload, *, app_name, project_root: (
            f"artifacts/{app_name}/trial.json"
        ),
        trace_writer=lambda **_kwargs: "logs/traces/recognition.json",
    )

    assert result.outcome == "completed"
    assert captured_bundle["sources"]["vision"]["interface_classification"] == (
        interface_classification
    )
    assert captured_bundle["panel_observation_evidence"][
        "interface_classification"
    ] == interface_classification


def test_recognition_result_adapter_preserves_legacy_response_shape() -> None:
    from app.learn.workflow_task_result_adapter import (
        recognition_result_to_legacy_response,
    )

    response = recognition_result_to_legacy_response(
        LearningTaskResult(
            outcome="completed",
            payload={"contract_version": "panel_learning_recognition_trial_run_v1"},
        )
    )

    assert response == {
        "success": True,
        "message": "Learning recognition draft saved",
        "data": {
            "contract_version": "panel_learning_recognition_trial_run_v1",
        },
        "error": None,
    }


def test_worker_recognition_branch_does_not_import_panel_api() -> None:
    from app.learn import workflow_worker

    source = inspect.getsource(workflow_worker.execute_learning_stage_worker_task)
    recognition_branch = source.split(
        'if normalized_kind == "panel_learning_recognition_trial":',
        maxsplit=1,
    )[1].split(
        'elif normalized_kind == "panel_learning_two_stage_understanding":',
        maxsplit=1,
    )[0]

    assert "app.api.panel" not in recognition_branch
    assert "run_recognition_task" in recognition_branch


def test_run_two_stage_understanding_task_returns_read_only_result(
    tmp_path,
) -> None:
    from app.learn.workflow_contracts import TwoStageUnderstandingTaskInput
    from app.learn.workflow_tasks.two_stage import (
        run_two_stage_understanding_task,
    )

    override_image = tmp_path / "artifacts" / "screenshots" / "override.png"
    override_image.parent.mkdir(parents=True)
    Image.new("RGB", (111, 77), "white").save(override_image)
    captured_bundle = {}

    def build_two_stage(**kwargs):
        captured_bundle.update(kwargs["bundle"])
        return {
            "stage1_gate": {"status": "passed"},
            "stage1_source": "fixture",
            "stage2_numbering": {
                "regions": [],
                "numbered_item_count": 0,
                "calibration_candidate_count": 0,
            },
            "fusion": {"fused_review_boxes": []},
        }

    result = run_two_stage_understanding_task(
        TwoStageUnderstandingTaskInput(
            app_name="sample_app",
            state_hint="home",
            source_image_path="artifacts/screenshots/override.png",
            observe_result={
                "image_path": "artifacts/screenshots/sample.png",
                "screen_size": {"width": 800, "height": 600},
            },
        ),
        project_root=tmp_path,
        observe_bundle_builder=lambda _result, *, trace_path: {
            "image_path": "artifacts/screenshots/sample.png",
            "screen_size": {"width": 800, "height": 600},
        },
        inventory_builder=lambda _result: [],
        layout_builder=lambda _inventory, *, screen_size: {
            "node_count": 0,
            "zone_count": 0,
            "zones": {},
        },
        two_stage_builder=build_two_stage,
        fusion_status_builder=lambda _report: {"status": "ready"},
        grounding_evidence_builder=lambda _report: {
            "status": "not_covered"
        },
        surface_rules_loader=lambda **_kwargs: [],
        report_saver=lambda _payload, *, app_name, project_root: (
            f"artifacts/{app_name}/two-stage.json"
        ),
        trace_writer=lambda **_kwargs: "logs/traces/two-stage.json",
    )

    assert result.outcome == "completed"
    assert result.failure is None
    assert result.payload["report_path"] == (
        "artifacts/sample_app/two-stage.json"
    )
    assert result.payload["stage1_gate"]["status"] == "passed"
    assert result.payload["source_image_override"]["status"] == "applied"
    assert result.payload["image_path"] == str(override_image)
    assert captured_bundle["screen_size"] == {"width": 111, "height": 77}
    assert result.payload["artifact_is_authorization"] is False
    assert result.payload["execute_binding_enabled"] is False
    assert result.payload["real_clicks"] == 0
    assert result.payload["final_submit_forbidden"] is True


def test_worker_two_stage_branch_does_not_import_panel_api() -> None:
    from app.learn import workflow_worker

    source = inspect.getsource(workflow_worker.execute_learning_stage_worker_task)
    two_stage_branch = source.split(
        'elif normalized_kind == "panel_learning_two_stage_understanding":',
        maxsplit=1,
    )[1].split(
        'elif normalized_kind == "panel_learning_model_review_repair":',
        maxsplit=1,
    )[0]

    assert "app.api.panel" not in two_stage_branch
    assert "run_two_stage_understanding_task" in two_stage_branch


def test_two_stage_result_adapter_preserves_legacy_response_shape() -> None:
    from app.learn.workflow_task_result_adapter import (
        two_stage_result_to_legacy_response,
    )

    response = two_stage_result_to_legacy_response(
        LearningTaskResult(
            outcome="completed",
            payload={
                "contract_version": (
                    "panel_learning_two_stage_understanding_run_v1"
                )
            },
        )
    )

    assert response == {
        "success": True,
        "message": "Two-stage learning understanding generated",
        "data": {
            "contract_version": (
                "panel_learning_two_stage_understanding_run_v1"
            )
        },
        "error": None,
    }


def test_learn_task_worker_subprocess_does_not_load_panel_api() -> None:
    script = textwrap.dedent(
        """
        import json
        import sys

        from app.learn import workflow_worker as worker
        from app.learn.workflow_contracts import LearningTaskResult

        worker._ensure_learning_stage_model_ready = (
            lambda *args, **kwargs: None
        )
        worker.run_recognition_task = (
            lambda *args, **kwargs: LearningTaskResult(
                outcome="completed",
                payload={"kind": "recognition"},
            )
        )
        worker.run_two_stage_understanding_task = (
            lambda *args, **kwargs: LearningTaskResult(
                outcome="completed",
                payload={"kind": "two_stage"},
            )
        )
        worker.run_model_review_task = (
            lambda *args, **kwargs: LearningTaskResult(
                outcome="completed",
                payload={"kind": "model_review"},
            )
        )

        cases = [
            ("panel_learning_recognition_trial", {}),
            ("panel_learning_two_stage_understanding", {}),
            (
                "panel_learning_model_review_repair",
                {
                    "two_stage_report_path": "input.json",
                    "screenshot_path": "screen.png",
                    "composite_overlay_path": "overlay.png",
                },
            ),
        ]
        results = []
        for task_kind, payload in cases:
            response = worker.execute_learning_stage_worker_task(
                task_kind,
                payload,
            )
            results.append(
                {
                    "task_kind": task_kind,
                    "success": response["success"],
                    "panel_loaded": "app.api.panel" in sys.modules,
                }
            )

        print(
            json.dumps(
                {
                    "results": results,
                    "panel_loaded": "app.api.panel" in sys.modules,
                    "api_modules": sorted(
                        name
                        for name in sys.modules
                        if name == "app.api" or name.startswith("app.api.")
                    ),
                }
            )
        )
        """
    )
    environment = dict(os.environ)
    environment["AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH"] = ":memory:"
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=os.getcwd(),
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["panel_loaded"] is False
    assert report["api_modules"] == []
    assert all(item["success"] is True for item in report["results"])
    assert all(item["panel_loaded"] is False for item in report["results"])


def test_recognition_task_drops_raw_provider_payload_at_learning_boundary(tmp_path) -> None:
    from app.learn.workflow_contracts import RecognitionTaskInput
    from app.learn.workflow_tasks.recognition import run_recognition_task

    captured_bundle = {}
    parser_result = {
        "contract_version": "screen_parser_result_v1",
        "provider": "omniparser",
        "status": "success",
        "profile_id": "omniparser_v2",
        "model_revision": "v.2.0.1",
        "capture_id": "capture-17",
        "source_run_id": "omni-run-17",
        "screenshot_sha256": "a" * 64,
        "image_size": {"width": 800, "height": 600},
        "coordinate_space": "image_normalized_xyxy",
        "elements": [],
        "timing": {},
        "resource_usage": {},
        "provenance": {"runner": "local_smoke"},
    }

    saved_payload = {}
    trace_payload = {}
    result = run_recognition_task(
        RecognitionTaskInput(
            app_name="sample_app",
            state_hint="home",
            observation_evidence={
                "screen_size": {"width": 800, "height": 600},
                "capture_id": "capture-17",
                "screenshot_sha256": "a" * 64,
                "omniparser": parser_result,
                "sources": {"omniparser": parser_result},
            },
        ),
        project_root=tmp_path,
        trial_builder=lambda **kwargs: (
            captured_bundle.update(kwargs["observe_bundle"])
            or {
                "status": "ready",
                "screen_inventory": [],
                "classification": {"summary": {}},
                "learning_draft": {
                    "workflow_draft": {
                        "states": [],
                        "action_templates": [],
                        "verification_rules": [],
                    },
                    "interface_draft": {"regions": []},
                    "blockers": [],
                    "safety": {},
                },
            }
        ),
        grounding_adapter=lambda **_kwargs: {},
        trial_saver=lambda payload, *, app_name, project_root: (
            saved_payload.update(payload) or f"artifacts/{app_name}/trial.json"
        ),
        trace_writer=lambda **kwargs: (
            trace_payload.update(kwargs["payload"]) or "logs/traces/recognition.json"
        ),
    )

    assert result.outcome == "completed"
    assert "omniparser" not in captured_bundle["sources"]
    assert captured_bundle["capture_id"] == "capture-17"
    assert captured_bundle["screenshot_sha256"] == "a" * 64
    serialized = json.dumps({"bundle": captured_bundle, "saved": saved_payload, "trace": trace_payload})
    assert "omni-run-17" not in serialized
    assert "local_smoke" not in serialized
    assert "image_normalized_xyxy" not in serialized
