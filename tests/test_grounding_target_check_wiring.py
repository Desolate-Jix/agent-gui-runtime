"""默认目标检查绑定原目标和定位描述，不自动建立干扰类别。"""
from copy import deepcopy
from dataclasses import replace
import json
from threading import get_ident
from time import perf_counter_ns
from types import SimpleNamespace as NS

import pytest

from app.core.agent_grounding_target import AgentGroundingTarget, agent_grounding_scope
from app.core.local_keyboard_target import issue_visual_keyboard_target
from app.core.typing_dispatch import create_typing_dispatch
from app.core.visual_submit_target import VisualSubmitTarget
from app.execution import action_review as review, visual_field_proof as field
from app.execution.action_review_dispatch import review_original_action
from app.execution.decision_check import DecisionCheckRejected
from app.execution.input_review_options import build_input_review_options
from tests.test_grounding_identity_wiring import case, candidate_review, value_proof, compound_receipt
from tests.test_target_identity_plan import identity_spec, review_args
from tests.test_visual_field_proof import FIELD, NATIVE, capture, focus_snapshot


DESCRIPTION = {"kind": "graphic", "appearance": "Wide blue outlined rectangle",
    "container": "Top search toolbar"}
CHECK = {"schema": "target_check.v1", "kind": "input_field", "target": "Search field",
    "appearance": "Wide blue outlined rectangle", "container": "Top search toolbar"}


@pytest.fixture
def checked(case):
    case.step["action"].pop("target_identity", None)
    case.state["result"].pop("identity_options", None)
    case.state["result"]["target_description"] = deepcopy(DESCRIPTION)
    case.field_context = build_input_review_options(NS(_decision_service=case.service), case.command,
        "grounded-input")["visual_field_context"]
    return case


def test_default_check_uses_original_goal_and_description_without_categories(checked):
    envelope, _ = candidate_review(checked)
    assert envelope["action"]["target_check"] == CHECK
    assert "target_identity" not in envelope["action"]
    assert all(name not in envelope["action"]["target_check"] for name in ("choices", "expected", "identity_options"))
    assert "MODEL_LABEL_IS_NOT_EXPECTED" not in json.dumps(envelope["action"]["target_check"])
    assert len(checked.provider.calls) == 1
    assert "target_check" not in checked.step["action"]


def test_click_uses_description_kind_and_input_forces_input_field(checked):
    checked.step["action"] = {"kind": "click", "goal": "Search field"}
    envelope, _ = candidate_review(checked)
    assert envelope["action"]["target_check"] == {**CHECK, "kind": "graphic"}


def test_explicit_identity_keeps_diagnostic_route_priority(checked):
    checked.step["action"]["target_identity"] = identity_spec()
    envelope, _ = candidate_review(checked)
    assert envelope["action"]["target_identity"] == identity_spec()
    assert "target_check" not in envelope["action"]


@pytest.mark.parametrize("old", ["no_description", "options_only", "v2", "not_api"])
def test_legacy_provider_or_plan_does_not_gain_new_target_authority(checked, old):
    if old in {"no_description", "options_only"}:
        del checked.state["result"]["target_description"]
        if old == "options_only":
            checked.state["result"]["identity_options"] = ["Browser address bar"]
    elif old == "v2":
        checked.source["schema_version"] = "task_plan.v2"
        del checked.source["goal"], checked.source["completion"]
    else:
        checked.state["configuration"]["source"] = "agent_current"
        checked.state["result"]["candidates"][0]["evidence_source"] = "agent_visual"
    envelope, _ = candidate_review(checked)
    assert "target_check" not in envelope["action"]
    assert "target_identity" not in envelope["action"]


@pytest.mark.parametrize("change", ["goal", "description"])
def test_current_target_change_invalidates_the_first_review(checked, change):
    target = AgentGroundingTarget(checked.state)
    def mutate():
        if change == "goal":
            target._state["goal"] = "Other field"
        else:
            target._state["result"]["target_description"]["appearance"] = "Another control"
    checked.provider.during = mutate
    with pytest.raises((ValueError, DecisionCheckRejected)):
        candidate_review(checked, target=target)


def test_original_step_goal_must_match_grounding_goal_exactly(checked):
    checked.step["action"]["field_goal"] += " "
    with pytest.raises((ValueError, DecisionCheckRejected), match="goal"):
        candidate_review(checked)
    assert checked.provider.calls == []


def test_arbitrary_action_cannot_inject_a_target_check(checked):
    args = review_args(checked.root)
    del args["step"]["action"]["target_identity"]
    args["action"]["target_check"] = deepcopy(CHECK)
    args["candidate"]["target_description"] = deepcopy(DESCRIPTION)
    with pytest.raises(ValueError, match="target_check.*conflict"):
        review.build_action_review(**args)


def test_value_check_stays_independent_and_authenticates_local_target_binding(checked):
    candidate_review(checked)
    proof = value_proof(checked)
    action = proof.request()["action"]
    assert "target_check" not in action
    assert "target_identity" not in action
    assert action["target_check_binding"]["target_check"] == CHECK
    assert checked.service.validate_result(proof.assessment(), **proof.request())
    assert len(checked.provider.calls) == 2


@pytest.mark.parametrize("change", ["spec", "run", "plan", "point", "window", "missing"])
def test_value_rejects_changed_or_missing_original_target_review(checked, change):
    candidate_review(checked)
    source = checked.focus["response"]["data"]["action_assessment"]
    if change == "spec":
        source["evaluation_request"]["action"]["target_check"]["target"] = "Other field"
    elif change == "run":
        checked.field_context["action_review"]["run_id"] = "another-run"
    elif change == "plan":
        checked.field_context["action_review"]["plan"]["title"] = "another-plan"
    elif change == "point":
        source["evaluation_request"]["action"]["candidate"]["click_point"]["x"] += 1
    elif change == "window":
        source["evaluation_request"]["action"]["target_window_identity"]["process_id"] += 1
    else:
        del checked.focus["response"]["data"]["action_assessment"]
    with pytest.raises(ValueError, match="target"):
        value_proof(checked)
    assert len(checked.provider.calls) == 1


def test_atomic_input_and_enter_reuse_authenticated_check_without_new_locator(checked):
    candidate_review(checked)
    compound_receipt(checked)
    proof = value_proof(checked, compound=True)
    target = VisualSubmitTarget(issue_visual_keyboard_target(proof, "press_key", submit_search=True),
        action_review=checked.context)
    current = capture(checked.root, "check-submit-current")
    with agent_grounding_scope(target), review.action_review_scope(checked.service, context=checked.context,
            deadline_ns=checked.field_context["deadline_ns"]) as active:
        selected = target.plan(image_path=current["image_path"], goal=FIELD["field_goal"], identity=NATIVE)["recommended_target"]
        reviewed = review_original_action(capture=current, identity=NATIVE, candidate=selected,
            point=FIELD["click_point"], goal=FIELD["field_goal"], click_kind="single", manager=checked.manager,
            validate_binding=lambda: (NATIVE, selected))
        assert active["envelope"]["action"]["target_check"] == CHECK
        assert active["envelope"]["action"]["visual_submit_phase"] == "reanchor_enter"
        target.before_dispatch(FIELD["click_point"], NATIVE)
        reviewed["validate"]()
    assert len(checked.provider.calls) == 3
    assert "target_check" not in checked.provider.calls[1]["action"]


def test_value_and_submit_cache_tampering_cannot_change_the_original_target(checked):
    candidate_review(checked)
    proof = value_proof(checked)
    target = VisualSubmitTarget(issue_visual_keyboard_target(proof, "press_key", submit_search=True),
        action_review=checked.context)
    with agent_grounding_scope(target):
        returned = target.review_target_check(checked.step["action"])
        returned["target"] = "Other field"
        assert target.review_target_check(checked.step["action"]) == CHECK
        target._target_check["target"] = "Other field"
        with pytest.raises(ValueError, match="target_check"):
            target.review_target_check(checked.step["action"])
    raw = json.loads(proof._json_value)
    raw["request"]["action"]["target_check_binding"]["target_check"]["target"] = "Other field"
    object.__setattr__(proof, "_json_value", field._json(raw))
    with pytest.raises(ValueError):
        issue_visual_keyboard_target(proof, "press_key", submit_search=True)


def test_scene_and_freshness_do_not_reuse_target_check(checked):
    envelope, _ = candidate_review(checked)
    fresh = review.build_freshness_review(envelope,
        current_frame={**envelope["frame"], "capture_id": "fresh-check"}, changed_region={"x": 12, "y": 12, "w": 2, "h": 10})
    assert "target_check" not in fresh["action"]
    args = review_args(checked.root)
    del args["step"]["action"]["target_identity"]
    args.update(scope="scene", candidate=None, action=deepcopy(envelope["action"]))
    scene = review.build_action_review(**args)
    assert "target_check" not in scene["action"]
    assert envelope["action"]["target_check"] == CHECK


def test_selection_request_excludes_the_prior_target_check(checked):
    checked.service.profile = checked.service.profile.model_copy(update={"auto_conditions": (
        *checked.service.profile.auto_conditions, field.VISUAL_SELECTION_CONDITION)})
    candidate_review(checked)
    original = field.assess_visual_field(phase="focus", focus_receipt=checked.focus, input_receipt=None,
        frame=checked.focus["observation"]["capture"], expected_field=deepcopy(FIELD), context=checked.field_context)
    dispatch = create_typing_dispatch()
    dispatch.record("selection", "started")
    dispatch.record("selection", "completed")
    dispatch.persist_selection(checked.root / "check-selection")
    selected = field.assess_visual_selection(original,
        frame=capture(checked.root, "check-selected", changed=True), dispatch=dispatch)
    assert "target_check" not in selected.request()["action"]
    assert original.request()["action"]["target_check"] == CHECK


def test_field_freshness_excludes_inherited_target_check(checked):
    checked.service.profile = checked.service.profile.model_copy(update={"auto_conditions": (
        *checked.service.profile.auto_conditions, field.VISUAL_FOCUS_CONDITION)})
    baseline = focus_snapshot(checked, selection=None)
    context = {**checked.field_context, "native_field_evidence": True}
    original_request = field._request(phase="focus", focus_receipt=checked.focus, input_receipt=None,
        frame=checked.focus["observation"]["capture"], expected_field=deepcopy(FIELD), context=context,
        value_reading=None)
    original_request["action"].update(focus_value_snapshot=baseline.to_reference(), target_check=deepcopy(CHECK))
    result = checked.service.evaluate(**original_request)
    original = field.VisualFieldProof(field._json({"request": original_request, "assessment": result}),
        checked.service, checked.field_context["deadline_ns"], get_ident(), field._ISSUER, _focus_snapshot=baseline)
    frame = capture(checked.root, "check-field-fresh", changed=True)
    snapshot = replace(baseline, capture_id=frame["capture_id"], read_id="new-check-reading",
        observed_at_ns=perf_counter_ns())
    fresh = field._field_freshness_request(original, frame=frame, native_snapshot=snapshot)
    assert "target_check" not in fresh["action"]
    assert original.request()["action"]["target_check"] == CHECK
