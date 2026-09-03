"""Pure, independent model-native contracts for the five-screen diagnostic."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
import math
from collections.abc import Mapping
from typing import Any


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
    return {"contract_version": "hybrid_qwen_bindings_v1", "bindings": expanded}


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
