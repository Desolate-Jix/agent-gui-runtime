from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.operation.runtime_context import OperationRuntimeContext


class ObserveWritePolicy(BaseModel):
    path_graph: bool = True
    element_memory: bool = False
    trace: bool = True


def _fast_write_policy() -> ObserveWritePolicy:
    return ObserveWritePolicy(
        path_graph=True,
        element_memory=False,
        trace=True,
    )


def _deep_write_policy() -> ObserveWritePolicy:
    return ObserveWritePolicy(
        path_graph=True,
        element_memory=True,
        trace=True,
    )


class ObserveScreenTaskInput(BaseModel):
    task: str = Field(default="observe_screen", min_length=1)
    app_name: str | None = None
    state_hint: str | None = None
    provider_mode: str | None = None
    agent_mode: Literal["learn", "execute"] = "learn"
    learn_depth: Literal["fast", "deep"] = "fast"
    write_policy: ObserveWritePolicy = Field(default_factory=_fast_write_policy)
    metadata: dict[str, Any] = Field(default_factory=dict)
    operation_context: OperationRuntimeContext = Field(
        default_factory=OperationRuntimeContext
    )
    capture_live: bool = True
    image_path: str | None = None

    @model_validator(mode="after")
    def align_default_write_policy_with_depth(self) -> "ObserveScreenTaskInput":
        if self.learn_depth == "deep" and "write_policy" not in self.model_fields_set:
            self.write_policy = _deep_write_policy()
        return self


class ObserveScreenReadRequest(BaseModel):
    image_path: str = Field(min_length=1)
    task: str = Field(default="observe_screen", min_length=1)
    app_name: str | None = None
    goal: str = "understand the current interface, visible controls, and likely actions"
    state_hint: str | None = None
    provider_mode: str = "local_understanding"
    agent_mode: Literal["learn", "execute"] = "learn"
    learn_depth: Literal["fast", "deep"] = "fast"
    write_policy: ObserveWritePolicy = Field(default_factory=_fast_write_policy)
    metadata: dict[str, Any] = Field(default_factory=dict)
    operation_context: OperationRuntimeContext = Field(
        default_factory=OperationRuntimeContext
    )


class ObserveScreenReadResult(BaseModel):
    success: bool
    message: str
    payload: dict[str, Any] | None = None
    error: dict[str, Any] | str | None = None
    model_io: dict[str, Any] | None = None


class ObserveScreenTaskFailure(BaseModel):
    code: str = Field(min_length=1)
    details: str


class ObserveScreenTaskResult(BaseModel):
    outcome: Literal["completed", "safe_stopped", "failed"]
    payload: dict[str, Any] = Field(default_factory=dict)
    failure: ObserveScreenTaskFailure | None = None
