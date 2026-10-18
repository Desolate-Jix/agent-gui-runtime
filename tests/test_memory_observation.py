"""截图、窗口身份与 UIA 快照必须来自同一次当前观察。"""
from hashlib import sha256
from types import SimpleNamespace

from PIL import Image
import pytest

from app.learning_memory.memory_observation import capture_memory_observation


class Manager:
    def __init__(self):
        self.bound = SimpleNamespace(handle=12, process_id=34, process_name="fixture.exe",
            rect=SimpleNamespace(left=10, top=20, right=110, bottom=90))

    def get_bound_window(self):
        return self.bound


class Coordinator:
    def __init__(self, root):
        self._runtime_output_root = root
        self.manager = Manager()

    def _windows(self):
        return self.manager


def _setup(monkeypatch, tmp_path, *, changed=False):
    from app.learning_memory import memory_observation as module
    image = tmp_path / "current.png"
    Image.new("RGB", (100, 70), "white").save(image)
    values = [123.0, 124.0] if changed else [123.0, 123.0]

    class IdentityReader:
        def __init__(self, **kwargs):
            pass

        def read_identity(self, handle):
            return {"status": "observed", "target_window_handle": handle, "process_id": 34,
                    "process_create_time": values.pop(0), "executable_path": "C:\\Fixture\\fixture.exe"}

    class Screenshot:
        def __init__(self, **kwargs):
            pass

        def capture_window(self, **kwargs):
            return {"image_path": str(image), "window_size": {"width": 100, "height": 70}}

    calls = []
    class UIA:
        def snapshot_window(self, bound):
            calls.append(bound.handle)
            return {"status": "ok", "scan_complete": True, "truncated": False,
                    "window": {"handle": 12, "process_id": 34}, "controls": []}

    monkeypatch.setattr(module, "WindowsNativeIdentityReader", IdentityReader)
    monkeypatch.setattr(module, "ScreenshotService", Screenshot)
    monkeypatch.setattr(module, "WindowsUIAProvider", UIA)
    monkeypatch.setattr(module, "_window_class", lambda handle: "Fixture")
    return Coordinator(tmp_path), image, calls


def test_current_capture_and_uia_bind_to_same_identity(monkeypatch, tmp_path):
    coordinator, image, calls = _setup(monkeypatch, tmp_path)
    recipe = {"scope": {"anchors": [{"kind": "uia", "name": "页面", "control_type": "Pane"}]},
              "strategies": [{"kind": "uia", "name": "打开", "control_type": "Button"}]}
    frame, observations = capture_memory_observation(coordinator, 12, 34, recipe=recipe)
    assert frame["sha256"] == sha256(image.read_bytes()).hexdigest()
    assert frame["image_size"] == {"width": 100, "height": 70}
    assert frame["window_identity"] == {"handle": 12, "process_id": 34, "process_create_time": 123.0}
    assert frame["application"] == {"executable_name": "fixture.exe", "window_class": "Fixture"}
    assert observations["uia"]["capture_id"] == frame["capture_id"]
    assert calls == [12]


def test_no_uia_rule_does_not_scan_and_existing_capture_is_rehashed(monkeypatch, tmp_path):
    coordinator, image, calls = _setup(monkeypatch, tmp_path)
    frame, observations = capture_memory_observation(coordinator, 12, 34, image_path=image,
        recipe={"scope": {"anchors": [{"kind": "template", "template_id": "template-" + "a" * 64}]},
                "strategies": [{"kind": "template", "template_id": "template-" + "b" * 64}]})
    assert observations["uia"]["status"] == "not_required"
    assert frame["sha256"] == sha256(image.read_bytes()).hexdigest()
    assert calls == []


def test_identity_drift_rejected_after_capture(monkeypatch, tmp_path):
    coordinator, _, _ = _setup(monkeypatch, tmp_path, changed=True)
    with pytest.raises(ValueError, match="identity_changed"):
        capture_memory_observation(coordinator, 12, 34)
