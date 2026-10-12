"""显式观察复用原等待；仅替换正式截图边界，保留真实持久和结算路径。"""
from copy import deepcopy
from hashlib import sha256
import importlib
from pathlib import Path

from PIL import Image
import pytest

from app.core.json_snapshot import read_json_snapshot, write_json_snapshot
from tests.test_task_plan_adaptive_review import OfflineAssessment, adaptive_plan, review_request
from tests.test_task_plan_runner import complete_original, scene


def module():
    name = "app.execution.task_plan_manual_observation"
    if importlib.util.find_spec(name) is None:
        pytest.fail("explicit manual observation is not implemented")
    return importlib.import_module(name)


def observe_request(s, waiting, *, logical="manual-one"):
    packet = waiting["review_packet"]
    return {"action": "observe", "run_id": s.run_id, "step_id": packet["step_id"],
        "execution_request_id": packet["execution_request_id"], "wait_id": packet["wait_id"],
        "observation_request_id": logical, "review_packet_sha256": packet["packet_sha256"],
        "evidence_set_sha256": packet["evidence_set_sha256"], "assessment_round": packet["assessment_round"]}


def manual_scene(tmp_path, monkeypatch, *, source=None):
    m = module()
    service = OfflineAssessment()
    s = scene(tmp_path, monkeypatch, source=source or adaptive_plan(), decision=service)
    original = complete_original(s, native=False)
    original.capture.update(image_size={"width": 80, "height": 60}, window_rect=[0, 0, 80, 60])
    write_json_snapshot(tmp_path / "responses" / (original.command_id + ".json"), original.receipt)
    waiting = s.runtime.tick(force=True)
    calls, clock = [], [0]
    monkeypatch.setattr(m, "now_ns", lambda: clock[0])
    def capture(coordinator, **kwargs):
        calls.append(kwargs["observation_id"])
        assert kwargs["cancelled"]() is False
        path = tmp_path / "task-plan-observations" / (kwargs["observation_id"] + ".png")
        path.parent.mkdir(exist_ok=True)
        Image.new("RGB", (80, 60), (len(calls), 20, 30)).save(path)
        return {"observation_id": kwargs["observation_id"], "capture_elapsed_ms": 1,
            "frame": {"capture_id": kwargs["observation_id"], "image_path": str(path),
                "sha256": sha256(path.read_bytes()).hexdigest(), "role": "observation",
                "window_identity": deepcopy(s.target)}}
    monkeypatch.setattr(m, "capture_followup", capture)
    return s, original, waiting, calls, clock


def snapshot(s):
    return s.runtime._review_snapshot(s.runtime.runner.status(s.run_id))


def test_observe_revises_packet_without_input_or_inference_and_bound_review_continues(tmp_path, monkeypatch):
    m = module()
    s, original, waiting, calls, _ = manual_scene(tmp_path, monkeypatch)
    raw = (tmp_path / "responses" / (original.command_id + ".json")).read_bytes()
    request = observe_request(s, waiting)
    result = m.observe_task_plan(s.runtime, request)
    current = snapshot(s)
    packet, previous = current["review_packet"], waiting["review_packet"]
    assert result["status"] == "captured" and packet["schema"] == "review_packet.v3"
    assert packet["after"] == previous["after"] and packet["latest_observation"]["role"] == "observation"
    assert packet["packet_revision"] == 1 and packet["previous_packet_sha256"] == previous["packet_sha256"]
    assert packet["packet_ancestors"] == [previous["packet_sha256"]]
    assert packet["assessment_basis"] == {"packet_sha256": previous["packet_sha256"],
        "evidence_set_sha256": previous["evidence_set_sha256"], "assessment_round": 0}
    assert packet["assessment"] == previous["assessment"] and packet["assessment_round"] == 0
    assert packet["evidence_set_sha256"] != previous["evidence_set_sha256"]
    assert current["wait"] == waiting["wait"] and current["history"] == []
    assert len(s.co._decision_service.calls) == 1 and len(list(tmp_path.glob("commands/*.json"))) == 1
    assert m.observe_task_plan(s.runtime, request) == result and len(calls) == 1
    with pytest.raises(ValueError, match="packet_binding"):
        s.runtime.control(review_request(s, waiting, original), "old-manual-review")
    reviewed = s.runtime.control(review_request(s, current, original), "new-manual-review")
    assert reviewed["status"] == "ready" and len(list(tmp_path.glob("commands/*.json"))) == 1
    history = s.runtime.backend.status(s.run_id)["history"][0]
    assert any(item["path"].endswith(".png") and item["sha256"] == packet["latest_observation"]["sha256"]
        for item in history["evidence_refs"])
    assert any("manual-observations" in item["path"] for item in history["evidence_refs"])
    assert s.runtime.control(review_request(s, current, original), "new-manual-review")["status"] == "ready"
    s.runtime.control({"action": "continue", "run_id": s.run_id, "wait_id": packet["wait_id"]}, "manual-continue")
    s.runtime.tick(force=True)
    assert len(list(tmp_path.glob("commands/*.json"))) == 2
    assert (tmp_path / "responses" / (original.command_id + ".json")).read_bytes() == raw


def test_two_manual_attempts_reopen_and_stale_binding_cannot_capture(tmp_path, monkeypatch):
    m = module()
    s, original, waiting, calls, _ = manual_scene(tmp_path, monkeypatch)
    request = observe_request(s, waiting)
    first = m.observe_task_plan(s.runtime, request)
    changed = {**request, "assessment_round": 1}
    with pytest.raises(ValueError, match="idempotency_conflict"):
        m.observe_task_plan(s.runtime, changed)
    with pytest.raises(ValueError, match="packet_binding"):
        m.observe_task_plan(s.runtime, {**request, "observation_request_id": "stale-other"})
    from app.execution.task_plan_admission import TaskPlanRuntime
    reopened = TaskPlanRuntime(tmp_path, s.co, owner_id="owner-1", target_identity=lambda: deepcopy(s.target),
        reviewed_runtime=s.reviewed)
    assert m.observe_task_plan(reopened, request) == first
    second = m.observe_task_plan(reopened, observe_request(s, snapshot(s), logical="manual-two"))
    assert second["status"] == "captured" and snapshot(s)["review_packet"]["packet_revision"] == 2
    assert snapshot(s)["review_packet"]["manual_observation_budget"] == {"limit": 2, "used": 2, "remaining": 0}
    assert snapshot(s)["review_packet"]["allowed_controls"] == ["review", "cancel"]
    with pytest.raises(ValueError, match="attempt_limit"):
        m.observe_task_plan(s.runtime, observe_request(s, snapshot(s), logical="manual-three"))
    assert len(calls) == 2


def test_reserved_crash_is_unknown_never_recaptured_and_blocks_review(tmp_path, monkeypatch):
    m = module()
    s, original, waiting, calls, _ = manual_scene(tmp_path, monkeypatch)
    request = observe_request(s, waiting)
    def crash(*args, **kwargs):
        raise KeyboardInterrupt("synthetic process interruption")
    monkeypatch.setattr(m, "capture_followup", crash)
    with pytest.raises(KeyboardInterrupt):
        m.observe_task_plan(s.runtime, request)
    assert m.observe_task_plan(s.runtime, request)["status"] == "unknown"
    with pytest.raises(ValueError, match="capture_unsettled"):
        s.runtime.control(review_request(s, waiting, original), "unknown-manual-review")
    with pytest.raises(ValueError, match="capture_unsettled"):
        m.observe_task_plan(s.runtime, {**request, "observation_request_id": "new-after-crash"})
    assert calls == [] and len(list(tmp_path.glob("commands/*.json"))) == 1
    assert s.runtime.control({"action": "cancel", "run_id": s.run_id}, "cancel-unknown")["status"] == "cancel_requested"


@pytest.mark.parametrize("hazard", ["cancel", "queued_cancel", "window", "evidence", "late", "review"])
def test_capture_side_changes_cannot_adopt_or_settle_original(tmp_path, monkeypatch, hazard):
    m = module()
    s, original, waiting, calls, clock = manual_scene(tmp_path, monkeypatch)
    capture = m.capture_followup
    review_errors = []
    def changed(*args, **kwargs):
        result = capture(*args, **kwargs)
        if hazard == "cancel":
            s.runtime.backend.cancel(s.run_id, "manual-cancel")
        elif hazard == "queued_cancel":
            from tests.test_task_plan_queued_cancel import queue_cancel
            queue_cancel(s)
        elif hazard == "window":
            s.target["process_create_time"] = 34
        elif hazard == "evidence":
            original.after.write_bytes(b"changed")
        elif hazard == "late":
            clock[0] = 12_000_000_000
        else:
            try:
                s.runtime.control(review_request(s, waiting, original), "concurrent-review")
            except ValueError as error:
                review_errors.append(str(error))
        return result
    monkeypatch.setattr(m, "capture_followup", changed)
    result = m.observe_task_plan(s.runtime, observe_request(s, waiting))
    if hazard == "review":
        assert result["status"] == "captured" and review_errors == ["task_plan_manual_capture_unsettled"]
    else:
        assert result["status"] == "rejected"
        assert s.runtime.backend.status(s.run_id)["history"] == []
    assert len(calls) == 1 and len(list(tmp_path.glob("commands/trial-exec-*.json"))) == 1


def test_automatic_capture_attempts_share_manual_cap_without_mutating_finished_ledger(tmp_path, monkeypatch):
    m = module()
    from tests.test_task_plan_observation import observation_scene
    from app.execution.task_plan_observation import ObservationLedger
    s, original, clock, captures = observation_scene(tmp_path, monkeypatch, unchanged=True)
    s.runtime.tick(force=True)
    clock.seconds = 1.6
    waiting = s.runtime.tick(force=True)
    ledger = ObservationLedger(s.runtime.backend, original.command_id)
    before = {path: path.read_bytes() for path in ledger.root.glob("*.json")}
    def capture(coordinator, **kwargs):
        path = tmp_path / "task-plan-observations" / "manual-shared.png"
        Image.new("RGB", (80, 60), "blue").save(path)
        return {"observation_id": kwargs["observation_id"], "capture_elapsed_ms": 1,
            "frame": {"capture_id": "manual-shared", "image_path": str(path), "sha256": sha256(path.read_bytes()).hexdigest(),
                "window_identity": deepcopy(s.target), "role": "observation"}}
    monkeypatch.setattr(m, "capture_followup", capture)
    assert m.observe_task_plan(s.runtime, observe_request(s, waiting))["status"] == "captured"
    with pytest.raises(ValueError, match="attempt_limit"):
        m.observe_task_plan(s.runtime, observe_request(s, snapshot(s), logical="over-shared-cap"))
    assert {path: path.read_bytes() for path in ledger.root.glob("*.json")} == before
    assert len(captures) == 1 and len(s.co._decision_service.calls) == 1


def test_failed_attempt_consumes_shared_limit_and_cannot_retry_same_logical_request(tmp_path, monkeypatch):
    m = module()
    s, _, waiting, calls, _ = manual_scene(tmp_path, monkeypatch)
    request = observe_request(s, waiting)
    def failed(*args, **kwargs):
        raise OSError("private capture failure")
    monkeypatch.setattr(m, "capture_followup", failed)
    first = m.observe_task_plan(s.runtime, request)
    assert first["status"] == "rejected" and "private" not in str(first)
    assert m.observe_task_plan(s.runtime, request) == first
    assert m.observe_task_plan(s.runtime, {**request, "observation_request_id": "second-failure"})["status"] == "rejected"
    budget = m.manual_observation_status(s.runtime.backend, s.runtime.backend.status(s.run_id))
    assert budget == {"manual_observation_budget": {"limit": 2, "used": 2, "remaining": 0},
        "allowed_controls": ["review", "cancel"]}
    with pytest.raises(ValueError, match="attempt_limit"):
        m.observe_task_plan(s.runtime, {**request, "observation_request_id": "after-two-failures"})
    assert calls == []


def test_manual_capture_cannot_reuse_automatic_observation(tmp_path, monkeypatch):
    m = module()
    from tests.test_task_plan_observation import observation_scene
    from app.execution.task_plan_observation import ObservationLedger
    s, original, clock, _ = observation_scene(tmp_path, monkeypatch, unchanged=True)
    s.runtime.tick(force=True)
    clock.seconds = 1.6
    waiting = s.runtime.tick(force=True)
    ledger = ObservationLedger(s.runtime.backend, original.command_id)
    old_frame = next(event["payload"]["frame"] for event in ledger.read() if event["event"] == "captured")
    monkeypatch.setattr(m, "capture_followup", lambda *args, **kwargs: {
        "observation_id": kwargs["observation_id"], "capture_elapsed_ms": 0, "frame": deepcopy(old_frame)})
    assert m.observe_task_plan(s.runtime, observe_request(s, waiting))["status"] == "rejected"
    assert snapshot(s)["review_packet"] == waiting["review_packet"]


def test_backend_rechecks_manual_records_and_includes_all_evidence(tmp_path, monkeypatch):
    m = module()
    s, original, waiting, _, _ = manual_scene(tmp_path, monkeypatch)
    m.observe_task_plan(s.runtime, observe_request(s, waiting))
    current = snapshot(s)
    original_settle = s.runtime.backend.record_verified_result
    def incomplete(*args, **kwargs):
        result = args[3]
        result["evidence_refs"] = [item for item in result["evidence_refs"]
            if not item["path"].startswith("task-plan-manual-observations/")]
        return original_settle(*args, **kwargs)
    monkeypatch.setattr(s.runtime.backend, "record_verified_result", incomplete)
    with pytest.raises(ValueError, match="manual_settlement_evidence_missing"):
        s.runtime.control(review_request(s, current, original), "incomplete-manual-review")
    assert s.runtime.backend.status(s.run_id)["history"] == []


def test_manual_review_rechecks_window_after_backend_authentication(tmp_path, monkeypatch):
    m = module()
    s, original, waiting, _, _ = manual_scene(tmp_path, monkeypatch)
    m.observe_task_plan(s.runtime, observe_request(s, waiting))
    current = snapshot(s)
    check = s.runtime.backend._evidence
    def drift(*args, **kwargs):
        value = check(*args, **kwargs)
        s.target["process_create_time"] = 34
        return value
    monkeypatch.setattr(s.runtime.backend, "_evidence", drift)
    with pytest.raises(ValueError, match="manual_window_changed"):
        s.runtime.control(review_request(s, current, original), "late-window-manual-review")
    assert s.runtime.backend.status(s.run_id)["history"] == []


def test_last_target_read_queuing_cancel_rejects_manual_adoption(tmp_path, monkeypatch):
    m = module()
    s, original, waiting, _, _ = manual_scene(tmp_path, monkeypatch)
    queued = []
    def target():
        if list((tmp_path / "task-plan-manual-observations").glob("*/capture-*.json")) and not queued:
            from tests.test_task_plan_queued_cancel import queue_cancel
            queue_cancel(s)
            queued.append(True)
        return deepcopy(s.target)
    s.runtime._target_identity = target
    result = m.observe_task_plan(s.runtime, observe_request(s, waiting))
    assert queued and result["status"] == "rejected"
    assert snapshot(s)["review_packet"] == waiting["review_packet"]


def test_real_capture_adapter_copies_owned_image_and_replays_without_owner_call(tmp_path, monkeypatch):
    m = module()
    from app.execution import task_plan_observation_capture as capture_module
    from tests.test_task_plan_observation_capture import Owner
    s = scene(tmp_path, monkeypatch, source=adaptive_plan(), decision=OfflineAssessment())
    original = complete_original(s, native=False)
    original.capture.update(image_size={"width": 80, "height": 60}, window_rect=[0, 0, 80, 60])
    write_json_snapshot(tmp_path / "responses" / (original.command_id + ".json"), original.receipt)
    waiting = s.runtime.tick(force=True)
    source = tmp_path / "captures" / "maintained-manual-current.png"
    Image.new("RGB", (80, 60), "blue").save(source)
    current = {**deepcopy(original.capture), "capture_id": "maintained-manual-current", "image_path": str(source),
        "sha256": sha256(source.read_bytes()).hexdigest()}
    owner = Owner()
    s.co._owner = owner
    def read(coordinator, handle, process_id, **kwargs):
        assert owner.active and coordinator is s.co
        assert (handle, process_id) == (11, 22) and kwargs == {"recipe": None}
        return deepcopy(current), {}
    monkeypatch.setattr(capture_module, "capture_memory_observation", read)
    request = observe_request(s, waiting)
    result = m.observe_task_plan(s.runtime, request)
    assert result["status"] == "captured" and owner.calls == 1
    assert Path(result["frame"]["image_path"]).parent == tmp_path / "task-plan-observations"
    source.write_bytes(b"unrelated producer now changes")
    assert m.observe_task_plan(s.runtime, request) == result and owner.calls == 1
    assert snapshot(s)["review_packet"]["latest_observation"]["sha256"] == current["sha256"]


def test_owner_drift_cannot_write_failed_settlement_from_another_owner(tmp_path, monkeypatch):
    m = module()
    s, _, waiting, _, _ = manual_scene(tmp_path, monkeypatch)
    capture = m.capture_followup
    def changed(*args, **kwargs):
        value = capture(*args, **kwargs)
        s.runtime.backend.owner_id = "owner-other"
        return value
    monkeypatch.setattr(m, "capture_followup", changed)
    request = observe_request(s, waiting)
    with pytest.raises(ValueError, match="owner_mismatch"):
        m.observe_task_plan(s.runtime, request)
    s.runtime.backend.owner_id = "owner-1"
    assert m.observe_task_plan(s.runtime, request)["status"] == "unknown"
    budget = m.manual_observation_status(s.runtime.backend, s.runtime.backend.status(s.run_id))
    assert budget["manual_observation_budget"] == {"limit": 2, "used": 1, "remaining": 1}
    assert budget["allowed_controls"] == ["cancel"]


def test_last_image_hash_must_finish_inside_manual_adoption_deadline(tmp_path, monkeypatch):
    m = module()
    s, _, waiting, _, clock = manual_scene(tmp_path, monkeypatch)
    original_reference = m.reference
    def late(session, path):
        value = original_reference(session, path)
        if Path(path).suffix == ".png" and list((tmp_path / "task-plan-manual-observations").glob("*/capture-*.json")):
            clock[0] = 12_000_000_000
        return value
    monkeypatch.setattr(m, "reference", late)
    assert m.observe_task_plan(s.runtime, observe_request(s, waiting))["status"] == "rejected"


def test_backend_rechecks_new_image_after_last_window_reader(tmp_path, monkeypatch):
    m = module()
    s, original, waiting, _, _ = manual_scene(tmp_path, monkeypatch)
    result = m.observe_task_plan(s.runtime, observe_request(s, waiting))
    current = snapshot(s)
    def target():
        Path(result["frame"]["image_path"]).write_bytes(b"changed during target read")
        return deepcopy(s.target)
    s.runtime._target_identity = target
    with pytest.raises(ValueError, match="(artifact_changed|evidence_changed|revision_binding)"):
        s.runtime.control(review_request(s, current, original), "late-evidence-manual-review")
    assert s.runtime.backend.status(s.run_id)["history"] == []
