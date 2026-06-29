from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.gate.candidates import attach_candidate_freshness, validate_action_candidate_freshness
from app.gate.contracts import build_gate_contract_catalog, list_gate_contracts
from app.gate.scroll import build_scroll_effect_validation, build_scroll_precondition_decision, build_scroll_safe_point
from app.gate.window import validate_bound_window_for_app
from app.main import app
from app.operation.skills import build_operation_skill_catalog, list_operation_skills
from app.operation.mousetester import should_verify_mouse_tester_semantics, target_bbox_from_recommended
from app.operation import region_click as region_click_module
from app.operation.region_click import run_region_click
from app.runtime_architecture.contracts import TraceEvent
from app.trace.actions import execute_trace_enabled, execute_trace_operation, write_execute_trace_if_enabled
from app.trace.recorder import record_trace_event


def test_gate_layer_exposes_candidate_freshness_contract() -> None:
    candidate = attach_candidate_freshness(
        {"bbox": {"x": 1, "y": 2, "w": 30, "h": 20}, "click_point": {"x": 10, "y": 10}},
        capture_id="capture-1",
        viewport_size={"width": 800, "height": 600},
        source="unit_test",
    )

    decision = validate_action_candidate_freshness(
        candidate,
        current_capture_id="capture-1",
        current_viewport_size={"width": 800, "height": 600},
    )

    assert decision["allowed"] is True
    assert decision["reasons"] == ["candidate_freshness_current"]


def test_gate_layer_validates_bound_window_aliases() -> None:
    edge = validate_bound_window_for_app(
        expected_app_name="edge",
        bound_window={"process_name": "msedge.exe", "title": "SEEK - Microsoft Edge"},
    )
    mismatch = validate_bound_window_for_app(
        expected_app_name="edge",
        bound_window={"process_name": "QQ.exe", "title": "QQ"},
    )
    custom = validate_bound_window_for_app(
        expected_app_name="custom-new-app",
        bound_window={"process_name": "unknown.exe", "title": "Something Else"},
    )

    assert edge["valid"] is True
    assert edge["reason"] == "matched_app_alias"
    assert mismatch["valid"] is False
    assert mismatch["reason"] == "process_name_mismatch"
    assert custom["valid"] is True
    assert custom["reason"] == "unmapped_app_name_not_enforced"


def test_operation_layer_catalog_maps_seek_profile_skills() -> None:
    catalog = build_operation_skill_catalog("seek")
    skills = {item["skill_id"]: item for item in catalog["skills"]}

    assert catalog["contract_version"] == "operation_skill_catalog_v1"
    assert catalog["app_id"] == "seek"
    assert skills["open_apply_entry"]["base_skill_id"] == "open_apply_flow"
    assert skills["read_full_job_detail"]["base_skill_id"] == "read_full_page"
    assert skills["observe_screen"]["requires_gate"] is False


def test_operation_layer_base_catalog_contains_framework_skills() -> None:
    skills = {item["skill_id"] for item in list_operation_skills()}

    assert {"observe_screen", "locate_element", "click_target", "type_text", "scroll_region", "read_region"}.issubset(skills)


def test_operation_layer_runs_region_click_without_action_api_dependency(tmp_path, monkeypatch) -> None:
    class Rect:
        left = 0
        top = 0
        right = 200
        bottom = 100

    class Bound:
        rect = Rect()

    class FakeVerifier:
        def capture_pre_action_state(self, *, action_name: str) -> dict[str, object]:
            return {"action_name": action_name}

        def verify_action(self, action_name: str, *, before_state: dict[str, object], click_result: dict[str, object]) -> dict[str, object]:
            return {"verified": True, "diff": {"changed": True, "count": 3}, "before_state": before_state, "click_result": click_result}

    class FakeInputController:
        def click_point(self, x: int, y: int, **kwargs: object) -> dict[str, object]:
            return {"x": x, "y": y, "kwargs": kwargs}

    monkeypatch.setattr(region_click_module, "REGION_CLICK_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(region_click_module, "REGION_CLICK_CASES_DIR", tmp_path / "cases")
    region_click_module.REGION_CLICK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    region_click_module.REGION_CLICK_CASES_DIR.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(region_click_module, "verifier", FakeVerifier())
    monkeypatch.setattr(region_click_module, "input_controller", FakeInputController())

    result = run_region_click(
        case_name="unit_region_click",
        bound=Bound(),
        panel_locator=lambda _bound: {"x": 0, "y": 0, "width": 200, "height": 100},
        zone_resolver=lambda _panel: {"x": 10, "y": 20, "width": 50, "height": 40},
        point_strategy=lambda _zone, _preferred: [{"x": 20, "y": 30}],
        validator=lambda _before, _after: {"strict_success": False, "weak_success": False},
    )

    assert result["success"] is True
    assert result["selected_point"] == {"x": 20, "y": 30}
    assert Path(result["memory_path"]).exists()
    assert Path(result["case_path"]).exists()


def test_operation_layer_exposes_mousetester_semantic_helpers() -> None:
    class Request:
        app_name = "MouseTesterWeb"
        state_hint = "MouseTester main page"

    plan = {
        "goal": "点击此处测试",
        "recommended_target": {"element": {"bbox": {"x": 10, "y": 20, "w": 30, "h": 40}}},
    }

    assert should_verify_mouse_tester_semantics(request=Request(), plan=plan) is True
    assert target_bbox_from_recommended(plan["recommended_target"]) == {"x": 10, "y": 20, "width": 30, "height": 40}


def test_gate_contract_catalog_maps_seek_profile_contracts() -> None:
    catalog = build_gate_contract_catalog("seek")
    contracts = {item["contract_id"]: item for item in catalog["contracts"]}

    assert catalog["contract_version"] == "gate_contract_catalog_v1"
    assert "candidate_freshness_v1" in contracts
    assert contracts["bound_window_match_v1"]["layer_module"] == "app.gate.window"
    assert contracts["final_submit_guard_v1"]["layer_module"] == "app.gate.danger"
    assert contracts["profile_mutation_requires_user_approval_v1"]["layer_module"] == "app.gate.candidates"
    assert any(item["contract_id"] == "latest_detail_snapshot_v1" for item in list_gate_contracts())


def test_gate_layer_builds_scroll_precondition_and_effect_contracts() -> None:
    class Request:
        coordinate_window_size = {"width": 800, "height": 600}
        scroll_scope = "container"
        direction = "down"
        target_container_id = "seek:job_detail"
        target_pane = "job_detail"

    point = build_scroll_safe_point({"x": 100, "y": 80, "width": 400, "height": 300}, explicit_x=None, explicit_y=None)
    precondition = build_scroll_precondition_decision(
        request=Request(),
        window_rect={"width": 800, "height": 600},
        point=point,
        container_rect={"x": 100, "y": 80, "width": 400, "height": 300},
        target_container={"container_id": "seek:job_detail", "pane_role": "job_detail", "can_scroll_down": True},
    )
    effect = build_scroll_effect_validation(
        request=Request(),
        post_scroll_verification={"verified": True, "verification_basis": "unit"},
        target_container={"container_id": "seek:job_detail", "pane_role": "job_detail"},
    )

    assert precondition["contract_version"] == "scroll_precondition_decision_v1"
    assert precondition["decision"] == "ALLOW"
    assert "point_inside_container" in precondition["reasons"]
    assert effect["contract_version"] == "scroll_effect_validation_v1"
    assert effect["status"] == "moved"
    assert effect["target_container_id"] == "seek:job_detail"


def test_trace_layer_records_trace_event() -> None:
    path = record_trace_event(
        TraceEvent(
            event_type="unit_test_event",
            layer="trace",
            summary="record trace facade smoke",
            evidence_refs=["tests/test_runtime_layer_facades.py"],
        ),
        category="unit_tests",
        name_hint="runtime_layer_facades",
    )

    assert Path(path).exists()
    assert "unit-test-event" in Path(path).name


def test_trace_layer_controls_execute_action_trace_writes() -> None:
    class WritePolicy:
        def __init__(self, trace: bool) -> None:
            self.trace = trace

        def model_dump(self) -> dict[str, bool]:
            return {"trace": self.trace}

    class Request:
        def __init__(self, *, dry_run: bool, trace: bool) -> None:
            self.dry_run = dry_run
            self.write_policy = WritePolicy(trace)

    written: list[dict[str, object]] = []

    disabled = write_execute_trace_if_enabled(
        Request(dry_run=True, trace=False),
        write_trace_fn=lambda **kwargs: written.append(kwargs) or "trace.json",
        category="actions",
        operation="execute_recognition_plan",
        payload={"ok": True},
        name_hint="unit",
    )
    enabled = write_execute_trace_if_enabled(
        Request(dry_run=False, trace=True),
        write_trace_fn=lambda **kwargs: written.append(kwargs) or "trace.json",
        category="actions",
        operation="execute_recognition_plan",
        payload={"ok": True},
        name_hint="unit",
    )

    assert disabled is None
    assert enabled == "trace.json"
    assert execute_trace_enabled(Request(dry_run=True, trace=True)) is True
    assert execute_trace_operation(Request(dry_run=True, trace=True), "execute_recognition_plan") == "execute_mode_plan_preview"
    assert written == [
        {
            "category": "actions",
            "operation": "execute_mode_click",
            "payload": {"ok": True},
            "name_hint": "unit",
        }
    ]


def test_runtime_architecture_and_operation_skill_routes() -> None:
    client = TestClient(app)

    arch_response = client.get("/runtime/architecture")
    assert arch_response.status_code == 200
    arch_payload = arch_response.json()
    assert arch_payload["success"] is True
    assert arch_payload["data"]["contract_version"] == "gui_agent_runtime_architecture_v1"

    skills_response = client.get("/runtime/operation_skills", params={"app_id": "seek"})
    assert skills_response.status_code == 200
    skills_payload = skills_response.json()
    assert skills_payload["success"] is True
    assert skills_payload["data"]["contract_version"] == "operation_skill_catalog_v1"
    assert any(item["skill_id"] == "open_apply_entry" for item in skills_payload["data"]["skills"])

    gates_response = client.get("/runtime/gate_contracts", params={"app_id": "seek"})
    assert gates_response.status_code == 200
    gates_payload = gates_response.json()
    assert gates_payload["success"] is True
    assert gates_payload["data"]["contract_version"] == "gate_contract_catalog_v1"
    assert any(item["contract_id"] == "final_submit_guard_v1" for item in gates_payload["data"]["contracts"])
