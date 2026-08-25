from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from app.learn.hybrid.contracts import validate_fusion_result, validate_qwen_bindings
from app.learn.hybrid.omni_candidates import validate_current_capture_bundle
from app.learn.hybrid.qwen_binding import validate_sealed_omni_inventory
from app.learn.recognition.roi import build_roi_crop_metadata
from app.learn.recognition.uei.canonical import (
    canonical_json_bytes,
    content_sha256,
    seal_immutable,
)


VISTA_REQUEST_CONTRACT = "hybrid_vista_refinement_request_v1"
VISTA_PROPOSAL_CONTRACT = "hybrid_vista_refinement_proposal_v1"
def build_vista_requests(
    fusion_result: Mapping[str, Any],
    capture_bundle: Mapping[str, Any],
    *,
    omni_inventory: Mapping[str, Any],
    qwen_bindings: Mapping[str, Any],
    qwen_cleanup_receipt: Mapping[str, Any],
    expected_workflow_revision: int,
) -> list[dict[str, Any]]:
    """为同一封存截图上的 BOUND candidate 构造确定性 VISTA 请求。"""

    inventory = validate_sealed_omni_inventory(omni_inventory)
    bindings = validate_qwen_bindings(
        _sealed_payload(qwen_bindings, "Qwen bindings"), inventory
    )
    fusion = validate_fusion_result(
        _sealed_payload(fusion_result, "fusion result"), inventory, bindings
    )
    bundle = validate_current_capture_bundle(capture_bundle)
    from app.core.model_server import validate_qwen_cleanup_receipt

    cleanup_receipt = validate_qwen_cleanup_receipt(qwen_cleanup_receipt)
    if bundle.get("workflow_revision") != expected_workflow_revision:
        raise ValueError("capture bundle workflow revision is stale")
    fusion_identity = _object(fusion.get("capture_identity"), "fusion capture identity")
    bundle_identity = _object(bundle.get("capture_identity"), "bundle capture identity")
    if canonical_json_bytes(fusion_identity) != canonical_json_bytes(bundle_identity):
        raise ValueError("fusion and bundle capture lineage do not match")
    source_revision = _required_text(fusion.get("config_sha256"), "fusion config_sha256")
    capture_sha256 = _required_text(
        fusion_identity.get("screenshot_sha256"),
        "capture screenshot_sha256",
    )
    image_size = _image_size(fusion_identity.get("image_size"))
    capture_lineage_ref = deepcopy(
        _object(fusion_identity.get("capture_lineage_ref"), "capture lineage ref")
    )
    candidates = fusion.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("fusion candidates must be a list")

    requests: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise ValueError("fusion candidate must be an object")
        candidate_id = _required_text(candidate.get("candidate_id"), "candidate_id")
        if candidate_id in seen_ids:
            raise ValueError("duplicate fusion candidate_id")
        seen_ids.add(candidate_id)
        if candidate.get("state") != "BOUND":
            continue
        if candidate.get("vista_eligible") is not True:
            raise ValueError("BOUND candidate is not VISTA eligible")
        if candidate.get("coordinate_space") != "capture_pixel_xyxy":
            raise ValueError("BOUND candidate coordinate space is invalid")
        bbox = _xyxy(candidate.get("bbox_original"), "candidate bbox")
        _inside_capture(bbox, image_size, "candidate bbox")
        bbox_ref = seal_immutable(
            {
                "contract_version": "hybrid_candidate_bbox_ref_v1",
                "candidate_id": candidate_id,
                "source_revision": source_revision,
                "capture_sha256": capture_sha256,
                "coordinate_space": "capture_pixel_xyxy",
                "xyxy": bbox,
            }
        )
        bbox_dict = {
            "x": bbox[0],
            "y": bbox[1],
            "w": bbox[2] - bbox[0],
            "h": bbox[3] - bbox[1],
        }
        roi_metadata = build_roi_crop_metadata(
            source_image_size=image_size,
            candidate_bbox=bbox_dict,
            crop_size={
                "width": max(1, bbox_dict["w"] * 2),
                "height": max(1, bbox_dict["h"] * 2),
            },
            expand_scale=2.0,
        )
        roi_bbox = roi_metadata["coordinate_transform"]["roi_bbox"]
        roi_xyxy = [
            roi_bbox["x"],
            roi_bbox["y"],
            roi_bbox["x"] + roi_bbox["w"],
            roi_bbox["y"] + roi_bbox["h"],
        ]
        roi_ref = seal_immutable(
            {
                "contract_version": "hybrid_permitted_roi_v1",
                "roi_id": f"roi/{candidate_id}",
                "candidate_id": candidate_id,
                "source_revision": source_revision,
                "capture_sha256": capture_sha256,
                "capture_lineage_ref": capture_lineage_ref,
                "coordinate_space": "capture_pixel_xyxy",
                "xyxy": roi_xyxy,
                "permitted_for_refinement": True,
            }
        )
        affine_ref = seal_immutable(
            {
                "contract_version": "hybrid_roi_affine_transform_v1",
                "candidate_id": candidate_id,
                "source_revision": source_revision,
                "capture_sha256": capture_sha256,
                "roi_ref": {
                    "id": roi_ref["roi_id"],
                    "content_sha256": roi_ref["content_sha256"],
                },
                "source_space": "roi_pixel_xy",
                "target_space": "capture_pixel_xyxy",
                "matrix": [
                    1.0,
                    0.0,
                    float(roi_bbox["x"]),
                    0.0,
                    1.0,
                    float(roi_bbox["y"]),
                ],
            }
        )
        requests.append(
            seal_immutable(
                {
                    "contract_version": VISTA_REQUEST_CONTRACT,
                    "submission_status": "SUBMITTED",
                    "candidate_id": candidate_id,
                    "source_revision": source_revision,
                    "capture_id": _required_text(
                        fusion_identity.get("capture_id"),
                        "capture_id",
                    ),
                    "capture_sha256": capture_sha256,
                    "capture_image_size": deepcopy(image_size),
                    "capture_lineage_ref": capture_lineage_ref,
                    "candidate_bbox_ref": bbox_ref,
                    "roi_ref": roi_ref,
                    "affine_transform_ref": affine_ref,
                    "qwen_cleanup_receipt": deepcopy(cleanup_receipt),
                    "authoritative_parent_refs": {
                        "fusion_result": _content_ref(fusion_result, "fusion result"),
                        "capture_bundle": _content_ref(capture_bundle, "capture bundle"),
                        "omni_inventory": _content_ref(omni_inventory, "Omni inventory"),
                        "qwen_bindings": _content_ref(qwen_bindings, "Qwen bindings"),
                    },
                    "automatic_acceptance": False,
                }
            )
        )
    return requests


def validate_vista_proposal(
    *,
    request: Mapping[str, Any],
    raw_result: Mapping[str, Any],
) -> dict[str, Any]:
    """校验 provider 提议；任何失败都只投影到人工审核。"""

    raw = deepcopy(dict(raw_result)) if isinstance(raw_result, Mapping) else {"raw_value": deepcopy(raw_result)}
    base: dict[str, Any] = {
        "contract_version": VISTA_PROPOSAL_CONTRACT,
        "status": "TRANSFORM_INVALID",
        "review_status": "REVIEW_REQUIRED",
        "automatic_acceptance": False,
        "raw_provider_result": raw,
        "provider_provenance": deepcopy(raw.get("provenance"))
        if isinstance(raw.get("provenance"), Mapping)
        else {},
    }
    try:
        normalized_request = _validated_request(request)
        for field in (
            "candidate_id",
            "candidate_bbox_ref",
            "roi_ref",
            "affine_transform_ref",
            "source_revision",
            "capture_sha256",
        ):
            base[field] = deepcopy(normalized_request[field])
        if normalized_request["submission_status"] != "SUBMITTED":
            raise ValueError("VISTA request was not submitted")
        raw_status = str(raw.get("status") or "PROPOSED").strip()
        if raw_status in {"VISTA_FAILED", "FAILED", "ERROR"} or raw.get("success") is False:
            base["status"] = "VISTA_FAILED"
            return base
        for field in (
            "candidate_id",
            "capture_id",
            "capture_sha256",
            "source_revision",
        ):
            if raw.get(field) != normalized_request[field]:
                raise ValueError(f"VISTA raw result {field} mismatch")
        if canonical_json_bytes(raw.get("affine_transform_ref")) != canonical_json_bytes(
            normalized_request["affine_transform_ref"]
        ):
            raise ValueError("VISTA affine transform mismatch")
        point = _point(raw.get("point"))
        coordinate_space = str(
            raw.get("point_coordinate_space") or "capture_pixel_xyxy"
        ).strip()
        if coordinate_space == "roi_pixel_xy":
            point = _apply_affine(
                normalized_request["affine_transform_ref"]["matrix"],
                point,
            )
        elif coordinate_space != "capture_pixel_xyxy":
            raise ValueError("VISTA point coordinate space is invalid")
        candidate_bbox = normalized_request["candidate_bbox_ref"]["xyxy"]
        roi = normalized_request["roi_ref"]["xyxy"]
        if not (_point_inside(point, candidate_bbox) and _point_inside(point, roi)):
            base["status"] = "VISTA_OUT_OF_BOUNDS"
            return base
        base["status"] = "PROPOSED"
        base["canonical_point"] = {
            "coordinate_space": "capture_pixel_xyxy",
            "xy": [_compact_number(point[0]), _compact_number(point[1])],
        }
        return base
    except (TypeError, ValueError) as exc:
        base["validation_error"] = str(exc)
        return base


def validate_vista_request_pre_acquisition(
    *, request: Mapping[str, Any], authoritative_context: Mapping[str, Any]
) -> dict[str, Any]:
    """在任何裁剪或 provider 获取前，从完整父证据重建并精确匹配请求。"""
    normalized = _validated_request(request)
    context = _object(authoritative_context, "VISTA authoritative context")
    from app.learn.hybrid.capture import load_and_verify_hybrid_capture_bundle

    authoritative_bundle = load_and_verify_hybrid_capture_bundle(
        project_root=Path(_required_text(context.get("project_root"), "project_root")),
        bundle_ref=context.get("hybrid_capture_bundle_ref"),
        expected_run_id=_required_text(context.get("run_id"), "run_id"),
        expected_workflow_revision=context.get("workflow_revision"),
    )
    if canonical_json_bytes(authoritative_bundle) != canonical_json_bytes(
        context.get("capture_bundle")
    ):
        raise ValueError("VISTA capture bundle does not match authoritative artifact store")
    expected = build_vista_requests(
        context.get("fusion_result"),
        authoritative_bundle,
        omni_inventory=context.get("omni_inventory"),
        qwen_bindings=context.get("qwen_bindings"),
        qwen_cleanup_receipt=context.get("qwen_cleanup_receipt"),
        expected_workflow_revision=context.get("workflow_revision"),
    )
    match = next(
        (item for item in expected if item.get("candidate_id") == normalized.get("candidate_id")),
        None,
    )
    if match is None or canonical_json_bytes(match) != canonical_json_bytes(normalized):
        raise ValueError("VISTA request does not match authoritative current lineage")
    if normalized.get("submission_status") != "SUBMITTED":
        raise ValueError("VISTA request was not submitted")
    return normalized


def _validated_request(value: Mapping[str, Any]) -> dict[str, Any]:
    request = _sealed_object(value, "VISTA request")
    if request.get("contract_version") != VISTA_REQUEST_CONTRACT:
        raise ValueError("VISTA request contract is invalid")
    candidate_id = _required_text(request.get("candidate_id"), "candidate_id")
    source_revision = _required_text(request.get("source_revision"), "source_revision")
    capture_sha256 = _required_text(request.get("capture_sha256"), "capture_sha256")
    _image_size(request.get("capture_image_size"))
    from app.core.model_server import validate_qwen_cleanup_receipt

    validate_qwen_cleanup_receipt(request.get("qwen_cleanup_receipt"))
    parents = _object(request.get("authoritative_parent_refs"), "authoritative parent refs")
    if set(parents) != {"fusion_result", "capture_bundle", "omni_inventory", "qwen_bindings"}:
        raise ValueError("VISTA authoritative parent refs are incomplete")
    for ref in parents.values():
        child = _object(ref, "authoritative parent ref")
        _required_text(child.get("id"), "authoritative parent ref id")
        digest = _required_text(child.get("content_sha256"), "authoritative parent ref digest")
        if len(digest) != 64:
            raise ValueError("VISTA authoritative parent ref digest is invalid")
    bbox_ref = _sealed_object(request.get("candidate_bbox_ref"), "candidate bbox ref")
    roi_ref = _sealed_object(request.get("roi_ref"), "ROI ref")
    affine_ref = _sealed_object(request.get("affine_transform_ref"), "affine transform ref")
    if (
        bbox_ref.get("candidate_id") != candidate_id
        or roi_ref.get("candidate_id") != candidate_id
        or affine_ref.get("candidate_id") != candidate_id
    ):
        raise ValueError("VISTA request candidate lineage mismatch")
    for child in (bbox_ref, roi_ref, affine_ref):
        if child.get("source_revision") != source_revision or child.get("capture_sha256") != capture_sha256:
            raise ValueError("VISTA request source lineage mismatch")
    bbox = _xyxy(bbox_ref.get("xyxy"), "candidate bbox ref")
    roi = _xyxy(roi_ref.get("xyxy"), "ROI ref")
    if roi_ref.get("permitted_for_refinement") is not True:
        raise ValueError("ROI is not permitted for refinement")
    expected_roi_ref = {
        "id": roi_ref.get("roi_id"),
        "content_sha256": roi_ref.get("content_sha256"),
    }
    if affine_ref.get("roi_ref") != expected_roi_ref:
        raise ValueError("affine transform ROI ref mismatch")
    matrix = affine_ref.get("matrix")
    if not isinstance(matrix, list) or len(matrix) != 6:
        raise ValueError("affine matrix must contain six coefficients")
    for item in matrix:
        _number(item, "affine matrix coefficient")
    if affine_ref.get("source_space") != "roi_pixel_xy" or affine_ref.get("target_space") != "capture_pixel_xyxy":
        raise ValueError("affine transform coordinate space mismatch")
    request["candidate_bbox_ref"]["xyxy"] = bbox
    request["roi_ref"]["xyxy"] = roi
    return request


def _sealed_object(value: Any, name: str) -> dict[str, Any]:
    result = _object(value, name)
    declared = result.get("content_sha256")
    if not isinstance(declared, str) or declared != content_sha256(result):
        raise ValueError(f"{name} must be sealed")
    return deepcopy(result)


def _sealed_capture_bundle(value: Any) -> dict[str, Any]:
    try:
        return validate_current_capture_bundle(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("capture bundle must satisfy the closed sealed contract") from exc


def _sealed_payload(value: Any, name: str) -> dict[str, Any]:
    result = _sealed_object(value, name)
    result.pop("content_sha256")
    return result


def _content_ref(value: Any, name: str) -> dict[str, str]:
    if name == "capture bundle" and isinstance(value, Mapping):
        bundle_id = str(value.get("bundle_id") or "")
        digest = bundle_id.rsplit("/", 1)[-1]
        if bundle_id and len(digest) == 64:
            return {"id": bundle_id, "content_sha256": digest}
    sealed = _sealed_object(value, name)
    return {"id": name.replace(" ", "_").lower(), "content_sha256": sealed["content_sha256"]}


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return dict(value)


def _required_text(value: Any, name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{name} is required")
    return normalized


def _image_size(value: Any) -> dict[str, int]:
    result = _object(value, "image size")
    width = result.get("width")
    height = result.get("height")
    if isinstance(width, bool) or isinstance(height, bool) or not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        raise ValueError("image size must contain positive integers")
    return {"width": width, "height": height}


def _xyxy(value: Any, name: str) -> list[int]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError(f"{name} must be xyxy")
    result: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            raise ValueError(f"{name} must contain integers")
        result.append(item)
    if result[0] < 0 or result[1] < 0 or result[2] <= result[0] or result[3] <= result[1]:
        raise ValueError(f"{name} geometry is invalid")
    return result


def _inside_capture(bbox: list[int], image_size: dict[str, int], name: str) -> None:
    if bbox[2] > image_size["width"] or bbox[3] > image_size["height"]:
        raise ValueError(f"{name} is outside capture")


def _point(value: Any) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError("VISTA point must contain two coordinates")
    return [_number(value[0], "VISTA point x"), _number(value[1], "VISTA point y")]


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be finite")
    normalized = float(value)
    if normalized != normalized or normalized in {float("inf"), float("-inf")}:
        raise ValueError(f"{name} must be finite")
    return normalized


def _apply_affine(matrix: list[Any], point: list[float]) -> list[float]:
    values = [_number(item, "affine matrix coefficient") for item in matrix]
    x, y = point
    return [
        values[0] * x + values[1] * y + values[2],
        values[3] * x + values[4] * y + values[5],
    ]


def _point_inside(point: list[float], bbox: list[int]) -> bool:
    return bbox[0] < point[0] < bbox[2] and bbox[1] < point[1] < bbox[3]


def _compact_number(value: float) -> int | float:
    return int(value) if value.is_integer() else value


__all__ = [
    "build_vista_requests",
    "validate_vista_request_pre_acquisition",
    "validate_vista_proposal",
]
