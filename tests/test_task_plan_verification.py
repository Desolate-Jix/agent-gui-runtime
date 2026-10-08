"""原输入事实与图像绑定优先于语义服务；离线真实认证服务不接触网络。"""
from copy import deepcopy
from hashlib import sha256

import httpx
import pytest

from app.core.json_snapshot import read_json_snapshot, write_json_snapshot
from app.execution.task_plan_backend import TaskPlanBackend
from app.execution.task_plan_verification import verify_task_plan_step
from tests.test_decision_service import setup_service
from tests.test_openai_decisions import reply
from tests.test_task_plan_contract import plan
from tests.test_task_plan_runner import TARGET, complete_original, scene


CONDITION = "The new details panel visibly contains the requested record."


def semantic_plan(count=2, condition=CONDITION):
    return plan(count=count, verification={"kind": "agent_judgment", "decision_condition": condition})


def verify(s, original, request_id="manual-verify", **kwargs):
    return verify_task_plan_step(s.runtime.backend, session_dir=s.session, run_id=s.run_id,
        request_id=request_id, execution_id=original.command_id, decision_service=s.co._decision_service, **kwargs)


def test_local_proof_success_makes_zero_decision_calls(tmp_path, monkeypatch):
    service, calls, client = setup_service(tmp_path, monkeypatch, mode="auto", conditions=[CONDITION])
    s = scene(tmp_path, monkeypatch, decision=service)
    for _ in range(2):
        complete_original(s)
        final = s.runtime.tick(force=True)
    assert final["runner_state"] == "completed"
    assert calls == []
    assert not list(tmp_path.glob("task-plan-decisions/*.json"))
    client.close()


def test_adopted_authenticated_decision_advances_without_agent_review(tmp_path, monkeypatch):
    service, calls, client = setup_service(tmp_path, monkeypatch, mode="auto", conditions=[CONDITION])
    s = scene(tmp_path, monkeypatch, source=semantic_plan(), decision=service)
    ids = []
    for _ in range(2):
        original = complete_original(s, native=False)
        ids.append(original.command_id)
        final = s.runtime.tick(force=True)
    assert final["runner_state"] == "completed"
    assert [row["execution_request_id"] for row in final["history"]] == ids
    assert all(row["judged_by"] == "decision" for row in final["history"])
    assert len(calls) == 2
    for path in tmp_path.glob("task-plan-decisions/*.json"):
        saved = read_json_snapshot(path)
        assert service.validate_result(saved["result"], **saved["binding"])
        assert saved["result"]["authorizes_action"] is False
        assert saved["binding"]["frames"][0]["capture_id"].endswith("-after")
    assert not list(tmp_path.glob("task-plan-reviews/*.json"))
    client.close()


@pytest.mark.parametrize("mode,conditions", [("shadow", [CONDITION]), ("auto", [CONDITION + " "])])
def test_shadow_or_inexact_allowlist_never_auto_advances(tmp_path, monkeypatch, mode, conditions):
    service, calls, client = setup_service(tmp_path, monkeypatch, mode=mode, conditions=conditions)
    s = scene(tmp_path, monkeypatch, source=semantic_plan(), decision=service)
    original = complete_original(s, native=False)
    result = s.runtime.tick(force=True)
    assert result["wait_reason"] == "verification_required"
    assert result["pending"]["execution_request_id"] == original.command_id
    assert result["history"] == [] and len(calls) == 1
    assert len(list(tmp_path.glob("commands/*.json"))) == 1
    client.close()


@pytest.mark.parametrize("case", ["uncertain", "timeout", "missing_key", "budget"])
def test_uncertain_timeout_missing_key_or_budget_waits(tmp_path, monkeypatch, case):
    handler = None
    if case == "timeout":
        def handler(request):
            raise httpx.ReadTimeout("synthetic offline timeout", request=request)
    service, calls, client = setup_service(tmp_path, monkeypatch, mode="auto", conditions=[CONDITION],
        response=reply(probability=.5) if case == "uncertain" else None, handler=handler, request_cap=1 if case == "budget" else 20)
    if case == "missing_key":
        monkeypatch.delenv("DECISION_TEST_KEY")
    s = scene(tmp_path, monkeypatch, source=semantic_plan(), decision=service)
    original = complete_original(s, native=False)
    result = s.runtime.tick(force=True)
    if case == "budget":
        assert result["pending"]["step_id"] == "step-1"
        original = complete_original(s, native=False)
        result = s.runtime.tick(force=True)
    assert result["wait_reason"] == "verification_required"
    assert result["pending"]["execution_request_id"] == original.command_id
    original_call_count = len(calls)
    assert original_call_count == (0 if case == "missing_key" else 1)
    for _ in range(3):
        s.runtime.control({"action": "status", "run_id": s.run_id}, "repeat-status")
        s.runtime.tick(force=True)
        assert verify(s, original)["status"] == "verification_required"
    assert len(calls) == original_call_count
    client.close()


def test_disabled_service_or_no_semantic_condition_stays_review_without_call(tmp_path, monkeypatch):
    source = plan(verification={"kind": "agent_judgment"})
    service, calls, client = setup_service(tmp_path, monkeypatch, mode="off")
    s = scene(tmp_path, monkeypatch, source=source, decision=service)
    complete_original(s)
    assert s.runtime.tick(force=True)["wait_reason"] == "verification_required"
    assert calls == []
    client.close()


@pytest.mark.parametrize("field", ["after_sha256", "expected", "after_capture_rechecked", "baseline", "samples"])
def test_invalid_native_proof_never_falls_back_to_decision(tmp_path, monkeypatch, field):
    service, calls, client = setup_service(tmp_path, monkeypatch, mode="auto", conditions=[CONDITION])
    s = scene(tmp_path, monkeypatch, decision=service)
    patch = {"after_sha256": "a" * 64, "expected": {"text": "Other", "control_type": "Text"},
             "after_capture_rechecked": False, "baseline": {"status": "matched"}, "samples": []}
    complete_original(s, proof_patch={field: patch[field]})
    assert s.runtime.tick(force=True)["wait_reason"] == "verification_required"
    assert calls == []
    assert len(list(tmp_path.glob("commands/*.json"))) == 1
    client.close()


@pytest.mark.parametrize("mutation", ["command", "receipt", "image", "wrong_target", "before_as_after"])
def test_original_binding_failure_blocks_semantic_calls(tmp_path, monkeypatch, mutation):
    service, calls, client = setup_service(tmp_path, monkeypatch, mode="auto", conditions=[CONDITION])
    s = scene(tmp_path, monkeypatch, source=semantic_plan(), decision=service)
    original = complete_original(s, native=False, identity={**TARGET, "process_create_time": 44.0} if mutation == "wrong_target" else None)
    command_path = tmp_path / "commands" / (original.command_id + ".json")
    receipt_path = tmp_path / "responses" / command_path.name
    if mutation == "command":
        command = read_json_snapshot(command_path)
        command["request"]["goal"] = "Other target"
        write_json_snapshot(command_path, command)
    elif mutation == "receipt":
        receipt = read_json_snapshot(receipt_path)
        receipt["command"]["request"]["goal"] = "Other target"
        write_json_snapshot(receipt_path, receipt)
    elif mutation == "image":
        original.after.write_bytes(original.after.read_bytes() + b"changed")
    elif mutation == "before_as_after":
        receipt = read_json_snapshot(receipt_path)
        receipt["observation"].update(image_path=str(original.before), sha256=sha256(original.before.read_bytes()).hexdigest())
        write_json_snapshot(receipt_path, receipt)
    result = s.runtime.tick(force=True)
    assert result["wait_reason"] == ("result_unknown" if mutation in {"command", "receipt"} else "verification_required")
    assert result["history"] == [] and calls == []
    assert len(list(tmp_path.glob("commands/*.json"))) == 1
    client.close()


def test_success_after_cancel_does_not_dispatch_next(tmp_path, monkeypatch):
    service, calls, client = setup_service(tmp_path, monkeypatch, mode="auto", conditions=[CONDITION])
    s = scene(tmp_path, monkeypatch, source=semantic_plan(), decision=service)
    original = complete_original(s, native=False)
    real_evaluate = service.evaluate
    def cancel_during(**binding):
        s.runtime.backend.cancel(s.run_id, "cancel-during-response")
        return real_evaluate(**binding)
    monkeypatch.setattr(service, "evaluate", cancel_during)
    first = s.runtime.tick(force=True)
    assert first["wait_reason"] == "verification_required" and first["status"] == "cancel_requested"
    final = s.runtime.control({"action": "cancel", "run_id": s.run_id}, "cancel-final")
    final = s.runtime.tick(force=True)
    assert final["runner_state"] == "cancelled"
    assert final["history"][0]["action_executed"] is True
    assert final["history"][0]["execution_request_id"] == original.command_id
    assert len(calls) == 1 and len(list(tmp_path.glob("commands/*.json"))) == 1
    client.close()


def test_unauthenticated_success_remains_pending(tmp_path, monkeypatch):
    service, calls, client = setup_service(tmp_path, monkeypatch, mode="auto", conditions=[CONDITION])
    monkeypatch.setattr(service, "validate_result", lambda *args, **kwargs: False)
    s = scene(tmp_path, monkeypatch, source=semantic_plan(), decision=service)
    complete_original(s, native=False)
    result = s.runtime.tick(force=True)
    assert result["wait_reason"] == "verification_required"
    assert result["history"] == [] and len(calls) == 1
    client.close()


def test_player_visible_is_not_playing(tmp_path, monkeypatch):
    condition = "The requested video visibly progresses in playback."
    service, calls, client = setup_service(tmp_path, monkeypatch, mode="auto", conditions=[condition], response=reply(probability=.01))
    s = scene(tmp_path, monkeypatch, source=semantic_plan(condition=condition), decision=service)
    complete_original(s, native=False)
    result = s.runtime.tick(force=True)
    assert result["runner_state"] == "failed"
    assert result["history"][0]["verdict"] == "failure"
    assert len(list(tmp_path.glob("commands/*.json"))) == 1 and len(calls) == 1
    client.close()


def test_agent_review_settles_once_and_requires_original_wait_to_continue(tmp_path, monkeypatch):
    s = scene(tmp_path, monkeypatch, source=plan(verification={"kind": "agent_judgment"}))
    original = complete_original(s)
    waiting = s.runtime.tick(force=True)
    request = {"action": "review", "run_id": s.run_id, "execution_request_id": original.command_id,
               "step_id": "step-0", "verdict": "success", "reason": "Original frame shows the expected record",
               "evidence_sha256": original.capture["sha256"]}
    reviewed = s.runtime.control(request, "agent-review")
    assert reviewed["wait_reason"] == "verification_required"
    assert reviewed["status"] == "ready" and reviewed["history"][0]["judged_by"] == "agent"
    assert len(list(tmp_path.glob("commands/*.json"))) == 1
    assert s.runtime.control(request, "agent-review")["status"] == "ready"
    assert len(s.runtime.backend.status(s.run_id)["history"]) == 1
    with pytest.raises(ValueError, match="wait_id_mismatch"):
        s.runtime.control({"action": "continue", "run_id": s.run_id, "wait_id": "wrong"}, "bad-resume")
    continued = s.runtime.control({"action": "continue", "run_id": s.run_id,
                                  "wait_id": waiting["wait"]["wait_id"]}, "continue-original")
    if continued["pending"] is None:
        continued = s.runtime.tick(force=True)
    assert continued["pending"]["step_id"] == "step-1"
    assert len(list(tmp_path.glob("commands/*.json"))) == 2


def test_review_cannot_turn_unknown_input_into_success(tmp_path, monkeypatch):
    s = scene(tmp_path, monkeypatch)
    original = complete_original(s, status="partial")
    s.runtime.tick(force=True)
    with pytest.raises(ValueError, match="original_input_unverified"):
        s.runtime.control({"action": "review", "run_id": s.run_id, "execution_request_id": original.command_id,
                           "step_id": "step-0", "verdict": "success", "reason": "Observed panel",
                           "evidence_sha256": original.capture["sha256"]}, "invalid-review")
    assert s.runtime.backend.status(s.run_id)["history"] == []


def test_verification_same_id_is_idempotent_after_success(tmp_path, monkeypatch):
    s = scene(tmp_path, monkeypatch, source=plan(count=1))
    original = complete_original(s)
    first = verify(s, original)
    assert first["status"] == "completed"
    repeated = verify(s, original)
    assert repeated == first
    assert len(repeated["history"]) == 1


def test_nonfinite_native_timing_cannot_prove_stability(tmp_path, monkeypatch):
    s = scene(tmp_path, monkeypatch)
    original = complete_original(s)
    path = tmp_path / "responses" / (original.command_id + ".json")
    receipt = read_json_snapshot(path)
    receipt["result"]["observation"]["condition"]["samples"][-1]["elapsed_ms"] = "not-a-time"
    write_json_snapshot(path, receipt)
    assert s.runtime.tick(force=True)["wait_reason"] == "verification_required"


def test_backend_rejects_receipt_only_fabricated_success(tmp_path, monkeypatch):
    s = scene(tmp_path, monkeypatch)
    original = complete_original(s, status="unknown")
    receipt_path = tmp_path / "responses" / (original.command_id + ".json")
    result = {"run_id": s.run_id, "step_id": "step-0", "execution_request_id": original.command_id,
              "plan_id": s.first["plan_id"], "plan_sha256": s.first["plan_sha256"], "target_identity": TARGET,
              "verdict": "success", "judged_by": "native_condition", "original_input_status": "completed",
              "evidence_refs": [{"path": receipt_path.relative_to(tmp_path).as_posix(), "sha256": sha256(receipt_path.read_bytes()).hexdigest()}]}
    with pytest.raises(ValueError, match="verification"):
        s.runtime.backend.record_verified_result(s.run_id, "fabricated-success", original.command_id, result)
    assert s.runtime.backend.status(s.run_id)["history"] == []


@pytest.mark.parametrize("field,value", [("step_id", "other-step"), ("evidence_sha256", "a" * 64)])
def test_agent_review_requires_original_step_and_after_image(tmp_path, monkeypatch, field, value):
    s = scene(tmp_path, monkeypatch, source=plan(verification={"kind": "agent_judgment"}))
    original = complete_original(s)
    s.runtime.tick(force=True)
    request = {"action": "review", "run_id": s.run_id, "execution_request_id": original.command_id,
               "step_id": "step-0", "verdict": "success", "reason": "Original after evidence",
               "evidence_sha256": original.capture["sha256"], field: value}
    with pytest.raises(ValueError, match="review_binding_mismatch"):
        s.runtime.control(request, "wrong-evidence-review")
    assert s.runtime.backend.status(s.run_id)["history"] == []


def test_evidence_mutation_after_settlement_breaks_repeat_verification(tmp_path, monkeypatch):
    s = scene(tmp_path, monkeypatch, source=plan(count=1))
    original = complete_original(s)
    assert verify(s, original)["status"] == "completed"
    original.after.write_bytes(original.after.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="original_evidence_changed"):
        verify(s, original)
    assert len(s.runtime.backend.status(s.run_id)["history"]) == 1


def test_backend_requires_authenticated_semantic_provenance(tmp_path, monkeypatch):
    s = scene(tmp_path, monkeypatch, source=semantic_plan())
    original = complete_original(s, native=False)
    uncertain = verify(s, original, "uncertain-original")
    result = deepcopy(uncertain["verification_results"]["uncertain-original"])
    result.update(verdict="success", judged_by="decision", reason="authenticated_decision")
    with pytest.raises(ValueError, match="decision_evidence_missing"):
        s.runtime.backend.record_verified_result(s.run_id, "forged-decision", original.command_id, result)
    assert s.runtime.backend.status(s.run_id)["history"] == []
