"""真实计划 tick 穿过正式追加采集；只替换桌面底层依赖，不访问实机。"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
import pytest

from app.core.json_snapshot import read_json_snapshot, write_json_snapshot
from app.execution import task_plan_observation, task_plan_observation_capture
from app.learning_memory import memory_observation, workflow_runtime
from tests.test_memory_observation import Manager
from tests.test_task_plan_observation import Clock, ObservingAssessment, observing_plan
from tests.test_task_plan_observation_capture import Owner
from tests.test_task_plan_runner import complete_original, scene


def _integration_scene(tmp_path, monkeypatch, *, complete_geometry=True):
    clock = Clock()
    assessment = ObservingAssessment(clock=clock)
    s = scene(tmp_path, monkeypatch, source=observing_plan(), decision=assessment)
    original = complete_original(s, native=False)
    if complete_geometry:
        original.capture.update(image_size={"width": 80, "height": 60}, window_rect=[0, 0, 80, 60])
    receipt_path = tmp_path / "responses" / (original.command_id + ".json")
    write_json_snapshot(receipt_path, original.receipt)
    owner, manager, captures = Owner(), Manager(), []
    manager.bound.handle = s.target["handle"]
    manager.bound.process_id = s.target["process_id"]
    manager.bound.rect = SimpleNamespace(left=0, top=0, right=80, bottom=60)
    s.co._owner = owner
    s.co._windows = lambda: manager
    s.co._runtime_output_root = tmp_path / "runtime-output"

    def forbidden(*args, **kwargs):
        pytest.fail("只读观察不得聚焦、输入或初始化全树扫描")

    manager.focus_window = forbidden
    s.co.execute_recognition_plan = forbidden
    s.co.input_sequence = forbidden
    monkeypatch.setattr(memory_observation, "WindowsUIAProvider", forbidden)

    class IdentityReader:
        def __init__(self, *, window_manager):
            assert owner.active and window_manager is manager

        def read_identity(self, handle):
            assert owner.active and handle == s.target["handle"]
            return {"status": "observed", "target_window_handle": handle,
                "process_id": s.target["process_id"], "process_create_time": s.target["process_create_time"],
                "executable_path": "C:\\Fixture\\fixture.exe"}

    class Screenshot:
        def __init__(self, *, window_manager, capture_dir):
            assert owner.active and window_manager is manager
            self.directory = Path(capture_dir)
            assert self.directory.is_relative_to(s.co._runtime_output_root)

        def capture_window(self, *, focus_window, purpose):
            assert owner.active and focus_window is False and purpose == "memory-current-observation"
            self.directory.mkdir(parents=True)
            path = self.directory / "current.png"
            Image.new("RGB", (80, 60), (20 * (len(captures) + 1), 0, 0)).save(path)
            captures.append({"image_path": str(path), "sha256": sha256(path.read_bytes()).hexdigest(),
                "window_rect": [0, 0, 80, 60], "image_size": {"width": 80, "height": 60}})
            clock.seconds += .125
            return {"image_path": str(path), "window_size": {"width": 80, "height": 60}, "roi": None,
                "image_width": 80, "image_height": 60, "image_size": {"width": 80, "height": 60},
                "window_rect": [0, 0, 80, 60]}

    def window_class(handle):
        assert owner.active and handle == s.target["handle"]
        return "Fixture"

    monkeypatch.setattr(memory_observation, "WindowsNativeIdentityReader", IdentityReader)
    monkeypatch.setattr(memory_observation, "ScreenshotService", Screenshot)
    monkeypatch.setattr(memory_observation, "_window_class", window_class)
    monkeypatch.setattr(task_plan_observation, "now_ns", clock.now_ns)
    monkeypatch.setattr(task_plan_observation_capture, "monotonic", lambda: clock.seconds)
    monkeypatch.setattr(workflow_runtime, "monotonic", lambda: clock.seconds)
    return SimpleNamespace(scene=s, original=original, clock=clock, assessment=assessment,
        owner=owner, captures=captures, receipt_path=receipt_path)


def test_runtime_observation_crosses_ticks_through_formal_capture_and_preserves_original_after(tmp_path, monkeypatch):
    fixture = _integration_scene(tmp_path, monkeypatch)
    s, original, clock = fixture.scene, fixture.original, fixture.clock
    original_receipt = fixture.receipt_path.read_bytes()
    original_png = original.after.read_bytes()
    original_frame = deepcopy(original.capture)
    first = s.runtime.tick(force=True)
    assert first["observation_pending"] is True and first["history"] == []
    assert first["pending"]["execution_request_id"] == original.command_id
    assert len(fixture.assessment.calls) == 1 and fixture.owner.calls == 0
    assert len(list(tmp_path.glob("commands/*.json"))) == 1
    for index in range(2):
        assert s.runtime.tick(force=True)["observation_pending"] is True
        s.runtime.control({"action": "status", "run_id": s.run_id}, "integration-wait-status-" + str(index))
    assert fixture.owner.calls == 0 and fixture.captures == []

    clock.seconds = .6
    middle = s.runtime.tick(force=True)
    assert middle["observation_pending"] is True and middle["history"] == []
    assert len(fixture.captures) == fixture.owner.calls == 1
    assert len(fixture.assessment.calls) == 1
    assert len(list(tmp_path.glob("commands/*.json"))) == 1
    assert fixture.receipt_path.read_bytes() == original_receipt
    assert original.after.read_bytes() == original_png

    clock.seconds = 1.6
    advanced = s.runtime.tick(force=True)
    assert len(fixture.captures) == fixture.owner.calls == 2
    assert len(fixture.assessment.calls) == 2
    assert advanced["history"][0]["execution_request_id"] == original.command_id
    assert advanced["history"][0]["action_executed"] is True
    assert advanced["history"][0]["verdict"] == "success"
    assert advanced["pending"]["step_id"] == "step-1"
    assert len(list(tmp_path.glob("commands/*.json"))) == 2

    first_binding, latest_binding = fixture.assessment.calls
    assert first_binding["assessment_context"]["assessment_round"] == 0
    assert [frame["role"] for frame in first_binding["frames"]] == ["after"]
    assert latest_binding["execution_request_id"] == original.command_id
    assert latest_binding["assessment_context"]["assessment_round"] == 2
    assert latest_binding["assessment_context"]["elapsed_ms"] == pytest.approx(1725)
    assert latest_binding["assessment_context"]["timeout_seconds"] == pytest.approx(10.275)
    assert [frame["role"] for frame in latest_binding["frames"]] == ["after", "observation"]
    assert latest_binding["frames"][0] == first_binding["frames"][0]
    latest_frame = latest_binding["frames"][1]
    assert set(latest_frame) == {"capture_id", "sha256", "image_path", "window_identity", "role"}
    assert latest_frame["window_identity"] == s.target
    assert latest_frame["capture_id"] != original.capture["capture_id"]
    assert latest_frame["sha256"] == fixture.captures[1]["sha256"]
    assert Path(latest_frame["image_path"]).parent == tmp_path / "task-plan-observations"
    assert Path(latest_frame["image_path"]).read_bytes() == Path(fixture.captures[1]["image_path"]).read_bytes()
    assert Path(latest_frame["image_path"]) != original.after
    ledger = task_plan_observation.ObservationLedger(s.runtime.backend, original.command_id)
    assert ledger.header()["original_frame"]["window_rect"] == [0, 0, 80, 60]
    assert ledger.header()["original_frame"]["image_size"] == {"width": 80, "height": 60}
    captured = [event["payload"] for event in ledger.read() if event["event"] == "captured"]
    assert [item["round"] for item in captured] == [1, 2]
    assert [item["capture_elapsed_ms"] for item in captured] == [125, 125]
    assert len({item["frame"]["capture_id"] for item in captured}) == 2
    assert len({item["frame"]["image_path"] for item in captured}) == 2
    assert ledger.finished()["reason"] == "authenticated_decision"
    assert read_json_snapshot(fixture.receipt_path) == original.receipt
    assert fixture.receipt_path.read_bytes() == original_receipt
    assert original.after.read_bytes() == original_png
    assert original.capture == original_frame


def test_old_after_receipt_without_geometry_cannot_observe_reassess_or_dispatch_suffix(tmp_path, monkeypatch):
    fixture = _integration_scene(tmp_path, monkeypatch, complete_geometry=False)
    s, original, clock = fixture.scene, fixture.original, fixture.clock
    # 已有前置几何与旧尺寸别名也不能补造动作后的窗口位置。
    original.receipt["result"]["target_window_geometry"] = {"x": 0, "y": 0, "w": 80, "h": 60}
    original.receipt["result"]["capture"].update(image_size={"width": 80, "height": 60},
        window_rect=[0, 0, 80, 60])
    write_json_snapshot(fixture.receipt_path, original.receipt)
    original_receipt = fixture.receipt_path.read_bytes()
    original_png = original.after.read_bytes()
    assert original.capture["window_size"] == {"width": 80, "height": 60}
    assert "image_size" not in original.capture and "window_rect" not in original.capture
    first = s.runtime.tick(force=True)
    assert first["observation_pending"] is True and len(fixture.assessment.calls) == 1
    clock.seconds = .6
    blocked = s.runtime.tick(force=True)
    assert blocked["review_required"] is True and blocked.get("observation_pending") is not True
    assert blocked["wait_reason"] == "verification_required" and blocked["history"] == []
    assert blocked["pending"]["execution_request_id"] == original.command_id
    assert blocked["pending"]["step_id"] == "step-0"
    ledger = task_plan_observation.ObservationLedger(s.runtime.backend, original.command_id)
    assert ledger.finished()["reason"] == "task_plan_observation_frame_invalid"
    assert "window_rect" not in ledger.header()["original_frame"]
    assert "image_size" not in ledger.header()["original_frame"]
    rejected = [event["payload"] for event in ledger.read() if event["event"] == "capture_rejected"]
    assert len(rejected) == 1 and rejected[0]["reason"] == "task_plan_observation_frame_invalid"
    assert not any(event["event"] == "captured" for event in ledger.read())
    clock.seconds = 2.0
    for index in range(3):
        assert s.runtime.tick(force=True) is None
        snapshot = s.runtime.control({"action": "status", "run_id": s.run_id}, "old-after-status-" + str(index))
        assert snapshot["history"] == [] and snapshot["pending"]["execution_request_id"] == original.command_id
    assert len(fixture.assessment.calls) == 1 and fixture.owner.calls == 0 and fixture.captures == []
    assert len(list(tmp_path.glob("commands/*.json"))) == 1
    assert list((tmp_path / "task-plan-observations").glob("*.png")) == []
    assert fixture.receipt_path.read_bytes() == original_receipt
    assert original.after.read_bytes() == original_png
