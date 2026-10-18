from app.learning_memory.workflow_verification import verify_step


def step(kind="field_equals", expected=None):
    return {"step_id": "fill", "action": {"kind": "input_sequence"},
            "verification": {"kind": kind, "expected": expected or {"source": "input", "name": "wanted"}, "output_name": "actual"},
            "outputs": [{"name": "actual", "type": "text"}]}


def receipt(status="completed"):
    return {"run_id": "run-new", "step_id": "fill", "request_id": "review-1", "execution_request_id": "exec-1",
            "status": status, "action_executed": status == "completed", "pre_capture_id": "cap-before",
            "post_capture_id": "cap-after", "post_capture_sha256": "a" * 64,
            "scope_id": "detail-pane",
            "window_identity": {"handle": 91, "process_id": 42, "process_create_time": 17.5},
            "evidence_ref": "receipt-sha256:abc"}


def observation(value="new value"):
    return {"run_id": "run-new", "step_id": "fill", "request_id": "review-1", "execution_request_id": "exec-1",
            "capture_id": "cap-after", "capture_sha256": "a" * 64,
            "scope_id": "detail-pane",
            "window_identity": {"handle": 91, "process_id": 42, "process_create_time": 17.5},
            "complete": True, "source": "uia_value", "values": {"field_value": value}, "evidence_ref": "capture-sha256:def"}


def test_current_field_value_verified_and_captured_as_run_local_output():
    result = verify_step(step(), inputs={"wanted": "new value"}, outputs={}, receipt=receipt(), observation=observation())
    assert result["verdict"] == "success"
    assert result["source"] == "rule"
    assert result["outputs"] == {"actual": "new value"}
    assert result["observations"]["capture_id"] == "cap-after"
    assert result["evidence_refs"] == ["receipt-sha256:abc", "capture-sha256:def"]


def test_click_receipt_without_changed_result_is_not_success():
    result = verify_step(step(), inputs={"wanted": "new value"}, outputs={}, receipt=receipt(), observation=observation("old value"))
    assert result["verdict"] == "failure"
    assert result["outputs"] == {}
    assert verify_step(step(), inputs={"wanted": "new value"}, outputs={}, receipt=receipt(), observation={})["verdict"] == "uncertain"


def test_old_capture_or_run_output_never_fills_missing_current_evidence():
    stale = observation()
    stale["capture_id"] = "cap-before"
    assert verify_step(step(), inputs={"wanted": "new value"}, outputs={}, receipt=receipt(), observation=stale)["verdict"] == "uncertain"
    stale = observation()
    stale["window_identity"]["process_create_time"] = 18.5
    assert verify_step(step(), inputs={"wanted": "new value"}, outputs={}, receipt=receipt(), observation=stale)["verdict"] == "uncertain"
    target = step(expected={"source": "output", "step_id": "read", "name": "fresh"})
    outputs = {"read.fresh": {"run_id": "run-old", "value": "new value"}}
    assert verify_step(target, inputs={}, outputs=outputs, receipt=receipt(), observation=observation())["verdict"] == "uncertain"
    outputs["read.fresh"]["run_id"] = "run-new"
    assert verify_step(target, inputs={}, outputs=outputs, receipt=receipt(), observation=observation())["verdict"] == "success"


def test_failed_receipt_and_pending_are_distinct():
    assert verify_step(step(), inputs={"wanted": "new value"}, outputs={}, receipt=receipt("failed"), observation=observation())["verdict"] == "failure"
    assert verify_step(step(), inputs={"wanted": "new value"}, outputs={}, receipt=receipt("pending"), observation=observation())["verdict"] == "uncertain"


def test_target_absence_requires_current_boolean_evidence():
    target = step("target_absent")
    target["verification"] = {"kind": "target_absent"}
    target["outputs"] = []
    observed = observation()
    observed["values"] = {"target_present": False}
    assert verify_step(target, inputs={}, outputs={}, receipt=receipt(), observation=observed)["verdict"] == "success"
    observed["values"] = {"target_present": True}
    assert verify_step(target, inputs={}, outputs={}, receipt=receipt(), observation=observed)["verdict"] == "failure"
    observed["values"] = {}
    assert verify_step(target, inputs={}, outputs={}, receipt=receipt(), observation=observed)["verdict"] == "uncertain"
    observed["values"] = {"target_present": False}
    observed["complete"] = False
    assert verify_step(target, inputs={}, outputs={}, receipt=receipt(), observation=observed)["verdict"] == "uncertain"
    observed["complete"] = True
    observed["scope_id"] = "other-pane"
    assert verify_step(target, inputs={}, outputs={}, receipt=receipt(), observation=observed)["verdict"] == "uncertain"


def test_agent_judgment_and_unavailable_text_read_remain_uncertain():
    target = step("agent_judgment")
    target["verification"] = {"kind": "agent_judgment"}
    target["outputs"] = []
    assert verify_step(target, inputs={}, outputs={}, receipt=receipt(), observation=observation())["verdict"] == "uncertain"
    text = step("text_contains", {"source": "constant", "value": "fresh"})
    text["outputs"] = []
    text["verification"].pop("output_name")
    observed = observation()
    observed["values"] = {}
    assert verify_step(text, inputs={}, outputs={}, receipt=receipt(), observation=observed)["verdict"] == "uncertain"


def test_required_output_type_and_capture_hash_must_be_verified():
    target = step()
    target["outputs"] = [{"name": "actual", "type": "number"}]
    observed = observation(True)
    assert verify_step(target, inputs={"wanted": True}, outputs={}, receipt=receipt(), observation=observed)["verdict"] == "uncertain"
    target["outputs"] = [{"name": "actual", "type": "text"}]
    observed = observation("new value")
    observed["capture_sha256"] = ""
    assert verify_step(target, inputs={"wanted": "new value"}, outputs={}, receipt=receipt(), observation=observed)["verdict"] == "uncertain"


def test_old_query_detail_conflicts_with_current_expected_text():
    target = step("text_contains", {"source": "input", "name": "wanted"})
    target["outputs"] = []
    target["verification"].pop("output_name")
    observed = observation()
    observed["source"] = "visible_text"
    observed["values"] = {"text": "Result for old query"}
    result = verify_step(target, inputs={"wanted": "new query"}, outputs={}, receipt=receipt(), observation=observed)
    assert result["verdict"] == "failure"
    assert result["observations"]["source"] == "visible_text"


def test_read_spec_requires_current_source_and_declared_output():
    target = {"step_id": "fill", "action": {"kind": "read_text"},
              "read_spec": {"method": "visible_text", "output_name": "detail"},
              "outputs": [{"name": "detail", "type": "text"}]}
    observed = observation()
    observed["source"] = "visible_text"
    observed["values"] = {"text": "Current detail"}
    result = verify_step(target, inputs={}, outputs={}, receipt=receipt(), observation=observed)
    assert result["verdict"] == "success"
    assert result["outputs"] == {"detail": "Current detail"}
    observed["source"] = "uia_value"
    assert verify_step(target, inputs={}, outputs={}, receipt=receipt(), observation=observed)["verdict"] == "uncertain"
    observed["source"] = "visible_text"
    target["outputs"] = [{"name": "detail", "type": "boolean"}]
    assert verify_step(target, inputs={}, outputs={}, receipt=receipt(), observation=observed)["verdict"] == "uncertain"


def test_observation_request_binding_rejects_late_reply():
    observed = observation()
    observed["execution_request_id"] = "exec-previous"
    assert verify_step(step(), inputs={"wanted": "new value"}, outputs={}, receipt=receipt(), observation=observed)["verdict"] == "uncertain"
