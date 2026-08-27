"""Pure, review-only coordinate projection primitives for UEI v1."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import math
import re
from typing import Any

from app.learn.recognition.uei.canonical import canonical_json_bytes, content_sha256, immutable_ref
from app.learn.recognition.uei.contracts import UEIProjectionFailure, UEIValidationError, validate_contract


_COORDINATE_SPACES = frozenset(
    {
        "screen_pixel_xyxy",
        "window_outer_pixel_xyxy",
        "window_client_pixel_xyxy",
        "capture_pixel_xyxy",
        "image_pixel_xyxy",
        "image_normalized_xyxy",
    }
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_AFFINE_PROOF_KEYS = frozenset(
    {
        "contract_version",
        "source_space",
        "target_space",
        "source_size",
        "target_size",
        "scale",
        "offset",
        "rounding",
        "clipping",
        "source_capture_artifact_sha256",
        "target_capture_artifact_sha256",
        "content_sha256",
    }
)
_HINT_CAPTURE_CLAIM_KEYS = frozenset(
    {
        "artifact_sha256",
        "image_size",
        "capture_bbox",
        "capture_lineage_ref",
        "coordinate_transform_ref",
        "request_artifact_sha256",
        "request_image_size",
    }
)


def _failure() -> UEIProjectionFailure:
    error = UEIProjectionFailure("coordinate_invalid")
    error.code = "coordinate_invalid"
    error.stage = "coordinate"
    return error


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _size(value: object) -> tuple[int, int] | None:
    if not isinstance(value, dict):
        return None
    width, height = value.get("width"), value.get("height")
    if not (
        isinstance(width, int)
        and not isinstance(width, bool)
        and isinstance(height, int)
        and not isinstance(height, bool)
        and 1 <= width <= 100000
        and 1 <= height <= 100000
    ):
        return None
    return width, height


def _sha(value: object) -> str | None:
    return value if isinstance(value, str) and _SHA256.fullmatch(value) else None


def _bbox(value: object, *, space: str, size: tuple[int, int] | None = None) -> list[float]:
    if space not in _COORDINATE_SPACES or not isinstance(value, list) or len(value) != 4:
        raise _failure()
    if not all(_is_number(edge) for edge in value):
        raise _failure()
    box = [float(edge) for edge in value]
    if not (box[0] < box[2] and box[1] < box[3]):
        raise _failure()
    if space == "image_normalized_xyxy":
        if not all(0 <= edge <= 1 for edge in box):
            raise _failure()
    elif any(edge < 0 or edge > 100000 or not edge.is_integer() for edge in box):
        raise _failure()
    if size is not None and (box[2] > size[0] or box[3] > size[1]):
        raise _failure()
    return box


def _binding_matches_request(
    binding: object, request_artifact_sha256: object, request_image_size: object
) -> tuple[str, tuple[int, int]] | None:
    request_sha = _sha(request_artifact_sha256)
    request_size = _size(request_image_size)
    if request_sha is None or request_size is None or not isinstance(binding, dict):
        return None
    if binding.get("artifact_sha256") != request_sha or _size(binding.get("image_size")) != request_size:
        return None
    return request_sha, request_size


def _round_edge(value: float, mode: str) -> int:
    if mode == "outward":
        raise AssertionError("outward rounding is edge-dependent")
    if mode == "nearest":
        return math.floor(value + 0.5) if value >= 0 else math.ceil(value - 0.5)
    if mode == "none" and value.is_integer():
        return int(value)
    raise _failure()


def _round_bbox(box: list[float], mode: str) -> list[int]:
    if mode == "outward":
        return [math.floor(box[0]), math.floor(box[1]), math.ceil(box[2]), math.ceil(box[3])]
    if mode not in {"nearest", "none"}:
        raise _failure()
    return [_round_edge(edge, mode) for edge in box]


def _immutable_reference(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"id", "content_sha256"}:
        raise _failure()
    identifier, digest = value.get("id"), _sha(value.get("content_sha256"))
    if not isinstance(identifier, str) or not identifier or len(identifier) > 512 or digest is None:
        raise _failure()
    return {"id": identifier, "content_sha256": digest}


def _bounded_opaque(value: object, *, depth: int = 1) -> None:
    if depth > 8:
        raise _failure()
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, str):
        if len(value) > 4096:
            raise _failure()
        return
    if _is_number(value):
        return
    if isinstance(value, list):
        if len(value) > 256:
            raise _failure()
        for child in value:
            _bounded_opaque(child, depth=depth + 1)
        return
    if isinstance(value, dict):
        if len(value) > 64 or not all(isinstance(key, str) for key in value):
            raise _failure()
        for child in value.values():
            _bounded_opaque(child, depth=depth + 1)
        return
    raise _failure()


def _harmless_transform_hint(value: object) -> None:
    if not isinstance(value, dict) or set(value) & _AFFINE_PROOF_KEYS or set(value) & _HINT_CAPTURE_CLAIM_KEYS:
        raise _failure()
    try:
        _bounded_opaque(value)
        if len(canonical_json_bytes(value)) > 65536:
            raise _failure()
    except UEIValidationError as error:
        raise _failure() from error


def _validate_safe_item(
    item: dict[str, object], capture_lineage_ref: dict[str, str], provider_id: str, profile_id: str
) -> None:
    candidate = {
        "contract_version": "provider_safe_result_v1",
        "result_id": "result/safe-item-validation",
        "request_ref": capture_lineage_ref,
        "requested_provider_id": provider_id,
        "requested_profile_id": profile_id,
        "registration_resolution": "not_reached",
        "manifest_resolution": "not_reached",
        "provider_id": provider_id,
        "profile_id": profile_id,
        "provider_version": "1",
        "capture_lineage_ref": capture_lineage_ref,
        "status": "success",
        "review_only": False,
        "items": [item],
        "redaction_summary": {
            "redacted_item_count": 0,
            "redacted_field_count": 0,
            "secret_detected": False,
            "sensitive_categories": [],
        },
        "content_sha256": "a" * 64,
    }
    try:
        validate_contract(candidate, contract_version="provider_safe_result_v1")
        canonical_json_bytes(candidate)
    except UEIValidationError as error:
        raise _failure() from error


def _transform_ref(transform: dict[str, object]) -> dict[str, str]:
    try:
        return immutable_ref(transform, id_field="content_sha256")
    except UEIValidationError as error:
        raise _failure() from error


def _validated_affine(
    transform: object,
    *,
    binding: object,
    source_coordinate_space: str,
    request_artifact_sha256: object,
    request_image_size: object,
) -> tuple[dict[str, object], tuple[int, int], tuple[int, int]] | None:
    if not isinstance(transform, dict):
        raise _failure()
    try:
        validate_contract(transform, contract_version="affine_coordinate_transform_v1")
        if transform.get("content_sha256") != content_sha256(transform):
            raise _failure()
    except UEIValidationError as error:
        raise _failure() from error
    request_sha = _sha(request_artifact_sha256)
    request_size = _size(request_image_size)
    source_size = _size(transform.get("source_size"))
    target_size = _size(transform.get("target_size"))
    if (
        _binding_matches_request(binding, request_artifact_sha256, request_image_size) is None
        or
        request_sha is None
        or request_size is None
        or source_size is None
        or target_size != request_size
        or transform.get("source_space") != source_coordinate_space
        or transform.get("target_space") != "capture_pixel_xyxy"
        or transform.get("source_capture_artifact_sha256") != request_sha
        or transform.get("target_capture_artifact_sha256") != request_sha
    ):
        raise _failure()
    scale, offset = transform.get("scale"), transform.get("offset")
    if not isinstance(scale, dict) or not isinstance(offset, dict):
        raise _failure()
    if not all(_is_number(point.get(axis)) for point in (scale, offset) for axis in ("x", "y")):
        raise _failure()
    if float(scale["x"]) == 0 or float(scale["y"]) == 0:
        raise _failure()
    if transform.get("rounding") not in {"outward", "nearest", "none"}:
        raise _failure()
    if transform.get("clipping") not in {"reject_if_outside", "clip_to_target"}:
        raise _failure()
    _transform_ref(transform)
    return transform, source_size, request_size


def project_capture_bbox(
    *,
    source_bbox: list[int | float],
    source_coordinate_space: str,
    binding: dict[str, object],
    request_artifact_sha256: str,
    request_image_size: dict[str, int],
    transform: dict[str, object] | None,
) -> tuple[list[int] | None, dict[str, str] | None, bool]:
    """Project one provider box into the exact request capture, or retain review-only evidence."""
    proven_binding = _binding_matches_request(binding, request_artifact_sha256, request_image_size)
    if transform is None:
        source = _bbox(
            source_bbox,
            space=source_coordinate_space,
            size=proven_binding[1] if source_coordinate_space == "capture_pixel_xyxy" and proven_binding else None,
        )
        if source_coordinate_space == "capture_pixel_xyxy" and proven_binding is not None:
            if not all(edge.is_integer() for edge in source):
                raise _failure()
            return [int(edge) for edge in source], None, False
        return None, None, True

    if not isinstance(transform, dict):
        raise _failure()
    if not (set(transform) & _AFFINE_PROOF_KEYS):
        _harmless_transform_hint(transform)
        _bbox(source_bbox, space=source_coordinate_space)
        return None, None, True

    affine = _validated_affine(
        transform,
        binding=binding,
        source_coordinate_space=source_coordinate_space,
        request_artifact_sha256=request_artifact_sha256,
        request_image_size=request_image_size,
    )
    if affine is None:
        _bbox(source_bbox, space=source_coordinate_space)
        return None, None, True
    affine_transform, source_size, target_size = affine
    source = _bbox(source_bbox, space=source_coordinate_space, size=source_size)
    scale = affine_transform["scale"]
    offset = affine_transform["offset"]
    assert isinstance(scale, dict) and isinstance(offset, dict)
    projected_x = [source[index] * float(scale["x"]) + float(offset["x"]) for index in (0, 2)]
    projected_y = [source[index] * float(scale["y"]) + float(offset["y"]) for index in (1, 3)]
    projected = [min(projected_x), min(projected_y), max(projected_x), max(projected_y)]
    clipping = affine_transform["clipping"]
    if clipping == "reject_if_outside" and (
        projected[0] < 0 or projected[1] < 0 or projected[2] > target_size[0] or projected[3] > target_size[1]
    ):
        raise _failure()
    if clipping == "clip_to_target":
        projected = [
            max(0.0, min(float(target_size[0]), projected[0])),
            max(0.0, min(float(target_size[1]), projected[1])),
            max(0.0, min(float(target_size[0]), projected[2])),
            max(0.0, min(float(target_size[1]), projected[3])),
        ]
    rounded = _round_bbox(projected, str(affine_transform["rounding"]))
    if clipping == "clip_to_target":
        rounded = [
            max(0, min(target_size[0], rounded[0])),
            max(0, min(target_size[1], rounded[1])),
            max(0, min(target_size[0], rounded[2])),
            max(0, min(target_size[1], rounded[3])),
        ]
    if not (0 <= rounded[0] < rounded[2] <= target_size[0] and 0 <= rounded[1] < rounded[3] <= target_size[1]):
        raise _failure()
    return rounded, _transform_ref(affine_transform), False


def make_source_item(
    *,
    provider_id: str,
    profile_id: str,
    capture_lineage_ref: dict[str, str],
    source_index: int,
    source_item_id: str | None,
    source_id_origin: str,
    kind: str,
    safe_text: str | None,
    safe_role: str | None,
    safe_states: list[str],
    source_bbox: list[int] | None,
    source_coordinate_space: str,
    capture_bbox: list[int] | None,
    coordinate_transform_ref: dict[str, str] | None,
    opaque_attributes: dict[str, object],
    provider_confidence: float | None,
) -> dict[str, object]:
    """Construct the closed, non-actionable UEI safe-item shape."""
    if (
        not isinstance(provider_id, str)
        or not provider_id
        or len(provider_id) > 512
        or not isinstance(profile_id, str)
        or not profile_id
        or len(profile_id) > 512
        or not isinstance(source_index, int)
        or isinstance(source_index, bool)
        or source_index < 0
    ):
        raise _failure()
    lineage_ref = _immutable_reference(capture_lineage_ref)
    if kind not in {"element", "text", "role", "state", "icon", "structure"}:
        raise _failure()
    if (
        not isinstance(safe_text, (str, type(None)))
        or not isinstance(safe_role, (str, type(None)))
        or isinstance(safe_text, str) and len(safe_text) > 4096
        or isinstance(safe_role, str) and len(safe_role) > 256
    ):
        raise _failure()
    if (
        not isinstance(safe_states, list)
        or len(safe_states) > 64
        or not all(isinstance(state, str) and state and len(state) <= 128 for state in safe_states)
        or len(set(safe_states)) != len(safe_states)
        or not isinstance(opaque_attributes, dict)
    ):
        raise _failure()
    _bounded_opaque(opaque_attributes)
    try:
        if len(canonical_json_bytes(opaque_attributes)) > 65536:
            raise _failure()
    except UEIValidationError as error:
        raise _failure() from error
    if source_coordinate_space not in _COORDINATE_SPACES:
        raise _failure()
    if source_bbox is not None:
        _bbox(source_bbox, space=source_coordinate_space)
        if source_coordinate_space != "image_normalized_xyxy" and not all(
            isinstance(edge, int) and not isinstance(edge, bool) for edge in source_bbox
        ):
            raise _failure()
    if capture_bbox is not None:
        _bbox(capture_bbox, space="capture_pixel_xyxy")
        if not all(isinstance(edge, int) and not isinstance(edge, bool) for edge in capture_bbox):
            raise _failure()
    transform_ref = None if coordinate_transform_ref is None else _immutable_reference(coordinate_transform_ref)
    if provider_confidence is not None and (not _is_number(provider_confidence) or not 0 <= provider_confidence <= 1):
        raise _failure()
    if source_item_id is not None and (not isinstance(source_item_id, str) or not source_item_id):
        raise _failure()
    if source_item_id is not None and len(source_item_id) > 512:
        raise _failure()
    if capture_bbox is not None and source_bbox is None:
        raise _failure()
    if capture_bbox is None and transform_ref is not None:
        raise _failure()
    if capture_bbox is not None and transform_ref is None and (
        source_coordinate_space != "capture_pixel_xyxy" or source_bbox != capture_bbox
    ):
        raise _failure()
    if source_item_id is None:
        identity = {
            "provider_id": provider_id,
            "profile_id": profile_id,
            "capture_lineage_ref": lineage_ref,
            "source_index": source_index,
            "kind": kind,
            "safe_text": safe_text,
            "safe_role": safe_role,
            "safe_states": safe_states,
            "source_bbox": source_bbox,
            "source_coordinate_space": source_coordinate_space,
        }
        try:
            source_item_id = "sha256:" + hashlib.sha256(canonical_json_bytes(identity)).hexdigest()
        except UEIValidationError as error:
            raise _failure() from error
        source_id_origin = "uei_deterministic_projection"
    else:
        source_id_origin = "provider"
    item = {
        "source_item_id": source_item_id,
        "source_id_origin": source_id_origin,
        "kind": kind,
        "safe_text": safe_text,
        "safe_role": safe_role,
        "safe_states": deepcopy(safe_states),
        "source_bbox": deepcopy(source_bbox),
        "capture_bbox": deepcopy(capture_bbox),
        "source_coordinate_space": source_coordinate_space,
        "coordinate_transform_ref": deepcopy(transform_ref),
        "opaque_attributes": deepcopy(opaque_attributes),
        "provider_confidence": provider_confidence,
    }
    _validate_safe_item(item, lineage_ref, provider_id, profile_id)
    return item


def _projection_failure(code: str = "provider_fixture_schema_invalid", *, stage: str = "projection") -> UEIProjectionFailure:
    """Return one schema-valid post-precondition projection failure."""
    error = UEIProjectionFailure(code)
    error.code = code
    error.stage = stage
    return error


def _xywh_bbox(value: object) -> list[int]:
    if not isinstance(value, dict) or set(value) != {"x", "y", "w", "h"}:
        raise _projection_failure()
    x, y, width, height = (value[field] for field in ("x", "y", "w", "h"))
    if not all(isinstance(edge, int) and not isinstance(edge, bool) for edge in (x, y, width, height)):
        raise _projection_failure()
    if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > 100000 or y + height > 100000:
        raise _projection_failure()
    return [x, y, x + width, y + height]


def _ocr_bbox(value: object) -> list[int]:
    if isinstance(value, dict):
        if set(value) != {"x", "y", "width", "height"}:
            raise _projection_failure()
        translated = {"x": value["x"], "y": value["y"], "w": value["width"], "h": value["height"]}
    else:
        translated = {
            "x": getattr(value, "x", None), "y": getattr(value, "y", None),
            "w": getattr(value, "width", None), "h": getattr(value, "height", None),
        }
    return _xywh_bbox(translated)


def _normalize_ocr_fixture(fixture: object) -> dict[str, object]:
    """Validate the closed OCR source shape and normalize the supported dataclass form."""
    if isinstance(fixture, dict):
        if set(fixture) != {"image_path", "matches", "metadata"}:
            raise _projection_failure()
        normalized = fixture
    else:
        image_path, matches, metadata = (
            getattr(fixture, "image_path", None), getattr(fixture, "matches", None), getattr(fixture, "metadata", None),
        )
        if not isinstance(image_path, str) or not isinstance(matches, list) or not isinstance(metadata, dict):
            raise _projection_failure()
        normalized_matches: list[dict[str, object]] = []
        for match in matches:
            if isinstance(match, dict):
                if set(match) != {"text", "score", "bbox"}:
                    raise _projection_failure()
                normalized_matches.append(dict(match))
                continue
            bbox = getattr(match, "bbox", None)
            if not isinstance(bbox, dict):
                bbox = {
                    "x": getattr(bbox, "x", None), "y": getattr(bbox, "y", None),
                    "width": getattr(bbox, "width", None), "height": getattr(bbox, "height", None),
                }
            normalized_matches.append({
                "text": getattr(match, "text", None), "score": getattr(match, "score", None), "bbox": bbox,
            })
        normalized = {"image_path": image_path, "matches": normalized_matches, "metadata": metadata}
    if not isinstance(normalized.get("image_path"), str) or not isinstance(normalized.get("metadata"), dict):
        raise _projection_failure()
    matches = normalized.get("matches")
    if not isinstance(matches, list):
        raise _projection_failure()
    for match in matches:
        if not isinstance(match, dict) or set(match) != {"text", "score", "bbox"}:
            raise _projection_failure()
        text, score, bbox = match["text"], match["score"], match["bbox"]
        if not isinstance(text, str) or not _is_number(score) or not 0 <= float(score) <= 1:
            raise _projection_failure()
        _ocr_bbox(bbox)
    return normalized


def _static_ocr_matches(fixture: object) -> list[tuple[str, float, list[int]]]:
    if not isinstance(fixture, dict):
        raise _projection_failure()
    matches = fixture.get("matches")
    if not isinstance(matches, list):
        raise _projection_failure()
    return [(str(match["text"]), float(match["score"]), _ocr_bbox(match["bbox"])) for match in matches if isinstance(match, dict)]


def _load_transform(store: object, transform_ref: object) -> dict[str, object] | None:
    if transform_ref is None:
        return None
    get = getattr(store, "get", None)
    if not callable(get):
        raise _failure()
    try:
        transform = get(transform_ref, contract_version="affine_coordinate_transform_v1")
    except (UEIValidationError, TypeError, ValueError) as error:
        raise _failure() from error
    if not isinstance(transform, dict):
        raise _failure()
    return transform


def _projection_context(
    *, store: object, request_ref: dict[str, str], registration_ref: dict[str, str] | None,
    manifest_ref: dict[str, str] | None, provider_id: str, profile_id: str,
) -> tuple[dict[str, object], dict[str, object]]:
    """Resolve the request and profile policy before inspecting fixture data."""
    from app.learn.recognition.uei.registry import resolve_projection_context, resolve_requested_profile

    context = resolve_projection_context(store=store, request_ref=request_ref)  # type: ignore[arg-type]
    selection = resolve_requested_profile(
        context=context, registration_ref=registration_ref, manifest_ref=manifest_ref,
        provider_id=provider_id, profile_id=profile_id,
    )
    return context, selection


_SENSITIVE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", re.IGNORECASE)),
    ("credential", re.compile(r"\bBearer\s+\S+|\bBasic\s+[A-Za-z0-9+/=]+", re.IGNORECASE)),
    ("credential", re.compile(r"\b(?:api[_-]?key|password|token|session|cookie)\s*=\s*\S+", re.IGNORECASE)),
    ("credential", re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}(?![A-Za-z0-9_-])")),
    ("personal_path", re.compile(r"\b[A-Za-z]:\\Users\\[^\\\s]+", re.IGNORECASE)),
    ("personal_data", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)),
    ("personal_data", re.compile(r"(?<!\w)\+?\d[\d .()\-]{6,}\d(?!\w)")),
)
_SAFE_ERROR_MESSAGES = {
    "payload_limit_exceeded": "Provider payload exceeds the safe limit.",
    "wire_payload_forbidden": "Provider wire payload is forbidden.",
    "coordinate_invalid": "Provider coordinates are invalid.",
    "fixture_invalid": "Provider fixture is invalid.",
    "provider_fixture_schema_invalid": "Provider fixture does not match the approved shape.",
    "projection_failed": "Provider projection could not be persisted safely.",
}


def _post_failure(*, stage: str, code: str) -> UEIProjectionFailure:
    error = UEIProjectionFailure(code)
    error.stage = stage
    error.code = code
    return error


def _redaction_summary(*, redacted_item_count: int = 0, redacted_field_count: int = 0,
                       categories: set[str] | None = None) -> dict[str, object]:
    category_ids = sorted(categories or set())
    return {
        "redacted_item_count": redacted_item_count,
        "redacted_field_count": redacted_field_count,
        "secret_detected": bool(redacted_field_count),
        "sensitive_categories": category_ids,
    }


def _sanitize_and_validate_payload(
    value: object, *, limits: object,
) -> tuple[object, dict[str, object]]:
    """Iteratively redact and bound a fixture before any adapter inspects it."""
    if not isinstance(limits, dict):
        raise _post_failure(stage="redaction", code="payload_limit_exceeded")
    required_limits = (
        "max_json_bytes", "max_depth", "max_array_items", "max_object_properties", "max_string_chars",
        "allowed_json_types",
    )
    if not all(isinstance(limits.get(name), int) and not isinstance(limits[name], bool) and limits[name] > 0 for name in required_limits[:-1]):
        raise _post_failure(stage="redaction", code="payload_limit_exceeded")
    allowed = limits.get("allowed_json_types")
    if not isinstance(allowed, list) or not all(isinstance(kind, str) for kind in allowed):
        raise _post_failure(stage="redaction", code="payload_limit_exceeded")
    allowed_types = frozenset(allowed)
    counts = {"fields": 0}
    categories: set[str] = set()
    redacted_items: set[tuple[object, ...]] = set()
    active_containers: set[int] = set()
    holder: dict[str, object] = {}
    work: list[tuple[str, object, int, tuple[object, ...] | None, object, object]] = [
        ("value", value, 1, None, holder, "root"),
    ]

    def summary_now() -> dict[str, object]:
        return _redaction_summary(
            redacted_item_count=len(redacted_items), redacted_field_count=counts["fields"], categories=categories,
        )

    def failure(code: str = "payload_limit_exceeded") -> UEIProjectionFailure:
        error = _post_failure(stage="redaction", code=code)
        error.redaction_summary = summary_now()
        return error

    def assign(destination: object, key: object, child: object) -> None:
        if isinstance(destination, dict) and isinstance(key, str):
            destination[key] = child
        elif isinstance(destination, list) and isinstance(key, int):
            destination[key] = child
        else:
            raise failure()

    while work:
        operation, candidate, depth, item_marker, destination, key = work.pop()
        if operation == "leave":
            active_containers.remove(id(candidate))
            continue
        if depth > limits["max_depth"]:
            raise failure()
        if candidate is None:
            kind = "null"
        elif isinstance(candidate, bool):
            kind = "boolean"
        elif isinstance(candidate, str):
            kind = "string"
        elif _is_number(candidate):
            kind = "number"
        elif isinstance(candidate, list):
            kind = "array"
        elif isinstance(candidate, dict):
            kind = "object"
        else:
            raise failure()
        if kind not in allowed_types:
            raise failure()
        if kind == "string":
            if len(candidate) > limits["max_string_chars"]:
                raise failure()
            category = next((name for name, pattern in _SENSITIVE_PATTERNS if pattern.search(candidate)), None)
            if category is not None:
                counts["fields"] += 1
                if item_marker is not None:
                    redacted_items.add(item_marker)
                categories.add(category)
                assign(destination, key, None)
            else:
                assign(destination, key, candidate)
            continue
        if kind in {"null", "boolean", "number"}:
            assign(destination, key, candidate)
            continue
        if id(candidate) in active_containers:
            raise failure()
        active_containers.add(id(candidate))
        work.append(("leave", candidate, depth, item_marker, destination, key))
        if kind == "array":
            if len(candidate) > limits["max_array_items"]:
                raise failure()
            copied_list: list[object] = [None] * len(candidate)
            assign(destination, key, copied_list)
            for index in range(len(candidate) - 1, -1, -1):
                work.append(("value", candidate[index], depth + 1, item_marker, copied_list, index))
            continue
        if len(candidate) > limits["max_object_properties"] or not all(isinstance(name, str) for name in candidate):
            raise failure()
        copied_object: dict[str, object] = {}
        assign(destination, key, copied_object)
        for name in reversed(tuple(candidate)):
            child = candidate[name]
            if name.casefold() in {"wire_payload", "raw_payload"}:
                raise failure("wire_payload_forbidden")
            if name in {"controls", "elements", "matches"} and isinstance(child, list):
                if "array" not in allowed_types or len(child) > limits["max_array_items"]:
                    raise failure()
                copied_items: list[object] = [None] * len(child)
                copied_object[name] = copied_items
                for index in range(len(child) - 1, -1, -1):
                    work.append(("value", child[index], depth + 2, (name, index), copied_items, index))
            else:
                work.append(("value", child, depth + 1, item_marker, copied_object, name))
    sanitized = holder["root"]
    summary = summary_now()
    try:
        if len(canonical_json_bytes(sanitized)) > limits["max_json_bytes"]:
            raise failure()
    except UEIProjectionFailure:
        raise
    except UEIValidationError as error:
        raise failure() from error
    return sanitized, summary


def _failure_context(context: dict[str, object], selection: dict[str, object]) -> dict[str, object]:
    """Bind only the resolved policy references needed by terminal failure records."""
    failure_context = dict(context)
    for name in ("registration_resolution", "manifest_resolution", "registration_ref", "manifest_ref", "manifest"):
        if name in selection:
            failure_context[f"_uei_{name}"] = deepcopy(selection[name])
    return failure_context


def store_post_precondition_failure(
    *, context: dict[str, object], stage: str, code: str, reason_class: str,
) -> dict[str, object]:
    """Persist a sealed error, then its sealed terminal review-only result."""
    from app.learn.recognition.uei.canonical import deterministic_error_id, deterministic_result_id, seal_immutable

    store = context.get("store")
    request_ref = context.get("request_ref")
    lineage_ref = context.get("capture_lineage_ref")
    provider_id = context.get("_uei_provider_id")
    profile_id = context.get("_uei_profile_id")
    fixture_kind = context.get("_uei_fixture_kind")
    manifest = context.get("_uei_manifest")
    if not (
        hasattr(store, "put") and hasattr(store, "get") and isinstance(request_ref, dict)
        and isinstance(lineage_ref, dict) and isinstance(provider_id, str) and isinstance(profile_id, str)
        and isinstance(fixture_kind, str)
    ):
        raise _post_failure(stage="store", code="projection_failed")
    registration_resolution = context.get("_uei_registration_resolution", "not_reached")
    manifest_resolution = context.get("_uei_manifest_resolution", "not_reached")
    redactions = context.get("_uei_redaction_summary")
    summary = redactions if isinstance(redactions, dict) else _redaction_summary()
    error: dict[str, object] = {
        "contract_version": "provider_error_v1",
        "error_id": deterministic_error_id(request_ref=request_ref, provider_id=provider_id, profile_id=profile_id, stage=stage, code=code),
        "request_ref": deepcopy(request_ref),
        "requested_provider_id": provider_id,
        "requested_profile_id": profile_id,
        "registration_resolution": registration_resolution,
        "manifest_resolution": manifest_resolution,
        "provider_id": provider_id,
        "profile_id": profile_id,
        "stage": stage,
        "code": code,
        "retryable": False,
        "message": _SAFE_ERROR_MESSAGES.get(code, "Provider projection failed safely."),
        "safe_details": {"reason_class": reason_class},
        "capture_lineage_ref": deepcopy(lineage_ref),
    }
    result: dict[str, object] = {
        "contract_version": "provider_safe_result_v1",
        "result_id": deterministic_result_id(request_ref=request_ref, provider_id=provider_id, profile_id=profile_id, fixture_kind=fixture_kind),
        "request_ref": deepcopy(request_ref),
        "requested_provider_id": provider_id,
        "requested_profile_id": profile_id,
        "registration_resolution": registration_resolution,
        "manifest_resolution": manifest_resolution,
        "provider_id": provider_id,
        "profile_id": profile_id,
        "provider_version": manifest.get("provider_version") if isinstance(manifest, dict) and isinstance(manifest.get("provider_version"), str) else "unresolved",
        "capture_lineage_ref": deepcopy(lineage_ref),
        "status": "failed",
        "review_only": True,
        "items": [],
        "redaction_summary": deepcopy(summary),
    }
    for resolution, reference in (("registration_resolution", "registration_ref"), ("manifest_resolution", "manifest_ref")):
        resolved_ref = context.get(f"_uei_{reference}")
        if error[resolution] == "resolved" and isinstance(resolved_ref, dict):
            error[reference] = deepcopy(resolved_ref)
            result[reference] = deepcopy(resolved_ref)
    error_ref = store.put(seal_immutable(error))  # type: ignore[attr-defined]
    result["error_ref"] = error_ref
    result_ref = store.put(seal_immutable(result))  # type: ignore[attr-defined]
    return store.get(result_ref, contract_version="provider_safe_result_v1")  # type: ignore[attr-defined]


def _failed_result(
    *, context: dict[str, object], error: UEIProjectionFailure, reason_class: str,
) -> dict[str, object]:
    return store_post_precondition_failure(
        context=context, stage=getattr(error, "stage", "projection"),
        code=getattr(error, "code", "projection_failed"), reason_class=reason_class,
    )


def _project_source_bbox(
    *, source_bbox: list[int], source_coordinate_space: str, fixture_binding: dict[str, object],
    context: dict[str, object], transform: dict[str, object] | None,
) -> tuple[list[int] | None, dict[str, str] | None, bool]:
    artifact_sha256 = context.get("artifact_sha256")
    image_size = context.get("image_size")
    if not isinstance(artifact_sha256, str) or not isinstance(image_size, dict):
        raise _projection_failure()
    return project_capture_bbox(
        source_bbox=source_bbox, source_coordinate_space=source_coordinate_space,
        binding=fixture_binding, request_artifact_sha256=artifact_sha256,
        request_image_size=image_size, transform=transform,
    )


def _assert_profile_permits(
    selection: dict[str, object], *, source_coordinate_space: str, kind: str,
) -> None:
    """Keep each projected source field within the selected manifest profile."""
    profile = selection.get("profile")
    if not isinstance(profile, dict):
        raise _projection_failure("projection_policy_unresolved")
    spaces, kinds = profile.get("supported_coordinate_spaces"), profile.get("declared_output_kinds")
    if not isinstance(spaces, list) or not isinstance(kinds, list):
        raise _projection_failure("projection_policy_unresolved")
    if source_coordinate_space not in spaces or kind not in kinds:
        raise _projection_failure("projection_policy_unresolved")


def _persist_success(
    *, store: object, context: dict[str, object], selection: dict[str, object], provider_id: str,
    profile_id: str, fixture_kind: str, items: list[dict[str, object]], review_only: bool,
    redacted_field_count: int,
) -> dict[str, object]:
    from app.learn.recognition.uei.canonical import deterministic_result_id, seal_immutable

    request_ref = context.get("request_ref")
    lineage_ref = context.get("capture_lineage_ref")
    manifest = selection.get("manifest")
    if not isinstance(request_ref, dict) or not isinstance(lineage_ref, dict) or not isinstance(manifest, dict):
        raise _projection_failure()
    provider_version = manifest.get("provider_version")
    if not isinstance(provider_version, str) or not provider_version:
        raise _projection_failure()
    result: dict[str, object] = {
        "contract_version": "provider_safe_result_v1",
        "result_id": deterministic_result_id(
            request_ref=request_ref, provider_id=provider_id, profile_id=profile_id, fixture_kind=fixture_kind,
        ),
        "request_ref": deepcopy(request_ref),
        "requested_provider_id": provider_id,
        "requested_profile_id": profile_id,
        "registration_resolution": "resolved",
        "manifest_resolution": "resolved",
        "registration_ref": deepcopy(selection["registration_ref"]),
        "manifest_ref": deepcopy(selection["manifest_ref"]),
        "provider_id": provider_id,
        "profile_id": profile_id,
        "provider_version": provider_version,
        "capture_lineage_ref": deepcopy(lineage_ref),
        "status": "success",
        "review_only": review_only,
        "items": deepcopy(items),
        "redaction_summary": {
            "redacted_item_count": 0,
            "redacted_field_count": redacted_field_count,
            "secret_detected": False,
            "sensitive_categories": [],
        },
    }
    try:
        sealed = seal_immutable(result)
        validate_contract(sealed, contract_version="provider_safe_result_v1")
    except UEIValidationError as error:
        raise _projection_failure() from error
    try:
        reference = store.put(sealed)  # type: ignore[attr-defined]
        return store.get(reference, contract_version="provider_safe_result_v1")  # type: ignore[attr-defined]
    except (UEIValidationError, TypeError, ValueError, AttributeError) as error:
        raise _post_failure(stage="store", code="projection_failed") from error


def project_ocr_result(
    *, store: object, request_ref: dict[str, str], registration_ref: dict[str, str] | None,
    manifest_ref: dict[str, str] | None, provider_id: str, profile_id: str,
    fixture: object, fixture_binding: dict[str, object], transform_ref: dict[str, str] | None = None,
) -> dict[str, object]:
    """Project caller-supplied OCRResult/static data without invoking OCR."""
    context, selection = _projection_context(
        store=store, request_ref=request_ref, registration_ref=registration_ref, manifest_ref=manifest_ref,
        provider_id=provider_id, profile_id=profile_id,
    )
    failure_context = _failure_context(context, selection)
    failure_context.update({"_uei_provider_id": provider_id, "_uei_profile_id": profile_id, "_uei_fixture_kind": "ocr"})
    try:
        if selection.get("resolved") is not True:
            policy_failure = selection.get("failure")
            if not isinstance(policy_failure, dict):
                raise _post_failure(stage="projection", code="projection_failed")
            raise _post_failure(
                stage=str(policy_failure.get("stage", "projection")),
                code=str(policy_failure.get("code", "projection_failed")),
            )
        fixture = _normalize_ocr_fixture(fixture)
        fixture, redaction_summary = _sanitize_and_validate_payload(
            fixture, limits=selection.get("safe_payload_limits"),
        )
        failure_context["_uei_redaction_summary"] = redaction_summary
        if redaction_summary["secret_detected"] is True:
            raise _post_failure(stage="redaction", code="fixture_invalid")
        transform = _load_transform(store, transform_ref)
        items: list[dict[str, object]] = []
        review_only = False
        for index, (text, score, source_bbox) in enumerate(_static_ocr_matches(fixture)):
            _assert_profile_permits(selection, source_coordinate_space="image_pixel_xyxy", kind="text")
            capture_bbox, coordinate_transform_ref, source_review_only = _project_source_bbox(
                source_bbox=source_bbox, source_coordinate_space="image_pixel_xyxy", fixture_binding=fixture_binding,
                context=context, transform=transform,
            )
            items.append(make_source_item(
                provider_id=provider_id, profile_id=profile_id,
                capture_lineage_ref=context["capture_lineage_ref"], source_index=index, source_item_id=None,
                source_id_origin="uei_deterministic_projection", kind="text", safe_text=text, safe_role=None,
                safe_states=[], source_bbox=source_bbox, source_coordinate_space="image_pixel_xyxy",
                capture_bbox=capture_bbox, coordinate_transform_ref=coordinate_transform_ref,
                opaque_attributes={}, provider_confidence=score,
            ))
            review_only = review_only or source_review_only
        return _persist_success(
            store=store, context=context, selection=selection, provider_id=provider_id, profile_id=profile_id,
            fixture_kind="ocr", items=items, review_only=review_only, redacted_field_count=0,
        )
    except UEIProjectionFailure as error:
        redactions = getattr(error, "redaction_summary", None)
        if isinstance(redactions, dict):
            failure_context["_uei_redaction_summary"] = redactions
        stage = getattr(error, "stage", "")
        reason_class = (
            "policy" if stage in {"registration", "manifest", "request"}
            else "privacy" if stage == "redaction" and failure_context.get("_uei_redaction_summary", {}).get("secret_detected")
            else "payload" if getattr(error, "code", "") in {"payload_limit_exceeded", "wire_payload_forbidden"}
            else "projection"
        )
        return _failed_result(context=failure_context, error=error, reason_class=reason_class)


def project_uia_snapshot(
    *, store: object, request_ref: dict[str, str], registration_ref: dict[str, str] | None,
    manifest_ref: dict[str, str] | None, provider_id: str, profile_id: str,
    fixture: dict[str, object], fixture_binding: dict[str, object], transform_ref: dict[str, str] | None = None,
) -> dict[str, object]:
    """Project a static UIA snapshot using only outer-window-relative controls."""
    context, selection = _projection_context(
        store=store, request_ref=request_ref, registration_ref=registration_ref, manifest_ref=manifest_ref,
        provider_id=provider_id, profile_id=profile_id,
    )
    failure_context = _failure_context(context, selection)
    failure_context.update({"_uei_provider_id": provider_id, "_uei_profile_id": profile_id, "_uei_fixture_kind": "uia"})
    try:
        if selection.get("resolved") is not True:
            policy_failure = selection.get("failure")
            if not isinstance(policy_failure, dict):
                raise _post_failure(stage="projection", code="projection_failed")
            raise _post_failure(
                stage=str(policy_failure.get("stage", "projection")),
                code=str(policy_failure.get("code", "projection_failed")),
            )
        fixture, redaction_summary = _sanitize_and_validate_payload(
            fixture, limits=selection.get("safe_payload_limits"),
        )
        failure_context["_uei_redaction_summary"] = redaction_summary
        if redaction_summary["secret_detected"] is True:
            raise _post_failure(stage="redaction", code="fixture_invalid")
        fixture = _validate_uia_fixture_source(fixture)
        if (
            not isinstance(fixture, dict) or set(fixture) != _UIA_RESULT_FIELDS
            or fixture.get("provider") != "windows_uia" or fixture.get("status") != "ok"
        ):
            raise _projection_failure()
        controls = fixture.get("controls")
        if not isinstance(controls, list):
            raise _projection_failure()
        transform = _load_transform(store, transform_ref)
        items: list[dict[str, object]] = []
        review_only = False
        redacted_field_count = 0
        seen_source_ids: set[str] = set()
        for index, control in enumerate(controls):
            if not isinstance(control, dict) or set(control) != _UIA_CONTROL_FIELDS:
                raise _projection_failure()
            source_id = control.get("control_id")
            if not isinstance(source_id, str) or not source_id or source_id in seen_source_ids:
                raise _projection_failure("fixture_invalid")
            seen_source_ids.add(source_id)
            source_bbox = _xywh_bbox(control.get("bbox"))
            name, control_type = control.get("name"), control.get("control_type")
            if not isinstance(name, (str, type(None))) or not isinstance(control_type, (str, type(None))):
                raise _projection_failure()
            enabled, visible, patterns = control.get("enabled"), control.get("visible"), control.get("patterns")
            automation_id, class_name = control.get("automation_id"), control.get("class_name")
            if not isinstance(enabled, (bool, type(None))) or not isinstance(visible, (bool, type(None))):
                raise _projection_failure()
            if not isinstance(automation_id, (str, type(None))) or not isinstance(class_name, (str, type(None))):
                raise _projection_failure()
            if not isinstance(patterns, list) or not all(isinstance(pattern, str) for pattern in patterns):
                raise _projection_failure()
            if "screen_bbox" in control:
                redacted_field_count += 1
            _assert_profile_permits(selection, source_coordinate_space="window_outer_pixel_xyxy", kind="element")
            capture_bbox, coordinate_transform_ref, source_review_only = _project_source_bbox(
                source_bbox=source_bbox, source_coordinate_space="window_outer_pixel_xyxy", fixture_binding=fixture_binding,
                context=context, transform=transform,
            )
            states = (["enabled"] if enabled is True else ["disabled"] if enabled is False else [])
            states += ["visible"] if visible is True else ["hidden"] if visible is False else []
            items.append(make_source_item(
                provider_id=provider_id, profile_id=profile_id, capture_lineage_ref=context["capture_lineage_ref"],
                source_index=index, source_item_id=source_id, source_id_origin="provider", kind="element",
                safe_text=name, safe_role=control_type, safe_states=states, source_bbox=source_bbox,
                source_coordinate_space="window_outer_pixel_xyxy", capture_bbox=capture_bbox,
                coordinate_transform_ref=coordinate_transform_ref,
                opaque_attributes={"automation_id": automation_id, "class_name": class_name, "patterns": patterns},
                provider_confidence=None,
            ))
            review_only = review_only or source_review_only
        return _persist_success(
            store=store, context=context, selection=selection, provider_id=provider_id, profile_id=profile_id,
            fixture_kind="uia", items=items, review_only=review_only, redacted_field_count=redacted_field_count,
        )
    except UEIProjectionFailure as error:
        redactions = getattr(error, "redaction_summary", None)
        if isinstance(redactions, dict):
            failure_context["_uei_redaction_summary"] = redactions
        stage = getattr(error, "stage", "")
        reason_class = (
            "policy" if stage in {"registration", "manifest", "request"}
            else "privacy" if stage == "redaction" and failure_context.get("_uei_redaction_summary", {}).get("secret_detected")
            else "payload" if getattr(error, "code", "") in {"payload_limit_exceeded", "wire_payload_forbidden"}
            else "projection"
        )
        return _failed_result(context=failure_context, error=error, reason_class=reason_class)


_OMNI_RESULT_FIELDS = frozenset({
    "contract_version", "provider", "status", "profile_id", "model_revision", "capture_id", "source_run_id",
    "screenshot_sha256", "image_size", "coordinate_space", "timing", "resource_usage", "provenance", "elements",
    "artifact_is_authorization", "execute_binding_enabled", "review_only", "grounding_eligible",
})
_OMNI_ELEMENT_FIELDS = frozenset({"element_id", "type", "content", "bbox", "interactivity", "source"})
_UIA_RESULT_FIELDS = frozenset({"provider", "provider_version", "status", "window", "control_count", "controls"})
_UIA_CONTROL_FIELDS = frozenset({
    "provider", "control_id", "name", "control_type", "automation_id", "class_name", "bbox", "screen_bbox",
    "enabled", "visible", "patterns",
})
_UIA_WINDOW_FIELDS = frozenset({"handle", "title", "process_id", "process_name", "bbox"})


def _uia_screen_bbox(value: object) -> None:
    if not isinstance(value, dict) or set(value) != {"x", "y", "w", "h"}:
        raise _projection_failure()
    x, y, width, height = (value[field] for field in ("x", "y", "w", "h"))
    if not all(isinstance(edge, int) and not isinstance(edge, bool) for edge in (x, y, width, height)):
        raise _projection_failure()
    if not (-100000 <= x <= 100000 and -100000 <= y <= 100000 and 1 <= width <= 100000 and 1 <= height <= 100000):
        raise _projection_failure()


def _validate_uia_fixture_source(fixture: object) -> dict[str, object]:
    """Validate the exact static UIA source contract before safe-field projection."""
    if not isinstance(fixture, dict) or set(fixture) != _UIA_RESULT_FIELDS:
        raise _projection_failure()
    if fixture.get("provider") != "windows_uia" or fixture.get("status") != "ok":
        raise _projection_failure()
    if not isinstance(fixture.get("provider_version"), str) or not fixture["provider_version"]:
        raise _projection_failure()
    window = fixture.get("window")
    if not isinstance(window, dict) or set(window) != _UIA_WINDOW_FIELDS:
        raise _projection_failure()
    if (not isinstance(window.get("handle"), int) or isinstance(window.get("handle"), bool)
            or not isinstance(window.get("process_id"), int) or isinstance(window.get("process_id"), bool)
            or window["handle"] < 1 or window["process_id"] < 1
            or not isinstance(window.get("title"), str) or not window["title"]
            or not isinstance(window.get("process_name"), str) or not window["process_name"]):
        raise _projection_failure()
    _uia_screen_bbox(window.get("bbox"))
    controls = fixture.get("controls")
    if not isinstance(controls, list) or not isinstance(fixture.get("control_count"), int) or isinstance(fixture.get("control_count"), bool) or fixture["control_count"] != len(controls):
        raise _projection_failure()
    seen_source_ids: set[str] = set()
    for control in controls:
        if not isinstance(control, dict) or set(control) != _UIA_CONTROL_FIELDS:
            raise _projection_failure()
        if control.get("provider") != "windows_uia":
            raise _projection_failure()
        source_id = control.get("control_id")
        if not isinstance(source_id, str) or not source_id or source_id in seen_source_ids:
            raise _projection_failure()
        seen_source_ids.add(source_id)
        for field in ("name", "control_type", "class_name"):
            if not isinstance(control.get(field), str) or not control[field]:
                raise _projection_failure()
        automation_id = control.get("automation_id")
        if automation_id is not None and (
            not isinstance(automation_id, str) or not automation_id
        ):
            raise _projection_failure()
        if not isinstance(control.get("enabled"), bool) or not isinstance(control.get("visible"), bool):
            raise _projection_failure()
        patterns = control.get("patterns")
        if not isinstance(patterns, list) or not all(isinstance(pattern, str) and pattern for pattern in patterns):
            raise _projection_failure()
        _xywh_bbox(control.get("bbox"))
        _uia_screen_bbox(control.get("screen_bbox"))
    return fixture


def _validate_screen_parser_fixture(
    fixture: object, *, provider_id: str, profile_id: str, fixture_binding: dict[str, object],
    context: dict[str, object],
) -> tuple[list[object], str, tuple[int, int]]:
    """Validate the closed current parser result before selecting safe fields."""
    if not isinstance(fixture, dict) or set(fixture) != _OMNI_RESULT_FIELDS:
        raise _projection_failure()
    if (
        fixture.get("contract_version") != "screen_parser_result_v1" or fixture.get("provider") != "omniparser"
        or fixture.get("profile_id") != profile_id or fixture.get("status") != "success"
        or fixture.get("artifact_is_authorization") is not False
        or fixture.get("execute_binding_enabled") is not False
        or fixture.get("review_only") is not True
        or fixture.get("grounding_eligible") is not False
    ):
        raise _projection_failure()
    if not all(isinstance(fixture.get(field), str) and fixture[field] for field in (
        "profile_id", "model_revision", "capture_id", "source_run_id",
    )):
        raise _projection_failure()
    artifact_sha256, image_size = context.get("artifact_sha256"), context.get("image_size")
    fixture_size = _size(fixture.get("image_size"))
    lineage = context.get("capture_lineage")
    if (
        _sha(fixture.get("screenshot_sha256")) is None
        or fixture.get("screenshot_sha256") != artifact_sha256
        or fixture_size is None
        or fixture.get("image_size") != image_size
        or _binding_matches_request(fixture_binding, artifact_sha256, image_size) is None
        or not isinstance(lineage, dict)
        or fixture.get("capture_id") != lineage.get("capture_id")
    ):
        raise _projection_failure()
    coordinate_space = fixture.get("coordinate_space")
    if coordinate_space not in {"image_pixel_xyxy", "image_normalized_xyxy"}:
        raise _projection_failure()
    if not all(isinstance(fixture.get(field), dict) for field in ("timing", "resource_usage", "provenance")):
        raise _projection_failure()
    elements = fixture.get("elements")
    if not isinstance(elements, list):
        raise _projection_failure()
    return elements, coordinate_space, fixture_size


def project_screen_parser_result(
    *, store: object, request_ref: dict[str, str], registration_ref: dict[str, str] | None,
    manifest_ref: dict[str, str] | None, provider_id: str, profile_id: str,
    fixture: dict[str, object], fixture_binding: dict[str, object], transform_ref: dict[str, str] | None = None,
) -> dict[str, object]:
    """Project successful static screen_parser_result_v1 elements without raw provenance."""
    context, selection = _projection_context(
        store=store, request_ref=request_ref, registration_ref=registration_ref, manifest_ref=manifest_ref,
        provider_id=provider_id, profile_id=profile_id,
    )
    failure_context = _failure_context(context, selection)
    failure_context.update({"_uei_provider_id": provider_id, "_uei_profile_id": profile_id, "_uei_fixture_kind": "screen-parser"})
    try:
        if selection.get("resolved") is not True:
            policy_failure = selection.get("failure")
            if not isinstance(policy_failure, dict):
                raise _post_failure(stage="projection", code="projection_failed")
            raise _post_failure(
                stage=str(policy_failure.get("stage", "projection")),
                code=str(policy_failure.get("code", "projection_failed")),
            )
        fixture, redaction_summary = _sanitize_and_validate_payload(
            fixture, limits=selection.get("safe_payload_limits"),
        )
        failure_context["_uei_redaction_summary"] = redaction_summary
        if redaction_summary["secret_detected"] is True:
            raise _post_failure(stage="redaction", code="fixture_invalid")
        elements, coordinate_space, fixture_size = _validate_screen_parser_fixture(
            fixture, provider_id=provider_id, profile_id=profile_id, fixture_binding=fixture_binding, context=context,
        )
        transform = _load_transform(store, transform_ref)
        items: list[dict[str, object]] = []
        review_only = False
        seen_source_ids: set[str] = set()
        for index, element in enumerate(elements):
            if not isinstance(element, dict) or set(element) != _OMNI_ELEMENT_FIELDS:
                raise _projection_failure()
            source_id, element_type, content = element.get("element_id"), element.get("type"), element.get("content")
            interactivity, source = element.get("interactivity"), element.get("source")
            if not all(isinstance(value, str) and value for value in (source_id, element_type, content, source)):
                raise _projection_failure()
            if source_id in seen_source_ids:
                raise _projection_failure("fixture_invalid")
            seen_source_ids.add(source_id)
            if not isinstance(interactivity, bool):
                raise _projection_failure()
            raw_bbox = element.get("bbox")
            if not isinstance(raw_bbox, list):
                raise _projection_failure()
            try:
                source_bbox = _bbox(raw_bbox, space=coordinate_space, size=fixture_size)
            except UEIProjectionFailure as error:
                raise _projection_failure() from error
            if coordinate_space != "image_normalized_xyxy":
                source_bbox = [int(edge) for edge in source_bbox]
            capture_bbox, coordinate_transform_ref, source_review_only = _project_source_bbox(
                source_bbox=source_bbox, source_coordinate_space=coordinate_space, fixture_binding=fixture_binding,
                context=context, transform=transform,
            )
            kind = element_type if element_type in {"text", "icon", "structure", "role", "state", "element"} else "element"
            _assert_profile_permits(selection, source_coordinate_space=coordinate_space, kind=kind)
            items.append(make_source_item(
                provider_id=provider_id, profile_id=profile_id, capture_lineage_ref=context["capture_lineage_ref"],
                source_index=index, source_item_id=source_id, source_id_origin="provider", kind=kind,
                safe_text=content, safe_role=element_type, safe_states=["interactable"] if interactivity else [],
                source_bbox=source_bbox, source_coordinate_space=coordinate_space, capture_bbox=capture_bbox,
                coordinate_transform_ref=coordinate_transform_ref, opaque_attributes={"source": source},
                provider_confidence=None,
            ))
            review_only = review_only or source_review_only
        return _persist_success(
            store=store, context=context, selection=selection, provider_id=provider_id, profile_id=profile_id,
            fixture_kind="screen-parser", items=items, review_only=review_only, redacted_field_count=0,
        )
    except UEIProjectionFailure as error:
        redactions = getattr(error, "redaction_summary", None)
        if isinstance(redactions, dict):
            failure_context["_uei_redaction_summary"] = redactions
        stage = getattr(error, "stage", "")
        reason_class = (
            "policy" if stage in {"registration", "manifest", "request"}
            else "privacy" if stage == "redaction" and failure_context.get("_uei_redaction_summary", {}).get("secret_detected")
            else "payload" if getattr(error, "code", "") in {"payload_limit_exceeded", "wire_payload_forbidden"}
            else "projection"
        )
        return _failed_result(context=failure_context, error=error, reason_class=reason_class)
