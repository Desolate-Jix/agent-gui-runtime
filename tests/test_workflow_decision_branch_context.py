"""学习审核上下文必须表达固定程序的真实后继图。"""
from copy import deepcopy
from hashlib import sha256

import pytest
from PIL import Image

from app.desktop_review.external_mapping import canonical_json_bytes
from app.learning_memory.decision_verification import decision_binding, decision_review_context
from app.learning_memory.workflow_program import validate_definition


def step(identity, *, success=None, failure=None, action=None):
    return {"step_id": identity, "title": identity.title(), "source_node_id": None, "target_node_id": None,
            "action": action or {"kind": "click", "goal": "Open " + identity},
            "preconditions": [], "success_conditions": [], "outputs": [],
            "branches": {"success": success, "failure": failure, "uncertain": None},
            "review_status": "reviewed", "provenance": "manual",
            "verification": {"kind": "agent_judgment", "decision_condition": "Result is visible."}}


def program(steps):
    definition = validate_definition({"title": "Branching workflow", "inputs": [], "outputs": [], "steps": steps}, set())
    digest = sha256(canonical_json_bytes(definition)).hexdigest()
    return {"program_id": "task-program-" + digest, "content_sha256": digest, "definition": definition}


def test_context_follows_success_edges_instead_of_definition_order():
    value = program([step("done"), step("next", success="done"), step("current", success="next")])
    current = value["definition"]["steps"][-1]
    context = decision_review_context(value, current)
    assert context["remaining_plan"] == [
        "next (entry=true; success=step:done; failure=terminal; uncertain=Main): Next [click] Result is visible.",
        "done (entry=false; success=terminal; failure=terminal; uncertain=Main): Done [click] Result is visible."]


def test_context_omits_current_failure_branch_and_unreachable_nodes():
    value = program([step("current", success="next", failure="recovery"), step("recovery"),
                     step("unrelated"), step("next")])
    context = decision_review_context(value, value["definition"]["steps"][0])
    assert context["remaining_plan"] == [
        "next (entry=true; success=terminal; failure=terminal; uncertain=Main): Next [click] Result is visible."]


def test_context_preserves_fork_edges_and_emits_shared_node_once():
    value = program([step("finish"), step("recovery", success="finish"), step("happy", success="finish"),
                     step("choose", success="happy", failure="recovery"), step("current", success="choose")])
    context = decision_review_context(value, value["definition"]["steps"][-1])
    assert context["remaining_plan"] == [
        "choose (entry=true; success=step:happy; failure=step:recovery; uncertain=Main): Choose [click] Result is visible.",
        "happy (entry=false; success=step:finish; failure=terminal; uncertain=Main): Happy [click] Result is visible.",
        "recovery (entry=false; success=step:finish; failure=terminal; uncertain=Main): Recovery [click] Result is visible.",
        "finish (entry=false; success=terminal; failure=terminal; uncertain=Main): Finish [click] Result is visible."]


def test_terminal_success_has_no_remaining_plan_even_with_later_definition_rows():
    value = program([step("current", failure="recovery"), step("recovery"), step("unrelated")])
    assert decision_review_context(value, value["definition"]["steps"][0])["remaining_plan"] == []


def test_branch_context_keeps_dynamic_action_values_out_of_model_input():
    value = program([step("current", success="next"), step("next", action={"kind": "input_sequence",
        "field_goal": "Private field", "text": {"source": "constant", "value": "synthetic-private-value"},
        "clear_existing": True, "submit_search": False})])
    context = decision_review_context(value, value["definition"]["steps"][0])
    assert "[input_sequence]" in context["remaining_plan"][0]
    assert "synthetic-private-value" not in str(context) and "Private field" not in str(context)


def test_long_node_summary_cannot_truncate_branch_topology():
    value = program([step("current", success="next"), step("next", success="finish"), step("finish")])
    value["definition"]["steps"][1]["title"] = "x" * 4000
    context = decision_review_context(value, value["definition"]["steps"][0])
    assert len(context["remaining_plan"][0]) == 2000
    assert context["remaining_plan"][0].startswith(
        "next (entry=true; success=step:finish; failure=terminal; uncertain=Main): ")


def test_frozen_context_rejects_changed_program_edges_at_original_evidence_binding(tmp_path):
    value = program([step("current", success="next"), step("next", success="done"), step("done")])
    current = value["definition"]["steps"][0]
    frozen = decision_review_context(value, current)
    original = deepcopy(frozen)
    image = tmp_path / "after.png"
    Image.new("RGB", (2, 2), "white").save(image)
    digest = sha256(image.read_bytes()).hexdigest()
    identity = {"handle": 1, "process_id": 2, "process_create_time": 3.0}
    ids = {"run_id": "run", "step_id": "current", "request_id": "verify", "execution_request_id": "execution"}
    envelope = {"receipt": {**ids, "pre_capture_id": "before", "post_capture_id": "after",
                    "post_capture_sha256": digest, "window_identity": identity, "scope_id": "scope"},
                "observation": {**ids, "capture_id": "after", "capture_sha256": digest,
                    "window_identity": identity, "scope_id": "scope", "complete": True,
                    "source": "decision_capture", "evidence_ref": "observation.json", "values": {}},
                "frame": {"image_path": str(image), "capture_id": "after", "sha256": digest,
                    "window_identity": identity}, "decision_review_context": frozen}
    assert decision_binding(current, envelope, program=value)["review_context"] == original
    value["definition"]["steps"][1]["branches"]["success"] = None
    assert frozen == original
    with pytest.raises(ValueError, match="review_context_mismatch"):
        decision_binding(current, envelope, program=value)
