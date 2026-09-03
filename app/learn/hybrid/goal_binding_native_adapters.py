"""封闭的 provider 原生落点解析器，不授予任何执行权限。

原始 UTF-8 输出由 Task 7 的 ``goal_binding_model_callers.py`` 留存为调用 trace；
本模块按 Task 2 合同只产生 ``NativePointProposal``，绝不伪造 trace 字段。
"""

from __future__ import annotations

from collections.abc import Mapping
import json
import math

from app.learn.hybrid.goal_binding_provider import NativePointProposal


_PROFILE_VERSION = "goal_binding_native_profile_v1"
_MAX_GOAL_INDEX = 1_000_000
_COORDINATE_SPACES = frozenset(
    {"normalized_0_1", "normalized_0_1000", "capture_pixels"}
)
_BASE_PROFILE_FIELDS = frozenset(
    {"contract_version", "provider_id", "native_shape", "coordinate_space"}
)


def _require_goal_index(value: object) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= _MAX_GOAL_INDEX
    ):
        raise ValueError("native goal_index is invalid")
    return value


def _require_profile(
    profile: Mapping[str, object], *, native_shape: str, extra_fields: frozenset[str] = frozenset()
) -> tuple[str, tuple[int, int] | None]:
    if not isinstance(profile, Mapping):
        raise ValueError("native provider profile is not sealed")
    coordinate_space = profile.get("coordinate_space")
    required_fields = _BASE_PROFILE_FIELDS | extra_fields
    if coordinate_space == "capture_pixels":
        required_fields |= {"image_size"}
    if set(profile) != required_fields:
        raise ValueError("native provider profile is not sealed")
    if (
        profile["contract_version"] != _PROFILE_VERSION
        or not isinstance(profile["provider_id"], str)
        or not profile["provider_id"].strip()
        or profile["native_shape"] != native_shape
        or not isinstance(coordinate_space, str)
        or coordinate_space not in _COORDINATE_SPACES
    ):
        raise ValueError("native provider profile is invalid")
    if coordinate_space != "capture_pixels":
        return coordinate_space, None
    image_size = profile["image_size"]
    if (
        not isinstance(image_size, list)
        or len(image_size) != 2
        or any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in image_size)
    ):
        raise ValueError("native capture-pixel profile image_size is invalid")
    try:
        if not all(math.isfinite(float(value)) for value in image_size):
            raise ValueError("native capture-pixel profile image_size is invalid")
    except OverflowError as exc:
        raise ValueError("native capture-pixel profile image_size is invalid") from exc
    return coordinate_space, (image_size[0], image_size[1])


def _failure(*, goal_index: int, coordinate_space: str) -> NativePointProposal:
    return NativePointProposal(
        goal_index=goal_index,
        point=None,
        coordinate_space=coordinate_space,
        confidence=None,
        status="PROVIDER_FAILURE",
        failure_reason="malformed_native_output",
    )


def _number(value: object, *, field: str, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be finite")
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{field} must be finite") from exc
    if not math.isfinite(number) or not 0.0 <= number <= high:
        raise ValueError(f"{field} is outside the sealed coordinate space")
    return number


def _coordinate_limits(
    coordinate_space: str, image_size: tuple[int, int] | None
) -> tuple[float, float]:
    if coordinate_space == "normalized_0_1":
        return 1.0, 1.0
    if coordinate_space == "normalized_0_1000":
        return 1000.0, 1000.0
    if image_size is None:
        raise ValueError("capture-pixel profile image_size is missing")
    return float(image_size[0]), float(image_size[1])


def _pair(
    value: object, *, field: str, coordinate_space: str, image_size: tuple[int, int] | None
) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{field} must be a pair")
    x_high, y_high = _coordinate_limits(coordinate_space, image_size)
    point = (
        _number(value[0], field=f"{field} x", high=x_high),
        _number(value[1], field=f"{field} y", high=y_high),
    )
    if coordinate_space == "capture_pixels" and (point[0] >= x_high or point[1] >= y_high):
        raise ValueError(f"{field} is outside the sealed capture")
    return point


def _bbox_center(
    value: object, *, coordinate_space: str, image_size: tuple[int, int] | None
) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError("Phi-Ground bbox must contain four coordinates")
    x_high, y_high = _coordinate_limits(coordinate_space, image_size)
    x1 = _number(value[0], field="Phi-Ground bbox x1", high=x_high)
    y1 = _number(value[1], field="Phi-Ground bbox y1", high=y_high)
    x2 = _number(value[2], field="Phi-Ground bbox x2", high=x_high)
    y2 = _number(value[3], field="Phi-Ground bbox y2", high=y_high)
    if not x1 < x2 or not y1 < y2:
        raise ValueError("Phi-Ground bbox is degenerate")
    center = (x1 + (x2 - x1) / 2.0, y1 + (y2 - y1) / 2.0)
    if not all(math.isfinite(part) for part in center):
        raise ValueError("Phi-Ground bbox center is invalid")
    return center


def _closed_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("native text has duplicate object keys")
        value[key] = item
    return value


def _parse_text(raw: str) -> object:
    decoder = json.JSONDecoder(object_pairs_hook=_closed_object)
    value, end = decoder.raw_decode(raw.lstrip())
    if raw.lstrip()[end:].strip():
        raise ValueError("native text has trailing prose")
    return value


def _structured_raw(raw: object) -> object:
    if isinstance(raw, str):
        return _parse_text(raw)
    return raw


def _ok(*, goal_index: int, point: tuple[float, float], coordinate_space: str) -> NativePointProposal:
    return NativePointProposal(
        goal_index=goal_index,
        point=point,
        coordinate_space=coordinate_space,
        confidence=None,
        status="OK",
        failure_reason=None,
    )


def parse_ui_venus_point(
    raw: object, *, goal_index: int, profile: Mapping[str, object]
) -> NativePointProposal:
    """Accept exactly UI-Venus's one bare point or its explicit [-1,-1] abstention."""
    goal_index = _require_goal_index(goal_index)
    coordinate_space, image_size = _require_profile(profile, native_shape="ui_venus_point_v1")
    try:
        value = _structured_raw(raw)
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError("UI-Venus output is not one bare point")
        if value == [-1, -1]:
            return _failure(goal_index=goal_index, coordinate_space=coordinate_space)
        return _ok(goal_index=goal_index, point=_pair(value, field="UI-Venus point", coordinate_space=coordinate_space, image_size=image_size), coordinate_space=coordinate_space)
    except (ValueError, json.JSONDecodeError, TypeError):
        return _failure(goal_index=goal_index, coordinate_space=coordinate_space)


def parse_gui_actor_top1(
    raw: object, *, goal_index: int, profile: Mapping[str, object]
) -> NativePointProposal:
    """只使用 GUI-Actor 的 ``topk_points[0]``；后续项保留给调用 trace。"""
    goal_index = _require_goal_index(goal_index)
    coordinate_space, image_size = _require_profile(profile, native_shape="gui_actor_topk_points_v1")
    try:
        value = _structured_raw(raw)
        if (
            not isinstance(value, Mapping)
            or set(value) != {"topk_points"}
            or not isinstance(value["topk_points"], list)
            or not value["topk_points"]
        ):
            raise ValueError("GUI-Actor output is not a non-empty top-k list")
        return _ok(
            goal_index=goal_index,
            point=_pair(
                value["topk_points"][0],
                field="GUI-Actor topk_points[0]",
                coordinate_space=coordinate_space,
                image_size=image_size,
            ),
            coordinate_space=coordinate_space,
        )
    except (ValueError, json.JSONDecodeError, TypeError):
        return _failure(goal_index=goal_index, coordinate_space=coordinate_space)


def parse_phi_ground_any(
    raw: object, *, goal_index: int, profile: Mapping[str, object]
) -> NativePointProposal:
    """只解析 Phi-Ground-Any profile sealed 的 point 或 bbox 模式。"""
    goal_index = _require_goal_index(goal_index)
    coordinate_space, image_size = _require_profile(
        profile, native_shape="phi_ground_any_v1", extra_fields=frozenset({"output_mode"})
    )
    mode = profile["output_mode"]
    if not isinstance(mode, str) or mode not in {"point", "bbox"}:
        raise ValueError("Phi-Ground profile output_mode is invalid")
    try:
        value = _structured_raw(raw)
        if not isinstance(value, Mapping) or set(value) != {mode}:
            raise ValueError("Phi-Ground output does not match the sealed mode")
        point = (
            _pair(value["point"], field="Phi-Ground point", coordinate_space=coordinate_space, image_size=image_size)
            if mode == "point"
            else _bbox_center(value["bbox"], coordinate_space=coordinate_space, image_size=image_size)
        )
        return _ok(goal_index=goal_index, point=point, coordinate_space=coordinate_space)
    except (ValueError, json.JSONDecodeError, TypeError):
        return _failure(goal_index=goal_index, coordinate_space=coordinate_space)


def parse_gguf_grounding(
    raw: object, *, goal_index: int, profile: Mapping[str, object]
) -> NativePointProposal:
    """只接受 sealed GGUF bare JSON 坐标对短格式。"""
    goal_index = _require_goal_index(goal_index)
    coordinate_space, image_size = _require_profile(profile, native_shape="gguf_bare_point_pair_v1")
    try:
        if not isinstance(raw, str):
            raise ValueError("GGUF native output must be text")
        return _ok(
            goal_index=goal_index,
            point=_pair(_parse_text(raw), field="GGUF native point", coordinate_space=coordinate_space, image_size=image_size),
            coordinate_space=coordinate_space,
        )
    except (ValueError, json.JSONDecodeError, TypeError):
        return _failure(goal_index=goal_index, coordinate_space=coordinate_space)
