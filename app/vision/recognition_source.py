"""识别来源的静态能力协商；不连接服务、不加载模型、不改写用户选择。"""
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Source = Literal["local", "agent_current", "agent_delegate", "external_api"]
Capability = Literal["supported", "unsupported", "unknown"]


class RecognitionSourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    source: Source = "local"
    delegate_profile: str | None = Field(default=None, min_length=1, max_length=128)
    api_profile: str | None = Field(default=None, min_length=1, max_length=128)
    fallback_policy: Literal["explicit_only"] = "explicit_only"

    @model_validator(mode="after")
    def validate_profile(self):
        for name, required_source in (("delegate_profile", "agent_delegate"),
                                       ("api_profile", "external_api")):
            value = getattr(self, name)
            if self.source == required_source:
                if value is None or not value.strip() or value != value.strip():
                    raise ValueError(f"{required_source} requires a non-empty {name} without outer whitespace")
            elif value is not None:
                raise ValueError(f"{name} is only supported for {required_source}")
        return self


class ClientVisionCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    image_transport: Capability = "unknown"
    current_vision: Capability = "unknown"
    delegation: Capability = "unknown"
    model_selection: Capability = "unknown"
    delegate_vision: Capability = "unknown"


@dataclass(frozen=True)
class RecognitionRoute:
    source: Source
    status: Literal["eligible", "unavailable"]
    code: str
    dispatch_owner: Literal["framework", "agent_client"]
    requires_local_model: bool
    profile: str | None
    missing_capabilities: tuple[str, ...]
    connection_verified: bool = False


def resolve_recognition_route(config: RecognitionSourceConfig,
                              capabilities: ClientVisionCapabilities) -> RecognitionRoute:
    # eligible 仅证明所声明的能力满足条件，不证明模型或连接已经可用。
    required = {
        "local": (), "external_api": (),
        "agent_current": ("image_transport", "current_vision"),
        "agent_delegate": ("image_transport", "delegation", "model_selection", "delegate_vision"),
    }[config.source]
    missing = tuple(key for key in required if getattr(capabilities, key) != "supported")
    code = "capabilities_satisfied"
    if missing:
        code = ("vision_unsupported" if any(getattr(capabilities, key) == "unsupported" for key in missing)
                else "capability_unknown")
    return RecognitionRoute(
        source=config.source, status="unavailable" if missing else "eligible", code=code,
        dispatch_owner="agent_client" if config.source.startswith("agent_") else "framework",
        requires_local_model=config.source == "local",
        profile=config.delegate_profile or config.api_profile, missing_capabilities=missing,
    )


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("recognition configuration contains a duplicate JSON key")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("recognition configuration contains a non-finite JSON value")


def load_recognition_source(path: str | Path) -> RecognitionSourceConfig:
    value = json.loads(Path(path).read_text(encoding="utf-8-sig"),
                       object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    if not isinstance(value, dict):
        raise ValueError("vision configuration must be an object")
    # 只有旧配置完全没有新节时沿用本地；损坏的新节必须报错。
    if "recognition" not in value:
        return RecognitionSourceConfig()
    section = value["recognition"]
    if not isinstance(section, dict) or "source" not in section:
        raise ValueError("recognition configuration requires an explicit source")
    return RecognitionSourceConfig.model_validate(section)
