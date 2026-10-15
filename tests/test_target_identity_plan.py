"""目标身份声明必须冻结于计划及候选审核，不从候选标签猜测。"""
from copy import deepcopy
from hashlib import sha256
from time import perf_counter_ns

from PIL import Image
import pytest

from app.execution.action_review import build_action_review, build_freshness_review
from app.execution.task_plan_contract import validate_task_plan


def identity_spec():
    return {"schema": "target_identity.v1", "choices": [
        {"value": "i0", "description": "搜索输入框"},
        {"value": "i1", "description": "搜索结果链接"}], "expected": "i0"}


def plan(kind="click", version="task_plan.v3"):
    action = ({"kind": "click", "goal": "Search field"} if kind == "click" else
        {"kind": "input_sequence", "field_goal": "Search field", "text": "fresh query",
            "clear_existing": True, "submit_search": False} if kind == "input_sequence" else
        {"kind": "read_text", "goal": "Read results"})
    action["target_identity"] = identity_spec()
    step = {"step_id": "search", "action": action,
        "verification": {"kind": "agent_judgment"}}
    result = {"schema_version": version, "title": "Search documentation", "inputs": {}, "steps": [step]}
    if version == "task_plan.v3":
        result.update(goal="Documentation is visible", completion={"step_id": "search",
            "verification": {"kind": "agent_judgment", "decision_condition": "Documentation is visible"}})
    return result


def review_args(tmp_path, *, kind="click"):
    path = tmp_path / "target.png"
    Image.new("RGB", (200, 150), "white").save(path)
    window = {"handle": 10, "process_id": 20, "process_create_time": 30.0}
    source = plan(kind)
    return {"scope": "candidate", "plan": source, "step": source["steps"][0],
        "run_id": "identity-run", "attempt_id": "identity-attempt",
        "capture": {"image_path": str(path), "capture_id": "current-capture",
            "sha256": sha256(path.read_bytes()).hexdigest(), "window_identity": window,
            "window_size": {"width": 200, "height": 150}}, "identity": window,
        "candidate": {"candidate_id": "candidate-1", "capture_id": "current-capture",
            "source": "external_api", "text": "Label is not an independent identity",
            "bbox": {"x": 10, "y": 10, "w": 100, "h": 20}, "click_point": {"x": 20, "y": 20}},
        "action": {"operation": "execute_recognition_plan", "goal": "Search field", "click_kind": "single"},
        "profile_sha256": "a" * 64, "deadline_ns": perf_counter_ns() + 5_000_000_000}


@pytest.mark.parametrize("kind", ["click", "input_sequence"])
def test_v3_action_freezes_explicit_identity_choices(kind):
    source = plan(kind)
    frozen = validate_task_plan(source)
    source["steps"][0]["action"]["target_identity"]["choices"][0]["description"] = "changed"
    assert frozen["steps"][0]["action"]["target_identity"] == identity_spec()


@pytest.mark.parametrize("version", ["task_plan.v1", "task_plan.v2"])
def test_legacy_plan_cannot_declare_unevaluated_identity(version):
    with pytest.raises(ValueError, match="target_identity"):
        validate_task_plan(plan(version=version))


def test_read_text_cannot_declare_target_identity():
    with pytest.raises(ValueError, match="target_identity"):
        validate_task_plan(plan("read_text"))


@pytest.mark.parametrize("change", ["one_choice", "expected_missing", "reserved_choice", "observed_result"])
def test_invalid_identity_contract_is_rejected(change):
    source = plan()
    spec = source["steps"][0]["action"]["target_identity"]
    if change == "one_choice":
        spec["choices"].pop()
    elif change == "expected_missing":
        spec["expected"] = "missing"
    elif change == "reserved_choice":
        spec["choices"][1]["value"] = "unknown"
    else:
        spec["identity_result"] = {"choice": "i0"}
    with pytest.raises(ValueError, match="target_identity"):
        validate_task_plan(source)


@pytest.mark.parametrize("kind", ["click", "input_sequence"])
def test_candidate_envelope_copies_plan_identity_without_candidate_label(tmp_path, kind):
    args = review_args(tmp_path, kind=kind)
    envelope = build_action_review(**args)
    args["step"]["action"]["target_identity"]["expected"] = "i1"
    assert envelope["action"]["target_identity"] == identity_spec()
    assert envelope["action"]["target_identity"]["choices"] == [
        {"value": "i0", "description": "搜索输入框"},
        {"value": "i1", "description": "搜索结果链接"}]
    assert "target_identity" not in args["action"]


@pytest.mark.parametrize("change", ["different_expected", "unbound_action"])
def test_runtime_action_cannot_replace_frozen_plan_identity(tmp_path, change):
    args = review_args(tmp_path)
    args["action"]["target_identity"] = identity_spec()
    if change == "different_expected":
        args["action"]["target_identity"]["expected"] = "i1"
    else:
        del args["step"]["action"]["target_identity"]
    with pytest.raises(ValueError, match="target_identity.*conflict"):
        build_action_review(**args)


def test_same_explicit_identity_can_be_rebuilt_without_aliasing(tmp_path):
    args = review_args(tmp_path)
    args["action"]["target_identity"] = identity_spec()
    envelope = build_action_review(**args)
    rebuilt = build_action_review(**{**args, "action": envelope["action"]})
    assert rebuilt == envelope
    args["action"]["target_identity"]["expected"] = "i1"
    assert envelope["action"]["target_identity"]["expected"] == "i0"


def test_scene_review_never_carries_candidate_identity(tmp_path):
    args = review_args(tmp_path)
    args.update(scope="scene", candidate=None)
    args["action"]["target_identity"] = identity_spec()
    envelope = build_action_review(**args)
    assert "target_identity" not in envelope["action"]
    assert args["action"]["target_identity"] == identity_spec()


def test_identity_declaration_changes_candidate_binding(tmp_path):
    args = review_args(tmp_path)
    original = build_action_review(**args)
    args["step"]["action"]["target_identity"]["expected"] = "i1"
    changed = build_action_review(**args)
    assert original["action"]["target_identity"]["expected"] == "i0"
    assert changed["action"]["target_identity"]["expected"] == "i1"
    assert original["envelope_sha256"] != changed["envelope_sha256"]


def test_freshness_review_does_not_reuse_prior_identity_as_observation(tmp_path):
    args = review_args(tmp_path)
    envelope = build_action_review(**args)
    original = deepcopy(envelope)
    fresh = build_freshness_review(envelope, current_frame={**envelope["frame"], "capture_id": "fresh-capture"},
        changed_region={"x": 12, "y": 12, "w": 2, "h": 10})
    assert "target_identity" not in fresh["action"]
    assert fresh["frame"]["capture_id"] == "fresh-capture"
    assert fresh["prior_frame"] == original["frame"]
    assert envelope == original
    assert envelope["action"]["target_identity"] == identity_spec()


def test_action_without_identity_keeps_legacy_envelope_shape(tmp_path):
    args = review_args(tmp_path)
    del args["step"]["action"]["target_identity"]
    envelope = build_action_review(**args)
    assert envelope["action"] == args["action"]
    assert "target_identity" not in envelope["action"]
