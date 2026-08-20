from __future__ import annotations

from copy import deepcopy
from typing import Any


_REGION_LEVELS = {"structure_region", "section", "component_group", "component", "content"}


def build_hierarchy_learning_draft(
    *,
    ui_hierarchy: dict[str, Any],
    source_image_path: str = "",
    compiled_overlay_path: str = "",
) -> dict[str, Any]:
    nodes = [node for node in ui_hierarchy.get("nodes", []) if isinstance(node, dict)]
    root_id = str(ui_hierarchy.get("root_node_id") or "uih:screen")
    root = next((node for node in nodes if str(node.get("node_id")) == root_id), {})
    regions = [_draft_region(node) for node in nodes if str(node.get("level") or "") in _REGION_LEVELS]
    regions = [region for region in regions if region]
    regions.sort(key=lambda region: (_level_rank(str(region.get("hierarchy_level") or "")), _bbox_sort(region), str(region["region_id"])))
    structure_region_ids = [
        str(region["region_id"])
        for region in regions
        if region.get("hierarchy_level") == "structure_region"
    ]
    level_counts = {
        level: sum(1 for node in nodes if str(node.get("level") or "") == level)
        for level in ("screen", "structure_region", "section", "component_group", "component", "content")
    }
    graph_validation = deepcopy(ui_hierarchy.get("validation")) if isinstance(ui_hierarchy.get("validation"), dict) else {}
    page_details = {
        "contract_version": "learning_draft_page_details_v1",
        "screen": {
            "image_path": source_image_path,
            "compiled_overlay_path": compiled_overlay_path,
            "bbox": deepcopy(root.get("bbox")) if isinstance(root.get("bbox"), dict) else {},
        },
        "inventory_summary": {
            "region_count": len(regions),
            "structure_region_count": level_counts["structure_region"],
            "section_count": level_counts["section"],
            "component_group_count": level_counts["component_group"],
            "component_count": level_counts["component"],
            "content_count": level_counts["content"],
            "orphan_node_count": int(graph_validation.get("orphan_node_count") or 0),
            "duplicate_primary_owner_count": int(graph_validation.get("duplicate_primary_owner_count") or 0),
            "child_outside_parent_count": int(graph_validation.get("child_outside_parent_count") or 0),
        },
        "sections": [
            {
                "section_id": region["region_id"],
                "label": region["label"],
                "bbox": deepcopy(region["bbox"]),
                "child_region_ids": list(region.get("child_region_ids") or []),
            }
            for region in regions
            if region.get("hierarchy_level") in {"structure_region", "section"}
        ],
        "ui_hierarchy": deepcopy(ui_hierarchy),
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "runtime_pathgraph_promotion": False,
    }
    summary_parts = [
        f"{level_counts['structure_region']} structure regions",
        f"{level_counts['section']} sections",
        f"{level_counts['component_group']} component groups",
        f"{level_counts['component']} components",
        f"{level_counts['content']} content nodes",
    ]
    return {
        "contract_version": "learning_template_draft_v1",
        "screen_summary": "UI hierarchy draft: " + ", ".join(summary_parts),
        "state_guess": "observed_screen",
        "states": [
            {
                "state_id": "observed_screen",
                "label": "Observed screen",
                "bbox": deepcopy(root.get("bbox")) if isinstance(root.get("bbox"), dict) else {},
                "region_ids": structure_region_ids,
                "review_only": True,
            }
        ],
        "regions": regions,
        "action_templates": [],
        "blockers": [
            {"blocker_id": "no_execute_authorization", "reason": "learning draft is display and review only"},
            {"blocker_id": "final_submit_forbidden", "reason": "final submit remains hard-blocked"},
        ],
        "verification_rules": [
            {"rule_id": "hierarchy_parent_containment", "expected": "every child remains inside its parent"},
            {"rule_id": "unique_primary_owner", "expected": "every item has at most one primary owner"},
            {"rule_id": "human_review_before_promotion", "expected": "manual review is required before template promotion"},
        ],
        "agent_decision_points": [],
        "operation_skills": ["observe_screen", "review_ui_hierarchy"],
        "gate_contracts": ["display_only", "no_click_authorization", "final_submit_forbidden"],
        "learning_source": "ui_hierarchy_graph_v1",
        "ui_hierarchy": deepcopy(ui_hierarchy),
        "page_details": page_details,
        "notes": [
            "The UI hierarchy is a review artifact, not a Runtime PathGraph.",
            "No action template is authorized until human review and a later gated promotion step.",
        ],
        "safety": {
            "display_only": True,
            "draft_only": True,
            "no_click_authorization": True,
            "final_submit_forbidden": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "runtime_pathgraph_promotion": False,
        },
    }


def _draft_region(node: dict[str, Any]) -> dict[str, Any]:
    node_id = str(node.get("node_id") or "").strip()
    bbox = node.get("bbox") if isinstance(node.get("bbox"), dict) else {}
    if not node_id or not bbox:
        return {}
    parent_id = str(node.get("parent_id") or "")
    return {
        "region_id": node_id,
        "source_ref": str(node.get("source_ref") or ""),
        "label": str(node.get("label") or node_id),
        "role": str(node.get("component_type") or node.get("level") or "review_region"),
        "hierarchy_level": str(node.get("level") or "component"),
        "bbox": deepcopy(bbox),
        "parent_region_id": "" if parent_id == "uih:screen" else parent_id,
        "child_region_ids": [str(child) for child in node.get("children", []) if str(child or "").strip()],
        "review_status": str(node.get("review_status") or "review_only"),
        "review_only": True,
        "candidate_only": True,
        "possible_operations": ["read_only"],
        "evidence": deepcopy(node.get("evidence")) if isinstance(node.get("evidence"), list) else [],
        "confidence": node.get("confidence"),
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _level_rank(level: str) -> int:
    return {
        "structure_region": 1,
        "section": 2,
        "component_group": 3,
        "component": 4,
        "content": 5,
    }.get(level, 99)


def _bbox_sort(region: dict[str, Any]) -> tuple[int, int, int, int]:
    bbox = region.get("bbox") if isinstance(region.get("bbox"), dict) else {}
    return (
        int(bbox.get("y") or 0),
        int(bbox.get("x") or 0),
        int(bbox.get("h") or 0),
        int(bbox.get("w") or 0),
    )
