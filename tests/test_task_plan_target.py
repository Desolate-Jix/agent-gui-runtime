"""有限结构化目标的同帧原生身份与模型前选择；无桌面或模型服务。"""
from copy import deepcopy
from hashlib import sha256

from PIL import Image
import pytest


TARGET = {"name": "Find", "control_type": "Button"}


@pytest.fixture
def current_frame(tmp_path):
    path = tmp_path / "fresh.png"
    Image.new("RGB", (900, 600), "white").save(path)
    capture = {"capture_id": str(path.resolve()), "image_path": str(path.resolve()),
               "sha256": sha256(path.read_bytes()).hexdigest(), "image_size": {"width": 900, "height": 600},
               "window_identity": {"handle": 11, "process_id": 22},
               "screen_rect": {"x": 100, "y": 200, "w": 900, "h": 600}}
    controls = [control("find", "Find", "Button", (40, 80, 120, 40))]
    snapshot = {"provider": "windows_uia", "status": "ok", "scan_scope": "bound_window",
                "scan_complete": True, "truncated": False, "provider_tree_valid": True,
                "window": {"handle": 11, "process_id": 22, "bbox": {"x": 0, "y": 0, "w": 900, "h": 600}},
                "controls": controls}
    return capture, snapshot


def control(identifier, name, kind, box, *, ancestors=(), offset=(100, 200), **changes):
    x, y, width, height = box
    return {"provider": "windows_uia", "control_id": identifier, "runtime_id": [42, *map(ord, identifier)],
            "name": name, "control_type": kind, "automation_id": "", "enabled": True, "visible": True,
            "patterns": ["Value", "Text"] if kind in {"Edit", "ComboBox"} else ["Invoke"],
            "bbox": {"x": x, "y": y, "w": width, "h": height},
            "screen_bbox": {"x": x + offset[0], "y": y + offset[1], "w": width, "h": height},
            "ancestor_control_ids": list(ancestors), **changes}


def resolve(current_frame, target=None):
    from app.execution.task_plan_target import resolve_current_uia_target
    capture, snapshot = current_frame
    return resolve_current_uia_target(target or TARGET, capture=capture, snapshot=snapshot)


def test_structured_target_is_frozen_and_transferred_to_original_click_command():
    from app.execution.task_plan_backend import TaskPlanBackend
    from app.execution.task_plan_contract import validate_task_plan
    plan = {"schema_version": "task_plan.v1", "title": "Fresh target", "inputs": {}, "steps": [
        {"step_id": "find", "action": {"kind": "click", "goal": "Find the matching row", "target": deepcopy(TARGET)},
         "verification": {"kind": "agent_judgment"}}]}
    frozen = validate_task_plan(plan)
    plan["steps"][0]["action"]["target"]["name"] = "changed"
    command = TaskPlanBackend._command(frozen["steps"][0], {})
    assert command["operation"] == "execute_recognition_plan"
    assert command["request"]["metadata"]["task_plan_target"] == TARGET


@pytest.mark.parametrize("change", [{"x": 20}, {"runtime_id": [1]}, {"capture_id": "old"},
    {"control_type": "Text"}, {"name": " "}, {"name": "a" * 513},
    {"container": {"name": "Form", "control_type": "Button"}},
    {"container": {"name": "Form", "control_type": "Pane", "bbox": {"x": 1}}}])
def test_semantic_target_rejects_coordinates_identity_and_unbounded_types(change):
    from app.execution.task_plan_target import validate_task_plan_control_target
    with pytest.raises(ValueError, match="task_plan_target"):
        validate_task_plan_control_target({**TARGET, **change})


def test_unique_current_control_has_native_source_and_capture_geometry(current_frame):
    value = resolve(current_frame)
    assert value["status"] == "matched"
    assert value["source"] == "windows_uia"
    assert value["control_id"] == "find"
    assert value["click_point"] == {"x": 100, "y": 100}
    assert value["bbox"] == {"x": 40, "y": 80, "w": 120, "h": 40}
    assert value["capture_id"] == current_frame[0]["capture_id"]
    assert value["viewport_size"] == {"width": 900, "height": 600}
    assert value["freshness"] == "current_capture"


def test_duplicate_and_absent_are_explicit_model_route_results(current_frame):
    snapshot = current_frame[1]
    snapshot["controls"].append(control("other-find", "Find", "Button", (340, 80, 120, 40)))
    assert resolve(current_frame)["status"] == "ambiguous"
    assert resolve(current_frame, {"name": "Missing", "control_type": "Button"})["status"] == "miss"


def test_container_uses_real_ancestor_relationship_before_uniqueness(current_frame):
    snapshot = current_frame[1]
    snapshot["controls"] = [control("form", "Search form", "Pane", (10, 10, 250, 190)),
        control("find", "Find", "Button", (40, 80, 120, 40), ancestors=("form",)),
        control("outside-find", "Find", "Button", (340, 80, 120, 40))]
    target = {**TARGET, "container": {"name": "Search form", "control_type": "Pane"}}
    assert resolve(current_frame, target)["control_id"] == "find"
    snapshot["controls"][1]["ancestor_control_ids"] = []
    assert resolve(current_frame, target)["status"] == "miss"
    snapshot["controls"].append(control("second-form", "Search form", "Pane", (300, 10, 250, 190)))
    assert resolve(current_frame, target)["status"] == "ambiguous"


@pytest.mark.parametrize("mutation,reason", [
    ("window", "window_mismatch"), ("size", "viewport_mismatch"), ("hash", "capture_changed"),
    ("incomplete", "uia_incomplete"), ("provider", "uia_provider_failed"),
    ("duplicate_id", "uia_identity_invalid"), ("unknown_ancestor", "uia_identity_invalid"),
    ("dpi", "coordinate_mismatch"), ("outside", "geometry_invalid"),
])
def test_bad_native_evidence_is_rejected_not_reclassified_as_miss(current_frame, mutation, reason):
    capture, snapshot = current_frame
    if mutation == "window": snapshot["window"]["handle"] = 99
    elif mutation == "size": snapshot["window"]["bbox"]["w"] = 600
    elif mutation == "hash": capture["sha256"] = "0" * 64
    elif mutation == "incomplete": snapshot.update(scan_complete=False, truncated=True)
    elif mutation == "provider": snapshot.update(status="failed")
    elif mutation == "duplicate_id": snapshot["controls"].append(deepcopy(snapshot["controls"][0]))
    elif mutation == "unknown_ancestor": snapshot["controls"][0]["ancestor_control_ids"] = ["uncollected"]
    elif mutation == "dpi": snapshot["controls"][0]["screen_bbox"]["x"] = 210
    elif mutation == "outside": snapshot["controls"][0]["bbox"]["w"] = 950
    with pytest.raises(ValueError, match=reason):
        resolve(current_frame)


def test_duplicate_runtime_identity_is_not_an_exact_native_target(current_frame):
    other = control("other", "Other", "Button", (340, 80, 120, 40))
    other["runtime_id"] = list(current_frame[1]["controls"][0]["runtime_id"])
    current_frame[1]["controls"].append(other)
    with pytest.raises(ValueError, match="uia_identity_invalid"):
        resolve(current_frame)


@pytest.mark.parametrize("flag", ["is_read_only", "readonly", "is_password", "protected"])
def test_structured_field_refuses_unwritable_native_evidence(current_frame, flag):
    current_frame[1]["controls"] = [control("query", "Query", "Edit", (40, 80, 120, 40), **{flag: True})]
    with pytest.raises(ValueError, match="field_not_writable"):
        resolve(current_frame, {"name": "Query", "control_type": "Edit"})


def native_plan(current_frame, monkeypatch, *, target=TARGET, goal="Click the Find button", model_allowed=False):
    from app.api import vision
    from app.core.runtime_artifacts import RuntimeTimer, pinned_runtime_output_root
    from app.operation.screen_reading.uia_provider import pinned_uia_snapshot
    from modules.ocr.contracts import OCRResult
    capture, snapshot = current_frame
    path = __import__("pathlib").Path(capture["image_path"])
    calls = []
    def infer(**kwargs):
        calls.append(kwargs)
        if not model_allowed:
            pytest.fail("unique structured current UIA target must not invoke the model")
        return {"point": {"x": 100, "y": 100}, "provider": "isolated-model-boundary"}
    monkeypatch.setattr(vision, "_call_vista_point_prompt", infer)
    monkeypatch.setattr(vision.ocr_service, "scan_image", lambda path: OCRResult(image_path=str(path), matches=[]))
    metadata = {"task_plan_target": deepcopy(target), "task_plan_capture": deepcopy(capture)} if target is not None else {}
    request = vision.VisionRecognitionPlanRequestModel(image_path=str(path), task="locate_element", goal=goal,
        agent_mode="execute", provider_mode="local_grounding", metadata=metadata,
        write_policy={"path_graph": False, "element_memory": False, "trace": False})
    with pinned_uia_snapshot(snapshot), pinned_runtime_output_root(path.parent):
        response = vision._recognition_plan_from_vista_point(request=request, timer=RuntimeTimer(),
            config={"vision": {"mode": "local_grounding"}}, local_config={"model_name": "isolated", "endpoint": "http://unused.invalid"},
            image_path=path, input_image_size=vision.ImageSize(width=900, height=600), goal=goal,
            observe_reuse={}, path_graph_recall={"status": "not_requested", "candidates": []})
    return response.data["result"], calls


def test_unique_structured_button_uses_existing_candidates_without_model(current_frame, monkeypatch):
    plan, calls = native_plan(current_frame, monkeypatch)
    assert calls == []
    assert plan["execution_path"]["vision_model_used"] is False
    assert plan["execution_path"]["vision_provider_used"] == "windows_uia"
    assert plan["model_io"]["status"] == "skipped"
    assert plan["pre_click_decision"]["contract_version"] == "pre_click_decision_v1"
    assert plan["candidate_result"]["summary"]["task_plan_target_resolution"]["status"] == "matched"
    selected = plan["recommended_target"]
    assert selected["element"]["evidence"]["screen_inventory_action"]["source_id"] == "find"
    assert selected["element"]["evidence"]["task_plan_current_uia_target"]["source"] == "windows_uia"
    assert plan["narrow_search_result"]["results"][0]["refined_click_point"] == {"x": 100, "y": 100}


@pytest.mark.parametrize("kind", ["Edit", "ComboBox", "Hyperlink", "MenuItem", "TabItem"])
def test_supported_current_types_use_same_candidates_and_zero_inference(current_frame, monkeypatch, kind):
    current_frame[1]["controls"] = [control("target", "Find", kind, (40, 80, 120, 40))]
    plan, calls = native_plan(current_frame, monkeypatch, target={"name": "Find", "control_type": kind})
    assert calls == []
    assert plan["execution_path"]["vision_provider_used"] == "windows_uia"
    assert plan["recommended_target"]["element"]["evidence"]["task_plan_current_uia_target"]["control_id"] == "target"


def test_browser_navigation_named_control_requires_full_physical_window_tree(current_frame, monkeypatch):
    current_frame[1]["controls"] = [control("address", "Address", "Edit", (40, 80, 600, 40))]
    plan, calls = native_plan(current_frame, monkeypatch,
        target={"name": "Address", "control_type": "Edit"}, goal="Click the browser Address input field")
    assert calls == []
    assert plan["narrow_search_result"]["results"][0]["refined_click_point"] == {"x": 340, "y": 100}
    current_frame[1]["controls"][0]["screen_bbox"]["w"] = 400
    with pytest.raises(ValueError, match="coordinate_mismatch"):
        native_plan(current_frame, monkeypatch,
            target={"name": "Address", "control_type": "Edit"}, goal="Click the browser Address input field")


def test_unwritable_field_and_provider_failure_never_reach_visual_boundary(current_frame, monkeypatch):
    current_frame[1]["controls"] = [control("query", "Query", "Edit", (40, 80, 120, 40), is_read_only=True)]
    with pytest.raises(ValueError, match="field_not_writable"):
        native_plan(current_frame, monkeypatch, target={"name": "Query", "control_type": "Edit"})
    current_frame[1]["status"] = "failed"
    with pytest.raises(ValueError, match="uia_provider_failed"):
        native_plan(current_frame, monkeypatch)


def test_absent_target_preserves_configured_visual_route(current_frame, monkeypatch):
    plan, calls = native_plan(current_frame, monkeypatch, target={"name": "Missing", "control_type": "Button"}, model_allowed=True)
    assert calls
    assert plan["candidate_result"]["summary"]["task_plan_target_resolution"]["status"] == "miss"
    assert plan["execution_path"]["vision_provider_used"] != "windows_uia"


def test_visual_miss_keeps_explicit_semantics_and_never_substitutes_generic_button(current_frame, monkeypatch):
    current_frame[1]["controls"] = [control("row", "Safe row", "Pane", (10, 10, 700, 190)),
        control("find", "Find", "Button", (40, 80, 120, 40), ancestors=("row",))]
    target = {"name": "Delete draft", "control_type": "Button",
              "container": {"name": "Safe row", "control_type": "Pane"}}
    plan, calls = native_plan(current_frame, monkeypatch, target=target, goal="Click the button", model_allowed=True)
    assert calls and "Delete draft" in calls[0]["prompt"] and "Safe row" in calls[0]["prompt"]
    assert '"control_type": "Button"' in calls[0]["prompt"]
    assert plan["recommended_target"] is None
    assert plan["candidate_result"]["candidates"] == []
    assert plan["pre_click_decision"]["allowed"] is False
    assert plan["candidate_result"]["summary"]["task_plan_target_visual_selection"]["status"] == "rejected"


def test_visual_selection_checks_container_and_raw_identity(current_frame):
    from app.execution.task_plan_target import validate_task_plan_visual_selection
    capture, snapshot = current_frame
    snapshot["controls"] = [control("row", "Safe row", "Pane", (10, 10, 700, 190)),
        control("find", "Find", "Button", (40, 80, 120, 40), ancestors=("row",)),
        control("other-find", "Find", "Button", (340, 80, 120, 40))]
    target = {**TARGET, "container": {"name": "Safe row", "control_type": "Pane"}}
    action = {"source": "windows_uia.controls", "source_id": "find", "bbox": snapshot["controls"][1]["bbox"]}
    value = validate_task_plan_visual_selection(target, capture=capture, snapshot=snapshot,
        action=action, bbox=action["bbox"], point={"x": 100, "y": 100})
    assert value["status"] == "matched" and value["source"] == "windows_uia"
    action = {"source": "windows_uia.controls", "source_id": "other-find", "bbox": snapshot["controls"][2]["bbox"]}
    with pytest.raises(ValueError, match="visual_semantics_unconfirmed"):
        validate_task_plan_visual_selection(target, capture=capture, snapshot=snapshot,
            action=action, bbox=action["bbox"], point={"x": 400, "y": 100})


def test_duplicate_target_preserves_original_visual_route(current_frame, monkeypatch):
    current_frame[1]["controls"].append(control("other-find", "Find", "Button", (340, 80, 120, 40)))
    plan, calls = native_plan(current_frame, monkeypatch, model_allowed=True)
    assert calls
    assert plan["candidate_result"]["summary"]["task_plan_target_resolution"]["status"] == "ambiguous"
    assert plan["candidate_result"]["summary"]["task_plan_target_visual_selection"]["status"] == "matched"
    assert plan["recommended_target"]["element"]["evidence"]["task_plan_current_uia_target"]["control_id"] == "find"
    assert plan["execution_path"]["vision_provider_used"] != "windows_uia"


def test_no_structured_target_keeps_original_model_route(current_frame, monkeypatch):
    plan, calls = native_plan(current_frame, monkeypatch, target=None, model_allowed=True)
    assert calls
    assert plan["execution_path"]["vision_provider_used"] != "windows_uia"


def bound_facts():
    return {"handle": 11, "process_id": 22,
            "rect": {"left": 100, "top": 200, "width": 900, "height": 600}}


def test_internal_capture_uses_live_file_and_facts_not_caller_binding(current_frame):
    from app.execution.task_plan_target import bind_task_plan_capture
    metadata = {"task_plan_target": deepcopy(TARGET), "task_plan_capture": {"sha256": "forged", "source": "agent"}}
    capture = bind_task_plan_capture(metadata, live_capture={"image_path": current_frame[0]["image_path"],
        "window_size": {"width": 900, "height": 600}, "roi": None},
        before=bound_facts(), current=bound_facts(), identity={"process_create_time": 123.0})
    assert metadata["task_plan_capture"]["sha256"] == "forged"
    assert capture["task_plan_capture"] == {**current_frame[0], "window_identity": {
        "handle": 11, "process_id": 22, "process_create_time": 123.0}}


@pytest.mark.parametrize("defect", ["handle", "process_id", "rect", "viewport", "roi", "missing"])
def test_internal_capture_refuses_changed_window_or_partial_image(current_frame, defect):
    from app.execution.task_plan_target import bind_task_plan_capture
    before, current = bound_facts(), bound_facts()
    live = {"image_path": current_frame[0]["image_path"], "window_size": {"width": 900, "height": 600}, "roi": None}
    if defect in {"handle", "process_id"}: current[defect] += 1
    elif defect == "rect": current["rect"]["left"] += 1
    elif defect == "viewport": live["window_size"]["width"] = 600
    elif defect == "roi": live["roi"] = {"x": 0, "y": 0, "w": 900, "h": 600}
    elif defect == "missing": live = None
    with pytest.raises(ValueError, match="task_plan_target"):
        bind_task_plan_capture({"task_plan_target": TARGET}, live_capture=live, before=before, current=current)


def test_no_target_clears_forged_capture_without_reading_live_desktop():
    from app.execution.task_plan_target import bind_task_plan_capture
    assert bind_task_plan_capture({"task_plan_capture": {"forged": True}, "normal": 1},
        live_capture=None, before=None, current=None) == {"normal": 1}


@pytest.mark.parametrize("defect", [None, "capture_window", "capture_pid", "capture_geometry",
    "uia_window", "uia_pid", "uia_viewport", "uia_truncated", "uia_provider", "dispatch_capture", "visual_substitute"])
def test_gated_action_rebuilds_capture_and_rejects_drift_before_any_input(current_frame, monkeypatch, defect):
    from types import SimpleNamespace
    from app.api import action, vision
    from app.api.models.request import ExecuteRecognitionPlanRequest
    from app.core.local_input_policy import _local_operator_input_scope
    from app.agent import windows_control_hit_reader as hit_reader, windows_text_field_reader as field_reader
    from app.operation.screen_reading.uia_provider import pinned_uia_snapshot
    from modules.ocr.contracts import OCRResult
    capture, snapshot = current_frame
    identity = {"contract_version": "windows_native_identity_observation_v1", "provider": "windows_native_identity",
        "status": "observed", "target_window_handle": 11, "process_id": 22,
        "process_create_time": 123.0, "executable_path": "c:\\fixture\\editor.exe"}
    bound = SimpleNamespace(handle=11, process_id=22, title="Fixture", process_name="editor.exe",
        rect=SimpleNamespace(left=100, top=200, right=1000, bottom=800))
    manager = SimpleNamespace(get_bound_window=lambda: bound)
    root = SimpleNamespace(element_info=SimpleNamespace(handle=11, process_id=22))
    hit = SimpleNamespace(element_info=SimpleNamespace(handle=0, process_id=22,
        element=SimpleNamespace(CurrentProcessId=22), name="Find", control_type="Button",
        runtime_id=list(snapshot["controls"][0]["runtime_id"]),
        rectangle=SimpleNamespace(left=140, top=280, right=260, bottom=320)),
        parent=lambda: root, is_visible=lambda: True, is_enabled=lambda: True)
    monkeypatch.setattr(hit_reader, "_desktop_factory", lambda **kw: SimpleNamespace(from_point=lambda x, y: hit))
    monkeypatch.setattr(hit_reader, "WindowsNativeIdentityReader", lambda **kw:
        SimpleNamespace(read_identity=lambda handle: deepcopy(identity)))
    monkeypatch.setattr(field_reader, "_native_root_handle", lambda handle: 11 if handle == 11 else None)
    monkeypatch.setattr(action, "window_manager", manager)
    def fresh_capture(**kwargs):
        if defect == "capture_window": bound.handle = 99
        elif defect == "capture_pid": bound.process_id = 99
        elif defect == "capture_geometry": bound.rect.left += 1
        return {"image_path": capture["image_path"], "window_size": capture["image_size"], "roi": None}
    monkeypatch.setattr(action.screenshot_service, "capture_window", fresh_capture)
    if defect == "uia_window": snapshot["window"]["handle"] = 99
    elif defect == "uia_pid": snapshot["window"]["process_id"] = 99
    elif defect == "uia_viewport": snapshot["window"]["bbox"]["w"] = 600
    elif defect == "uia_truncated": snapshot.update(scan_complete=False, truncated=True)
    elif defect == "uia_provider": snapshot["status"] = "failed"
    declared_target = TARGET
    if defect == "visual_substitute":
        snapshot["controls"] = [control("row", "Safe row", "Pane", (10, 10, 700, 190)),
            control("find", "Find", "Button", (40, 80, 120, 40), ancestors=("row",))]
        declared_target = {"name": "Delete draft", "control_type": "Button",
            "container": {"name": "Safe row", "control_type": "Pane"}}
    monkeypatch.setattr(vision.VisionProviderFactory, "load_config", lambda: {"vision": {"mode": "local_grounding"}})
    monkeypatch.setattr(vision.VisionProviderFactory, "create", lambda **kwargs: object())
    monkeypatch.setattr(vision, "_selected_local_vision_config", lambda *args: {"model_name": "isolated"})
    monkeypatch.setattr(vision, "_uses_vista_point_grounding", lambda config: True)
    monkeypatch.setattr(vision, "_call_vista_point_prompt", lambda **kw:
        {"point": {"x": 100, "y": 100}, "provider": "isolated-model-boundary"}
        if defect == "visual_substitute" else pytest.fail("native match must not call model"))
    monkeypatch.setattr(vision.ocr_service, "scan_image", lambda path: OCRResult(image_path=str(path), matches=[]))
    seen = []
    def recognize(request):
        seen.append(deepcopy(request.metadata))
        result = vision.recognition_plan(request)
        if defect == "dispatch_capture": Image.new("RGB", (900, 600), "black").save(capture["image_path"])
        return result
    monkeypatch.setattr(action, "_run_recognition_plan_for_execution", recognize)
    clicks = []
    monkeypatch.setattr(action.input_controller, "click_point", lambda x, y, **kw:
        clicks.append((x, y)) or {"clicked": True, "window_point": {"x": x, "y": y}})
    monkeypatch.setattr(action, "_render_recognition_plan_overlay_for_execution", lambda p: None)
    request = ExecuteRecognitionPlanRequest(goal="Click the button" if defect == "visual_substitute" else "Click the Find button", enable_post_click_verification=False,
        max_execution_attempts=1, auto_observe_learning_artifacts=False,
        metadata={"task_plan_target": declared_target, "task_plan_capture": {"sha256": "forged", "source": "agent",
            "capture_id": "forged", "window_identity": {"handle": 99, "process_id": 99}}},
        write_policy={"path_graph": False, "element_memory": False, "trace": False})
    with _local_operator_input_scope(manager=manager, identity_reader=SimpleNamespace(read_identity=lambda handle: deepcopy(identity)),
            identity=identity, window_rect=(100, 200, 1000, 800), enabled=lambda: True), pinned_uia_snapshot(snapshot):
        response = action.execute_recognition_plan(request)
    if defect is None:
        assert response.success, response
        assert clicks == [(100, 100)]
        result = response.data["result"]
        assert result["task_plan_capture_check"]["source"] == "windows_uia"
    else:
        assert not response.success, response
        assert clicks == []
    if seen:
        trusted = seen[0]["task_plan_capture"]
        assert trusted["sha256"] == capture["sha256"]
        assert trusted["capture_id"] == capture["capture_id"]
        assert trusted["window_identity"] == {"handle": 11, "process_id": 22, "process_create_time": 123.0}
        assert "source" not in trusted
