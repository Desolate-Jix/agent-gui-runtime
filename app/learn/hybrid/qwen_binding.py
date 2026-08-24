"""将 Qwen 语义严格绑定到同一截图的不可变 Omni candidate ID。"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
from typing import Any, Callable
import unicodedata

from PIL import Image, UnidentifiedImageError

from app.learn.hybrid.capture import load_and_verify_hybrid_capture_bundle
from app.learn.hybrid.contracts import (
    validate_capture_identity,
    validate_omni_inventory,
    validate_qwen_bindings,
)
from app.learn.recognition.uei.canonical import content_sha256, seal_immutable


_NON_AUTHORIZING = {
    "artifact_is_authorization": False,
    "execute_binding_enabled": False,
    "final_submit_forbidden": True,
    "real_action_requires_gate": True,
    "authorization_scope": "display_and_review_only",
}
_PAYLOAD_FIELDS = {
    "project_root",
    "run_id",
    "workflow_revision",
    "hybrid_capture_bundle_ref",
    "capture_image_path",
    "omni_inventory",
}
_BINDING_FIELDS = {
    "candidate_id",
    "role",
    "label",
    "description",
    "semantic_confidence",
    "task_relevance",
    "relation",
    "ambiguity",
}
_ORPHAN_FIELDS = {"semantic_id", "role", "label", "description", "reason"}
_FORBIDDEN_FIELDS = {
    "action_authorized",
    "approved_to_click",
    "approved_to_execute",
    "bbox",
    "bbox_original",
    "candidate_bbox",
    "candidate_bbox_ref",
    "click_authorized",
    "coordinate_space",
    "execute",
    "final_submit",
    "geometry",
    "new_candidate",
    "point",
    "refined_point",
    "roi",
    "roi_ref",
    "submit_authorized",
    "xy",
    "xyxy",
}
_MAX_JSON_DEPTH = 16
_MAX_MODEL_STRING_BYTES = 4096
_MAX_ORPHAN_SEMANTICS = 64
_MAX_MODEL_JSON_BYTES = 1024 * 1024


class QwenBindingCancelled(ValueError):
    """受管 Qwen 绑定在产生新 artifact 前被取消。"""


class QwenBindingTimeout(ValueError):
    """受管 Qwen 模型调用超时。"""


def validate_sealed_omni_inventory(value: object) -> dict[str, Any]:
    """在模型获取前验证 Task 3 inventory 的精确不可变密封。"""
    return _validated_inventory(value)


def build_qwen_binding_request(
    capture_bundle: Mapping[str, Any],
    omni_inventory: Mapping[str, Any],
) -> dict[str, Any]:
    """构造只含权威截图、Omni 几何和同源 OCR/UIA 的封闭请求。"""
    if not isinstance(capture_bundle, Mapping):
        raise ValueError("capture_bundle must be an object")
    bundle = deepcopy(dict(capture_bundle))
    inventory = _validated_inventory(omni_inventory)
    capture_identity = validate_capture_identity(bundle.get("capture_identity"))
    if capture_identity != inventory["capture_identity"]:
        raise ValueError("Qwen request capture identity mismatch")
    context = _sealed_context(bundle.get("context"), capture_identity)
    request = {
        "contract_version": "hybrid_qwen_binding_request_v1",
        "capture_identity": capture_identity,
        "screenshot": {
            "artifact_ref": deepcopy(capture_identity["artifact_ref"]),
            "screenshot_sha256": capture_identity["screenshot_sha256"],
            "image_size": deepcopy(capture_identity["image_size"]),
            "coordinate_space": "capture_pixel_xyxy",
        },
        "candidates": [
            {
                "candidate_id": candidate["candidate_id"],
                "bbox_original": deepcopy(candidate["bbox_original"]),
                "coordinate_space": candidate["coordinate_space"],
                "active": candidate["active"],
                "inactive_reason": candidate["inactive_reason"],
            }
            for candidate in inventory["candidates"]
        ],
        "ocr_uia_context": context,
        "allowed_output_fields": sorted(_BINDING_FIELDS | _ORPHAN_FIELDS),
    }
    return seal_immutable(request)


def parse_qwen_candidate_bindings(
    raw: Mapping[str, Any],
    omni_inventory: Mapping[str, Any],
) -> dict[str, Any]:
    """解析 candidate-ID-closed 模型输出，不接受任何自由几何或执行权限。"""
    inventory = _validated_inventory(omni_inventory)
    if not isinstance(raw, Mapping) or set(raw) != {"bindings", "orphan_semantics"}:
        raise ValueError("unbound Qwen prose or non-closed output")
    value = deepcopy(dict(raw))
    _validate_model_json_bounds(value)
    forbidden = _first_forbidden_field(value)
    if forbidden is not None:
        raise ValueError(f"forbidden Qwen field: {forbidden}")
    if not isinstance(value["bindings"], list):
        raise ValueError("Qwen bindings must be a list")
    if not isinstance(value["orphan_semantics"], list):
        raise ValueError("Qwen orphan_semantics must be a list")
    if len(value["bindings"]) != len(inventory["candidates"]):
        raise ValueError("candidate omission in Qwen bindings")
    if len(value["orphan_semantics"]) > _MAX_ORPHAN_SEMANTICS:
        raise ValueError("Qwen orphan count exceeds limit")
    for index, binding in enumerate(value["bindings"]):
        if not isinstance(binding, Mapping) or set(binding) != _BINDING_FIELDS:
            raise ValueError(f"binding[{index}] is not closed")
    for index, orphan in enumerate(value["orphan_semantics"]):
        if not isinstance(orphan, Mapping) or set(orphan) != _ORPHAN_FIELDS:
            raise ValueError(f"orphan_semantic[{index}] is not closed")
        semantic_id = orphan.get("semantic_id")
        if not isinstance(semantic_id, str) or not semantic_id.startswith("semantic/"):
            raise ValueError("orphan semantic cannot use a fabricated candidate identity")
        if orphan.get("reason") != "ORPHAN_SEMANTIC":
            raise ValueError("orphan semantic reason must be ORPHAN_SEMANTIC")

    artifact = {
        "contract_version": "hybrid_qwen_bindings_v1",
        "capture_identity": deepcopy(inventory["capture_identity"]),
        "bindings": value["bindings"],
        "orphan_semantics": value["orphan_semantics"],
        **_NON_AUTHORIZING,
    }
    validated = validate_qwen_bindings(artifact, inventory)
    expected_ids = [candidate["candidate_id"] for candidate in inventory["candidates"]]
    actual_ids = [binding["candidate_id"] for binding in validated["bindings"]]
    if set(actual_ids) != set(expected_ids) or len(actual_ids) != len(expected_ids):
        raise ValueError("candidate omission in Qwen bindings")
    semantic_targets: dict[tuple[str, str, str], str] = {}
    for binding in validated["bindings"]:
        target = _semantic_target_key(binding)
        previous = semantic_targets.get(target)
        if previous is not None and previous != binding["candidate_id"]:
            raise ValueError("semantic target bound to multiple candidate IDs")
        semantic_targets[target] = binding["candidate_id"]
    orphan_targets: set[tuple[str, str, str]] = set()
    for orphan in validated["orphan_semantics"]:
        target = _semantic_target_key(orphan)
        if target in semantic_targets:
            raise ValueError("semantic target bound and orphaned")
        if target in orphan_targets:
            raise ValueError("duplicate orphan semantic target")
        orphan_targets.add(target)
    return validated


def run_qwen_candidate_binding(
    payload: dict[str, Any],
    *,
    model_runner: Callable[..., object],
    cancellation_event: Any | None = None,
    model_lease: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """重新验证 Task 2/3 artifact，调用 Qwen，并在返回前密封绑定。"""
    request_payload = _validated_payload(payload)
    if cancellation_event is not None and cancellation_event.is_set():
        raise QwenBindingCancelled("Qwen candidate binding cancelled")
    root = Path(request_payload["project_root"]).resolve()
    bundle = load_and_verify_hybrid_capture_bundle(
        project_root=root,
        bundle_ref=deepcopy(request_payload["hybrid_capture_bundle_ref"]),
        expected_run_id=request_payload["run_id"],
        expected_workflow_revision=request_payload["workflow_revision"],
    )
    image_path = _capture_path(root, request_payload["capture_image_path"])
    sealed_inventory = deepcopy(request_payload["omni_inventory"])
    inventory = _validated_inventory(sealed_inventory)
    model_request = build_qwen_binding_request(bundle, sealed_inventory)
    screenshot_bytes, screenshot_media_type, screenshot_sha256 = _read_verified_capture(
        image_path,
        inventory["capture_identity"],
    )
    try:
        raw = model_runner(
            request=deepcopy(model_request),
            screenshot_bytes=screenshot_bytes,
            screenshot_media_type=screenshot_media_type,
            screenshot_sha256=screenshot_sha256,
            cancellation_event=cancellation_event,
            model_lease=deepcopy(model_lease),
        )
    except TimeoutError as error:
        raise QwenBindingTimeout("Qwen model timeout") from error
    if cancellation_event is not None and cancellation_event.is_set():
        raise QwenBindingCancelled("Qwen candidate binding cancelled")
    if isinstance(raw, str):
        if len(raw.encode("utf-8")) > _MAX_MODEL_JSON_BYTES:
            raise ValueError("Qwen model JSON exceeds byte limit")
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ValueError("unbound Qwen prose or invalid JSON") from error
    parsed = parse_qwen_candidate_bindings(raw, sealed_inventory)
    return seal_immutable(parsed)


def _validated_inventory(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("omni_inventory must be an object")
    candidate = deepcopy(dict(value))
    declared = candidate.pop("content_sha256", None)
    if (
        not isinstance(declared, str)
        or re.fullmatch(r"[0-9a-f]{64}", declared) is None
        or declared != content_sha256(dict(value))
    ):
        raise ValueError("sealed Omni inventory content_sha256 mismatch")
    return validate_omni_inventory(candidate)


def _sealed_context(value: object, capture_identity: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("sealed OCR/UIA context is missing")
    context = deepcopy(dict(value))
    if context.get("content_sha256") != content_sha256(context):
        raise ValueError("OCR/UIA context content_sha256 mismatch")
    if (
        context.get("contract_version") != "hybrid_capture_context_v1"
        or context.get("capture_lineage_ref") != capture_identity["capture_lineage_ref"]
    ):
        raise ValueError("OCR/UIA context capture mismatch")
    sources = context.get("sources")
    if not isinstance(sources, list) or len(sources) != 2 or {
        source.get("source_kind") for source in sources if isinstance(source, Mapping)
    } != {"ocr", "uia"}:
        raise ValueError("OCR/UIA context requires sealed OCR and UIA sources")
    if any(
        not isinstance(source, Mapping)
        or source.get("capture_lineage_ref") != capture_identity["capture_lineage_ref"]
        for source in sources
    ):
        raise ValueError("OCR/UIA context source capture mismatch")
    return context


def _validated_payload(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _PAYLOAD_FIELDS:
        raise ValueError("Hybrid Qwen payload is not closed")
    payload = deepcopy(dict(value))
    for field in ("project_root", "run_id", "capture_image_path"):
        if not isinstance(payload[field], str) or not payload[field].strip():
            raise ValueError(f"{field} is invalid")
    revision = payload["workflow_revision"]
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ValueError("workflow_revision is invalid")
    reference = payload["hybrid_capture_bundle_ref"]
    if (
        not isinstance(reference, Mapping)
        or set(reference) != {"id", "content_sha256"}
        or not isinstance(reference.get("id"), str)
        or not isinstance(reference.get("content_sha256"), str)
    ):
        raise ValueError("hybrid_capture_bundle_ref is invalid")
    return payload


def _capture_path(root: Path, value: str) -> Path:
    candidate = Path(value)
    resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise ValueError("capture_image_path escapes project_root") from None
    if not resolved.is_file():
        raise ValueError("capture_image_path is not a file")
    return resolved


def _read_verified_capture(
    path: Path,
    identity: dict[str, Any],
) -> tuple[bytes, str, str]:
    try:
        raw = path.read_bytes()
        with Image.open(BytesIO(raw)) as image:
            image_format = str(image.format or "").upper()
            image.verify()
        with Image.open(BytesIO(raw)) as image:
            size = {"width": image.width, "height": image.height}
    except (OSError, SyntaxError, UnidentifiedImageError):
        raise ValueError("canonical screenshot is unreadable") from None
    digest = sha256(raw).hexdigest()
    if digest != identity["screenshot_sha256"] or size != identity["image_size"]:
        raise ValueError("canonical screenshot capture mismatch")
    media_types = {"PNG": "image/png", "JPEG": "image/jpeg"}
    media_type = media_types.get(image_format)
    if media_type is None:
        raise ValueError("canonical screenshot media type is unsupported")
    return raw, media_type, digest


def _canonical_semantic_text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("semantic target fields must be strings")
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _semantic_target_key(value: Mapping[str, Any]) -> tuple[str, str, str]:
    return tuple(
        _canonical_semantic_text(value.get(field))
        for field in ("role", "label", "description")
    )


def _validate_model_json_bounds(value: object) -> None:
    stack: list[tuple[object, int]] = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        if depth > _MAX_JSON_DEPTH:
            raise ValueError("Qwen output exceeds maximum JSON depth")
        if isinstance(current, str):
            if len(current.encode("utf-8")) > _MAX_MODEL_STRING_BYTES:
                raise ValueError("Qwen model string exceeds UTF-8 byte limit")
            continue
        if isinstance(current, Mapping):
            for key, child in current.items():
                if len(str(key).encode("utf-8")) > _MAX_MODEL_STRING_BYTES:
                    raise ValueError("Qwen model string exceeds UTF-8 byte limit")
                stack.append((child, depth + 1))
        elif isinstance(current, list):
            stack.extend((child, depth + 1) for child in current)


def _first_forbidden_field(value: object) -> str | None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key) in _FORBIDDEN_FIELDS:
                return str(key)
            found = _first_forbidden_field(child)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _first_forbidden_field(child)
            if found is not None:
                return found
    return None
