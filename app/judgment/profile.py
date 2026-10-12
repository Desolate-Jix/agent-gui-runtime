"""只读取非秘密配置；模型和供应商地址固定。"""
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_serializer, model_validator


Condition = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=4000)]


class ConditionTemplateIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    condition_template_id: Annotated[str, StringConstraints(strict=True, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,159}$")]
    revision: int = Field(strict=True, ge=1)
    template_sha256: Annotated[str, StringConstraints(strict=True, min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")]


class DecisionProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    contract_version: Literal["decision_profile.v1", "decision_profile.v2"] = "decision_profile.v1"
    mode: Literal["off", "shadow", "auto"] = "shadow"
    api_key_env: Annotated[str, StringConstraints(strict=True, pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")] = "OPENAI_API_KEY"
    timeout_seconds: float = Field(default=8, gt=0, le=60, strict=True, allow_inf_nan=False)
    pass_threshold: float = Field(default=0.9, ge=0, le=1, strict=True, allow_inf_nan=False)
    fail_threshold: float = Field(default=0.1, ge=0, le=1, strict=True, allow_inf_nan=False)
    before_action_pass_threshold: float | None = Field(default=None, ge=0, le=1, strict=True, allow_inf_nan=False)
    after_action_pass_threshold: float | None = Field(default=None, ge=0, le=1, strict=True, allow_inf_nan=False)
    after_action_review_threshold: float | None = Field(default=None, gt=0, le=1, strict=True, allow_inf_nan=False)
    request_cap: int = Field(default=20, ge=1, le=1000, strict=True)
    auto_conditions: tuple[Condition, ...] = ()
    auto_condition_templates: tuple[ConditionTemplateIdentity, ...] = ()
    proactive_review: bool = Field(default=True, strict=True)
    review_policy: Literal["adaptive", "always_main"] = "adaptive"
    scene_precheck: Literal["off", "parallel"] = "off"
    decision_format: Literal["predicate", "choice"] = "predicate"

    @model_validator(mode="before")
    @classmethod
    def validate_versioned_policy(cls, value):
        if isinstance(value, dict) and value.get("contract_version") == "decision_profile.v2" and "mode" not in value:
            # 新版配置默认主动采用；旧版及已冻结的明确模式保持原意。
            value = {**value, "mode": "auto"}
        if (isinstance(value, dict) and value.get("contract_version", "decision_profile.v1") == "decision_profile.v1"
                and {"proactive_review", "review_policy", "auto_condition_templates",
                     "before_action_pass_threshold", "after_action_pass_threshold", "after_action_review_threshold", "scene_precheck", "decision_format"}.intersection(value)):
            raise ValueError("decision_v2_policy_requires_v2_profile")
        return value

    @model_serializer(mode="wrap")
    def serialize_versioned_policy(self, serializer):
        value = serializer(self)
        if "decision_format" not in self.model_fields_set:
            # 缺省保留旧谓词配置及其认证摘要。
            value.pop("decision_format", None)
        if "scene_precheck" not in self.model_fields_set:
            # 缺省关闭的新预检字段不改变旧配置的序列化或摘要。
            value.pop("scene_precheck", None)
        for field in ("before_action_pass_threshold", "after_action_pass_threshold", "after_action_review_threshold"):
            if getattr(self, field) is None:
                # 未配置的新阈值不改变既有会话快照和摘要。
                value.pop(field, None)
        if not self.auto_condition_templates:
            # 空模板列表不改变既有 v1/v2 配置快照和请求摘要。
            value.pop("auto_condition_templates", None)
        if self.contract_version == "decision_profile.v1":
            # 旧会话的配置快照与摘要不因新增字段改变。
            value.pop("proactive_review", None)
            value.pop("review_policy", None)
        return value

    @field_validator("auto_condition_templates", mode="before")
    @classmethod
    def validate_template_list(cls, value):
        if not isinstance(value, (list, tuple)) or len(value) > 100:
            raise ValueError("decision_auto_condition_templates_invalid")
        return value

    @field_validator("auto_condition_templates")
    @classmethod
    def validate_template_identities(cls, value):
        revisions = [(item.condition_template_id, item.revision) for item in value]
        if len(set(revisions)) != len(revisions):
            raise ValueError("decision_auto_condition_template_revision_conflict")
        return value

    @field_validator("auto_conditions", mode="before")
    @classmethod
    def validate_conditions(cls, value):
        if not isinstance(value, (list, tuple)) or len(value) > 100:
            raise ValueError("decision_auto_conditions_invalid")
        if any(not isinstance(item, str) or not item.strip() for item in value):
            raise ValueError("decision_auto_condition_required")
        if len(set(value)) != len(value):
            raise ValueError("decision_auto_conditions_duplicate")
        return tuple(value)

    @model_validator(mode="after")
    def validate_thresholds(self):
        if self.fail_threshold >= self.pass_threshold:
            raise ValueError("decision_thresholds_overlap")
        if self.before_action_pass_threshold is not None and self.before_action_pass_threshold <= self.fail_threshold:
            raise ValueError("decision_before_action_thresholds_overlap")
        if self.after_action_pass_threshold is not None and self.after_action_pass_threshold <= self.fail_threshold:
            raise ValueError("decision_after_action_thresholds_overlap")
        return self


def load_decision_profile(path: str | Path) -> DecisionProfile:
    try:
        profile_path = Path(path)
        if profile_path.stat().st_size > 64 * 1024:
            raise ValueError("decision_profile_too_large")
        payload = json.loads(profile_path.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict) or payload.get("contract_version") not in ("decision_profile.v1", "decision_profile.v2"):
            raise ValueError("decision_profile_version_invalid")
        return DecisionProfile.model_validate(payload)
    except (OSError, UnicodeError, ValueError):
        # 不回显配置原文或校验输入，防止错误配置中夹带凭据。
        raise ValueError("decision_profile_invalid") from None
