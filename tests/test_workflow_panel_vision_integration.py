import json
from copy import deepcopy

import pytest

from tests.test_workflow_run_panel import panel, connect, wait, receipt
from tests.test_workflow_runtime import runtime_scene
from tests.test_workflow_trial import services, WORKFLOW
from tests.test_agent_command_jobs import env, _wait


@pytest.mark.parametrize("read_only", [False, True])
def test_panel_declaration_passes_real_runtime_runner_trial_to_original_command(tmp_path, runtime_scene, read_only):
    runtime, trials, run, session, _ = runtime_scene
    saved = trials.programs.load(WORKFLOW, run["program_id"])
    if read_only:
        definition = deepcopy(saved["definition"])
        definition["steps"][0]["action"] = {"kind": "read_text", "goal": "Read current result"}
        saved = trials.programs.save(WORKFLOW, saved["content_sha256"], definition, "save-read")
        run = trials.start(WORKFLOW, saved["program_id"], "search", {"query": "current"}, "start-read")
    app, widget, clients = panel(tmp_path)
    client = connect(app, widget, clients)
    widget._accept_status({**client.connect(), "recognition_source": "agent_current"})
    widget.vision_checkbox.setChecked(True)
    widget.set_context(saved, "search")
    widget._run = deepcopy(run)
    widget._prepared_run = True
    submitted = []

    def control(request, request_id):
        submitted.append(deepcopy(request))
        return receipt(request_id, runtime.control(request, request_id))

    client.control = control
    widget.start_continuous()
    wait(app, lambda: bool(submitted) and not widget.is_busy)
    ticket = trials.status(run["run_id"])["pending"]
    original = json.loads((session / "commands" / (ticket["execution_request_id"] + ".json")).read_text(encoding="utf-8"))
    assert original == ticket["suggested_command"]
    assert submitted[0]["vision_capabilities"] == {"image_transport": "supported", "current_vision": "supported"}
    if read_only:
        assert original["kind"] == "read_text"
        assert "vision_capabilities" not in original
    else:
        assert original["kind"] == "input_sequence"
        assert original["vision_capabilities"]["image_transport"] == "supported"
        assert original["vision_capabilities"]["current_vision"] == "supported"
        assert original["vision_capabilities"]["delegate_vision"] == "unknown"
    widget.close_client()


@pytest.mark.parametrize("declared", [False, True])
def test_panel_declaration_controls_original_memory_miss_handoff_without_input(tmp_path, env, declared):
    jobs, coordinator, store = env
    app, widget, clients = panel(tmp_path)
    client = connect(app, widget, clients)
    widget._accept_status({**client.connect(), "recognition_source": "agent_current"})
    widget.vision_checkbox.setChecked(declared)
    request = widget._run_request("run", "single", widget._declared_vision_capabilities())
    reference = {"recipe_id": "target-recipe-" + "a" * 64,
                 "interface_key": "search", "state_key": "results"}
    command = {"kind": "step", "operation": "execute_recognition_plan",
               "request": {"goal": "Open", "target_memory": reference}}
    coordinator.prepare_memory_grounding = lambda **kwargs: (
        None, {"status": "miss", "reason": "visible_row_missing", "grounding_goal": "Open current result"})
    if not declared:
        jobs.capture_current = lambda: pytest.fail("unknown capabilities must not capture for handoff")
    jobs.start("panel-memory-miss", command, {"handle": 100, "process_id": 200},
               request.get("vision_capabilities", {}))
    status = _wait(jobs, "panel-memory-miss", "awaiting_grounding" if declared else "failed")
    if declared:
        assert status["pending_grounding"]["goal"] == "Open current result"
        jobs.cancel("panel-memory-miss")
        _wait(jobs, "panel-memory-miss", "cancelled")
    else:
        assert status["error"]["code"] == "capability_unknown"
        assert status["pending_grounding"] is None and status["action_executed"] is False
    assert coordinator.calls == []
    widget.close_client()
