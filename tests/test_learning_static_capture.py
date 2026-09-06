from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from PIL import Image
import pytest


def _static_inputs(root: Path) -> tuple[Path, dict[str, object]]:
    image = root / "artifacts" / "screenshots" / "static" / "web-01.png"
    image.parent.mkdir(parents=True)
    Image.new("RGB", (160, 90), "white").save(image)
    raw = image.read_bytes()
    manifest = {
        "schema": "public_screenspot_v2_regression_manifest_v1",
        "dataset": "OS-Copilot/ScreenSpot-v2",
        "revision": "5efbb1f1b5463a575f2eb7bc30fe29e49c15f93c",
        "records": [{
            "case_id": "screenspot-v2-web-01",
            "image_sha256": sha256(raw).hexdigest(),
            "image_bytes": len(raw),
            "width": 160,
            "height": 90,
        }],
    }
    manifest_path = root / "artifacts" / "static-manifests" / "public.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return image, {
        "case_id": "screenspot-v2-web-01",
        "dataset": "OS-Copilot/ScreenSpot-v2",
        "revision": "5efbb1f1b5463a575f2eb7bc30fe29e49c15f93c",
        "source_manifest_ref": {
            "relative_path": "artifacts/static-manifests/public.json",
            "sha256": sha256(manifest_path.read_bytes()).hexdigest(),
        },
    }


def _fixed_static_inputs(
    root: Path, monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, dict[str, object], Path]:
    from app.learn.hybrid import static_capture as subject

    image = root / "artifacts" / "screenshots" / "static" / "case-001.png"
    image.parent.mkdir(parents=True)
    Image.new("RGB", (160, 90), "white").save(image)
    raw = image.read_bytes()
    catalog_path = root / "configs" / "benchmarks" / "learning_selection_acceptance_v1.json"
    catalog_path.parent.mkdir(parents=True)
    catalog = {
        "contract_version": "learning_selection_acceptance_v1",
        "inference_rows": [{
            "suite": "fixed25", "case_id": "case-001", "target_id": "case-001-target-01",
            "target_text": "Select the fixed button", "image_sha256": sha256(raw).hexdigest(),
            "image_size": [160, 90],
        }],
    }
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")
    catalog_sha = sha256(catalog_path.read_bytes()).hexdigest()
    monkeypatch.setattr(subject, "FROZEN_SELECTION_CATALOG_SHA256", catalog_sha)
    manifest_path = root / "artifacts" / "static-manifests" / "fixed25.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps({
        "schema": "learning_selection_fixed_capture_manifest_v1",
        "dataset": "portfolio_hybrid_v1_1", "revision": catalog_sha,
        "source_catalog_sha256": catalog_sha,
        "records": [{
            "case_id": "case-001", "image_sha256": sha256(raw).hexdigest(),
            "image_bytes": len(raw), "width": 160, "height": 90,
        }],
    }, ensure_ascii=False), encoding="utf-8")
    return image, {
        "case_id": "case-001", "dataset": "portfolio_hybrid_v1_1", "revision": catalog_sha,
        "source_manifest_ref": {
            "relative_path": "artifacts/static-manifests/fixed25.json",
            "sha256": sha256(manifest_path.read_bytes()).hexdigest(),
        },
    }, manifest_path


def _rewrite_static_asset_manifest(asset: dict[str, object], manifest_path: Path, manifest: dict[str, object]) -> None:
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    reference = asset["source_manifest_ref"]
    assert isinstance(reference, dict)
    reference["sha256"] = sha256(manifest_path.read_bytes()).hexdigest()


def test_static_capture_seals_real_image_without_fake_ocr_or_uia(tmp_path: Path) -> None:
    from app.learn.hybrid.static_capture import seal_static_capture_bundle

    image, static_asset = _static_inputs(tmp_path)
    saved = seal_static_capture_bundle(
        project_root=tmp_path, image_path=image, run_id="static-run",
        workflow_revision=3, static_asset=static_asset,
    )

    assert saved["contract_version"] == "hybrid_static_capture_bundle_v1"
    assert saved["bundle_ref"]["id"].startswith("hybrid-static-capture/")
    assert saved["capture_identity"]["screenshot_sha256"] == sha256(image.read_bytes()).hexdigest()
    assert saved["capture_identity"]["capture_coordinate_space"] == "capture_pixel_xyxy"
    assert saved["context"]["window_binding"] is None
    assert saved["context"]["sources"] == []
    assert saved["context"]["availability"] == {
        "ocr": {"status": "not_collected_static"},
        "uia": {"status": "not_applicable_static", "reason": "no_live_window"},
    }


def test_fixed25_static_capture_uses_only_pinned_inference_image_identity(
    tmp_path: Path,
) -> None:
    from app.learn.hybrid import static_capture as subject
    from app.learn.recognition.uei.contracts import validate_contract

    assert subject.FROZEN_SELECTION_CATALOG_SHA256 == "bb09975c8042f72a59e41fa9f22969cf5104c8419deb5e9d62804ee855a35d92"
    source_catalog = Path(__file__).resolve().parents[1] / "configs" / "benchmarks" / "learning_selection_acceptance_v1.json"
    catalog_path = tmp_path / "configs" / "benchmarks" / source_catalog.name
    catalog_path.parent.mkdir(parents=True)
    catalog_path.write_bytes(source_catalog.read_bytes())
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    row = next(item for item in catalog["inference_rows"] if item["suite"] == "fixed25")
    manifest_path = tmp_path / "artifacts" / "static-manifests" / "fixed25.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps({
        "schema": "learning_selection_fixed_capture_manifest_v1",
        "dataset": "portfolio_hybrid_v1_1", "revision": subject.FROZEN_SELECTION_CATALOG_SHA256,
        "source_catalog_sha256": subject.FROZEN_SELECTION_CATALOG_SHA256,
        "records": [{
            "case_id": row["case_id"], "image_sha256": row["image_sha256"],
            "image_bytes": 1, "width": row["image_size"][0], "height": row["image_size"][1],
        }],
    }, ensure_ascii=False), encoding="utf-8")
    static_asset = {
        "case_id": row["case_id"], "dataset": "portfolio_hybrid_v1_1",
        "revision": subject.FROZEN_SELECTION_CATALOG_SHA256,
        "source_manifest_ref": {
            "relative_path": "artifacts/static-manifests/fixed25.json",
            "sha256": sha256(manifest_path.read_bytes()).hexdigest(),
        },
    }
    asset, record = subject._verified_static_asset(tmp_path, static_asset)

    assert asset["dataset"] == "portfolio_hybrid_v1_1"
    assert record["image_sha256"] == row["image_sha256"]
    validate_contract({
        "contract_version": "hybrid_static_capture_context_v1", "context_id": "context/fixed",
        "run_id": "fixed-run", "workflow_revision": 4,
        "capture_lineage_ref": {"id": "lineage/fixed", "content_sha256": "a" * 64},
        "window_binding": None,
        "static_asset": {
            "case_id": "case-001", "dataset": "portfolio_hybrid_v1_1",
            "revision": "bb09975c8042f72a59e41fa9f22969cf5104c8419deb5e9d62804ee855a35d92",
            "source_manifest_ref": {"relative_path": "artifacts/static-manifests/fixed25.json", "sha256": "b" * 64},
        },
        "availability": {"ocr": {"status": "not_collected_static"}, "uia": {"status": "not_applicable_static", "reason": "no_live_window"}},
        "sources": [], "derived_views": [], "artifact_is_authorization": False,
        "execute_binding_enabled": False, "final_submit_forbidden": True,
        "real_action_requires_gate": True, "authorization_scope": "display_and_review_only",
        "content_sha256": "c" * 64,
    }, contract_version="hybrid_static_capture_context_v1")


def test_fixed25_bundle_crosses_omni_candidate_consumer(tmp_path, monkeypatch):
    from app.learn.hybrid import static_capture
    from app.learn.hybrid.omni_candidates import _validate_static_context
    from app.learn.recognition.uei.canonical import seal_immutable
    image, asset = _static_inputs(tmp_path)
    bundle = static_capture.seal_static_capture_bundle(project_root=tmp_path, image_path=image,
        run_id="fixed-consumer", workflow_revision=0, static_asset=asset)
    # 仅验证封闭静态字段的消费者接缝；文件和目录身份由其他测试独立验证。
    context = bundle["context"]
    context.pop("content_sha256")
    context["static_asset"]["dataset"] = "portfolio_hybrid_v1_1"
    context["static_asset"]["revision"] = static_capture.FROZEN_SELECTION_CATALOG_SHA256
    checked = _validate_static_context(seal_immutable(context))
    assert checked["static_asset"]["dataset"] == "portfolio_hybrid_v1_1"


def test_fixed25_static_capture_rejects_closed_manifest_and_catalog_identity_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import static_capture as subject

    image, static_asset, manifest_path = _fixed_static_inputs(tmp_path / "extra-field", monkeypatch)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["records"][0]["unexpected"] = True
    _rewrite_static_asset_manifest(static_asset, manifest_path, manifest)
    with pytest.raises(ValueError, match="manifest record"):
        subject.seal_static_capture_bundle(
            project_root=tmp_path / "extra-field", image_path=image, run_id="fixed-run",
            workflow_revision=4, static_asset=static_asset,
        )

    image, static_asset, manifest_path = _fixed_static_inputs(tmp_path / "duplicate", monkeypatch)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["records"].append(deepcopy(manifest["records"][0]))
    _rewrite_static_asset_manifest(static_asset, manifest_path, manifest)
    with pytest.raises(ValueError, match="duplicate cases"):
        subject.seal_static_capture_bundle(
            project_root=tmp_path / "duplicate", image_path=image, run_id="fixed-run",
            workflow_revision=4, static_asset=static_asset,
        )

    root = tmp_path / "additional-unknown-case"
    image, static_asset, manifest_path = _fixed_static_inputs(root, monkeypatch)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    additional = deepcopy(manifest["records"][0])
    additional["case_id"] = "case-unknown"
    manifest["records"].append(additional)
    _rewrite_static_asset_manifest(static_asset, manifest_path, manifest)
    with pytest.raises(ValueError, match="does not match fixed25 inference image"):
        subject.seal_static_capture_bundle(
            project_root=root, image_path=image, run_id="fixed-run",
            workflow_revision=4, static_asset=static_asset,
        )

    root = tmp_path / "wrong-dimension"
    image, static_asset, manifest_path = _fixed_static_inputs(root, monkeypatch)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["records"][0]["width"] = 161
    _rewrite_static_asset_manifest(static_asset, manifest_path, manifest)
    with pytest.raises(ValueError, match="does not match fixed25 inference image"):
        subject.seal_static_capture_bundle(
            project_root=root, image_path=image, run_id="fixed-run",
            workflow_revision=4, static_asset=static_asset,
        )

    root = tmp_path / "unknown-case"
    image, static_asset, manifest_path = _fixed_static_inputs(root, monkeypatch)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["records"][0]["case_id"] = "case-unknown"
    static_asset["case_id"] = "case-unknown"
    _rewrite_static_asset_manifest(static_asset, manifest_path, manifest)
    with pytest.raises(ValueError, match="does not match fixed25 inference image"):
        subject.seal_static_capture_bundle(
            project_root=root, image_path=image, run_id="fixed-run",
            workflow_revision=4, static_asset=static_asset,
        )

    root = tmp_path / "wrong-catalog-reference"
    image, static_asset, manifest_path = _fixed_static_inputs(root, monkeypatch)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_catalog_sha256"] = "0" * 64
    _rewrite_static_asset_manifest(static_asset, manifest_path, manifest)
    with pytest.raises(ValueError, match="fixed static asset manifest"):
        subject.seal_static_capture_bundle(
            project_root=root, image_path=image, run_id="fixed-run",
            workflow_revision=4, static_asset=static_asset,
        )

    root = tmp_path / "catalog-sha"
    image, static_asset, _ = _fixed_static_inputs(root, monkeypatch)
    catalog_path = root / "configs" / "benchmarks" / "learning_selection_acceptance_v1.json"
    catalog_path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="catalog hash"):
        subject.seal_static_capture_bundle(
            project_root=root, image_path=image, run_id="fixed-run",
            workflow_revision=4, static_asset=static_asset,
        )


def test_static_capture_loader_rejects_manifest_and_cross_capture_tampering(tmp_path: Path) -> None:
    from app.learn.hybrid.capture import load_and_verify_hybrid_capture_bundle
    from app.learn.hybrid.static_capture import seal_static_capture_bundle

    image, static_asset = _static_inputs(tmp_path)
    saved = seal_static_capture_bundle(
        project_root=tmp_path, image_path=image, run_id="static-run",
        workflow_revision=3, static_asset=static_asset,
    )
    assert load_and_verify_hybrid_capture_bundle(
        project_root=tmp_path, bundle_ref=saved["bundle_ref"],
        expected_run_id="static-run", expected_workflow_revision=3,
    )["capture_identity"] == saved["capture_identity"]

    manifest = tmp_path / "artifacts" / "static-manifests" / "public.json"
    manifest.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="manifest"):
        load_and_verify_hybrid_capture_bundle(
            project_root=tmp_path, bundle_ref=saved["bundle_ref"],
            expected_run_id="static-run", expected_workflow_revision=3,
        )
    with pytest.raises(ValueError, match="cross-run"):
        load_and_verify_hybrid_capture_bundle(
            project_root=tmp_path, bundle_ref=saved["bundle_ref"],
            expected_run_id="other-run", expected_workflow_revision=3,
        )


def test_static_capture_forms_an_omni_inventory_with_a_fixture_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import omni_discovery
    from app.learn.hybrid.static_capture import seal_static_capture_bundle
    from app.learn.recognition.uei.canonical import seal_immutable
    from app.learn.recognition.uei.store import UEIObjectStore
    from tests.test_learn_hybrid_omni_discovery import _RecordedAdapter

    image, static_asset = _static_inputs(tmp_path)
    bundle = seal_static_capture_bundle(
        project_root=tmp_path, image_path=image, run_id="static-run",
        workflow_revision=3, static_asset=static_asset,
    )
    store = UEIObjectStore(root=tmp_path / "artifacts" / "uei-shadow-store")

    def put(value: dict[str, object]) -> dict[str, str]:
        return store.put(seal_immutable(value))

    provider_id, profile_id = _RecordedAdapter.provider_id, _RecordedAdapter.profile_id
    request = put({
        "contract_version": "screen_parse_request_v1", "request_id": "request/static-omni",
        "capture_lineage_ref": deepcopy(bundle["capture_lineage_ref"]),
        "requested_profiles": [{"provider_id": provider_id, "profile_id": profile_id, "mode": "Shadow"}],
        "privacy_policy": "restricted", "requester_id": "server",
    })
    registration = put({
        "contract_version": "trusted_provider_registration_v1", "registration_id": "registration/static-omni",
        "provider_id": provider_id, "profile_ids": [profile_id], "enabled": True,
        "allowed_modes": ["Shadow"], "allowed_privacy_policies": ["restricted"],
        "egress_policy": "local_only", "wire_payload_policy": "restricted_store_only",
        "safe_payload_limits": {"max_json_bytes": 4096, "max_depth": 8, "max_array_items": 16, "max_object_properties": 32, "max_string_chars": 256, "allowed_json_types": ["object", "array", "string", "number", "boolean", "null"]},
        "required_conformance_suite": "uei-v1-static-projection",
    })
    manifest = put({
        "contract_version": "provider_manifest_v1", "manifest_id": "manifest/static-omni",
        "provider_id": provider_id, "provider_version": _RecordedAdapter.provider_version,
        "profiles": [{"profile_id": profile_id, "operation": "screen_parse", "input_contract": "screen_parse_request_v1", "output_contract": "provider_safe_result_v1", "declared_output_kinds": ["element"], "supported_coordinate_spaces": ["capture_pixel_xyxy"], "supports_capture_artifact": True, "privacy_capabilities": ["restricted"], "mode_allowlist": ["Shadow"]}],
    })
    monkeypatch.setattr(omni_discovery, "OmniParserShadowAdapter", _RecordedAdapter)
    result = omni_discovery.run_hybrid_omni_discovery({
        "project_root": str(tmp_path), "run_id": "static-run", "workflow_revision": 3,
        "hybrid_capture_bundle_ref": deepcopy(bundle["bundle_ref"]), "request_ref": request,
        "registration_ref": registration, "manifest_ref": manifest,
        "capture_image_path": image.relative_to(tmp_path).as_posix(),
    })
    assert result["outcome"] == "completed"
    assert result["inventory"]["capture_identity"] == bundle["capture_identity"]


def test_live_v1_still_rejects_missing_uia(tmp_path: Path) -> None:
    from app.learn.hybrid.capture import seal_hybrid_capture_bundle, seal_hybrid_capture_identity

    image, _ = _static_inputs(tmp_path)
    binding = {
        "window_binding_id": "live-window", "process_id": 123,
        "process_name": "live.exe", "rect": {"left": 0, "top": 0, "right": 160, "bottom": 90},
    }
    identity = seal_hybrid_capture_identity(
        project_root=tmp_path, image_path=image, run_id="live-run",
        workflow_revision=3, window_binding=binding,
    )
    with pytest.raises(ValueError, match="exactly two sources"):
        seal_hybrid_capture_bundle(
            project_root=tmp_path, image_path=image, run_id="live-run",
            workflow_revision=3, window_binding=binding,
            ocr_uia_context={
                "capture_lineage_ref": identity["capture_lineage_ref"],
                "sources": [], "derived_views": [],
            },
            capture_envelope=identity.capture_envelope,
        )
