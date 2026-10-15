"""真实 Jobs、组合输入、模型服务与原计划审核续行，仅替换桌面和 HTTP 边界。"""
from copy import deepcopy
import json
from time import monotonic, sleep

import httpx
import pytest

from app.core.json_snapshot import read_json_snapshot, write_json_snapshot
from app.execution import input_sequence
from app.execution.task_plan_admission import TaskPlanRuntime
from app.judgment import DecisionService, OpenAIDecisionsProvider
from app.learning_memory.workflow_runtime import WorkflowRuntime
from app.vision import agent_command_jobs
from app.vision.grounding_handoff import GroundingHandoffStore
from app.vision.recognition_source import RecognitionSourceConfig
from tests.test_luna_choice_review_provider import decision_body, response_body
from tests.test_visual_field_proof import scene, FIELD, TEXT, IDENTITY
from tests.test_visual_input_no_uia import visual_sequence


def wait_for(jobs, execution, wanted):
    end = monotonic() + 5
    while monotonic() < end:
        state = jobs.get(execution)
        if state["status"] == wanted:
            return state
        if state["status"] in {"failed", "cancelled", "completed"}:
            pytest.fail(f"Unexpected {state['status']}: {state.get('error') or (state.get('result') or {}).get('error')}")
        sleep(.005)
    pytest.fail(f"Not {wanted}: {state}")


@pytest.mark.parametrize("submit", [False, True])
def test_same_runtime_plan_resumes_real_field_input_from_original_review(visual_sequence, monkeypatch, submit):
    from app.core.input_controller import VK_CONTROL, VK_A, VK_V, VK_RETURN
    v = visual_sequence
    collected = {}
    def collect(coordinator, target, request, **kwargs):
        collected.update(coordinator=coordinator, target=target, request=request)
    with monkeypatch.context() as temporary:
        temporary.setattr(input_sequence, "run_input_sequence", collect)
        v.run(submit_search=submit)
    coordinator = collected["coordinator"]
    calls = []
    primary_count = [0]
    def respond(request):
        calls.append(request)
        if request.url.path.endswith("/responses"):
            body = response_body("condition_not_met")
        else:
            primary_count[0] += 1
            body = decision_body()
            if primary_count[0] != 2:
                answer = body["answers"][0]
                answer.update(choice="condition_met", confidence=.99)
                for row in answer["probabilities"]:
                    row["probability"] = .99 if row["value"] == "condition_met" else .005
        return httpx.Response(200, json=body, headers={"x-request-id": "offline-" + str(len(calls))})
    client = httpx.Client(transport=httpx.MockTransport(respond))
    condition = "The fresh input text is present in the intended field."
    profile = v.scene.service.profile.model_copy(update={"decision_format": "choice", "ordinary_review": "on_reject",
        "auto_conditions": (*v.scene.service.profile.auto_conditions, condition)})
    service = DecisionService(v.scene.root, profile=profile,
        provider=OpenAIDecisionsProvider(api_key_env="VISUAL_FIELD_TEST_KEY", client=client))
    # 复用旧夹具的真实候选服务，只将其传输与配置指向本次统一离线服务。
    method = coordinator.execute_local_step.__func__
    closure = {name: cell.cell_contents for name, cell in zip(method.__code__.co_freevars, method.__closure__)}
    closure["candidate_service"].profile = service.profile
    closure["candidate_service"]._provider = service._provider
    v.scene.context["service"] = coordinator._decision_service = service
    coordinator._memory_library_root = v.scene.root / "unused-learning"
    for directory in ("commands", "responses", "agent-commands"):
        (v.scene.root / directory).mkdir(exist_ok=True)
    store = GroundingHandoffStore(v.scene.root, owner_id="integration-owner")
    jobs = agent_command_jobs.AgentCommandJobs(coordinator, store, lambda: deepcopy(v.scene.focus["capture"]),
        RecognitionSourceConfig(source="agent_current"))
    runtime = TaskPlanRuntime(v.scene.root, coordinator, owner_id="integration-owner", agent_jobs=jobs,
        target_identity=lambda: deepcopy(IDENTITY), reviewed_runtime=WorkflowRuntime(v.scene.root, coordinator))
    from app.core import visual_compound_input
    summaries = []
    prepare = visual_compound_input.prepare_visual_compound_input
    def reviewed_input(manager, point, review):
        summaries.append(deepcopy(review["assessment"]))
        return prepare(manager, point, review)
    monkeypatch.setattr(visual_compound_input, "prepare_visual_compound_input", reviewed_input)
    def physical(proxy, **kwargs):
        # 合成定位已由夹具提供；真实候选/输入/键盘门禁及原子 Jobs 账本不替换。
        job = proxy._job
        with jobs._condition:
            index = jobs._begin_dispatch(job, kwargs["operation"])
        local = coordinator.execute_local_step(**kwargs)
        if kwargs.get("grounding_target") is None:
            local["response"]["data"]["action_assessment"] = deepcopy(summaries[-1])
            local["response"]["data"]["recognition_plan"]["recommended_target"] = deepcopy(
                summaries[-1]["evaluation_request"]["action"]["source_candidate"])
        jobs._record_receipt(job, local, kwargs["operation"], index)
        return local
    monkeypatch.setattr(agent_command_jobs._CoordinatorProxy, "execute_local_step", physical)
    verification = {"kind": "agent_judgment", "decision_condition": condition}
    plan = {"schema_version": "task_plan.v3", "title": "Resume the original field", "goal": "Fill the intended field",
        "inputs": {}, "steps": [{"step_id": "field", "action": {"kind": "input_sequence", **collected["request"]},
            "verification": verification}], "completion": {"step_id": "field", "verification": verification}}
    try:
        initial = runtime.control({"action": "start", "plan": plan}, "start-original-plan")
        pending = initial["pending"]
        execution = pending["execution_request_id"]
        command = read_json_snapshot(v.scene.root / "commands" / (execution + ".json"))
        first = jobs.start(execution, command, collected["target"],
            {"image_transport": "supported", "current_vision": "supported"})
        write_json_snapshot(v.scene.root / "responses" / (execution + ".json"),
            {"status": "returned", "command": command, "result": first})
        paused = wait_for(jobs, execution, "awaiting_field_review")
        assert len(calls) == 3 and len(paused["dispatch_attempts"]) == 1
        waiting = runtime.tick(force=True)
        assert waiting["review_packet"]["schema"] == "field_review_packet.v1"
        assert waiting["history"] == [] and waiting["pending"] == pending
        answer = {**waiting["caller_controls"]["review"]["request"], "verdict": "success",
            "reason": "The original image contains the exact input text."}
        reviewed = runtime.control(answer, "main-reviewed-original")
        assert jobs.get(execution)["status"] == "awaiting_field_review"
        assert len(v.calls) == 1 and len(calls) == 3
        runtime.control(reviewed["caller_controls"]["continue"]["request"], "continue-original")
        finished = wait_for(jobs, execution, "completed")
        assert finished["result"]["input_check"]["source"] == "main_agent"
        assert finished["result"]["field_proofs"][0]["main_review"]["review"] == answer
        assert finished["field_review"]["continued"] is True
        terminal = runtime.tick(force=True)
        assert terminal["runner_state"] == "completed", terminal
        assert terminal["pending"] is None and len(terminal["history"]) == 1
        assert terminal["history"][0]["original_input_status"] == "completed"
        assert terminal["history"][0]["execution_request_id"] == execution
        assert len(list((v.scene.root / "commands").glob("trial-exec-*.json"))) == 1
        assert v.events.count((VK_CONTROL, VK_A)) == v.events.count((VK_CONTROL, VK_V)) == 1
        assert v.events.count((VK_RETURN,)) == int(submit)
        assert v.events.count("gate-click") == 1 + int(submit)
        assert len(calls) == 4 + int(submit)
        assert all(json.loads(call.content).get("model") == "gpt-6-luna" for call in calls)
    finally:
        jobs.close(timeout=1)
        service.close()
        client.close()
