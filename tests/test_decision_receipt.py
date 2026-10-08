"""真实持久化判断只结算原命令，轮询和包装字段不能改变输入事实。"""
from copy import deepcopy
import json

import pytest

from app.core.decision_receipt import project_decision_receipt
from test_decision_service import arguments, setup_service


def saved_case(tmp_path, monkeypatch):
    service, calls, client = setup_service(tmp_path, monkeypatch, mode="auto", conditions=["详情已打开"])
    from app.core.decision_configuration import freeze_decision_profile
    freeze_decision_profile(service)
    args = arguments(tmp_path, step_id="local-step-1")
    raw = service.evaluate(**args)
    profile = tmp_path / "profile.json"
    profile.write_text(service.profile.model_dump_json(), encoding="utf-8")
    command = {"kind": "step", "operation": "execute_recognition_plan", "request": {"goal": "Open"},
               "decision_check": {"phase": "after_action", "condition": args["condition"]}}
    (tmp_path / "commands").mkdir()
    (tmp_path / "commands" / "execute-1.json").write_text(json.dumps(command, ensure_ascii=False), encoding="utf-8")
    frame = args["frames"][0]
    result = {"contract_version": "local_direct_step_v1", "phase": "returned", "step_id": args["step_id"],
              "target_identity": frame["window_identity"], "response": {"success": True},
              "observation": {"status": "captured", "capture": frame},
              "decision_judgment": {**raw, "judgment_result": raw, "input_status": "returned", "effect_verified": True}}
    receipt = {"request_id": "execute-1", "status": "returned", "operation_succeeded": True,
               "task_effect_verified": False, "automatic_retry_allowed": False, "result": result}
    service.close()
    client.close()
    return receipt, profile, calls


def test_authenticated_wrapper_repeated_poll_requires_no_credentials_or_http(tmp_path, monkeypatch):
    receipt, profile, calls = saved_case(tmp_path, monkeypatch)
    monkeypatch.delenv("DECISION_TEST_KEY")
    for _ in range(2):
        projected = project_decision_receipt(deepcopy(receipt), session_dir=tmp_path, profile_path=profile)
        assert projected["task_effect_verified"] is True
        assert projected["operation_succeeded"] is True
        assert projected["decision_validation"] == "authenticated"
        assert projected["agent_review"]["automatic_retry_allowed"] is False
    assert len(calls) == 1


def test_async_status_binds_original_command_not_poll_request_id(tmp_path, monkeypatch):
    receipt, profile, calls = saved_case(tmp_path, monkeypatch)
    receipt["request_id"] = "status-2"
    receipt["result"] = {"contract_version": "agent_command.v1", "command_id": "execute-1",
                          "status": "completed", "result": receipt["result"]}
    projected = project_decision_receipt(receipt, session_dir=tmp_path, profile_path=profile)
    assert projected["task_effect_verified"] is True
    assert len(calls) == 1


def test_editing_startup_profile_does_not_change_saved_task_effect(tmp_path, monkeypatch):
    receipt, profile, calls = saved_case(tmp_path, monkeypatch)
    original = project_decision_receipt(deepcopy(receipt), session_dir=tmp_path, profile_path=profile)
    changed = json.loads(profile.read_text(encoding="utf-8"))
    changed["mode"] = "shadow"
    profile.write_text(json.dumps(changed), encoding="utf-8")
    later = project_decision_receipt(deepcopy(receipt), session_dir=tmp_path, profile_path=profile)
    assert original["task_effect_verified"] is later["task_effect_verified"] is True
    assert len(calls) == 1


@pytest.mark.parametrize("mutation", ["wrapper", "signed_result", "execution", "frame", "input_failed", "condition"])
def test_untrusted_or_mismatched_result_never_resolves_original_review(tmp_path, monkeypatch, mutation):
    receipt, profile, calls = saved_case(tmp_path, monkeypatch)
    advice = receipt["result"]["decision_judgment"]
    if mutation == "wrapper":
        advice["verdict"] = "failure"
    elif mutation == "signed_result":
        advice["judgment_result"] = {**advice["judgment_result"], "condition": "Forged condition"}
    elif mutation == "execution":
        receipt["request_id"] = "execute-other"
    elif mutation == "frame":
        receipt["result"]["observation"]["capture"]["capture_id"] = "different"
    elif mutation == "input_failed":
        receipt["result"]["response"]["success"] = False
    else:
        path = tmp_path / "commands" / "execute-1.json"
        command = json.loads(path.read_text(encoding="utf-8"))
        command["decision_check"]["condition"] = "Other condition"
        path.write_text(json.dumps(command), encoding="utf-8")
    projected = project_decision_receipt(receipt, session_dir=tmp_path, profile_path=profile)
    assert projected["task_effect_verified"] is False
    assert projected["decision_validation"] != "authenticated"
    assert len(calls) == 1
