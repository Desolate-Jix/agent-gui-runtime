"""识别交接与显式执行命令；执行只引用已冻结的候选。"""
from pydantic import BaseModel, ConfigDict, Field

from .recognition_source import ClientVisionCapabilities, RecognitionSourceConfig


class GroundingPrepareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    goal: str = Field(min_length=1, max_length=4096)
    configuration: RecognitionSourceConfig
    capabilities: ClientVisionCapabilities


class GroundingReferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    grounding_request_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,79}$")


class GroundingResolveRequest(GroundingReferenceRequest):
    result: dict | str


GROUNDING_COMMANDS = {
    "grounding_prepare": GroundingPrepareRequest,
    "grounding_resolve": GroundingResolveRequest,
    "grounding_status": GroundingReferenceRequest,
    "grounding_cancel": GroundingReferenceRequest,
    "grounding_execute": GroundingReferenceRequest,
}


def validate_grounding_command(kind, request):
    return GROUNDING_COMMANDS[kind].model_validate(request)
