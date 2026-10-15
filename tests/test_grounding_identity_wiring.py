"""历史显式身份诊断保持认证闭合；定位备选不再自动生成类别。"""
from copy import deepcopy
from hashlib import sha256
import json
from time import perf_counter_ns, time
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
from app.judgment import DecisionProfile, DecisionService
from app.judgment.target_identity import normalize_identity_answer
from tests.test_target_identity_plan import identity_spec, plan
from tests.test_visual_field_proof import FIELD, TEXT, NATIVE, capture, executed_focus, receipt


GENERATED = {"schema": "target_identity.v1", "choices": [
    {"value": "a", "description": "Browser address bar"},
    {"value": "b", "description": "Search field"}], "expected": "b"}


class Provider:
    ready = True

    def __init__(self):
        self.calls, self.during = [], None

    def judge(self, payload):
        self.calls.append(deepcopy(payload))
        result = {"request_sha256": payload["request_sha256"],
            "usage": {"input_tokens": 8, "output_tokens": 1, "total_tokens": 9},
            "http_elapsed_ms": 1.0, "server_processing_ms": None, "provider_request_id": "offline-wiring"}
        spec = payload["action"].get("target_identity")
        if spec is None:
            result["choice_result"] = {"type": "choice", "name": "current_step", "choice": "condition_met",
                "confidence": .97, "probabilities": [
                    {"value": "condition_met", "probability": .98},
                    {"value": "condition_not_met", "probability": .01},
                    {"value": "evidence_insufficient", "probability": .01}]}
        else:
            values = [row["value"] for row in spec["choices"]] + ["other", "unknown"]
            raw = {"type": "choice", "name": "observed_target", "choice": spec["expected"], "confidence": .97,
                "probabilities": [{"value": value, "probability": .97 if value == spec["expected"] else
                    .03 / (len(values)-1)} for value in values]}
            result["choice_result"], result["identity_result"] = normalize_identity_answer(raw, spec)
        if self.during:
            callback, self.during = self.during, None
            callback()
        return result


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setattr("app.judgment.service._protect", lambda data, entropy, decrypt=False: data)
    provider = Provider()
    service = DecisionService(tmp_path, provider=provider, profile=DecisionProfile(
        contract_version="decision_profile.v2", mode="auto", decision_format="choice", request_cap=20,
        auto_conditions=[review.CANDIDATE_CONDITION, review.SCENE_CONDITION, review.FRESHNESS_CONDITION,
            field.VISUAL_INPUT_CLICKED_CONDITION, field.VISUAL_TEXT_VALUE_CONDITION]))
    source = plan("input_sequence")
    step = source["steps"][0]
    step["action"].update(text=TEXT, submit_search=True)
    step["action"]["target_identity"] = deepcopy(GENERATED)
    context = {"schema": "action_review_context.v1", "run_id": "grounding-run", "attempt_id": "grounding-attempt",
        "step_id": step["step_id"], "budget_ms": 30000, "plan": source}
    command = {"kind": "input_sequence", "request": {key: step["action"][key] for key in
        ("field_goal", "text", "clear_existing", "submit_search")}, "action_review": context}
    options = build_input_review_options(NS(_decision_service=service), command, "grounded-input")
    focus = executed_focus(receipt(tmp_path, "focus"))
    state = {"phase": "executing", "request_id": "ground-1", "goal": FIELD["field_goal"],
        "expires_at": time()+180, "configuration": {"source": "external_api"},
        "capture": {**deepcopy(focus["capture"]), "image_size": {"width": 180, "height": 90}},
        "result": {"schema_version": "grounding.v1", "request_id": "ground-1",
            "capture_id": focus["capture"]["capture_id"], "status": "found",
            "coordinate_space": "capture_image_pixels", "image_size": {"width": 180, "height": 90},
            "identity_options": ["Browser address bar"], "selected_candidate_id": "field", "candidates": [{
                "id": "field", "label": "MODEL_LABEL_IS_NOT_EXPECTED", "bbox": {"x": 10, "y": 10, "width": 140, "height": 40},
                "click_point": deepcopy(FIELD["click_point"]), "evidence_source": "api_visual"}]}}
    bound = NS(handle=10, process_id=20, rect=NS(left=0, top=0, right=180, bottom=90))
    value = NS(root=tmp_path, provider=provider, service=service, context=context, source=source, step=step,
        command=command, field_context=options["visual_field_context"], focus=focus, state=state,
        typed=receipt(tmp_path, "typed", "type_text"), manager=NS(get_bound_window=lambda: bound))
    yield value
    service.close()


def candidate_review(case, *, target=None):
    target = AgentGroundingTarget(case.state) if target is None else target
    with agent_grounding_scope(target), review.action_review_scope(case.service, context=case.context,
            deadline_ns=case.field_context["deadline_ns"]) as active:
        planned = target.plan(image_path=case.focus["capture"]["image_path"], goal=FIELD["field_goal"], identity=NATIVE)
        selected = planned["recommended_target"]
        reviewed = review_original_action(capture=case.focus["capture"], identity=NATIVE, candidate=selected,
            point=FIELD["click_point"], goal=FIELD["field_goal"], click_kind="single", manager=case.manager,
            validate_binding=lambda: (NATIVE, selected))
        envelope = deepcopy(active["envelope"])
        case.focus["response"]["data"]["recognition_plan"] = deepcopy(planned)
        case.focus["response"]["data"]["action_assessment"] = deepcopy(reviewed["assessment"])
    return envelope, target


def value_proof(case, *, compound=False):
    original = case.focus if compound else case.typed
    return field.assess_visual_field(phase="value", focus_receipt=case.focus, input_receipt=original,
        frame=original["observation"]["capture"], expected_field=deepcopy(FIELD), context=case.field_context)


def compound_receipt(case):
    data = case.focus["response"]["data"]
    dispatch = create_typing_dispatch()
    for stage in ("selection", "text"):
        dispatch.record(stage, "started")
        dispatch.record(stage, "completed")
    fact = dispatch.reference()
    typed = {"typed": True, "window_handle": 10, "text_length": len(TEXT), "clear_existing": True,
        "submit": False, "click_before_typing": False, "typing_dispatch": fact}
    data["visual_compound_input"] = {"schema": "visual_compound_input.v1", "text_length": len(TEXT),
        "text_sha256": sha256(TEXT.encode("utf-8")).hexdigest(), "clear_existing": True, "submit": False,
        "window_identity": deepcopy(FIELD["window_identity"]), "execution_request_id": "grounded-input",
        "window_rect": [0, 0, 180, 90], "point": deepcopy(FIELD["click_point"]),
        "click_result_sha256": field._digest(data["click_result"]), "typing_dispatch": fact, "type_result": typed}


def test_api_options_do_not_automatically_create_identity_categories(case):
    del case.step["action"]["target_identity"]
    envelope, _ = candidate_review(case)
    assert "target_identity" not in envelope["action"]
    assert "target_check" not in envelope["action"]
    assert len(case.provider.calls) == 1
    assert "target_identity" not in case.step["action"]


def test_explicit_plan_identity_takes_priority(case):
    case.step["action"]["target_identity"] = identity_spec()
    envelope, _ = candidate_review(case)
    assert envelope["action"]["target_identity"] == identity_spec()


@pytest.mark.parametrize("old", ["no_options", "v2", "not_api"])
def test_legacy_or_non_api_grounding_keeps_ordinary_candidate_review(case, old):
    del case.step["action"]["target_identity"]
    if old == "no_options":
        del case.state["result"]["identity_options"]
    elif old == "not_api":
        case.state["configuration"]["source"] = "agent_current"
        case.state["result"]["candidates"][0]["evidence_source"] = "agent_visual"
    else:
        case.source["schema_version"] = "task_plan.v2"
        del case.source["goal"], case.source["completion"]
    envelope, _ = candidate_review(case)
    assert "target_identity" not in envelope["action"]


@pytest.mark.parametrize("change", ["goal", "options"])
def test_current_target_mutation_during_decision_cannot_release_review(case, change):
    del case.step["action"]["target_identity"]
    target = AgentGroundingTarget(case.state)
    def mutate():
        if change == "goal":
            target._state["goal"] = "Other field"
        else:
            target._state["result"]["identity_options"] = ["Other field"]
    case.provider.during = mutate
    with pytest.raises((ValueError, DecisionCheckRejected)):
        candidate_review(case, target=target)


def test_grounding_goal_must_exactly_match_frozen_step(case):
    case.step["action"]["field_goal"] += " "
    with pytest.raises((ValueError, DecisionCheckRejected), match="goal"):
        candidate_review(case)
    assert case.provider.calls == []


def test_arbitrary_candidate_options_do_not_create_identity_without_internal_target(case):
    from tests.test_target_identity_plan import review_args
    args = review_args(case.root)
    del args["step"]["action"]["target_identity"]
    args["candidate"]["identity_options"] = ["Forged alternate"]
    args["action"]["identity_options"] = ["Forged alternate"]
    assert "target_identity" not in review.build_action_review(**args)["action"]


def test_value_keeps_authenticated_original_identity_in_separate_local_binding(case):
    candidate_review(case)
    proof = value_proof(case)
    action = proof.request()["action"]
    assert "target_identity" not in action
    assert action["target_identity_binding"]["target_identity"] == GENERATED
    assert action["target_identity_binding"]["goal"] == "Search field"
    assert case.service.validate_result(proof.assessment(), **proof.request())
    assert len(case.provider.calls) == 2


@pytest.mark.parametrize("change", ["spec", "run", "plan", "point", "window"])
def test_value_rejects_forged_or_rebound_original_candidate_before_decision(case, change):
    candidate_review(case)
    source = case.focus["response"]["data"]["action_assessment"]
    if change == "spec":
        source["evaluation_request"]["action"]["target_identity"]["expected"] = "a"
    elif change == "run":
        case.field_context["action_review"]["run_id"] = "another-run"
    elif change == "plan":
        case.field_context["action_review"]["plan"]["title"] = "another-plan"
    elif change == "point":
        source["evaluation_request"]["action"]["candidate"]["click_point"]["x"] += 1
    else:
        source["evaluation_request"]["action"]["target_window_identity"]["process_id"] += 1
    with pytest.raises(ValueError, match="identity"):
        value_proof(case)
    assert len(case.provider.calls) == 1


def test_compound_input_value_and_enter_reuse_original_identity_without_new_grounding(case):
    candidate_review(case)
    compound_receipt(case)
    proof = value_proof(case, compound=True)
    target = VisualSubmitTarget(issue_visual_keyboard_target(proof, "press_key", submit_search=True),
        action_review=case.context)
    current = capture(case.root, "submit-current")
    with agent_grounding_scope(target), review.action_review_scope(case.service, context=case.context,
            deadline_ns=case.field_context["deadline_ns"]) as active:
        selected = target.plan(image_path=current["image_path"], goal=FIELD["field_goal"], identity=NATIVE)["recommended_target"]
        reviewed = review_original_action(capture=current, identity=NATIVE, candidate=selected,
            point=FIELD["click_point"], goal=FIELD["field_goal"], click_kind="single", manager=case.manager,
            validate_binding=lambda: (NATIVE, selected))
        assert active["envelope"]["action"]["target_identity"] == GENERATED
        assert active["envelope"]["action"]["visual_submit_phase"] == "reanchor_enter"
        target.before_dispatch(FIELD["click_point"], NATIVE)
        reviewed["validate"]()
    assert len(case.provider.calls) == 3
    assert "target_identity" not in case.provider.calls[1]["action"]


def test_value_binding_tampering_or_goal_change_cannot_construct_submit_target(case):
    candidate_review(case)
    proof = value_proof(case)
    raw = json.loads(proof._json_value)
    raw["request"]["action"]["target_identity_binding"]["target_identity"]["expected"] = "a"
    object.__setattr__(proof, "_json_value", field._json(raw))
    with pytest.raises(ValueError):
        issue_visual_keyboard_target(proof, "press_key", submit_search=True)


def test_legacy_explicit_identity_does_not_bind_an_unauthenticated_source(case):
    candidate_review(case)
    del case.focus["response"]["data"]["action_assessment"]
    proof = value_proof(case)
    assert "target_identity_binding" not in proof.request()["action"]
    assert len(case.provider.calls) == 2


def test_submit_identity_copy_is_bound_to_authenticated_value_proof(case):
    candidate_review(case)
    target = VisualSubmitTarget(issue_visual_keyboard_target(value_proof(case), "press_key", submit_search=True),
        action_review=case.context)
    with agent_grounding_scope(target):
        returned = target.review_target_identity(case.step["action"])
        returned["expected"] = "a"
        assert target.review_target_identity(case.step["action"]) == GENERATED
        target._target_identity["expected"] = "a"
        with pytest.raises(ValueError, match="identity"):
            target.review_target_identity(case.step["action"])


def test_non_identity_scopes_do_not_inherit_generated_top_level_spec(case):
    envelope, _ = candidate_review(case)
    fresh = review.build_freshness_review(envelope,
        current_frame={**envelope["frame"], "capture_id": "fresh"}, changed_region={"x": 12, "y": 12, "w": 2, "h": 10})
    assert "target_identity" not in fresh["action"]
    assert envelope["action"]["target_identity"] == GENERATED
