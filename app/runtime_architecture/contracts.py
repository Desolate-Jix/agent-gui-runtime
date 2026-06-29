from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


LayerName = Literal["agent", "operation", "gate", "trace", "workflow_asset"]
ExecutionMode = Literal["agentic_loop_first", "pathgraph_assisted"]


class LayerSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: LayerName
    responsibility: str
    owns: list[str] = Field(default_factory=list)
    does_not_own: list[str] = Field(default_factory=list)


class RuntimeArchitectureSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["gui_agent_runtime_architecture_v1"]
    execution_model: ExecutionMode
    layers: list[LayerSpec]
    workflow_asset_role: str
    required_cross_cutting_contracts: list[str]


class OperationRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    contract_version: Literal["operation_request_v1"] = "operation_request_v1"
    intent: str
    skill_id: str
    target_description: str
    risk_level: Literal["read_only", "low", "medium", "high"] = "low"
    requires_gate: bool = True
    evidence_refs: list[str] = Field(default_factory=list)


class GateDecision(BaseModel):
    model_config = ConfigDict(extra="allow")

    contract_version: Literal["gate_decision_v1"] = "gate_decision_v1"
    action_type: str
    allowed: bool
    reason: str
    required_action: Literal["continue", "ask_user_required", "stop_and_report"] = "continue"
    checks: list[str] = Field(default_factory=list)


class TraceEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    contract_version: Literal["trace_event_v1"] = "trace_event_v1"
    event_type: str
    layer: LayerName
    summary: str
    evidence_refs: list[str] = Field(default_factory=list)


class AppProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["app_profile_v1"]
    app_id: str
    display_name: str
    execution_model: ExecutionMode
    profile_role: str
    agent_prompt_requirements: list[str] = Field(default_factory=list)
    operation_skills: list[str] = Field(default_factory=list)
    gate_contracts: list[str] = Field(default_factory=list)
    trace_requirements: list[str] = Field(default_factory=list)
    workflow_assets: list[dict[str, Any]] = Field(default_factory=list)
    learning_assets: list[dict[str, Any]] = Field(default_factory=list)
    policy: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)

    @field_validator("app_id", "display_name", "profile_role")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        cleaned = " ".join(str(value or "").split())
        if not cleaned:
            raise ValueError("value must not be empty")
        return cleaned


def build_default_architecture_spec() -> RuntimeArchitectureSpec:
    return RuntimeArchitectureSpec(
        contract_version="gui_agent_runtime_architecture_v1",
        execution_model="agentic_loop_first",
        workflow_asset_role=(
            "Workflow/PathGraph is a reusable learned asset. It can guide execution when available, "
            "but unfamiliar interfaces still run through observe -> agent decision -> gate -> operation -> trace."
        ),
        required_cross_cutting_contracts=[
            "agent_decision_v1",
            "operation_request_v1",
            "operation_result_v1",
            "gate_decision_v1",
            "trace_event_v1",
            "app_profile_v1",
            "runtime_path_graph_v1",
        ],
        layers=[
            LayerSpec(
                name="agent",
                responsibility="Understand the user goal, decompose the task, edit prompts, and decide the next intent.",
                owns=[
                    "conversation understanding",
                    "task decomposition",
                    "prompt versioning",
                    "content suitability decisions",
                    "ask_user_required decisions",
                    "pathgraph selection when a matching asset exists",
                ],
                does_not_own=["real clicks", "raw coordinate authorization", "final-submit bypass"],
            ),
            LayerSpec(
                name="operation",
                responsibility="Observe the screen and execute concrete skills such as locate, click, input, scroll, and read.",
                owns=[
                    "observe_screen",
                    "locate_element",
                    "click_target",
                    "type_text",
                    "scroll_region",
                    "read_region",
                    "window/app adapters",
                ],
                does_not_own=["business suitability decisions", "danger approval"],
            ),
            LayerSpec(
                name="gate",
                responsibility="Approve or block each real action using freshness, target, danger, and policy checks.",
                owns=[
                    "candidate freshness",
                    "coordinate validation",
                    "action taxonomy",
                    "danger detection",
                    "final submit blocking",
                    "policy enforcement",
                ],
                does_not_own=["task planning", "job/profile matching"],
            ),
            LayerSpec(
                name="trace",
                responsibility="Record evidence for audit, replay, evaluation, and learning.",
                owns=[
                    "agent prompt/output records",
                    "operation evidence",
                    "gate decisions",
                    "screenshots/OCR/UIA/DOM refs",
                    "replay cases",
                    "learning inputs",
                ],
                does_not_own=["live action selection"],
            ),
            LayerSpec(
                name="workflow_asset",
                responsibility="Represent learned reusable workflows as PathGraph assets, not as the mandatory execution entry.",
                owns=[
                    "abstract workflow templates",
                    "runtime_path_graph_v1",
                    "state detectors",
                    "transition skill bindings",
                    "success/failure conditions",
                ],
                does_not_own=["open-ended exploration on unknown screens"],
            ),
        ],
    )


def load_app_profile(path: str | Path) -> AppProfile:
    profile_path = Path(path)
    payload = json.loads(profile_path.read_text(encoding="utf-8"))
    return AppProfile.model_validate(payload)
