"""早图未成功时只补足原观察宽限；真实运行器、回执及账本均离线验真。"""
from copy import deepcopy

import pytest

from app.core.json_snapshot import read_json_snapshot, write_json_snapshot
from tests.test_task_plan_adaptive_review import OfflineAssessment, adaptive_plan
from tests.test_task_plan_observation import observation_scene


@pytest.fixture(autouse=True)
def reject_real_input(monkeypatch):
    from app.core import input_controller
    def forbidden(*args, **kwargs):
        pytest.fail("离线观察测试不得进入真实鼠标或键盘后端")
    monkeypatch.setattr(input_controller.InputController, "_send_mouse_input", forbidden)
    monkeypatch.setattr(input_controller.InputController, "_send_key", forbidden)
    if input_controller.win32api is not None:
        monkeypatch.setattr(input_controller.win32api, "SetCursorPos", forbidden)


def grace_plan():
    value = adaptive_plan(count=1)
    value.update(schema_version="task_plan.v3", goal="Open the requested detail")
    value["completion"] = {"step_id": "step-0", "verification": deepcopy(value["steps"][0]["verification"])}
    return value


class GraceAssessment(OfflineAssessment):
    def __init__(self, *, initial="failure", final="success", error=None):
        super().__init__(error=error)
        self.initial, self.final = initial, final

    def evaluate(self, **binding):
        result = super().evaluate(**binding)
        if not isinstance(result, dict):
            return result
        verdict = self.initial if len(self.calls) == 1 else self.final
        result.update(status="completed", verdict=verdict, adopted=verdict in {"success", "failure"},
                      disposition="continue" if verdict in {"success", "failure"} else "review_required")
        return result


def grace_scene(tmp_path, monkeypatch, *, service=None, unchanged=False):
    from app.execution import task_plan_observation as observation
    service = service or GraceAssessment()
    s, original, clock, captures = observation_scene(tmp_path, monkeypatch, source=grace_plan(),
        service=service, unchanged=unchanged)
    clock.seconds = 1.4
    result = original.receipt["result"]
    result["contract_version"] = "local_direct_step_v1"
    result["response"]["data"]["result"]["click_result"] = {}
    result["observation"]["capture"]["observation_stage"] = "after_transition_observation"
    result["observation"].update(source="post_action", authorizes_action=False, render_grace_ms=2000,
        adaptive_wait={"schema": "adaptive_observation.v1", "budget_ms": 2000, "elapsed_ms": 400.0,
            "early": True, "reason": "changed_then_stable", "readiness": "unassessed",
            "effect_verified": False, "authorizes_action": False, "automatic_retry_allowed": False,
            "clock_id": observation.CLOCK_ID, "started_ns": 1_000_000_000, "deadline_ns": 3_000_000_000,
            "samples": [{"image_path": original.capture["image_path"], "sha256": original.capture["sha256"]}]})
    write_json_snapshot(tmp_path / "responses" / (original.command_id + ".json"), original.receipt)
    return s, original, clock, captures


def test_static_loading_early_frame_waits_until_original_deadline_then_succeeds(tmp_path, monkeypatch):
    s, original, clock, captures = grace_scene(tmp_path, monkeypatch)
    first = s.runtime.tick(force=True)
    assert first.get("observation_pending") is True and first["history"] == []
    assert captures == [] and len(s.co._decision_service.calls) == 1
    clock.seconds = 2.0
    assert s.runtime.tick(force=True)["observation_pending"] is True
    assert captures == []
    clock.seconds = 3.0
    final = s.runtime.tick(force=True)
    assert final["runner_state"] == "completed"
    assert len(captures) == 1 and len(s.co._decision_service.calls) == 2
    from app.judgment.evidence import prepare_request
    binding, _ = prepare_request(tmp_path, **s.co._decision_service.calls[1], include_upload=False)
    assert [item["role"] for item in binding["frames"]] == ["after"]
    assert s.co._decision_service.calls[1]["frames"][-1]["sha256"] != original.capture["sha256"]
    assert len(list(tmp_path.glob("commands/*.json"))) == 1
    assert read_json_snapshot(tmp_path / "responses" / (original.command_id + ".json")) == original.receipt
    for _ in range(3):
        s.runtime.tick(force=True)
    assert len(captures) == 1 and len(s.co._decision_service.calls) == 2


@pytest.mark.parametrize("unchanged", [False, True])
def test_permanent_failure_uses_one_final_capture_and_never_replays_input(tmp_path, monkeypatch, unchanged):
    s, _, clock, captures = grace_scene(tmp_path, monkeypatch,
        service=GraceAssessment(final="failure"), unchanged=unchanged)
    assert s.runtime.tick(force=True).get("observation_pending") is True
    clock.seconds = 3.0
    final = s.runtime.tick(force=True)
    assert final["runner_state"] == "failed" and final["history"][0]["verdict"] == "failure"
    assert len(captures) == 1
    assert len(s.co._decision_service.calls) == (1 if unchanged else 2)
    assert len(list(tmp_path.glob("commands/*.json"))) == 1


def test_initial_judgment_ending_after_deadline_still_gets_one_final_capture(tmp_path, monkeypatch):
    service = GraceAssessment()
    s, _, clock, captures = grace_scene(tmp_path, monkeypatch, service=service)
    service.during = lambda: setattr(clock, "seconds", 5.0)
    final = s.runtime.tick(force=True)
    assert final["runner_state"] == "completed"
    assert len(captures) == 1 and clock.seconds == 5.0
    assert len(service.calls) == 2


@pytest.mark.parametrize("error", ["provider", "shape", "authentication"])
def test_hard_judgment_errors_never_trigger_followup(tmp_path, monkeypatch, error):
    s, _, _, captures = grace_scene(tmp_path, monkeypatch, service=GraceAssessment(error=error))
    result = s.runtime.tick(force=True)
    assert result["runner_state"] != "completed" and result["history"] == []
    assert captures == [] and len(s.co._decision_service.calls) == 1


@pytest.mark.parametrize("mutation", ["deadline", "clock", "frame", "source", "target"])
def test_tampering_during_original_grace_never_passes(tmp_path, monkeypatch, mutation):
    s, original, clock, captures = grace_scene(tmp_path, monkeypatch)
    first = s.runtime.tick(force=True)
    assert first.get("observation_pending") is True
    if mutation in {"deadline", "clock"}:
        from app.execution import task_plan_observation as observation
        ledger = observation.ObservationLedger(s.runtime.backend, original.command_id)
        path = ledger.root / "0000.json"
        value = read_json_snapshot(path)
        value["payload"]["grace"]["deadline_ns" if mutation == "deadline" else "clock_id"] = 999
        write_json_snapshot(path, value)
    elif mutation == "frame":
        original.after.write_bytes(b"changed original frame")
    elif mutation == "source":
        path = s.runtime.backend._source_path(s.first["plan_id"])
        value = read_json_snapshot(path)
        value["plan"]["goal"] = "tampered goal"
        write_json_snapshot(path, value)
    else:
        s.target["process_create_time"] += 1
    clock.seconds = 3.0
    if mutation in {"deadline", "clock", "source"}:
        with pytest.raises(ValueError, match="task_plan_"):
            s.runtime.tick(force=True)
    else:
        result = s.runtime.tick(force=True)
        assert result["runner_state"] != "completed" and result["history"] == []
    assert captures == []


def test_queued_cancel_during_grace_never_captures_or_adopts_success(tmp_path, monkeypatch):
    from tests.test_task_plan_queued_cancel import queue_cancel
    s, original, clock, captures = grace_scene(tmp_path, monkeypatch)
    assert s.runtime.tick(force=True).get("observation_pending") is True
    command = queue_cancel(s)
    clock.seconds = 3.0
    waiting = s.runtime.tick(force=True)
    assert waiting["pending"]["execution_request_id"] == original.command_id and captures == []
    cancelled = s.runtime.control(command["request"], "queued-plan-cancel")
    write_json_snapshot(tmp_path / "responses/queued-plan-cancel.json", {"status": "returned", "command": command, "result": cancelled})
    assert s.runtime.tick(force=True)["runner_state"] == "cancelled"
    assert captures == [] and len(s.co._decision_service.calls) == 1


def test_early_authenticated_success_never_opens_a_followup_ledger(tmp_path, monkeypatch):
    s, original, _, captures = grace_scene(tmp_path, monkeypatch, service=GraceAssessment(initial="success"))
    assert s.runtime.tick(force=True)["runner_state"] == "completed"
    assert captures == [] and len(s.co._decision_service.calls) == 1
    assert not (tmp_path / "task-plan-observations" / original.command_id).exists()


def test_final_uncertain_keeps_original_main_review_bindings(tmp_path, monkeypatch):
    from tests.test_task_plan_adaptive_review import review_request
    s, original, clock, captures = grace_scene(tmp_path, monkeypatch, service=GraceAssessment(final="uncertain"))
    s.runtime.tick(force=True)
    clock.seconds = 3.0
    waiting = s.runtime.tick(force=True)
    assert waiting["review_required"] is True and waiting["review_packet"]["schema"] == "review_packet.v2"
    assert waiting["review_packet"]["after"]["sha256"] == original.capture["sha256"]
    reviewed = s.runtime.control(review_request(s, waiting, original), "review-final-grace")
    assert reviewed["status"] == "completed"
    assert len(captures) == 1 and len(s.co._decision_service.calls) == 2
    assert len(list(tmp_path.glob("commands/*.json"))) == 1


@pytest.mark.parametrize("unknown", ["capture", "assessment"])
def test_unknown_followup_claim_never_repeats_capture_or_judgment(tmp_path, monkeypatch, unknown):
    from app.execution import task_plan_observation as observation
    s, original, clock, captures = grace_scene(tmp_path, monkeypatch)
    s.runtime.tick(force=True)
    ledger = observation.ObservationLedger(s.runtime.backend, original.command_id)
    ledger.append("capture_claimed" if unknown == "capture" else "assessment_claimed", {"round": 1})
    clock.seconds = 3.0
    waiting = s.runtime.tick(force=True)
    assert waiting["review_required"] is True
    assert waiting["review_packet"]["reason"] == "task_plan_adaptive_grace_result_unknown"
    assert captures == [] and len(s.co._decision_service.calls) == 1


def test_real_capture_helper_allows_only_the_expired_wait_and_still_rejects_cancel(tmp_path, monkeypatch):
    from tests.test_task_plan_observation_capture import _setup, _call, _reject
    state = _setup(monkeypatch, tmp_path)
    record = _call(state, remaining_seconds=lambda: 0, wait_budget_exhausted=True)
    assert record["frame"]["role"] == "observation" and state.captures == 1
    other = tmp_path / "cancelled"
    other.mkdir()
    state = _setup(monkeypatch, other)
    state.stopped = True
    _reject(state, "cancelled", remaining_seconds=lambda: 0, wait_budget_exhausted=True)
    assert state.captures == 0


def test_real_capture_helper_keeps_normal_expiry_and_rejects_premature_final_capture(tmp_path, monkeypatch):
    from tests.test_task_plan_observation_capture import _setup, _reject
    state = _setup(monkeypatch, tmp_path)
    _reject(state, "timeout", remaining_seconds=lambda: 0)
    _reject(state, "budget_invalid", remaining_seconds=lambda: .5, wait_budget_exhausted=True)
    assert state.captures == 0


@pytest.mark.parametrize("drift", [False, True])
def test_grace_runner_crosses_real_capture_adapter_with_native_boundary_stubbed(tmp_path, monkeypatch, drift):
    from hashlib import sha256
    from PIL import Image
    from tests.test_task_plan_observation_capture import Owner
    from app.execution import task_plan_observation as observation, task_plan_observation_capture as helper
    s, _, clock, captures = grace_scene(tmp_path, monkeypatch)
    owner = Owner()
    s.co._owner = owner
    calls = []
    def current_frame(coordinator, handle, pid, **kwargs):
        assert owner.active and coordinator is s.co and (handle, pid) == (11, 22)
        assert kwargs == {"recipe": None}
        path = tmp_path / "captures/read-only-final.png"
        Image.new("RGB", (80, 60), "red").save(path)
        calls.append("read_only_capture")
        return {"capture_id": "fresh-final", "image_path": str(path), "sha256": sha256(path.read_bytes()).hexdigest(),
            "image_size": {"width": 80, "height": 60}, "window_identity": deepcopy(s.target),
            "window_rect": [10, 0, 90, 60] if drift else [0, 0, 80, 60]}, {}
    monkeypatch.setattr(helper, "capture_memory_observation", current_frame)
    monkeypatch.setattr(helper, "monotonic", lambda: clock.seconds)
    monkeypatch.setattr(observation, "capture_followup", helper.capture_followup)
    assert s.runtime.tick(force=True)["observation_pending"] is True
    clock.seconds = 3.0
    final = s.runtime.tick(force=True)
    assert calls == ["read_only_capture"] and owner.calls == 1 and captures == []
    assert final["runner_state"] == ("waiting" if drift else "completed")
    assert len(s.co._decision_service.calls) == (1 if drift else 2)


def test_completed_click_annotation_stays_bound_to_original_early_assessment(tmp_path, monkeypatch):
    s, original, clock, captures = grace_scene(tmp_path, monkeypatch)
    result = original.receipt["result"]
    result.update(operation="execute_recognition_plan", local_input_scope_closed=True,
        finished_at="2026-10-17T00:00:00+00:00", target_window_geometry={
            "coordinate_space": "screen_pixels", "rect_format": "ltrb", "rect": [0, 0, 80, 60]})
    click = {"clicked": True, "button": "left", "click_count": 1, "window_handle": 11,
        "window_point": {"x": 20, "y": 20}, "screen_point": {"x": 20, "y": 20},
        "down": {"button": "left", "state": "down", "cursor": {"x": 20, "y": 20}},
        "up": {"button": "left", "state": "up", "cursor": {"x": 20, "y": 20}}}
    result["response"]["data"]["result"]["click_result"] = click
    write_json_snapshot(tmp_path / "responses" / (original.command_id + ".json"), original.receipt)
    assert s.runtime.tick(force=True)["observation_pending"] is True
    assert s.co._decision_service.calls[0]["action"]["operation"] == "step_result_check"
    clock.seconds = 3.0
    assert s.runtime.tick(force=True)["runner_state"] == "completed"
    initial, final = s.co._decision_service.calls
    assert final["action"]["operation"] == "step_result_check"
    assert final["action"]["executed_click"] == initial["action"]["executed_click"]
    assert final["frames"][0]["sha256"] != initial["frames"][0]["sha256"]
    from app.judgment.evidence import prepare_request
    from app.judgment.executed_click_annotation import executed_click_metadata
    bound, _ = prepare_request(tmp_path, **final, include_upload=False)
    marker = executed_click_metadata(bound["frames"][0], (80, 60), bound["action"])
    assert marker["capture_id"] == final["frames"][0]["capture_id"]
    assert marker["source_sha256"] == final["frames"][0]["sha256"]
    assert len(captures) == 1 and len(s.co._decision_service.calls) == 2


@pytest.mark.parametrize("mutation", ["missing", "schema", "false_early"])
def test_adaptive_stage_without_valid_early_metadata_cannot_adopt_even_a_pass(tmp_path, monkeypatch, mutation):
    s, original, _, captures = grace_scene(tmp_path, monkeypatch, service=GraceAssessment(initial="success"))
    value = original.receipt["result"]["observation"]
    if mutation == "missing":
        value.pop("adaptive_wait")
    elif mutation == "schema":
        value["adaptive_wait"].pop("schema")
    else:
        value["adaptive_wait"]["early"] = False
    write_json_snapshot(tmp_path / "responses" / (original.command_id + ".json"), original.receipt)
    result = s.runtime.tick(force=True)
    assert result["runner_state"] != "completed" and result["history"] == []
    assert captures == [] and s.co._decision_service.calls == []


@pytest.mark.parametrize("complete_wait", [False, True])
def test_foreign_process_clock_is_only_rejected_when_early_budget_needs_reuse(tmp_path, monkeypatch, complete_wait):
    from app.execution import task_plan_observation as observation
    s, original, clock, captures = grace_scene(tmp_path, monkeypatch, service=GraceAssessment(initial="success"))
    if complete_wait:
        value = original.receipt["result"]["observation"]["adaptive_wait"]
        value.update(early=False, elapsed_ms=2000.0, reason="budget_exhausted")
        clock.seconds = 3.0
        write_json_snapshot(tmp_path / "responses" / (original.command_id + ".json"), original.receipt)
    monkeypatch.setattr(observation, "CLOCK_ID", "new-host-clock")
    result = s.runtime.tick(force=True)
    assert (result["runner_state"] == "completed") is complete_wait
    assert len(s.co._decision_service.calls) == int(complete_wait) and captures == []
