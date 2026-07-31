from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from app.api import action as action_api
from app.api.models.request import ExecuteRecognitionPlanRequest
from app.api.models.response import APIResponse, VisionResultData
from app.agent.reviewed_interface_memory import (
    ReviewedInterfaceMemoryStore,
    validate_current_target_text_anchor,
)
from tests.test_reviewed_interface_memory import _write_reviewed_candidate


def _bound_window() -> SimpleNamespace:
    return SimpleNamespace(
        handle=100,
        title="Sample Search",
        process_id=1234,
        process_name="sample.exe",
        rect=SimpleNamespace(left=0, top=0, right=1600, bottom=900),
        is_active=True,
    )


def _blocked_plan(goal: str, image_path: str) -> dict:
    return {
        "contract_version": "recognition_plan_v1",
        "image_path": image_path,
        "goal": goal,
        "candidate_result": {"summary": {"returned_count": 0}, "candidates": []},
        "recommended_target": None,
        "narrow_search_result": {"results": []},
        "pre_click_decision": {
            "contract_version": "pre_click_decision_v1",
            "allowed": False,
            "selected_candidate_id": None,
            "selected_click_point": None,
            "reasons": ["no_candidate_passed_pre_click_checks"],
            "candidate_decisions": [],
            "summary": {"candidate_count": 0, "allowed_candidate_count": 0},
        },
        "execution_path": {"vision_model_used": True, "action_executed": False},
        "trace_path": "logs/traces/vision/memory-dry-run.json",
    }


def _allowed_plan(goal: str, image_path: str, point: dict[str, int]) -> dict:
    return {
        "contract_version": "recognition_plan_v1",
        "image_path": image_path,
        "goal": goal,
        "candidate_result": {
            "summary": {"returned_count": 1},
            "candidates": [
                {
                    "candidate_id": "search_button",
                    "label": "Search",
                    "element": {"bbox": {"x": 860, "y": 120, "w": 180, "h": 63}},
                }
            ],
        },
        "recommended_target": {
            "candidate_id": "search_button",
            "label": "Search",
            "element": {"bbox": {"x": 860, "y": 120, "w": 180, "h": 63}},
        },
        "narrow_search_result": {
            "results": [
                {
                    "candidate_id": "search_button",
                    "refined_click_point": point,
                    "matched_text": "Search",
                }
            ]
        },
        "pre_click_decision": {
            "contract_version": "pre_click_decision_v1",
            "allowed": True,
            "selected_candidate_id": "search_button",
            "selected_click_point": point,
            "reasons": ["pre_click_candidate_allowed"],
        },
        "execution_path": {"vision_model_used": True, "action_executed": False},
        "trace_path": "logs/traces/vision/memory-local-anchor.json",
    }


def _ocr_match(text: str, *, x: int, y: int, width: int, height: int, score: float = 0.99) -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        score=score,
        bbox=SimpleNamespace(x=x, y=y, width=width, height=height),
    )


def test_local_target_anchor_accepts_current_ocr_evidence_near_selected_point() -> None:
    result = validate_current_target_text_anchor(
        seed={"locator_evidence": {"text_anchors": ["Search"]}},
        selected_point={"x": 940, "y": 151},
        observed_matches=[_ocr_match("Search", x=900, y=135, width=72, height=28)],
    )

    assert result["allowed"] is True
    assert result["reason"] == "current_target_text_anchor_locally_matched"
    assert result["nearest_anchor_distance"] == 0.0
    assert result["matched_anchor_evidence"][0]["bbox"] == {
        "x": 900,
        "y": 135,
        "width": 72,
        "height": 28,
    }


def test_local_target_anchor_rejects_same_text_elsewhere_on_current_surface() -> None:
    result = validate_current_target_text_anchor(
        seed={"locator_evidence": {"text_anchors": ["Senior Test Engineer"]}},
        selected_point={"x": 792, "y": 588},
        observed_matches=[
            _ocr_match("Senior Test Engineer", x=650, y=180, width=260, height=32),
        ],
    )

    assert result["allowed"] is False
    assert result["reason"] == "current_target_text_anchor_not_local_to_selected_point"
    assert result["nearest_anchor_distance"] > result["max_local_distance"]


def test_local_target_anchor_rejects_non_contiguous_token_match_near_selected_point() -> None:
    result = validate_current_target_text_anchor(
        seed={"locator_evidence": {"text_anchors": ["Senior Test Engineer"]}},
        selected_point={"x": 792, "y": 588},
        observed_matches=[
            _ocr_match("Senior Hardware Test Engineer", x=700, y=550, width=300, height=32),
        ],
    )

    assert result["allowed"] is False
    assert result["reason"] == "current_target_text_anchor_missing"
    assert result["matched_anchor_evidence"] == []


def test_local_target_anchor_accepts_wrapped_card_title_inside_seed_neighborhood() -> None:
    result = validate_current_target_text_anchor(
        seed={
            "role": "card",
            "bbox": {"x": 641, "y": 600, "w": 473, "h": 434},
            "locator_evidence": {"text_anchors": ["General Practitioner - Hauora Heretaunga"]},
        },
        selected_point={"x": 878, "y": 817},
        observed_matches=[
            _ocr_match("General Practitioner - Hauora", x=662, y=479, width=244, height=26),
            _ocr_match("Heretaunga", x=661, y=502, width=106, height=30),
        ],
    )

    assert result["allowed"] is True
    assert result["reason"] == "current_target_text_anchor_locally_matched"
    assert result["matched_anchor_evidence"][0]["evidence_source"] == "adjacent_ocr_lines"


def test_local_target_anchor_rejects_exact_query_text_outside_card_seed_neighborhood() -> None:
    result = validate_current_target_text_anchor(
        seed={
            "role": "card",
            "bbox": {"x": 70, "y": 352, "w": 1445, "h": 473},
            "locator_evidence": {"text_anchors": ["Senior Test Engineer"]},
        },
        selected_point={"x": 792, "y": 588},
        observed_matches=[
            _ocr_match("Senior Test Engineer", x=650, y=180, width=260, height=32),
        ],
    )

    assert result["allowed"] is False
    assert result["reason"] == "current_target_text_anchor_outside_seed_neighborhood"


def test_local_target_anchor_rejects_text_without_bbox_evidence() -> None:
    result = validate_current_target_text_anchor(
        seed={"locator_evidence": {"text_anchors": ["Search"]}},
        selected_point={"x": 940, "y": 151},
        observed_matches=[SimpleNamespace(text="Search", score=0.99)],
    )

    assert result["allowed"] is False
    assert result["reason"] == "current_target_text_anchor_bbox_missing"
    assert result["matched_anchor_evidence"] == []


def test_execute_route_injects_operational_memory_only_after_current_live_capture(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_path = _write_reviewed_candidate(tmp_path)
    store = ReviewedInterfaceMemoryStore(project_root=tmp_path)
    store.publish(source_path=source_path, interface_id="sample_search", expected_registry_revision=0)
    current_capture = tmp_path / "artifacts" / "screenshots" / "current-live.png"
    Image.new("RGB", (1600, 900), "white").save(current_capture)
    captured_plan_request: dict[str, object] = {}

    monkeypatch.setattr(action_api, "reviewed_interface_memory_store", store)
    monkeypatch.setattr(action_api.window_manager, "get_bound_window", _bound_window)
    monkeypatch.setattr(
        action_api.screenshot_service,
        "capture_window",
        lambda **kwargs: {
            "image_path": str(current_capture),
            "window_size": {"width": 1600, "height": 900},
        },
    )
    monkeypatch.setattr(
        action_api.ocr_service,
        "scan_image",
        lambda image_path: SimpleNamespace(
            matches=[SimpleNamespace(text="Search", score=0.99)],
            metadata={"engine": "test_ocr"},
        ),
    )

    def fake_recognition_plan(request):
        captured_plan_request["image_path"] = request.image_path
        captured_plan_request["metadata"] = request.metadata
        return APIResponse(
            success=True,
            message="blocked safely",
            data=VisionResultData(result=_blocked_plan(request.goal, request.image_path)).model_dump(),
            error=None,
        )

    monkeypatch.setattr(action_api, "_run_recognition_plan_for_execution", fake_recognition_plan)
    monkeypatch.setattr(action_api, "_render_recognition_plan_overlay_for_execution", lambda trace_path: None)
    monkeypatch.setattr(action_api, "write_trace", lambda **kwargs: "logs/traces/actions/memory-dry-run.json")

    response = action_api.execute_recognition_plan(
        ExecuteRecognitionPlanRequest(
            goal="Click Search",
            app_name="sample",
            interface_memory_id="sample_search",
            interface_memory_action_id="sample_search::action::submit_search",
            dry_run=True,
        )
    )

    metadata = captured_plan_request["metadata"]
    assert captured_plan_request["image_path"] == str(current_capture.resolve())
    assert metadata["operational_memory"]["interface_id"] == "sample_search"
    assert metadata["operational_memory"]["action_id"] == "sample_search::action::submit_search"
    assert metadata["seeded_candidate_v1"]["bbox"] == {"x": 860, "y": 120, "w": 180, "h": 63}
    assert metadata["seeded_candidate_v1"]["current_capture"]["screenshot_path"] == str(current_capture.resolve())
    assert metadata["seeded_candidate_v1"]["require_current_grounding"] is True
    assert metadata.get("reviewed_test_execution", {}).get("allow_seeded_candidate_without_model") is not True
    assert response.success is False
    assert response.error.code == "pre_click_rejected"
    feedback = response.data["learning_review_feedback"]
    assert feedback["review_status"] == "needs_human_review"
    payload = __import__("json").loads((tmp_path / feedback["feedback_path"]).read_text(encoding="utf-8"))
    assert payload["failure"]["category"] == "pre_click_rejected"
    assert payload["review_target"]["source_action_template_id"] == "submit_search"


def test_execute_route_blocks_operational_memory_on_current_surface_mismatch_before_model(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_path = _write_reviewed_candidate(tmp_path)
    store = ReviewedInterfaceMemoryStore(project_root=tmp_path)
    store.publish(source_path=source_path, interface_id="sample_search", expected_registry_revision=0)
    current_capture = tmp_path / "artifacts" / "screenshots" / "wrong-surface.png"
    Image.new("RGB", (1600, 900), "white").save(current_capture)
    model_called = False

    monkeypatch.setattr(action_api, "reviewed_interface_memory_store", store)
    monkeypatch.setattr(action_api.window_manager, "get_bound_window", _bound_window)
    monkeypatch.setattr(
        action_api.screenshot_service,
        "capture_window",
        lambda **kwargs: {
            "image_path": str(current_capture),
            "window_size": {"width": 1600, "height": 900},
        },
    )
    monkeypatch.setattr(
        action_api.ocr_service,
        "scan_image",
        lambda image_path: SimpleNamespace(
            matches=[SimpleNamespace(text="Unrelated dashboard", score=0.99)],
            metadata={"engine": "test_ocr"},
        ),
    )

    def fail_if_model_called(request):
        nonlocal model_called
        model_called = True
        raise AssertionError("surface mismatch must stop before model grounding")

    monkeypatch.setattr(action_api, "_run_recognition_plan_for_execution", fail_if_model_called)
    monkeypatch.setattr(action_api, "write_trace", lambda **kwargs: "logs/traces/actions/memory-surface-mismatch.json")

    response = action_api.execute_recognition_plan(
        ExecuteRecognitionPlanRequest(
            goal="Click Search",
            app_name="sample",
            interface_memory_id="sample_search",
            interface_memory_action_id="sample_search::action::submit_search",
            dry_run=True,
        )
    )

    assert model_called is False
    assert response.success is False
    assert response.error.code == "operational_memory_surface_mismatch"
    assert response.data["surface_validation"]["allowed"] is False
    assert response.data["surface_validation"]["reason"] == "current_surface_text_anchor_missing"
    assert response.data["surface_validation"]["required_text_anchors"] == ["Search"]


def test_execute_route_resolves_memory_action_from_natural_language_goal(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_path = _write_reviewed_candidate(tmp_path)
    store = ReviewedInterfaceMemoryStore(project_root=tmp_path)
    store.publish(source_path=source_path, interface_id="sample_search", expected_registry_revision=0)
    current_capture = tmp_path / "artifacts" / "screenshots" / "current-live.png"
    Image.new("RGB", (1600, 900), "white").save(current_capture)
    captured_plan_request: dict[str, object] = {}

    monkeypatch.setattr(action_api, "reviewed_interface_memory_store", store)
    monkeypatch.setattr(action_api.window_manager, "get_bound_window", _bound_window)
    monkeypatch.setattr(
        action_api.screenshot_service,
        "capture_window",
        lambda **kwargs: {
            "image_path": str(current_capture),
            "window_size": {"width": 1600, "height": 900},
        },
    )
    monkeypatch.setattr(
        action_api.ocr_service,
        "scan_image",
        lambda image_path: SimpleNamespace(
            matches=[SimpleNamespace(text="Search", score=0.99)],
            metadata={"engine": "test_ocr"},
        ),
    )

    def fake_recognition_plan(request):
        captured_plan_request["metadata"] = request.metadata
        return APIResponse(
            success=True,
            message="blocked safely",
            data=VisionResultData(result=_blocked_plan(request.goal, request.image_path)).model_dump(),
            error=None,
        )

    monkeypatch.setattr(action_api, "_run_recognition_plan_for_execution", fake_recognition_plan)
    monkeypatch.setattr(action_api, "_render_recognition_plan_overlay_for_execution", lambda trace_path: None)
    monkeypatch.setattr(action_api, "write_trace", lambda **kwargs: "logs/traces/actions/memory-goal-resolution.json")

    response = action_api.execute_recognition_plan(
        ExecuteRecognitionPlanRequest(
            goal="Click the Search button",
            app_name="sample",
            interface_memory_id="sample_search",
            dry_run=True,
        )
    )

    operational_memory = captured_plan_request["metadata"]["operational_memory"]
    assert operational_memory["action_id"] == "sample_search::action::submit_search"
    assert operational_memory["action_resolution"]["status"] == "selected"
    assert operational_memory["action_resolution"]["resolution_source"] == "deterministic_semantic_memory_match"
    assert response.error.code == "pre_click_rejected"


def test_execute_route_persists_memory_failure_for_human_review(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_path = _write_reviewed_candidate(tmp_path)
    store = ReviewedInterfaceMemoryStore(project_root=tmp_path)
    store.publish(source_path=source_path, interface_id="sample_search", expected_registry_revision=0)
    current_capture = tmp_path / "artifacts" / "screenshots" / "wrong-surface.png"
    Image.new("RGB", (1600, 900), "white").save(current_capture)

    monkeypatch.setattr(action_api, "reviewed_interface_memory_store", store)
    monkeypatch.setattr(action_api.window_manager, "get_bound_window", _bound_window)
    monkeypatch.setattr(
        action_api.screenshot_service,
        "capture_window",
        lambda **kwargs: {
            "image_path": str(current_capture),
            "window_size": {"width": 1600, "height": 900},
        },
    )
    monkeypatch.setattr(
        action_api.ocr_service,
        "scan_image",
        lambda image_path: SimpleNamespace(
            matches=[SimpleNamespace(text="Unrelated dashboard", score=0.99)],
            metadata={"engine": "test_ocr"},
        ),
    )
    monkeypatch.setattr(action_api, "write_trace", lambda **kwargs: "logs/traces/actions/memory-feedback.json")

    response = action_api.execute_recognition_plan(
        ExecuteRecognitionPlanRequest(
            goal="Click the Search button",
            app_name="sample",
            interface_memory_id="sample_search",
            dry_run=True,
        )
    )

    feedback = response.data["learning_review_feedback"]
    feedback_path = tmp_path / feedback["feedback_path"]
    payload = __import__("json").loads(feedback_path.read_text(encoding="utf-8"))
    assert payload["review_status"] == "needs_human_review"
    assert payload["failure"]["category"] == "operational_memory_surface_mismatch"
    assert payload["review_target"]["source_action_template_id"] == "submit_search"


def test_execute_route_blocks_memory_click_when_matching_text_is_not_local_to_selected_point(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_path = _write_reviewed_candidate(tmp_path)
    store = ReviewedInterfaceMemoryStore(project_root=tmp_path)
    store.publish(source_path=source_path, interface_id="sample_search", expected_registry_revision=0)
    current_capture = tmp_path / "artifacts" / "screenshots" / "current-live.png"
    Image.new("RGB", (1600, 900), "white").save(current_capture)
    click_called = False

    monkeypatch.setattr(action_api, "reviewed_interface_memory_store", store)
    monkeypatch.setattr(action_api.window_manager, "get_bound_window", _bound_window)
    monkeypatch.setattr(
        action_api.screenshot_service,
        "capture_window",
        lambda **kwargs: {
            "image_path": str(current_capture),
            "window_size": {"width": 1600, "height": 900},
        },
    )
    monkeypatch.setattr(
        action_api.ocr_service,
        "scan_image",
        lambda image_path: SimpleNamespace(
            matches=[_ocr_match("Search", x=50, y=40, width=80, height=28)],
            metadata={"engine": "test_ocr"},
        ),
    )
    monkeypatch.setattr(
        action_api,
        "_run_recognition_plan_for_execution",
        lambda request: APIResponse(
            success=True,
            message="plan ready",
            data=VisionResultData(
                result=_allowed_plan(request.goal, request.image_path, {"x": 940, "y": 151})
            ).model_dump(),
            error=None,
        ),
    )
    monkeypatch.setattr(action_api, "write_trace", lambda **kwargs: "logs/traces/actions/memory-local-mismatch.json")

    def fail_if_clicked(*args, **kwargs):
        nonlocal click_called
        click_called = True
        raise AssertionError("local anchor mismatch must stop before click")

    monkeypatch.setattr(action_api.input_controller, "click_point", fail_if_clicked)

    response = action_api.execute_recognition_plan(
        ExecuteRecognitionPlanRequest(
            goal="Click Search",
            app_name="sample",
            interface_memory_id="sample_search",
            interface_memory_action_id="sample_search::action::submit_search",
            dry_run=False,
        )
    )

    assert click_called is False
    assert response.success is False
    assert response.error.code == "operational_memory_local_target_mismatch"
    assert response.data["local_target_validation"]["allowed"] is False
    assert response.data["local_target_validation"]["reason"] == "current_target_text_anchor_outside_seed_neighborhood"
    feedback = response.data["learning_review_feedback"]
    payload = __import__("json").loads((tmp_path / feedback["feedback_path"]).read_text(encoding="utf-8"))
    assert payload["failure"]["category"] == "operational_memory_local_target_mismatch"


def test_execute_route_reports_successful_local_target_validation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_path = _write_reviewed_candidate(tmp_path)
    store = ReviewedInterfaceMemoryStore(project_root=tmp_path)
    store.publish(source_path=source_path, interface_id="sample_search", expected_registry_revision=0)
    current_capture = tmp_path / "artifacts" / "screenshots" / "current-live.png"
    Image.new("RGB", (1600, 900), "white").save(current_capture)

    monkeypatch.setattr(action_api, "reviewed_interface_memory_store", store)
    monkeypatch.setattr(action_api.window_manager, "get_bound_window", _bound_window)
    monkeypatch.setattr(
        action_api.screenshot_service,
        "capture_window",
        lambda **kwargs: {
            "image_path": str(current_capture),
            "window_size": {"width": 1600, "height": 900},
        },
    )
    monkeypatch.setattr(
        action_api.ocr_service,
        "scan_image",
        lambda image_path: SimpleNamespace(
            matches=[_ocr_match("Search", x=880, y=130, width=100, height=36)],
            metadata={"engine": "test_ocr"},
        ),
    )
    monkeypatch.setattr(
        action_api,
        "_run_recognition_plan_for_execution",
        lambda request: APIResponse(
            success=True,
            message="plan ready",
            data=VisionResultData(
                result=_allowed_plan(request.goal, request.image_path, {"x": 930, "y": 148})
            ).model_dump(),
            error=None,
        ),
    )
    monkeypatch.setattr(action_api, "write_trace", lambda **kwargs: "logs/traces/actions/memory-local-match.json")

    response = action_api.execute_recognition_plan(
        ExecuteRecognitionPlanRequest(
            goal="Click Search",
            app_name="sample",
            interface_memory_id="sample_search",
            interface_memory_action_id="sample_search::action::submit_search",
            dry_run=True,
        )
    )

    assert response.success is True
    assert response.data["result"]["local_target_validation"]["allowed"] is True
    assert response.data["result"]["local_target_validation"]["reason"] == "current_target_text_anchor_locally_matched"
