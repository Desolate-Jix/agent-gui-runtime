from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.runtime_architecture.contracts import AppProfile
from app.runtime_architecture.profiles import get_app_profile


class OperationSkill(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["operation_skill_v1"] = "operation_skill_v1"
    skill_id: str
    category: Literal["observe", "locate", "click", "input", "scroll", "read", "form", "window", "verify", "app_specific"]
    description: str
    side_effect_class: Literal["read_only", "navigation", "write", "dangerous"] = "read_only"
    requires_gate: bool = True
    maps_to_apis: list[str] = Field(default_factory=list)


_BASE_OPERATION_SKILLS: tuple[OperationSkill, ...] = (
    OperationSkill(
        skill_id="observe_screen",
        category="observe",
        description="Capture and understand the current screen before the Agent decides the next intent.",
        side_effect_class="read_only",
        requires_gate=False,
        maps_to_apis=["POST /vision/observe_screen", "POST /execute/observe"],
    ),
    OperationSkill(
        skill_id="locate_element",
        category="locate",
        description="Locate a target element from the current observation without executing a real action.",
        side_effect_class="read_only",
        requires_gate=False,
        maps_to_apis=["POST /vision/locate_target"],
    ),
    OperationSkill(
        skill_id="click_target",
        category="click",
        description="Click a fresh, gated target in the bound window.",
        side_effect_class="navigation",
        maps_to_apis=["POST /action/execute_recognition_plan", "POST /action/execute_confirmed_point"],
    ),
    OperationSkill(
        skill_id="type_text",
        category="input",
        description="Type Agent-provided text into a verified field without submitting by default.",
        side_effect_class="write",
        maps_to_apis=["POST /action/type_text"],
    ),
    OperationSkill(
        skill_id="scroll_region",
        category="scroll",
        description="Scroll a scoped container and verify the intended content changed.",
        side_effect_class="navigation",
        maps_to_apis=["POST /action/scroll"],
    ),
    OperationSkill(
        skill_id="read_region",
        category="read",
        description="Read a known screen region through OCR/UI evidence.",
        side_effect_class="read_only",
        requires_gate=False,
        maps_to_apis=["POST /ocr/region", "POST /execute/read_region_batch"],
    ),
    OperationSkill(
        skill_id="read_full_page",
        category="read",
        description="Read full page content when a scoped region is not enough for Agent decisions.",
        side_effect_class="read_only",
        requires_gate=False,
        maps_to_apis=["POST /vision/observe_screen"],
    ),
    OperationSkill(
        skill_id="detect_form",
        category="form",
        description="Detect fields, selected values, and safe fill targets in the active form.",
        side_effect_class="read_only",
        requires_gate=False,
        maps_to_apis=["POST /execute/form_inventory"],
    ),
    OperationSkill(
        skill_id="bind_window",
        category="window",
        description="Bind or launch the target app/window before screen operations.",
        side_effect_class="navigation",
        maps_to_apis=["POST /apps/open", "POST /apps/bind"],
    ),
    OperationSkill(
        skill_id="verify_change",
        category="verify",
        description="Verify before/after screen change, focus, OCR, or scoped UI diff evidence.",
        side_effect_class="read_only",
        requires_gate=False,
        maps_to_apis=["POST /execute/verify_diff"],
    ),
    OperationSkill(
        skill_id="open_apply_flow",
        category="click",
        description="Open an application flow; this is not final submit.",
        side_effect_class="navigation",
        maps_to_apis=["POST /action/execute_recognition_plan"],
    ),
)


_SEEK_SKILL_ALIASES: dict[str, str] = {
    "locate_job_card": "locate_element",
    "open_job_detail": "click_target",
    "read_full_job_detail": "read_full_page",
    "scroll_results_list": "scroll_region",
    "scroll_detail_pane": "scroll_region",
    "reset_detail_pane_to_header": "scroll_region",
    "open_apply_entry": "open_apply_flow",
    "observe_application_flow": "observe_screen",
    "read_application_form": "detect_form",
    "verify_page_change": "verify_change",
}


def list_operation_skills(app_id: str | None = None) -> list[dict[str, Any]]:
    profile = _profile_for_app(app_id)
    base = {skill.skill_id: skill.model_dump() for skill in _BASE_OPERATION_SKILLS}
    if not profile:
        return list(base.values())
    skills: list[dict[str, Any]] = []
    for skill_id in profile.operation_skills:
        if skill_id in base:
            payload = dict(base[skill_id])
            payload["profile_skill_id"] = skill_id
            skills.append(payload)
            continue
        base_skill_id = _SEEK_SKILL_ALIASES.get(skill_id)
        if base_skill_id and base_skill_id in base:
            payload = dict(base[base_skill_id])
            payload.update(
                {
                    "skill_id": skill_id,
                    "base_skill_id": base_skill_id,
                    "category": "app_specific",
                    "description": f"{profile.display_name} profile skill backed by {base_skill_id}.",
                }
            )
            skills.append(payload)
            continue
        skills.append(
            OperationSkill(
                skill_id=skill_id,
                category="app_specific",
                description=f"{profile.display_name} profile-specific operation skill.",
                side_effect_class="navigation",
            ).model_dump()
        )
    return skills


def build_operation_skill_catalog(app_id: str | None = None) -> dict[str, Any]:
    profile = _profile_for_app(app_id)
    return {
        "contract_version": "operation_skill_catalog_v1",
        "execution_model": "agentic_loop_first",
        "app_id": profile.app_id if profile else app_id,
        "profile_path": _profile_path(app_id) if profile else None,
        "skills": list_operation_skills(app_id),
    }


def _profile_for_app(app_id: str | None) -> AppProfile | None:
    if not app_id:
        return None
    profile, _path = get_app_profile(app_id)
    return profile


def _profile_path(app_id: str | None) -> str | None:
    if not app_id:
        return None
    _profile, path = get_app_profile(app_id)
    return str(Path(path))
