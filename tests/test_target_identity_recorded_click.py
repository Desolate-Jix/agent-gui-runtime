"""计划身份进入真实点击后请求；后续字段阶段不得继承旧身份声明。"""
from copy import deepcopy
from dataclasses import replace
from threading import get_ident
from time import perf_counter_ns
from types import SimpleNamespace

import pytest

from app.core.typing_dispatch import create_typing_dispatch
from app.execution import visual_field_proof as field_proof
from app.execution.action_review import CANDIDATE_CONDITION
from app.execution.input_review_options import build_input_review_options
from app.judgment import DecisionProfile, DecisionService
from app.judgment.target_identity import normalize_identity_answer
from tests.test_target_identity_plan import identity_spec, plan
from tests.test_visual_field_proof import FIELD, TEXT, capture, executed_focus, focus_snapshot, receipt


class Provider:
    ready = True

    def judge(self, payload):
        result = {"request_sha256": payload["request_sha256"],
            "usage": {"input_tokens": 8, "output_tokens": 1, "total_tokens": 9},
            "http_elapsed_ms": 1.0, "server_processing_ms": None, "provider_request_id": "offline-identity"}
        spec = payload["action"].get("target_identity")
        if spec is None:
            result["choice_result"] = {"type": "choice", "name": "current_step", "choice": "condition_met",
                "confidence": .97, "probabilities": [
                    {"value": "condition_met", "probability": .98},
                    {"value": "condition_not_met", "probability": .01},
                    {"value": "evidence_insufficient", "probability": .01}]}
        else:
            raw = {"type": "choice", "name": "observed_target", "choice": "i0", "confidence": .97,
                "probabilities": [{"value": "i0", "probability": .97},
                    {"value": "i1", "probability": .01}, {"value": "other", "probability": .01},
                    {"value": "unknown", "probability": .01}]}
            result["choice_result"], result["identity_result"] = normalize_identity_answer(raw, spec)
        return result


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setattr("app.judgment.service._protect", lambda data, entropy, decrypt=False: data)
    service = DecisionService(tmp_path, provider=Provider(), profile=DecisionProfile(
        contract_version="decision_profile.v2", mode="auto", decision_format="choice", request_cap=10,
        auto_conditions=[CANDIDATE_CONDITION, field_proof.VISUAL_INPUT_CLICKED_CONDITION,
            field_proof.VISUAL_FOCUS_CONDITION, field_proof.VISUAL_SELECTION_CONDITION,
            field_proof.VISUAL_FIELD_FRESHNESS_CONDITION]))
    source = plan("input_sequence")
    source["steps"][0]["action"]["text"] = TEXT
    command = {"kind": "input_sequence", "request": {"field_goal": FIELD["field_goal"], "text": TEXT,
        "clear_existing": True, "submit_search": False}, "action_review": {
            "schema": "action_review_context.v1", "plan": source, "step_id": "search",
            "run_id": "recorded-run", "attempt_id": "recorded-attempt", "budget_ms": 30000}}
    options = build_input_review_options(SimpleNamespace(_decision_service=service), command, "recorded-input")
    value = SimpleNamespace(root=tmp_path, service=service, command=command, options=options,
        context=options["visual_field_context"], focus=executed_focus(receipt(tmp_path, "focus")),
        typed=receipt(tmp_path, "typed", "type_text"))
    yield value
    service.close()


def request(case, *, phase="focus", context=None):
    source = case.focus if phase == "focus" else case.typed
    return field_proof._request(phase=phase, focus_receipt=case.focus,
        input_receipt=None if phase == "focus" else case.typed,
        frame=source["observation"]["capture"], expected_field=deepcopy(FIELD),
        context=case.context if context is None else context, value_reading=None)


def proof(case):
    return field_proof.assess_visual_field(phase="focus", focus_receipt=case.focus, input_receipt=None,
        frame=case.focus["observation"]["capture"], expected_field=deepcopy(FIELD), context=case.context)


def test_plan_identity_reaches_frozen_recorded_click_request(case):
    value = request(case)
    case.command["action_review"]["plan"]["steps"][0]["action"]["target_identity"]["expected"] = "i1"
    assert case.context["target_identity"] == identity_spec()
    assert value["action"]["target_identity"] == identity_spec()
    assert value["condition"] == field_proof.VISUAL_INPUT_CLICKED_CONDITION
    assert value["action"]["executed_click"]["click_point"] == {"x": 40, "y": 30}
    assert value["action"]["executed_click"]["receipt_sha256"] == value["action"]["focus_receipt_sha256"]
    case.context["target_identity"]["expected"] = "i1"
    assert value["action"]["target_identity"]["expected"] == "i0"
    assert value["execution_request_id"] == "recorded-input"


def test_actual_field_proof_authenticates_identity_and_rejects_changed_spec(case):
    value = proof(case)
    bound = value.request()
    result = value.assessment()
    assert bound["action"]["target_identity"] == identity_spec()
    assert result["identity_result"]["answer"]["choice"] == "i0"
    assert case.service.validate_result(result, **bound)
    changed = deepcopy(bound)
    changed["action"]["target_identity"]["expected"] = "i1"
    assert not case.service.validate_result(result, **changed)


def test_recorded_click_rejects_invalid_context_identity(case):
    context = {**case.context, "target_identity": identity_spec()}
    context["target_identity"]["choices"].pop()
    with pytest.raises(ValueError, match="target_identity"):
        request(case, context=context)


@pytest.mark.parametrize("phase,native", [("focus", True), ("value", False)])
def test_native_and_value_requests_do_not_mix_identity(case, phase, native):
    context = {**case.context, "native_field_evidence": native, "target_identity": identity_spec()}
    value = request(case, phase=phase, context=context)
    assert "target_identity" not in value["action"]


def test_selection_request_drops_recorded_click_identity(case):
    case.context["target_identity"] = identity_spec()
    original = proof(case)
    dispatch = create_typing_dispatch()
    dispatch.record("selection", "started")
    dispatch.record("selection", "completed")
    dispatch.persist_selection(case.root / "selection-evidence")
    selected = field_proof.assess_visual_selection(original,
        frame=capture(case.root, "selected", changed=True), dispatch=dispatch)
    assert "target_identity" not in selected.request()["action"]
    assert original.request()["action"]["target_identity"] == identity_spec()
    assert selected.request()["action"]["focus_stage"] == "after_selection"


def test_freshness_request_drops_inherited_identity_without_mutating_proof(case):
    baseline = focus_snapshot(case, selection=None)
    native_request = request(case, context={**case.context, "native_field_evidence": True})
    native_request["action"]["focus_value_snapshot"] = baseline.to_reference()
    # 模拟已认证旧记录携带声明，派生阶段仍必须清除，不能依赖上游碰巧缺省。
    native_request["action"]["target_identity"] = identity_spec()
    result = case.service.evaluate(**native_request)
    original = field_proof.VisualFieldProof(field_proof._json({"request": native_request, "assessment": result}),
        case.service, case.context["deadline_ns"], get_ident(), field_proof._ISSUER, _focus_snapshot=baseline)
    fresh_frame = capture(case.root, "fresh", changed=True)
    snapshot = replace(baseline, capture_id=fresh_frame["capture_id"], read_id="fresh-read",
        observed_at_ns=perf_counter_ns())
    fresh = field_proof._field_freshness_request(original, frame=fresh_frame, native_snapshot=snapshot)
    assert "target_identity" not in fresh["action"]
    assert fresh["action"]["focus_stage"] == "before_keyboard_freshness"
    assert original.request()["action"]["target_identity"] == identity_spec()


def test_legacy_visual_context_does_not_add_identity(case):
    source = deepcopy(case.command)
    del source["action_review"]["plan"]["steps"][0]["action"]["target_identity"]
    options = build_input_review_options(SimpleNamespace(_decision_service=case.service), source, "legacy-input")
    value = request(case, context=options["visual_field_context"])
    assert "target_identity" not in options["visual_field_context"]
    assert "target_identity" not in value["action"]
