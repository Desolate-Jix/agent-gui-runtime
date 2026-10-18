from copy import deepcopy

import pytest
from tests.test_image_verification import sample
from tests.test_workflow_verification import receipt, observation
from tests.test_workflow_trial import services, WORKFLOW, response


def test_optional_image_success_uses_public_rule_and_stale_proof_is_uncertain(tmp_path):
    from app.learning_memory.image_verification import match_image_check
    from app.learning_memory.workflow_verification import verify_step
    check, raw, _, frame = sample(tmp_path)
    step = {"step_id": "fill", "action": {"kind": "click"}, "outputs": [],
            "verification": {"kind": "agent_judgment", "image_check": check}}
    obs, rec = observation(), receipt()
    obs.update(source="image_template", values={"image_check": match_image_check(check, raw, frame)},
               capture_id=frame["capture_id"], capture_sha256=frame["sha256"])
    rec.update(post_capture_id=frame["capture_id"], post_capture_sha256=frame["sha256"])
    assert verify_step(step, inputs={}, outputs={}, receipt=rec, observation=obs)["verdict"] == "success"
    conditional = deepcopy(step)
    conditional["success_conditions"] = [{"left": {"source": "observation", "name": "review_assertion"}, "operator": "agent_assertion"}]
    assert verify_step(conditional, inputs={}, outputs={}, receipt=rec, observation=obs)["verdict"] == "uncertain"
    obs["values"]["image_check"]["capture_id"] = "stale"
    assert verify_step(step, inputs={}, outputs={}, receipt=rec, observation=obs)["verdict"] == "uncertain"


@pytest.mark.parametrize("mutation", ["outputs", "read_spec", "read_text"])
def test_image_check_cannot_replace_dynamic_read(tmp_path, mutation):
    from app.learning_memory.workflow_program import _step_rules
    check, _, _, _ = sample(tmp_path)
    step = {"action": {"kind": "click"}, "outputs": [],
            "verification": {"kind": "agent_judgment", "image_check": check}}
    if mutation == "read_text": step["action"]["kind"] = "read_text"
    else: step[mutation] = [{"name": "value", "type": "text"}] if mutation == "outputs" else {}
    with pytest.raises(ValueError, match="image"):
        _step_rules(step, {}, {}, {})


def test_valid_optional_image_schema(tmp_path):
    from app.learning_memory.workflow_program import _step_rules
    check, _, _, _ = sample(tmp_path)
    _step_rules({"action": {"kind": "click"}, "outputs": [],
                 "verification": {"kind": "agent_judgment", "image_check": check}}, {}, {}, {})


@pytest.mark.parametrize("matched", [True, False])
def test_runtime_image_observation_keeps_agent_pending_on_miss_and_replays_once(services, tmp_path, monkeypatch, matched):
    from contextlib import contextmanager
    from types import SimpleNamespace
    from hashlib import sha256
    import json
    from app.learning_memory.runtime_verification import verify_trial_step
    from app.learning_memory.measurement import load_events
    programs, trials, saved, session = services
    library = programs.library
    library._artifact_root = tmp_path
    check, raw, _, frame = sample(tmp_path)
    value = deepcopy(saved["definition"])
    value["steps"] = value["steps"][:1]
    value["steps"][0].update(outputs=[], success_conditions=[], branches={"success": None, "failure": None, "uncertain": None},
        verification={"kind": "agent_judgment", "image_check": check})
    saved = programs.save(WORKFLOW, saved["content_sha256"], value, "image-save")
    run = trials.start(WORKFLOW, saved["program_id"], "search", {"query": "new"}, "image-start")
    ticket = trials.prepare(run["run_id"], "image-prepare")
    path = response(session, ticket)
    original = json.loads(path.read_text(encoding="utf-8"))
    original["result"].update(target_identity={"target_window_handle": 1, "process_id": 2, "process_create_time": 3},
                               capture={"capture_id": "before"})
    path.write_text(json.dumps(original), encoding="utf-8")
    current = session / "current.png"
    current.write_bytes(raw)
    frame["image_path"] = str(current)
    original_pending = trials.status(run["run_id"])["pending"]
    @contextmanager
    def workspace(root): yield library
    monkeypatch.setattr("app.learning_memory.workspace.MemoryWorkspace", workspace)
    calls = []
    def capture(*args, **kwargs):
        assert kwargs == {"recipe": None}
        calls.append(True)
        return deepcopy(frame), {}
    monkeypatch.setattr("app.learning_memory.memory_observation.capture_memory_observation", capture)
    from tests.test_image_wait_early_exit import Clock
    clock = Clock()
    monkeypatch.setattr("app.learning_memory.image_verification.monotonic", clock.monotonic)
    monkeypatch.setattr("app.learning_memory.image_verification.sleep", clock.wait)
    if not matched:
        # 保留模板原件，以独立当前图模拟未到达界面。
        from PIL import Image
        Image.new("RGB", (80, 60), "black").save(current)
        frame.update(image_path=str(current), sha256=sha256(current.read_bytes()).hexdigest())
    co = SimpleNamespace(_memory_library_root=tmp_path, _owner=SimpleNamespace(call=lambda f: f()))
    request = {"action": "verify", "run_id": run["run_id"], "execution_request_id": ticket["execution_request_id"]}
    result = verify_trial_step(co, session_dir=session, request=request, request_id="image-verify")
    assert result["status"] == ("completed" if matched else "verification_required")
    state = trials.status(run["run_id"])
    assert (state["pending"] is None) is matched
    assert len(state["history"]) == (1 if matched else 0)
    if matched: assert state["history"][0]["judged_by"] == "rule"
    else:
        assert result["automatic_retry_allowed"] is False
        assert state["pending"] == original_pending
    assert verify_trial_step(co, session_dir=session, request=request, request_id="image-verify") == result
    assert len(calls) == (1 if matched else 20)
    assert clock.now == (0 if matched else 2)
    events = load_events(session, run["run_id"])
    assert len(events) == 1
    assert events[0]["status"] == ("success" if matched else "waiting")
    if not matched:
        reviewed = trials.review(run["run_id"], "agent-after-image", ticket["execution_request_id"], "success", {}, {})
        assert reviewed["status"] == "completed"
        assert reviewed["history"][0]["judged_by"] == "agent"


def test_saving_missing_reference_fails_and_old_program_stays_pinned(services, tmp_path):
    programs, _, saved, _ = services
    programs.library._artifact_root = tmp_path
    check, _, _, _ = sample(tmp_path)
    value = deepcopy(saved["definition"])
    value["steps"][1]["verification"] = {"kind": "agent_judgment", "image_check": check}
    new = programs.save(WORKFLOW, saved["content_sha256"], value, "image-save")
    assert "verification" not in programs.load(WORKFLOW, saved["program_id"])["definition"]["steps"][1]
    value["steps"][1]["verification"]["image_check"]["reference_sha256"] = "f" * 64
    with pytest.raises(FileNotFoundError):
        programs.save(WORKFLOW, new["content_sha256"], value, "missing-image")


def test_final_consumer_recomputes_pixels_and_rejects_forged_matched_proof(services, tmp_path):
    from hashlib import sha256
    import json
    from PIL import Image
    from app.learning_memory.image_verification import match_image_check
    from app.learning_memory.workflow_verification import verify_step
    from app.learning_memory.workflow_trial import _receipt_state
    programs, trials, saved, session = services
    programs.library._artifact_root = tmp_path
    check, raw, _, reference_frame = sample(tmp_path)
    value = deepcopy(saved["definition"])
    value["steps"] = value["steps"][:1]
    value["steps"][0].update(outputs=[], success_conditions=[], branches={"success": None, "failure": None, "uncertain": None},
        verification={"kind": "agent_judgment", "image_check": check})
    saved = programs.save(WORKFLOW, saved["content_sha256"], value, "consumer-save")
    run = trials.start(WORKFLOW, saved["program_id"], "search", {"query": "new"}, "consumer-start")
    ticket = trials.prepare(run["run_id"], "consumer-prepare")
    pending = trials.status(run["run_id"])["pending"]
    path = response(session, ticket)
    source = json.loads(path.read_text(encoding="utf-8"))
    source["result"].update(target_identity={"target_window_handle": 1, "process_id": 2, "process_create_time": 3}, capture={"capture_id": "before"})
    path.write_text(json.dumps(source), encoding="utf-8")
    _, terminal, _ = _receipt_state(source, path, ticket["execution_request_id"], ticket["suggested_command"])
    current = session / "current.png"
    Image.new("RGB", (80, 60), "black").save(current)
    frame = dict(reference_frame, image_path=str(current), sha256=sha256(current.read_bytes()).hexdigest())
    proof = match_image_check(check, raw, reference_frame)
    proof["capture_sha256"] = frame["sha256"]
    ids = dict(run_id=run["run_id"], step_id="search", request_id="consumer-verify", execution_request_id=ticket["execution_request_id"])
    rec = dict(ids, status="completed", action_executed=True, pre_capture_id="before", post_capture_id="fresh",
        post_capture_sha256=frame["sha256"], scope_id="image-check", window_identity=frame["window_identity"], evidence_ref=str(path.relative_to(session)))
    obs = dict(ids, capture_id="fresh", capture_sha256=frame["sha256"], scope_id="image-check", window_identity=frame["window_identity"],
        complete=True, source="image_template", values={"image_check": proof}, evidence_ref="workflow-observations/consumer-verify.json")
    envelope = dict(contract_version="workflow_observation.v1", receipt=rec, observation=obs, frame=frame,
        source_receipt_sha256=sha256(path.read_bytes()).hexdigest(), terminal_receipt=terminal)
    artifact = session / obs["evidence_ref"]
    artifact.parent.mkdir()
    artifact.write_text(json.dumps(envelope), encoding="utf-8")
    result = verify_step(saved["definition"]["steps"][0], inputs=run["inputs"], outputs={}, receipt=rec, observation=obs)
    assert result["verdict"] == "success"
    with pytest.raises(ValueError, match="image"):
        trials.record_verified_result(run["run_id"], "consumer-verify", ticket["execution_request_id"], result)
    assert trials.status(run["run_id"])["pending"] == pending
    assert trials.status(run["run_id"])["history"] == []
