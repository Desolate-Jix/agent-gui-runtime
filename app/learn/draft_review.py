from __future__ import annotations

import hashlib
from io import BytesIO
import json
import re
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, UnidentifiedImageError

from app.learn.correction_memory import record_human_review_correction
from app.learn.recognition.uei.learning_shadow import (
    load_uei_shadow_provider_review,
    strip_uei_shadow_review_cache,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REVIEW_CONTRACT = "learning_draft_review_v1"
REVIEWED_TEMPLATE_CONTRACT = "reviewed_template_candidate_v1"
HUMAN_REVIEW_PATCH_CONTRACT = "human_review_patch_v1"
HIERARCHY_OWNERSHIP_REVIEW_CONTRACT = "hierarchy_ownership_review_revision_v1"
MODEL_START_PREFLIGHT_REPORT_NAME = "learn_fusion_model_start_preflight_report.json"
DEMO_READINESS_REPORT_NAME = "learn_fusion_demo_readiness_report.json"
MODEL_START_APPROVAL_PACKET_NAME = "learn_fusion_model_start_approval_packet.json"
CALIBRATION_PRE_RUN_CHECK_REPORT_NAME = "learn_fusion_calibration_pre_run_check_report.json"
PATHGRAPH_INTEGRATION_READINESS_REPORT_NAME = "learn_fusion_pathgraph_integration_readiness_report.json"
CURRENT_EVIDENCE_PACKET_NAME = "learn_fusion_current_evidence_packet.json"
PRECISE_UNDERSTANDING_CANDIDATE_NAME = "learn_precise_understanding_candidate.json"
PAGE_DETAIL_CANDIDATE_NAME = "learn_page_detail_candidate.json"
LEARN_MODE_DEMO_SCAFFOLD_NAME = "learn_mode_demo_scaffold.json"
LEARNING_MODE_DEMO_GOAL_READINESS_NAME = "learning_mode_demo_goal_readiness_report.json"
_SIDECAR_CANDIDATE_PATH_CACHE: dict[tuple[str, str], list[Path]] = {}


def clear_learning_draft_sidecar_cache() -> None:
    """清理学习草稿 sidecar 索引，保证同进程新生成的产物可见。"""
    _SIDECAR_CANDIDATE_PATH_CACHE.clear()


def _uei_review_uia_support_items(draft: dict[str, Any]) -> list[dict[str, object]]:
    """仅转交当前草稿内显式标注为 UIA 的审阅辅助证据。"""

    page_details = draft.get("page_details")
    if not isinstance(page_details, dict):
        return []
    candidates = page_details.get("grounding_candidates")
    if not isinstance(candidates, list):
        return []
    return [
        deepcopy(candidate)
        for candidate in candidates
        if isinstance(candidate, dict)
        and isinstance(candidate.get("source_evidence"), list)
        and "uia" in {str(source).casefold() for source in candidate["source_evidence"]}
    ]


def load_learning_draft_review(
    source_path: str | Path,
    *,
    project_root: str | Path | None = None,
    discover_related_sidecars: bool = True,
) -> dict[str, Any]:
    """加载模型学习草稿，生成只用于展示和人工审核的面板模型。"""
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    resolved = _resolve_source_path(source_path, root)
    source_bytes = resolved.read_bytes()
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    payload = json.loads(source_bytes.decode("utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("learning draft source must be a JSON object")
    workflow_node_identity = _workflow_node_identity(payload, root)
    preserved_review_status = str(payload.get("review_status") or "").strip()
    preserved_reviewed_by_human = payload.get("reviewed_by_human") is True
    preserved_source_after_review = str(payload.get("source_after_review") or "").strip()
    payload, resolved, source_bytes, source_hash, candidate_review = _resolve_review_payload(
        payload,
        resolved,
        root,
        source_bytes,
        source_hash,
        discover_related_sidecars=discover_related_sidecars,
    )

    draft, attempt_index = _select_draft(payload)
    selected_draft = draft
    source_ref = {
        "source_path": _relative_path(resolved, root),
        "source_trial_path": _relative_path(resolved, root) if _is_trial(payload) else None,
        "original_draft_path": _relative_path(resolved, root),
        "sha256": source_hash,
        "attempt_index": attempt_index,
        "readonly": True,
    }
    normalized_draft = _normalized_draft(draft)
    displayed_source_image = _bind_review_source_image(normalized_draft, root)
    current_capture_lineage_ref, current_capture_lineage_error = _server_capture_lineage_ref(
        payload,
        selected_draft,
        normalized_draft,
    )
    shadow_review = load_uei_shadow_provider_review(
        normalized_draft,
        project_root=root,
        current_capture_lineage_ref=current_capture_lineage_ref,
        current_capture_lineage_error=current_capture_lineage_error,
        displayed_source_sha256=(
            str(displayed_source_image.get("sha256") or "")
            if isinstance(displayed_source_image, dict)
            else None
        ),
        displayed_source_size=(
            deepcopy(displayed_source_image.get("image_size"))
            if isinstance(displayed_source_image, dict)
            and isinstance(displayed_source_image.get("image_size"), dict)
            else None
        ),
        existing_region_ids={
            str(region.get("region_id"))
            for region in normalized_draft.get("regions", [])
            if isinstance(region, dict) and str(region.get("region_id") or "").strip()
        },
        uia_support_items=_uei_review_uia_support_items(normalized_draft),
    )
    shadow_summary = shadow_review.get("summary") if isinstance(shadow_review, dict) else None
    if shadow_summary is not None:
        normalized_draft.pop("provider_summary", None)
        page_details = normalized_draft.get("page_details")
        if isinstance(page_details, dict):
            page_details.pop("provider_summary", None)
    if isinstance(shadow_review, dict) and isinstance(shadow_review.get("regions"), list):
        normalized_draft["regions"].extend(deepcopy(shadow_review["regions"]))
        if shadow_review["regions"]:
            _bind_projected_review_source_copy(
                normalized_draft,
                displayed_source_image=displayed_source_image,
                root=root,
            )
    strip_uei_shadow_review_cache(normalized_draft)
    result = {
        "contract_version": REVIEW_CONTRACT,
        "source": source_ref,
        "review_status": "needs_human_review",
        "draft_only": True,
        "no_click_authorization": True,
        "source_after_review": "model_generated",
        "counts_as_pure_model_generated": False,
        "artifact_is_authorization": False,
        "final_submit_forbidden": True,
        "real_action_requires_gate": True,
        "execute_binding_enabled": False,
        "authorization_scope": "display_and_review_only",
        "draft": normalized_draft,
        "screen_understanding_preview": _screen_understanding_preview(payload, root=root),
        "audit": deepcopy(payload.get("audit")) if isinstance(payload.get("audit"), dict) else {},
        "safety": _review_safety(),
    }
    if shadow_summary is not None:
        result["uei_shadow_provider_summary"] = shadow_summary
    if isinstance(shadow_review, dict) and isinstance(shadow_review.get("projection"), dict):
        result["uei_shadow_review_projection"] = deepcopy(shadow_review["projection"])
    if workflow_node_identity:
        result["workflow_node_identity"] = workflow_node_identity
    if payload.get("contract_version") == REVIEWED_TEMPLATE_CONTRACT:
        result["review_status"] = preserved_review_status or "needs_human_review"
        result["reviewed_by_human"] = preserved_reviewed_by_human
        result["source_after_review"] = preserved_source_after_review or "mixed"
    if candidate_review:
        result["pathgraph_candidate_review"] = candidate_review
    else:
        demo_artifact_review = _learning_demo_artifact_review(
            payload,
            resolved,
            root,
            discover_related_sidecars=discover_related_sidecars,
        )
        if demo_artifact_review:
            result["pathgraph_candidate_review"] = demo_artifact_review
    return result


def _server_capture_lineage_ref(
    payload: dict[str, Any], *drafts: dict[str, Any],
) -> tuple[dict[str, str] | None, str | None]:
    """只接受已加载服务器产物中精确的当前 capture 引用。"""
    candidates = [payload, *drafts]
    for key in ("draft", "learning_draft", "best_learning_draft"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            candidates.append(nested)
    values: list[object] = []
    for candidate in candidates:
        values.append(candidate.get("capture_lineage_ref"))
        page_details = candidate.get("page_details")
        if isinstance(page_details, dict):
            values.append(page_details.get("capture_lineage_ref"))
    unique: dict[tuple[str, str], dict[str, str]] = {}
    for value in values:
        if (isinstance(value, dict) and set(value) == {"id", "content_sha256"}
                and all(isinstance(value.get(name), str) for name in ("id", "content_sha256"))):
            reference = {"id": value["id"], "content_sha256": value["content_sha256"]}
            unique[(reference["id"], reference["content_sha256"])] = reference
    if len(unique) > 1:
        return None, "current_capture_lineage_ambiguous"
    if unique:
        return next(iter(unique.values())), None
    return None, None


def _workflow_node_identity(payload: dict[str, Any], root: Path) -> dict[str, str]:
    candidates = [payload]
    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    for key in ("source_path", "original_draft_path"):
        reference = str(source.get(key) or "").strip()
        if not reference:
            continue
        try:
            referenced_path = _resolve_source_path(reference, root)
            referenced = json.loads(referenced_path.read_text(encoding="utf-8-sig"))
        except (FileNotFoundError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(referenced, dict):
            candidates.append(referenced)

    for candidate in candidates:
        if candidate.get("contract_version") != "interface_workflow_node_review_source_v1":
            continue
        node_id = str(candidate.get("node_id") or "").strip()
        workflow_id = str(candidate.get("workflow_id") or "").strip()
        if not re.fullmatch(r"interface_[A-Za-z0-9_.-]+", node_id):
            continue
        identity = {"node_id": node_id}
        if re.fullmatch(r"workflow_[A-Za-z0-9_.-]+", workflow_id):
            identity["workflow_id"] = workflow_id
        return identity
    return {}


def save_reviewed_template_candidate(
    source_path: str | Path,
    review_patch: dict[str, Any] | None,
    *,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    """保存人工审核后的候选模板；候选件仍不授权执行。"""
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    review_patch = review_patch if isinstance(review_patch, dict) else {}
    review = load_learning_draft_review(
        source_path,
        project_root=root,
        discover_related_sidecars=_review_source_requires_sidecar_discovery(
            source_path,
            root,
        ),
    )
    draft = deepcopy(review["draft"])
    out_dir = root / "artifacts" / "learning-draft-review" / _slug_for_output(review["source"])
    out_dir.mkdir(parents=True, exist_ok=True)
    human_review_patch, human_review_patch_path = _prepare_human_review_patch(
        review_patch,
        review=review,
        draft=draft,
        root=root,
        out_dir=out_dir,
    )
    if human_review_patch:
        review_patch = _compile_human_review_patch(review_patch, human_review_patch)
    changes: list[str] = []
    hierarchy_ownership_review = _apply_hierarchy_ownership_corrections(
        draft,
        human_review_patch,
        review=review,
        root=root,
        patch_path=human_review_patch_path,
    )
    if hierarchy_ownership_review:
        changes.extend(
            f"ownership_resolved:{item.get('item_id')}->{item.get('after_parent_group_id')}"
            for item in hierarchy_ownership_review.get("corrections", [])
        )

    _apply_label_updates(draft.get("regions") or [], review_patch.get("region_label_updates"), "region_id", changes)
    _apply_label_updates(
        draft.get("action_templates") or [],
        review_patch.get("action_label_updates"),
        "action_template_id",
        changes,
    )
    _apply_action_region_bindings(draft.get("action_templates") or [], review_patch.get("action_region_bindings"), changes)
    _apply_bbox_updates(draft.get("regions") or [], review_patch.get("region_bbox_updates"), "region_id", "region", changes)
    _apply_bbox_updates(
        draft.get("action_templates") or [],
        review_patch.get("action_bbox_updates"),
        "action_template_id",
        "action",
        changes,
    )
    _apply_review_additions(draft, review_patch, changes)
    # 旧版表单编辑先应用；结构化框编辑操作随后覆盖同一字段，避免空旧字段抹掉 Agent 语义。
    _apply_manual_edit(draft, review_patch.get("manual_edit"), changes)
    _apply_role_updates(draft.get("regions") or [], review_patch.get("region_role_updates"), changes)
    _apply_parent_updates(draft.get("regions") or [], review_patch.get("region_parent_updates"), changes)
    _apply_metadata_updates(
        draft.get("regions") or [],
        review_patch.get("region_metadata_updates"),
        "region_id",
        "region",
        changes,
    )
    _apply_metadata_updates(
        draft.get("action_templates") or [],
        review_patch.get("action_metadata_updates"),
        "action_template_id",
        "action",
        changes,
    )
    _apply_review_deletions(draft, review_patch, changes)
    for operation in _list_of_dicts(human_review_patch.get("operations")):
        if operation.get("op") == "add":
            changes.append(f"{operation.get('target_kind')}_add:{operation.get('target_id')}")

    reviewed_overlay_path = _render_human_review_overlay(
        draft,
        root=root,
        out_dir=out_dir,
        revision=int(human_review_patch.get("revision") or 0),
    )
    reviewed_overlay_ref = _relative_path(reviewed_overlay_path, root) if reviewed_overlay_path else ""
    if reviewed_overlay_ref:
        draft["numbered_map_path"] = reviewed_overlay_ref
        page_details = draft.get("page_details") if isinstance(draft.get("page_details"), dict) else {}
        page_details["compiled_overlay_path"] = reviewed_overlay_ref
        page_details["human_review_overlay_path"] = reviewed_overlay_ref
        page_details["human_review_overlay_revision"] = int(human_review_patch.get("revision") or 0)
        draft["page_details"] = page_details

    blockers = _list_of_dicts(review_patch.get("blockers"))
    verification_rules = _list_of_dicts(review_patch.get("verification_rules"))
    if blockers:
        draft["blockers"] = blockers
        changes.append(f"blockers:{len(blockers)}")
    if verification_rules:
        draft["verification_rules"] = verification_rules
        changes.append(f"verification_rules:{len(verification_rules)}")

    review_status = str(review_patch.get("review_status") or "needs_human_review").strip()
    if review_status not in {"needs_human_review", "approved_as_assisted_template"}:
        review_status = "needs_human_review"
    if hierarchy_ownership_review:
        review_status = "needs_human_review"
    requested_source = str(review_patch.get("source_after_review") or "mixed").strip()
    source_after_review = "assisted_generation" if requested_source == "assisted_generation" else "mixed"
    manual_bbox_edit_summary = _manual_bbox_edit_summary(draft)
    source_freshness_summary = _source_freshness_summary(draft, root, manual_bbox_edit_summary)
    precise_understanding_summary = _precise_understanding_summary(draft)
    screen_preview = review.get("screen_understanding_preview") if isinstance(review.get("screen_understanding_preview"), dict) else {}
    precise_understanding_readiness_summary = (
        deepcopy(screen_preview.get("precise_understanding_readiness_summary"))
        if isinstance(screen_preview.get("precise_understanding_readiness_summary"), dict)
        else {}
    )
    evidence_integrity = (
        deepcopy(screen_preview.get("evidence_integrity"))
        if isinstance(screen_preview.get("evidence_integrity"), dict)
        else {}
    )
    if not precise_understanding_readiness_summary:
        precise_understanding_readiness_summary = _precise_understanding_readiness_summary(draft)

    candidate = {
        "contract_version": REVIEWED_TEMPLATE_CONTRACT,
        "source": review["source"],
        "source_after_review": source_after_review,
        "counts_as_pure_model_generated": False,
        "artifact_is_authorization": False,
        "draft_only": False,
        "reviewed_by_human": True,
        "review_status": review_status,
        "final_submit_forbidden": True,
        "real_action_requires_gate": True,
        "execute_binding_enabled": False,
        "authorization_scope": "display_and_review_only",
        "draft": draft,
        "safety": _review_safety(),
        "audit": {
            "source_trial_path": review["source"].get("source_trial_path") or review["source"].get("source_path"),
            "original_draft_path": review["source"].get("original_draft_path"),
            "reviewed_at": datetime.now().isoformat(),
            "changes_summary": changes,
            "manual_bbox_edit_summary": manual_bbox_edit_summary,
            "source_freshness_summary": source_freshness_summary,
            "precise_understanding_summary": precise_understanding_summary,
            "precise_understanding_readiness_summary": precise_understanding_readiness_summary,
            "evidence_integrity": evidence_integrity,
            "human_review_patch_path": _relative_path(human_review_patch_path, root) if human_review_patch_path else "",
            "human_review_patch_revision": human_review_patch.get("revision") if human_review_patch else None,
            "reviewed_overlay_path": reviewed_overlay_ref,
            "review_status": review_status,
            "authorization_scope": "display_and_review_only",
        },
    }
    if hierarchy_ownership_review:
        candidate["audit"]["hierarchy_ownership_review"] = deepcopy(
            hierarchy_ownership_review
        )
    out_path = out_dir / "reviewed_template_candidate.json"
    if human_review_patch and human_review_patch_path:
        human_review_patch_path.write_text(
            json.dumps(human_review_patch, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    correction_memory_patch = _correction_memory_compatible_patch(human_review_patch)
    correction_memory = (
        record_human_review_correction(
            correction_memory_patch,
            review=review,
            reviewed_draft=draft,
            project_root=root,
            source_patch_path=_relative_path(human_review_patch_path, root),
        )
        if correction_memory_patch and human_review_patch_path
        else None
    )
    if correction_memory:
        candidate["audit"]["correction_memory"] = deepcopy(correction_memory)
    out_path.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = {
        "contract_version": "learning_draft_review_save_v1",
        "reviewed_template_candidate_path": _relative_path(out_path, root),
        "review_status": review_status,
        "source_after_review": source_after_review,
        "counts_as_pure_model_generated": False,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "final_submit_forbidden": True,
        "changes_summary": changes,
        "manual_bbox_edit_summary": manual_bbox_edit_summary,
        "source_freshness_summary": source_freshness_summary,
        "precise_understanding_summary": precise_understanding_summary,
        "precise_understanding_readiness_summary": precise_understanding_readiness_summary,
        "evidence_integrity": evidence_integrity,
        "human_review_patch_path": _relative_path(human_review_patch_path, root) if human_review_patch_path else "",
        "human_review_patch_revision": human_review_patch.get("revision") if human_review_patch else None,
        "reviewed_overlay_path": reviewed_overlay_ref,
    }
    if correction_memory:
        result["correction_memory"] = correction_memory
    if hierarchy_ownership_review:
        result["hierarchy_ownership_review"] = deepcopy(
            hierarchy_ownership_review
        )
    return result


def _review_source_requires_sidecar_discovery(
    source_path: str | Path,
    root: Path,
) -> bool:
    """正式流程节点已自带完整证据，保存时不再扫描旧 sidecar。"""

    resolved = _resolve_source_path(source_path, root)
    payload = json.loads(resolved.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        return True
    return str(payload.get("contract_version") or "") != (
        "interface_workflow_node_review_source_v1"
    )


def _select_draft(payload: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
    if payload.get("contract_version") == "learning_template_draft_v1":
        return payload, None
    if payload.get("contract_version") == "learn_page_detail_candidate_v1":
        return _draft_from_page_detail_candidate(payload), None
    if payload.get("contract_version") == "learn_mode_demo_scaffold_v1":
        page_detail = payload.get("page_detail_candidate")
        if isinstance(page_detail, dict) and page_detail.get("contract_version") == "learn_page_detail_candidate_v1":
            return _draft_from_page_detail_candidate(page_detail, scaffold=payload), None
        return _draft_from_demo_scaffold(payload), None
    draft = payload.get("draft")
    if isinstance(draft, dict):
        return draft, None
    draft = payload.get("learning_draft")
    if isinstance(draft, dict):
        return draft, None
    draft = payload.get("best_learning_draft")
    if isinstance(draft, dict):
        return draft, _int_or_none(payload.get("best_attempt_index"))
    attempts = payload.get("attempts")
    if isinstance(attempts, list):
        for index, attempt in enumerate(attempts):
            if not isinstance(attempt, dict):
                continue
            result = attempt.get("parsed_result") or attempt.get("learning_draft") or attempt.get("draft")
            if isinstance(result, dict):
                return result, index
    raise ValueError("source does not contain a learning template draft")


def _draft_from_page_detail_candidate(
    page_detail: dict[str, Any],
    *,
    scaffold: dict[str, Any] | None = None,
) -> dict[str, Any]:
    layout = page_detail.get("layout") if isinstance(page_detail.get("layout"), dict) else {}
    sections = _list_of_dicts(layout.get("sections"))
    regions = _list_of_dicts(layout.get("regions"))
    section_ids = [
        str(section.get("section_id") or f"section_{index + 1}")
        for index, section in enumerate(sections)
    ]
    states = [
        {
            "state_id": section_ids[index],
            "label": section.get("label") or section.get("section_id") or f"Section {index + 1}",
            "page_type": "learn_page_detail_section",
            "bbox": _normalized_bbox(section.get("bbox")),
            "region_refs": [],
            "action_template_refs": [],
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        }
        for index, section in enumerate(sections)
    ]
    state_by_id = {str(state.get("state_id") or ""): state for state in states if str(state.get("state_id") or "")}
    draft_regions = []
    action_templates = []
    for index, region in enumerate(regions):
        region_id = str(region.get("region_id") or region.get("source_item_id") or f"region_{index + 1}")
        source_section_id = str(region.get("source_section_id") or "")
        if source_section_id not in state_by_id and len(section_ids) == 1:
            source_section_id = section_ids[0]
        possible_operation = (
            region.get("possible_operation") if isinstance(region.get("possible_operation"), dict) else {}
        )
        operation_kind = str(
            possible_operation.get("kind")
            or possible_operation.get("operation_type")
            or region.get("possible_action")
            or "read_only"
        )
        action_template_id = f"review_{region_id}"
        draft_regions.append(
            {
                "region_id": region_id,
                "label": region.get("label") or region_id,
                "role": region.get("role") or "review_region",
                "bbox": _normalized_bbox(region.get("bbox")) or {},
                "source_section_id": source_section_id or region.get("source_section_id"),
                "source_section_label": region.get("source_section_label"),
                "state_id": source_section_id,
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )
        action_templates.append(
            {
                "action_template_id": action_template_id,
                "label": possible_operation.get("label") or f"Review {region.get('label') or region_id}",
                "semantic_action": operation_kind,
                "action_type": operation_kind,
                "target_entity": region_id,
                "target_region_id": region_id,
                "state_id": source_section_id,
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )
        if source_section_id in state_by_id:
            state_by_id[source_section_id]["region_refs"].append(region_id)
            state_by_id[source_section_id]["action_template_refs"].append(action_template_id)
    summary = page_detail.get("summary") if isinstance(page_detail.get("summary"), dict) else {}
    scaffold_summary = scaffold.get("summary") if isinstance(scaffold, dict) and isinstance(scaffold.get("summary"), dict) else {}
    page_detail_review_only_regions = [
        {
            **deepcopy(region),
            "region_id": str(region.get("region_id") or region.get("source_item_id") or f"region_{index + 1}"),
            "review_only": True,
            "grounding_eligible": False,
            "grounding_block_reason": "page_detail_candidate_requires_human_review",
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        }
        for index, region in enumerate(regions)
    ]
    compiled_overlay_path = str(page_detail.get("compiled_overlay_path") or "").strip()
    full_overlay_path = str(page_detail.get("full_screen_understanding_overlay_path") or compiled_overlay_path).strip()
    calibration_overlay_path = str(page_detail.get("calibration_overlay_path") or "").strip()
    fusion_status = {
        "contract_version": "learning_draft_page_detail_fusion_status_v1",
        "compiled_overlay_path": compiled_overlay_path,
        "full_screen_understanding_overlay_path": full_overlay_path,
        "calibration_overlay_path": calibration_overlay_path,
        "summary": {
            "source": "learn_page_detail_candidate",
            "region_count": summary.get("region_count"),
            "section_count": summary.get("section_count"),
            "display_only": True,
        },
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "not_accuracy": True,
    }
    return {
        "contract_version": "learning_template_draft_v1",
        "screen_summary": page_detail.get("screen_summary")
        or scaffold_summary.get("screen_summary")
        or "Review-only page detail candidate.",
        "state_guess": page_detail.get("source_detail_shape") or "learn_page_detail_candidate",
        "states": states,
        "regions": draft_regions,
        "action_templates": action_templates,
        "blockers": [
            {
                "blocker_id": "review_only_page_detail_candidate",
                "blocker_type": "display_only",
                "description": "Page-detail/scaffold source is display-only and must not authorize Execute.",
            }
        ],
        "verification_rules": [],
        "operation_skills": ["review_page_detail"],
        "gate_contracts": ["no_execute_binding", "final_submit_forbidden"],
        "learning_source": "learn_page_detail_candidate",
        "ui_hierarchy": deepcopy(page_detail.get("ui_hierarchy"))
        if isinstance(page_detail.get("ui_hierarchy"), dict)
        else {},
        "page_details": {
            "contract_version": "learning_draft_page_details_v1",
            "screen": {
                "summary": page_detail.get("screen_summary") or "",
                "image_path": page_detail.get("screenshot_path"),
                "compiled_overlay_path": compiled_overlay_path,
                "full_screen_understanding_overlay_path": full_overlay_path,
                "calibration_overlay_path": calibration_overlay_path,
            },
            "compiled_overlay_path": compiled_overlay_path,
            "full_screen_understanding_overlay_path": full_overlay_path,
            "calibration_overlay_path": calibration_overlay_path,
            "precise_understanding_fusion_status": fusion_status,
            "layout": deepcopy(layout),
            "summary": deepcopy(summary),
            "inventory_summary": {
                "screen_inventory_count": len(page_detail_review_only_regions),
                "accepted_for_grounding_count": 0,
                "rejected_non_actionable_count": len(page_detail_review_only_regions),
                "grounding_validation_count": 0,
            },
            "review_only_regions": page_detail_review_only_regions,
            "grounding_candidates": [],
            "danger_zones": [],
            "source_contract_version": page_detail.get("contract_version"),
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
        "safety": {
            "observation_only": True,
            "display_only": True,
            "final_submit_blocked": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
        "notes": [
            "Synthesized review-only draft from page-detail candidate for panel display.",
            "Not a Runtime PathGraph, not Execute authorization, and not a click/fill/submit permission.",
        ],
    }


def _draft_from_demo_scaffold(scaffold: dict[str, Any]) -> dict[str, Any]:
    summary = scaffold.get("summary") if isinstance(scaffold.get("summary"), dict) else {}
    return {
        "contract_version": "learning_template_draft_v1",
        "screen_summary": "Review-only learning demo scaffold.",
        "state_guess": "learn_mode_demo_scaffold",
        "states": [
            {
                "state_id": "demo_scaffold",
                "label": "Learning demo scaffold",
                "page_type": "review_only_demo_scaffold",
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        ],
        "regions": [],
        "action_templates": [],
        "blockers": [
            {
                "blocker_id": "review_only_demo_scaffold",
                "blocker_type": "display_only",
                "description": "Demo scaffold is display-only and cannot authorize Execute.",
            }
        ],
        "verification_rules": [],
        "operation_skills": ["review_page_detail"],
        "gate_contracts": ["no_execute_binding", "final_submit_forbidden"],
        "learning_source": "learn_mode_demo_scaffold",
        "page_details": {
            "contract_version": "learning_draft_page_details_v1",
            "summary": deepcopy(summary),
            "source_contract_version": scaffold.get("contract_version"),
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
        "safety": {
            "observation_only": True,
            "display_only": True,
            "final_submit_blocked": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
        "notes": [
            "Synthesized review-only draft from demo scaffold for panel display.",
            "Not a Runtime PathGraph, not Execute authorization, and not a click/fill/submit permission.",
        ],
    }


def _resolve_review_payload(
    payload: dict[str, Any],
    resolved: Path,
    root: Path,
    source_bytes: bytes,
    source_hash: str,
    *,
    discover_related_sidecars: bool = True,
) -> tuple[dict[str, Any], Path, bytes, str, dict[str, Any] | None]:
    contract = str(payload.get("contract_version") or "")
    reviewed_path: Path | None = None
    wrapper_payload: dict[str, Any] | None = None
    wrapper_path: Path | None = None
    if contract == "pathgraph_candidate_v1":
        wrapper_payload = payload
        wrapper_path = resolved
        reviewed = payload.get("reviewed_template_candidate_path")
        if reviewed:
            reviewed_path = _resolve_source_path(str(reviewed), root)
    elif contract == "pathgraph_candidate_validation_report_v1":
        wrapper_path = resolved.parent / "pathgraph_candidate.json"
        if wrapper_path.exists():
            wrapper_payload = json.loads(wrapper_path.read_text(encoding="utf-8-sig"))
            reviewed = wrapper_payload.get("reviewed_template_candidate_path") if isinstance(wrapper_payload, dict) else None
            if reviewed:
                reviewed_path = _resolve_source_path(str(reviewed), root)
    if reviewed_path is None:
        return payload, resolved, source_bytes, source_hash, None
    reviewed_bytes = reviewed_path.read_bytes()
    reviewed_payload = json.loads(reviewed_bytes.decode("utf-8-sig"))
    if not isinstance(reviewed_payload, dict):
        raise ValueError("reviewed template candidate must be a JSON object")
    candidate_review = _pathgraph_candidate_review(
        wrapper_payload,
        wrapper_path,
        root,
        discover_related_sidecars=discover_related_sidecars,
    )
    return reviewed_payload, reviewed_path, reviewed_bytes, hashlib.sha256(reviewed_bytes).hexdigest(), candidate_review


def _pathgraph_candidate_review(
    wrapper_payload: dict[str, Any] | None,
    wrapper_path: Path | None,
    root: Path,
    *,
    discover_related_sidecars: bool = True,
) -> dict[str, Any] | None:
    if not isinstance(wrapper_payload, dict) or wrapper_payload.get("contract_version") != "pathgraph_candidate_v1":
        return None
    graph = _load_candidate_json(wrapper_payload.get("runtime_path_graph_candidate_path"), root)
    interface_map = _load_candidate_json(wrapper_payload.get("interface_map_candidate_path"), root)
    attachments = _list_of_dicts(wrapper_payload.get("detail_surface_attachments"))
    pending_requests = _list_of_dicts(wrapper_payload.get("pending_detail_observe_requests"))
    target_state_ids = {
        str(item.get("target_state_id") or "")
        for item in attachments
        if str(item.get("target_state_id") or "")
    }
    regions = _list_of_dicts(interface_map.get("regions") if isinstance(interface_map, dict) else [])
    actions = _list_of_dicts(graph.get("action_templates") if isinstance(graph, dict) else [])
    attached_regions = [
        item for item in regions if any(str(item.get("region_id") or "").startswith(f"{state_id}::") for state_id in target_state_ids)
    ]
    attached_actions = [
        item
        for item in actions
        if any(str(item.get("action_template_id") or "").startswith(f"{state_id}::") for state_id in target_state_ids)
    ]
    validation_report = _load_candidate_json(wrapper_payload.get("validation_report_path"), root)
    model_start_preflight = _load_model_start_preflight(wrapper_payload, wrapper_path, root)
    demo_readiness = _load_demo_readiness(wrapper_payload, wrapper_path, root)
    model_start_approval_packet = _load_model_start_approval_packet(wrapper_payload, wrapper_path, root)
    calibration_pre_run_check = _load_calibration_pre_run_check(wrapper_payload, wrapper_path, root)
    pathgraph_integration_readiness = _load_pathgraph_integration_readiness(wrapper_payload, wrapper_path, root)
    current_evidence_packet = _load_current_evidence_packet(wrapper_payload, wrapper_path, root)
    learn_mode_demo_scaffold = _load_learn_mode_demo_scaffold(
        wrapper_payload,
        wrapper_path,
        root,
        discover_related_sidecars=discover_related_sidecars,
    )
    precise_understanding_candidate = _load_precise_understanding_candidate(wrapper_payload, wrapper_path, root)
    page_detail_candidate = _load_page_detail_candidate(
        wrapper_payload,
        wrapper_path,
        root,
        discover_related_sidecars=discover_related_sidecars,
    )
    if not page_detail_candidate:
        scaffold_page_detail = learn_mode_demo_scaffold.get("page_detail_candidate")
        if (
            isinstance(scaffold_page_detail, dict)
            and scaffold_page_detail.get("contract_version") == "learn_page_detail_candidate_v1"
        ):
            page_detail_candidate = scaffold_page_detail
    learning_mode_demo_goal_readiness = _load_learning_mode_demo_goal_readiness(
        wrapper_payload,
        wrapper_path,
        root,
        discover_related_sidecars=discover_related_sidecars,
    )
    model_start_runbook = (
        wrapper_payload.get("model_start_runbook")
        if isinstance(wrapper_payload.get("model_start_runbook"), dict)
        else validation_report.get("model_start_runbook")
        if isinstance(validation_report.get("model_start_runbook"), dict)
        else {}
    )
    readiness_summary = _pathgraph_readiness_summary(
        graph=graph,
        interface_map=interface_map,
        wrapper_payload=wrapper_payload,
        validation_report=validation_report,
        model_start_preflight=model_start_preflight,
        demo_readiness=demo_readiness,
        model_start_approval_packet=model_start_approval_packet,
        calibration_pre_run_check=calibration_pre_run_check,
        pathgraph_integration_readiness=pathgraph_integration_readiness,
        current_evidence_packet=current_evidence_packet,
        precise_understanding_candidate=precise_understanding_candidate,
        page_detail_candidate=page_detail_candidate,
        learn_mode_demo_scaffold=learn_mode_demo_scaffold,
        learning_mode_demo_goal_readiness=learning_mode_demo_goal_readiness,
        attachments=attachments,
        pending_requests=pending_requests,
        attached_regions=attached_regions,
        attached_actions=attached_actions,
    )
    return {
        "contract_version": "pathgraph_candidate_review_v1",
        "pathgraph_candidate_path": _relative_path(wrapper_path, root) if wrapper_path else "",
        "runtime_path_graph_candidate_path": wrapper_payload.get("runtime_path_graph_candidate_path"),
        "interface_map_candidate_path": wrapper_payload.get("interface_map_candidate_path"),
        "validation_report_path": wrapper_payload.get("validation_report_path"),
        "pending_detail_observe_requests": pending_requests,
        "detail_surface_attachments": attachments,
        "attached_detail_regions": attached_regions,
        "attached_detail_actions": attached_actions,
        "detail_region_count": len(attached_regions),
        "detail_action_template_count": len(attached_actions),
        "pathgraph_readiness_summary": readiness_summary,
        "model_start_runbook": deepcopy(model_start_runbook),
        "model_start_preflight": deepcopy(model_start_preflight),
        "demo_readiness": deepcopy(demo_readiness),
        "model_start_approval_packet": deepcopy(model_start_approval_packet),
        "calibration_pre_run_check": deepcopy(calibration_pre_run_check),
        "pathgraph_integration_readiness": deepcopy(pathgraph_integration_readiness),
        "current_evidence_packet": deepcopy(current_evidence_packet),
        "precise_understanding_candidate": deepcopy(precise_understanding_candidate),
        "page_detail_candidate": deepcopy(page_detail_candidate),
        "learn_mode_demo_scaffold": deepcopy(learn_mode_demo_scaffold),
        "learning_mode_demo_goal_readiness": deepcopy(learning_mode_demo_goal_readiness),
        "precise_understanding_summary": wrapper_payload.get("precise_understanding_summary")
        if isinstance(wrapper_payload.get("precise_understanding_summary"), dict)
        else {},
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "no_dispatch": True,
        "candidate_only": True,
    }


def _learning_demo_artifact_review(
    wrapper_payload: dict[str, Any] | None,
    wrapper_path: Path | None,
    root: Path,
    *,
    discover_related_sidecars: bool = True,
) -> dict[str, Any] | None:
    if not isinstance(wrapper_payload, dict) or wrapper_path is None:
        return None
    contract = str(wrapper_payload.get("contract_version") or "")
    current_evidence_packet = _load_current_evidence_packet(wrapper_payload, wrapper_path, root)
    precise_understanding_candidate = _load_precise_understanding_candidate(wrapper_payload, wrapper_path, root)
    page_detail_candidate = (
        deepcopy(wrapper_payload)
        if contract == "learn_page_detail_candidate_v1"
        else _load_page_detail_candidate(wrapper_payload, wrapper_path, root)
        if discover_related_sidecars
        or bool(wrapper_payload.get("page_detail_candidate_path") or wrapper_payload.get("learn_page_detail_candidate_path"))
        or (wrapper_path.parent / PAGE_DETAIL_CANDIDATE_NAME).is_file()
        else {}
    )
    learn_mode_demo_scaffold = (
        deepcopy(wrapper_payload)
        if contract == "learn_mode_demo_scaffold_v1"
        else _load_learn_mode_demo_scaffold(wrapper_payload, wrapper_path, root)
        if discover_related_sidecars
        or bool(wrapper_payload.get("learn_mode_demo_scaffold_path"))
        or (wrapper_path.parent / LEARN_MODE_DEMO_SCAFFOLD_NAME).is_file()
        else {}
    )
    if contract == "learn_mode_demo_scaffold_v1" and not page_detail_candidate:
        scaffold_page_detail = wrapper_payload.get("page_detail_candidate")
        if (
            isinstance(scaffold_page_detail, dict)
            and scaffold_page_detail.get("contract_version") == "learn_page_detail_candidate_v1"
        ):
            page_detail_candidate = deepcopy(scaffold_page_detail)
    learning_mode_demo_goal_readiness = (
        _load_learning_mode_demo_goal_readiness(wrapper_payload, wrapper_path, root)
        if discover_related_sidecars
        or bool(wrapper_payload.get("learning_mode_demo_goal_readiness_path"))
        or (wrapper_path.parent / LEARNING_MODE_DEMO_GOAL_READINESS_NAME).is_file()
        else {}
    )
    if not any(
        (
            current_evidence_packet,
            precise_understanding_candidate,
            page_detail_candidate,
            learn_mode_demo_scaffold,
            learning_mode_demo_goal_readiness,
        )
    ):
        return None
    readiness_summary = {
        "contract_version": "learning_demo_artifact_readiness_summary_v1",
        "current_evidence_packet": deepcopy(current_evidence_packet),
        "precise_understanding_candidate": deepcopy(precise_understanding_candidate),
        "page_detail_candidate": deepcopy(page_detail_candidate),
        "learn_mode_demo_scaffold": deepcopy(learn_mode_demo_scaffold),
        "learning_mode_demo_goal_readiness": deepcopy(learning_mode_demo_goal_readiness),
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "no_dispatch": True,
        "candidate_only": True,
        "interpretation": "direct learning draft sidecars for panel display only; not Execute binding or click authorization",
    }
    return {
        "contract_version": "learning_demo_artifact_review_v1",
        "pathgraph_candidate_path": "",
        "runtime_path_graph_candidate_path": None,
        "interface_map_candidate_path": None,
        "validation_report_path": None,
        "pending_detail_observe_requests": [],
        "detail_surface_attachments": [],
        "attached_detail_regions": [],
        "attached_detail_actions": [],
        "detail_region_count": 0,
        "detail_action_template_count": 0,
        "pathgraph_readiness_summary": readiness_summary,
        "current_evidence_packet": deepcopy(current_evidence_packet),
        "precise_understanding_candidate": deepcopy(precise_understanding_candidate),
        "page_detail_candidate": deepcopy(page_detail_candidate),
        "learn_mode_demo_scaffold": deepcopy(learn_mode_demo_scaffold),
        "learning_mode_demo_goal_readiness": deepcopy(learning_mode_demo_goal_readiness),
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "no_dispatch": True,
        "candidate_only": True,
    }


def _pathgraph_readiness_summary(
    *,
    graph: dict[str, Any],
    interface_map: dict[str, Any],
    wrapper_payload: dict[str, Any],
    validation_report: dict[str, Any],
    model_start_preflight: dict[str, Any],
    demo_readiness: dict[str, Any],
    model_start_approval_packet: dict[str, Any],
    calibration_pre_run_check: dict[str, Any],
    pathgraph_integration_readiness: dict[str, Any],
    current_evidence_packet: dict[str, Any],
    precise_understanding_candidate: dict[str, Any],
    page_detail_candidate: dict[str, Any],
    learn_mode_demo_scaffold: dict[str, Any],
    learning_mode_demo_goal_readiness: dict[str, Any],
    attachments: list[dict[str, Any]],
    pending_requests: list[dict[str, Any]],
    attached_regions: list[dict[str, Any]],
    attached_actions: list[dict[str, Any]],
) -> dict[str, Any]:
    states = _list_of_dicts(graph.get("states") if isinstance(graph, dict) else [])
    regions = _list_of_dicts(interface_map.get("regions") if isinstance(interface_map, dict) else [])
    actions = _list_of_dicts(graph.get("action_templates") if isinstance(graph, dict) else [])
    transitions = _list_of_dicts(graph.get("transitions") if isinstance(graph, dict) else [])
    blockers: list[str] = []
    if not states:
        blockers.append("missing_states")
    if not regions:
        blockers.append("missing_regions")
    if not actions:
        blockers.append("missing_action_templates")
    if not transitions:
        blockers.append("missing_transitions")
    if not attachments:
        blockers.append("detail_surface_not_attached")
    if pending_requests and any(str(item.get("status") or "pending") != "attached" for item in pending_requests):
        blockers.append("pending_detail_observe_request_not_attached")
    if not attached_regions:
        blockers.append("missing_attached_detail_regions")
    if not attached_actions:
        blockers.append("missing_attached_detail_actions")
    if wrapper_payload.get("execute_binding_enabled") is not False:
        blockers.append("execute_binding_must_remain_disabled")
    if wrapper_payload.get("artifact_is_authorization") is not False:
        blockers.append("artifact_must_not_authorize_actions")
    validation_status = str(validation_report.get("validation_status") or wrapper_payload.get("validation_status") or "")
    if validation_status and validation_status not in {"passed_candidate", "needs_human_review"}:
        blockers.append(f"validation_status:{validation_status}")
    blockers.append("review_only_not_promoted")
    readiness_status = "needs_promotion_review" if len(blockers) == 1 else "blocked_from_promotion_review"
    promotion_review_gate = _pathgraph_promotion_review_gate(
        graph=graph,
        wrapper_payload=wrapper_payload,
        validation_report=validation_report,
        actions=actions,
        attachments=attachments,
    )
    model_start_runbook = (
        wrapper_payload.get("model_start_runbook")
        if isinstance(wrapper_payload.get("model_start_runbook"), dict)
        else validation_report.get("model_start_runbook")
        if isinstance(validation_report.get("model_start_runbook"), dict)
        else {}
    )
    return {
        "contract_version": "pathgraph_candidate_readiness_summary_v1",
        "readiness_status": readiness_status,
        "state_count": len(states),
        "region_count": len(regions),
        "action_template_count": len(actions),
        "transition_count": len(transitions),
        "detail_surface_attachment_count": len(attachments),
        "pending_detail_observe_request_count": len(pending_requests),
        "attached_detail_region_count": len(attached_regions),
        "attached_detail_action_count": len(attached_actions),
        "validation_status": validation_status,
        "promotion_review_blockers": blockers,
        "promotion_review_gate": promotion_review_gate,
        "model_start_runbook": deepcopy(model_start_runbook),
        "model_start_preflight": deepcopy(model_start_preflight),
        "demo_readiness": deepcopy(demo_readiness),
        "model_start_approval_packet": deepcopy(model_start_approval_packet),
        "calibration_pre_run_check": deepcopy(calibration_pre_run_check),
        "pathgraph_integration_readiness": deepcopy(pathgraph_integration_readiness),
        "current_evidence_packet": deepcopy(current_evidence_packet),
        "precise_understanding_candidate": deepcopy(precise_understanding_candidate),
        "page_detail_candidate": deepcopy(page_detail_candidate),
        "learn_mode_demo_scaffold": deepcopy(learn_mode_demo_scaffold),
        "learning_mode_demo_goal_readiness": deepcopy(learning_mode_demo_goal_readiness),
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "no_dispatch": True,
        "candidate_only": True,
        "interpretation": "readiness for human PathGraph promotion review only; not Execute binding or click authorization",
    }


def _pathgraph_promotion_review_gate(
    *,
    graph: dict[str, Any],
    wrapper_payload: dict[str, Any],
    validation_report: dict[str, Any],
    actions: list[dict[str, Any]],
    attachments: list[dict[str, Any]],
) -> dict[str, Any]:
    summary = validation_report.get("summary") if isinstance(validation_report.get("summary"), dict) else {}
    freshness = wrapper_payload.get("source_freshness_summary") if isinstance(wrapper_payload.get("source_freshness_summary"), dict) else {}
    semantic_actions = {str(item.get("semantic_action") or item.get("action_kind") or "").strip() for item in actions}
    semantic_actions.discard("")
    final_submit_actions = [
        str(item.get("action_template_id") or item.get("action_id") or "")
        for item in actions
        if _is_final_submit_like_action(item)
    ]
    checks = [
        _promotion_gate_check(
            "current_screen_freshness",
            freshness.get("freshness_status") == "verified" and freshness.get("checksum_status") in {"matched", "not_required"},
            {
                "freshness_status": freshness.get("freshness_status") or "missing",
                "checksum_status": freshness.get("checksum_status") or "missing",
                "warnings": freshness.get("warnings") if isinstance(freshness.get("warnings"), list) else [],
            },
        ),
        _promotion_gate_check(
            "action_taxonomy",
            bool(actions) and bool(semantic_actions),
            {"semantic_actions": sorted(semantic_actions), "action_count": len(actions)},
        ),
        _promotion_gate_check(
            "verification_rules",
            int(summary.get("verification_rule_count") or 0) > 0,
            {"verification_rule_count": int(summary.get("verification_rule_count") or 0)},
        ),
        _promotion_gate_check(
            "blockers_present",
            int(summary.get("blocker_count") or 0) > 0,
            {"blocker_count": int(summary.get("blocker_count") or 0)},
        ),
        _promotion_gate_check(
            "final_submit_safety",
            wrapper_payload.get("final_submit_forbidden") is not False and not final_submit_actions,
            {"final_submit_actions": final_submit_actions, "final_submit_forbidden": wrapper_payload.get("final_submit_forbidden") is not False},
        ),
        _promotion_gate_check(
            "no_dispatch_policy",
            wrapper_payload.get("execute_binding_enabled") is False
            and wrapper_payload.get("artifact_is_authorization") is False
            and all(item.get("no_dispatch") is not False for item in attachments),
            {
                "execute_binding_enabled": wrapper_payload.get("execute_binding_enabled") is True,
                "artifact_is_authorization": wrapper_payload.get("artifact_is_authorization") is True,
                "attachment_count": len(attachments),
            },
        ),
    ]
    failed = [item for item in checks if not item["passed"]]
    return {
        "contract_version": "pathgraph_promotion_review_gate_v1",
        "gate_status": "passed_for_human_promotion_review" if not failed else "blocked_from_promotion_review",
        "checks": checks,
        "failed_check_ids": [item["check_id"] for item in failed],
        "candidate_only": True,
        "no_dispatch": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "interpretation": "promotion review gate only; passing does not authorize Execute or clicks",
    }


def _promotion_gate_check(check_id: str, passed: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "passed": bool(passed),
        "evidence": evidence,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _is_final_submit_like_action(action: dict[str, Any]) -> bool:
    text = " ".join(
        str(action.get(key) or "")
        for key in ("semantic_action", "action_kind", "label", "description", "target_label")
    ).lower()
    return any(token in text for token in ("final_submit", "submit application", "send application", "complete application", "payment"))


def _load_candidate_json(path_value: Any, root: Path) -> dict[str, Any]:
    if not path_value:
        return {}
    path = _resolve_source_path(str(path_value), root)
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    return payload if isinstance(payload, dict) else {}


def _load_sidecar_by_source_path(
    *,
    wrapper_path: Path | None,
    root: Path,
    file_name: str,
    contract_version: str,
    source_field: str = "source_path",
    allow_global_search: bool = True,
) -> dict[str, Any]:
    if wrapper_path is None:
        return {}
    adjacent_candidates = [
        wrapper_path if wrapper_path.name == file_name else wrapper_path.parent / file_name,
        wrapper_path.parent / "pathgraph_candidate" / file_name,
        wrapper_path.parent.parent / file_name,
    ]
    seen_adjacent: set[str] = set()
    for path in adjacent_candidates:
        resolved_text = str(path.resolve())
        if resolved_text in seen_adjacent:
            continue
        seen_adjacent.add(resolved_text)
        payload = _load_matching_sidecar_candidate(
            path,
            wrapper_path=wrapper_path,
            root=root,
            contract_version=contract_version,
            source_field=source_field,
        )
        if payload:
            return payload
    if not allow_global_search:
        return {}
    search_roots = [root / "logs", root / "artifacts"]
    cache_key = (str(root.resolve()), file_name)
    if cache_key not in _SIDECAR_CANDIDATE_PATH_CACHE:
        candidates: list[Path] = []
        for search_root in search_roots:
            if search_root.exists():
                candidates.extend(path for path in search_root.rglob(file_name) if path.is_file())
        candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        _SIDECAR_CANDIDATE_PATH_CACHE[cache_key] = candidates
    candidates = _SIDECAR_CANDIDATE_PATH_CACHE[cache_key]
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        if not isinstance(payload, dict) or payload.get("contract_version") != contract_version:
            continue
        if _path_value_matches(payload.get(source_field), wrapper_path, root):
            return payload
    return {}


def _load_matching_sidecar_candidate(
    path: Path,
    *,
    wrapper_path: Path,
    root: Path,
    contract_version: str,
    source_field: str,
) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict) or payload.get("contract_version") != contract_version:
        return {}
    if path.resolve() == wrapper_path.resolve() or _path_value_matches(payload.get(source_field), wrapper_path, root):
        return payload
    return {}


def _path_value_matches(value: Any, target: Path, root: Path) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    raw = value.strip().replace("\\", "/")
    relative = _relative_path(target, root).replace("\\", "/")
    if raw == relative or raw == str(target.resolve()).replace("\\", "/"):
        return True
    try:
        return _resolve_source_path(value, root).resolve() == target.resolve()
    except Exception:
        return False


def _load_model_start_preflight(wrapper_payload: dict[str, Any], wrapper_path: Path | None, root: Path) -> dict[str, Any]:
    explicit = wrapper_payload.get("model_start_preflight_report_path")
    if explicit:
        payload = _load_candidate_json(explicit, root)
        return payload if payload.get("contract_version") == "learn_fusion_model_start_preflight_v1" else {}
    if wrapper_path is None:
        return {}
    sidecar = wrapper_path.parent / MODEL_START_PREFLIGHT_REPORT_NAME
    if not sidecar.exists():
        return {}
    payload = json.loads(sidecar.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        return {}
    return payload if payload.get("contract_version") == "learn_fusion_model_start_preflight_v1" else {}


def _load_demo_readiness(wrapper_payload: dict[str, Any], wrapper_path: Path | None, root: Path) -> dict[str, Any]:
    explicit = wrapper_payload.get("demo_readiness_report_path")
    if explicit:
        payload = _load_candidate_json(explicit, root)
        return payload if payload.get("contract_version") == "learn_fusion_demo_readiness_v1" else {}
    if wrapper_path is None:
        return {}
    sidecar = wrapper_path.parent / DEMO_READINESS_REPORT_NAME
    if not sidecar.exists():
        return {}
    payload = json.loads(sidecar.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        return {}
    return payload if payload.get("contract_version") == "learn_fusion_demo_readiness_v1" else {}


def _load_model_start_approval_packet(
    wrapper_payload: dict[str, Any], wrapper_path: Path | None, root: Path
) -> dict[str, Any]:
    explicit = wrapper_payload.get("model_start_approval_packet_path")
    if explicit:
        payload = _load_candidate_json(explicit, root)
        return payload if payload.get("contract_version") == "learn_fusion_model_start_approval_packet_v1" else {}
    if wrapper_path is None:
        return {}
    sidecar = wrapper_path.parent / MODEL_START_APPROVAL_PACKET_NAME
    if not sidecar.exists():
        return {}
    payload = json.loads(sidecar.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        return {}
    return payload if payload.get("contract_version") == "learn_fusion_model_start_approval_packet_v1" else {}


def _load_calibration_pre_run_check(
    wrapper_payload: dict[str, Any], wrapper_path: Path | None, root: Path
) -> dict[str, Any]:
    explicit = wrapper_payload.get("calibration_pre_run_check_report_path")
    if explicit:
        payload = _load_candidate_json(explicit, root)
        if payload.get("contract_version") != "learn_fusion_calibration_pre_run_check_v1":
            return {}
        return _annotate_calibration_pre_run_check(payload, root)
    if wrapper_path is None:
        return {}
    sidecar = wrapper_path.parent / CALIBRATION_PRE_RUN_CHECK_REPORT_NAME
    if not sidecar.exists():
        return {}
    payload = json.loads(sidecar.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        return {}
    if payload.get("contract_version") != "learn_fusion_calibration_pre_run_check_v1":
        return {}
    return _annotate_calibration_pre_run_check(payload, root)


def _annotate_calibration_pre_run_check(payload: dict[str, Any], root: Path) -> dict[str, Any]:
    report = deepcopy(payload)
    expected_sha256 = str(report.get("approval_packet_sha256") or "").strip()
    packet_path_value = report.get("approval_packet_path")
    if not expected_sha256:
        report["approval_packet_checksum_status"] = "missing_expected_sha256"
        return _apply_calibration_pre_run_checksum_effect(report)
    if not isinstance(packet_path_value, str) or not packet_path_value.strip():
        report["approval_packet_checksum_status"] = "missing_approval_packet_path"
        return _apply_calibration_pre_run_checksum_effect(report)
    try:
        packet_path = _resolve_source_path(packet_path_value, root)
        current_sha256 = hashlib.sha256(packet_path.read_bytes()).hexdigest()
    except FileNotFoundError:
        report["approval_packet_checksum_status"] = "approval_packet_missing"
        return _apply_calibration_pre_run_checksum_effect(report)
    except ValueError:
        report["approval_packet_checksum_status"] = "approval_packet_path_not_allowed"
        return _apply_calibration_pre_run_checksum_effect(report)
    except OSError as exc:
        report["approval_packet_checksum_status"] = "approval_packet_unreadable"
        report["approval_packet_checksum_error"] = str(exc)
        return _apply_calibration_pre_run_checksum_effect(report)
    report["approval_packet_current_sha256"] = current_sha256
    report["approval_packet_checksum_status"] = "matched" if current_sha256 == expected_sha256 else "mismatch"
    return _apply_calibration_pre_run_checksum_effect(report)


def _apply_calibration_pre_run_checksum_effect(report: dict[str, Any]) -> dict[str, Any]:
    checksum_status = str(report.get("approval_packet_checksum_status") or "unknown")
    if checksum_status == "matched":
        report["effective_pre_run_status"] = report.get("pre_run_status") or "unknown"
        report["effective_may_run_calibration_batch_now"] = report.get("may_run_calibration_batch_now") is True
        report["stale_pre_run_evidence"] = False
        return report
    report["effective_pre_run_status"] = "stale_pre_run_evidence"
    report["effective_may_run_calibration_batch_now"] = False
    report["stale_pre_run_evidence"] = True
    blockers = report.get("blockers") if isinstance(report.get("blockers"), list) else []
    blocker_id = f"approval_packet_checksum_{checksum_status}"
    if not any(isinstance(item, dict) and item.get("blocker_id") == blocker_id for item in blockers):
        blockers = [
            *blockers,
            {
                "blocker_id": blocker_id,
                "label": "Approval packet checksum does not match current pre-run evidence",
                "severity": "blocking",
                "approval_packet_checksum_status": checksum_status,
                "recommended_action": "regenerate_calibration_pre_run_check_after_reviewing_current_approval_packet",
            },
        ]
    report["blockers"] = blockers
    return report


def _load_pathgraph_integration_readiness(
    wrapper_payload: dict[str, Any], wrapper_path: Path | None, root: Path
) -> dict[str, Any]:
    explicit = wrapper_payload.get("pathgraph_integration_readiness_report_path")
    if explicit:
        payload = _load_candidate_json(explicit, root)
        return payload if payload.get("contract_version") == "learn_fusion_pathgraph_integration_readiness_report_v1" else {}
    if wrapper_path is None:
        return {}
    sidecar = wrapper_path.parent / PATHGRAPH_INTEGRATION_READINESS_REPORT_NAME
    if not sidecar.exists():
        return {}
    payload = json.loads(sidecar.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        return {}
    return payload if payload.get("contract_version") == "learn_fusion_pathgraph_integration_readiness_report_v1" else {}


def _load_current_evidence_packet(wrapper_payload: dict[str, Any], wrapper_path: Path | None, root: Path) -> dict[str, Any]:
    explicit = wrapper_payload.get("current_evidence_packet_path") or wrapper_payload.get(
        "learn_fusion_current_evidence_packet_path"
    )
    if explicit:
        payload = _load_candidate_json(explicit, root)
        return payload if payload.get("contract_version") == "learn_fusion_current_evidence_packet_v1" else {}
    if wrapper_path is None:
        return {}
    sidecar = wrapper_path.parent / CURRENT_EVIDENCE_PACKET_NAME
    if not sidecar.exists():
        return {}
    payload = json.loads(sidecar.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        return {}
    return payload if payload.get("contract_version") == "learn_fusion_current_evidence_packet_v1" else {}


def _load_precise_understanding_candidate(
    wrapper_payload: dict[str, Any], wrapper_path: Path | None, root: Path
) -> dict[str, Any]:
    explicit = wrapper_payload.get("precise_understanding_candidate_path") or wrapper_payload.get(
        "learn_precise_understanding_candidate_path"
    )
    if explicit:
        payload = _load_candidate_json(explicit, root)
        return payload if payload.get("contract_version") == "learn_precise_understanding_candidate_v1" else {}
    if wrapper_path is None:
        return {}
    sidecar = wrapper_path.parent / PRECISE_UNDERSTANDING_CANDIDATE_NAME
    if not sidecar.exists():
        return {}
    payload = json.loads(sidecar.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        return {}
    return payload if payload.get("contract_version") == "learn_precise_understanding_candidate_v1" else {}


def _load_page_detail_candidate(
    wrapper_payload: dict[str, Any],
    wrapper_path: Path | None,
    root: Path,
    *,
    discover_related_sidecars: bool = True,
) -> dict[str, Any]:
    explicit = wrapper_payload.get("page_detail_candidate_path") or wrapper_payload.get("learn_page_detail_candidate_path")
    if explicit:
        payload = _load_candidate_json(explicit, root)
        return payload if payload.get("contract_version") == "learn_page_detail_candidate_v1" else {}
    if wrapper_path is None:
        return {}
    sidecar = wrapper_path.parent / PAGE_DETAIL_CANDIDATE_NAME
    if not sidecar.exists():
        return _load_sidecar_by_source_path(
            wrapper_path=wrapper_path,
            root=root,
            file_name=PAGE_DETAIL_CANDIDATE_NAME,
            contract_version="learn_page_detail_candidate_v1",
            allow_global_search=discover_related_sidecars,
        )
    payload = json.loads(sidecar.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        return {}
    if payload.get("contract_version") == "learn_page_detail_candidate_v1":
        return payload
    return _load_sidecar_by_source_path(
        wrapper_path=wrapper_path,
        root=root,
        file_name=PAGE_DETAIL_CANDIDATE_NAME,
        contract_version="learn_page_detail_candidate_v1",
        allow_global_search=discover_related_sidecars,
    )


def _load_learn_mode_demo_scaffold(
    wrapper_payload: dict[str, Any],
    wrapper_path: Path | None,
    root: Path,
    *,
    discover_related_sidecars: bool = True,
) -> dict[str, Any]:
    explicit = wrapper_payload.get("learn_mode_demo_scaffold_path")
    if explicit:
        payload = _load_candidate_json(explicit, root)
        return payload if payload.get("contract_version") == "learn_mode_demo_scaffold_v1" else {}
    if wrapper_path is None:
        return {}
    sidecar = wrapper_path.parent / LEARN_MODE_DEMO_SCAFFOLD_NAME
    if not sidecar.exists():
        return _load_sidecar_by_source_path(
            wrapper_path=wrapper_path,
            root=root,
            file_name=LEARN_MODE_DEMO_SCAFFOLD_NAME,
            contract_version="learn_mode_demo_scaffold_v1",
            allow_global_search=discover_related_sidecars,
        )
    payload = json.loads(sidecar.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        return {}
    if payload.get("contract_version") == "learn_mode_demo_scaffold_v1":
        return payload
    return _load_sidecar_by_source_path(
        wrapper_path=wrapper_path,
        root=root,
        file_name=LEARN_MODE_DEMO_SCAFFOLD_NAME,
        contract_version="learn_mode_demo_scaffold_v1",
        allow_global_search=discover_related_sidecars,
    )


def _load_learning_mode_demo_goal_readiness(
    wrapper_payload: dict[str, Any],
    wrapper_path: Path | None,
    root: Path,
    *,
    discover_related_sidecars: bool = True,
) -> dict[str, Any]:
    explicit = wrapper_payload.get("learning_mode_demo_goal_readiness_path")
    if explicit:
        payload = _load_candidate_json(explicit, root)
        return payload if payload.get("contract_version") == "learning_mode_demo_goal_readiness_v1" else {}
    if wrapper_path is None:
        return {}
    sidecar = wrapper_path.parent / LEARNING_MODE_DEMO_GOAL_READINESS_NAME
    if not sidecar.exists():
        scaffold = _load_learn_mode_demo_scaffold(
            wrapper_payload,
            wrapper_path,
            root,
            discover_related_sidecars=discover_related_sidecars,
        )
        scaffold_report_path = scaffold.get("report_path") if isinstance(scaffold, dict) else None
        if not isinstance(scaffold_report_path, str) or not scaffold_report_path.strip():
            return {}
        scaffold_path = _resolve_source_path(scaffold_report_path, root)
        candidate = scaffold_path.parent / LEARNING_MODE_DEMO_GOAL_READINESS_NAME
        if not candidate.exists():
            return {}
        payload = json.loads(candidate.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict) or payload.get("contract_version") != "learning_mode_demo_goal_readiness_v1":
            return {}
        return payload if _path_value_matches(payload.get("source_scaffold_path"), scaffold_path, root) else {}
    payload = json.loads(sidecar.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        return {}
    if payload.get("contract_version") == "learning_mode_demo_goal_readiness_v1":
        return payload
    scaffold = _load_learn_mode_demo_scaffold(
        wrapper_payload,
        wrapper_path,
        root,
        discover_related_sidecars=discover_related_sidecars,
    )
    scaffold_report_path = scaffold.get("report_path") if isinstance(scaffold, dict) else None
    if not isinstance(scaffold_report_path, str) or not scaffold_report_path.strip():
        return {}
    scaffold_path = _resolve_source_path(scaffold_report_path, root)
    candidate = scaffold_path.parent / LEARNING_MODE_DEMO_GOAL_READINESS_NAME
    if not candidate.exists():
        return {}
    payload = json.loads(candidate.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or payload.get("contract_version") != "learning_mode_demo_goal_readiness_v1":
        return {}
    if _path_value_matches(payload.get("source_scaffold_path"), scaffold_path, root):
        return payload
    return {}


def _normalized_draft(draft: dict[str, Any]) -> dict[str, Any]:
    workflow = draft.get("workflow_draft") if isinstance(draft.get("workflow_draft"), dict) else {}
    interface = draft.get("interface_draft") if isinstance(draft.get("interface_draft"), dict) else {}
    safety = draft.get("safety") if isinstance(draft.get("safety"), dict) else {}
    return {
        "contract_version": draft.get("contract_version") or "learning_template_draft_v1",
        "screen_summary": draft.get("screen_summary") or "",
        "state_guess": draft.get("state_guess") or "",
        "states": _list_of_dicts(workflow.get("states") or draft.get("states")),
        "regions": _list_of_dicts(interface.get("regions") or draft.get("regions")),
        "action_templates": _list_of_dicts(workflow.get("action_templates") or draft.get("action_templates")),
        "blockers": _extract_blockers(draft, safety),
        "verification_rules": _list_of_dicts(workflow.get("verification_rules") or draft.get("verification_rules")),
        "agent_decision_points": _list_of_dicts(draft.get("agent_decision_points")),
        "operation_skills": _list_of_dicts_or_strings(draft.get("operation_skills")),
        "gate_contracts": _list_of_dicts_or_strings(draft.get("gate_contracts")),
        "learning_source": draft.get("learning_source") or "observe_model",
        "ui_hierarchy": deepcopy(draft.get("ui_hierarchy")) if isinstance(draft.get("ui_hierarchy"), dict) else {},
        "page_details": deepcopy(draft.get("page_details")) if isinstance(draft.get("page_details"), dict) else {},
        "notes": _list_of_dicts_or_strings(draft.get("notes")),
        "safety": safety,
    }


def _screen_understanding_preview(payload: dict[str, Any], *, root: Path) -> dict[str, Any]:
    classification = payload.get("classification") if isinstance(payload.get("classification"), dict) else {}
    inventory = payload.get("screen_inventory") if isinstance(payload.get("screen_inventory"), list) else []
    draft, _ = _select_draft(payload)
    page_details = draft.get("page_details") if isinstance(draft.get("page_details"), dict) else {}
    fusion_status = _preview_fusion_status(draft, root=root)
    preview = {
        "contract_version": "screen_understanding_preview_v1",
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "real_action_requires_gate": True,
        "source_status": "not_available",
        "counts": {
            "inventory_items": len(inventory),
            "review_only_regions": 0,
            "grounding_candidates": 0,
            "danger_zones": 0,
        },
        "review_only_regions": [],
        "grounding_candidates": [],
        "danger_zones": [],
        "interpretation": "screen understanding preview only; not a PathGraph, not click authorization, and not Execute binding",
    }
    if fusion_status:
        preview.update(fusion_status)
    if not classification:
        preview["review_only_regions"] = _preview_items(
            page_details.get("review_only_regions"),
            default_policy="review_only",
        )
        preview["grounding_candidates"] = _preview_items(
            page_details.get("grounding_candidates"),
            default_policy="grounding_candidate",
        )
        preview["danger_zones"] = _preview_items(
            page_details.get("danger_zones"),
            default_policy="danger_zone",
        )
        inventory_summary = (
            page_details.get("inventory_summary")
            if isinstance(page_details.get("inventory_summary"), dict)
            else {}
        )
        inventory_count = _int_or_none(inventory_summary.get("screen_inventory_count"))
        if inventory_count is None:
            inventory_count = len(inventory) or sum(
                len(preview[key])
                for key in ("review_only_regions", "grounding_candidates", "danger_zones")
            )
        preview["counts"] = {
            "inventory_items": inventory_count,
            "review_only_regions": len(preview["review_only_regions"]),
            "grounding_candidates": len(preview["grounding_candidates"]),
            "danger_zones": len(preview["danger_zones"]),
        }
        if fusion_status or any(preview[key] for key in ("review_only_regions", "grounding_candidates", "danger_zones")):
            preview["source_status"] = "available"
        return preview
    preview["source_status"] = "available"
    preview["review_only_regions"] = _preview_items(
        classification.get("rejected_non_actionable"),
        default_policy="review_only",
    ) + _preview_items(
        classification.get("needs_human_review"),
        default_policy="needs_human_review",
    )
    preview["grounding_candidates"] = _preview_items(
        classification.get("accepted_for_grounding"),
        default_policy="grounding_candidate",
    )
    preview["danger_zones"] = _preview_items(
        classification.get("danger_zones"),
        default_policy="danger_zone",
    )
    preview["counts"] = {
        "inventory_items": len(inventory),
        "review_only_regions": len(preview["review_only_regions"]),
        "grounding_candidates": len(preview["grounding_candidates"]),
        "danger_zones": len(preview["danger_zones"]),
    }
    return preview


def _preview_fusion_status(draft: dict[str, Any], *, root: Path) -> dict[str, Any]:
    page_details = draft.get("page_details") if isinstance(draft.get("page_details"), dict) else {}
    reviewed_overlay = str(page_details.get("human_review_overlay_path") or "").strip()
    if reviewed_overlay:
        reviewed_overlay_path = _preview_artifact_path(reviewed_overlay, root=root)
        return {
            "full_screen_understanding_overlay_path": reviewed_overlay_path,
            "compiled_overlay_path": reviewed_overlay_path,
            "fusion_summary": {
                "source": "human_review_overlay",
                "revision": _int_value(page_details.get("human_review_overlay_revision"), 0),
            },
            "fusion_not_accuracy": True,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    statuses = _fusion_source_statuses(page_details)
    for _, status in statuses:
        full_overlay = str(status.get("full_screen_understanding_overlay_path") or "").strip()
        compiled_overlay = str(status.get("compiled_overlay_path") or status.get("overlay_path") or "").strip()
        if not full_overlay and not compiled_overlay:
            continue
        backlog = status.get("calibration_backlog") if isinstance(status.get("calibration_backlog"), dict) else {}
        batch_plan = (
            status.get("calibration_batch_plan")
            if isinstance(status.get("calibration_batch_plan"), dict)
            else {}
        )
        handoff_report = (
            status.get("calibration_handoff_report")
            if isinstance(status.get("calibration_handoff_report"), dict)
            else {}
        )
        acceptance_report = (
            status.get("calibration_batch_acceptance_report")
            if isinstance(status.get("calibration_batch_acceptance_report"), dict)
            else {}
        )
        consistency_report = (
            status.get("calibration_handoff_consistency_report")
            if isinstance(status.get("calibration_handoff_consistency_report"), dict)
            else {}
        )
        model_start_runbook = (
            status.get("model_start_runbook")
            if isinstance(status.get("model_start_runbook"), dict)
            else {}
        )
        return {
            "full_screen_understanding_overlay_path": _preview_artifact_path(full_overlay, root=root),
            "compiled_overlay_path": _preview_artifact_path(compiled_overlay, root=root),
            "calibration_overlay_path": _preview_artifact_path(
                str(status.get("calibration_overlay_path") or "").strip(),
                root=root,
            ),
            "fusion_summary": deepcopy(status.get("summary")) if isinstance(status.get("summary"), dict) else {},
            "calibration_backlog_summary": deepcopy(backlog.get("summary")) if isinstance(backlog.get("summary"), dict) else {},
            "calibration_backlog_items": _list_of_dicts(backlog.get("items")),
            "calibration_batch_plan_summary": deepcopy(batch_plan.get("summary"))
            if isinstance(batch_plan.get("summary"), dict)
            else {},
            "calibration_batch_ready_region_numbers": deepcopy(batch_plan.get("ready_region_numbers"))
            if isinstance(batch_plan.get("ready_region_numbers"), list)
            else [],
            "calibration_batch_review_blocked_region_numbers": deepcopy(batch_plan.get("review_blocked_region_numbers"))
            if isinstance(batch_plan.get("review_blocked_region_numbers"), list)
            else [],
            "calibration_batch_run_command_preview": str(batch_plan.get("run_command_preview") or ""),
            "calibration_batch_command_executes_now": batch_plan.get("command_executes_now") is True,
            "post_batch_refresh_command_preview": str(batch_plan.get("post_batch_refresh_command_preview") or ""),
            "post_batch_refresh_command_executes_now": batch_plan.get("post_batch_refresh_command_executes_now") is True,
            "post_batch_refresh_requires_completed_batch": batch_plan.get("post_batch_refresh_requires_completed_batch") is True,
            "calibration_handoff_report": _preview_calibration_handoff_report(handoff_report),
            "calibration_batch_acceptance_report": _preview_calibration_batch_acceptance_report(acceptance_report),
            "calibration_handoff_consistency_report": _preview_calibration_handoff_consistency_report(consistency_report),
            "model_start_runbook": _preview_model_start_runbook(model_start_runbook),
            "evidence_integrity": _preview_evidence_integrity(status, root=root),
            "precise_understanding_readiness_summary": _preview_precise_understanding_readiness(
                status=status,
                backlog=backlog,
                batch_plan=batch_plan,
            ),
            "fusion_display_readiness": deepcopy(status.get("display_readiness"))
            if isinstance(status.get("display_readiness"), dict)
            else {},
            "fusion_not_accuracy": status.get("not_accuracy") is not False,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    screen = page_details.get("screen") if isinstance(page_details.get("screen"), dict) else {}
    source_image = str(
        screen.get("source_image_path")
        or screen.get("image_path")
        or screen.get("screenshot_path")
        or ""
    ).strip()
    compiled_overlay = str(screen.get("compiled_overlay_path") or screen.get("overlay_path") or "").strip()
    if source_image or compiled_overlay:
        return {
            "source_image_path": _preview_artifact_path(source_image, root=root),
            "compiled_overlay_path": _preview_artifact_path(compiled_overlay, root=root),
            "fusion_summary": {},
            "fusion_not_accuracy": True,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    return {}


def _preview_calibration_batch_acceptance_report(report: dict[str, Any]) -> dict[str, Any]:
    if not report:
        return {}
    coverage = report.get("coverage") if isinstance(report.get("coverage"), dict) else {}
    safety = report.get("safety") if isinstance(report.get("safety"), dict) else {}
    checks = report.get("checks") if isinstance(report.get("checks"), dict) else {}
    return {
        "contract_version": str(report.get("contract_version") or "learn_fusion_calibration_batch_acceptance_report_v1"),
        "acceptance_status": str(report.get("acceptance_status") or ""),
        "ready_for_post_batch_refresh": report.get("ready_for_post_batch_refresh") is True,
        "coverage": {
            "expected_ready_region_numbers": _list_of_ints(coverage.get("expected_ready_region_numbers")),
            "accepted_region_numbers": _list_of_ints(coverage.get("accepted_region_numbers")),
            "missing_ready_region_numbers": _list_of_ints(coverage.get("missing_ready_region_numbers")),
            "unexpected_region_numbers": _list_of_ints(coverage.get("unexpected_region_numbers")),
            "review_blocked_region_numbers_in_rerun": _list_of_ints(coverage.get("review_blocked_region_numbers_in_rerun")),
        },
        "checks": deepcopy(checks),
        "blockers": _list_of_strings(report.get("blockers")),
        "warnings": _list_of_strings(report.get("warnings")),
        "safety": {
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "final_submit_forbidden": safety.get("final_submit_forbidden") is not False,
            "real_clicks": _int_value(safety.get("real_clicks"), 0),
        },
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _preview_calibration_handoff_consistency_report(report: dict[str, Any]) -> dict[str, Any]:
    if not report:
        return {}
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    safety = report.get("safety") if isinstance(report.get("safety"), dict) else {}
    checks = report.get("checks") if isinstance(report.get("checks"), dict) else {}
    return {
        "contract_version": str(report.get("contract_version") or "learn_fusion_handoff_consistency_report_v1"),
        "consistency_status": str(report.get("consistency_status") or ""),
        "summary": {
            "readiness_status": str(summary.get("readiness_status") or ""),
            "handoff_status": str(summary.get("handoff_status") or ""),
            "acceptance_status": str(summary.get("acceptance_status") or ""),
            "ready_region_numbers": _list_of_ints(summary.get("ready_region_numbers")),
            "review_blocked_region_numbers": _list_of_ints(summary.get("review_blocked_region_numbers")),
            "post_batch_refresh_has_batch_plan": summary.get("post_batch_refresh_has_batch_plan") is True,
            "refresh_blocks_before_future_rerun": summary.get("refresh_blocks_before_future_rerun") is True,
        },
        "checks": deepcopy(checks),
        "blockers": _list_of_strings(report.get("blockers")),
        "safety": {
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "model_started": safety.get("model_started") is True,
            "live_clicks": _int_value(safety.get("live_clicks"), 0),
            "live_fills": _int_value(safety.get("live_fills"), 0),
            "live_submits": _int_value(safety.get("live_submits"), 0),
            "runtime_pathgraph_promotion": safety.get("runtime_pathgraph_promotion") is True,
        },
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _preview_model_start_runbook(report: dict[str, Any]) -> dict[str, Any]:
    if not report:
        return {}
    guards = report.get("guards") if isinstance(report.get("guards"), dict) else {}
    safety = report.get("safety") if isinstance(report.get("safety"), dict) else {}
    return {
        "contract_version": str(report.get("contract_version") or "learn_fusion_model_start_runbook_v1"),
        "runbook_status": str(report.get("runbook_status") or ""),
        "approval_required": report.get("approval_required") is True,
        "may_start_model_after_user_approval": report.get("may_start_model_after_user_approval") is True,
        "may_run_calibration_batch_now": False,
        "next_manual_action": str(report.get("next_manual_action") or ""),
        "ready_region_numbers": _list_of_ints(report.get("ready_region_numbers")),
        "review_blocked_region_numbers": _list_of_ints(report.get("review_blocked_region_numbers")),
        "guards": {
            "post_batch_refresh_has_batch_plan": guards.get("post_batch_refresh_has_batch_plan") is True,
            "prebatch_refresh_blocks_before_future_rerun": guards.get("prebatch_refresh_blocks_before_future_rerun") is True,
            "acceptance_required_before_refresh": guards.get("acceptance_required_before_refresh") is True,
            "accepted_for_post_batch_refresh": guards.get("accepted_for_post_batch_refresh") is True,
        },
        "safety": {
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "model_started": safety.get("model_started") is True,
            "live_clicks": _int_value(safety.get("live_clicks"), 0),
            "live_fills": _int_value(safety.get("live_fills"), 0),
            "live_submits": _int_value(safety.get("live_submits"), 0),
        },
        "blockers": _list_of_strings(report.get("blockers")),
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _preview_evidence_integrity(status: dict[str, Any], *, root: Path) -> dict[str, Any]:
    declared_paths = {
        "screenshot": status.get("screenshot_path"),
        "full_screen_understanding_overlay": status.get("full_screen_understanding_overlay_path"),
        "compiled_overlay": status.get("compiled_overlay_path") or status.get("overlay_path"),
        "source_status_report": status.get("source_status_report_path"),
        "source_calibration_report": status.get("source_calibration_report_path"),
    }
    evidence: dict[str, Any] = {
        "contract_version": "learn_precise_understanding_evidence_integrity_v1",
        "status": "no_declared_external_evidence",
        "required_for_pathgraph_review": True,
        "missing_declared_evidence": [],
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }
    declared_count = 0
    for name, raw_path in declared_paths.items():
        path_text = str(raw_path or "").strip()
        if not path_text:
            continue
        declared_count += 1
        item = _preview_file_evidence(name, path_text, root=root)
        evidence[name] = item
        if item["exists"] is not True:
            evidence["missing_declared_evidence"].append(name)
    if evidence["missing_declared_evidence"]:
        evidence["status"] = "missing_declared_evidence"
    elif declared_count:
        evidence["status"] = "complete"
    return evidence


def _preview_file_evidence(kind: str, path_text: str, *, root: Path) -> dict[str, Any]:
    path = Path(path_text)
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    exists = path.exists() and path.is_file()
    return {
        "kind": kind,
        "path": _relative_path(path, root),
        "declared_path": path_text,
        "exists": exists,
        "sha256": _sha256_file(path) if exists else "",
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _preview_calibration_handoff_report(report: dict[str, Any]) -> dict[str, Any]:
    if not report:
        return {}
    future_outputs = report.get("future_outputs") if isinstance(report.get("future_outputs"), dict) else {}
    safety = report.get("safety") if isinstance(report.get("safety"), dict) else {}
    return {
        "contract_version": str(report.get("contract_version") or "learn_fusion_calibration_handoff_report_v1"),
        "handoff_status": str(report.get("handoff_status") or ""),
        "safe_to_start_after_user_approval": report.get("safe_to_start_after_user_approval") is True,
        "ready_region_numbers": _list_of_ints(report.get("ready_region_numbers")),
        "review_blocked_region_numbers": _list_of_ints(report.get("review_blocked_region_numbers")),
        "future_outputs": {
            "rerun_report_status": str(future_outputs.get("rerun_report_status") or ""),
            "post_batch_refresh_requires_completed_batch": future_outputs.get("post_batch_refresh_requires_completed_batch") is True,
        },
        "blockers": _list_of_strings(report.get("blockers")),
        "warnings": _list_of_strings(report.get("warnings")),
        "safety": {
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "final_submit_forbidden": safety.get("final_submit_forbidden") is not False,
            "real_clicks": _int_value(safety.get("real_clicks"), 0),
            "live_fill": safety.get("live_fill") is True,
            "live_submit": safety.get("live_submit") is True,
        },
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _precise_understanding_readiness_summary(draft: dict[str, Any]) -> dict[str, Any]:
    page_details = draft.get("page_details") if isinstance(draft.get("page_details"), dict) else {}
    for _, status in _fusion_source_statuses(page_details):
        backlog = status.get("calibration_backlog") if isinstance(status.get("calibration_backlog"), dict) else {}
        batch_plan = status.get("calibration_batch_plan") if isinstance(status.get("calibration_batch_plan"), dict) else {}
        return _preview_precise_understanding_readiness(status=status, backlog=backlog, batch_plan=batch_plan)
    return {}


def _preview_precise_understanding_readiness(
    *,
    status: dict[str, Any],
    backlog: dict[str, Any],
    batch_plan: dict[str, Any],
) -> dict[str, Any]:
    summary = status.get("summary") if isinstance(status.get("summary"), dict) else {}
    backlog_summary = backlog.get("summary") if isinstance(backlog.get("summary"), dict) else {}
    pathgraph = status.get("pathgraph_preparation") if isinstance(status.get("pathgraph_preparation"), dict) else {}
    preflight = status.get("pathgraph_preflight_plan") if isinstance(status.get("pathgraph_preflight_plan"), dict) else {}
    preflight_summary = preflight.get("summary") if isinstance(preflight.get("summary"), dict) else {}
    pending_batch = preflight.get("pending_calibration_batch") if isinstance(preflight.get("pending_calibration_batch"), dict) else {}
    ready_regions = _list_of_ints(pending_batch.get("ready_region_numbers") if pending_batch else batch_plan.get("ready_region_numbers"))
    review_regions = _list_of_ints(
        pending_batch.get("review_blocked_region_numbers") if pending_batch else batch_plan.get("review_blocked_region_numbers")
    )
    total = _int_value(summary.get("total_locator_cards"), summary.get("attempted"))
    pending_count = len(ready_regions) + len(review_regions)
    uncalibrated = _int_value(summary.get("uncalibrated_locator_cards"), backlog_summary.get("uncalibrated_locator_cards"))
    if uncalibrated == 0 and not _has_int_value(summary.get("uncalibrated_locator_cards"), backlog_summary.get("uncalibrated_locator_cards")):
        uncalibrated = pending_count
    calibrated = _int_value(summary.get("calibrated_cases"))
    if calibrated == 0 and total:
        calibrated = max(total - uncalibrated, 0)
    rate: float | str = round(calibrated / total, 4) if total else "not_covered"
    ready_for_promotion = preflight_summary.get("ready_for_runtime_pathgraph_promotion") is True
    readiness_status = (
        "needs_pending_calibration"
        if pending_count
        else "ready_for_manual_runtime_promotion_review"
        if ready_for_promotion
        else "not_covered"
        if not total
        else "needs_pathgraph_review"
    )
    return {
        "readiness_status": readiness_status,
        "total_locator_cards": total,
        "calibrated_cases": calibrated,
        "uncalibrated_locator_cards": uncalibrated,
        "calibration_coverage_rate": rate,
        "pending_calibration_ready_count": _int_value(preflight_summary.get("pending_calibration_ready_count"), len(ready_regions)),
        "pending_calibration_review_count": _int_value(preflight_summary.get("pending_calibration_review_count"), len(review_regions)),
        "pathgraph_status": str(pathgraph.get("status") or "missing"),
        "ready_for_runtime_pathgraph_promotion": ready_for_promotion,
        "display_only": True,
        "not_accuracy": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _preview_artifact_path(value: str, *, root: Path) -> str:
    value = str(value or "").strip()
    if not value:
        return ""
    path = Path(value)
    if path.is_absolute():
        return _relative_path(path, root)
    return path.as_posix()


def _preview_items(value: Any, *, default_policy: str) -> list[dict[str, Any]]:
    items = value if isinstance(value, list) else []
    return [_preview_item(item, default_policy=default_policy) for item in items if isinstance(item, dict)]


def _preview_item(item: dict[str, Any], *, default_policy: str) -> dict[str, Any]:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    cross_evidence = metadata.get("cross_evidence") if isinstance(metadata.get("cross_evidence"), dict) else {}
    return {
        "item_id": str(item.get("item_id") or item.get("region_id") or item.get("source_item_id") or item.get("id") or ""),
        "label": str(item.get("label") or item.get("text") or ""),
        "item_type": str(item.get("item_type") or ""),
        "role": str(item.get("role") or ""),
        "bbox": deepcopy(item.get("bbox") if isinstance(item.get("bbox"), dict) else {}),
        "source_evidence": deepcopy(item.get("source_evidence") if isinstance(item.get("source_evidence"), list) else []),
        "evidence_level": str(item.get("evidence_level") or ""),
        "grounding_eligible": bool(item.get("grounding_eligible")),
        "review_only": bool(item.get("review_only")),
        "grounding_block_reason": str(item.get("grounding_block_reason") or ""),
        "display_policy": default_policy,
        "cross_evidence": deepcopy(cross_evidence),
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def _extract_blockers(draft: dict[str, Any], safety: dict[str, Any]) -> list[dict[str, Any]]:
    blockers = draft.get("blockers")
    if isinstance(blockers, list):
        return _list_of_dicts(blockers)
    safety_blockers = safety.get("blockers")
    if isinstance(safety_blockers, list):
        return _list_of_dicts(safety_blockers)
    return []


def _prepare_human_review_patch(
    review_patch: dict[str, Any],
    *,
    review: dict[str, Any],
    draft: dict[str, Any],
    root: Path,
    out_dir: Path,
) -> tuple[dict[str, Any], Path | None]:
    if review_patch.get("contract_version") != HUMAN_REVIEW_PATCH_CONTRACT:
        return {}, None

    screenshot_path = str(review_patch.get("screenshot_path") or "").strip()
    screenshot_sha256 = str(review_patch.get("screenshot_sha256") or "").strip().lower()
    if not screenshot_path or not screenshot_sha256:
        raise ValueError("human_review_patch requires screenshot_path and screenshot_sha256")
    source_image = _draft_source_image_evidence(draft)
    source_path = str(source_image.get("path") or "").strip()
    if source_path and _relative_path(_resolve_optional_under_root(screenshot_path, root), root) != _relative_path(
        _resolve_optional_under_root(source_path, root), root
    ):
        raise ValueError("human_review_patch screenshot_path does not match the learning draft source image")
    screenshot = _resolve_optional_under_root(screenshot_path, root)
    if not screenshot.exists() or not screenshot.is_file():
        raise ValueError("human_review_patch screenshot file is missing")
    actual_sha256 = hashlib.sha256(screenshot.read_bytes()).hexdigest()
    if actual_sha256 != screenshot_sha256:
        raise ValueError("human_review_patch screenshot checksum mismatch")
    expected_sha256 = str(source_image.get("sha256") or "").strip().lower()
    if expected_sha256 and expected_sha256 != screenshot_sha256:
        raise ValueError("human_review_patch screenshot checksum is stale for the learning draft")
    try:
        with Image.open(screenshot) as source_image_file:
            source_image_file.load()
            screenshot_size = source_image_file.size
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ValueError("human_review_patch screenshot is not a decodable image") from exc

    operations = _normalize_human_review_operations(
        review_patch.get("operations"),
        draft,
        screenshot_size=screenshot_size,
    )
    revision, patch_path = _next_human_review_patch_path(out_dir)
    normalized = {
        "contract_version": HUMAN_REVIEW_PATCH_CONTRACT,
        "revision": revision,
        "created_at": datetime.now().isoformat(),
        "source_draft_path": review.get("source", {}).get("source_path"),
        "source_draft_sha256": review.get("source", {}).get("sha256"),
        "screenshot_path": _relative_path(screenshot, root),
        "screenshot_sha256": screenshot_sha256,
        "reason": str(review_patch.get("reason") or "").strip(),
        "source": str(review_patch.get("source") or "human_panel_editor_v1").strip(),
        "operations": operations,
        "operation_count": len(operations),
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "final_submit_forbidden": True,
        "authorization_scope": "display_and_review_only",
    }
    return normalized, patch_path


def _normalize_human_review_operations(
    value: Any,
    draft: dict[str, Any],
    *,
    screenshot_size: tuple[int, int],
) -> list[dict[str, Any]]:
    operations = _list_of_dicts(value)
    regions = {
        str(item.get("region_id") or "").strip(): deepcopy(item)
        for item in _list_of_dicts(draft.get("regions"))
    }
    actions = {
        str(item.get("action_template_id") or item.get("action_id") or "").strip(): deepcopy(item)
        for item in _list_of_dicts(draft.get("action_templates"))
    }
    stage2 = _hierarchy_ownership_stage2(draft)
    ownership_stage2 = deepcopy(stage2) if stage2 else None
    has_ownership_operation = False
    normalized: list[dict[str, Any]] = []
    for index, operation in enumerate(operations):
        op = str(operation.get("op") or "").strip()
        if op == "resolve_ownership":
            operation = _normalize_ownership_target_contract(
                operation,
                index=index,
            )
        target_kind = str(operation.get("target_kind") or "").strip()
        target_id = str(operation.get("target_id") or "").strip()
        if op == "resolve_ownership":
            has_ownership_operation = True
            if ownership_stage2 is None:
                raise ValueError("human_review_patch ownership stage2 evidence is missing")
            normalized_operation = _normalize_ownership_operation(
                operation,
                ownership_stage2,
                index=index,
            )
            normalized.append(normalized_operation)
            _apply_normalized_ownership_operation(
                ownership_stage2,
                normalized_operation,
            )
            continue
        items = actions if target_kind == "action" else regions if target_kind == "region" else {}
        if target_kind not in {"region", "action"} or not target_id:
            raise ValueError(f"human_review_patch operation {index} has invalid target")
        if op == "add":
            if target_id in items:
                raise ValueError(f"human_review_patch operation {index} target already exists: {target_kind}:{target_id}")
            item = deepcopy(operation.get("item")) if isinstance(operation.get("item"), dict) else {}
            id_key = "action_template_id" if target_kind == "action" else "region_id"
            item[id_key] = target_id
            if _normalized_bbox(item.get("bbox")) is None:
                raise ValueError(f"human_review_patch operation {index} has invalid added bbox")
            item["bbox"] = _normalized_bbox(item["bbox"])
            if not _bbox_within_image(item["bbox"], screenshot_size):
                raise ValueError(f"human_review_patch operation {index} bbox is outside screenshot bounds")
            normalized.append(
                {
                    "op": op,
                    "target_kind": target_kind,
                    "target_id": target_id,
                    "item": item,
                    "reason": str(operation.get("reason") or "").strip(),
                }
            )
            items[target_id] = item
            continue
        item = items.get(target_id)
        if item is None:
            raise ValueError(f"human_review_patch operation {index} target does not exist: {target_kind}:{target_id}")
        if op == "delete":
            normalized.append(
                {
                    "op": op,
                    "target_kind": target_kind,
                    "target_id": target_id,
                    "before_item": deepcopy(item),
                    "reason": str(operation.get("reason") or "").strip(),
                }
            )
            items.pop(target_id, None)
            continue
        if op == "update_role":
            if target_kind != "region":
                raise ValueError(f"human_review_patch operation {index} role target must be a region")
            before_value = str(operation.get("before_value") or "").strip()
            current_value = str(item.get("role") or item.get("region_type") or "").strip()
            if before_value and before_value != current_value:
                raise ValueError(f"human_review_patch operation {index} before_value is stale")
            after_value = str(operation.get("after_value") or "").strip()
            if not after_value:
                raise ValueError(f"human_review_patch operation {index} after_value is required")
            normalized.append(
                {
                    "op": op,
                    "target_kind": target_kind,
                    "target_id": target_id,
                    "before_value": current_value,
                    "after_value": after_value,
                    "reason": str(operation.get("reason") or "").strip(),
                }
            )
            item["role"] = after_value
            continue
        if op == "update_parent":
            if target_kind != "region":
                raise ValueError(f"human_review_patch operation {index} parent target must be a region")
            before_value = str(operation.get("before_value") or "").strip()
            current_value = str(item.get("parent_region_id") or "").strip()
            if before_value != current_value:
                raise ValueError(f"human_review_patch operation {index} before_value is stale")
            after_value = str(operation.get("after_value") or "").strip()
            if after_value == target_id or (after_value and after_value not in regions):
                raise ValueError(f"human_review_patch operation {index} parent target is invalid")
            normalized.append(
                {
                    "op": op,
                    "target_kind": target_kind,
                    "target_id": target_id,
                    "before_value": current_value,
                    "after_value": after_value,
                    "reason": str(operation.get("reason") or "").strip(),
                }
            )
            item["parent_region_id"] = after_value
            continue
        if op == "update_metadata":
            after_metadata = _normalize_human_review_metadata(operation.get("after_metadata"))
            if not after_metadata:
                raise ValueError(f"human_review_patch operation {index} after_metadata is required")
            before_metadata = {key: deepcopy(item.get(key)) for key in after_metadata}
            normalized.append(
                {
                    "op": op,
                    "target_kind": target_kind,
                    "target_id": target_id,
                    "before_metadata": before_metadata,
                    "after_metadata": after_metadata,
                    "reason": str(operation.get("reason") or "").strip(),
                }
            )
            item.update(deepcopy(after_metadata))
            continue
        if op != "update_bbox":
            raise ValueError(f"human_review_patch operation {index} has unsupported op: {op}")
        current_bbox = _normalized_bbox(item.get("bbox"))
        before_bbox = _normalized_bbox(operation.get("before_bbox"))
        after_bbox = _normalized_bbox(operation.get("after_bbox"))
        if current_bbox is None or after_bbox is None:
            raise ValueError(f"human_review_patch operation {index} has invalid bbox")
        if not _bbox_within_image(after_bbox, screenshot_size):
            raise ValueError(f"human_review_patch operation {index} bbox is outside screenshot bounds")
        if before_bbox is not None and before_bbox != current_bbox:
            raise ValueError(f"human_review_patch operation {index} before_bbox is stale")
        normalized.append(
            {
                "op": op,
                "target_kind": target_kind,
                "target_id": target_id,
                "before_bbox": before_bbox or current_bbox,
                "after_bbox": after_bbox,
                "reason": str(operation.get("reason") or "").strip(),
            }
        )
        item["bbox"] = after_bbox
    _validate_region_parent_graph(regions)
    if has_ownership_operation:
        remaining = _multiple_leaf_ownership(ownership_stage2 or {})
        if remaining:
            item_ids = ", ".join(sorted(remaining))
            raise ValueError(
                f"human_review_patch multiple leaf ownership remains: {item_ids}"
            )
    return normalized


def _normalize_ownership_target_contract(
    operation: dict[str, Any],
    *,
    index: int,
) -> dict[str, Any]:
    target_kind = str(operation.get("target_kind") or "").strip()
    target_id = str(operation.get("target_id") or "").strip()
    if target_kind not in {"ownership", "leaf"} or not target_id:
        raise ValueError(
            f"human_review_patch operation {index} has invalid ownership target"
        )

    normalized = deepcopy(operation)
    parent_target_kind = str(
        operation.get("parent_target_kind") or ""
    ).strip()
    parent_target_id = str(operation.get("parent_target_id") or "").strip()
    after_parent_group_id = str(
        operation.get("after_parent_group_id") or ""
    ).strip()
    if target_kind == "leaf":
        if parent_target_kind != "parent" or not parent_target_id:
            raise ValueError(
                f"human_review_patch operation {index} has invalid ownership parent target"
            )
        if after_parent_group_id and after_parent_group_id != parent_target_id:
            raise ValueError(
                f"human_review_patch operation {index} ownership parent targets disagree"
            )
        normalized["target_kind"] = "ownership"
        normalized["after_parent_group_id"] = parent_target_id
        normalized.pop("parent_target_kind", None)
        normalized.pop("parent_target_id", None)
        return normalized

    if parent_target_kind or parent_target_id:
        if parent_target_kind != "parent" or not parent_target_id:
            raise ValueError(
                f"human_review_patch operation {index} has invalid ownership parent target"
            )
        if after_parent_group_id and after_parent_group_id != parent_target_id:
            raise ValueError(
                f"human_review_patch operation {index} ownership parent targets disagree"
            )
        normalized["after_parent_group_id"] = parent_target_id
        normalized.pop("parent_target_kind", None)
        normalized.pop("parent_target_id", None)
    return normalized


def _hierarchy_ownership_stage2(draft: dict[str, Any]) -> dict[str, Any] | None:
    page_details = (
        draft.get("page_details")
        if isinstance(draft.get("page_details"), dict)
        else {}
    )
    two_stage = (
        page_details.get("two_stage_understanding")
        if isinstance(page_details.get("two_stage_understanding"), dict)
        else {}
    )
    stage2 = two_stage.get("stage2_numbering")
    return stage2 if isinstance(stage2, dict) else None


def _normalize_ownership_operation(
    operation: dict[str, Any],
    stage2: dict[str, Any],
    *,
    index: int,
) -> dict[str, Any]:
    region_id = str(operation.get("region_id") or "").strip()
    item_id = str(operation.get("target_id") or "").strip()
    regions = [
        region
        for region in stage2.get("regions", [])
        if isinstance(region, dict)
        and str(region.get("region_id") or "").strip() == region_id
    ]
    if len(regions) != 1:
        raise ValueError(
            f"human_review_patch operation {index} ownership region does not exist exactly once"
        )
    region = regions[0]
    item_numbers = {
        str(item.get("item_id") or "").strip(): str(item.get("number") or "").strip()
        for item in region.get("numbered_items", [])
        if isinstance(item, dict) and str(item.get("item_id") or "").strip()
    }
    if item_id not in item_numbers:
        raise ValueError(
            f"human_review_patch operation {index} ownership item does not exist: {item_id}"
        )
    groups = _validated_ownership_groups(region, index=index)
    after_parent_group_id = str(
        operation.get("after_parent_group_id") or ""
    ).strip()
    if after_parent_group_id not in groups:
        raise ValueError(
            f"human_review_patch operation {index} ownership parent group does not exist: "
            f"{after_parent_group_id}"
        )
    current_owners = _leaf_owner_ids(region, item_id)
    before_parent_group_ids = sorted(
        {
            str(value or "").strip()
            for value in operation.get("before_parent_group_ids", [])
            if str(value or "").strip()
        }
    ) if isinstance(operation.get("before_parent_group_ids"), list) else []
    if before_parent_group_ids != current_owners:
        raise ValueError(
            f"human_review_patch operation {index} ownership parent set is stale"
        )
    if len(current_owners) < 2 or after_parent_group_id not in current_owners:
        raise ValueError(
            f"human_review_patch operation {index} ownership correction must select one current leaf owner"
        )
    return {
        "op": "resolve_ownership",
        "target_kind": "ownership",
        "target_id": item_id,
        "region_id": region_id,
        "before_parent_group_ids": current_owners,
        "after_parent_group_id": after_parent_group_id,
        "removed_from_group_ids": [
            group_id
            for group_id in current_owners
            if group_id != after_parent_group_id
        ],
        "item_number": item_numbers[item_id],
        "reason": str(operation.get("reason") or "").strip(),
    }


def _validated_ownership_groups(
    region: dict[str, Any],
    *,
    index: int,
) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for group in region.get("subregion_groups", []):
        if not isinstance(group, dict):
            raise ValueError(
                f"human_review_patch operation {index} ownership group must be an object"
            )
        group_id = str(group.get("group_id") or "").strip()
        if not group_id or group_id in groups:
            raise ValueError(
                f"human_review_patch operation {index} ownership group id is invalid"
            )
        groups[group_id] = group
    for group_id, group in groups.items():
        parent_group_id = str(
            group.get("parent_group_id")
            or group.get("resolved_parent_group_id")
            or ""
        ).strip()
        if parent_group_id and (
            parent_group_id == group_id or parent_group_id not in groups
        ):
            raise ValueError(
                f"human_review_patch operation {index} ownership parent is invalid: "
                f"{group_id}->{parent_group_id}"
            )
        member_ids = group.get("member_item_ids")
        if member_ids is not None and not isinstance(member_ids, list):
            raise ValueError(
                f"human_review_patch operation {index} ownership membership must be an array"
            )
    return groups


def _leaf_owner_ids(region: dict[str, Any], item_id: str) -> list[str]:
    groups = {
        str(group.get("group_id") or "").strip(): group
        for group in region.get("subregion_groups", [])
        if isinstance(group, dict) and str(group.get("group_id") or "").strip()
    }
    parent_group_ids = {
        str(
            group.get("parent_group_id")
            or group.get("resolved_parent_group_id")
            or ""
        ).strip()
        for group in groups.values()
        if str(
            group.get("parent_group_id")
            or group.get("resolved_parent_group_id")
            or ""
        ).strip()
    }
    return sorted(
        group_id
        for group_id, group in groups.items()
        if group_id not in parent_group_ids
        and item_id
        in {
            str(member_id or "").strip()
            for member_id in group.get("member_item_ids", [])
        }
    )


def _multiple_leaf_ownership(stage2: dict[str, Any]) -> dict[str, list[str]]:
    conflicts: dict[str, list[str]] = {}
    for region in stage2.get("regions", []):
        if not isinstance(region, dict):
            raise ValueError("human_review_patch ownership region must be an object")
        _validated_ownership_groups(region, index=0)
        item_ids = {
            str(item.get("item_id") or "").strip()
            for item in region.get("numbered_items", [])
            if isinstance(item, dict) and str(item.get("item_id") or "").strip()
        }
        for item_id in sorted(item_ids):
            owners = _leaf_owner_ids(region, item_id)
            if len(owners) > 1:
                conflicts[f"{region.get('region_id')}:{item_id}"] = owners
    return conflicts


def _apply_normalized_ownership_operation(
    stage2: dict[str, Any],
    operation: dict[str, Any],
) -> None:
    region = next(
        region
        for region in stage2.get("regions", [])
        if isinstance(region, dict)
        and str(region.get("region_id") or "").strip() == operation["region_id"]
    )
    item_id = operation["target_id"]
    item_number = operation["item_number"]
    removed_groups = set(operation["removed_from_group_ids"])
    canonical_groups = {
        str(group.get("group_id") or "").strip(): group
        for group in region.get("subregion_groups", [])
        if isinstance(group, dict) and str(group.get("group_id") or "").strip()
    }
    mirror_groups = _ownership_mirror_groups(
        region,
        required_group_ids=removed_groups,
    )
    for group_id in sorted(removed_groups):
        canonical = canonical_groups[group_id]
        mirror = mirror_groups.get(group_id)
        if mirror is not None and (
            _ownership_member_ids(mirror) != _ownership_member_ids(canonical)
            or _ownership_member_numbers(mirror)
            != _ownership_member_numbers(canonical)
        ):
            raise ValueError(
                f"human_review_patch ownership mirror is stale: {group_id}"
            )
        _remove_ownership_member(
            canonical,
            item_id=item_id,
            item_number=item_number,
        )
        if mirror is not None:
            _remove_ownership_member(
                mirror,
                item_id=item_id,
                item_number=item_number,
            )


def _ownership_mirror_groups(
    region: dict[str, Any],
    *,
    required_group_ids: set[str],
) -> dict[str, dict[str, Any]]:
    streams = region.get("stage2_streams")
    if streams is None:
        return {}
    if not isinstance(streams, dict):
        raise ValueError("human_review_patch ownership stage2_streams must be an object")
    semantic_groups = streams.get("semantic_groups")
    if semantic_groups is None:
        return {}
    if not isinstance(semantic_groups, list):
        raise ValueError(
            "human_review_patch ownership semantic_groups mirror must be an array"
        )
    mirrors: dict[str, dict[str, Any]] = {}
    for group in semantic_groups:
        if not isinstance(group, dict):
            raise ValueError(
                "human_review_patch ownership semantic group mirror must be an object"
            )
        group_id = str(group.get("group_id") or "").strip()
        if not group_id or group_id in mirrors:
            raise ValueError(
                "human_review_patch ownership semantic group mirror id is invalid"
            )
        mirrors[group_id] = group
    missing = sorted(required_group_ids - mirrors.keys())
    if missing:
        raise ValueError(
            "human_review_patch ownership semantic group mirror is missing: "
            + ", ".join(missing)
        )
    return mirrors


def _ownership_member_ids(group: dict[str, Any]) -> list[str]:
    values = group.get("member_item_ids")
    if not isinstance(values, list):
        raise ValueError("human_review_patch ownership membership must be an array")
    return [str(value or "").strip() for value in values]


def _ownership_member_numbers(group: dict[str, Any]) -> list[str] | None:
    values = group.get("member_numbers")
    if values is None:
        return None
    if not isinstance(values, list):
        raise ValueError(
            "human_review_patch ownership member numbers must be an array"
        )
    return [str(value or "").strip() for value in values]


def _remove_ownership_member(
    group: dict[str, Any],
    *,
    item_id: str,
    item_number: str,
) -> None:
    member_ids = _ownership_member_ids(group)
    member_numbers = _ownership_member_numbers(group)
    if member_numbers is not None:
        if len(member_numbers) != len(member_ids):
            raise ValueError(
                "human_review_patch ownership member numbers are inconsistent"
            )
        kept_pairs = [
            (member_id, member_number)
            for member_id, member_number in zip(member_ids, member_numbers)
            if member_id != item_id
        ]
        group["member_item_ids"] = [member_id for member_id, _ in kept_pairs]
        group["member_numbers"] = [number for _, number in kept_pairs]
    else:
        group["member_item_ids"] = [
            member_id for member_id in member_ids if member_id != item_id
        ]
    if "current_evidence_member_count" in group:
        group["current_evidence_member_count"] = len(group["member_item_ids"])
    if item_id in group["member_item_ids"]:
        raise ValueError("human_review_patch ownership member removal failed")
    if item_number and item_number in group.get("member_numbers", []):
        raise ValueError("human_review_patch ownership number removal failed")


def _normalize_human_review_metadata(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    normalized: dict[str, Any] = {}
    for key in (
        "label",
        "description",
        "semantic_action",
        "action_type",
        "input_semantics",
        "verification_rule",
        "risk_level",
    ):
        if key in source:
            normalized[key] = str(source.get(key) or "").strip()
    if "requires_confirmation" in source:
        normalized["requires_confirmation"] = source.get("requires_confirmation") is True
    if "destination" in source:
        destination = source.get("destination") if isinstance(source.get("destination"), dict) else {}
        kind = str(destination.get("kind") or "none").strip().lower()
        if kind not in {"none", "interface", "url"}:
            raise ValueError(f"human_review_patch destination kind is invalid: {kind}")
        normalized_destination: dict[str, Any] = {"kind": kind}
        if kind == "interface":
            normalized_destination["target_interface_id"] = str(
                destination.get("target_interface_id") or ""
            ).strip()
        elif kind == "url":
            normalized_destination["url"] = str(destination.get("url") or "").strip()
        normalized["destination"] = normalized_destination
    semantic_action = str(normalized.get("semantic_action") or normalized.get("action_type") or "").lower()
    if semantic_action in {"final_submit", "send", "confirm", "payment"}:
        normalized["risk_level"] = "dangerous"
        normalized["requires_confirmation"] = True
    return normalized


def _bbox_within_image(bbox: dict[str, int], screenshot_size: tuple[int, int]) -> bool:
    image_width, image_height = screenshot_size
    return (
        bbox["x"] >= 0
        and bbox["y"] >= 0
        and bbox["x"] + bbox["w"] <= image_width
        and bbox["y"] + bbox["h"] <= image_height
    )


def _validate_region_parent_graph(regions: dict[str, dict[str, Any]]) -> None:
    for region_id in regions:
        visited: set[str] = set()
        current_id = region_id
        while current_id:
            if current_id in visited:
                raise ValueError(f"human_review_patch parent cycle detected at region: {current_id}")
            visited.add(current_id)
            current = regions.get(current_id)
            if current is None:
                break
            current_id = str(current.get("parent_region_id") or "").strip()


def _next_human_review_patch_path(out_dir: Path) -> tuple[int, Path]:
    revisions: list[int] = []
    for path in out_dir.glob("human_review_patch_r*.json"):
        match = re.fullmatch(r"human_review_patch_r(\d+)\.json", path.name)
        if match:
            revisions.append(int(match.group(1)))
    revision = max(revisions, default=0) + 1
    return revision, out_dir / f"human_review_patch_r{revision:04d}.json"


def _apply_hierarchy_ownership_corrections(
    draft: dict[str, Any],
    human_review_patch: dict[str, Any],
    *,
    review: dict[str, Any],
    root: Path,
    patch_path: Path | None,
) -> dict[str, Any]:
    operations = [
        operation
        for operation in _list_of_dicts(human_review_patch.get("operations"))
        if operation.get("op") == "resolve_ownership"
    ]
    if not operations:
        return {}
    stage2 = _hierarchy_ownership_stage2(draft)
    if stage2 is None:
        raise ValueError("human_review_patch ownership stage2 evidence is missing")
    source_stage2_sha256 = _canonical_json_sha256(stage2)
    for operation in operations:
        _apply_normalized_ownership_operation(stage2, operation)
    remaining = _multiple_leaf_ownership(stage2)
    if remaining:
        raise ValueError(
            "human_review_patch multiple leaf ownership remains: "
            + ", ".join(sorted(remaining))
        )
    reviewed_stage2_sha256 = _canonical_json_sha256(stage2)
    reviewed_at = datetime.now().isoformat()
    source = review.get("source") if isinstance(review.get("source"), dict) else {}
    evidence_lineage = {
        "source_draft_path": str(source.get("source_path") or ""),
        "source_draft_sha256": str(source.get("sha256") or ""),
        "screenshot_path": str(human_review_patch.get("screenshot_path") or ""),
        "screenshot_sha256": str(human_review_patch.get("screenshot_sha256") or ""),
        "human_review_patch_path": (
            _relative_path(patch_path, root) if patch_path is not None else ""
        ),
        "human_review_patch_revision": human_review_patch.get("revision"),
    }
    revision = {
        "contract_version": HIERARCHY_OWNERSHIP_REVIEW_CONTRACT,
        "status": "corrected_needs_integrity_revalidation",
        "integrity_revalidation_status": "pending",
        "agent_usable": False,
        "reviewed_by_human": True,
        "created_at": reviewed_at,
        "source_stage2_sha256": source_stage2_sha256,
        "reviewed_stage2_sha256": reviewed_stage2_sha256,
        "corrections": [
            {
                "region_id": operation["region_id"],
                "item_id": operation["target_id"],
                "before_parent_group_ids": deepcopy(
                    operation["before_parent_group_ids"]
                ),
                "after_parent_group_id": operation["after_parent_group_id"],
                "removed_from_group_ids": deepcopy(
                    operation["removed_from_group_ids"]
                ),
                "reason": str(operation.get("reason") or ""),
            }
            for operation in operations
        ],
        "evidence_lineage": evidence_lineage,
        "human_review_provenance": {
            "source": str(
                human_review_patch.get("source") or "human_panel_editor_v1"
            ),
            "reason": str(human_review_patch.get("reason") or ""),
            "reviewed_at": reviewed_at,
        },
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "final_submit_forbidden": True,
    }
    revision["canonical_revision_sha256"] = _canonical_json_sha256(revision)
    page_details = (
        draft.get("page_details")
        if isinstance(draft.get("page_details"), dict)
        else {}
    )
    page_details["hierarchy_ownership_review"] = deepcopy(revision)
    draft["page_details"] = page_details
    human_review_patch["hierarchy_ownership_review"] = deepcopy(revision)
    return revision


def _canonical_json_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _correction_memory_compatible_patch(
    human_review_patch: dict[str, Any],
) -> dict[str, Any]:
    if not human_review_patch:
        return {}
    compatible = deepcopy(human_review_patch)
    compatible["operations"] = [
        deepcopy(operation)
        for operation in _list_of_dicts(human_review_patch.get("operations"))
        if operation.get("op") != "resolve_ownership"
    ]
    return compatible


def _compile_human_review_patch(
    legacy_patch: dict[str, Any],
    human_review_patch: dict[str, Any],
) -> dict[str, Any]:
    compiled = deepcopy(legacy_patch)
    region_updates = deepcopy(compiled.get("region_bbox_updates")) if isinstance(compiled.get("region_bbox_updates"), dict) else {}
    action_updates = deepcopy(compiled.get("action_bbox_updates")) if isinstance(compiled.get("action_bbox_updates"), dict) else {}
    region_additions = _list_of_dicts(compiled.get("region_additions"))
    action_additions = _list_of_dicts(compiled.get("action_template_additions"))
    region_role_updates = deepcopy(compiled.get("region_role_updates")) if isinstance(compiled.get("region_role_updates"), dict) else {}
    region_parent_updates = deepcopy(compiled.get("region_parent_updates")) if isinstance(compiled.get("region_parent_updates"), dict) else {}
    region_metadata_updates = deepcopy(compiled.get("region_metadata_updates")) if isinstance(compiled.get("region_metadata_updates"), dict) else {}
    action_metadata_updates = deepcopy(compiled.get("action_metadata_updates")) if isinstance(compiled.get("action_metadata_updates"), dict) else {}
    region_deletions = [str(item) for item in compiled.get("region_deletions", [])] if isinstance(compiled.get("region_deletions"), list) else []
    action_deletions = [str(item) for item in compiled.get("action_deletions", [])] if isinstance(compiled.get("action_deletions"), list) else []
    for operation in _list_of_dicts(human_review_patch.get("operations")):
        op = operation.get("op")
        target_kind = operation.get("target_kind")
        target_id = str(operation.get("target_id") or "")
        if op == "resolve_ownership":
            continue
        if op == "add":
            (action_additions if target_kind == "action" else region_additions).append(deepcopy(operation["item"]))
            continue
        if op == "delete":
            (action_deletions if target_kind == "action" else region_deletions).append(target_id)
            continue
        if op == "update_role":
            region_role_updates[target_id] = operation["after_value"]
            continue
        if op == "update_parent":
            region_parent_updates[target_id] = operation["after_value"]
            continue
        if op == "update_metadata":
            metadata_updates = action_metadata_updates if target_kind == "action" else region_metadata_updates
            metadata_updates[target_id] = deepcopy(operation["after_metadata"])
            continue
        update = {
            "bbox": deepcopy(operation["after_bbox"]),
            "source": "human_review_patch_v1",
        }
        if target_kind == "action":
            action_updates[target_id] = update
        else:
            region_updates[target_id] = update
    compiled["region_bbox_updates"] = region_updates
    compiled["action_bbox_updates"] = action_updates
    compiled["region_additions"] = region_additions
    compiled["action_template_additions"] = action_additions
    compiled["region_role_updates"] = region_role_updates
    compiled["region_parent_updates"] = region_parent_updates
    compiled["region_metadata_updates"] = region_metadata_updates
    compiled["action_metadata_updates"] = action_metadata_updates
    compiled["region_deletions"] = region_deletions
    compiled["action_deletions"] = action_deletions
    return compiled


def _render_human_review_overlay(
    draft: dict[str, Any],
    *,
    root: Path,
    out_dir: Path,
    revision: int,
) -> Path | None:
    source = _draft_source_image_evidence(draft)
    source_path = str(source.get("path") or "").strip()
    if not source_path:
        return None
    resolved = _resolve_optional_under_root(source_path, root)
    if not resolved.exists() or not resolved.is_file():
        return None
    try:
        image = Image.open(resolved).convert("RGB")
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ValueError("learning draft source screenshot is not a decodable image") from exc
    draw = ImageDraw.Draw(image)
    for kind, items, color, id_key in (
        ("R", _list_of_dicts(draft.get("regions")), (0, 110, 230), "region_id"),
        ("A", _list_of_dicts(draft.get("action_templates")), (240, 120, 0), "action_template_id"),
    ):
        for index, item in enumerate(items, start=1):
            bbox = _normalized_bbox(item.get("bbox"))
            if bbox is None:
                continue
            x1 = max(0, min(image.width - 1, bbox["x"]))
            y1 = max(0, min(image.height - 1, bbox["y"]))
            x2 = max(x1, min(image.width - 1, bbox["x"] + bbox["w"]))
            y2 = max(y1, min(image.height - 1, bbox["y"] + bbox["h"]))
            draw.rectangle((x1, y1, x2, y2), outline=color, width=3)
            item_id = str(item.get(id_key) or item.get("action_id") or index).strip()
            draw.text((x1 + 3, y1 + 3), f"{kind}{index} {item_id}", fill=color)
    suffix = f"r{revision:04d}" if revision > 0 else "legacy"
    output = out_dir / f"human_review_overlay_{suffix}.png"
    image.save(output)
    return output


def _apply_label_updates(items: list[dict[str, Any]], updates: Any, id_key: str, changes: list[str]) -> None:
    if not isinstance(updates, dict):
        return
    for item in items:
        item_id = str(item.get(id_key) or "")
        if item_id in updates:
            item["label"] = str(updates[item_id])
            changes.append(f"{id_key}_label:{item_id}")


def _apply_action_region_bindings(actions: list[dict[str, Any]], bindings: Any, changes: list[str]) -> None:
    if not isinstance(bindings, dict):
        return
    for action in actions:
        action_id = str(action.get("action_template_id") or action.get("action_id") or "")
        if action_id in bindings:
            action["target_entity"] = str(bindings[action_id])
            changes.append(f"action_region_binding:{action_id}")


def _apply_bbox_updates(
    items: list[dict[str, Any]],
    updates: Any,
    id_key: str,
    change_prefix: str,
    changes: list[str],
) -> None:
    if not isinstance(updates, dict):
        return
    for item in items:
        item_id = str(item.get(id_key) or item.get("action_id") or "").strip()
        update = updates.get(item_id)
        if not isinstance(update, dict):
            continue
        bbox = _normalized_bbox(update.get("bbox") if isinstance(update.get("bbox"), dict) else update)
        if bbox is None:
            continue
        previous_bbox = deepcopy(item.get("bbox")) if isinstance(item.get("bbox"), dict) else None
        previous_point = deepcopy(item.get("click_point")) if isinstance(item.get("click_point"), dict) else None
        item["bbox"] = bbox
        point = _normalized_point(update.get("click_point"))
        if point is None:
            point = {"x": int(round(bbox["x"] + bbox["w"] / 2)), "y": int(round(bbox["y"] + bbox["h"] / 2))}
        item["click_point"] = point
        human_review = item.get("human_review") if isinstance(item.get("human_review"), dict) else {}
        human_review.update(
            {
                "bbox_edited": True,
                "bbox_edit_source": str(update.get("source") or "human_review_full_image_inspector_v1"),
                "previous_bbox": previous_bbox,
                "previous_click_point": previous_point,
                "updated_bbox": deepcopy(bbox),
                "updated_click_point": deepcopy(point),
            }
        )
        item["human_review"] = human_review
        changes.append(f"{change_prefix}_bbox:{item_id}")


def _apply_role_updates(items: list[dict[str, Any]], updates: Any, changes: list[str]) -> None:
    if not isinstance(updates, dict):
        return
    for item in items:
        item_id = str(item.get("region_id") or "").strip()
        if item_id not in updates:
            continue
        item["role"] = str(updates[item_id]).strip()
        item["requires_human_review"] = True
        changes.append(f"region_role:{item_id}")


def _apply_parent_updates(items: list[dict[str, Any]], updates: Any, changes: list[str]) -> None:
    if not isinstance(updates, dict):
        return
    for item in items:
        item_id = str(item.get("region_id") or "").strip()
        if item_id not in updates:
            continue
        item["parent_region_id"] = str(updates[item_id]).strip()
        item["requires_human_review"] = True
        changes.append(f"region_parent:{item_id}")


def _apply_metadata_updates(
    items: list[dict[str, Any]],
    updates: Any,
    id_key: str,
    change_prefix: str,
    changes: list[str],
) -> None:
    if not isinstance(updates, dict):
        return
    for item in items:
        item_id = str(item.get(id_key) or item.get("action_id") or "").strip()
        metadata = updates.get(item_id)
        if not isinstance(metadata, dict):
            continue
        item.update(deepcopy(_normalize_human_review_metadata(metadata)))
        item["candidate_only"] = True
        item["requires_human_review"] = True
        item["artifact_is_authorization"] = False
        item["execute_binding_enabled"] = False
        item["final_submit_forbidden"] = True
        changes.append(f"{change_prefix}_metadata:{item_id}")


def _apply_review_deletions(draft: dict[str, Any], review_patch: dict[str, Any], changes: list[str]) -> None:
    deleted_region_ids: set[str] = set()
    deleted_action_ids: set[str] = set()
    for draft_key, patch_key, id_key, prefix in (
        ("regions", "region_deletions", "region_id", "region"),
        ("action_templates", "action_deletions", "action_template_id", "action"),
    ):
        requested = {
            str(item).strip()
            for item in review_patch.get(patch_key, [])
            if str(item).strip()
        } if isinstance(review_patch.get(patch_key), list) else set()
        if not requested:
            continue
        if draft_key == "regions":
            deleted_region_ids.update(requested)
        else:
            deleted_action_ids.update(requested)
        retained: list[dict[str, Any]] = []
        for item in _list_of_dicts(draft.get(draft_key)):
            item_id = str(item.get(id_key) or item.get("action_id") or "").strip()
            if item_id in requested:
                changes.append(f"{prefix}_delete:{item_id}")
            else:
                retained.append(item)
        draft[draft_key] = retained
    _prune_deleted_review_references(
        draft,
        deleted_region_ids=deleted_region_ids,
        deleted_action_ids=deleted_action_ids,
    )


def _prune_deleted_review_references(
    draft: dict[str, Any],
    *,
    deleted_region_ids: set[str],
    deleted_action_ids: set[str],
) -> None:
    if not deleted_region_ids and not deleted_action_ids:
        return

    for state in _list_of_dicts(draft.get("states")):
        if isinstance(state.get("region_refs"), list):
            state["region_refs"] = _prune_deleted_review_items(
                state["region_refs"],
                deleted_region_ids=deleted_region_ids,
                deleted_action_ids=set(),
            )
        if isinstance(state.get("action_template_refs"), list):
            state["action_template_refs"] = _prune_deleted_review_items(
                state["action_template_refs"],
                deleted_region_ids=set(),
                deleted_action_ids=deleted_action_ids,
            )

    page_details = draft.get("page_details") if isinstance(draft.get("page_details"), dict) else {}
    layout = page_details.get("layout") if isinstance(page_details.get("layout"), dict) else {}
    for section in _list_of_dicts(layout.get("sections")):
        if isinstance(section.get("regions"), list):
            section["regions"] = _prune_deleted_review_items(
                section["regions"],
                deleted_region_ids=deleted_region_ids,
                deleted_action_ids=set(),
            )
        if isinstance(section.get("operation_links"), list):
            section["operation_links"] = _prune_deleted_review_items(
                section["operation_links"],
                deleted_region_ids=deleted_region_ids,
                deleted_action_ids=deleted_action_ids,
            )
    if isinstance(layout.get("regions"), list):
        layout["regions"] = _prune_deleted_review_items(
            layout["regions"],
            deleted_region_ids=deleted_region_ids,
            deleted_action_ids=set(),
        )
    if isinstance(page_details.get("review_only_regions"), list):
        page_details["review_only_regions"] = _prune_deleted_review_items(
            page_details["review_only_regions"],
            deleted_region_ids=deleted_region_ids,
            deleted_action_ids=set(),
        )

    _prune_deleted_hierarchy_nodes(
        draft.get("ui_hierarchy"),
        deleted_region_ids=deleted_region_ids,
        deleted_action_ids=deleted_action_ids,
    )
    _prune_deleted_hierarchy_nodes(
        page_details.get("ui_hierarchy"),
        deleted_region_ids=deleted_region_ids,
        deleted_action_ids=deleted_action_ids,
    )


def _prune_deleted_review_items(
    value: Any,
    *,
    deleted_region_ids: set[str],
    deleted_action_ids: set[str],
) -> list[Any]:
    if not isinstance(value, list):
        return []
    return [
        item
        for item in value
        if not _review_item_references_deleted_id(
            item,
            deleted_region_ids=deleted_region_ids,
            deleted_action_ids=deleted_action_ids,
        )
    ]


def _review_item_references_deleted_id(
    item: Any,
    *,
    deleted_region_ids: set[str],
    deleted_action_ids: set[str],
) -> bool:
    if isinstance(item, str):
        return item.strip() in deleted_region_ids or item.strip() in deleted_action_ids
    if not isinstance(item, dict):
        return False
    for key in ("region_id", "source_region_id", "target_region_id", "target_entity"):
        if str(item.get(key) or "").strip() in deleted_region_ids:
            return True
    for key in ("action_template_id", "action_id", "source_action_template_id", "target_action_template_id"):
        if str(item.get(key) or "").strip() in deleted_action_ids:
            return True
    for key in ("source_item_id", "item_id", "id", "source_ref", "node_id"):
        item_id = str(item.get(key) or "").strip()
        if item_id in deleted_region_ids or item_id in deleted_action_ids:
            return True
    return False


def _prune_deleted_hierarchy_nodes(
    value: Any,
    *,
    deleted_region_ids: set[str],
    deleted_action_ids: set[str],
) -> None:
    if not isinstance(value, dict):
        return
    nodes = _list_of_dicts(value.get("nodes"))
    removed_node_ids = {
        str(node.get("node_id") or "").strip()
        for node in nodes
        if _review_item_references_deleted_id(
            node,
            deleted_region_ids=deleted_region_ids,
            deleted_action_ids=deleted_action_ids,
        )
    }
    while removed_node_ids:
        descendants = {
            str(node.get("node_id") or "").strip()
            for node in nodes
            if str(node.get("parent_id") or "").strip() in removed_node_ids
        }
        new_descendants = descendants - removed_node_ids
        if not new_descendants:
            break
        removed_node_ids.update(new_descendants)
    if not removed_node_ids:
        return

    retained_nodes = [
        node for node in nodes if str(node.get("node_id") or "").strip() not in removed_node_ids
    ]
    for node in retained_nodes:
        if isinstance(node.get("children"), list):
            node["children"] = [
                child for child in node["children"] if str(child or "").strip() not in removed_node_ids
            ]
    value["nodes"] = retained_nodes
    if isinstance(value.get("edges"), list):
        value["edges"] = [
            edge
            for edge in value["edges"]
            if isinstance(edge, dict)
            and not any(
                str(edge.get(key) or "").strip() in removed_node_ids
                for key in ("parent_id", "child_id", "source", "target", "source_node_id", "target_node_id")
            )
        ]
    if isinstance(value.get("roots"), list):
        value["roots"] = [
            root for root in value["roots"] if str(root or "").strip() not in removed_node_ids
        ]
    if str(value.get("root_node_id") or "").strip() in removed_node_ids:
        value["root_node_id"] = ""
    summary = value.get("summary") if isinstance(value.get("summary"), dict) else None
    if summary is not None:
        summary["node_count"] = len(retained_nodes)
        if isinstance(value.get("edges"), list):
            summary["edge_count"] = len(value["edges"])


def _apply_review_additions(draft: dict[str, Any], review_patch: dict[str, Any], changes: list[str]) -> None:
    additions = (
        ("states", "state_additions", "state_id"),
        ("regions", "region_additions", "region_id"),
        ("action_templates", "action_template_additions", "action_template_id"),
        ("transitions", "transition_additions", "transition_id"),
    )
    for draft_key, patch_key, id_key in additions:
        added = _append_review_only_items(draft, draft_key, review_patch.get(patch_key), id_key)
        if added:
            changes.append(f"{patch_key}:{added}")


def _apply_manual_edit(draft: dict[str, Any], manual_edit: Any, changes: list[str]) -> None:
    if not isinstance(manual_edit, dict):
        return
    region_id = str(manual_edit.get("target_region_id") or "").strip()
    action_id = str(manual_edit.get("target_action_template_id") or "").strip()
    regions = _list_of_dicts(draft.get("regions"))
    actions = _list_of_dicts(draft.get("action_templates"))
    region = next((item for item in regions if str(item.get("region_id") or "").strip() == region_id), None)
    action = next(
        (
            item
            for item in actions
            if str(item.get("action_template_id") or item.get("action_id") or "").strip() == action_id
        ),
        None,
    )
    if region is None and region_id:
        raise ValueError(f"manual edit target region was not found: {region_id}")
    if action is None and action_id:
        raise ValueError(f"manual edit target action was not found: {action_id}")

    if region is not None:
        for source_key, target_key in (
            ("region_label", "label"),
            ("region_role", "role"),
            ("region_section", "parent_region_id"),
            ("notes", "description"),
        ):
            if source_key not in manual_edit:
                continue
            region[target_key] = str(manual_edit.get(source_key) or "").strip()
            changes.append(f"manual_{target_key}:{region_id}")
        for key in ("may_enter_pathgraph_draft", "needs_recalibration"):
            if key not in manual_edit:
                continue
            region[key] = manual_edit.get(key) is True
            changes.append(f"manual_{key}:{region_id}")
        region["requires_human_review"] = True

    if action is not None and "possible_operation" in manual_edit:
        operation = str(manual_edit.get("possible_operation") or "").strip()
        if operation:
            action["semantic_action"] = operation
            action["action_type"] = operation
            action["requires_human_review"] = True
            changes.append(f"manual_action_type:{action_id}")


def _append_review_only_items(draft: dict[str, Any], draft_key: str, additions: Any, id_key: str) -> int:
    items = _list_of_dicts(draft.get(draft_key))
    draft[draft_key] = items
    existing_ids = {str(item.get(id_key) or "").strip() for item in items if str(item.get(id_key) or "").strip()}
    added = 0
    for addition in _list_of_dicts(additions):
        item_id = str(addition.get(id_key) or "").strip()
        if not item_id or item_id in existing_ids:
            continue
        item = deepcopy(addition)
        _force_review_only_item(item)
        items.append(item)
        existing_ids.add(item_id)
        added += 1
    return added


def _force_review_only_item(item: dict[str, Any]) -> None:
    item["candidate_only"] = True
    item["artifact_is_authorization"] = False
    item["execute_binding_enabled"] = False
    item["final_submit_forbidden"] = True
    item["real_action_requires_gate"] = True
    item["requires_human_review"] = True


def _normalized_bbox(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    try:
        x = int(round(float(value.get("x", 0))))
        y = int(round(float(value.get("y", 0))))
        width = int(round(float(value.get("w", value.get("width")))))
        height = int(round(float(value.get("h", value.get("height")))))
    except (TypeError, ValueError):
        return None
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        return None
    return {"x": x, "y": y, "w": width, "h": height}


def _normalized_point(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    try:
        x = int(round(float(value.get("x"))))
        y = int(round(float(value.get("y"))))
    except (TypeError, ValueError):
        return None
    if x < 0 or y < 0:
        return None
    return {"x": x, "y": y}


def _manual_bbox_edit_summary(draft: dict[str, Any]) -> dict[str, Any]:
    regions = _list_of_dicts(draft.get("regions"))
    actions = _list_of_dicts(draft.get("action_templates"))
    edited_regions = [item for item in regions if _bbox_edited(item)]
    edited_actions = [item for item in actions if _bbox_edited(item)]
    edited_items = edited_regions + edited_actions
    point_passed = 0
    point_failed = 0
    invalid_geometry = 0
    for item in edited_items:
        bbox = _normalized_bbox(item.get("bbox"))
        point = _normalized_point(item.get("click_point"))
        if bbox is None or point is None:
            invalid_geometry += 1
            continue
        if _point_inside_bbox(point, bbox):
            point_passed += 1
        else:
            point_failed += 1
    return {
        "contract_version": "manual_bbox_edit_summary_v1",
        "edited_region_count": len(edited_regions),
        "edited_action_count": len(edited_actions),
        "edited_total": len(edited_items),
        "point_inside_bbox_passed": point_passed,
        "point_inside_bbox_failed": point_failed,
        "invalid_geometry_count": invalid_geometry,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _precise_understanding_summary(draft: dict[str, Any]) -> dict[str, Any]:
    regions = _list_of_dicts(draft.get("regions"))
    actions = _list_of_dicts(draft.get("action_templates"))
    states = _list_of_dicts(draft.get("states"))
    blockers = _list_of_dicts(draft.get("blockers"))
    verification_rules = _list_of_dicts(draft.get("verification_rules"))
    bbox_regions = [item for item in regions if _normalized_bbox(item.get("bbox")) is not None]
    action_points = [item for item in actions if _normalized_point(item.get("click_point")) is not None]
    open_detail_hints = [
        item
        for item in actions
        if isinstance(item.get("transition_hint"), dict)
        and item["transition_hint"].get("contract_version") == "learn_open_detail_transition_hint_v1"
    ]
    semantic_actions = sorted({
        str(item.get("semantic_action") or item.get("action_kind") or "").strip()
        for item in actions
        if str(item.get("semantic_action") or item.get("action_kind") or "").strip()
    })
    return {
        "contract_version": "precise_understanding_summary_v1",
        "state_count": len(states),
        "region_count": len(regions),
        "bbox_region_count": len(bbox_regions),
        "action_template_count": len(actions),
        "action_click_point_count": len(action_points),
        "open_detail_transition_hint_count": len(open_detail_hints),
        "blocker_count": len(blockers),
        "verification_rule_count": len(verification_rules),
        "semantic_actions": semantic_actions,
        "candidate_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "final_submit_forbidden": True,
        "interpretation": "review-only precise understanding summary; not Execute authorization",
    }


def _source_freshness_summary(
    draft: dict[str, Any],
    root: Path,
    manual_bbox_edit_summary: dict[str, Any],
) -> dict[str, Any]:
    source_image_evidence = _draft_source_image_evidence(draft)
    image_path = source_image_evidence["path"]
    expected_sha256 = source_image_evidence["sha256"]
    warnings: list[str] = []
    actual_sha256 = ""

    if not image_path:
        source_image_status = "missing"
        warnings.append("missing_source_image")
    else:
        resolved = _resolve_optional_under_root(image_path, root)
        if resolved.exists():
            source_image_status = "available"
            actual_sha256 = hashlib.sha256(resolved.read_bytes()).hexdigest()
        else:
            source_image_status = "missing_file"
            warnings.append("source_image_file_missing")

    if not expected_sha256 and actual_sha256 and source_image_evidence["allow_computed_checksum"]:
        expected_sha256 = actual_sha256

    if not expected_sha256:
        checksum_status = "missing"
        warnings.append("missing_source_image_sha256")
    elif not image_path:
        checksum_status = "not_verified"
        warnings.append("source_image_sha256_without_image")
    else:
        resolved = _resolve_optional_under_root(image_path, root)
        if not resolved.exists():
            checksum_status = "not_verified"
        else:
            actual_sha256 = actual_sha256 or hashlib.sha256(resolved.read_bytes()).hexdigest()
            checksum_status = "matched" if actual_sha256 == expected_sha256 else "mismatch"
            if checksum_status == "mismatch":
                warnings.append("source_image_sha256_mismatch")

    edited_total = int(manual_bbox_edit_summary.get("edited_total") or 0)
    freshness_status = "warning" if warnings else "verified"
    return {
        "contract_version": "source_freshness_summary_v1",
        "source_image_status": source_image_status,
        "checksum_status": checksum_status,
        "freshness_status": freshness_status,
        "warning_count": len(warnings),
        "warnings": warnings,
        "source_image_path": image_path,
        "source_image_sha256": expected_sha256,
        "actual_source_image_sha256": actual_sha256,
        "source_image_evidence_source": source_image_evidence["source"],
        "checksum_binding_status": (
            "computed_from_existing_fusion_source"
            if source_image_evidence["allow_computed_checksum"] and expected_sha256 and expected_sha256 == actual_sha256
            else "provided_by_draft"
            if expected_sha256
            else "missing"
        ),
        "edited_geometry_requires_review": edited_total > 0 and bool(warnings),
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _draft_source_image_path(draft: dict[str, Any]) -> str:
    return _draft_source_image_evidence(draft)["path"]


def _bind_review_source_image(
    draft: dict[str, Any], root: Path,
) -> dict[str, Any] | None:
    source = _draft_source_image_evidence(draft)
    image_path = str(source.get("path") or "").strip()
    if not image_path:
        return None
    resolved = _resolve_optional_under_root(image_path, root)
    if not resolved.exists() or not resolved.is_file():
        return None
    source_bytes = resolved.read_bytes()
    actual_sha256 = hashlib.sha256(source_bytes).hexdigest()
    expected_sha256 = str(source.get("sha256") or "").strip().lower()
    try:
        with Image.open(BytesIO(source_bytes)) as source_image:
            source_image.load()
            width, height = source_image.size
        source_image_size = {"width": int(width), "height": int(height)}
    except (OSError, UnidentifiedImageError, SyntaxError):
        return None
    if expected_sha256 and expected_sha256 != actual_sha256:
        return {
            "sha256": actual_sha256,
            "image_size": source_image_size,
            "source_bytes": source_bytes,
            "source_path": resolved,
        }
    panel_source = _materialize_panel_review_source_image(
        resolved,
        root=root,
        source_bytes=source_bytes,
        source_sha256=actual_sha256,
    )
    page_details = draft.get("page_details") if isinstance(draft.get("page_details"), dict) else {}
    screen = page_details.get("screen") if isinstance(page_details.get("screen"), dict) else {}
    screen["source_image_path"] = _relative_path(panel_source, root)
    screen["source_image_sha256"] = actual_sha256
    screen["source_image_binding_source"] = str(source.get("source") or "")
    screen["source_image_binding_allows_computed_checksum"] = bool(source.get("allow_computed_checksum"))
    screen["source_image_materialized_for_panel"] = panel_source != resolved
    if source_image_size:
        screen["screen_size"] = source_image_size
    screen["artifact_is_authorization"] = False
    screen["execute_binding_enabled"] = False
    page_details["screen"] = screen
    draft["page_details"] = page_details
    return {
        "sha256": actual_sha256,
        "image_size": source_image_size,
        "source_bytes": source_bytes,
        "source_path": resolved,
    }


def _bind_projected_review_source_copy(
    draft: dict[str, Any],
    *,
    displayed_source_image: dict[str, Any] | None,
    root: Path,
) -> None:
    if not isinstance(displayed_source_image, dict):
        return
    source_path = displayed_source_image.get("source_path")
    source_bytes = displayed_source_image.get("source_bytes")
    source_sha256 = displayed_source_image.get("sha256")
    if (
        not isinstance(source_path, Path)
        or not isinstance(source_bytes, bytes)
        or not isinstance(source_sha256, str)
        or hashlib.sha256(source_bytes).hexdigest() != source_sha256
    ):
        return
    panel_source = _materialize_panel_review_source_image(
        source_path,
        root=root,
        source_bytes=source_bytes,
        source_sha256=source_sha256,
        force_content_addressed=True,
    )
    page_details = draft.get("page_details") if isinstance(draft.get("page_details"), dict) else {}
    screen = page_details.get("screen") if isinstance(page_details.get("screen"), dict) else {}
    screen["source_image_path"] = _relative_path(panel_source, root)
    screen["source_image_sha256"] = source_sha256
    screen["source_image_materialized_for_panel"] = True
    page_details["screen"] = screen
    draft["page_details"] = page_details


def _materialize_panel_review_source_image(
    source_path: Path,
    *,
    root: Path,
    source_bytes: bytes,
    source_sha256: str,
    force_content_addressed: bool = False,
) -> Path:
    if not force_content_addressed:
        try:
            source_path.relative_to(root)
            return source_path
        except ValueError:
            pass

    suffix = source_path.suffix.lower() or ".png"
    output_path = (
        root
        / "artifacts"
        / "learning-draft-review"
        / "source-images"
        / f"{source_sha256}{suffix}"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not output_path.exists() or hashlib.sha256(output_path.read_bytes()).hexdigest() != source_sha256:
        output_path.write_bytes(source_bytes)
    return output_path


def _draft_source_image_evidence(draft: dict[str, Any]) -> dict[str, Any]:
    page_details = draft.get("page_details") if isinstance(draft.get("page_details"), dict) else {}
    screen = page_details.get("screen") if isinstance(page_details.get("screen"), dict) else {}
    for path_value, sha_value, source, allow_computed_checksum in (
        (
            screen.get("source_image_path"),
            screen.get("source_image_sha256"),
            str(screen.get("source_image_binding_source") or "page_details.screen.source_image_path"),
            bool(screen.get("source_image_binding_allows_computed_checksum")),
        ),
        (screen.get("image_path"), screen.get("image_sha256"), "page_details.screen.image_path", False),
        (
            screen.get("screenshot_path"),
            screen.get("screenshot_sha256"),
            "page_details.screen.screenshot_path",
            False,
        ),
        (
            page_details.get("source_image_path"),
            page_details.get("source_image_sha256"),
            "page_details.source_image_path",
            False,
        ),
        (page_details.get("image_path"), page_details.get("image_sha256"), "page_details.image_path", False),
        (
            page_details.get("screenshot_path"),
            page_details.get("screenshot_sha256"),
            "page_details.screenshot_path",
            False,
        ),
        *[
            (
                status.get("source_image_path") or status.get("image_path") or status.get("screenshot_path"),
                status.get("source_image_sha256") or status.get("image_sha256") or status.get("screenshot_sha256"),
                source,
                True,
            )
            for source, status in _fusion_source_statuses(page_details)
        ],
        (draft.get("source_image_path"), draft.get("source_image_sha256"), "draft.source_image_path", False),
        (draft.get("image_path"), draft.get("image_sha256"), "draft.image_path", False),
        (draft.get("screenshot_path"), draft.get("screenshot_sha256"), "draft.screenshot_path", False),
    ):
        text = str(path_value or "").strip()
        if text:
            return {
                "path": text,
                "sha256": str(sha_value or "").strip().lower(),
                "source": source,
                "allow_computed_checksum": allow_computed_checksum,
            }
    return {"path": "", "sha256": "", "source": "missing", "allow_computed_checksum": False}


def _draft_source_image_sha256(draft: dict[str, Any]) -> str:
    return _draft_source_image_evidence(draft)["sha256"]


def _fusion_source_statuses(page_details: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    statuses: list[tuple[str, dict[str, Any]]] = []
    two_stage = (
        page_details.get("two_stage_understanding")
        if isinstance(page_details.get("two_stage_understanding"), dict)
        else {}
    )
    current_fusion = two_stage.get("fusion") if isinstance(two_stage.get("fusion"), dict) else {}
    if current_fusion:
        statuses.append(("page_details.two_stage_understanding.fusion", current_fusion))
    direct = page_details.get("precise_understanding_fusion_status")
    if isinstance(direct, dict):
        statuses.append(("page_details.precise_understanding_fusion_status", direct))
    audit = page_details.get("pipeline_audit") if isinstance(page_details.get("pipeline_audit"), dict) else {}
    nested = audit.get("precise_understanding_fusion_status") if isinstance(audit.get("precise_understanding_fusion_status"), dict) else {}
    if nested:
        statuses.append(("page_details.pipeline_audit.precise_understanding_fusion_status", nested))
    return sorted(
        statuses,
        key=lambda entry: 0
        if entry[1].get("final_fusion_overlay") is True
        and entry[1].get("display_overlay_source") == "two_stage_plus_precise_calibration"
        else 1,
    )


def _resolve_optional_under_root(path_value: str, root: Path) -> Path:
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def _bbox_edited(item: dict[str, Any]) -> bool:
    human_review = item.get("human_review") if isinstance(item.get("human_review"), dict) else {}
    return human_review.get("bbox_edited") is True


def _point_inside_bbox(point: dict[str, int], bbox: dict[str, int]) -> bool:
    return bbox["x"] <= point["x"] <= bbox["x"] + bbox["w"] and bbox["y"] <= point["y"] <= bbox["y"] + bbox["h"]


def _review_safety() -> dict[str, Any]:
    return {
        "artifact_is_authorization": False,
        "final_submit_allowed": False,
        "final_submit_forbidden": True,
        "real_action_requires_gate": True,
        "execute_binding_enabled": False,
        "authorization_scope": "display_and_review_only",
    }


def _resolve_source_path(path_value: str | Path, root: Path) -> Path:
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    allowed_roots = [(root / "artifacts").resolve(), (root / "logs").resolve()]
    if not any(path == allowed or allowed in path.parents for allowed in allowed_roots):
        raise ValueError("learning draft source must be under artifacts or logs")
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(str(path))
    return path


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _slug_for_output(source: dict[str, Any]) -> str:
    source_path = str(source.get("source_path") or "learning_draft")
    digest = str(source.get("sha256") or hashlib.sha256(source_path.encode("utf-8")).hexdigest())[:10]
    stem = Path(source_path).stem or "learning_draft"
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("._-").lower() or "learning_draft"
    return f"{slug}_{digest}"


def _is_trial(payload: dict[str, Any]) -> bool:
    return isinstance(payload.get("best_learning_draft"), dict) or isinstance(payload.get("attempts"), list)


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _list_of_dicts_or_strings(value: Any) -> list[Any]:
    return [item for item in value if isinstance(item, (dict, str)) and item] if isinstance(value, list) else []


def _list_of_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item or "").strip()]


def _list_of_ints(value: Any) -> list[int]:
    result: list[int] = []
    if not isinstance(value, list):
        return result
    for item in value:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result


def _int_value(*values: Any) -> int:
    for value in values:
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return 0


def _has_int_value(*values: Any) -> bool:
    for value in values:
        try:
            int(value)
            return True
        except (TypeError, ValueError):
            continue
    return False


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
