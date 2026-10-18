from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path

from PIL import Image
import pytest

from app.agent.action_learning_capture_archive import (
    ActionLearningCaptureArchive,
    ActionLearningCaptureArchiveError,
)
from app.agent.action_learning_recorder import ActionLearningRecorder
from app.agent.live_controller import ServerWorkflowBinding
from app.agent.live_runtime_composition import (
    ExistingWindowsCurrentEvidenceAdapter,
    build_existing_windows_live_controller,
)
from app.agent.reviewed_workflow_asset import content_sha256
from tests.test_live_runtime_composition_w3b import (
    _OriginReader,
    _RecognitionRunner,
    _ScreenshotService,
    _UIAProvider,
    _WindowManager,
    _bound,
    _entry_payloads,
)
from tests.test_reviewed_workflow_asset_v2 import _asset


def _png(width: int = 16, height: int = 12, color=(10, 20, 30)) -> bytes:
    stream = BytesIO()
    Image.new("RGB", (width, height), color).save(stream, "PNG")
    return stream.getvalue()


def _active(root: Path, learning_id: str, runtime_id: str):
    recorder = ActionLearningRecorder(project_root=root)
    recorder.start_learning_session(
        learning_session_id=learning_id,
        runtime_session_id=runtime_id,
    )
    return recorder, ActionLearningCaptureArchive(recorder=recorder)


def _pin(
    archive: ActionLearningCaptureArchive,
    *,
    runtime_id: str = "runtime-a",
    capture_id: str = "capture-a",
    png: bytes | None = None,
    viewport: dict[str, int] | None = None,
    asset_sha: str = "a" * 64,
) -> dict:
    payload = _png() if png is None else png
    return archive.pin_current_capture(
        runtime_session_id=runtime_id,
        capture_id=capture_id,
        screenshot_sha256=sha256(payload).hexdigest(),
        viewport_size=viewport or {"width": 16, "height": 12},
        asset_content_sha256=asset_sha,
        target_window_handle=4242,
        target_process_id=9001,
        png_bytes=payload,
    )


def _adapter(
    root: Path,
    archive: ActionLearningCaptureArchive | None,
    *,
    manager: _WindowManager | None = None,
    screenshot: _ScreenshotService | None = None,
    cache_limit: int = 8,
):
    root.mkdir(parents=True, exist_ok=True)
    asset = _asset()
    manager = manager or _WindowManager(_bound(), _bound(), _bound())
    screenshot = screenshot or _ScreenshotService(root)
    runner = _RecognitionRunner(_entry_payloads(asset))
    adapter = ExistingWindowsCurrentEvidenceAdapter(
        project_root=root,
        application_identity_key="web:nz.seek.com",
        screenshot_service=screenshot,
        origin_reader=_OriginReader(),
        window_manager=manager,
        recognition_runner=runner,
        uia_provider=_UIAProvider(),
        cache_limit=cache_limit,
        capture_archive=archive,
    )
    return asset, adapter, screenshot, runner


def _recognition_goal_count(asset: dict) -> int:
    return len({
        anchor["label"]
        for state in asset["states"]
        for anchor in state["identity_anchors"]
    })


def test_active_binding_read_is_local_validated_and_nonallocating(tmp_path: Path) -> None:
    recorder = ActionLearningRecorder(project_root=tmp_path)
    assert recorder.get_active_learning_binding(runtime_session_id="runtime-a") is None
    assert recorder.list_learning_sessions() == []
    recorder.start_learning_session(
        learning_session_id="learning-a", runtime_session_id="runtime-a",
    )
    assert recorder.get_active_learning_binding(runtime_session_id="runtime-a") == "learning-a"
    recorder.finish_learning_session(
        learning_session_id="learning-a", runtime_session_id="runtime-a",
    )
    assert recorder.get_active_learning_binding(runtime_session_id="runtime-a") is None
    with pytest.raises(ValueError, match="runtime_session_id"):
        recorder.get_active_learning_binding(runtime_session_id="../escape")


def test_real_adapter_pins_exact_bytes_surviving_cache_eviction_and_source_removal(
    tmp_path: Path,
) -> None:
    sentinel = tmp_path / "unrelated-source.txt"
    sentinel.write_bytes(b"keep-me")
    recorder, archive = _active(tmp_path, "learning-a", "runtime-a")
    manager = _WindowManager(*[_bound() for _ in range(6)])
    screenshot = _ScreenshotService(tmp_path)
    asset, adapter, screenshot, runner = _adapter(
        tmp_path, archive, manager=manager, screenshot=screenshot, cache_limit=1,
    )

    first = adapter.capture_current(
        session_id="runtime-a", asset=asset, target_window_handle=4242,
    )
    first_bytes = screenshot.paths[0].read_bytes()
    second = adapter.capture_current(
        session_id="runtime-a", asset=asset, target_window_handle=4242,
    )
    assert first["capture_id"] != second["capture_id"]
    assert len(adapter._cache) == 1
    screenshot.paths[0].unlink()
    restarted = ActionLearningCaptureArchive(
        recorder=ActionLearningRecorder(project_root=tmp_path),
    )

    assert restarted.read_capture(
        learning_session_id="learning-a",
        runtime_session_id="runtime-a",
        capture_id=first["capture_id"],
        screenshot_sha256=first["screenshot_sha256"],
    ) == first_bytes
    assert len(screenshot.calls) == 2
    assert len(runner.calls) == 2 * _recognition_goal_count(asset)
    assert sentinel.read_bytes() == b"keep-me"
    assert content_sha256(asset) == _pin_metadata(archive, first)["asset_content_sha256"]


def _pin_metadata(archive: ActionLearningCaptureArchive, current: dict) -> dict:
    records = list((archive.root / "records").glob("*.json"))
    for path in records:
        import json
        item = json.loads(path.read_text(encoding="utf-8"))
        if item["capture_id"] == current["capture_id"]:
            return item
    raise AssertionError("pinned metadata was not found")


def test_unbound_and_default_adapter_create_no_capture_archive(tmp_path: Path) -> None:
    recorder = ActionLearningRecorder(project_root=tmp_path / "unbound")
    archive = ActionLearningCaptureArchive(
        recorder=recorder, max_png_bytes=1, max_total_png_bytes=1,
    )
    asset, adapter, screenshot, runner = _adapter(tmp_path / "unbound", archive)
    current = adapter.capture_current(
        session_id="runtime-unbound", asset=asset, target_window_handle=4242,
    )
    assert current["capture_id"]
    assert not archive.root.exists()
    assert len(screenshot.calls) == 1
    assert len(runner.calls) == _recognition_goal_count(asset)

    default_root = tmp_path / "default"
    asset, default, *_ = _adapter(default_root, None)
    default.capture_current(
        session_id="runtime-default", asset=asset, target_window_handle=4242,
    )
    default_archive = default_root / "runtime_state/action-learning-v1/captures"
    assert not default_archive.exists()


def test_identity_isolation_idempotence_and_finished_read(tmp_path: Path) -> None:
    recorder, archive = _active(tmp_path, "learning-a", "runtime-a")
    payload = _png()
    first = _pin(archive, png=payload)
    assert _pin(archive, png=payload) == first
    assert first["artifact_is_authorization"] is False
    assert first["execute_binding_enabled"] is False
    assert len(list((archive.root / "blobs").glob("*.png"))) == 1
    assert len(list((archive.root / "records").glob("*.json"))) == 1
    recorder.finish_learning_session(
        learning_session_id="learning-a", runtime_session_id="runtime-a",
    )
    recorder.start_learning_session(
        learning_session_id="learning-b", runtime_session_id="runtime-b",
    )
    assert archive.read_capture(
        learning_session_id="learning-a",
        runtime_session_id="runtime-a",
        capture_id="capture-a",
        screenshot_sha256=sha256(payload).hexdigest(),
    ) == payload
    with pytest.raises(ActionLearningCaptureArchiveError):
        archive.read_capture(
            learning_session_id="learning-b",
            runtime_session_id="runtime-b",
            capture_id="capture-a",
            screenshot_sha256=sha256(payload).hexdigest(),
        )
    with pytest.raises(ActionLearningCaptureArchiveError, match="scope"):
        archive.read_capture(
            learning_session_id="learning-a",
            runtime_session_id="runtime-b",
            capture_id="capture-a",
            screenshot_sha256=sha256(payload).hexdigest(),
        )


def test_validation_conflict_and_binding_change_never_publish_false_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder, archive = _active(tmp_path, "learning-a", "runtime-a")
    payload = _png()
    small_limit = ActionLearningCaptureArchive(
        recorder=recorder,
        max_png_bytes=len(payload) - 1,
        max_total_png_bytes=1024,
    )
    with pytest.raises(ActionLearningCaptureArchiveError, match="per-capture quota"):
        _pin(small_limit, png=payload)
    with pytest.raises(ActionLearningCaptureArchiveError, match="screenshot"):
        archive.pin_current_capture(
            runtime_session_id="runtime-a", capture_id="capture-invalid",
            screenshot_sha256="f" * 64,
            viewport_size={"width": 16, "height": 12},
            asset_content_sha256="a" * 64,
            target_window_handle=4242, target_process_id=9001, png_bytes=payload,
        )
    with pytest.raises(ActionLearningCaptureArchiveError, match="dimension"):
        _pin(archive, capture_id="capture-invalid", viewport={"width": 17, "height": 12})
    assert not archive.root.exists()

    original = recorder.get_active_learning_binding
    calls = 0

    def changed(*, runtime_session_id: str):
        nonlocal calls
        calls += 1
        if calls == 2:
            recorder.finish_learning_session(
                learning_session_id="learning-a", runtime_session_id="runtime-a",
            )
        return original(runtime_session_id=runtime_session_id)

    monkeypatch.setattr(recorder, "get_active_learning_binding", changed)
    with pytest.raises(ActionLearningCaptureArchiveError, match="binding changed"):
        _pin(archive)
    assert not list(archive.root.glob("records/*.json")) if archive.root.exists() else True


def test_conflict_corruption_and_quota_do_not_overwrite_existing_bytes(
    tmp_path: Path,
) -> None:
    recorder = ActionLearningRecorder(project_root=tmp_path)
    recorder.start_learning_session(
        learning_session_id="learning-a", runtime_session_id="runtime-a",
    )
    archive = ActionLearningCaptureArchive(
        recorder=recorder, max_png_bytes=1024, max_total_png_bytes=180,
    )
    first_png = _png(color=(1, 2, 3))
    first = _pin(archive, png=first_png)
    blob = next((archive.root / "blobs").glob("*.png"))
    original_blob = blob.read_bytes()
    with pytest.raises(ActionLearningCaptureArchiveError, match="conflict"):
        _pin(archive, png=first_png, asset_sha="b" * 64)
    assert blob.read_bytes() == original_blob

    large_png = _png(64, 64, color=(50, 60, 70))
    if len(first_png) + len(large_png) <= 180:
        large_png += b"padding" * 30
    with pytest.raises(ActionLearningCaptureArchiveError, match="quota"):
        _pin(
            archive,
            capture_id="capture-b",
            png=large_png,
            viewport={"width": 64, "height": 64},
        )
    assert archive.read_capture(
        learning_session_id="learning-a", runtime_session_id="runtime-a",
        capture_id="capture-a", screenshot_sha256=first["screenshot_sha256"],
    ) == first_png
    assert blob.read_bytes() == original_blob


def test_metadata_publish_failure_leaves_only_deduplicable_unreferenced_blob(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.agent.action_learning_capture_archive as archive_module

    _, archive = _active(tmp_path, "learning-a", "runtime-a")
    payload = _png(color=(4, 5, 6))
    real_atomic_write = archive_module._atomic_write

    def fail_metadata(path: Path, contents: bytes) -> None:
        if ".json." in path.name:
            raise OSError("simulated metadata persistence failure")
        real_atomic_write(path, contents)

    monkeypatch.setattr(archive_module, "_atomic_write", fail_metadata)
    with pytest.raises(ActionLearningCaptureArchiveError, match="metadata persistence"):
        _pin(archive, png=payload)
    blobs = list((archive.root / "blobs").glob("*.png"))
    assert len(blobs) == 1 and blobs[0].read_bytes() == payload
    assert list((archive.root / "records").glob("*.json")) == []

    monkeypatch.setattr(archive_module, "_atomic_write", real_atomic_write)
    metadata = _pin(archive, png=payload)
    assert metadata["screenshot_sha256"] == sha256(payload).hexdigest()
    assert len(list((archive.root / "blobs").glob("*.png"))) == 1
    assert len(list((archive.root / "records").glob("*.json"))) == 1

@pytest.mark.parametrize("corrupt", ["metadata", "blob"])
def test_corrupt_archive_is_rejected_and_not_repaired(
    tmp_path: Path,
    corrupt: str,
) -> None:
    _, archive = _active(tmp_path, "learning-a", "runtime-a")
    payload = _png()
    metadata = _pin(archive, png=payload)
    target = (
        next((archive.root / "records").glob("*.json"))
        if corrupt == "metadata"
        else next((archive.root / "blobs").glob("*.png"))
    )
    damaged = b"not-canonical-metadata" if corrupt == "metadata" else b"not-a-png"
    target.write_bytes(damaged)
    with pytest.raises(ActionLearningCaptureArchiveError, match="corrupt"):
        archive.read_capture(
            learning_session_id="learning-a", runtime_session_id="runtime-a",
            capture_id="capture-a", screenshot_sha256=metadata["screenshot_sha256"],
        )
    with pytest.raises(ActionLearningCaptureArchiveError, match="corrupt"):
        _pin(archive, png=payload)
    assert target.read_bytes() == damaged


def test_real_adapter_drift_never_pins_and_factory_wiring_is_conditional(
    tmp_path: Path,
) -> None:
    drift_root = tmp_path / "drift"
    recorder, archive = _active(drift_root, "learning-a", "runtime-a")
    manager = _WindowManager(_bound(), _bound(), _bound(process_id=9002))
    asset, adapter, screenshot, runner = _adapter(
        drift_root, archive, manager=manager,
    )
    with pytest.raises(ValueError, match="drift"):
        adapter.capture_current(
            session_id="runtime-a", asset=asset, target_window_handle=4242,
        )
    assert len(screenshot.calls) == 1
    assert len(runner.calls) == _recognition_goal_count(asset)
    assert not archive.root.exists()

    from tests.test_native_vision_configuration import _config
    factory_root = tmp_path / "factory"
    _config(factory_root / "configs/vision.json")
    binding = ServerWorkflowBinding(
        workflow_id="workflow.seek.portfolio",
        asset_id="seek_homepage_quick_apply",
        application_identity_key="web:nz.seek.com",
        target_window_handle=4242,
    )
    default = build_existing_windows_live_controller(factory_root, binding)
    assert default._observation_source._capture_archive is None
    assert not (factory_root / "runtime_state/action-learning-v1/captures").exists()
    wired_recorder = ActionLearningRecorder(project_root=factory_root)
    wired = build_existing_windows_live_controller(
        factory_root, binding, action_learning_recorder=wired_recorder,
    )
    assert isinstance(wired._observation_source._capture_archive, ActionLearningCaptureArchive)
    assert not (factory_root / "runtime_state/action-learning-v1/captures").exists()
    with pytest.raises(ValueError, match="same project root"):
        build_existing_windows_live_controller(
            factory_root,
            binding,
            action_learning_recorder=ActionLearningRecorder(
                project_root=tmp_path / "foreign",
            ),
        )
