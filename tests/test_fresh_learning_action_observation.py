"""动作定位必须得到同一新截图的原始识别，不能把脱敏投影冒充原件。"""

import hashlib
import json

import pytest

from tests.test_formal_fresh_learning_observation import _owner, _RecognitionRunner, _ScreenshotService, _UIAProvider


def test_action_observation_retains_original_recognition_with_exact_fresh_png(tmp_path):
    runner = _RecognitionRunner(include_internal_metadata=True)
    screenshot = _ScreenshotService(tmp_path)
    owner = _owner(tmp_path, runner=runner, screenshot=screenshot)
    assert hasattr(owner, "observe_for_action"), "fresh action has no original recognition capture path"
    bundle = owner.observe_for_action(target_window_handle=4242, target_process_id=9001, goal="View job details")
    public = bundle.packet.evidence()
    original = bundle.recognition_result()
    assert bundle.packet.png_bytes == screenshot.path.read_bytes()
    assert original["image_path"] == str(screenshot.path)
    assert original["goal"] == public["recognition"]["goal"] == "View job details"
    assert "model_io" in original and "model_io" not in public["recognition"]["result"]
    assert public["recognition"]["result_is_original"] is False
    assert hashlib.sha256(bundle.recognition_json).hexdigest() == public["recognition"]["result_sha256"]
    assert public["capture"]["screenshot_sha256"] == hashlib.sha256(bundle.packet.png_bytes).hexdigest()
    assert len(runner.calls) == len(screenshot.calls) == 1
    assert screenshot.calls[0]["focus_window"] is False
    original["candidate_result"]["goal"] = "client mutation"
    assert bundle.recognition_result()["candidate_result"]["goal"] == "View job details"
    assert bundle.artifact_is_authorization is False
    assert hashlib.sha256(bundle.uia_snapshot_json).hexdigest() == public["uia"]["snapshot_sha256"]
    uia = bundle.uia_snapshot()
    uia["controls"].clear()
    assert bundle.uia_snapshot()["control_count"] == len(bundle.uia_snapshot()["controls"]) == 1


def test_actual_provider_window_local_rectangle_is_accepted_at_nonzero_screen_origin(tmp_path):
    owner = _owner(tmp_path, uia=_UIAProvider(left=0, top=0))
    packet = owner.observe(target_window_handle=4242, target_process_id=9001)
    assert packet.evidence()["target"]["rect"]["x"] == 10


def test_action_observation_requires_goal(tmp_path):
    owner = _owner(tmp_path)
    with pytest.raises(ValueError, match="goal"):
        owner.observe_for_action(target_window_handle=4242, target_process_id=9001, goal=None)


def test_action_observation_rejects_wrong_goal_and_never_returns_partial_evidence(tmp_path):
    owner = _owner(tmp_path, runner=_RecognitionRunner(malformed="goal"))
    assert hasattr(owner, "observe_for_action"), "fresh action has no original recognition capture path"
    with pytest.raises(ValueError, match="goal"):
        owner.observe_for_action(target_window_handle=4242, target_process_id=9001, goal="View job details")


def test_plain_observation_retains_existing_public_projection_contract(tmp_path):
    owner = _owner(tmp_path)
    packet = owner.observe(target_window_handle=4242, target_process_id=9001, goal="View job details")
    public = packet.evidence()
    assert public["recognition"]["result_is_original"] is False
    assert "recognition_json" not in json.dumps(public)
    assert public["artifact_is_authorization"] is False
