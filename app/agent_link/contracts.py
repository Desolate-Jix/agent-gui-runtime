from __future__ import annotations

import base64
import hashlib
import json
import math
from io import BytesIO
from typing import Annotated, Any, Literal

from PIL import Image, UnidentifiedImageError

from app.agent.scroll_parameters import ReviewedScrollParameters, SCROLL_SEMANTIC_ACTION
from app.agent.text_parameters import validate_text_review_subject
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_serializer, model_validator

CONTRACT_VERSION = "agent_link_v1"
MAX_PNG_BYTES = 2 * 1024 * 1024
MAX_LOCAL_PNG_BYTES = 32 * 1024 * 1024
MAX_LOCAL_IMAGE_RESPONSE_BYTES = 48 * 1024 * 1024
MAX_SCREENSHOT_DIMENSION = 4096


class AgentLinkError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code, self.message = code, message
        super().__init__(message)


def fail(code: str, message: str) -> None:
    raise AgentLinkError(code, message)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class LearnedControlSelectionInput(StrictModel):
    """只接受已保存界面的确切引用，不接受坐标或伪造的服务端摘要。"""

    interface_id: str = Field(min_length=1, max_length=160)
    version_id: str = Field(min_length=1, max_length=160)
    region_id: str = Field(min_length=1, max_length=160)


class InterfaceRelearningRegionChange(StrictModel):
    region_id: str = Field(min_length=1, max_length=160)
    bbox: list[float] | None = Field(default=None, min_length=4, max_length=4)
    name: str | None = Field(default=None, min_length=1, max_length=4000)
    kind: Literal["unknown", "text", "control", "input", "button", "link", "menu", "image", "container", "other"] | None = None
    meaning: str | None = Field(default=None, min_length=1, max_length=4000)
    recognition_text: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def valid_change(self):
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("provided region fields must not be null")
        if self.bbox is not None and (any(not math.isfinite(n) for n in self.bbox)
                or self.bbox[0] < 0 or self.bbox[1] < 0 or self.bbox[2] <= 0 or self.bbox[3] <= 0):
            raise ValueError("bbox must contain finite in-bounds pixel geometry")
        return self


class InterfaceRelearningChanges(StrictModel):
    meaning: str | None = Field(default=None, min_length=1, max_length=4000)
    recognition_text: str | None = Field(default=None, max_length=4000)
    regions: list[InterfaceRelearningRegionChange] | None = Field(default=None, max_length=128,
        description="完整有序的区域列表，不是局部补丁；保留未修改区域时至少列出它们的 region_id。省略的区域将从候选中删除。")

    @model_validator(mode="after")
    def nonempty_changes(self):
        if not self.model_fields_set or any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("provide at least one non-null content change")
        return self


def _canonical_action_type(value: str) -> str:
    # 在入库前统一判定语义，避免后续规范化才发现必填参数缺失。
    if not value or value != value.strip().casefold():
        raise ValueError("action_type must be canonical lowercase without surrounding whitespace")
    return value


class ScreenshotInput(StrictModel):
    screenshot_id: str = Field(min_length=1, max_length=160)
    png_base64: str = Field(min_length=1, max_length=4 * ((MAX_LOCAL_PNG_BYTES + 2) // 3))


class RegionInput(StrictModel):
    region_id: str = Field(min_length=1, max_length=160)
    bbox: list[float] = Field(min_length=4, max_length=4)
    name: str | None = Field(default=None, min_length=1, max_length=4000)
    label: str | None = Field(default=None, min_length=1, max_length=4000)
    type: str | None = Field(default=None, min_length=1, max_length=160)
    kind: str | None = Field(default=None, min_length=1, max_length=160)
    meaning: str = Field(min_length=1, max_length=4000)
    recognition_text: str | None = Field(default=None, max_length=4000, exclude_if=lambda value: value is None)

    @field_validator("bbox")
    @classmethod
    def finite_bbox(cls, value: list[float]) -> list[float]:
        if any(not math.isfinite(number) for number in value):
            raise ValueError("bbox must be finite")
        if value[0] < 0 or value[1] < 0 or value[2] <= 0 or value[3] <= 0:
            raise ValueError("bbox must be positive and in bounds")
        return value

    @model_validator(mode="after")
    def named(self) -> "RegionInput":
        if not any((self.name, self.label, self.type, self.kind)):
            raise ValueError("region needs name, label, type, or kind")
        return self


class ObservedRegionInput(StrictModel):
    """Agent 观察提交的截图像素框；区域 ID 由服务端生成。"""

    bbox: list[float] = Field(min_length=4, max_length=4, description="截图像素 [x, y, width, height]")
    name: str = Field(min_length=1, max_length=4000)
    kind: Literal["unknown", "text", "control", "input", "button", "link", "menu", "image", "container", "other"] = Field(
        description="控件类型；可点击超链接使用 link，纯标题和列表文字使用 text，不能确定时使用 unknown 或 other。"
    )
    meaning: str = Field(min_length=1, max_length=4000)
    recognition_text: str = Field(default="", max_length=4000)

    @field_validator("bbox")
    @classmethod
    def finite_bbox(cls, value: list[float]) -> list[float]:
        if any(not math.isfinite(number) for number in value):
            raise ValueError("bbox must be finite")
        if value[0] < 0 or value[1] < 0 or value[2] <= 0 or value[3] <= 0:
            raise ValueError("bbox must be positive")
        return value


class InterfaceInput(StrictModel):
    interface_id: str = Field(min_length=1, max_length=160)
    screenshot_id: str = Field(min_length=1, max_length=160)
    meaning: str = Field(min_length=1, max_length=4000)
    recognition_text: str | None = Field(default=None, min_length=1, max_length=4000, exclude_if=lambda value: value is None)
    regions: list[RegionInput] = Field(max_length=128)

    @field_validator("recognition_text")
    @classmethod
    def nonblank_recognition_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("recognition_text must not be blank")
        return value


class RelationshipInput(StrictModel):
    relationship_id: str = Field(min_length=1, max_length=160)
    from_interface_id: str = Field(min_length=1, max_length=160)
    to_interface_id: str = Field(min_length=1, max_length=160)
    kind: str = Field(min_length=1, max_length=160)


class StepInput(StrictModel):
    step_id: str = Field(min_length=1, max_length=160)
    action_type: str = Field(min_length=1, max_length=160)
    target_region_id: str | None = Field(default=None, min_length=1, max_length=160)
    start_state: str = Field(min_length=1, max_length=4000)
    arrival_state: str = Field(min_length=1, max_length=4000)
    prerequisites: list[str] = Field(max_length=64)
    expected_result: str = Field(min_length=1, max_length=4000)
    stop_condition: str = Field(min_length=1, max_length=4000)
    scroll_parameters: dict[str, Any] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    text_parameters: dict[str, Any] | None = Field(default=None, exclude_if=lambda value: value is None)
    canonical_action_type = field_validator("action_type")(_canonical_action_type)

    @model_validator(mode="after")
    def reviewed_text_parameters_are_bound(self) -> "StepInput":
        validate_text_review_subject(self.model_dump(exclude_none=True))
        return self

    @model_validator(mode="after")
    def reviewed_scroll_parameters_are_bound(self) -> "StepInput":
        if self.action_type != SCROLL_SEMANTIC_ACTION:
            if self.scroll_parameters is not None:
                raise ValueError("non-scroll step cannot carry scroll parameters")
            return self
        if self.target_region_id is None:
            raise ValueError("scroll step requires a target region")
        try:
            parameters = ReviewedScrollParameters.from_payload(self.scroll_parameters)
        except ValueError as error:
            raise ValueError("scroll step requires reviewed scroll parameters") from error
        if parameters.target_container_id != self.target_region_id:
            raise ValueError("scroll parameters must match the target region")
        return self


class ReportedIssueInput(StrictModel):
    issue_id: str = Field(min_length=1, max_length=160)
    region_id: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=4000)


class BatchInput(StrictModel):
    contract_version: Literal["agent_link_v1"]
    idempotency_key: str = Field(min_length=1, max_length=160)
    batch_id: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=4000)
    learning_outcome: Literal["completed", "partial", "failed", "safety_stop"]
    outcome_reason: str | None = Field(default=None, min_length=1, max_length=4000)
    screenshots: list[ScreenshotInput] = Field(max_length=32)
    interfaces: list[InterfaceInput] = Field(max_length=128)
    relationships: list[RelationshipInput] = Field(max_length=256)
    steps: list[StepInput] = Field(max_length=256)
    issues: list[ReportedIssueInput] = Field(max_length=128)

    @model_validator(mode="after")
    def outcome_evidence(self) -> "BatchInput":
        if self.learning_outcome == "completed" and (not self.screenshots or not self.interfaces):
            raise ValueError("completed batches require evidence")
        if self.learning_outcome != "completed" and not self.outcome_reason:
            raise ValueError("incomplete batches require outcome_reason")
        return self


class ScopeInput(StrictModel):
    interface_ids: list[str] = Field(max_length=128)
    relationship_ids: list[str] = Field(max_length=256)


class GraphScopeInput(StrictModel):
    node_ids: list[str] = Field(max_length=256)
    edge_ids: list[str] = Field(max_length=256)


class NoteInput(StrictModel):
    note_id: str = Field(min_length=1, max_length=160)
    text: str = Field(min_length=1, max_length=4000)


class IssueInput(StrictModel):
    issue_id: str = Field(min_length=1, max_length=160)
    scope: ScopeInput | GraphScopeInput
    message: str = Field(min_length=1, max_length=4000)
    review_baseline: "ReviewBaselineInput | GraphReviewBaselineInput | None" = Field(
        default=None, exclude_if=lambda value: value is None
    )


class ReviewBaselineInput(StrictModel):
    contract_version: Literal["desktop_review_baseline_v1"]
    task_id: str = Field(min_length=1, max_length=4000)
    workspace_revision: int = Field(ge=1)
    source_ref: str = Field(pattern=r"^[0-9a-f]{64}$")
    batch_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    batch: BatchInput


class GraphReviewBaselineInput(StrictModel):
    contract_version: Literal["desktop_graph_review_baseline_v1"]
    task_id: str = Field(min_length=1, max_length=4000)
    batch_id: str = Field(min_length=1, max_length=160)
    logical_workflow_id: str = Field(pattern=r"^workflow-[0-9a-f]{64}$")
    revision: int = Field(ge=1)
    graph_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot: dict[str, Any]


class GraphUpdateEdgeTarget(StrictModel):
    type: Literal["update_edge_target"]
    edge_id: str = Field(min_length=1, max_length=512)
    target_node_id: str = Field(min_length=1, max_length=512)


class GraphUpdateRegionBBox(StrictModel):
    type: Literal["update_region_bbox"]
    node_id: str = Field(min_length=1, max_length=512)
    region_id: str = Field(min_length=1, max_length=512)
    bbox: list[float] = Field(min_length=4, max_length=4)


class GraphUpdateNodeMeaning(StrictModel):
    type: Literal["update_node_meaning"]
    node_id: str = Field(min_length=1, max_length=512)
    meaning: str = Field(min_length=1, max_length=4000)


class GraphUpdateNodeRecognitionText(StrictModel):
    type: Literal["update_node_recognition_text"]
    node_id: str = Field(min_length=1, max_length=512)
    recognition_text: str = Field(min_length=1, max_length=4000)
    source_screenshot_path: str = Field(min_length=1, max_length=4000)
    source_screenshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bbox: list[float] = Field(min_length=4, max_length=4)


class GraphUpdateEdgeSemantics(StrictModel):
    type: Literal["update_edge_semantics"]
    edge_id: str = Field(min_length=1, max_length=512)
    expected_result: str = Field(min_length=1, max_length=4000)
    stop_condition: str = Field(min_length=1, max_length=4000)
    prerequisites: list[ConditionText] = Field(max_length=64)
    relationship_kinds: dict[str, str]


class GeometryChange(StrictModel):
    change_type: Literal["geometry"]
    region_id: str = Field(min_length=1, max_length=160)
    bbox: list[float] = Field(min_length=4, max_length=4)


class RegionsAddChange(StrictModel):
    change_type: Literal["regions_add"]
    interface_id: str = Field(min_length=1, max_length=160)
    regions: list[RegionInput] = Field(min_length=1, max_length=128)


class InterfacesAddChange(StrictModel):
    change_type: Literal["interfaces_add"]
    anchor_interface_id: str = Field(min_length=1, max_length=160)
    screenshots: list[ScreenshotInput] = Field(min_length=1, max_length=32)
    interfaces: list[InterfaceInput] = Field(min_length=1, max_length=128)


class StepsAddChange(StrictModel):
    change_type: Literal["steps_add"]
    after_step_id: str | None = Field(min_length=1, max_length=160)
    steps: list[StepInput] = Field(min_length=1, max_length=256)


class RelationshipsAddChange(StrictModel):
    change_type: Literal["relationships_add"]
    relationships: list[RelationshipInput] = Field(min_length=1, max_length=256)


class SemanticChange(StrictModel):
    change_type: Literal["semantic"]
    target_type: Literal["interface", "region", "relationship", "step"]
    target_id: str = Field(min_length=1, max_length=160)
    meaning: str = Field(min_length=1, max_length=4000)


    recognition_text: str | None = Field(default=None, min_length=1, max_length=4000)

    @model_serializer(mode="wrap")
    def serialize_recognition_presence(self, handler):
        # 缺失表示不修改，显式 null 表示清空；嵌套序列化也必须保留区别。
        payload = handler(self)
        if "recognition_text" in self.model_fields_set:
            payload["recognition_text"] = self.recognition_text
        else:
            payload.pop("recognition_text", None)
        return payload

    @model_validator(mode="after")
    def recognition_text_only_for_interface(self) -> "SemanticChange":
        if "recognition_text" in self.model_fields_set and self.target_type != "interface":
            raise ValueError("recognition_text is only valid for interface semantic changes")
        if self.recognition_text is not None and not self.recognition_text.strip():
            raise ValueError("recognition_text must not be blank")
        return self


class RelationshipChange(StrictModel):
    change_type: Literal["relationship"]
    relationship_id: str = Field(min_length=1, max_length=160)
    kind: str = Field(min_length=1, max_length=160)


class StepChange(StrictModel):
    change_type: Literal["step"]
    step_id: str = Field(min_length=1, max_length=160)
    action_type: str = Field(min_length=1, max_length=160)
    target_region_id: str = Field(min_length=1, max_length=160)
    expected_result: str = Field(min_length=1, max_length=4000)
    scroll_parameters: dict[str, Any] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    text_parameters: dict[str, Any] | None = Field(default=None, exclude_if=lambda value: value is None)
    canonical_action_type = field_validator("action_type")(_canonical_action_type)

    @model_validator(mode="after")
    def reviewed_text_parameters_are_bound(self) -> "StepChange":
        validate_text_review_subject(self.model_dump(exclude_none=True))
        return self

    @model_validator(mode="after")
    def reviewed_scroll_parameters_are_bound(self) -> "StepChange":
        if self.action_type != SCROLL_SEMANTIC_ACTION:
            if self.scroll_parameters is not None:
                raise ValueError("non-scroll step change cannot carry scroll parameters")
            return self
        try:
            parameters = ReviewedScrollParameters.from_payload(self.scroll_parameters)
        except ValueError as error:
            raise ValueError("scroll step change requires reviewed scroll parameters") from error
        if parameters.target_container_id != self.target_region_id:
            raise ValueError("scroll parameters must match the target region")
        return self


ConditionText = Annotated[str, Field(min_length=1, max_length=4000)]


class StepFlowChange(StrictModel):
    change_type: Literal["step_flow"]
    step_id: str = Field(min_length=1, max_length=160)
    action_type: str = Field(min_length=1, max_length=160)
    target_region_id: str | None = Field(default=None, min_length=1, max_length=160)
    start_state: str = Field(min_length=1, max_length=4000)
    arrival_state: str = Field(min_length=1, max_length=4000)
    prerequisites: list[ConditionText] = Field(max_length=64)
    expected_result: str = Field(min_length=1, max_length=4000)
    stop_condition: str = Field(min_length=1, max_length=4000)
    scroll_parameters: dict[str, Any] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    text_parameters: dict[str, Any] | None = Field(default=None, exclude_if=lambda value: value is None)
    canonical_action_type = field_validator("action_type")(_canonical_action_type)

    @model_validator(mode="after")
    def reviewed_text_parameters_are_bound(self) -> "StepFlowChange":
        validate_text_review_subject(self.model_dump(exclude_none=True))
        return self

    @field_validator(
        "action_type", "start_state", "arrival_state", "expected_result",
        "stop_condition",
    )
    @classmethod
    def nonblank_flow_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("flow text must not be blank")
        return value

    @field_validator("prerequisites")
    @classmethod
    def nonblank_prerequisites(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("prerequisites must not contain blank conditions")
        return value

    @model_validator(mode="after")
    def reviewed_scroll_parameters_are_bound(self) -> "StepFlowChange":
        if self.action_type != SCROLL_SEMANTIC_ACTION:
            if self.scroll_parameters is not None:
                raise ValueError("non-scroll step flow cannot carry scroll parameters")
            return self
        if self.target_region_id is None:
            raise ValueError("scroll step flow requires a target region")
        try:
            parameters = ReviewedScrollParameters.from_payload(self.scroll_parameters)
        except ValueError as error:
            raise ValueError("scroll step flow requires reviewed scroll parameters") from error
        if parameters.target_container_id != self.target_region_id:
            raise ValueError("scroll parameters must match the target region")
        return self


class RelationshipFlowChange(StrictModel):
    change_type: Literal["relationship_flow"]
    relationship_id: str = Field(min_length=1, max_length=160)
    from_interface_id: str = Field(min_length=1, max_length=160)
    to_interface_id: str = Field(min_length=1, max_length=160)
    kind: str = Field(min_length=1, max_length=160)


class StepOrderChange(StrictModel):
    change_type: Literal["step_order"]
    step_ids: list[str] = Field(min_length=2, max_length=256)

    @field_validator("step_ids")
    @classmethod
    def unique_step_ids(cls, value: list[str]) -> list[str]:
        if any(not item or len(item) > 160 for item in value) or len(set(value)) != len(value):
            raise ValueError("step_ids must be non-empty, bounded, and unique")
        return value


class CandidateInput(StrictModel):
    contract_version: Literal["agent_link_v1"]
    idempotency_key: str = Field(min_length=1, max_length=160)
    batch_id: str = Field(min_length=1, max_length=160)
    issue_id: str = Field(min_length=1, max_length=160)
    baseline_revision: int = Field(ge=1)
    review_baseline_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
        exclude_if=lambda value: value is None,
    )
    scope: ScopeInput
    changes: list[
        GeometryChange | RegionsAddChange | InterfacesAddChange | StepsAddChange | RelationshipsAddChange | SemanticChange | RelationshipChange | StepChange
        | StepFlowChange | RelationshipFlowChange | StepOrderChange
    ] = Field(min_length=1, max_length=128)


class GraphCandidateInput(StrictModel):
    contract_version: Literal["agent_link_graph_candidate_v1"]
    idempotency_key: str = Field(min_length=1, max_length=160)
    batch_id: str = Field(min_length=1, max_length=160)
    issue_id: str = Field(min_length=1, max_length=160)
    baseline_revision: int = Field(ge=1)
    review_baseline_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    logical_workflow_id: str = Field(pattern=r"^workflow-[0-9a-f]{64}$")
    baseline_graph_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scope: GraphScopeInput
    changes: list[GraphUpdateEdgeTarget | GraphUpdateRegionBBox | GraphUpdateNodeMeaning | GraphUpdateNodeRecognitionText | GraphUpdateEdgeSemantics] = Field(min_length=1, max_length=128)


def parse(model: type[StrictModel], value: Any, name: str) -> dict[str, Any]:
    try:
        result = model.model_validate(value).model_dump(mode="json")
        # 新可选字段缺失时维持既有 agent_link_v1 的持久化与哈希形状。
        if isinstance(value, dict):
            for optional in ("review_baseline", "review_baseline_sha256"):
                if result.get(optional) is None:
                    result.pop(optional, None)
        return result
    except (ValidationError, TypeError, ValueError):
        fail("invalid_arguments", f"{name} does not satisfy the agent_link_v1 contract")


def canonical_hash(value: Any) -> str:
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError):
        fail("invalid_arguments", "arguments are not canonical JSON")
    return hashlib.sha256(encoded).hexdigest()


def validate_batch(value: Any, *, existing_png_sha256: frozenset[str] = frozenset()) -> dict[str, Any]:
    batch = parse(BatchInput, value, "batch")
    dimensions: dict[str, tuple[int, int]] = {}
    for screenshot in batch["screenshots"]:
        if screenshot["screenshot_id"] in dimensions:
            fail("invalid_arguments", "screenshot ids must be unique")
        try:
            raw = base64.b64decode(screenshot["png_base64"], validate=True)
            digest = hashlib.sha256(raw).hexdigest()
            # 大图预算仅由内部已核验原件授予，外部声明不能扩大上传限制。
            limit = MAX_LOCAL_PNG_BYTES if digest in existing_png_sha256 else MAX_PNG_BYTES
            if not raw or len(raw) > limit:
                raise ValueError
            with Image.open(BytesIO(raw)) as image:
                if image.format != "PNG": raise ValueError
                image.verify()
            with Image.open(BytesIO(raw)) as image:
                width, height = image.size
        except (ValueError, TypeError, UnidentifiedImageError, OSError):
            fail("invalid_png", "evidence must be a readable PNG within limits")
        if not 1 <= width <= MAX_SCREENSHOT_DIMENSION or not 1 <= height <= MAX_SCREENSHOT_DIMENSION:
            fail("invalid_png", "PNG dimensions exceed limits")
        screenshot.update(sha256=digest, width=width, height=height)
        dimensions[screenshot["screenshot_id"]] = (width, height)
    interface_ids, region_ids = set(), set()
    for interface in batch["interfaces"]:
        if interface["interface_id"] in interface_ids or interface["screenshot_id"] not in dimensions:
            fail("invalid_reference", "interface ids and screenshots must be valid")
        interface_ids.add(interface["interface_id"])
        width, height = dimensions[interface["screenshot_id"]]
        for region in interface["regions"]:
            if region["region_id"] in region_ids:
                fail("invalid_reference", "region ids must be unique")
            x, y, box_width, box_height = region["bbox"]
            if x + box_width > width or y + box_height > height:
                fail("invalid_bbox", "region bbox is outside its screenshot")
            region_ids.add(region["region_id"])
    relationship_ids = set()
    for relation in batch["relationships"]:
        if relation["relationship_id"] in relationship_ids or relation["from_interface_id"] not in interface_ids or relation["to_interface_id"] not in interface_ids:
            fail("invalid_reference", "relationship reference is invalid")
        relationship_ids.add(relation["relationship_id"])
    step_ids = set()
    interfaces_by_region = {region["region_id"]: interface["interface_id"] for interface in batch["interfaces"] for region in interface["regions"]}
    for step in batch["steps"]:
        if step["step_id"] in step_ids or step["start_state"] not in interface_ids or step["arrival_state"] not in interface_ids:
            fail("invalid_reference", "step ids and states must reference interfaces")
        step_ids.add(step["step_id"])
        if step["action_type"] in {"safe_stop", "observe"}:
            if step["target_region_id"] is not None and step["target_region_id"] not in region_ids: fail("invalid_reference", "optional stop target is invalid")
        elif step["target_region_id"] not in region_ids or interfaces_by_region[step["target_region_id"]] != step["start_state"]:
            fail("invalid_reference", "step target must belong to its start interface")
    issue_ids = set()
    for issue in batch["issues"]:
        if issue["issue_id"] in issue_ids or issue["region_id"] not in region_ids: fail("invalid_reference", "reported issue ids and regions must be valid")
        issue_ids.add(issue["issue_id"])
    return batch


def validate_scope(value: Any, batch: dict[str, Any]) -> dict[str, list[str]]:
    scope = parse(ScopeInput, value, "scope")
    known_interfaces = {item["interface_id"] for item in batch["interfaces"]}
    known_relationships = {item["relationship_id"] for item in batch["relationships"]}
    if not scope["interface_ids"] and not scope["relationship_ids"] or len(set(scope["interface_ids"])) != len(scope["interface_ids"]) or len(set(scope["relationship_ids"])) != len(scope["relationship_ids"]):
        fail("invalid_scope", "scope must be non-empty and unique")
    if not set(scope["interface_ids"]) <= known_interfaces or not set(scope["relationship_ids"]) <= known_relationships:
        fail("invalid_reference", "scope references are not in batch")
    return scope


def validate_candidate(value: Any) -> dict[str, Any]:
    if isinstance(value, dict) and value.get("contract_version") == "agent_link_graph_candidate_v1":
        return parse(GraphCandidateInput, value, "graph candidate")
    candidate = parse(CandidateInput, value, "candidate")
    changes = []
    mapping = {
        "geometry": GeometryChange, "regions_add": RegionsAddChange, "interfaces_add": InterfacesAddChange, "steps_add": StepsAddChange, "relationships_add": RelationshipsAddChange, "semantic": SemanticChange,
        "relationship": RelationshipChange, "step": StepChange,
        "step_flow": StepFlowChange, "relationship_flow": RelationshipFlowChange,
        "step_order": StepOrderChange,
    }
    for raw in candidate["changes"]:
        if not isinstance(raw, dict) or raw.get("change_type") not in mapping:
            fail("invalid_arguments", "candidate changes have an unsupported type")
        changes.append(parse(mapping[raw["change_type"]], raw, "candidate change"))
    candidate["changes"] = changes
    return candidate
