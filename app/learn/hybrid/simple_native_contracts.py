"""Pure, independent model-native contracts for the five-screen diagnostic."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
import math
from collections.abc import Mapping
from typing import Any

from app.learn.recognition.uei.canonical import content_sha256


@dataclass(frozen=True)
class OmniNativeItem:
    """官方 OmniParser 输出；运行时字段绝不来自模型。"""

    bbox: tuple[float, float, float, float]
    type: str
    content: str
    interactivity: bool


def _number(value: object, *, field: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{field} must be a finite number")
    number = float(value)
    if not low <= number <= high:
        raise ValueError(f"{field} is outside allowed range")
    return number


def parse_omni_native_output(raw: object) -> tuple[OmniNativeItem, ...]:
    """严格解析官方四字段 Omni 输出，不接受 runtime/evidence 注入。"""
    if not isinstance(raw, Mapping) or set(raw) != {"items"} or not isinstance(raw["items"], list):
        raise ValueError("Omni native output must be a closed items object")
    result: list[OmniNativeItem] = []
    for index, value in enumerate(raw["items"]):
        if not isinstance(value, Mapping) or set(value) != {"bbox", "type", "content", "interactivity"}:
            raise ValueError(f"Omni item[{index}] is not closed")
        bbox = value["bbox"]
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            raise ValueError(f"Omni item[{index}].bbox is invalid")
        coordinates = tuple(_number(number, field=f"Omni item[{index}].bbox", low=0.0, high=1.0) for number in bbox)
        if not coordinates[0] < coordinates[2] or not coordinates[1] < coordinates[3]:
            raise ValueError(f"Omni item[{index}].bbox is invalid")
        kind, content, interactivity = value["type"], value["content"], value["interactivity"]
        if not isinstance(kind, str) or not kind.strip() or len(kind) > 64:
            raise ValueError(f"Omni item[{index}].type is invalid")
        if not isinstance(content, str) or len(content) > 4096:
            raise ValueError(f"Omni item[{index}].content is invalid")
        if not isinstance(interactivity, bool):
            raise ValueError(f"Omni item[{index}].interactivity is invalid")
        result.append(OmniNativeItem(coordinates, kind, content, interactivity))
    return tuple(result)


def _runtime_candidates(runtime_request: Mapping[str, object]) -> tuple[list[Mapping[str, object]], tuple[int, int]]:
    if not isinstance(runtime_request, Mapping):
        raise ValueError("Qwen runtime request must be an object")
    if runtime_request.get("contract_version") != "hybrid_qwen_binding_request_v1":
        raise ValueError("Qwen runtime request must be built by the full binding contract")
    screenshot = runtime_request.get("screenshot")
    candidates = runtime_request.get("candidates")
    if not isinstance(screenshot, Mapping) or not isinstance(screenshot.get("image_size"), Mapping) or not isinstance(candidates, list):
        raise ValueError("Qwen runtime request is invalid")
    size = screenshot["image_size"]
    width, height = size.get("width"), size.get("height")
    if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in (width, height)):
        raise ValueError("Qwen runtime image_size is invalid")
    normalized: list[Mapping[str, object]] = []
    seen: set[str] = set()
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, Mapping):
            raise ValueError(f"Qwen runtime candidate[{index}] is invalid")
        candidate_id, box, active = candidate.get("candidate_id"), candidate.get("bbox_original"), candidate.get("active")
        if not isinstance(candidate_id, str) or not candidate_id.startswith("candidate/") or candidate_id in seen:
            raise ValueError("Qwen runtime candidate identity is invalid")
        if not isinstance(box, (list, tuple)) or len(box) != 4 or not isinstance(active, bool):
            raise ValueError("Qwen runtime candidate geometry is invalid")
        values = tuple(_number(point, field="Qwen runtime candidate geometry", low=0.0, high=float(max(width, height))) for point in box)
        if not values[0] < values[2] <= width or not values[1] < values[3] <= height:
            raise ValueError("Qwen runtime candidate geometry is invalid")
        seen.add(candidate_id); normalized.append(candidate)
    return normalized, (width, height)


def build_qwen_model_projection(runtime_request: Mapping[str, object]) -> dict[str, object]:
    """从已验证的完整请求生成无 stable ID 的短 ordinal projection。"""
    candidates, size = _runtime_candidates(runtime_request)
    return {"image_size": [size[0], size[1]], "candidates": [
        {"i": index, "box": list(candidate["bbox_original"]), "active": candidate["active"]}
        for index, candidate in enumerate(candidates)
    ]}


def expand_qwen_model_response(raw: object, *, projection: Mapping[str, object], runtime_request: Mapping[str, object]) -> dict[str, object]:
    """将 ordinal 恢复为 runtime ID，保留既有 bindings artifact 形状。"""
    candidates, _ = _runtime_candidates(runtime_request)
    expected = list(range(len(candidates)))
    if not isinstance(projection, Mapping) or projection != build_qwen_model_projection(runtime_request):
        raise ValueError("Qwen projection does not match full runtime request")
    if not isinstance(raw, Mapping) or set(raw) != {"bindings"} or not isinstance(raw["bindings"], list):
        raise ValueError("Qwen native response is not closed")
    if len(raw["bindings"]) != len(expected):
        raise ValueError("Qwen ordinal coverage is incomplete")
    expanded: list[dict[str, object]] = []
    for ordinal, binding in enumerate(raw["bindings"]):
        if not isinstance(binding, Mapping) or set(binding) != {"i", "role", "label", "status", "confidence"}:
            raise ValueError("Qwen ordinal binding is not closed")
        index = binding["i"]
        if isinstance(index, bool) or not isinstance(index, int) or index != ordinal or index not in expected:
            raise ValueError("Qwen ordinal order or coverage is invalid")
        role, label, status = binding["role"], binding["label"], binding["status"]
        confidence = binding["confidence"]
        if not isinstance(role, str) or not role.strip() or len(role) > 64 or not isinstance(label, str) or not label.strip() or len(label) > 256:
            raise ValueError("Qwen native semantic value is invalid")
        if not isinstance(status, str) or status not in {"BOUND", "UNBOUND", "AMBIGUOUS", "CONFLICT"}:
            raise ValueError("Qwen native status is invalid")
        confidence = _number(confidence, field="Qwen native confidence", low=0.0, high=1.0)
        expanded.append({"candidate_id": candidates[index]["candidate_id"], "role": role, "label": label, "binding_status": status, "confidence": confidence})
    # This is deliberately the existing wire shape; the runner supplies its sealed inventory to
    # parse_qwen_candidate_bindings before consumers see the result.
    return {"bindings": expanded}



def _runtime_goal_binding_request(
    runtime_request: Mapping[str, object],
) -> tuple[list[Mapping[str, object]], list[Mapping[str, object]], tuple[int, int]]:
    if not isinstance(runtime_request, Mapping):
        raise ValueError("Qwen goal-binding runtime request must be an object")
    if runtime_request.get("contract_version") != "simple_native_qwen_goal_binding_request_v1":
        raise ValueError("Qwen goal-binding request contract is invalid")
    screenshot, goals, candidates = (
        runtime_request.get("screenshot"),
        runtime_request.get("goals"),
        runtime_request.get("candidates"),
    )
    if not isinstance(screenshot, Mapping) or not isinstance(screenshot.get("image_size"), Mapping):
        raise ValueError("Qwen goal-binding image_size is invalid")
    size = screenshot["image_size"]
    width, height = size.get("width"), size.get("height")
    if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in (width, height)):
        raise ValueError("Qwen goal-binding image_size is invalid")
    if not isinstance(goals, list) or not isinstance(candidates, list):
        raise ValueError("Qwen goal-binding goals or candidates are invalid")
    normalized_goals: list[Mapping[str, object]] = []
    for index, goal in enumerate(goals):
        if (
            not isinstance(goal, Mapping)
            or set(goal) != {"goal_index", "role", "label"}
            or isinstance(goal.get("goal_index"), bool)
            or goal.get("goal_index") != index
            or not isinstance(goal.get("role"), str)
            or not goal["role"].strip()
            or len(goal["role"]) > 64
            or not isinstance(goal.get("label"), str)
            or not goal["label"].strip()
            or len(goal["label"]) > 256
        ):
            raise ValueError("Qwen goal-binding goal is invalid")
        normalized_goals.append(goal)
    normalized_candidates: list[Mapping[str, object]] = []
    seen_ids: set[str] = set()
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, Mapping):
            raise ValueError(f"Qwen goal-binding candidate[{index}] is invalid")
        candidate_id, box, active = candidate.get("candidate_id"), candidate.get("bbox_original"), candidate.get("active")
        if not isinstance(candidate_id, str) or not candidate_id.startswith("candidate/") or candidate_id in seen_ids:
            raise ValueError("Qwen goal-binding candidate identity is invalid")
        if not isinstance(box, (list, tuple)) or len(box) != 4 or not isinstance(active, bool):
            raise ValueError("Qwen goal-binding candidate geometry is invalid")
        values = tuple(_number(point, field="Qwen goal-binding candidate geometry", low=0.0, high=float(max(width, height))) for point in box)
        if not values[0] < values[2] <= width or not values[1] < values[3] <= height:
            raise ValueError("Qwen goal-binding candidate geometry is invalid")
        seen_ids.add(candidate_id)
        normalized_candidates.append(candidate)
    return normalized_goals, normalized_candidates, (width, height)


def build_qwen_goal_binding_projection(runtime_request: Mapping[str, object]) -> dict[str, object]:
    """Project fixed semantic goals and Omni geometry without runtime identities."""
    goals, candidates, size = _runtime_goal_binding_request(runtime_request)
    return {
        "image_size": [size[0], size[1]],
        "goals": [deepcopy(dict(goal)) for goal in goals],
        "candidates": [
            {"candidate_index": index, "bbox": list(candidate["bbox_original"]), "active": candidate["active"]}
            for index, candidate in enumerate(candidates)
        ],
    }


def expand_qwen_goal_binding_response(
    raw: object, *, projection: Mapping[str, object], runtime_request: Mapping[str, object]
) -> dict[str, object]:
    """Fail closed while restoring stable candidate IDs and deterministic goal semantics."""
    goals, candidates, _ = _runtime_goal_binding_request(runtime_request)
    if not isinstance(projection, Mapping) or projection != build_qwen_goal_binding_projection(runtime_request):
        raise ValueError("Qwen goal-binding projection does not match full runtime request")
    if not isinstance(raw, list):
        raise ValueError("Qwen goal-binding response is not a bare array")
    if len(raw) != len(goals):
        raise ValueError("Qwen goal-binding coverage is incomplete")
    expanded: list[dict[str, object]] = []
    for index, binding in enumerate(raw):
        if not isinstance(binding, Mapping) or set(binding) != {"goal_index", "candidate_index", "status", "confidence"}:
            raise ValueError("Qwen goal-binding item is not closed")
        goal_index, candidate_index, status = binding["goal_index"], binding["candidate_index"], binding["status"]
        if isinstance(goal_index, bool) or not isinstance(goal_index, int) or goal_index != index:
            raise ValueError("Qwen goal-binding order or coverage is invalid")
        if not isinstance(status, str) or status not in {"BOUND", "UNBOUND"}:
            raise ValueError("Qwen goal-binding status is invalid")
        if status == "BOUND":
            if isinstance(candidate_index, bool) or not isinstance(candidate_index, int) or not 0 <= candidate_index < len(candidates):
                raise ValueError("Qwen bound candidate_index is invalid")
            candidate_id: str | None = str(candidates[candidate_index]["candidate_id"])
        else:
            if candidate_index is not None:
                raise ValueError("Qwen unbound candidate_index must be null")
            candidate_id = None
        confidence = _number(binding["confidence"], field="Qwen goal-binding confidence", low=0.0, high=1.0)
        goal = goals[goal_index]
        expanded.append({
            "goal_index": goal_index,
            "candidate_id": candidate_id,
            "role": goal["role"],
            "label": goal["label"],
            "status": status,
            "confidence": confidence,
        })
    return {"bindings": expanded}


_NATIVE_GROUNDING_FORMATS = {
    "ui_venus_point",
    "gui_actor_topk_points",
    "phi_ground_point_or_bbox",
}
_NATIVE_POINT_SPACES = {
    "normalized_0_1",
    "normalized_0_1000",
    "capture_pixels",
}


def _native_pair(value: object, *, field: str) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{field} must be a pair")
    return (
        _number(value[0], field=field, low=0.0, high=float("inf")),
        _number(value[1], field=field, low=0.0, high=float("inf")),
    )


def _native_bbox_center(
    bbox: object, *, coordinate_space: str, image_size: tuple[int, int]
) -> tuple[float, float]:
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        raise ValueError("Phi-Ground bbox must contain four coordinates")
    if coordinate_space == "normalized_0_1":
        x_high, y_high = 1.0, 1.0
    elif coordinate_space == "normalized_0_1000":
        x_high, y_high = 1000.0, 1000.0
    elif coordinate_space == "capture_pixels":
        x_high, y_high = float(image_size[0]), float(image_size[1])
    else:
        raise ValueError("native coordinate_space is unsupported")
    x1 = _number(bbox[0], field="Phi-Ground bbox x", low=0.0, high=x_high)
    y1 = _number(bbox[1], field="Phi-Ground bbox y", low=0.0, high=y_high)
    x2 = _number(bbox[2], field="Phi-Ground bbox x", low=0.0, high=x_high)
    y2 = _number(bbox[3], field="Phi-Ground bbox y", low=0.0, high=y_high)
    if not x1 < x2 or not y1 < y2:
        raise ValueError("Phi-Ground bbox is invalid")
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


def _native_grounding_point(
    raw: object,
    *,
    provider_format: str,
    coordinate_space: str,
    image_size: tuple[int, int],
) -> tuple[float, float]:
    if not isinstance(raw, Mapping):
        raise ValueError("native grounding output must be an object")
    if provider_format == "ui_venus_point":
        if set(raw) != {"point"}:
            raise ValueError("UI-Venus native output is not closed")
        return _native_pair(raw["point"], field="UI-Venus point")
    if provider_format == "gui_actor_topk_points":
        if set(raw) != {"topk_points"} or not isinstance(raw["topk_points"], list) or not raw["topk_points"]:
            raise ValueError("GUI-Actor native output is not a non-empty closed top-k list")
        # 公平基准固定只使用第一项；后续命中也不能挽救 top-1 失败。
        return _native_pair(raw["topk_points"][0], field="GUI-Actor topk_points[0]")
    if provider_format == "phi_ground_point_or_bbox":
        if set(raw) == {"point"}:
            return _native_pair(raw["point"], field="Phi-Ground point")
        if set(raw) != {"bbox"}:
            raise ValueError("Phi-Ground native output must contain exactly one point or bbox")
        return _native_bbox_center(
            raw["bbox"], coordinate_space=coordinate_space, image_size=image_size
        )
    raise AssertionError("provider format allowlist and parser are inconsistent")


def _capture_point(
    point: tuple[float, float], *, coordinate_space: str, image_size: tuple[int, int]
) -> tuple[float, float]:
    if coordinate_space not in _NATIVE_POINT_SPACES:
        raise ValueError("native coordinate_space is unsupported")
    width, height = image_size
    x, y = point
    if coordinate_space == "normalized_0_1":
        x = _number(x, field="normalized x", low=0.0, high=1.0) * width
        y = _number(y, field="normalized y", low=0.0, high=1.0) * height
    elif coordinate_space == "normalized_0_1000":
        x = _number(x, field="normalized x", low=0.0, high=1000.0) * width / 1000.0
        y = _number(y, field="normalized y", low=0.0, high=1000.0) * height / 1000.0
    else:
        x = _number(x, field="capture x", low=0.0, high=float(width))
        y = _number(y, field="capture y", low=0.0, high=float(height))
    # 截图点采用半开范围，避免 x==width 或 y==height 成为伪合法像素。
    if not 0.0 <= x < width or not 0.0 <= y < height:
        raise ValueError("native point is outside capture")
    return x, y


def _native_binding_result(
    *,
    goal_index: int,
    goal: Mapping[str, object],
    status: str,
    confidence: float,
    capture_point: tuple[float, float] | None,
    candidate_index: int | None = None,
    candidate_id: str | None = None,
) -> dict[str, object]:
    return {
        "goal_index": goal_index,
        "candidate_index": candidate_index,
        "candidate_id": candidate_id,
        "role": goal["role"],
        "label": goal["label"],
        "status": status,
        "confidence": confidence,
        "capture_point": list(capture_point) if capture_point is not None else None,
    }


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _verify_source_capture_identity(
    *,
    source_capture_identity: object,
    runtime_request: Mapping[str, object],
    image_size: tuple[int, int],
) -> None:
    expected_source_fields = {
        "capture_id",
        "screenshot_sha256",
        "artifact_ref",
        "capture_identity_content_sha256",
    }
    runtime_identity = runtime_request.get("capture_identity")
    screenshot = runtime_request.get("screenshot")
    if (
        not isinstance(source_capture_identity, Mapping)
        or set(source_capture_identity) != expected_source_fields
        or not isinstance(runtime_identity, Mapping)
        or not isinstance(screenshot, Mapping)
    ):
        raise ValueError("native grounding capture identity is invalid")
    capture_id = runtime_identity.get("capture_id")
    screenshot_sha256 = runtime_identity.get("screenshot_sha256")
    artifact_ref = runtime_identity.get("artifact_ref")
    identity_image_size = runtime_identity.get("image_size")
    if (
        not isinstance(capture_id, str)
        or not capture_id
        or not _valid_sha256(screenshot_sha256)
        or not isinstance(artifact_ref, Mapping)
        or set(artifact_ref) != {"id", "content_sha256"}
        or not isinstance(artifact_ref.get("id"), str)
        or not artifact_ref["id"]
        or not _valid_sha256(artifact_ref.get("content_sha256"))
        or identity_image_size != {"width": image_size[0], "height": image_size[1]}
        or screenshot.get("screenshot_sha256") != screenshot_sha256
    ):
        raise ValueError("runtime capture identity is invalid")
    runtime_identity_dict = dict(runtime_identity)
    calculated_identity_hash = content_sha256(runtime_identity_dict)
    declared_identity_hash = runtime_identity.get("content_sha256")
    if declared_identity_hash is not None and declared_identity_hash != calculated_identity_hash:
        raise ValueError("runtime capture identity content hash is invalid")
    if (
        source_capture_identity["capture_id"] != capture_id
        or source_capture_identity["screenshot_sha256"] != screenshot_sha256
        or source_capture_identity["artifact_ref"] != dict(artifact_ref)
        or source_capture_identity["capture_identity_content_sha256"]
        != calculated_identity_hash
    ):
        raise ValueError("native grounding source capture does not match runtime capture")


def bind_native_grounding_output(
    raw: object,
    *,
    provider_format: str,
    coordinate_space: str,
    source_image_size: tuple[int, int],
    runtime_request: Mapping[str, object],
    source_capture_identity: Mapping[str, object],
    goal_index: int,
    confidence: float,
) -> dict[str, object]:
    """把原生点确定性映射为一个 active Omni candidate，失败时不猜测。

    candidate bbox 只接受严格内部命中，边界点不绑定。模型不能提供 role、label、
    candidate identity 或新的几何；这些字段只继承自同截图的 runtime request。
    """
    if provider_format not in _NATIVE_GROUNDING_FORMATS:
        raise ValueError("native provider_format is unsupported")
    goals, candidates, image_size = _runtime_goal_binding_request(runtime_request)
    if isinstance(goal_index, bool) or not isinstance(goal_index, int) or not 0 <= goal_index < len(goals):
        raise ValueError("native grounding goal_index is invalid")
    goal = goals[goal_index]
    try:
        if (
            not isinstance(source_image_size, tuple)
            or len(source_image_size) != 2
            or any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in source_image_size)
            or source_image_size != image_size
        ):
            raise ValueError("native grounding source image does not match capture")
        _verify_source_capture_identity(
            source_capture_identity=source_capture_identity,
            runtime_request=runtime_request,
            image_size=image_size,
        )
        validated_confidence = _number(
            confidence, field="native grounding confidence", low=0.0, high=1.0
        )
        capture_point = _capture_point(
            _native_grounding_point(
                raw,
                provider_format=provider_format,
                coordinate_space=coordinate_space,
                image_size=image_size,
            ),
            coordinate_space=coordinate_space,
            image_size=image_size,
        )
    except ValueError:
        return _native_binding_result(
            goal_index=goal_index,
            goal=goal,
            status="PROVIDER_FAILURE",
            confidence=0.0,
            capture_point=None,
        )

    x, y = capture_point
    hits: list[tuple[int, Mapping[str, object]]] = []
    for candidate_index, candidate in enumerate(candidates):
        if not candidate["active"]:
            continue
        x1, y1, x2, y2 = candidate["bbox_original"]  # type: ignore[misc]
        if x1 < x < x2 and y1 < y < y2:
            hits.append((candidate_index, candidate))
    if len(hits) != 1:
        return _native_binding_result(
            goal_index=goal_index,
            goal=goal,
            status="UNBOUND",
            confidence=validated_confidence,
            capture_point=capture_point,
        )
    candidate_index, candidate = hits[0]
    return _native_binding_result(
        goal_index=goal_index,
        goal=goal,
        status="BOUND",
        confidence=validated_confidence,
        capture_point=capture_point,
        candidate_index=candidate_index,
        candidate_id=str(candidate["candidate_id"]),
    )

def parse_vista_normalized_point(raw_text: str) -> tuple[float, float]:
    """只接受 VISTA 的 bare `[x,y]` 文本，禁止 JSON envelope/prose。"""
    if not isinstance(raw_text, str):
        raise ValueError("VISTA native response must be text")
    decoder = json.JSONDecoder()
    try:
        value, end = decoder.raw_decode(raw_text.lstrip())
    except json.JSONDecodeError as exc:
        raise ValueError("VISTA native response is not a bare pair") from exc
    if raw_text.lstrip()[end:].strip() or not isinstance(value, list) or len(value) != 2:
        raise ValueError("VISTA native response is not a bare pair")
    return tuple(_number(point, field="VISTA normalized point", low=0.0, high=1000.0) for point in value)  # type: ignore[return-value]


def restore_vista_point_to_capture(point: tuple[float, float], *, roi_xyxy: tuple[int, int, int, int]) -> tuple[int, int]:
    """按 ROI 原点恢复点；拒绝越界，绝不裁剪或纠正。"""
    if not isinstance(roi_xyxy, tuple) or len(roi_xyxy) != 4 or any(isinstance(value, bool) or not isinstance(value, int) for value in roi_xyxy):
        raise ValueError("VISTA ROI is invalid")
    x1, y1, x2, y2 = roi_xyxy
    if not x1 < x2 or not y1 < y2:
        raise ValueError("VISTA ROI is invalid")
    px, py = (_number(value, field="VISTA normalized point", low=0.0, high=1000.0) for value in point)
    x = round(x1 + (x2 - x1) * px / 1000.0)
    y = round(y1 + (y2 - y1) * py / 1000.0)
    if not x1 <= x <= x2 or not y1 <= y <= y2:
        raise ValueError("VISTA point is outside ROI")
    return x, y
