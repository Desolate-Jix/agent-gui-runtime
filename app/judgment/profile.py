"""只读取非秘密配置；模型和供应商地址固定。"""
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator


Condition = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=4000)]


class DecisionProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    contract_version: Literal["decision_profile.v1"] = "decision_profile.v1"
    mode: Literal["off", "shadow", "auto"] = "shadow"
    api_key_env: Annotated[str, StringConstraints(strict=True, pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")] = "OPENAI_API_KEY"
    timeout_seconds: float = Field(default=8, gt=0, le=60, strict=True, allow_inf_nan=False)
    pass_threshold: float = Field(default=0.9, ge=0, le=1, strict=True, allow_inf_nan=False)
    fail_threshold: float = Field(default=0.1, ge=0, le=1, strict=True, allow_inf_nan=False)
    request_cap: int = Field(default=20, ge=1, le=1000, strict=True)
    auto_conditions: tuple[Condition, ...] = ()

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
        return self


def load_decision_profile(path: str | Path) -> DecisionProfile:
    try:
        profile_path = Path(path)
        if profile_path.stat().st_size > 64 * 1024:
            raise ValueError("decision_profile_too_large")
        payload = json.loads(profile_path.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict) or payload.get("contract_version") != "decision_profile.v1":
            raise ValueError("decision_profile_version_invalid")
        return DecisionProfile.model_validate(payload)
    except (OSError, UnicodeError, ValueError):
        # 不回显配置原文或校验输入，防止错误配置中夹带凭据。
        raise ValueError("decision_profile_invalid") from None
