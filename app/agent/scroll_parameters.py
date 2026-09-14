"""审核滚轮参数与当前容器几何分离，二者均不能产生输入权限。"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping


SCROLL_PARAMETERS_CONTRACT = "reviewed_scroll_parameters_v1"
SCROLL_SEMANTIC_ACTION = "scroll_region"


def _finite_number(value: object) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


@dataclass(frozen=True, slots=True)
class ReviewedScrollParameters:
    target_container_id: str
    axis: str
    direction: str
    wheel_clicks: int
    unit: str

    def __post_init__(self) -> None:
        if not isinstance(self.target_container_id, str) or not self.target_container_id.strip() or len(self.target_container_id) > 256:
            raise ValueError("scroll requires a bounded target container identity")
        if self.axis != "vertical" or self.direction not in ("up", "down") or self.unit != "wheel_detent":
            raise ValueError("scroll requires explicit vertical up/down wheel_detent parameters")
        if type(self.wheel_clicks) is not int or not 1 <= self.wheel_clicks <= 20:
            raise ValueError("scroll wheel_clicks must be an integer from 1 through 20")

    @classmethod
    def from_payload(cls, payload: object) -> ReviewedScrollParameters:
        if not isinstance(payload, Mapping) or set(payload) != {"contract_version", "target_container_id", "axis", "direction", "wheel_clicks", "unit"}:
            raise ValueError("reviewed scroll parameter fields are invalid")
        if payload["contract_version"] != SCROLL_PARAMETERS_CONTRACT:
            raise ValueError("reviewed scroll parameter version is unsupported")
        return cls(**{key: value for key, value in payload.items() if key != "contract_version"})

    def to_payload(self) -> dict[str, Any]:
        return {"contract_version": SCROLL_PARAMETERS_CONTRACT, "target_container_id": self.target_container_id,
                "axis": self.axis, "direction": self.direction, "wheel_clicks": self.wheel_clicks, "unit": self.unit}


@dataclass(frozen=True, slots=True)
class ScrollDispatchParameters:
    parameters: ReviewedScrollParameters
    target_bbox: tuple[float, float, float, float]
    viewport_size: tuple[int, int]

    def __post_init__(self) -> None:
        if type(self.parameters) is not ReviewedScrollParameters:
            raise ValueError("dispatch requires typed reviewed scroll parameters")
        if type(self.viewport_size) is not tuple or len(self.viewport_size) != 2 or any(type(v) is not int or v <= 0 for v in self.viewport_size):
            raise ValueError("scroll dispatch requires an immutable positive viewport")
        if type(self.target_bbox) is not tuple or len(self.target_bbox) != 4 or not all(_finite_number(v) for v in self.target_bbox):
            raise ValueError("scroll dispatch requires an immutable finite target bbox")
        x, y, width, height = self.target_bbox
        if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > self.viewport_size[0] or y + height > self.viewport_size[1]:
            raise ValueError("scroll target bbox must be inside the current viewport")

    def validate_point(self, point: tuple[float, float]) -> None:
        if type(point) is not tuple or len(point) != 2 or not all(_finite_number(value) for value in point):
            raise ValueError("scroll dispatch point must be finite and immutable")
        x, y, width, height = self.target_bbox
        # 既核对识别点，也核对真正送入 Windows 的整数像素，拒绝截断后越界。
        if not all(x <= px < x + width and y <= py < y + height for px, py in (point, (int(point[0]), int(point[1])))):
            raise ValueError("scroll dispatch point must be inside the current target bbox")


def validate_scroll_review_subject(subject: Mapping[str, Any]) -> None:
    semantic = subject.get("semantic_action") or subject.get("action_type")
    if semantic != SCROLL_SEMANTIC_ACTION:
        if "scroll_parameters" in subject:
            raise ValueError("non-scroll review subject cannot carry scroll parameters")
        return
    parameters = ReviewedScrollParameters.from_payload(subject.get("scroll_parameters"))
    if subject.get("target_control_id") or parameters.target_container_id != subject.get("target_region_id"):
        raise ValueError("scroll parameters must reference the reviewed target region")


def scroll_parameter_fields(subject: Mapping[str, Any], *, semantic_action: str | None = None) -> dict[str, Any]:
    """仅滚动附加规范参数副本；旧动作不增加空字段。"""
    semantic = subject.get("semantic_action") if semantic_action is None else semantic_action
    if semantic != SCROLL_SEMANTIC_ACTION:
        if "scroll_parameters" in subject:
            raise ValueError("non-scroll contract cannot carry scroll parameters")
        return {}
    parameters = ReviewedScrollParameters.from_payload(subject.get("scroll_parameters"))
    return {"scroll_parameters": parameters.to_payload()}


def validate_scroll_grounding_geometry(subject: Mapping[str, Any], grounding: Mapping[str, Any]) -> None:
    """预览与后端共用半开边界及整数像素校验。"""
    fields = scroll_parameter_fields(subject)
    if not fields:
        return
    try:
        bbox, point, viewport = grounding["bbox"], grounding["click_point"], grounding["viewport_size"]
        spatial = ScrollDispatchParameters(
            parameters=ReviewedScrollParameters.from_payload(fields["scroll_parameters"]),
            target_bbox=tuple(bbox[key] for key in ("x", "y", "w", "h")),
            viewport_size=(viewport["width"], viewport["height"]),
        )
        spatial.validate_point((point["x"], point["y"]))
    except (KeyError, TypeError) as exc:
        raise ValueError("scroll grounding geometry is invalid") from exc
