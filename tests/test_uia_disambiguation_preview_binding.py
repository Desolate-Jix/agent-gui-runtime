"""同名 UIA 消歧证据必须原样穿过公共投影及新鲜预览绑定。"""

from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest

from app.agent.fresh_learning_action_contracts import canonical_json_bytes
from app.agent.fresh_learning_action_preview import build_fresh_learning_action_preview
from app.agent.fresh_learning_observation import FreshLearningActionObservation, FreshLearningObservationPacket
from tests.test_fresh_learning_action_preview import _preview, _recognize, _setup


def _current_point_recognition(**kwargs):
    value = _recognize(**kwargs)
    candidate = value["candidate_result"]["candidates"][0]
    candidate["element"]["evidence"]["current_uia_point_disambiguation"] = {
        "source": "current_screenshot_vista_point_and_uia_bbox_v1",
        "screenshot_sha256": sha256(Path(kwargs["image_path"]).read_bytes()).hexdigest(),
        "point": {"x": 60, "y": 30},
        "selected_control_id": "fresh.detail",
        "excluded_control_ids": ["background.detail"],
        "matching_control_count": 2,
    }
    return value


def test_fresh_preview_keeps_current_point_image_digest_without_private_path(tmp_path):
    preview, *_ = _preview(tmp_path, runner=_current_point_recognition)
    data = preview.to_dict()
    observation = data["observation_evidence"]
    candidate = observation["recognition"]["result"]["candidate_result"]["candidates"][0]
    current = candidate["element"]["evidence"]["current_uia_point_disambiguation"]
    assert current["screenshot_sha256"] == observation["capture"]["screenshot_sha256"]
    assert current["point"] == data["pre_click_decision"]["selected_click_point"]
    assert "image_path" not in current
    assert data["pre_click_decision"]["allowed"] is True
    assert data["action_executed"] is False


def test_private_path_reintroduced_into_candidate_still_fails_binding(tmp_path):
    def recognize(**kwargs):
        value = _current_point_recognition(**kwargs)
        value["candidate_result"]["candidates"][0]["element"]["evidence"]["current_uia_point_disambiguation"]["image_path"] = kwargs["image_path"]
        return value

    with pytest.raises(ValueError, match="original recognition binding mismatch"):
        _preview(tmp_path, runner=recognize)


@pytest.mark.parametrize("key,value", [
    ("point", {"x": 61, "y": 30}),
    ("selected_control_id", "background.detail"),
    ("screenshot_sha256", "0" * 64),
    ("excluded_control_ids", []),
])
def test_projected_current_point_evidence_cannot_be_tampered(tmp_path, key, value):
    host, owner, runtime, _backend, _claims, source, session, intent = _setup(
        tmp_path, runner=_current_point_recognition)
    try:
        bundle = owner.observe_for_action(target_window_handle=4242, target_process_id=9001, goal=intent.goal)
        reference = source.reference()
        capture_source = host.fresh_learning.archive.record(
            bundle.packet, **{key: reference[key] for key in ("connection_id", "task_id", "segment_id")})
        projected = bundle.packet.evidence()
        candidate = projected["recognition"]["result"]["candidate_result"]["candidates"][0]
        candidate["element"]["evidence"]["current_uia_point_disambiguation"][key] = deepcopy(value)
        tampered = FreshLearningActionObservation(
            packet=FreshLearningObservationPacket(bundle.packet.png_bytes, canonical_json_bytes(projected)),
            recognition_json=bundle.recognition_json, uia_snapshot_json=bundle.uia_snapshot_json)
        with pytest.raises(ValueError, match="original recognition binding mismatch"):
            build_fresh_learning_action_preview(
                bundle=tampered, capture_source=capture_source, observation=session.current_observation.to_dict(),
                intent=intent, source_reference=reference)
    finally:
        runtime.abandon_session(session_id=session.session_id)
        host.close()
