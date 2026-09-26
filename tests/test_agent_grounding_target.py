"""外部候选通过当前截图复核进入同一动作计划，不直接调用输入后端。"""
from copy import deepcopy
from hashlib import sha256
import time

from PIL import Image, ImageDraw
import pytest

from app.core.agent_grounding_target import (
    AgentGroundingTarget, agent_grounding_scope, current_agent_grounding,
)
from app.core.local_recognition_policy import local_recognition_selection


@pytest.fixture
def scene(tmp_path):
    image = tmp_path / "reference.png"
    im = Image.new("RGB", (200, 150), "white")
    ImageDraw.Draw(im).rectangle((30, 40, 100, 70), fill="blue")
    im.save(image)
    state = {"request_id": "g-1", "phase": "executing", "goal": "Search",
        "expires_at": time.time()+180,
        "configuration": {"source": "agent_current"},
        "capture": {"capture_id": "cap-1", "image_path": str(image),
            "sha256": sha256(image.read_bytes()).hexdigest(),
            "image_size": {"width": 200, "height": 150},
            "window_identity": {"handle": 10, "process_id": 20, "process_create_time": 30.0}},
        "result": {"schema_version": "grounding.v1", "request_id": "g-1", "capture_id": "cap-1",
            "coordinate_space": "capture_image_pixels", "image_size": {"width": 200, "height": 150},
            "status": "found", "selected_candidate_id": "button", "candidates": [{"id": "button",
            "label": "Search", "bbox": {"x": 30, "y": 40, "width": 71, "height": 31},
            "click_point": {"x": 65, "y": 55}, "evidence_source": "agent_visual"}]}}
    identity = {"target_window_handle": 10, "process_id": 20, "process_create_time": 30.0}
    return state, identity, im, tmp_path


def plan(scene, image=None, identity=None):
    state, original_identity, _, _ = scene
    target = AgentGroundingTarget(state)
    result = target.plan(image_path=image or state["capture"]["image_path"], goal="Search",
                         identity=identity or original_identity)
    return target, result


def test_adapter_plan_is_consumable_by_existing_geometry_selector(scene):
    target, result = plan(scene)
    selected = local_recognition_selection(result, image_path=result["image_path"],
                                           viewport_size={"width": 200, "height": 150})
    assert selected["selected_click_point"] == {"x": 65, "y": 55}
    assert selected["candidate_decisions"][0]["coordinate_source"] == "agent_visual"
    assert result["execution_path"]["local_model_used"] is False
    assert result["grounding_evidence"]["task_effect_verified"] is None


def test_changes_outside_target_patch_do_not_require_whole_screen_hash_match(scene):
    state, identity, im, root = scene
    ImageDraw.Draw(im).rectangle((160, 100, 199, 149), fill="black")
    current = root / "current.png"
    im.save(current)
    _, result = plan(scene, str(current))
    assert result["grounding_evidence"]["region_changed_fraction"] == 0
    assert result["image_path"] == str(current)


def test_changed_target_rejects_stale_coordinate(scene):
    state, identity, im, root = scene
    ImageDraw.Draw(im).rectangle((30, 40, 100, 70), fill="red")
    current = root / "current.png"
    im.save(current)
    with pytest.raises(ValueError, match="target_region_changed"):
        plan(scene, str(current))


@pytest.mark.parametrize("defect", ["pid", "birth", "size", "goal", "expired", "source_hash"])
def test_target_rejects_changed_binding_or_source(scene, defect):
    state, identity, im, root = scene
    kwargs = {"image_path": state["capture"]["image_path"], "goal": "Search", "identity": identity}
    if defect == "pid": identity["process_id"] += 1
    elif defect == "birth": identity["process_create_time"] += 1
    elif defect == "size":
        current = root / "small.png"
        im.resize((100, 75)).save(current)
        kwargs["image_path"] = str(current)
    elif defect == "goal": kwargs["goal"] = "Cancel"
    elif defect == "expired": state["expires_at"] = time.time()-1
    else: state["capture"]["sha256"] = "0"*64
    with pytest.raises(ValueError):
        AgentGroundingTarget(state).plan(**kwargs)


def test_scope_revokes_copied_context_and_double_dispatch(scene):
    from contextvars import copy_context
    target, result = plan(scene)
    with agent_grounding_scope(target):
        copied = copy_context()
        assert current_agent_grounding() is target
        target.before_dispatch({"x": 65, "y": 55}, scene[1])
        with pytest.raises(ValueError, match="already_claimed"):
            target.before_dispatch({"x": 65, "y": 55}, scene[1])
    assert current_agent_grounding() is None
    with pytest.raises(ValueError, match="scope_revoked"):
        copied.run(current_agent_grounding)


def test_dispatch_requires_built_plan_and_same_identity_point(scene):
    target = AgentGroundingTarget(scene[0])
    with pytest.raises(ValueError, match="plan_required"):
        target.before_dispatch({"x": 65, "y": 55}, scene[1])
    target, _ = plan(scene)
    with pytest.raises(ValueError, match="point_mismatch"):
        target.before_dispatch({"x": 66, "y": 55}, scene[1])


def test_target_freezes_model_result_against_caller_mutation(scene):
    state = scene[0]
    target = AgentGroundingTarget(state)
    state["result"]["candidates"][0]["click_point"]["x"] = 80
    result = target.plan(image_path=state["capture"]["image_path"], goal="Search", identity=scene[1])
    assert result["pre_click_decision"]["selected_click_point"] == {"x": 65, "y": 55}
