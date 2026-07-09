from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_LOAD_CONTRACT = "model_learning_artifact_load_v1"
LOADER_CONTRACT = "model_learning_artifact_loader_v1"


def load_model_learning_artifact(trial_path: str | Path, *, project_root: str | Path | None = None) -> dict[str, Any]:
    """把模型学习产物转换为运行层可加载的只读派生件。"""
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    source_path = _resolve_source_path(trial_path, root)
    source_bytes = source_path.read_bytes()
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    trial = json.loads(source_bytes.decode("utf-8-sig"))
    if not isinstance(trial, dict):
        raise ValueError(f"{source_path} must contain a JSON object")

    draft, attempt_index = _select_learning_draft(trial)
    if not isinstance(draft, dict):
        raise ValueError("trial_result does not contain a usable best_learning_draft")

    run_slug = _slug_for_output(source_path, source_hash)
    output_dir = root / "artifacts" / "model-artifact-loader" / run_slug
    output_dir.mkdir(parents=True, exist_ok=True)

    source_ref = {
        "trial_path": _relative_path(source_path, root),
        "sha256": source_hash,
        "attempt_index": attempt_index,
        "readonly": True,
        "posthoc_optimization_allowed": False,
        "loaded_at": datetime.now().isoformat(),
    }
    graph = _build_runtime_path_graph(trial, draft, source_ref)
    interface_map = _build_interface_map(trial, draft, source_ref, graph)

    graph_path = output_dir / "runtime_path_graph.json"
    interface_map_path = output_dir / "interface_map.json"
    graph_path.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    interface_map_path.write_text(json.dumps(interface_map, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "contract_version": ARTIFACT_LOAD_CONTRACT,
        "loader_contract_version": LOADER_CONTRACT,
        "source": source_ref,
        "runtime_graph_path": _relative_path(graph_path, root),
        "interface_map_path": _relative_path(interface_map_path, root),
        "summary": {
            "app_id": graph.get("app_id"),
            "state_count": len(graph.get("states") or []),
            "transition_count": len(graph.get("transitions") or []),
            "action_template_count": len(graph.get("action_templates") or []),
            "region_count": len(interface_map.get("regions") or []),
            "source_artifact_modified": False,
        },
        "safety": {
            "artifact_is_authorization": False,
            "final_submit_allowed": False,
            "final_submit_forbidden": True,
            "real_action_requires_gate": True,
        },
    }


def _resolve_source_path(path_value: str | Path, root: Path) -> Path:
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    allowed_roots = [(root / "artifacts").resolve(), (root / "logs").resolve()]
    if not any(path == allowed or allowed in path.parents for allowed in allowed_roots):
        raise ValueError("trial_path must be under artifacts or logs")
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"trial_path not found: {path_value}")
    return path


def _select_learning_draft(trial: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
    draft = trial.get("best_learning_draft")
    if isinstance(draft, dict):
        return draft, _int_or_none(trial.get("best_attempt_index"))
    attempts = trial.get("attempts")
    if isinstance(attempts, list):
        for index, attempt in enumerate(attempts):
            if not isinstance(attempt, dict):
                continue
            result = attempt.get("parsed_result") or attempt.get("learning_draft") or attempt.get("draft")
            if isinstance(result, dict):
                return result, index
    raise ValueError("trial_result does not contain best_learning_draft or attempt draft")


def _build_runtime_path_graph(trial: dict[str, Any], draft: dict[str, Any], source_ref: dict[str, Any]) -> dict[str, Any]:
    workflow = draft.get("workflow_draft") if isinstance(draft.get("workflow_draft"), dict) else {}
    page_details = draft.get("page_details") if isinstance(draft.get("page_details"), dict) else {}
    states = _runtime_states(workflow, draft)
    regions = _interface_regions(draft)
    action_templates = [_runtime_action_template(item, regions) for item in _list_of_dicts(workflow.get("action_templates"))]
    transitions = _runtime_transitions(workflow, states, action_templates)
    app_id = _slug(str(trial.get("app_name") or draft.get("app_name") or "model_learned_app"), fallback="model_learned_app")
    page_type = str(states[0].get("page_type") or draft.get("state_guess") or "learned_page") if states else "learned_page"
    return {
        "contract_version": "runtime_path_graph_v1",
        "graph_id": f"{app_id}:model_loaded:{source_ref['sha256'][:12]}",
        "app_id": app_id,
        "page_type": page_type,
        "coordinate_policy": {
            "coordinate_space": "window_screenshot",
            "requires_current_capture": True,
            "source_bbox_is_learning_evidence_only": True,
        },
        "loader": {
            "contract_version": LOADER_CONTRACT,
            "source_trial_path": source_ref["trial_path"],
            "source_sha256": source_ref["sha256"],
            "source_attempt_index": source_ref.get("attempt_index"),
            "source_artifact_readonly": True,
            "posthoc_optimization_allowed": False,
        },
        "source": source_ref,
        "page_details": _readonly_page_details(page_details),
        "states": states,
        "regions": regions,
        "transitions": transitions,
        "action_templates": action_templates,
        "artifact_is_authorization": False,
        "safety": {
            "final_submit_allowed": False,
            "final_submit_forbidden": True,
            "real_action_requires_gate": True,
            "observation_source_only": True,
        },
        "summary": {
            "state_count": len(states),
            "region_count": len(regions),
            "transition_count": len(transitions),
            "action_template_count": len(action_templates),
        },
    }


def _build_interface_map(
    trial: dict[str, Any],
    draft: dict[str, Any],
    source_ref: dict[str, Any],
    graph: dict[str, Any],
) -> dict[str, Any]:
    workflow = draft.get("workflow_draft") if isinstance(draft.get("workflow_draft"), dict) else {}
    interface = draft.get("interface_draft") if isinstance(draft.get("interface_draft"), dict) else {}
    page_details = draft.get("page_details") if isinstance(draft.get("page_details"), dict) else {}
    regions = _interface_regions(draft)
    states = [dict(state) for state in graph.get("states") or [] if isinstance(state, dict)]
    visual_assets = _list_of_dicts(interface.get("visual_assets"))
    fixed_assets = [_interface_asset(item, index) for index, item in enumerate(visual_assets)]
    dynamic_areas = _list_of_dicts(interface.get("dynamic_areas"))
    danger_zones = _list_of_dicts(interface.get("danger_zones"))
    app_id = graph.get("app_id") or _slug(str(trial.get("app_name") or "model_learned_app"), fallback="model_learned_app")
    return {
        "contract_version": "learned_interface_map_v1",
        "app_id": app_id,
        "page_type": graph.get("page_type") or draft.get("state_guess") or "",
        "source": source_ref,
        "loader": graph.get("loader"),
        "screen_summary": draft.get("screen_summary") or "",
        "page_details": _readonly_page_details(page_details),
        "states": states,
        "transitions": _list_of_dicts(workflow.get("transitions")) or graph.get("transitions") or [],
        "regions": regions,
        "fixed_visual_assets": fixed_assets,
        "dynamic_areas": dynamic_areas,
        "danger_zones": danger_zones,
        "editor_policy": {
            "source_artifact_editable": False,
            "derived_artifact_editable": False,
            "save_as_required_for_manual_changes": True,
        },
        "summary": {
            "state_count": len(states),
            "region_count": len(regions),
            "fixed_visual_asset_count": len(fixed_assets),
            "dynamic_area_count": len(dynamic_areas),
            "danger_zone_count": len(danger_zones),
        },
    }


def _readonly_page_details(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        return {}
    details = dict(value)
    details["display_only"] = True
    details["artifact_is_authorization"] = False
    details["execute_binding_enabled"] = False
    details["candidate_only"] = True
    return details


def _runtime_states(workflow: dict[str, Any], draft: dict[str, Any]) -> list[dict[str, Any]]:
    states = []
    region_refs = [item["region_id"] for item in _interface_regions(draft) if item.get("region_id")]
    for index, item in enumerate(_list_of_dicts(workflow.get("states"))):
        state_id = str(item.get("state_id") or f"state_{index + 1}").strip()
        if not state_id:
            state_id = f"state_{index + 1}"
        state = {
            "state_id": state_id,
            "label": item.get("label") or state_id,
            "page_type": item.get("page_type") or draft.get("state_guess") or "learned_page",
            "region_refs": item.get("region_refs") if isinstance(item.get("region_refs"), list) else list(region_refs),
        }
        states.append(state)
    if not states:
        states.append({
            "state_id": "model_observed_state",
            "label": draft.get("state_guess") or "model observed state",
            "page_type": draft.get("state_guess") or "learned_page",
            "region_refs": list(region_refs),
        })
    return states


def _interface_regions(draft: dict[str, Any]) -> list[dict[str, Any]]:
    interface = draft.get("interface_draft") if isinstance(draft.get("interface_draft"), dict) else {}
    regions = []
    for index, item in enumerate(_list_of_dicts(interface.get("regions"))):
        region_id = str(item.get("region_id") or f"region_{index + 1}").strip() or f"region_{index + 1}"
        role = str(item.get("role") or item.get("region_type") or "").strip()
        regions.append({
            **item,
            "region_id": region_id,
            "label": item.get("label") or region_id,
            "region_type": item.get("region_type") or role or "learned_region",
            "role": role,
            "source_artifact_readonly": True,
        })
    return regions


def _runtime_action_template(template: dict[str, Any], regions: list[dict[str, Any]]) -> dict[str, Any]:
    action_id = str(template.get("action_template_id") or template.get("action_id") or "model_action").strip()
    low_level = _low_level_action_type(template)
    region = _select_target_region(template, regions, low_level)
    result = {
        **template,
        "action_template_id": action_id,
        "label": template.get("label") or action_id,
        "action_type": low_level,
        "low_level_action_type": low_level,
        "requires_gate": template.get("requires_gate", True),
        "target_entity": template.get("target_entity") or (region.get("region_id") if region else None),
        "learned_skill_ref": template.get("learned_skill_ref") or _skill_ref_for_action(low_level),
        "artifact_is_authorization": False,
    }
    if low_level == "input":
        input_role = (region.get("role") or region.get("region_type") or "textbox") if region else "textbox"
        result["input_target"] = {
            "region_id": region.get("region_id") if region else None,
            "role": input_role,
            "requires_current_validation": True,
        }
        result["input_policy"] = {
            "requires_agent_text": True,
            "clear_existing": True,
            "submit_allowed": False,
            "text_is_not_stored_by_menu": True,
        }
    if low_level == "scroll":
        result["scroll_target"] = template.get("scroll_target") if isinstance(template.get("scroll_target"), dict) else {
            "target_container_id": region.get("region_id") if region else None,
            "target_pane": region.get("label") if region else "learned_region",
        }
    return result


def _runtime_transitions(
    workflow: dict[str, Any],
    states: list[dict[str, Any]],
    action_templates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    existing = _list_of_dicts(workflow.get("transitions"))
    if existing:
        return [
            {
                **item,
                "transition_id": item.get("transition_id") or f"model:transition:{item.get('action_template_id') or index + 1}",
                "from_state_id": item.get("from_state_id") or states[0]["state_id"],
                "to_state_id": item.get("to_state_id") or item.get("from_state_id") or states[0]["state_id"],
            }
            for index, item in enumerate(existing)
        ]
    if not states:
        return []
    state_id = states[0]["state_id"]
    transitions = []
    for index, template in enumerate(action_templates):
        action_id = str(template.get("action_template_id") or f"model_action_{index + 1}")
        hint = _transition_hint_for_action(template)
        if hint:
            target_state_id = _ensure_hint_state(states, hint)
            transitions.append({
                "transition_id": f"model:transition:{action_id}",
                "from_state_id": state_id,
                "to_state_id": target_state_id,
                "action_template_id": action_id,
                "transition_type": hint.get("transition_type") or template.get("semantic_action") or "action",
                "target_surface": hint.get("target_surface"),
                "requires_post_action_observe": bool(hint.get("requires_post_action_observe", True)),
                "default_available": True,
                "verification_refs": [],
                "candidate_only": True,
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            })
            continue
        transitions.append({
            "transition_id": f"model:transition:{action_id}",
            "from_state_id": state_id,
            "to_state_id": state_id,
            "action_template_id": action_id,
            "default_available": True,
            "verification_refs": [],
        })
    return transitions


def _transition_hint_for_action(template: dict[str, Any]) -> dict[str, Any] | None:
    hint = template.get("transition_hint") if isinstance(template.get("transition_hint"), dict) else {}
    if hint.get("contract_version") == "learn_open_detail_transition_hint_v1":
        return hint
    return None


def _ensure_hint_state(states: list[dict[str, Any]], hint: dict[str, Any]) -> str:
    role = str(hint.get("expected_next_state_role") or "next_state").strip() or "next_state"
    state_id = f"model_{_slug(role, fallback='next_state')}"
    for state in states:
        if state.get("state_id") == state_id:
            return state_id
    states.append({
        "state_id": state_id,
        "label": role.replace("_", " ").title(),
        "page_type": role,
        "region_refs": [],
        "source": {
            "contract_version": hint.get("contract_version"),
            "transition_type": hint.get("transition_type"),
            "target_surface": hint.get("target_surface"),
        },
        "requires_post_action_observe": bool(hint.get("requires_post_action_observe", True)),
        "candidate_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    })
    return state_id


def _interface_asset(item: dict[str, Any], index: int) -> dict[str, Any]:
    asset_id = str(item.get("asset_id") or item.get("id") or f"asset_{index + 1}")
    return {
        **item,
        "asset_id": asset_id,
        "label": item.get("label") or asset_id,
        "can_authorize_click": False,
        "source_artifact_readonly": True,
    }


def _low_level_action_type(template: dict[str, Any]) -> str:
    raw = " ".join(
        str(template.get(key) or "")
        for key in ("low_level_action_type", "action_type", "semantic_action", "label", "action_template_id")
    ).casefold()
    if any(token in raw for token in ("scroll", "wheel")):
        return "scroll"
    if any(token in raw for token in ("type", "text", "input", "fill", "search", "press")):
        return "input"
    if any(token in raw for token in ("observe", "read", "verify")):
        return "observe"
    return "click"


def _select_target_region(template: dict[str, Any], regions: list[dict[str, Any]], low_level: str) -> dict[str, Any] | None:
    target = str(template.get("target_entity") or template.get("region_id") or "").strip()
    if target:
        for region in regions:
            if region.get("region_id") == target:
                return region
    if low_level == "input":
        for region in regions:
            text = f"{region.get('region_id')} {region.get('label')} {region.get('role')} {region.get('region_type')}".casefold()
            if any(token in text for token in ("input", "text", "search", "field", "textbox")):
                return region
    return regions[0] if regions else None


def _skill_ref_for_action(low_level: str) -> str:
    return {
        "input": "skill.input_text_into_field",
        "scroll": "skill.scroll_container_until_new_content",
        "observe": "skill.observe_screen_region",
    }.get(low_level, "skill.click_currently_validated_target")


def _slug_for_output(source_path: Path, source_hash: str) -> str:
    stem_parts = [source_path.parent.name, source_path.stem, source_hash[:10]]
    return _slug("_".join(part for part in stem_parts if part), fallback=f"model_artifact_{source_hash[:10]}")


def _slug(value: str, *, fallback: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip()).strip("._-").lower()
    return slug or fallback


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())
