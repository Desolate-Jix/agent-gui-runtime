from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agent.fresh_learning_factory import create_fresh_learning_observation_owner
from app.core.screenshot import ScreenshotService


class _WindowManager:
    def __init__(self, *, handle: int = 4242, process_id: int = 9001) -> None:
        self.bound = SimpleNamespace(
            handle=handle,
            process_id=process_id,
            title="Fresh window",
            process_name="fresh.exe",
            rect=SimpleNamespace(left=10, top=20, right=170, bottom=120),
        )
        self.bound_handles: list[int] = []
        self.focus_calls = 0

    def bind_window_by_handle(self, handle: int):
        self.bound_handles.append(handle)
        return self.bound

    def get_bound_window(self):
        return self.bound

    def validate_bound_capture_visibility(self, **kwargs):
        return {"allowed": True, "reason": "capture_window_visible"}

    def focus_bound_window(self):
        self.focus_calls += 1
        return self.bound


class _MSS:
    monitors: list[dict[str, int]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def grab(self, monitor):
        self.monitors.append(dict(monitor))
        return SimpleNamespace(
            size=(monitor["width"], monitor["height"]),
            rgb=bytes([7, 8, 9]) * monitor["width"] * monitor["height"],
        )


class _NativeReader:
    def __init__(self, *, window_manager) -> None:
        self.window_manager = window_manager

    def read_identity(self, handle: int):
        bound = self.window_manager.get_bound_window()
        return {
            "contract_version": "windows_native_identity_observation_v1",
            "provider": "windows_native_identity",
            "status": "observed",
            "target_window_handle": handle,
            "process_id": bound.process_id,
            "process_create_time": 100.5,
            "executable_path": r"c:\fresh\fresh.exe",
        }


class _OriginReader:
    def __init__(self, *, window_manager) -> None:
        self.window_manager = window_manager


class _UIAProvider:
    def snapshot_window(self, bound):
        return {
            "provider": "windows_uia",
            "provider_version": "windows_uia_provider_v1",
            "status": "ok",
            "window": {
                "handle": bound.handle,
                "process_id": bound.process_id,
                "bbox": {"x": 0, "y": 0, "w": 160, "h": 100},
            },
            "control_count": 0,
            "controls": [],
        }


class _GlobalWindowManager:
    def __init__(self) -> None:
        self.calls = 0

    def get_bound_window(self):
        self.calls += 1
        raise AssertionError("fresh observation must not read the global window binding")


def _patch_capture_backend(monkeypatch) -> None:
    import app.core.screenshot as screenshot_module

    _MSS.monitors.clear()
    monkeypatch.setattr(screenshot_module, "MSS_BACKEND_AVAILABLE", True)
    monkeypatch.setattr(screenshot_module, "mss", _MSS)


def test_screenshot_service_capture_uses_injected_window_and_private_capture_dir(
    tmp_path: Path, monkeypatch,
) -> None:
    _patch_capture_backend(monkeypatch)
    manager = _WindowManager()
    capture_dir = tmp_path / "runtime_state" / "fresh-learning-captures"

    result = ScreenshotService(
        window_manager=manager,
        capture_dir=capture_dir,
    ).capture_window(save_image=True, focus_window=False, purpose="learning-observation")

    image_path = Path(result["image_path"])
    assert image_path.parent == capture_dir
    assert image_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert _MSS.monitors == [{"left": 10, "top": 20, "width": 160, "height": 100}]
    assert manager.focus_calls == 0


def test_screenshot_service_default_window_manager_is_preserved(monkeypatch) -> None:
    import app.core.screenshot as screenshot_module

    assert ScreenshotService()._window_manager is screenshot_module.window_manager


def test_factory_binds_a_fresh_manager_and_wires_it_to_real_screenshot_service(
    tmp_path: Path, monkeypatch,
) -> None:
    import app.agent.fresh_learning_factory as factory_module

    manager = _WindowManager()
    monkeypatch.setattr(factory_module, "WindowManager", lambda: manager)

    owner = create_fresh_learning_observation_owner(
        project_root=tmp_path,
        application_identity={"kind": "native", "executable_path": r"C:\Fresh\fresh.exe"},
        target_window_handle=4242,
        target_process_id=9001,
    )

    assert manager.bound_handles == [4242]
    assert manager.focus_calls == 0
    assert owner._window_manager is manager
    assert isinstance(owner._screenshot_service, ScreenshotService)
    assert owner._screenshot_service._window_manager is manager
    assert owner._screenshot_service._capture_dir == (
        tmp_path.resolve() / "runtime_state" / "fresh-learning-captures"
    )


def test_factory_rejects_mismatched_process_before_capture(tmp_path: Path, monkeypatch) -> None:
    import app.agent.fresh_learning_factory as factory_module

    manager = _WindowManager(process_id=9999)
    monkeypatch.setattr(factory_module, "WindowManager", lambda: manager)

    with pytest.raises(ValueError, match="process"):
        create_fresh_learning_observation_owner(
            project_root=tmp_path,
            application_identity={"kind": "native", "executable_path": r"C:\Fresh\fresh.exe"},
            target_window_handle=4242,
            target_process_id=9001,
        )

    assert manager.bound_handles == [4242]


def test_factory_owner_observes_png_through_its_isolated_window_manager(
    tmp_path: Path, monkeypatch,
) -> None:
    import app.agent.fresh_learning_factory as factory_module
    import app.core.screenshot as screenshot_module

    _patch_capture_backend(monkeypatch)
    manager = _WindowManager()
    global_manager = _GlobalWindowManager()
    monkeypatch.setattr(factory_module, "WindowManager", lambda: manager)
    monkeypatch.setattr(factory_module, "WindowsNativeIdentityReader", _NativeReader)
    monkeypatch.setattr(factory_module, "WindowsUIAOriginReader", _OriginReader)
    monkeypatch.setattr(factory_module, "uia_provider", _UIAProvider())
    monkeypatch.setattr(screenshot_module, "window_manager", global_manager)

    owner = create_fresh_learning_observation_owner(
        project_root=tmp_path,
        application_identity={"kind": "native", "executable_path": r"C:\\Fresh\\fresh.exe"},
        target_window_handle=4242,
        target_process_id=9001,
    )
    packet = owner.observe(
        target_window_handle=4242,
        target_process_id=9001,
        goal=None,
    )

    captures = list((tmp_path / "runtime_state" / "fresh-learning-captures").glob("*.png"))
    assert len(captures) == 1
    assert packet.png_bytes == captures[0].read_bytes()
    assert packet.evidence()["target"]["window_handle"] == 4242
    assert _MSS.monitors == [{"left": 10, "top": 20, "width": 160, "height": 100}]
    assert manager.focus_calls == 0
    assert global_manager.calls == 0
