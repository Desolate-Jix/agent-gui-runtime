"""不可信视觉定位输出的轻量、无输入副作用的边界契约。"""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from pydantic import (BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError,
    field_validator, model_serializer, model_validator)


class _StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class ImageSize(_StrictModel):
    width: StrictInt = Field(gt=0)
    height: StrictInt = Field(gt=0)


class BoundingBox(_StrictModel):
    x: StrictInt = Field(ge=0)
    y: StrictInt = Field(ge=0)
    width: StrictInt = Field(gt=0)
    height: StrictInt = Field(gt=0)


class ClickPoint(_StrictModel):
    x: StrictInt = Field(ge=0)
    y: StrictInt = Field(ge=0)


class GroundingCandidate(_StrictModel):
    id: StrictStr = Field(min_length=1)
    label: StrictStr = Field(min_length=1)
    bbox: BoundingBox = Field(description="Real target bounding box. For an input field, cover the entire visible input field, "
        "including its existing text area, even when the requested click is in a blank or other clickable subregion.")
    click_point: ClickPoint = Field(description="Point inside bbox chosen independently for the requested clickable subregion, "
        "not necessarily the bbox center.")
    evidence_source: Literal["agent_visual", "api_visual", "local_visual"]
    confidence: float | None = Field(default=None, strict=True, ge=0, le=1, allow_inf_nan=False)


IdentityOption = Annotated[StrictStr, Field(min_length=1, max_length=4000)]


class TargetDescription(_StrictModel):
    kind: Literal["graphic", "input_field"]
    appearance: StrictStr = Field(min_length=1, max_length=1000)
    container: StrictStr = Field(min_length=1, max_length=1000)

    @field_validator("appearance", "container")
    @classmethod
    def validate_description_text(cls, value):
        if not value.strip():
            raise ValueError("target_description text must be non-empty")
        return value


class GroundingResult(_StrictModel):
    schema_version: Literal["grounding.v1"]
    request_id: StrictStr = Field(min_length=1)
    capture_id: StrictStr = Field(min_length=1)
    status: Literal["found", "absent", "ambiguous", "unsupported", "error"]
    coordinate_space: Literal["capture_image_pixels"]
    image_size: ImageSize
    candidates: list[GroundingCandidate]
    selected_candidate_id: StrictStr | None
    identity_options: list[IdentityOption] | None = Field(default=None, min_length=1, max_length=7,
        description="Concrete neutral, mutually exclusive descriptions of visually confusable alternative UI identities, "
            "excluding the requested goal. Not expected IDs, correctness labels or an identity answer; found status only.")
    target_description: TargetDescription | None = Field(default=None,
        description="Unverified locator description of the found object's visible appearance and containing UI region. "
            "Not a replacement goal, expected identity, set of options or correctness answer; found status only.")

    @field_validator("identity_options")
    @classmethod
    def validate_identity_options(cls, value):
        if value is None:
            return value
        keys = ["".join(item.split()).casefold() for item in value]
        reserved = {"expected", "correct", "incorrect", "right", "wrong", "yes", "no", "true", "false",
            "pass", "fail", "condition_met", "condition_not_met", "evidence_insufficient", "other", "unknown",
            "正确", "错误", "是", "否", "对", "错"}
        if any(not key or key in reserved for key in keys) or len(set(keys)) != len(keys):
            raise ValueError("identity_options must contain distinct concrete neutral descriptions")
        return value

    @model_serializer(mode="wrap")
    def serialize_optional_locator_context(self, serializer):
        value = serializer(self)
        # 旧定位和委派结果省略新字段，既有摘要与持久化形状保持原样。
        for field in ("identity_options", "target_description"):
            if field not in self.model_fields_set:
                value.pop(field, None)
        return value

    @model_validator(mode="after")
    def validate_consistency(self) -> GroundingResult:
        if self.status != "found" and self.identity_options is not None:
            raise ValueError("identity_options require found status")
        if self.status != "found" and self.target_description is not None:
            raise ValueError("target_description requires found status")
        ids = [candidate.id for candidate in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("candidate IDs must be unique")
        for candidate in self.candidates:
            box = candidate.bbox
            point = candidate.click_point
            if box.x + box.width > self.image_size.width or box.y + box.height > self.image_size.height:
                raise ValueError("candidate bbox exceeds image_size")
            if not (box.x <= point.x < box.x + box.width and box.y <= point.y < box.y + box.height):
                raise ValueError("candidate click_point is outside bbox")
        if self.status == "found":
            if self.selected_candidate_id is None or self.selected_candidate_id not in ids:
                raise ValueError("found requires a selected candidate ID present in candidates")
        elif self.status == "ambiguous":
            if len(ids) < 2 or self.selected_candidate_id is not None:
                raise ValueError("ambiguous requires at least two candidates and no selection")
        elif self.candidates or self.selected_candidate_id is not None:
            raise ValueError("non-target status requires no candidates or selection")
        return self


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_nonfinite(token: str) -> None:
    raise ValueError("non-finite JSON number is not permitted")


def validate_grounding_result(
    payload: dict[str, Any] | str,
    *,
    request_id: str,
    capture_id: str,
    image_size: tuple[int, int],
) -> GroundingResult:
    """解析模型输出并与运行时可信的请求、截图和尺寸核对。"""
    if type(payload) is str:
        try:
            payload = json.loads(
                payload,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_nonfinite,
            )
        except (ValueError, TypeError) as exc:
            raise ValueError(f"grounding JSON invalid: {exc}") from None
    if type(payload) is not dict:
        raise ValueError("grounding payload must be a dict or raw JSON object")
    try:
        result = GroundingResult.model_validate(payload)
    except ValidationError as exc:
        issues = []
        for issue in exc.errors():
            location = ".".join(map(str, issue["loc"])) or "result"
            detail = str(issue.get("ctx", {}).get("error", "")) if issue["type"] == "value_error" else issue["type"]
            issues.append(location + ": " + detail)
        raise ValueError("grounding schema invalid: " + "; ".join(issues)) from None
    if result.request_id != request_id:
        raise ValueError("grounding request_id does not match runtime request")
    if result.capture_id != capture_id:
        raise ValueError("grounding capture_id does not match runtime capture")
    if (result.image_size.width, result.image_size.height) != image_size:
        raise ValueError("grounding image_size does not match runtime capture")
    return result
