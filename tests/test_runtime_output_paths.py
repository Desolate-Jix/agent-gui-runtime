from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]


def test_cold_imports_do_not_create_cwd_artifacts_or_logs(tmp_path: Path) -> None:
    code = (
        "import app.core.runtime_artifacts, app.core.screenshot, app.core.verifier, app.api.vision; "
        "import app.desktop_review.entrypoint, app.desktop_review.application; "
        "import app.desktop_review.single_step_coordinator"
    )
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "QT_QPA_PLATFORM": "offscreen"}
    result = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "artifacts").exists()
    assert not (tmp_path / "logs").exists()


def test_pinned_output_root_is_scoped_nested_thread_local_and_resets(tmp_path: Path) -> None:
    from app.core.runtime_artifacts import pinned_runtime_output_root, runtime_output_directory

    one = (tmp_path / "one").resolve()
    two = (tmp_path / "two").resolve()
    assert runtime_output_directory("artifacts/screenshots") == Path("artifacts/screenshots")
    with pinned_runtime_output_root(one):
        assert runtime_output_directory("artifacts/screenshots") == one / "artifacts/screenshots"
        with pinned_runtime_output_root(two):
            assert runtime_output_directory("logs/traces") == two / "logs/traces"
        assert runtime_output_directory("logs/traces") == one / "logs/traces"
    assert runtime_output_directory("logs/traces") == Path("logs/traces")

    observed: list[Path] = []
    def read_scoped_root() -> None:
        observed.append(runtime_output_directory("artifacts/screenshots"))
    with pinned_runtime_output_root(one):
        worker = threading.Thread(target=read_scoped_root)
        worker.start()
        worker.join()
        assert runtime_output_directory("artifacts/screenshots") == one / "artifacts/screenshots"
    assert observed == [Path("artifacts/screenshots")]

    with pytest.raises(RuntimeError):
        with pinned_runtime_output_root(one):
            raise RuntimeError("reset")
    assert runtime_output_directory("artifacts/screenshots") == Path("artifacts/screenshots")


@pytest.mark.parametrize("relative", ["/absolute", "../escape", "artifacts/../escape"])
def test_output_directory_rejects_unsafe_relative_paths(relative: str) -> None:
    from app.core.runtime_artifacts import runtime_output_directory

    with pytest.raises(ValueError):
        runtime_output_directory(relative)


def test_trace_write_uses_pinned_root_and_preserves_utf8(tmp_path: Path) -> None:
    from app.core.runtime_artifacts import pinned_runtime_output_root, write_trace

    root = (tmp_path / "formal").resolve()
    with pinned_runtime_output_root(root):
        written = Path(write_trace(category="测试", operation="保存", payload={"中文": "证据"}))
    assert written.is_file()
    assert written.is_relative_to(root)
    assert "证据" in written.read_text(encoding="utf-8")


def test_screenshot_capture_uses_scope_for_save_and_retention(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import screenshot
    from app.core.runtime_artifacts import pinned_runtime_output_root

    class Raw:
        size = (2, 2)
        rgb = b"\x00\x00\x00" * 4

    class FakeMSS:
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def grab(self, _monitor): return Raw()

    class Bound:
        handle = 7
        process_id = 70
        title = "Synthetic"
        process_name = "fake.exe"
        is_active = True
        class rect:
            left, top, right, bottom = 0, 0, 2, 2

    monkeypatch.setattr(screenshot, "mss", FakeMSS)
    monkeypatch.setattr(screenshot, "Image", Image)
    monkeypatch.setattr(screenshot, "MSS_BACKEND_AVAILABLE", True)
    monkeypatch.setattr(screenshot.window_manager, "get_bound_window", lambda: Bound())
    monkeypatch.setattr(screenshot.window_manager, "validate_bound_capture_visibility",
        lambda **_: {"allowed": True, "reason": "capture_window_visible"})
    service = screenshot.ScreenshotService()
    service._focus_settle_seconds = 0
    service._capture_keep_limit = 1
    root = (tmp_path / "formal").resolve()

    assert service.capture_window(save_image=False, focus_window=False)["image_path"] is None
    assert not root.exists()
    with pinned_runtime_output_root(root):
        first = Path(service.capture_window(focus_window=False)["image_path"])
        second = Path(service.capture_window(focus_window=False)["image_path"])
    assert first.is_relative_to(root)
    assert second.is_file()
    assert len(list((root / "artifacts/screenshots").glob("*.png"))) == 1


def test_region_crops_are_lazy_and_use_pinned_root(tmp_path: Path) -> None:
    from app.core.runtime_artifacts import pinned_runtime_output_root
    from app.vision import artifacts
    from app.vision.schemas import BBox, Diagonal, ImageSize, NormalizedDiagonal, VisionAnalyzeResponse, VisionRegion

    assert not (tmp_path / "cold").exists()
    source = tmp_path / "source.png"
    Image.new("RGB", (3, 3)).save(source)
    region = VisionRegion(
        region_id="r1", label="one", role="button", bbox=BBox(x=0, y=0, w=2, h=2),
        diagonal=Diagonal(x1=0, y1=0, x2=2, y2=2),
        normalized_diagonal=NormalizedDiagonal(nx1=0, ny1=0, nx2=1, ny2=1), description="synthetic",
    )
    response = VisionAnalyzeResponse(provider="test", screen_summary="synthetic", state_guess=None, regions=[region], image_size=ImageSize(width=3, height=3))
    root = (tmp_path / "formal").resolve()
    with pinned_runtime_output_root(root):
        result = artifacts.save_region_artifacts(source, response)
    assert Path(result["bundle_dir"]).is_relative_to(root)
    assert Path(result["manifest_path"]).is_file()


def test_visual_asset_match_artifacts_follow_each_pinned_root(tmp_path: Path) -> None:
    from app.api.vision import _build_visual_asset_recall
    from app.core.runtime_artifacts import pinned_runtime_output_root
    from app.vision.schemas import ImageSize

    target = tmp_path / "target.png"
    template = tmp_path / "template.png"
    image = Image.new("RGB", (32, 24), "white")
    for x in range(8, 18):
        for y in range(6, 16):
            image.putpixel((x, y), (17, 83, 201))
    image.save(target)
    image.crop((8, 6, 18, 16)).save(template)
    assets = {
        "contract_version": "visual_asset_store_v1",
        "assets": [{
            "asset_id": "synthetic.asset", "label": "Synthetic",
            "semantic_action": "open_apply_flow",
            "crop": {"tight_crop_ref": str(template)},
            "match_policy": {"scale_variants": [1.0], "min_score": 0.1},
        }],
    }
    roots = [(tmp_path / "one").resolve(), (tmp_path / "two").resolve()]
    refs: list[Path] = []
    for root in roots:
        with pinned_runtime_output_root(root):
            recall = _build_visual_asset_recall(
                metadata={"visual_assets": assets}, observe_reuse={}, image_path=target,
                image_size=ImageSize(width=32, height=24), goal="Synthetic",
            )
        ref = Path(recall["matches"][0]["current_roi_ref"])
        assert ref.is_file()
        assert ref.is_relative_to(root)
        refs.append(ref)
    assert refs[0].is_relative_to(roots[0])
    assert refs[1].is_relative_to(roots[1])


def test_observe_task_receives_pinned_artifacts_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api import vision
    from app.api.models.request import VisionObserveScreenRequestModel
    from app.core.runtime_artifacts import pinned_runtime_output_root

    received: list[Path] = []
    monkeypatch.setattr(vision, "run_observe_task", lambda *_args, **kwargs: received.append(kwargs["artifacts_dir"]) or object())
    monkeypatch.setattr(vision, "observe_result_to_legacy_response", lambda _result: {
        "success": True, "message": "synthetic", "data": {"result": {}}, "error": None,
    })
    root = (tmp_path / "formal").resolve()
    with pinned_runtime_output_root(root):
        response = vision.observe_screen(VisionObserveScreenRequestModel(capture_live=False, image_path="synthetic.png"))
    assert response.success is True
    assert received == [root / "artifacts"]
