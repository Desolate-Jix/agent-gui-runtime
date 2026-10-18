"""动作记忆保留所选控件的实际文字，不把 Agent 意图当作可见文字。"""

from copy import deepcopy

import pytest

from app.agent.fresh_learning_action_contracts import FreshLearningIntent, payload_sha256
from app.agent.fresh_learning_recording import validate_fresh_before_shape, validate_fresh_before_source
from app.agent.reviewed_workflow_compiler import _stable_node_anchors
from tests import test_fresh_dispatch_graph as dispatch_fixtures
from tests import test_fresh_learning_action_preview as preview_fixtures


def _record(tmp_path, monkeypatch):
    recognize = preview_fixtures._recognize
    setup = dispatch_fixtures._setup

    def visible_text(**kwargs):
        result = recognize(**{**kwargs, "goal": "View details"})
        for item in (result, result["candidate_result"], result["narrow_search_result"]):
            item["goal"] = kwargs["goal"]
        return result

    def separate_goal(root):
        values = list(setup(root))
        values[-1] = FreshLearningIntent.from_dict({
            **values[-1].to_dict(), "goal": "Open the selected item details",
        })
        return tuple(values)

    monkeypatch.setattr(preview_fixtures, "_recognize", visible_text)
    monkeypatch.setattr(dispatch_fixtures, "_setup", separate_goal)
    return dispatch_fixtures._ready(tmp_path)


def test_observed_target_text_survives_recording_graph_and_authoritative_reload(tmp_path, monkeypatch):
    host, owner, runtime, backend, claims, session, scope, confirmation_id = _record(tmp_path, monkeypatch)
    try:
        receipt = runtime.consume_grounded_confirmation(confirmation_id=confirmation_id)
        assert receipt.outcome == "ACTION_RECORDED", receipt
        assert len(backend.commands) == 1
        segment = host.fresh_learning.segments.get(**scope)
        learning_id = segment["children"][0]["learning_session_id"]
        recorder = host.fresh_learning.segments.recorder
        learned = recorder.get_learning_session(learning_session_id=learning_id)
        event = next(iter(learned["events"].values()))
        before = event["before"]
        target = before.get("target_observation")
        assert target is not None, "selected target text was discarded before recording"
        assert target["text"] == "View details"
        assert target["label"] == "View details" and target["role"] == "button"
        assert target["capture_id"] == before["capture"]["capture_id"]
        assert target["screenshot_sha256"] == before["capture"]["screenshot_sha256"]
        assert before["action"] == {"action_id": "action.view", "semantic_action": "open_detail"}
        assert receipt.action.model_dump(mode="json") == before["action"]
        source, record = claims.read_committed_terminal_evidence(
            session_id=session.session_id, observation_id=session.current_observation.observation_id)
        assert source.intent.goal == "Open the selected item details"
        assert validate_fresh_before_source(before, source, record)["status"] == "verified"
        legacy = deepcopy(before)
        legacy.pop("target_observation")
        legacy["content_sha256"] = payload_sha256({
            key: value for key, value in legacy.items() if key != "content_sha256"})
        legacy_snapshot = deepcopy(legacy)
        validate_fresh_before_shape(legacy)
        assert validate_fresh_before_source(legacy, source, record)["status"] == "verified"
        assert legacy == legacy_snapshot
        corrupted = deepcopy(before)
        corrupted["target_observation"]["text"] = "Delete item"
        corrupted["content_sha256"] = payload_sha256({
            key: value for key, value in corrupted.items() if key != "content_sha256"})
        with pytest.raises(ValueError, match="authoritative consume"):
            validate_fresh_before_source(corrupted, source, record)
        graph_id = host.fresh_learning.sync_actions(**scope)["logical_workflow_id"]
        snapshot = host.facade.load_graph_revision(graph_id)
        edge = snapshot["graph"]["edges"][0]
        node = next(item for item in snapshot["graph"]["nodes"] if item["node_id"] == edge["source_node_id"])
        region = next(item for item in node["regions"] if item["region_id"] == edge["target_region_id"])
        assert region["name"] == "View details", region
        assert region["reviewed_by_human"] is False
        assert edge["semantic_action"] == "open_detail"
        assert len(backend.commands) == 1
    finally:
        dispatch_fixtures._close(host, runtime)


@pytest.mark.parametrize("role,recorded,semantic,expected", [
    ("button", True, "open_detail", "control"),
    ("button", False, "open_detail", "region"),
    ("pane", True, "open_detail", "region"),
    ("input", True, "open_detail", "region"),
    (None, True, "open_detail", "region"),
    ("button", True, "scroll_region", "region"),
    ("button", True, "fill_field", "region"),
])
def test_recorded_control_kind_does_not_reclassify_generic_or_legacy_regions(role, recorded, semantic, expected):
    node = {
        "surface_type": "recorded_action_observation" if recorded else "external_untrusted_interface",
        "evidence": {"external_source_kind": "recorded_action" if recorded else "untrusted_external"},
        "regions": [{"region_id": "region.view", "name": "View details"}],
        "action_candidates": [{"semantic_action": semantic, "target_region_id": "region.view"}],
    }
    if role is not None:
        node["regions"][0]["target_observation"] = {
            "contract_version": "action_learning_target_observation_v1", "role": role,
        }
    anchors, refs = _stable_node_anchors(node, "state.before")
    target = next(item for item in anchors if item["anchor_id"] == refs["region.view"])
    assert target["label"] == "View details" and target["kind"] == expected
