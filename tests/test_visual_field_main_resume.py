"""Main 审核仅续原已完成输入的后缀，不重放文字或冒充模型通过。"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter_ns

import pytest

from app.execution import input_sequence
from tests.test_visual_field_proof import scene, FIELD, TEXT, capture
from tests.test_visual_input_no_uia import visual_sequence, choice_replies


def main_review(error):
    ref = error.to_reference()
    return {"action": "review", "run_id": "visual-run", "step_id": "fill",
        "execution_request_id": ref["request"]["execution_request_id"],
        "evidence_sha256": ref["request"]["frames"][-1]["sha256"],
        "review_packet_sha256": "a" * 64, "evidence_set_sha256": "b" * 64,
        "assessment_round": 0, "verdict": "success", "reason": "Original image checked"}


def install_handler(v, monkeypatch, handler):
    original = input_sequence.run_input_sequence
    owner_active = [False]
    def guarded_handler(*args, **kwargs):
        assert owner_active[0] is False
        return handler(*args, **kwargs)
    def run(coordinator, *args, **kwargs):
        from app.core.input_sequence_partial import _digest
        context = kwargs["visual_field_context"]
        context["action_review"] = deepcopy(kwargs["action_review"])
        context["review_context"].update(source_id=kwargs["action_review"]["run_id"],
            source_sha256=_digest(kwargs["action_review"]["plan"]))
        previous = coordinator._owner.call
        def call(callback):
            owner_active[0] = True
            try:
                return previous(callback)
            finally:
                owner_active[0] = False
        coordinator._owner.call = call
        return original(coordinator, *args, **kwargs, field_review_handler=guarded_handler)
    monkeypatch.setattr(input_sequence, "run_input_sequence", run)


def value_refusal(v, monkeypatch):
    from tests import test_visual_input_no_uia
    monkeypatch.setattr(test_visual_input_no_uia, "current_stage",
        lambda current: "value" if len(current.calls) == 1 else "focus")
    return choice_replies(v, monkeypatch, "value", "condition_not_met")


def persisted_review(error, progress, service):
    from app.core.input_sequence_partial import _digest
    original = error.to_reference()
    session = Path(service.session_dir)
    execution = original["request"]["execution_request_id"]
    def save(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        return {"path": path.relative_to(session).as_posix(), "sha256": sha256(path.read_bytes()).hexdigest()}
    snapshot = save(session / "agent-commands" / "field-reviews" / (execution + "-round0-progress.json"), progress)
    frame = original["request"]["frames"][0]
    refs = [snapshot, {"path": Path(frame["image_path"]).relative_to(session).as_posix(), "sha256": frame["sha256"]}]
    packet = {"schema": "field_review_packet.v1", "stage": "after_type", "run_id": "visual-run", "step_id": "fill",
        "execution_request_id": execution, "assessment_round": 0, "after": frame, "frames": [frame],
        "plan_sha256": original["request"]["review_context"]["source_sha256"],
        "request": original["request"], "assessment": original["assessment"],
        "progress_sha256": _digest(progress), "progress_snapshot": snapshot,
        "evidence_refs": refs, "evidence_set_sha256": _digest(refs)}
    packet["packet_sha256"] = _digest(packet)
    review = {**main_review(error), "review_packet_sha256": packet["packet_sha256"],
        "evidence_set_sha256": packet["evidence_set_sha256"]}
    save(session / "agent-commands" / (execution + ".json"), {"field_review": {"packet": packet,
        "review": review, "review_request_id": "main-review-1", "continued": True,
        "continue_request_id": "main-continue-1"}})
    return review


@pytest.mark.parametrize("submit", [False, True])
def test_main_approval_continues_original_compound_without_retyping(visual_sequence, monkeypatch, submit):
    from app.execution.main_field_approval import _issue_main_field_approval
    from app.core.input_controller import VK_CONTROL, VK_A, VK_V, VK_RETURN
    v = visual_sequence
    service, client = value_refusal(v, monkeypatch)
    calls = []
    old_deadline = v.scene.context["deadline_ns"]
    # 合成的新采集与原 after 内容相同，但有独立 capture ID。
    monkeypatch.setattr(v.scene.module, "capture_visual_field_frame",
        lambda manager, context: capture(v.scene.root, "manual-fresh"))
    def handler(error, *, stage, progress, context):
        assert stage == "after_type" and progress["completed_steps"] == ["focus_type"]
        assert progress["steps"][0]["receipt"]["local_input_scope_closed"] is True
        assert v.events.count((VK_CONTROL, VK_V)) == 1
        calls.append(deepcopy(error.to_reference()))
        review = persisted_review(error, progress, service)
        progress["steps"].clear()
        return _issue_main_field_approval(error, service=service, review=review,
            deadline_ns=perf_counter_ns() + 40_000_000_000, validator=lambda: True)
    install_handler(v, monkeypatch, handler)
    try:
        result = v.run(submit_search=submit)
        assert result["status"] == "completed", result.get("error")
        assert result["input_check"] == {"status": "verified", "source": "main_agent", "evidence_kind": "visual"}
        assert result["completed_steps"] == ["focus_type", "check_input"] + (["search"] if submit else [])
        assert len(calls) == 1 and "main_handoff" not in result
        assert result["field_review_resolutions"][0]["handoff"]["assessment"] == calls[0]["assessment"]
        proof = result["field_proofs"][0]
        assert proof["source"] == "main_agent" and proof["main_review"]["review"]["verdict"] == "success"
        assert calls[0]["assessment"]["adopted"] is False
        assert v.events.count((VK_CONTROL, VK_A)) == v.events.count((VK_CONTROL, VK_V)) == 1
        assert v.events.count((VK_RETURN,)) == int(submit)
        assert v.events.count("gate-click") == 1 + int(submit)
        if submit:
            assert v.calls[-1]["action_review_deadline_ns"] > old_deadline
        assert len(v.scene.requests) == 1 + int(submit)
        from app.core.input_sequence_partial import original_input_status
        from tests.test_visual_field_proof import IDENTITY
        command = {"kind": "input_sequence", "request": {"field_goal": FIELD["field_goal"], "text": TEXT,
            "clear_existing": True, "submit_search": submit}}
        assert original_input_status({"status": "returned", "command": command, "result": result}, command,
            succeeded=True, action_executed=True, target_identity=IDENTITY) == "completed"
    finally:
        service.close()
        client.close()


@pytest.mark.parametrize("damage", ["dict", "wrong_error", "validator", "expired", "too_long"])
def test_invalid_main_approval_cannot_enter_or_retype(visual_sequence, monkeypatch, damage):
    from app.execution.main_field_approval import _issue_main_field_approval
    from app.core.input_controller import VK_CONTROL, VK_V, VK_RETURN
    v = visual_sequence
    service, client = value_refusal(v, monkeypatch)
    def handler(error, **kwargs):
        if damage == "dict":
            return {"source": "main_agent", "review": main_review(error)}
        deadline = perf_counter_ns() + (61_000_000_000 if damage == "too_long" else 30_000_000_000)
        if damage == "expired": deadline = perf_counter_ns() - 1
        approval = _issue_main_field_approval(error, service=service, review=main_review(error),
            deadline_ns=deadline, validator=lambda: damage != "validator")
        if damage == "wrong_error":
            object.__setattr__(approval, "_reference_json", "{}")
        return approval
    install_handler(v, monkeypatch, handler)
    try:
        result = v.run()
        assert result["status"] == "interrupted"
        assert (VK_RETURN,) not in v.events and v.events.count((VK_CONTROL, VK_V)) == 1
        assert len(v.calls) == 1 and len(v.scene.requests) == 1
    finally:
        service.close()
        client.close()


@pytest.mark.parametrize("damage", ["downgrade_source", "source_only", "review", "artifact", "continued", "progress", "frame"])
def test_reopened_manual_receipt_requires_bound_original_review(visual_sequence, monkeypatch, damage):
    from app.execution.main_field_approval import _issue_main_field_approval
    from app.core.input_sequence_partial import original_input_status
    from tests.test_visual_field_proof import IDENTITY
    v = visual_sequence
    service, client = value_refusal(v, monkeypatch)
    def handler(error, *, progress, **kwargs):
        return _issue_main_field_approval(error, service=service,
            review=persisted_review(error, progress, service),
            deadline_ns=perf_counter_ns() + 30_000_000_000, validator=lambda: True)
    install_handler(v, monkeypatch, handler)
    try:
        result = v.run(submit_search=False)
        assert result["status"] == "completed", result.get("error")
        command = {"kind": "input_sequence", "request": {"field_goal": FIELD["field_goal"], "text": TEXT,
            "clear_existing": True, "submit_search": False}}
        if damage == "downgrade_source": result["input_check"]["source"] = "decision_visual"
        elif damage == "source_only": result.pop("field_review_resolutions")
        elif damage == "review": result["field_proofs"][0]["main_review"]["review"]["reason"] += " changed"
        elif damage == "artifact": result["field_proofs"][0]["main_review"]["artifact"]["sha256"] = "f" * 64
        elif damage == "frame": result["field_proofs"][0]["frame"]["capture_id"] = "different"
        else:
            path = v.scene.root / "agent-commands" / (v.scene.context["execution_request_id"] + ".json")
            job = json.loads(path.read_text(encoding="utf-8"))
            if damage == "continued":
                job["field_review"]["continued"] = False
                path.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
            else:
                progress = v.scene.root / job["field_review"]["packet"]["progress_snapshot"]["path"]
                progress.write_bytes(progress.read_bytes() + b" ")
        assert original_input_status({"status": "returned", "command": command, "result": result}, command,
            succeeded=True, action_executed=True, target_identity=IDENTITY) == "unknown"
    finally:
        service.close()
        client.close()


def test_main_review_does_not_approve_reanchor_candidate_or_wait_again(visual_sequence, monkeypatch):
    from app.execution.main_field_approval import _issue_main_field_approval
    from app.core.input_controller import VK_CONTROL, VK_V, VK_RETURN
    v = visual_sequence
    service, client = choice_replies(v, monkeypatch, "value", "condition_not_met")
    handlers = []
    def handler(error, *, progress, **kwargs):
        handlers.append(error)
        return _issue_main_field_approval(error, service=service,
            review=persisted_review(error, progress, service),
            deadline_ns=perf_counter_ns() + 30_000_000_000, validator=lambda: True)
    install_handler(v, monkeypatch, handler)
    try:
        result = v.run()
        assert result["status"] == "interrupted" and len(handlers) == 1
        assert result["input_check"]["source"] == "main_agent"
        assert result["error"]["code"] == "action_review_not_adoptable"
        assert v.events.count((VK_CONTROL, VK_V)) == 1 and (VK_RETURN,) not in v.events
        assert v.events.count("gate-click") == 1 and len(v.scene.requests) == 2
        assert result["automatic_retry_allowed"] is False
    finally:
        service.close()
        client.close()


@pytest.mark.parametrize("damage", ["ordinary_error", "open_scope", "unknown_typing"])
def test_only_trusted_after_type_with_closed_physical_input_can_wait(visual_sequence, monkeypatch, damage):
    from app.core.input_controller import VK_CONTROL, VK_V, VK_RETURN
    v = visual_sequence
    service, client = value_refusal(v, monkeypatch)
    original = v.scene.module.assess_visual_field
    handlers = []
    def assessment(**kwargs):
        if damage == "ordinary_error":
            raise ValueError("visual_field_requires_review")
        try:
            return original(**kwargs)
        except v.scene.module.VisualFieldReviewRequired:
            receipt = kwargs["input_receipt"]
            if damage == "open_scope": receipt["local_input_scope_closed"] = False
            else:
                receipt["response"]["data"]["visual_compound_input"]["typing_dispatch"]["text_dispatch"] = "started"
            raise
    monkeypatch.setattr(v.scene.module, "assess_visual_field", assessment)
    install_handler(v, monkeypatch, lambda *args, **kwargs: handlers.append(args))
    try:
        result = v.run()
        assert result["status"] == "interrupted" and handlers == []
        assert v.events.count((VK_CONTROL, VK_V)) == 1 and (VK_RETURN,) not in v.events
        assert len(v.calls) == 1
    finally:
        service.close()
        client.close()


@pytest.mark.parametrize("stop", ["cancel", "deadline"])
def test_stop_after_main_continue_settles_closed_prefix_without_enter(visual_sequence, monkeypatch, stop):
    from app.execution.main_field_approval import _issue_main_field_approval
    from app.core import local_keyboard_target
    from app.core.input_sequence_partial import original_input_status
    from app.core.input_controller import VK_CONTROL, VK_V, VK_RETURN
    from tests.test_visual_field_proof import IDENTITY
    v = visual_sequence
    service, client = value_refusal(v, monkeypatch)
    cancelled = [False]
    v.scene.context["cancelled"] = lambda: cancelled[0]
    def handler(error, *, progress, **kwargs):
        return _issue_main_field_approval(error, service=service,
            review=persisted_review(error, progress, service),
            deadline_ns=perf_counter_ns() + 30_000_000_000, validator=lambda: True)
    install_handler(v, monkeypatch, handler)
    original = local_keyboard_target.issue_visual_keyboard_target
    def keyboard(proof, operation, **kwargs):
        if operation == "press_key":
            if stop == "cancel": cancelled[0] = True
            else:
                observed = proof._deadline_ns + 1
                monkeypatch.setattr(v.scene.module, "perf_counter_ns", lambda: observed)
                monkeypatch.setattr(input_sequence, "perf_counter_ns", lambda: observed)
        return original(proof, operation, **kwargs)
    monkeypatch.setattr(local_keyboard_target, "issue_visual_keyboard_target", keyboard)
    try:
        result = v.run()
        assert result["status"] == "interrupted" and result["phase"] == "prepare_search"
        assert result["enter_preparation_failure"]["suffix_dispatch_started"] is False
        assert v.events.count((VK_CONTROL, VK_V)) == 1 and (VK_RETURN,) not in v.events
        command = {"kind": "input_sequence", "request": {"field_goal": FIELD["field_goal"], "text": TEXT,
            "clear_existing": True, "submit_search": True}}
        assert original_input_status({"status": "returned", "command": command, "result": result}, command,
            succeeded=False, action_executed=True, target_identity=IDENTITY) == "failed"
    finally:
        service.close()
        client.close()
