"""审核文本来源与本次解析值分离，冻结后不再读取外部变量。"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
import re
from typing import Any, Mapping


TEXT_PARAMETERS_CONTRACT = "reviewed_text_parameters_v1"
TEXT_SEMANTIC_ACTION = "fill_field"
MAX_TEXT_LENGTH = 32768
_VARIABLE_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,127}\Z")


def validate_text_value(value: object) -> str:
    if not isinstance(value, str) or len(value) > MAX_TEXT_LENGTH:
        raise ValueError("text must be a string of at most 32768 characters")
    if any((ord(char) < 32 and char not in "\t\n\r") or 0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise ValueError("text contains unsupported control or surrogate characters")
    return value


@dataclass(frozen=True, slots=True)
class ReviewedTextSource:
    kind: str
    value: str = field(repr=False)

    def __post_init__(self) -> None:
        if self.kind == "literal":
            validate_text_value(self.value)
        elif self.kind == "variable":
            if not isinstance(self.value, str) or _VARIABLE_NAME.fullmatch(self.value) is None:
                raise ValueError("text variable name is invalid")
        else:
            raise ValueError("text content requires literal or variable kind")

    @classmethod
    def from_payload(cls, payload: object) -> ReviewedTextSource:
        if not isinstance(payload, Mapping):
            raise ValueError("text content fields are invalid")
        key = "text" if payload.get("kind") == "literal" else "name"
        if set(payload) != {"kind", key}:
            raise ValueError("text content fields are invalid")
        return cls(kind=payload["kind"], value=payload[key])

    def to_payload(self) -> dict[str, str]:
        return {"kind": self.kind, "text" if self.kind == "literal" else "name": self.value}


@dataclass(frozen=True, slots=True)
class ReviewedTextParameters:
    target_field_id: str
    content: ReviewedTextSource = field(repr=False)
    clear_existing: bool
    sensitive: bool
    submit: bool = False
    clipboard_policy: str = "restore_previous"

    def __post_init__(self) -> None:
        if not isinstance(self.target_field_id, str) or not self.target_field_id.strip() or len(self.target_field_id) > 256:
            raise ValueError("text requires a bounded target field identity")
        if type(self.content) is not ReviewedTextSource:
            raise ValueError("text requires an immutable reviewed source")
        if type(self.clear_existing) is not bool or type(self.sensitive) is not bool:
            raise ValueError("text clear_existing and sensitive must be booleans")
        if self.submit is not False:
            raise ValueError("text entry cannot submit")
        if self.clipboard_policy != "restore_previous":
            raise ValueError("text entry requires restore_previous clipboard policy")

    @classmethod
    def from_payload(cls, payload: object) -> ReviewedTextParameters:
        keys = {"contract_version", "target_field_id", "content", "clear_existing", "sensitive", "submit", "clipboard_policy"}
        if not isinstance(payload, Mapping) or set(payload) != keys:
            raise ValueError("reviewed text parameter fields are invalid")
        if payload["contract_version"] != TEXT_PARAMETERS_CONTRACT:
            raise ValueError("reviewed text parameter version is unsupported")
        return cls(
            target_field_id=payload["target_field_id"], content=ReviewedTextSource.from_payload(payload["content"]),
            clear_existing=payload["clear_existing"], sensitive=payload["sensitive"],
            submit=payload["submit"], clipboard_policy=payload["clipboard_policy"],
        )

    def to_payload(self) -> dict[str, Any]:
        return {"contract_version": TEXT_PARAMETERS_CONTRACT, "target_field_id": self.target_field_id,
                "content": self.content.to_payload(), "clear_existing": self.clear_existing,
                "sensitive": self.sensitive, "submit": self.submit, "clipboard_policy": self.clipboard_policy}


@dataclass(frozen=True, slots=True)
class ResolvedTextParameters:
    reviewed: ReviewedTextParameters = field(repr=False)
    text: str = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.reviewed) is not ReviewedTextParameters:
            raise ValueError("resolved text requires typed reviewed parameters")
        validate_text_value(self.text)
        if self.reviewed.content.kind == "literal" and self.text != self.reviewed.content.value:
            raise ValueError("resolved text does not match reviewed literal")


def resolve_text_parameters(reviewed: ReviewedTextParameters, variables: Mapping[str, str]) -> ResolvedTextParameters:
    if type(reviewed) is not ReviewedTextParameters or not isinstance(variables, Mapping):
        raise ValueError("text resolution requires reviewed parameters and a variable mapping")
    source = reviewed.content
    if source.kind == "literal":
        value = source.value
    else:
        if source.value not in variables:
            raise ValueError(f"required text variable is missing: {source.value}")
        value = variables[source.value]
    return ResolvedTextParameters(reviewed=reviewed, text=validate_text_value(value))


def validate_text_review_subject(subject: Mapping[str, Any]) -> None:
    semantic = subject.get("semantic_action") or subject.get("action_type")
    if semantic != TEXT_SEMANTIC_ACTION:
        if "text_parameters" in subject:
            raise ValueError("non-text review subject cannot carry text parameters")
        return
    parameters = ReviewedTextParameters.from_payload(subject.get("text_parameters"))
    control, region = subject.get("target_control_id"), subject.get("target_region_id")
    if bool(control) == bool(region) or parameters.target_field_id != (control or region):
        raise ValueError("text parameters must reference the reviewed target field")


def _finite_number(value: object) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def validate_text_dispatch_geometry(
    target_bbox: tuple[float, float, float, float],
    viewport_size: tuple[int, int],
    point: tuple[float, float] | None = None,
) -> None:
    """校验填写定位的视口、半开边界与实际整数像素。"""
    if type(viewport_size) is not tuple or len(viewport_size) != 2 or any(type(value) is not int or value <= 0 for value in viewport_size):
        raise ValueError("text dispatch requires an immutable positive viewport")
    if type(target_bbox) is not tuple or len(target_bbox) != 4 or not all(_finite_number(value) for value in target_bbox):
        raise ValueError("text dispatch requires an immutable finite target bbox")
    x, y, width, height = target_bbox
    if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > viewport_size[0] or y + height > viewport_size[1]:
        raise ValueError("text target bbox must be inside the current viewport")
    if point is None:
        return
    if type(point) is not tuple or len(point) != 2 or not all(_finite_number(value) for value in point):
        raise ValueError("text dispatch point must be finite and immutable")
    # 同时核对识别点和真正派发的整数像素，拒绝右/下半开边界外的截断。
    if not all(x <= px < x + width and y <= py < y + height for px, py in (point, (int(point[0]), int(point[1])))):
        raise ValueError("text dispatch point must be inside the current target bbox")


@dataclass(frozen=True, slots=True)
class TextDispatchParameters:
    parameters: ResolvedTextParameters = field(repr=False)
    target_bbox: tuple[float, float, float, float]
    viewport_size: tuple[int, int]

    def __post_init__(self) -> None:
        if type(self.parameters) is not ResolvedTextParameters:
            raise ValueError("dispatch requires typed resolved text parameters")
        validate_text_dispatch_geometry(self.target_bbox, self.viewport_size)

    def validate_point(self, point: tuple[float, float]) -> None:
        validate_text_dispatch_geometry(self.target_bbox, self.viewport_size, point)


TEXT_PARAMETER_REFERENCE_CONTRACT = "reviewed_text_reference_v1"

def _text_reference_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")

def text_parameter_reference(reviewed: ReviewedTextParameters) -> dict[str, Any]:
    """生成不含原文或解析值的审核声明引用。"""
    if type(reviewed) is not ReviewedTextParameters:
        raise ValueError("text reference requires typed reviewed parameters")
    source = reviewed.content
    return {
        "contract_version": TEXT_PARAMETER_REFERENCE_CONTRACT,
        "parameters_sha256": hashlib.sha256(_text_reference_bytes(reviewed.to_payload())).hexdigest(),
        "target_field_id": reviewed.target_field_id,
        "source_kind": source.kind,
        "variable_name": source.value if source.kind == "variable" else None,
        "clear_existing": reviewed.clear_existing,
        "sensitive": reviewed.sensitive,
        "submit": False,
        "clipboard_policy": "restore_previous",
    }

def validate_text_parameter_reference(payload: object) -> dict[str, Any]:
    keys = {"contract_version", "parameters_sha256", "target_field_id", "source_kind", "variable_name", "clear_existing", "sensitive", "submit", "clipboard_policy"}
    if not isinstance(payload, Mapping) or set(payload) != keys:
        raise ValueError("text reference fields are invalid")
    value = dict(payload)
    if value["contract_version"] != TEXT_PARAMETER_REFERENCE_CONTRACT:
        raise ValueError("text reference version is unsupported")
    if not isinstance(value["parameters_sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", value["parameters_sha256"]) is None:
        raise ValueError("text reference hash is invalid")
    if not isinstance(value["target_field_id"], str) or not value["target_field_id"].strip() or len(value["target_field_id"]) > 256:
        raise ValueError("text reference field identity is invalid")
    if value["source_kind"] not in {"literal", "variable"}:
        raise ValueError("text reference source kind is invalid")
    variable_name = value["variable_name"]
    if value["source_kind"] == "variable":
        if not isinstance(variable_name, str) or _VARIABLE_NAME.fullmatch(variable_name) is None:
            raise ValueError("text reference variable name is invalid")
    elif variable_name is not None:
        raise ValueError("literal text reference cannot expose a variable name")
    if type(value["clear_existing"]) is not bool or type(value["sensitive"]) is not bool:
        raise ValueError("text reference flags are invalid")
    if value["submit"] is not False or value["clipboard_policy"] != "restore_previous":
        raise ValueError("text reference safety policy is invalid")
    return value

def text_parameter_fields(subject: Mapping[str, Any], *, semantic_action: str | None = None) -> dict[str, Any]:
    """仅填写动作投影声明引用，禁止公开文本来源或解析值。"""
    semantic = subject.get("semantic_action") if semantic_action is None else semantic_action
    has_parameters = "text_parameters" in subject
    has_reference = "text_parameters_ref" in subject
    if semantic != TEXT_SEMANTIC_ACTION:
        if has_parameters or has_reference:
            raise ValueError("non-text contract cannot carry text parameters")
        return {}
    if has_parameters == has_reference:
        raise ValueError("text contract requires exactly one parameter declaration")
    if has_parameters:
        return {"text_parameters_ref": text_parameter_reference(ReviewedTextParameters.from_payload(subject["text_parameters"]))}
    return {"text_parameters_ref": validate_text_parameter_reference(subject["text_parameters_ref"])}
