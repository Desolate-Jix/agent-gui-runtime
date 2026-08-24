from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest
from PIL import Image

from app.learn.recognition.uei.canonical import canonical_json_bytes, seal_immutable
from app.learn.recognition.uei.store import UEIObjectStore


def _image(path: Path, *, color: tuple[int, int, int] = (10, 20, 30)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 6), color=color).save(path)
    return path


def _context(*, derived_views: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "ocr": {
            "provenance": {"engine": "windows-ocr", "revision": "ocr-1"},
            "items": [{"text": "Search", "bbox": [1, 1, 5, 3]}],
        },
        "uia": {
            "provenance": {"adapter": "windows-uia", "revision": "uia-1"},
            "nodes": [{"automation_id": "search", "role": "edit"}],
        },
        "derived_views": derived_views or [],
    }


def _window() -> dict[str, object]:
    return {
        "window_binding_id": "window:101",
        "process_id": 202,
        "process_name": "fixture.exe",
        "rect": {"left": 10, "top": 20, "right": 810, "bottom": 620},
    }


def _seal(root: Path, *, revision: str = "7", color: tuple[int, int, int] = (10, 20, 30)):
    from app.learn.hybrid.capture import seal_hybrid_capture_bundle

    return seal_hybrid_capture_bundle(
        project_root=root,
        image_path=_image(root / "artifacts" / "screenshots" / f"capture-{revision}.png", color=color),
        workflow_revision=revision,
        window_binding=_window(),
        ocr_uia_context=_context(),
    )


def _store_forged_bundle(root: Path, value: dict[str, object]) -> dict[str, str]:
    sealed = seal_immutable(value)
    bundle_id = str(sealed["bundle_id"])
    digest = str(sealed["content_sha256"])
    path = root / "artifacts" / "hybrid-capture-store" / "objects" / f"{digest}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(sealed))
    return {"id": bundle_id, "content_sha256": digest}


def test_seal_reads_once_and_persists_exact_capture_and_context(monkeypatch, tmp_path: Path) -> None:
    import app.learn.hybrid.capture as capture_module

    image_path = _image(tmp_path / "artifacts" / "screenshots" / "capture.png")
    image_bytes = image_path.read_bytes()
    calls = 0
    original = capture_module._read_server_owned_image

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(capture_module, "_read_server_owned_image", counted)
    bundle = capture_module.seal_hybrid_capture_bundle(
        project_root=tmp_path,
        image_path=image_path,
        workflow_revision="7",
        window_binding=_window(),
        ocr_uia_context=_context(),
    )
    loaded = capture_module.load_and_verify_hybrid_capture_bundle(
        project_root=tmp_path, bundle_ref=bundle["bundle_ref"]
    )

    expected_sha = sha256(image_bytes).hexdigest()
    identity = loaded["capture_identity"]
    assert calls == 1
    assert identity["artifact_sha256"] == expected_sha
    assert identity["screenshot_sha256"] == expected_sha
    assert identity["image_size"] == {"width": 8, "height": 6}
    assert identity["workflow_revision"] == "7"
    assert identity["artifact"]["artifact_sha256"] == expected_sha
    assert identity["capture_lineage"]["artifact_sha256"] == expected_sha
    assert identity["artifact_ref"]["content_sha256"] != expected_sha
    assert identity["capture_lineage_ref"]["content_sha256"] != expected_sha
    assert loaded["capture_lineage_ref"] == identity["capture_lineage_ref"]
    assert loaded["context_ref"]["content_sha256"] == loaded["context"]["content_sha256"]
    assert loaded["context"]["capture_lineage_ref"] == identity["capture_lineage_ref"]
    assert loaded["context"]["workflow_revision"] == "7"
    assert loaded["context"]["window_binding"] == _window()
    assert loaded["context"]["ocr_uia_context"]["ocr"]["provenance"]["engine"] == "windows-ocr"
    assert loaded["context"]["ocr_uia_context"]["uia"]["provenance"]["adapter"] == "windows-uia"

    store = UEIObjectStore(root=tmp_path / "artifacts" / "uei-shadow-store")
    assert store.get(identity["artifact_ref"], contract_version="artifact_ref_v1") == identity["artifact"]
    assert store.get(identity["capture_lineage_ref"], contract_version="capture_lineage_v1") == identity["capture_lineage"]


def test_loader_rejects_client_forged_path_or_ref(tmp_path: Path) -> None:
    from app.learn.hybrid.capture import load_and_verify_hybrid_capture_bundle

    bundle = _seal(tmp_path)
    for forged in (
        {**bundle["bundle_ref"], "image_path": "Z:/forged.png"},
        {"id": bundle["bundle_ref"]["id"], "content_sha256": "0" * 64},
    ):
        with pytest.raises(ValueError):
            load_and_verify_hybrid_capture_bundle(project_root=tmp_path, bundle_ref=forged)


def test_stale_workflow_revision_fails_closed(tmp_path: Path) -> None:
    from app.learn.hybrid.capture import load_and_verify_hybrid_capture_bundle

    stale = _seal(tmp_path, revision="7")
    _seal(tmp_path, revision="8", color=(30, 20, 10))
    with pytest.raises(ValueError, match="stale workflow revision"):
        load_and_verify_hybrid_capture_bundle(project_root=tmp_path, bundle_ref=stale["bundle_ref"])


def test_conflicting_valid_lineage_refs_fail_closed(tmp_path: Path) -> None:
    from app.learn.hybrid.capture import load_and_verify_hybrid_capture_bundle

    first = _seal(tmp_path / "one", revision="7")
    second = _seal(tmp_path / "two", revision="7", color=(30, 20, 10))
    loaded = load_and_verify_hybrid_capture_bundle(
        project_root=tmp_path / "one", bundle_ref=first["bundle_ref"]
    )
    forged = deepcopy(loaded)
    forged.pop("content_sha256")
    forged["capture_lineage_ref"] = second["capture_lineage_ref"]
    forged_ref = _store_forged_bundle(tmp_path / "one", forged)
    with pytest.raises(ValueError, match="capture lineage conflict"):
        load_and_verify_hybrid_capture_bundle(project_root=tmp_path / "one", bundle_ref=forged_ref)


def test_cross_capture_provider_result_fails_closed(tmp_path: Path) -> None:
    from app.learn.hybrid.capture import seal_hybrid_capture_bundle
    from app.learn.recognition.uei.builtin_learning_projection import seal_builtin_ocr_evidence

    other_image = _image(tmp_path / "artifacts" / "screenshots" / "other.png", color=(1, 2, 3))
    other_ref = seal_builtin_ocr_evidence(
        project_root=tmp_path,
        image_path=other_image,
        capture_id="capture/other",
        captured_at="2026-08-25T00:00:00Z",
        ocr_result={
            "matches": [{
                "text": "Other",
                "score": 0.9,
                "bbox": {"x": 1, "y": 1, "width": 3, "height": 2},
            }],
            "metadata": {"engine": "fixture"},
        },
    )
    with pytest.raises(ValueError, match="cross-capture evidence"):
        seal_hybrid_capture_bundle(
            project_root=tmp_path,
            image_path=_image(tmp_path / "artifacts" / "screenshots" / "current.png"),
            workflow_revision="7",
            window_binding=_window(),
            ocr_uia_context={**_context(), "ocr_result_ref": other_ref},
        )


def test_derived_view_transform_must_bind_source_and_target_sha(tmp_path: Path) -> None:
    from app.learn.hybrid.capture import seal_hybrid_capture_bundle

    image_path = _image(tmp_path / "artifacts" / "screenshots" / "capture.png")
    target_sha = "b" * 64
    transform = seal_immutable({
        "contract_version": "affine_coordinate_transform_v1",
        "source_space": "capture_pixel_xyxy",
        "target_space": "image_pixel_xyxy",
        "source_size": {"width": 8, "height": 6},
        "target_size": {"width": 4, "height": 3},
        "scale": {"x": 0.5, "y": 0.5},
        "offset": {"x": 0, "y": 0},
        "rounding": "outward",
        "clipping": "reject_if_outside",
        "source_capture_artifact_sha256": "a" * 64,
        "target_capture_artifact_sha256": target_sha,
    })
    context = _context(derived_views=[{
        "target_artifact_sha256": target_sha,
        "coordinate_transform": transform,
    }])
    with pytest.raises(ValueError, match="transform source artifact SHA mismatch"):
        seal_hybrid_capture_bundle(
            project_root=tmp_path,
            image_path=image_path,
            workflow_revision="7",
            window_binding=_window(),
            ocr_uia_context=context,
        )


def test_raw_provider_payload_and_path_escape_are_rejected(tmp_path: Path) -> None:
    from app.learn.hybrid.capture import seal_hybrid_capture_bundle

    outside = _image(tmp_path.parent / "outside-hybrid-capture.png")
    with pytest.raises(ValueError, match="server-owned image"):
        seal_hybrid_capture_bundle(
            project_root=tmp_path,
            image_path=outside,
            workflow_revision="7",
            window_binding=_window(),
            ocr_uia_context=_context(),
        )
    with pytest.raises(ValueError, match="raw provider payload"):
        seal_hybrid_capture_bundle(
            project_root=tmp_path,
            image_path=_image(tmp_path / "artifacts" / "screenshots" / "capture.png"),
            workflow_revision="7",
            window_binding=_window(),
            ocr_uia_context={**_context(), "qwen_payload": {"raw": "not allowed"}},
        )


def test_symlink_and_capture_read_race_fail_closed(monkeypatch, tmp_path: Path) -> None:
    import app.learn.hybrid.capture as capture_module

    screenshots = tmp_path / "artifacts" / "screenshots"
    real = _image(screenshots / "real.png")
    link = screenshots / "linked.png"
    try:
        link.symlink_to(real)
    except OSError:
        link = None
    if link is not None:
        with pytest.raises(ValueError, match="reparse point"):
            capture_module.seal_hybrid_capture_bundle(
                project_root=tmp_path,
                image_path=link,
                workflow_revision="7",
                window_binding=_window(),
                ocr_uia_context=_context(),
            )

    comparisons = 0
    original = capture_module._same_file_state

    def changed_during_read(left, right):
        nonlocal comparisons
        comparisons += 1
        return False if comparisons == 2 else original(left, right)

    monkeypatch.setattr(capture_module, "_same_file_state", changed_during_read)
    with pytest.raises(ValueError, match="changed during read"):
        capture_module.seal_hybrid_capture_bundle(
            project_root=tmp_path,
            image_path=real,
            workflow_revision="7",
            window_binding=_window(),
            ocr_uia_context=_context(),
        )


def test_screen_observe_prefers_sealed_bundle_ref_without_changing_legacy_default() -> None:
    from app.learn.workflow_continuation import interpret_learning_stage_worker_result

    ref = {"id": "hybrid-capture/example", "content_sha256": "a" * 64}
    decision = interpret_learning_stage_worker_result(
        stage="screen_understanding",
        task_kind="vision_observe_screen",
        response={
            "success": True,
            "data": {"result": {
                "image_path": "artifacts/screenshots/current.png",
                "hybrid_capture_bundle_ref": ref,
                "screen_size": {"width": 8, "height": 6},
            }},
        },
    )
    evidence = decision["next_worker"]["payload"]["observation_evidence"]
    assert evidence["hybrid_capture_bundle_ref"] == ref
    assert "current_image_path" not in evidence

    legacy = interpret_learning_stage_worker_result(
        stage="screen_understanding",
        task_kind="vision_observe_screen",
        response={"success": True, "data": {"result": {"image_path": "legacy.png"}}},
    )
    assert legacy["next_worker"]["payload"]["observation_evidence"]["current_image_path"] == "legacy.png"
