from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class LocateWritePolicy(BaseModel):
    path_graph: bool = False
    element_memory: bool = True
    trace: bool = True


class LocateSingleTargetTaskInput(BaseModel):
    goal: str = Field(min_length=1)
    image_path: str = Field(min_length=1)
    task: str = Field(default="click_target", min_length=1)
    app_name: str | None = None
    state_hint: str | None = None
    provider_mode: str = "local_grounding"
    agent_mode: Literal["learn", "execute"] = "execute"
    learn_depth: Literal["fast", "deep"] | None = None
    write_policy: LocateWritePolicy = Field(default_factory=LocateWritePolicy)
    metadata: dict[str, Any] = Field(default_factory=dict)
    top_k: int = Field(default=5, ge=1, le=20)
    live_capture: dict[str, Any] | None = None
    observe_trace_path: str | None = None
    operation_context: dict[str, Any] = Field(default_factory=dict)
    observe_reuse: dict[str, Any] = Field(default_factory=dict)


class LocateRecognitionPlanRequest(BaseModel):
    image_path: str = Field(min_length=1)
    task: str = Field(default="click_target", min_length=1)
    app_name: str | None = None
    goal: str = Field(min_length=1)
    state_hint: str | None = None
    provider_mode: str = "local_grounding"
    agent_mode: Literal["learn", "execute"] = "execute"
    learn_depth: Literal["fast", "deep"] | None = None
    write_policy: LocateWritePolicy = Field(default_factory=LocateWritePolicy)
    metadata: dict[str, Any] = Field(default_factory=dict)
    top_k: int = Field(default=5, ge=1, le=20)
    observe_trace_path: str | None = None
    operation_context: dict[str, Any] = Field(default_factory=dict)


class LocateRecognitionPlanResult(BaseModel):
    success: bool
    message: str
    payload: dict[str, Any] | None = None
    error: dict[str, Any] | str | None = None


class LocateTaskFailure(BaseModel):
    code: str = Field(min_length=1)
    details: str


class LocateSingleTargetTaskResult(BaseModel):
    outcome: Literal["completed", "failed"]
    payload: dict[str, Any] = Field(default_factory=dict)
    failure: LocateTaskFailure | None = None

