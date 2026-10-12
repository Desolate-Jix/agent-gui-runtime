"""指定动态内容复用三图驱动；目标与一次判断均严格绑定。"""
import pytest

from app.execution.task_plan_contract import validate_task_plan
from app.execution import video_playback_verification as module
from tests.test_task_plan_adaptive_review import OfflineAssessment, review_request
from tests.test_task_plan_video_playback import video_plan
from tests.test_video_picture_change_runtime import picture_scene, capture_three


TARGET = "The seconds digits of the clock in the main content area."
CONDITION = "The specified clock digits visibly change across the three screenshots."


def dynamic_plan(*, always_main=False):
    plan = video_plan(always_main=always_main)
    plan["steps"][0]["verification"].update(kind="dynamic_content", target_description=TARGET,
        decision_condition=CONDITION)
    return plan


@pytest.mark.parametrize("action", ["click", "submit"])
def test_dynamic_contract_accepts_only_explicit_target_and_supported_input(action):
    plan = dynamic_plan()
    if action == "submit":
        plan["steps"][0]["action"] = {"kind": "input_sequence", "field_goal": "Address", "text": "example",
            "clear_existing": True, "submit_search": True}
    plan["steps"][0]["verification"].update(allowed_states=["The clock is static."], render_grace_ms=0)
    assert validate_task_plan(plan) == plan


@pytest.mark.parametrize("length", [1, 1000])
def test_dynamic_target_length_boundaries(length):
    plan = dynamic_plan()
    plan["steps"][0]["verification"]["target_description"] = "x" * length
    assert validate_task_plan(plan) == plan


@pytest.mark.parametrize("damage", ["missing_target", "empty", "whitespace", "long", "number", "boolean", "null",
    "missing_condition", "empty_condition", "wait_policy", "condition_binding", "extra", "adaptive", "bad_states",
    "render_bool", "render_large", "v1", "read_text", "non_submit"])
def test_dynamic_contract_rejects_implicit_target_authority_and_waits(damage):
    plan = dynamic_plan()
    rule, step = plan["steps"][0]["verification"], plan["steps"][0]
    targets = {"empty": "", "whitespace": " \t", "long": "x" * 1001, "number": 2, "boolean": True, "null": None}
    if damage in targets:
        rule["target_description"] = targets[damage]
    elif damage == "missing_target":
        rule.pop("target_description")
    elif damage == "missing_condition":
        rule.pop("decision_condition")
    elif damage == "empty_condition":
        rule["decision_condition"] = ""
    elif damage == "wait_policy":
        rule["wait_policy"] = {"loading_condition": "Loading", "completion_excludes_loading": True}
    elif damage == "condition_binding":
        rule["condition_binding"] = {}
    elif damage == "extra":
        rule["allow_local_success"] = True
    elif damage == "adaptive":
        rule["review_policy"] = "adaptive"
    elif damage == "bad_states":
        rule["allowed_states"] = [""]
    elif damage == "render_bool":
        rule["render_grace_ms"] = True
    elif damage == "render_large":
        rule["render_grace_ms"] = 2001
    elif damage == "v1":
        plan["schema_version"] = "task_plan.v1"
    elif damage == "read_text":
        step["action"] = {"kind": "read_text", "goal": "Clock"}
    else:
        step["action"] = {"kind": "input_sequence", "field_goal": "Address", "text": "example",
            "clear_existing": True, "submit_search": False}
    with pytest.raises(ValueError):
        validate_task_plan(plan)


def test_dynamic_target_is_bound_to_three_frames_and_one_authenticated_decision(tmp_path, monkeypatch):
    service = OfflineAssessment(disposition="continue")
    s, original, clock, calls = picture_scene(tmp_path, monkeypatch, service=service, source=dynamic_plan())
    def forbidden(*args, **kwargs):
        pytest.fail("通用路径不得定位、OCR或本地比较")
    for name in ("locate_player", "observe_player_frame", "observation_evidence_refs", "page_loading", "_analysis"):
        monkeypatch.setattr(module, name, forbidden)
    result = capture_three(s, clock)
    assert result["status"] == "completed" and result["history"][0]["judged_by"] == "decision"
    assert len(calls.capture) == 3 and len(service.calls) == 1
    assert len(list(tmp_path.glob("commands/*.json"))) == 1
    binding = service.calls[0]
    temporal = binding["temporal_context"]
    assert set(temporal) == {"schema", "original_after", "samples", "selected_capture_ids", "timeout_seconds", "target_description"}
    assert temporal["schema"] == "temporal_visual_change.v1" and temporal["target_description"] == TARGET
    assert temporal["original_after"] == binding["frames"][0]
    assert temporal["original_after"]["sha256"] == original.capture["sha256"]
    assert [item["elapsed_ms"] for item in temporal["samples"]] == [1000, 1500, 2000]
    assert temporal["selected_capture_ids"] == [item["frame"]["capture_id"] for item in temporal["samples"]]
    ledger = module.VideoPlaybackLedger(s.runtime.backend, original.command_id)
    assert ledger.header()["analysis_policy"] == "dynamic_content_change.v1"
    assert ledger.summary()["schema"] == "dynamic_content_binding.v1"
    assert ledger.summary()["analysis"] is None and ledger.summary()["region"] is None
    assert ledger.summary()["readiness_observations"] == [] and module._outcome(ledger)["local_success"] is False


@pytest.mark.parametrize("gate", ["unconfigured", "always_main", "shadow", "negative"])
def test_dynamic_review_modes_keep_three_original_images_without_retry(tmp_path, monkeypatch, gate):
    service = None if gate == "unconfigured" else OfflineAssessment(
        disposition="continue" if gate == "shadow" else "review_required")
    if gate == "shadow":
        status = service.status
        monkeypatch.setattr(service, "status", lambda: {**status(), "adoption_mode": "shadow"})
    s, original, clock, calls = picture_scene(tmp_path, monkeypatch, service=service,
        source=dynamic_plan(always_main=gate == "always_main"))
    result = capture_three(s, clock)
    assert result["review_required"] is True and result["history"] == [] and len(calls.capture) == 3
    assert result["review_packet"]["video_playback"]["schema"] == "dynamic_content_binding.v1"
    if service:
        assert len(service.calls) == (0 if gate == "always_main" else 1)
    assert s.runtime.tick(force=True) is None
    reviewed = s.runtime.control(review_request(s, result, original), "dynamic-main-review")
    assert reviewed["status"] == "completed" and len(calls.capture) == 3


@pytest.mark.parametrize("damage", ["target", "schema", "selected", "elapsed"])
def test_dynamic_decision_cannot_change_target_or_frame_binding(tmp_path, monkeypatch, damage):
    service = OfflineAssessment(disposition="continue")
    # 绕过替身自身的参数相等检查，单独检验运行时采用绑定。
    monkeypatch.setattr(service, "validate_result", lambda *args, **kwargs: True)
    evaluate = service.evaluate
    def changed(**binding):
        result = evaluate(**binding)
        context = binding["temporal_context"]
        if damage == "target":
            context["target_description"] = "An unrelated animated icon."
        elif damage == "schema":
            context["schema"] = "temporal_playback.v2"
        elif damage == "selected":
            context["selected_capture_ids"].reverse()
        else:
            context["samples"][0]["elapsed_ms"] = 0
        return result
    monkeypatch.setattr(service, "evaluate", changed)
    s, _, clock, calls = picture_scene(tmp_path, monkeypatch, service=service, source=dynamic_plan())
    result = capture_three(s, clock)
    assert result["history"] == [] and result["wait"].get("error")
    assert len(service.calls) == 1 and len(calls.capture) == 3


def test_dynamic_unfinished_capture_keeps_existing_no_replay_guards(tmp_path, monkeypatch):
    s, original, clock, calls = picture_scene(tmp_path, monkeypatch, source=dynamic_plan())
    s.runtime.tick(force=True)
    ledger = module.VideoPlaybackLedger(s.runtime.backend, original.command_id)
    ledger.append("capture_claimed", {"index": 1, "claimed_ns": 1_000_000_000})
    clock.seconds = 1
    result = s.runtime.tick(force=True)
    assert result["review_required"] is True and "unknown" in result["review_packet"]["reason"]
    assert calls.capture == []
    assert s.runtime.tick(force=True) is None


@pytest.mark.parametrize("guard", ["budget", "window", "policy", "pixels", "cancel"])
def test_dynamic_preserves_time_identity_policy_evidence_and_cancel_guards(tmp_path, monkeypatch, guard):
    from PIL import Image
    service = OfflineAssessment(disposition="continue")
    s, original, clock, calls = picture_scene(tmp_path, monkeypatch, service=service, source=dynamic_plan())
    s.runtime.tick(force=True)
    clock.seconds = 1
    s.runtime.tick(force=True)
    if guard == "window":
        s.target["process_create_time"] += 1
    elif guard == "policy":
        status = service.status
        monkeypatch.setattr(service, "status", lambda: {**status(), "profile_sha256": "f" * 64})
    elif guard == "pixels":
        Image.new("RGB", (80, 60), "blue").save(tmp_path / "captures" / (calls.capture[0] + ".png"))
    elif guard == "cancel":
        s.runtime.control({"action": "cancel", "run_id": s.run_id}, "dynamic-cancel")
    clock.seconds = 8 if guard == "budget" else 1.5
    result = s.runtime.tick(force=True)
    assert len(calls.capture) == 1 and service.calls == []
    if guard == "cancel":
        assert result["status"] == "cancelled"
        assert result["history"][0]["execution_request_id"] == original.command_id
        assert result["history"][0]["original_input_status"] == "completed"
    elif guard in {"budget", "policy"}:
        assert result["review_required"] is True and result["history"] == []
        assert ("budget" if guard == "budget" else "profile_changed") in result["review_packet"]["reason"]
    elif guard == "window":
        assert result["review_required"] is True and result["history"] == []
        assert result["review_packet"]["reason"] == "task_plan_video_window_changed"
    else:
        assert result["history"] == [] and result["wait"].get("error")
