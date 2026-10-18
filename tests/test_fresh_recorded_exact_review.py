"""新动作通过真实记录、图审核和发布链，不导入旧学习。"""

from copy import deepcopy

import pytest

from app.desktop_review.graph_exact_projection import project_graph_exact_review
from tests.test_fresh_dispatch_graph import _close, _ready


BINDING = {"kind": "web", "display_name": "Fresh fixture",
           "canonical_origin": "https://fresh.example"}


def test_recorded_action_enters_review_without_inventing_effect_or_interface_identity(tmp_path):
    host, owner, runtime, backend, claims, session, scope, confirmation_id = _ready(tmp_path)
    try:
        result = runtime.consume_grounded_confirmation(confirmation_id=confirmation_id)
        assert result.outcome == "ACTION_RECORDED" and result.effect_status == "not_verified"
        synced = host.fresh_learning.sync_actions(**scope)
        facade = host.facade
        snapshot = facade.load_graph_revision(synced["logical_workflow_id"])
        saved = deepcopy(snapshot)
        edge = snapshot["graph"]["edges"][0]
        prepared = facade.prepare_graph_exact_review(snapshot["logical_workflow_id"],
            snapshot["revision"], snapshot["content_sha256"], BINDING, [])
        action_subjects = [item for item in prepared["subjects"] if item["kind"] == "action"]
        assert len(action_subjects) == 1
        subject = action_subjects[0]
        assert subject["confirmed"] is False
        action = subject["content"]
        assert action["external_step_id"] == edge["recorded_event"]["event_id"]
        assert action["target_region_id"] == edge["target_region_id"]
        assert action["target_node_id"] == edge["target_node_id"]
        assert action["semantic_action"] == "open_detail"
        assert action["artifact_is_authorization"] is False
        assert action["execute_binding_enabled"] is False
        assert facade.compile_exact_review(prepared["review_ref"], 0)["status"] == "blocked"
        approved = facade.record_review_decisions(prepared["review_ref"], 0,
            [item["subject_id"] for item in prepared["subjects"]])
        no_effect = facade.compile_exact_review(prepared["review_ref"], approved["approval_revision"])
        assert no_effect["status"] == "blocked", no_effect
        assert facade.load_graph_revision(snapshot["logical_workflow_id"]) == saved

        corrected = facade.apply_graph_edit(snapshot["logical_workflow_id"],
            snapshot["revision"], snapshot["content_sha256"],
            {"type": "update_edge_semantics", "edge_id": edge["edge_id"],
             "prerequisites": ["Fresh item visible"], "expected_result": "Fresh detail visible",
             "stop_condition": "Fresh detail absent", "relationship_kinds": {}},
            "recorded-explicit-effect")
        reviewed = facade.prepare_graph_exact_review(corrected["logical_workflow_id"],
            corrected["revision"], corrected["content_sha256"], BINDING, [])
        assert not any(item["confirmed"] for item in reviewed["subjects"])
        confirmed = facade.record_review_decisions(reviewed["review_ref"], 0,
            [item["subject_id"] for item in reviewed["subjects"]])
        compiled = facade.compile_exact_review(reviewed["review_ref"], confirmed["approval_revision"])
        # 新观察没有可见身份特征；接通候选不能绕过后续编译检查。
        assert compiled["status"] == "blocked", compiled
        assert any(item["detail"] == "missing_observable_interface_identity"
                   for item in compiled["blocked_reasons"]), compiled
        assert facade.load_graph_revision(snapshot["logical_workflow_id"], snapshot["revision"]) == saved
        assert corrected["graph"]["edges"][0]["recorded_event"] == edge["recorded_event"]
        assert len(backend.commands) == 1
        from tests.test_graph_recognition_identity import _identity
        from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore
        with_identity = corrected
        for index, node in enumerate(corrected["graph"]["nodes"]):
            with_identity = facade.apply_graph_edit(with_identity["logical_workflow_id"],
                with_identity["revision"], with_identity["content_sha256"],
                _identity(node, text=f"Fresh visible screen {index}"), f"identity-{index}")
        final_review = facade.prepare_graph_exact_review(with_identity["logical_workflow_id"],
            with_identity["revision"], with_identity["content_sha256"], BINDING, [])
        assert not any(item["confirmed"] for item in final_review["subjects"])
        approved_final = facade.record_review_decisions(final_review["review_ref"], 0,
            [item["subject_id"] for item in final_review["subjects"]])
        final_compile = facade.compile_exact_review(final_review["review_ref"], approved_final["approval_revision"])
        assert final_compile["status"] == "compiled", final_compile
        publication = facade.publish_exact_review(final_compile["compile_receipt_id"])
        loaded = ReviewedWorkflowAssetStore(project_root=facade._artifact_root).load_workflow_version(
            with_identity["logical_workflow_id"], publication["version_id"])
        assert loaded["asset"] == publication["asset"]
        assert len(loaded["asset"]["transitions"]) == 1
        memory = facade.get_workflow_memory([with_identity["logical_workflow_id"]],
            with_identity["logical_workflow_id"], publication["version_id"])
        assert memory["version_id"] == publication["version_id"]
        assert memory["graph_sha256"] == with_identity["content_sha256"]
        assert memory["requires_current_grounding"] is True
        assert memory["execute_binding_enabled"] is False
        assert memory["asset_view"]["transitions"] == loaded["asset"]["transitions"]
        for index, node in enumerate(with_identity["graph"]["nodes"]):
            state = next(item for item in loaded["asset"]["states"] if item["source_node_id"] == node["node_id"])
            assert any(anchor["kind"] == "text" and anchor["label"] == f"Fresh visible screen {index}"
                       for anchor in state["identity_anchors"]), state["identity_anchors"]
        assert facade.load_graph_revision(snapshot["logical_workflow_id"], snapshot["revision"]) == saved
        assert len(backend.commands) == 1
    finally:
        _close(host, runtime)


def _projection_fixture():
    return {"graph": {"workflow": {}, "nodes": [
        {"node_id": "before", "evidence": {"external_source_kind": "recorded_action",
            "source_sha256": "a" * 64}, "regions": [{"region_id": "target"}],
         "action_candidates": []},
        {"node_id": "after", "regions": [], "action_candidates": []},
    ], "edges": [{"edge_id": "recorded-edge", "external_step_id": "event-1",
        "source_node_id": "before", "target_node_id": "after", "target_region_id": "target",
        "target_control_id": "", "action_type": "open_detail",
        "recorded_event": {"event_id": "event-1", "source_sha256": "a" * 64},
        "success_conditions": [], "failure_conditions": []}]}}


@pytest.mark.parametrize("mutation", [
    lambda g: g["nodes"][0]["evidence"].update(external_source_kind="untrusted_external"),
    lambda g: g["edges"][0]["recorded_event"].update(event_id="different-event"),
    lambda g: g["edges"][0]["recorded_event"].update(source_sha256="b" * 64),
    lambda g: g["edges"][0].update(target_region_id="missing-region"),
    lambda g: g["edges"][0].update(target_control_id="another-target"),
    lambda g: g["nodes"][0]["regions"].append({"region_id": "target"}),
    lambda g: g["nodes"][0]["action_candidates"].extend([
        {"external_step_id": "event-1", "action_template_id": "first"},
        {"external_step_id": "event-1", "action_template_id": "second"}]),
])
def test_recorded_adapter_does_not_repair_ambiguous_or_unbound_evidence(mutation):
    snapshot = _projection_fixture()
    mutation(snapshot["graph"])
    before = deepcopy(snapshot)
    with pytest.raises(ValueError, match="candidate.*binding"):
        project_graph_exact_review(snapshot, BINDING, [], {"open_detail"}, set())
    assert snapshot == before


def test_recorded_projection_is_deterministic_unreviewed_and_keeps_conditions_empty():
    snapshot = _projection_fixture()
    before = deepcopy(snapshot)
    first = project_graph_exact_review(snapshot, BINDING, [], {"open_detail"}, set())
    assert first == project_graph_exact_review(snapshot, BINDING, [], {"open_detail"}, set())
    assert snapshot == before
    candidate = first["nodes"][0]["action_candidates"][0]
    assert candidate["expected_result"] == "" and candidate["stop_condition"] == ""
    assert candidate["reviewed_by_human"] is False
    assert first["edges"][0]["action_template_id"] == candidate["action_template_id"]
