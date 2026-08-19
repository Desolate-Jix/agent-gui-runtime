from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any

CONTRACT_VERSION = "screen_parser_result_v1"
PROVIDER_NAME = "omniparser"
COORDINATE_SPACES = {"image_normalized_xyxy", "image_pixel_xyxy"}
ERROR_CODES = {
    "dependency_missing",
    "provider_unavailable",
    "weights_missing",
    "runtime_preflight",
    "cuda_oom",
    "protocol_invalid",
    "invalid_bbox",
    "screenshot_sha_mismatch",
    "inference_failed",
}


@dataclass(frozen=True)
class OmniparserProviderError(ValueError):
    code: str
    details: str

    def __str__(self) -> str:
        return f"{self.code}: {self.details}"


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_omniparser_result(
    *,
    parsed_content_list: list[dict[str, Any]],
    profile_id: str,
    model_revision: str,
    capture_id: str,
    source_run_id: str,
    screenshot_sha256: str,
    image_size: dict[str, Any],
    coordinate_space: str,
    timing: dict[str, Any],
    resource_usage: dict[str, Any],
    provenance: dict[str, Any],
) -> dict[str, Any]:
    context = _validated_context(
        profile_id=profile_id,
        model_revision=model_revision,
        capture_id=capture_id,
        source_run_id=source_run_id,
        screenshot_sha256=screenshot_sha256,
        image_size=image_size,
        coordinate_space=coordinate_space,
        timing=timing,
        resource_usage=resource_usage,
        provenance=provenance,
    )
    if not isinstance(parsed_content_list, list):
        raise OmniparserProviderError("protocol_invalid", "parsed_content_list must be a list")
    elements = [
        _normalize_element(item=item, index=index, image_size=context["image_size"], coordinate_space=coordinate_space)
        for index, item in enumerate(parsed_content_list, start=1)
    ]
    return {
        **context,
        "contract_version": CONTRACT_VERSION,
        "provider": PROVIDER_NAME,
        "status": "success",
        "elements": elements,
        **_non_authorizing_fields(),
    }


def build_failed_screen_parser_result(
    *,
    error_code: str,
    error_details: str,
    stage: str,
    profile_id: str,
    model_revision: str,
    capture_id: str,
    source_run_id: str,
    screenshot_sha256: str,
    image_size: dict[str, Any],
    coordinate_space: str,
    timing: dict[str, Any],
    resource_usage: dict[str, Any],
    provenance: dict[str, Any],
) -> dict[str, Any]:
    if error_code not in ERROR_CODES:
        raise OmniparserProviderError("protocol_invalid", f"unsupported error code: {error_code}")
    context = _validated_context(
        profile_id=profile_id,
        model_revision=model_revision,
        capture_id=capture_id,
        source_run_id=source_run_id,
        screenshot_sha256=screenshot_sha256,
        image_size=image_size,
        coordinate_space=coordinate_space,
        timing=timing,
        resource_usage=resource_usage,
        provenance=provenance,
    )
    if not str(error_details).strip() or not str(stage).strip():
        raise OmniparserProviderError("protocol_invalid", "failed results require non-empty details and stage")
    return {
        **context,
        "contract_version": CONTRACT_VERSION,
        "provider": PROVIDER_NAME,
        "status": "failed",
        "error": {"code": error_code, "details": str(error_details), "stage": str(stage)},
        **_non_authorizing_fields(),
    }


def _validated_context(
    *,
    profile_id: str,
    model_revision: str,
    capture_id: str,
    source_run_id: str,
    screenshot_sha256: str,
    image_size: dict[str, Any],
    coordinate_space: str,
    timing: dict[str, Any],
    resource_usage: dict[str, Any],
    provenance: dict[str, Any],
) -> dict[str, Any]:
    for field, value in {
        "profile_id": profile_id,
        "model_revision": model_revision,
        "capture_id": capture_id,
        "source_run_id": source_run_id,
    }.items():
        if not isinstance(value, str) or not value.strip():
            raise OmniparserProviderError("protocol_invalid", f"{field} must be a non-empty string")
    if not isinstance(screenshot_sha256, str) or len(screenshot_sha256) != 64 or any(char not in "0123456789abcdef" for char in screenshot_sha256.lower()):
        raise OmniparserProviderError("screenshot_sha_mismatch", "screenshot_sha256 must be a SHA-256 hex digest")
    if coordinate_space not in COORDINATE_SPACES:
        raise OmniparserProviderError("protocol_invalid", f"unsupported coordinate_space: {coordinate_space}")
    if not isinstance(image_size, dict):
        raise OmniparserProviderError("protocol_invalid", "image_size must be an object")
    width, height = image_size.get("width"), image_size.get("height")
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        raise OmniparserProviderError("protocol_invalid", "image_size requires positive integer width and height")
    if not all(isinstance(value, dict) for value in (timing, resource_usage, provenance)):
        raise OmniparserProviderError("protocol_invalid", "timing, resource_usage, and provenance must be objects")
    return {
        "profile_id": profile_id,
        "model_revision": model_revision,
        "capture_id": capture_id,
        "source_run_id": source_run_id,
        "screenshot_sha256": screenshot_sha256.lower(),
        "image_size": {"width": width, "height": height},
        "coordinate_space": coordinate_space,
        "timing": timing,
        "resource_usage": resource_usage,
        "provenance": provenance,
    }


def _normalize_element(*, item: dict[str, Any], index: int, image_size: dict[str, int], coordinate_space: str) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise OmniparserProviderError("protocol_invalid", f"element {index} must be an object")
    element_type = _required_text(item, "type", index)
    content = _required_text(item, "content", index)
    bbox = _validate_bbox(item.get("bbox"), image_size=image_size, coordinate_space=coordinate_space, index=index)
    source = str(item.get("source") or "official_omniparser")
    fingerprint = json.dumps(
        {"type": element_type, "content": content, "bbox": bbox, "source": source},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "element_id": f"omniparser_{index:04d}_{sha256(fingerprint.encode('utf-8')).hexdigest()[:10]}",
        "type": element_type,
        "content": content,
        "bbox": bbox,
        "interactivity": bool(item.get("interactivity")),
        "source": source,
    }


def _required_text(item: dict[str, Any], field: str, index: int) -> str:
    value = str(item.get(field) or "").strip()
    if not value:
        raise OmniparserProviderError("protocol_invalid", f"element {index} requires non-empty {field}")
    return value


def _validate_bbox(value: Any, *, image_size: dict[str, int], coordinate_space: str, index: int) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise OmniparserProviderError("invalid_bbox", f"element {index} bbox must be a four-item xyxy sequence")
    try:
        bbox = [float(number) for number in value]
    except (TypeError, ValueError) as exc:
        raise OmniparserProviderError("invalid_bbox", f"element {index} bbox must contain numbers") from exc
    if not all(math.isfinite(number) for number in bbox):
        raise OmniparserProviderError("invalid_bbox", f"element {index} bbox must contain finite numbers")
    x1, y1, x2, y2 = bbox
    max_x = 1.0 if coordinate_space == "image_normalized_xyxy" else float(image_size["width"])
    max_y = 1.0 if coordinate_space == "image_normalized_xyxy" else float(image_size["height"])
    if not (0.0 <= x1 < x2 <= max_x and 0.0 <= y1 < y2 <= max_y):
        raise OmniparserProviderError("invalid_bbox", f"element {index} bbox is outside {coordinate_space}")
    return bbox


def _non_authorizing_fields() -> dict[str, bool]:
    return {
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "review_only": True,
        "grounding_eligible": False,
    }
