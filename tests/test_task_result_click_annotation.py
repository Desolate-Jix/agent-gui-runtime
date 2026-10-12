"""普通结果使用原真实点击标注整图，保留历史绑定，不模拟执行成功。"""
import base64
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json

from PIL import Image, ImageChops, ImageDraw
import pytest

from app.execution.decision_check import decision_frame
from app.judgment.evidence import prepare_request
from app.judgment.executed_click_annotation import (
    executed_click_reference, executed_click_metadata, render_executed_click_annotation,
)


IDENTITY = {"handle": 11, "process_id": 22, "process_create_time": 33.0}
CONDITION = "The requested current document text is visible and the File menu is closed."


def canonical(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


@pytest.fixture
def saved_click(tmp_path):
    # 脱敏最小回执保留真实 Save 原件的层级、坐标、窗口几何与派发阶段。
    image = Image.new("RGB", (1065, 976), "white")
    ImageDraw.Draw(image).text((4, 25), "Release 0.1.2 round two: changed text saved in the same window.", fill="black")
    path = tmp_path / "after.png"
    image.save(path)
    capture = {"capture_id": "original-after", "image_path": str(path),
        "sha256": sha256(path.read_bytes()).hexdigest(), "image_size": {"width": 1065, "height": 976},
        "window_rect": [779, 250, 1844, 1226], "window_identity": deepcopy(IDENTITY),
        "frame_id": "after_settled", "observation_stage": "after_render_wait", "render_completion_verified": False}
    point, screen = {"x": 51, "y": 98}, {"x": 830, "y": 348}
    down = {"button": "left", "state": "down", "cursor": deepcopy(screen)}
    up = {"button": "left", "state": "up", "cursor": deepcopy(screen)}
    click = {"clicked": True, "input_backend": "SendInput", "window_point": point, "screen_point": screen,
        "window_handle": IDENTITY["handle"], "button": "left", "click_count": 1, "down": down, "up": up,
        "click_events": [{"index": 1, "down": deepcopy(down), "up": deepcopy(up), "hold_ms": 70, "gap_before_ms": 0}]}
    receipt = {"contract_version": "local_direct_step_v1", "operation": "execute_recognition_plan",
        "phase": "returned", "local_input_scope_closed": True, "finished_at": "2026-10-13T00:14:26Z",
        "target_identity": {"target_window_handle": IDENTITY["handle"], "process_id": IDENTITY["process_id"],
            "process_create_time": IDENTITY["process_create_time"]},
        "target_window_geometry": {"coordinate_space": "screen_pixels", "rect_format": "ltrb",
            "rect": [779, 250, 1844, 1226]},
        "request": {"click_kind": "single"},
        "response": {"success": True, "data": {"result": {
            "execution_path": {"action_executed": True}, "click_result": click}}},
        "observation": {"status": "captured", "source": "post_action", "capture": deepcopy(capture)}}
    command = {"kind": "step", "operation": "execute_recognition_plan", "request": {"click_kind": "single"}}
    effective = {"status": "returned", "command": command, "result": receipt, "observation": deepcopy(capture)}
    step = {"step_id": "save", "action": {"kind": "click", "click_kind": "single"}}
    frame = decision_frame(capture, IDENTITY, role="after")
    field = {"click_point": point, "window_identity": deepcopy(IDENTITY), "window_rect": [779, 250, 1065, 976]}
    reference = executed_click_reference(receipt, field)
    action = {"operation": "step_result_check", "kind": "click",
        "input_receipt_sha256": reference["receipt_sha256"], "executed_click": reference}
    return {"receipt": receipt, "effective": effective, "step": step, "frame": frame, "action": action,
        "capture": capture, "bytes": path.read_bytes()}


def arguments(value):
    return {"request_id": "current-result", "execution_request_id": "original-execution",
        "condition": CONDITION, "frames": [deepcopy(value["frame"])], "phase": "after_action",
        "action": deepcopy(value["action"]), "review_context": {
            "goal": "Inspect current result", "step_goal": "Save", "remaining_plan": [], "allowed_states": []}}


def test_generic_prepare_and_renderer_keep_full_frame_and_body_text(saved_click, tmp_path):
    before = deepcopy(saved_click)
    binding, uploads = prepare_request(tmp_path, **arguments(saved_click))
    assert len(uploads) == 1 and binding["action"] == saved_click["action"]
    meta = uploads[0]["executed_click_annotation"]["metadata"]
    assert meta["schema"] == "decision_executed_click_annotation.v3"
    assert set(meta) == {"schema", "capture_id", "source_sha256", "role", "viewport_size", "executed_click"}
    marked = render_executed_click_annotation(saved_click["bytes"], meta)
    with Image.open(BytesIO(saved_click["bytes"])) as original, Image.open(BytesIO(marked)) as annotated:
        assert original.size == annotated.size == (1065, 976)
        original, annotated = original.convert("RGB"), annotated.convert("RGB")
        assert annotated.getpixel((51, 98)) == original.getpixel((51, 98))
        assert annotated.crop((0, 0, 1065, 45)).tobytes() == original.crop((0, 0, 1065, 45)).tobytes()
        left, top, right, bottom = ImageChops.difference(original, annotated).getbbox()
        assert 38 <= left < right <= 65 and 85 <= top < bottom <= 112
    assert saved_click == before


def test_helper_projects_exact_real_receipt_without_mutation(saved_click):
    from app.execution.task_result_annotation import task_result_click_action
    before = deepcopy(saved_click)
    result = task_result_click_action(saved_click["step"], saved_click["effective"], saved_click["frame"])
    assert result == saved_click["action"]
    assert result["input_receipt_sha256"] == canonical(saved_click["receipt"])
    assert "field" not in result and "bbox" not in result
    assert saved_click == before


@pytest.mark.parametrize("tamper_frame", [False, True])
def test_helper_derives_missing_original_capture_id_without_changing_receipt(saved_click, tamper_frame):
    from app.execution.task_result_annotation import task_result_click_action
    capture = saved_click["receipt"]["observation"]["capture"]
    capture.pop("capture_id")
    saved_click["effective"]["observation"].pop("capture_id")
    frame = decision_frame(capture, IDENTITY, role="after")
    assert frame["capture_id"].startswith("capture-")
    if tamper_frame:
        frame["capture_id"] = "capture-unrelated"
    before = deepcopy(saved_click)
    if tamper_frame:
        with pytest.raises(ValueError):
            task_result_click_action(saved_click["step"], saved_click["effective"], frame)
    else:
        result = task_result_click_action(saved_click["step"], saved_click["effective"], frame)
        assert result["input_receipt_sha256"] == canonical(saved_click["receipt"])
        assert result["executed_click"]["receipt_sha256"] == result["input_receipt_sha256"]
    assert saved_click == before


@pytest.mark.parametrize("case", ["phase", "scope", "finished", "success", "executed", "clicked", "screen",
    "down", "up", "event", "handle", "identity", "geometry", "after_geometry", "after_sha", "after_path", "frame_identity",
    "post_source", "request_kind", "right", "count"])
def test_helper_rejects_tampered_physical_or_post_frame_binding(saved_click, case):
    from app.execution.task_result_annotation import task_result_click_action
    receipt = saved_click["receipt"]
    click = receipt["response"]["data"]["result"]["click_result"]
    capture = receipt["observation"]["capture"]
    if case == "phase": receipt["phase"] = "failed"
    elif case == "scope": receipt["local_input_scope_closed"] = False
    elif case == "finished": receipt["finished_at"] = None
    elif case == "success": receipt["response"]["success"] = False
    elif case == "executed": receipt["response"]["data"]["result"]["execution_path"]["action_executed"] = False
    elif case == "clicked": click["clicked"] = False
    elif case == "screen": click["screen_point"]["x"] += 1
    elif case == "down": click["down"]["cursor"]["x"] += 1
    elif case == "up": click["up"]["cursor"]["y"] += 1
    elif case == "event": click["click_events"][0]["up"]["cursor"]["x"] += 1
    elif case == "handle": click["window_handle"] += 1
    elif case == "identity": receipt["target_identity"]["process_create_time"] += 1
    elif case == "geometry": receipt["target_window_geometry"]["rect"][0] += 1
    elif case == "after_geometry": capture["window_rect"][0] += 1
    elif case == "after_sha": capture["sha256"] = "a" * 64
    elif case == "after_path": capture["image_path"] += ".other"
    elif case == "frame_identity": saved_click["frame"]["window_identity"]["process_id"] += 1
    elif case == "post_source": receipt["observation"]["source"] = "pre_action"
    elif case == "request_kind": receipt["request"]["click_kind"] = "double"
    elif case == "right": click["button"] = "right"
    elif case == "count": click["click_count"] = 2
    with pytest.raises(ValueError):
        task_result_click_action(saved_click["step"], saved_click["effective"], saved_click["frame"])


@pytest.mark.parametrize("case", ["read", "input", "double", "key", "legacy", "legacy_no_coordinates"])
def test_other_genuine_routes_do_not_get_synthetic_click_mark(saved_click, case):
    from app.execution.task_result_annotation import task_result_click_action
    if case in {"read", "input"}:
        saved_click["step"]["action"]["kind"] = "read_text" if case == "read" else "input_sequence"
    elif case == "double": saved_click["step"]["action"]["click_kind"] = "double"
    elif case == "key": saved_click["effective"]["command"]["operation"] = "press_key"
    elif case == "legacy": saved_click["receipt"].pop("contract_version")
    else:
        click = saved_click["receipt"]["response"]["data"]["result"]["click_result"]
        for key in ("window_point", "screen_point", "down", "up", "click_events"):
            click.pop(key)
    assert task_result_click_action(saved_click["step"], saved_click["effective"], saved_click["frame"]) is None


@pytest.mark.parametrize("case", ["receipt_sha", "identity", "size", "before", "bbox", "field", "scope"])
def test_generic_metadata_rejects_mixed_or_tampered_contract(saved_click, case):
    action, frame, size = deepcopy(saved_click["action"]), deepcopy(saved_click["frame"]), (1065, 976)
    if case == "receipt_sha": action["input_receipt_sha256"] = "a" * 64
    elif case == "identity": frame["window_identity"]["process_id"] += 1
    elif case == "size": size = (1064, 976)
    elif case == "before": frame["role"] = "before"
    elif case == "bbox": action["bbox"] = {"x": 2, "y": 87, "w": 232, "h": 23}
    elif case == "field": action["field"] = {}
    elif case == "scope": action["field_image_scope"] = {"schema": "visual_field_roi.v1", "padding": 16}
    with pytest.raises(ValueError):
        executed_click_metadata(frame, size, action)


def test_binding_compatibility_reads_old_evidence_without_adding_or_reauthorizing(saved_click):
    from app.execution.task_result_annotation import task_result_decision_binding
    base = arguments(saved_click)
    action = base.pop("action")
    assert task_result_decision_binding(base, action) == {**base, "action": action}
    for old in (base, {**base, "action": None}):
        assert task_result_decision_binding(base, action, saved_binding=old) == old
        assert "executed_click" not in (old.get("action") or {})
    current = {**base, "action": action}
    assert task_result_decision_binding(base, action, saved_binding=current) == current
    for tampered in ({**base, "condition": "different"}, {**current, "action": {**action, "input_receipt_sha256": "a"*64}}):
        with pytest.raises(ValueError, match="task_plan_decision_binding_changed"):
            task_result_decision_binding(base, action, saved_binding=tampered)


def test_real_offline_service_uploads_one_marked_current_frame_and_authenticates(saved_click, tmp_path, monkeypatch):
    from tests.test_decision_choice import runtime
    args = arguments(saved_click)
    service, calls, client = runtime(tmp_path, monkeypatch, profile={"auto_conditions": [CONDITION]})
    try:
        result = service.evaluate(**args)
        assert result["status"] == "completed" and len(calls) == 1
        body = json.loads(calls[0].content)
        images = [p["image_url"] for p in body["input"][0]["content"] if p["type"] == "input_image"]
        assert len(images) == 1 and base64.b64decode(images[0].split(",", 1)[1]) != saved_click["bytes"]
        with Image.open(BytesIO(base64.b64decode(images[0].split(",", 1)[1]))) as marked:
            assert marked.size == (1065, 976)
        assert result["executed_click_annotations"][0]["schema"] == "decision_executed_click_annotation.v3"
        assert service.validate_result(result, **args)
        changed = deepcopy(result)
        changed["executed_click_annotations"][0]["source_sha256"] = "a" * 64
        assert not service.validate_result(changed, **args)
        assert service.evaluate(**args) == result and len(calls) == 1
    finally:
        service.close()
        client.close()


def test_task_plan_verified_single_click_passes_exact_raw_result_to_annotation(saved_click, tmp_path, monkeypatch):
    from app.core.json_snapshot import write_json_snapshot, read_json_snapshot
    from tests.test_task_plan_adaptive_review import adaptive_plan, OfflineAssessment
    from tests.test_task_plan_runner import scene, complete_original
    service = OfflineAssessment(disposition="continue")
    s = scene(tmp_path, monkeypatch, source=adaptive_plan(count=1), decision=service)
    original = complete_original(s, native=False)
    response = deepcopy(original.receipt)
    response["result"] = deepcopy(saved_click["receipt"])
    response["result"]["capture"] = deepcopy(original.result["capture"])
    response["observation"] = deepcopy(saved_click["capture"])
    write_json_snapshot(tmp_path / "responses" / (original.command_id + ".json"), response)
    final = s.runtime.tick(force=True)
    assert final["runner_state"] == "completed" and len(service.calls) == 1
    actual = service.calls[0]["action"]
    assert actual["operation"] == "step_result_check"
    assert actual["input_receipt_sha256"] == canonical(response["result"])
    assert actual["executed_click"] == {**saved_click["action"]["executed_click"],
        "receipt_sha256": canonical(response["result"])}
    assert read_json_snapshot(tmp_path / "responses" / (original.command_id + ".json")) == response


@pytest.mark.parametrize("explicit_null", [False, True])
def test_task_plan_cached_legacy_binding_is_authenticated_as_original_without_new_dispatch(
        saved_click, tmp_path, monkeypatch, explicit_null):
    from app.core.json_snapshot import write_json_snapshot, read_json_snapshot
    from app.execution.task_plan_review import review_context
    from app.execution.task_plan_conditions import semantic_binding
    from tests.test_task_plan_adaptive_review import adaptive_plan, OfflineAssessment
    from tests.test_task_plan_runner import scene, complete_original
    service = OfflineAssessment(disposition="continue")
    s = scene(tmp_path, monkeypatch, source=adaptive_plan(count=1), decision=service)
    original = complete_original(s, native=False)
    response = deepcopy(original.receipt)
    response["result"] = deepcopy(saved_click["receipt"])
    response["result"]["capture"] = deepcopy(original.result["capture"])
    response["observation"] = deepcopy(saved_click["capture"])
    write_json_snapshot(tmp_path / "responses" / (original.command_id + ".json"), response)
    state = s.runtime.backend.status(s.run_id)
    step = s.runtime.backend.pinned_step(s.run_id, state["pending"]["step_id"])
    source = s.runtime.backend._source(state)
    binding = {"request_id": "task-decision-" + sha256(original.command_id.encode()).hexdigest()[:32],
        "execution_request_id": original.command_id, **semantic_binding(source["plan"], step),
        "frames": [saved_click["frame"]], "mode": "execution", "phase": "after_action",
        "run_id": s.run_id, "step_id": step["step_id"],
        "review_context": review_context(source["plan"], step,
            source_id=state["plan_id"], source_sha256=state["plan_sha256"])}
    if explicit_null:
        binding["action"] = None
    saved = {"binding": deepcopy(binding), "result": service.evaluate(**binding),
        "policy_snapshot": service.status(), "validated": True}
    path = tmp_path / "task-plan-decisions" / (original.command_id + ".json")
    path.parent.mkdir()
    write_json_snapshot(path, saved)
    old_bytes = path.read_bytes()
    assert s.runtime.tick(force=True)["runner_state"] == "completed"
    assert len(service.calls) == 1 and service.calls[0] == binding
    assert path.read_bytes() == old_bytes and read_json_snapshot(path) == saved


@pytest.mark.parametrize("case", ["missing_mark", "before", "temporal"])
def test_generic_request_cannot_silently_upload_an_unmarked_or_wrong_phase_frame(saved_click, tmp_path, case):
    args = arguments(saved_click)
    if case == "missing_mark":
        args["action"].pop("executed_click")
    elif case == "before":
        args["phase"] = "before_action"
        args["frames"][0]["role"] = "before"
    else:
        args["temporal_context"] = {}
    with pytest.raises(ValueError, match="decision_step_result_annotation_required"):
        prepare_request(tmp_path, **args)
