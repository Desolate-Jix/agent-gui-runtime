"""原生拥有者固定输出根，系统边界使用替身且不操作真实窗口。"""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, get_ident
from types import SimpleNamespace

import pytest
from PIL import Image

from app.core import runtime_artifacts as artifacts
from app.desktop_review.single_step_runtime_owner import RuntimeOwnerProxy, SerialRuntimeOwner
from tests.test_native_grounded_image_material import grounded_image_runtime


def _trace():
    return Path(artifacts.write_trace(category="native", operation="output", payload={"text": "中文证据"}))


def test_owner_freezes_relative_root_and_scopes_initializer_inline_proxy_finalizer(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    events = []

    def record(phase):
        path = _trace()
        events.append((phase, path, get_ident()))
        return path

    owner = SerialRuntimeOwner(output_root=Path("owned"), initializer=lambda: record("init"), finalizer=lambda: record("fini"))
    empty = tmp_path / "unrelated"
    empty.mkdir()
    monkeypatch.chdir(empty)
    try:
        assert owner.call(lambda: owner.call(lambda: record("inline"))).is_file()
        proxy = RuntimeOwnerProxy(owner, SimpleNamespace(get_local_grounded_image=lambda **_: record("proxy")))
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(proxy.get_local_grounded_image, confirmation_id="synthetic").result().is_file()
        with pytest.raises(ValueError, match="synthetic"):
            owner.call(lambda: (_ for _ in ()).throw(ValueError("synthetic")))
        owner.call(lambda: record("after_error"))
    finally:
        owner.close()
    assert [row[0] for row in events] == ["init", "inline", "proxy", "after_error", "fini"]
    assert len({row[2] for row in events}) == 1
    assert all(row[1].is_relative_to(tmp_path / "owned/logs/traces") for row in events)
    assert all(json.loads(row[1].read_text(encoding="utf-8"))["text"] == "中文证据" for row in events)
    assert not list(empty.iterdir())
    assert artifacts.runtime_output_directory("artifacts") == Path("artifacts")


def test_two_owners_do_not_inherit_caller_or_other_owner_output(tmp_path):
    rendezvous = Barrier(2)
    owners = [SerialRuntimeOwner(output_root=tmp_path / name, initializer=lambda: None, finalizer=lambda: None) for name in ("a", "b")]

    def run(owner):
        def operation():
            rendezvous.wait(timeout=10)
            first = _trace()
            rendezvous.wait(timeout=10)
            return first, _trace()
        return owner.call(operation)

    try:
        with artifacts.pinned_runtime_output_root(tmp_path / "caller"):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(run, owners))
            assert artifacts.runtime_output_directory("artifacts") == tmp_path / "caller/artifacts"
        for name, paths in zip(("a", "b"), results):
            assert all(path.is_relative_to(tmp_path / name) and path.is_file() for path in paths)
        assert not (tmp_path / "caller").exists()
    finally:
        for owner in owners:
            owner.close()


def test_native_entrypoint_wires_user_data_output_root_without_starting_runtime(tmp_path, monkeypatch):
    from app.desktop_review import entrypoint, host, single_step_runtime_owner, window
    from tests.test_native_single_step_coordinator import _Facade, _Host

    fake_host = _Host()
    fake_host.facade, fake_host.connections = _Facade(), object()
    fake_host.start = lambda: None
    monkeypatch.setattr(host, "DesktopReviewHost", lambda *args, **kwargs: fake_host)
    monkeypatch.setattr(single_step_runtime_owner, "_initialize_com", lambda: None)
    monkeypatch.setattr(single_step_runtime_owner, "_finalize_com", lambda: None)
    monkeypatch.setattr(window, "ensure_application", lambda: SimpleNamespace(exec=lambda: 0))
    observed = []

    class Window:
        def __init__(self, facade, *, single_step, **kwargs):
            self.coordinator = single_step

        def show(self):
            co = self.coordinator
            assert co._runtime_output_root == tmp_path / "data/runtime-output"
            assert co._owner.thread_id is None and co._runtime is None
            assert not co._runtime_output_root.exists()
            observed.append(co._owner.call(_trace))

    monkeypatch.setattr(window, "ReviewMainWindow", Window)
    monkeypatch.setattr(entrypoint, "_show_startup_error", lambda kind: pytest.fail(kind))
    empty = tmp_path / "unrelated"
    empty.mkdir()
    monkeypatch.chdir(empty)
    assert entrypoint.main(["--data-dir", str(tmp_path / "data")]) == 0
    assert observed[0].is_relative_to(tmp_path / "data/runtime-output")
    assert observed[0].is_file() and not list(empty.iterdir())


def test_formal_owner_routes_existing_capture_vista_overlay_and_trace_without_path_patches(tmp_path, monkeypatch):
    from app.agent.live_controller import ServerWorkflowBinding
    from app.agent.runtime_session_selection import RuntimeSessionSelection
    from app.api import vision
    from app.core import screenshot
    from app.desktop_review.single_step_coordinator import _production_runtime_factory
    from app.vision.configuration import load_formal_vision_configuration
    from app.vision.local_provider import LocalVisionProvider
    from modules.ocr.contracts import OCRResult
    from tests.test_native_vision_configuration import _config

    source = _config(tmp_path / "config/vision.json")
    config = json.loads(source.read_text(encoding="utf-8"))
    config["vision"]["local"].update(runtime="transformers", output_contract="vista_point_v1", model_path="synthetic-weights")
    source.write_text(json.dumps(config), encoding="utf-8")
    snapshot = load_formal_vision_configuration(source)
    bound = SimpleNamespace(handle=4242, process_id=9001, title="Synthetic", process_name="editor.exe",
        rect=SimpleNamespace(left=10, top=10, right=50, bottom=30), is_active=True)
    windows = SimpleNamespace(get_bound_window=lambda: bound,
        validate_bound_capture_visibility=lambda **_: {"allowed": True, "reason": "capture_window_visible"})
    monkeypatch.setattr(screenshot, "window_manager", windows)
    monkeypatch.setattr(screenshot.screenshot_service, "_window_manager", windows)

    class Capture:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def grab(self, monitor):
            size = monitor["width"], monitor["height"]
            return SimpleNamespace(size=size, rgb=bytes((3, 5, 7)) * (size[0] * size[1]))

    monkeypatch.setattr(screenshot, "mss", Capture)
    monkeypatch.setattr(screenshot, "MSS_BACKEND_AVAILABLE", True)
    endpoints = []

    def point_endpoint(provider, image_path, prompt, **kwargs):
        image = Path(image_path)
        assert image.is_file()
        endpoints.append(image)
        return {"choices": [{"message": {"content": "[500, 500]"}}]}

    monkeypatch.setattr(LocalVisionProvider, "analyze", lambda *args: pytest.fail("VISTA must use the point endpoint"))
    monkeypatch.setattr(LocalVisionProvider, "_call_openai_compatible_endpoint", point_endpoint)
    monkeypatch.setattr(vision.ocr_service, "scan_image", lambda path: OCRResult(image_path=path, matches=[]))
    empty = tmp_path / "unrelated"
    empty.mkdir()
    monkeypatch.chdir(empty)
    roots = [tmp_path / "first/runtime-output", tmp_path / "second/runtime-output"]
    owners = [SerialRuntimeOwner(output_root=root, initializer=lambda: None, finalizer=lambda: None) for root in roots]
    controllers = []
    selection = RuntimeSessionSelection("asset-output", "a" * 64, 4242, 9001)
    try:
        for owner, root in zip(owners, roots):
            def build():
                callsite = _production_runtime_factory(project_root=root.parent / "reviews", selection=selection,
                    window_manager=windows, vision_configuration=snapshot)
                return callsite._controller_factory(ServerWorkflowBinding(workflow_id="output-flow", asset_id="asset-output",
                    application_identity_key="native:editor.exe:notepad", target_window_handle=4242))
            controllers.append(owner.call(build))
        for index in (0, 1, 0):
            root, owner = roots[index], owners[index]
            adapter = controllers[index]._observation_source

            def capture_and_recognize():
                capture = adapter._screenshot_service.capture_window(focus_window=False)
                path = Path(capture["image_path"])
                assert path.is_relative_to(root / "artifacts/screenshots")
                result = adapter._recognition_runner(image_path=str(path), goal="synthetic target", provider_mode="local",
                    uia_snapshot={"status": "ok", "window": {"handle": 4242, "process_id": 9001}, "controls": []})
                assert result["image_path"] == str(path)
                assert result["execution_path"]["action_executed"] is False
                assert not result["trace_path"]
                overlay = artifacts.build_review_overlay_path(name_hint="synthetic")
                Image.new("RGB", (4, 4)).save(overlay)
                assert overlay.is_relative_to(root / "artifacts/review-overlays")
                return _trace()

            before = len(endpoints)
            assert owner.call(capture_and_recognize).is_relative_to(root)
            assert len(endpoints) == before + 2
            assert all(path.is_relative_to(root / "artifacts") for path in endpoints[before:])
            assert list((root / "artifacts/vista-direct").glob("*.png"))
        assert controllers[0]._observation_source._screenshot_service is controllers[1]._observation_source._screenshot_service
        assert not list(empty.iterdir())
    finally:
        for owner in owners:
            owner.close()


def test_native_preview_reads_original_absolute_capture_after_owner_scope_changes(tmp_path, monkeypatch, grounded_image_runtime):
    from app.api.agent_runtime import AgentRuntimeCallsiteError
    from app.core import screenshot
    from tests.test_native_grounded_image_material import _pending

    runtime = grounded_image_runtime
    root_a, root_b = tmp_path / "a", tmp_path / "b"
    bound = SimpleNamespace(handle=4242, process_id=9001, title="Synthetic", process_name="editor.exe",
        rect=SimpleNamespace(left=10, top=20, right=330, bottom=220))
    monkeypatch.setattr(screenshot, "window_manager", SimpleNamespace(get_bound_window=lambda: bound,
        validate_bound_capture_visibility=lambda **_: {"allowed": True, "reason": "capture_window_visible"}))
    monkeypatch.setattr(screenshot, "MSS_BACKEND_AVAILABLE", True)
    monkeypatch.setattr(artifacts, "timestamp_label", lambda: "same-name")
    pixels = {"color": (1, 20, 30), "captures": 0}

    class Capture:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def grab(self, monitor):
            pixels["captures"] += 1
            size = monitor["width"], monitor["height"]
            return SimpleNamespace(size=size, rgb=bytes(pixels["color"]) * (size[0] * size[1]))

    monkeypatch.setattr(screenshot, "mss", Capture)
    service = screenshot.ScreenshotService()
    runtime.evidence._screenshot_service = service
    owner = SerialRuntimeOwner(output_root=root_a, initializer=lambda: None, finalizer=lambda: None)
    other = SerialRuntimeOwner(output_root=root_b, initializer=lambda: None, finalizer=lambda: None)
    try:
        observation, pending = owner.call(lambda: _pending(runtime))
        confirmation_id = pending.grounded_confirmation.confirmation_id
        proxy = RuntimeOwnerProxy(owner, runtime.service)
        original = proxy.get_local_grounded_image(confirmation_id=confirmation_id)
        capture_id = pending.grounded_confirmation.preview.to_dict()["grounding_preview"]["capture_lineage"]["capture_id"]
        path_a = Path(next(bundle.image_path for bundle in runtime.evidence._cache.values() if bundle.capture_id == capture_id))
        assert path_a.is_absolute() and path_a.is_relative_to(root_a)
        pixels["color"] = (200, 10, 40)
        capture_b = other.call(lambda: service.capture_window(focus_window=False, purpose="runtime-observation"))
        path_b = Path(capture_b["image_path"])
        assert path_a.name == path_b.name and original != path_b.read_bytes()
        count = pixels["captures"]
        with artifacts.pinned_runtime_output_root(root_b):
            assert proxy.get_local_grounded_image(confirmation_id=confirmation_id) == original
        # 仅重建串行线程壳，不冒充应用重启后可以复活原批准。
        owner.close()
        owner = SerialRuntimeOwner(output_root=root_a, initializer=lambda: None, finalizer=lambda: None)
        proxy = RuntimeOwnerProxy(owner, runtime.service)
        assert proxy.get_local_grounded_image(confirmation_id=confirmation_id) == original
        path_a.rename(tmp_path / "temporarily-missing-a.png")
        with pytest.raises(AgentRuntimeCallsiteError) as error:
            proxy.get_local_grounded_image(confirmation_id=confirmation_id)
        assert error.value.code == "agent_runtime_grounded_image_unavailable"
        assert path_b.is_file() and pixels["captures"] == count
        assert all(backend.attempt_count == 0 for backend in runtime.backends)
        owner.call(lambda: runtime.service.cancel_grounded_review(session_id=observation.session_id))
    finally:
        owner.close()
        other.close()
