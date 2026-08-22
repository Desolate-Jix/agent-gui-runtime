"""学习边界使用的服务端内置 OCR 证据投影。"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any

from PIL import Image

from app.learn.recognition.uei.canonical import seal_immutable
from app.learn.recognition.uei.projections import project_ocr_result
from app.learn.recognition.uei.store import UEIObjectStore


_STORE_RELATIVE_PATH = Path("artifacts") / "uei-shadow-store"
_PROVIDER_ID = "local.runtime/builtin-ocr"
_PROFILE_ID = "local.runtime/builtin-ocr/v1"
_SAFE_LIMITS: dict[str, object] = {
    "max_json_bytes": 65536,
    "max_depth": 8,
    "max_array_items": 256,
    "max_object_properties": 64,
    "max_string_chars": 4096,
    "allowed_json_types": ["object", "array", "string", "number", "boolean", "null"],
}


def seal_builtin_ocr_evidence(
    *,
    project_root: Path,
    image_path: Path,
    capture_id: str,
    captured_at: str,
    ocr_result: dict[str, object],
    expected_image_sha256: str | None = None,
    expected_image_size: dict[str, int] | None = None,
) -> dict[str, str]:
    """把服务端截图与内置 OCR 结果封装成仅供审阅的 UEI 引用。"""
    root = project_root.resolve()
    image = image_path.resolve()
    try:
        image.relative_to(root)
    except ValueError as error:
        raise ValueError("server-owned image must be inside project root") from error
    if not image.is_file() or image.is_symlink():
        raise ValueError("server-owned image must be a regular project file")
    if not isinstance(capture_id, str) or not capture_id.strip():
        raise ValueError("capture_id is required")
    if not isinstance(captured_at, str) or not captured_at.strip():
        raise ValueError("captured_at is required")
    if not isinstance(ocr_result, dict):
        raise ValueError("built-in OCR result must be an object")

    image_bytes = image.read_bytes()
    artifact_sha256 = sha256(image_bytes).hexdigest()
    with Image.open(image) as opened:
        image_size = {"width": int(opened.width), "height": int(opened.height)}
    if expected_image_sha256 is not None and expected_image_sha256 != artifact_sha256:
        raise ValueError("server-owned image SHA-256 mismatch")
    if expected_image_size is not None and expected_image_size != image_size:
        raise ValueError("server-owned image dimensions mismatch")

    store = UEIObjectStore(root=root / _STORE_RELATIVE_PATH)
    capture_token = sha256((capture_id + artifact_sha256).encode("utf-8")).hexdigest()[:24]
    artifact_ref = _put(store, {
        "contract_version": "artifact_ref_v1",
        "artifact_id": f"artifact/server-owned/{artifact_sha256}",
        "artifact_sha256": artifact_sha256,
        "media_type": "image/png",
        "byte_length": len(image_bytes),
        "restricted": True,
    })
    capture_ref = _put(store, {
        "contract_version": "capture_lineage_v1",
        "capture_id": capture_id,
        "artifact_ref": artifact_ref,
        "artifact_sha256": artifact_sha256,
        "image_size": image_size,
        "capture_coordinate_space": "capture_pixel_xyxy",
        "captured_at": captured_at,
    })
    request_ref = _put(store, {
        "contract_version": "screen_parse_request_v1",
        "request_id": f"request/server-owned/{capture_token}",
        "capture_lineage_ref": capture_ref,
        "requested_profiles": [{
            "provider_id": _PROVIDER_ID,
            "profile_id": _PROFILE_ID,
            "mode": "Advisory",
        }],
        "privacy_policy": "minimal",
        "requester_id": "server",
    })
    registration_ref = _put(store, {
        "contract_version": "trusted_provider_registration_v1",
        "registration_id": "registration/local.runtime/builtin-ocr/v1",
        "provider_id": _PROVIDER_ID,
        "profile_ids": [_PROFILE_ID],
        "enabled": True,
        "allowed_modes": ["Advisory"],
        "allowed_privacy_policies": ["minimal"],
        "egress_policy": "local_only",
        "wire_payload_policy": "restricted_store_only",
        "safe_payload_limits": _SAFE_LIMITS,
        "required_conformance_suite": "uei-v1-static-projection",
    })
    manifest_ref = _put(store, {
        "contract_version": "provider_manifest_v1",
        "manifest_id": "manifest/local.runtime/builtin-ocr/v1",
        "provider_id": _PROVIDER_ID,
        "provider_version": "built-in-v1",
        "profiles": [{
            "profile_id": _PROFILE_ID,
            "operation": "screen_parse",
            "input_contract": "screen_parse_request_v1",
            "output_contract": "provider_safe_result_v1",
            "declared_output_kinds": ["text"],
            "supported_coordinate_spaces": ["image_pixel_xyxy"],
            "supports_capture_artifact": True,
            "privacy_capabilities": ["minimal"],
            "mode_allowlist": ["Advisory"],
        }],
    })
    fixture = {
        "image_path": image.relative_to(root).as_posix(),
        "matches": ocr_result.get("matches", []),
        "metadata": ocr_result.get("metadata", {}),
    }
    result = project_ocr_result(
        store=store,
        request_ref=request_ref,
        registration_ref=registration_ref,
        manifest_ref=manifest_ref,
        provider_id=_PROVIDER_ID,
        profile_id=_PROFILE_ID,
        fixture=fixture,
        fixture_binding={"artifact_sha256": artifact_sha256, "image_size": image_size},
    )
    if result.get("contract_version") != "provider_safe_result_v1" or result.get("review_only") is not True:
        raise ValueError("built-in evidence did not remain review-only")
    return {"id": str(result["result_id"]), "content_sha256": str(result["content_sha256"])}


def _put(store: UEIObjectStore, value: dict[str, Any]) -> dict[str, str]:
    return store.put(seal_immutable(value))
