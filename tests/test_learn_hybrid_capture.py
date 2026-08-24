from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest
from PIL import Image

from app.learn.recognition.uei.canonical import seal_immutable
from app.learn.recognition.uei.store import UEIObjectStore


def _image(path: Path, *, size: tuple[int, int] = (8, 6), color=(10, 20, 30)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color=color).save(path)
    return path


def _window() -> dict[str, object]:
    return {
        "window_binding_id": "window:101",
        "process_id": 202,
        "process_name": "fixture.exe",
        "rect": {"left": 10, "top": 20, "right": 810, "bottom": 620},
    }


def _identity(root: Path, *, run_id: str = "run-a", revision: int = 7, name="capture.png", size=(8, 6)):
    from app.learn.hybrid.capture import seal_hybrid_capture_identity

    image_path = _image(root / "artifacts" / "screenshots" / name, size=size)
    return image_path, seal_hybrid_capture_identity(
        project_root=root,
        image_path=image_path,
        run_id=run_id,
        workflow_revision=revision,
        window_binding=_window(),
        captured_at="2026-08-25T00:00:00Z",
    )


def _put(store: UEIObjectStore, value: dict[str, object]) -> dict[str, str]:
    return store.put(seal_immutable(value))


def _provider_evidence(
    root: Path,
    *,
    capture_lineage_ref: dict[str, str],
    source_kind: str,
    suffix: str,
) -> dict[str, str]:
    store = UEIObjectStore(root=root / "artifacts" / "uei-shadow-store")
    provider_id = f"local.test/{source_kind}"
    profile_id = f"local.test/{source_kind}/v1"
    request_ref = _put(store, {
        "contract_version": "screen_parse_request_v1",
        "request_id": f"request/{suffix}",
        "capture_lineage_ref": capture_lineage_ref,
        "requested_profiles": [{
            "provider_id": provider_id,
            "profile_id": profile_id,
            "mode": "Advisory",
        }],
        "privacy_policy": "minimal",
        "requester_id": "server",
    })
    registration_ref = _put(store, {
        "contract_version": "trusted_provider_registration_v1",
        "registration_id": f"registration/{suffix}",
        "provider_id": provider_id,
        "profile_ids": [profile_id],
        "enabled": True,
        "allowed_modes": ["Advisory"],
        "allowed_privacy_policies": ["minimal"],
        "egress_policy": "local_only",
        "wire_payload_policy": "restricted_store_only",
        "safe_payload_limits": {
            "max_json_bytes": 4096,
            "max_depth": 6,
            "max_array_items": 16,
            "max_object_properties": 16,
            "max_string_chars": 256,
            "allowed_json_types": ["object", "array", "string", "number", "boolean", "null"],
        },
        "required_conformance_suite": "uei-v1-static-projection",
    })
    manifest_ref = _put(store, {
        "contract_version": "provider_manifest_v1",
        "manifest_id": f"manifest/{suffix}",
        "provider_id": provider_id,
        "provider_version": "test-1",
        "profiles": [{
            "profile_id": profile_id,
            "operation": "screen_parse",
            "input_contract": "screen_parse_request_v1",
            "output_contract": "provider_safe_result_v1",
            "declared_output_kinds": ["text" if source_kind == "ocr" else "element"],
            "supported_coordinate_spaces": ["capture_pixel_xyxy"],
            "supports_capture_artifact": True,
            "privacy_capabilities": ["minimal"],
            "mode_allowlist": ["Advisory"],
        }],
    })
    return _put(store, {
        "contract_version": "provider_safe_result_v1",
        "result_id": f"result/{suffix}",
        "request_ref": request_ref,
        "requested_provider_id": provider_id,
        "requested_profile_id": profile_id,
        "registration_resolution": "resolved",
        "manifest_resolution": "resolved",
        "registration_ref": registration_ref,
        "manifest_ref": manifest_ref,
        "provider_id": provider_id,
        "profile_id": profile_id,
        "provider_version": "test-1",
        "capture_lineage_ref": capture_lineage_ref,
        "status": "success",
        "review_only": True,
        "items": [],
        "redaction_summary": {
            "redacted_item_count": 0,
            "redacted_field_count": 0,
            "secret_detected": False,
            "sensitive_categories": [],
        },
    })


def _source(
    *, kind: str, evidence_ref: dict[str, str], lineage_ref: dict[str, str], run_id="run-a", revision=7
) -> dict[str, object]:
    return {
        "source_kind": kind,
        "capture_lineage_ref": lineage_ref,
        "run_id": run_id,
        "workflow_revision": revision,
        "window_binding": _window(),
        "evidence_contract_version": "provider_safe_result_v1",
        "evidence_ref": evidence_ref,
    }


def _context(root: Path, identity: dict[str, object], *, run_id="run-a", revision=7):
    lineage_ref = identity["capture_lineage_ref"]
    ocr = _provider_evidence(
        root, capture_lineage_ref=lineage_ref, source_kind="ocr", suffix=f"{run_id}-ocr-{revision}"
    )
    uia = _provider_evidence(
        root, capture_lineage_ref=lineage_ref, source_kind="uia", suffix=f"{run_id}-uia-{revision}"
    )
    return {
        "capture_lineage_ref": lineage_ref,
        "sources": [
            _source(kind="ocr", evidence_ref=ocr, lineage_ref=lineage_ref, run_id=run_id, revision=revision),
            _source(kind="uia", evidence_ref=uia, lineage_ref=lineage_ref, run_id=run_id, revision=revision),
        ],
        "derived_views": [],
    }


def _bundle(root: Path, *, run_id="run-a", revision=7):
    from app.learn.hybrid.capture import seal_hybrid_capture_bundle

    image_path, identity = _identity(root, run_id=run_id, revision=revision)
    return seal_hybrid_capture_bundle(
        project_root=root,
        image_path=image_path,
        run_id=run_id,
        workflow_revision=revision,
        window_binding=_window(),
        ocr_uia_context=_context(root, identity, run_id=run_id, revision=revision),
    )


def test_valid_same_capture_ocr_uia_context_is_uei_native_and_loadable(tmp_path: Path) -> None:
    from app.learn.hybrid.capture import load_and_verify_hybrid_capture_bundle

    bundle = _bundle(tmp_path)
    loaded = load_and_verify_hybrid_capture_bundle(
        project_root=tmp_path,
        bundle_ref=bundle["bundle_ref"],
        expected_run_id="run-a",
        expected_workflow_revision=7,
    )

    assert loaded["run_id"] == "run-a"
    assert loaded["workflow_revision"] == 7
    assert [source["source_kind"] for source in loaded["context"]["sources"]] == ["ocr", "uia"]
    assert all(source["capture_lineage_ref"] == loaded["capture_identity"]["capture_lineage_ref"]
               for source in loaded["context"]["sources"])
    store = UEIObjectStore(root=tmp_path / "artifacts" / "uei-shadow-store")
    assert store.get(bundle["context_ref"], contract_version="hybrid_capture_context_v1") == loaded["context"]
    stored_bundle = store.get(bundle["bundle_ref"], contract_version="hybrid_capture_bundle_v1")
    assert {field: loaded[field] for field in stored_bundle} == stored_bundle


def test_bundle_reads_canonical_screenshot_once_and_derives_exact_facts(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import app.learn.hybrid.capture as capture_module

    image_path, identity = _identity(tmp_path)
    context = _context(tmp_path, identity)
    image_open_count = 0
    original_open = capture_module.os.open

    def counted_open(path, *args, **kwargs):
        nonlocal image_open_count
        if Path(path).resolve() == image_path.resolve():
            image_open_count += 1
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(capture_module.os, "open", counted_open)
    bundle = capture_module.seal_hybrid_capture_bundle(
        project_root=tmp_path,
        image_path=image_path,
        run_id="run-a",
        workflow_revision=7,
        window_binding=_window(),
        ocr_uia_context=context,
    )

    expected_sha = sha256(image_path.read_bytes()).hexdigest()
    assert image_open_count == 1
    assert bundle["capture_identity"]["artifact_sha256"] == expected_sha
    assert bundle["capture_identity"]["screenshot_sha256"] == expected_sha
    assert bundle["capture_identity"]["image_size"] == {"width": 8, "height": 6}


def test_raw_ocr_uia_snapshot_fields_are_not_a_context_contract(tmp_path: Path) -> None:
    from app.learn.hybrid.capture import seal_hybrid_capture_bundle

    image_path, identity = _identity(tmp_path)
    with pytest.raises(ValueError, match="closed object"):
        seal_hybrid_capture_bundle(
            project_root=tmp_path,
            image_path=image_path,
            run_id="run-a",
            workflow_revision=7,
            window_binding=_window(),
            ocr_uia_context={
                "capture_lineage_ref": identity["capture_lineage_ref"],
                "sources": [],
                "derived_views": [],
                "qwen_payload": {"raw": True},
            },
        )


def test_builtin_ocr_hybrid_path_reuses_exact_sealed_lineage(tmp_path: Path) -> None:
    from app.learn.recognition.uei.builtin_learning_projection import seal_builtin_ocr_evidence

    image_path, identity = _identity(tmp_path)
    result_ref = seal_builtin_ocr_evidence(
        project_root=tmp_path,
        image_path=image_path,
        capture_id=identity["capture_id"],
        captured_at=identity["captured_at"],
        capture_lineage_ref=identity["capture_lineage_ref"],
        expected_image_sha256=identity["artifact_sha256"],
        expected_image_size=identity["image_size"],
        ocr_result={
            "matches": [{
                "text": "Search",
                "score": 0.9,
                "bbox": {"x": 1, "y": 1, "width": 4, "height": 2},
            }],
            "metadata": {"engine": "builtin"},
        },
    )
    store = UEIObjectStore(root=tmp_path / "artifacts" / "uei-shadow-store")
    result = store.get(result_ref, contract_version="provider_safe_result_v1")
    assert result["capture_lineage_ref"] == identity["capture_lineage_ref"]
    assert store.object_count(contract_version="capture_lineage_v1") == 1


def test_cross_capture_source_and_nested_authority_fail_closed(tmp_path: Path) -> None:
    from app.learn.hybrid.capture import seal_hybrid_capture_bundle

    image_path, identity = _identity(tmp_path, run_id="run-a")
    _, other = _identity(tmp_path, run_id="run-b", name="other.png")
    context = _context(tmp_path, identity)
    cross = _provider_evidence(
        tmp_path,
        capture_lineage_ref=other["capture_lineage_ref"],
        source_kind="ocr",
        suffix="cross-ocr",
    )
    context["sources"][0]["evidence_ref"] = cross
    with pytest.raises(ValueError, match="cross-capture evidence"):
        seal_hybrid_capture_bundle(
            project_root=tmp_path, image_path=image_path, run_id="run-a", workflow_revision=7,
            window_binding=_window(), ocr_uia_context=context,
        )

    context = _context(tmp_path, identity)
    context["sources"][0]["window_binding"]["approved_to_click"] = True
    with pytest.raises(ValueError, match="window binding|closed|authority"):
        seal_hybrid_capture_bundle(
            project_root=tmp_path, image_path=image_path, run_id="run-a", workflow_revision=7,
            window_binding=_window(), ocr_uia_context=context,
        )


def test_capture_path_must_be_under_screenshot_service_root(tmp_path: Path) -> None:
    from app.learn.hybrid.capture import seal_hybrid_capture_identity

    outside = _image(tmp_path / "arbitrary.png")
    with pytest.raises(ValueError, match="screenshot service root"):
        seal_hybrid_capture_identity(
            project_root=tmp_path, image_path=outside, run_id="run-a", workflow_revision=7,
            window_binding=_window(), captured_at="2026-08-25T00:00:00Z",
        )


def test_derived_target_artifact_and_affine_are_resolved_semantically(tmp_path: Path) -> None:
    from app.learn.hybrid.capture import (
        load_and_verify_hybrid_capture_bundle,
        seal_hybrid_capture_bundle,
    )

    source_path, source = _identity(tmp_path, name="source.png", size=(8, 6))
    _, target = _identity(tmp_path, name="target.png", size=(4, 3))
    store = UEIObjectStore(root=tmp_path / "artifacts" / "uei-shadow-store")
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
        "source_capture_artifact_sha256": source["artifact_sha256"],
        "target_capture_artifact_sha256": target["artifact_sha256"],
    })
    transform_ref = store.put(transform)
    context = _context(tmp_path, source)
    context["derived_views"] = [{
        "target_capture_lineage_ref": target["capture_lineage_ref"],
        "target_artifact_ref": target["artifact_ref"],
        "coordinate_transform_ref": transform_ref,
    }]
    bundle = seal_hybrid_capture_bundle(
        project_root=tmp_path, image_path=source_path, run_id="run-a", workflow_revision=7,
        window_binding=_window(), ocr_uia_context=context,
    )
    assert bundle["context"]["derived_views"][0]["target_artifact"]["artifact_sha256"] == target["artifact_sha256"]
    assert load_and_verify_hybrid_capture_bundle(
        project_root=tmp_path,
        bundle_ref=bundle["bundle_ref"],
        expected_run_id="run-a",
        expected_workflow_revision=7,
    )["context"]["derived_views"][0]["coordinate_transform"] == transform

    bad = deepcopy(transform)
    bad.pop("content_sha256")
    bad["scale"] = {"x": 0.25, "y": 0.5}
    context["derived_views"][0]["coordinate_transform_ref"] = store.put(seal_immutable(bad))
    with pytest.raises(ValueError, match="affine scale mismatch"):
        seal_hybrid_capture_bundle(
            project_root=tmp_path, image_path=source_path, run_id="run-a", workflow_revision=7,
            window_binding=_window(), ocr_uia_context=context,
        )

    wrong_size = deepcopy(transform)
    wrong_size.pop("content_sha256")
    wrong_size["target_size"] = {"width": 5, "height": 3}
    context["derived_views"][0]["coordinate_transform_ref"] = store.put(
        seal_immutable(wrong_size)
    )
    with pytest.raises(ValueError, match="derived affine binding mismatch"):
        seal_hybrid_capture_bundle(
            project_root=tmp_path, image_path=source_path, run_id="run-a", workflow_revision=7,
            window_binding=_window(), ocr_uia_context=context,
        )

    context["derived_views"][0]["target_artifact_ref"] = {
        "id": "artifact/missing", "content_sha256": "f" * 64
    }
    with pytest.raises(ValueError):
        seal_hybrid_capture_bundle(
            project_root=tmp_path, image_path=source_path, run_id="run-a", workflow_revision=7,
            window_binding=_window(), ocr_uia_context=context,
        )


def test_run_scoped_freshness_supports_concurrent_runs(tmp_path: Path) -> None:
    from app.learn.hybrid.capture import load_and_verify_hybrid_capture_bundle

    first = _bundle(tmp_path / "shared", run_id="run-a", revision=7)
    second = _bundle(tmp_path / "shared", run_id="run-b", revision=7)
    assert load_and_verify_hybrid_capture_bundle(
        project_root=tmp_path / "shared", bundle_ref=first["bundle_ref"],
        expected_run_id="run-a", expected_workflow_revision=7,
    )["run_id"] == "run-a"
    assert load_and_verify_hybrid_capture_bundle(
        project_root=tmp_path / "shared", bundle_ref=second["bundle_ref"],
        expected_run_id="run-b", expected_workflow_revision=7,
    )["run_id"] == "run-b"
    with pytest.raises(ValueError, match="cross-run bundle"):
        load_and_verify_hybrid_capture_bundle(
            project_root=tmp_path / "shared", bundle_ref=first["bundle_ref"],
            expected_run_id="run-b", expected_workflow_revision=7,
        )


def test_unverified_screen_observe_ref_never_suppresses_legacy_path() -> None:
    from app.learn.workflow_continuation import interpret_learning_stage_worker_result

    ref = {"id": "hybrid-capture/fabricated", "content_sha256": "a" * 64}
    decision = interpret_learning_stage_worker_result(
        stage="screen_understanding",
        task_kind="vision_observe_screen",
        response={"success": True, "data": {"result": {
            "image_path": "artifacts/screenshots/current.png",
            "hybrid_capture_bundle_ref": ref,
            "screen_size": {"width": 8, "height": 6},
        }}},
    )
    evidence = decision["next_worker"]["payload"]["observation_evidence"]
    assert evidence["current_image_path"] == "artifacts/screenshots/current.png"
    assert "hybrid_capture_bundle_ref" not in evidence


def test_windows_reparse_capture_is_rejected_or_explicitly_skipped(tmp_path: Path) -> None:
    from app.learn.hybrid.capture import seal_hybrid_capture_identity

    screenshots = tmp_path / "artifacts" / "screenshots"
    real = _image(screenshots / "real.png")
    link = screenshots / "linked.png"
    try:
        link.symlink_to(real)
    except OSError as error:
        pytest.skip(f"Windows symlink creation unavailable: {error}")
    with pytest.raises(ValueError, match="reparse point"):
        seal_hybrid_capture_identity(
            project_root=tmp_path, image_path=link, run_id="run-a", workflow_revision=7,
            window_binding=_window(), captured_at="2026-08-25T00:00:00Z",
        )
