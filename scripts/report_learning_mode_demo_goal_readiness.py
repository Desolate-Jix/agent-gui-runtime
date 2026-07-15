from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_NAME = "learning_mode_demo_goal_readiness_report.json"


def report_learning_mode_demo_goal_readiness(
    *,
    scaffold_path: str | Path,
    presentation_evidence_path: str | Path | None = None,
    out_dir: str | Path | None = None,
    project_root: str | Path | None = None,
    json_stdout: bool = False,
) -> dict[str, Any]:
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    scaffold_file = _resolve_path(scaffold_path, root)
    scaffold = _attach_generated_artifacts(_read_json(scaffold_file), scaffold_file=scaffold_file, root=root)
    presentation_evidence_file = (
        _resolve_path(presentation_evidence_path, root) if presentation_evidence_path is not None else None
    )
    if presentation_evidence_file is not None:
        scaffold["presentation_evidence"] = _read_json(presentation_evidence_file)
    out = _resolve_path(out_dir, root) if out_dir is not None else scaffold_file.parent
    out.mkdir(parents=True, exist_ok=True)

    requirements = _requirements(scaffold)
    model_and_safety_blockers = _blocking_reasons(scaffold, requirements)
    evidence_map = _demo_evidence_map(scaffold, root=root, scaffold_file=scaffold_file)
    fresh_model_acceptance = _fresh_model_chain_acceptance(scaffold, requirements, model_and_safety_blockers)
    presentation_acceptance = _presentation_acceptance(scaffold, root=root, scaffold_file=scaffold_file)
    model_chain_accepted = fresh_model_acceptance.get("accepted") is True
    fresh_model_acceptance["model_chain_accepted"] = model_chain_accepted
    fresh_model_acceptance["presentation_acceptance_required"] = True
    fresh_model_acceptance["counts_as_final_goal_completion"] = (
        model_chain_accepted and presentation_acceptance.get("accepted") is True
    )
    fresh_model_acceptance["interpretation"] = (
        "Strict acceptance gate for the model-generated Learning Mode chain. Passing this gate proves only the model "
        "chain; counts_as_final_goal_completion also requires current presentation acceptance."
    )
    blocking_reasons = list(model_and_safety_blockers)
    if presentation_acceptance.get("accepted") is not True:
        blocking_reasons.append("current_presentation_evidence_not_accepted")
    blocking_reasons = _unique_text(blocking_reasons)
    next_actions = _next_actions(scaffold, blocking_reasons, root=root)
    display_demo_ready = all(
        _requirement_status(requirements, requirement_id) == "passed"
        for requirement_id in (
            "full_screen_understanding_numbered_regions",
            "selection_map_available",
            "pathgraph_preview_available",
            "pathgraph_opens_page_detail",
            "template_like_page_detail_layout",
            "model_only_demo_chain_ready",
            "no_execute_no_submit_safety",
        )
    )
    final_goal_complete = (
        display_demo_ready
        and fresh_model_acceptance.get("accepted") is True
        and presentation_acceptance.get("accepted") is True
    )
    if final_goal_complete:
        status = "final_goal_complete"
    elif display_demo_ready and fresh_model_acceptance.get("accepted") is True:
        status = "display_demo_ready_presentation_unverified"
    elif display_demo_ready:
        status = "display_demo_ready_official_goal_blocked"
    else:
        status = "display_demo_blocked"

    report = {
        "contract_version": "learning_mode_demo_goal_readiness_v1",
        "source_scaffold_path": _relative_path(scaffold_file, root),
        "source_presentation_evidence_path": (
            _relative_path(presentation_evidence_file, root) if presentation_evidence_file is not None else None
        ),
        "demo_goal_status": status,
        "display_demo_ready": display_demo_ready,
        "final_goal_complete": final_goal_complete,
        "demo_evidence_map": evidence_map,
        "fresh_model_chain_acceptance": fresh_model_acceptance,
        "presentation_acceptance": presentation_acceptance,
        "demo_chain_manifest": _demo_chain_manifest(
            evidence_map=evidence_map,
            display_demo_ready=display_demo_ready,
            final_goal_complete=final_goal_complete,
            blocking_reasons=blocking_reasons,
        ),
        "blocking_reasons": blocking_reasons,
        "next_action_status": _next_action_status(next_actions, final_goal_complete),
        "may_start_model_after_user_approval": any(
            item.get("action_id") == "request_explicit_model_start_approval" and item.get("status") == "required"
            for item in next_actions
        ),
        "may_run_without_user_approval": False,
        "next_actions": next_actions,
        "summary": {
            "passed_requirement_count": sum(1 for item in requirements if item.get("status") == "passed"),
            "failed_requirement_count": sum(1 for item in requirements if item.get("status") == "failed"),
            "not_covered_requirement_count": sum(1 for item in requirements if item.get("status") == "not_covered"),
            "presentation_acceptance_status": presentation_acceptance.get("acceptance_status"),
            "presentation_accepted": presentation_acceptance.get("accepted") is True,
            "presentation_blocker_count": len(
                presentation_acceptance.get("blocking_reasons")
                if isinstance(presentation_acceptance.get("blocking_reasons"), list)
                else []
            ),
        },
        "requirements": requirements,
        "safety": {
            "display_only": True,
            "model_started": False,
            "live_clicks": _int_value(_dict(scaffold.get("safety")).get("live_clicks")),
            "live_fills": _int_value(_dict(scaffold.get("safety")).get("live_fills")),
            "live_submits": _int_value(_dict(scaffold.get("safety")).get("live_submits")),
            "execute_binding_enabled": False,
            "runtime_pathgraph_promotion": False,
            "artifact_is_authorization": False,
        },
        "interpretation": (
            "Goal-level demo readiness audit. A display-ready model-only PathGraph/page-detail preview is useful for "
            "demo review, but the final Learning Mode goal is not complete until the official candidate chain is "
            "fully system-model generated, pending calibration is resolved, current presentation evidence matches "
            "the active frontend revision, and safety remains no-execute/no-submit."
        ),
    }
    output_path = out / REPORT_NAME
    report["report_path"] = str(output_path.resolve())
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if json_stdout:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def _requirements(scaffold: dict[str, Any]) -> list[dict[str, Any]]:
    summary = _dict(scaffold.get("summary"))
    display = _dict(scaffold.get("display_readiness"))
    provenance = _dict(scaffold.get("model_provenance_audit"))
    model_only = _dict(scaffold.get("model_only_demo_readiness"))
    safety = _dict(scaffold.get("safety"))
    flow_status = {str(item.get("step_id")): str(item.get("status") or "") for item in _list_of_dicts(scaffold.get("flow"))}
    generated = _dict(scaffold.get("generated_artifacts"))

    return [
        _requirement(
            "full_screen_understanding_numbered_regions",
            flow_status.get("full_screen_understanding_numbered_regions") == "available",
            evidence={"flow_status": flow_status.get("full_screen_understanding_numbered_regions")},
        ),
        _requirement(
            "selection_map_available",
            bool(generated.get("precise_understanding_candidate_path")),
            evidence={
                "precise_understanding_candidate_path": generated.get("precise_understanding_candidate_path"),
                "pending_calibration_count": summary.get("precise_pending_calibration_count"),
            },
        ),
        _requirement(
            "pathgraph_preview_available",
            summary.get("model_generated_pathgraph_preview_status") == "model_generated_preview_ready"
            and _int_value(summary.get("model_generated_pathgraph_preview_region_count")) > 0
            and _int_value(summary.get("model_generated_pathgraph_preview_action_count")) > 0,
            evidence={
                "preview_status": summary.get("model_generated_pathgraph_preview_status"),
                "region_count": summary.get("model_generated_pathgraph_preview_region_count"),
                "action_count": summary.get("model_generated_pathgraph_preview_action_count"),
            },
        ),
        _requirement(
            "pathgraph_opens_page_detail",
            display.get("pathgraph_detail_can_show_page_detail") is True,
            evidence={"pathgraph_detail_can_show_page_detail": display.get("pathgraph_detail_can_show_page_detail")},
        ),
        _requirement(
            "template_like_page_detail_layout",
            (
                display.get("template_like_layout_available") is True
                and _int_value(summary.get("page_detail_section_count")) > 0
                and _int_value(summary.get("page_detail_possible_operation_count")) > 0
            )
            or (
                _int_value(summary.get("model_generated_page_detail_section_count")) > 0
                and _int_value(summary.get("model_generated_page_detail_possible_operation_count")) > 0
            )
            or (
                _int_value(model_only.get("model_page_detail_section_count")) > 0
                and _int_value(model_only.get("model_page_detail_possible_operation_count")) > 0
            ),
            evidence={
                "page_detail_section_count": summary.get("page_detail_section_count"),
                "page_detail_possible_operation_count": summary.get("page_detail_possible_operation_count"),
                "model_generated_page_detail_section_count": summary.get("model_generated_page_detail_section_count"),
                "model_generated_page_detail_possible_operation_count": summary.get(
                    "model_generated_page_detail_possible_operation_count"
                ),
                "model_only_page_detail_section_count": model_only.get("model_page_detail_section_count"),
                "model_only_page_detail_possible_operation_count": model_only.get(
                    "model_page_detail_possible_operation_count"
                ),
            },
        ),
        _requirement(
            "model_only_demo_chain_ready",
            model_only.get("ready") is True and model_only.get("status") == "model_only_demo_ready",
            evidence={
                "status": model_only.get("status"),
                "preview_regions": model_only.get("model_preview_region_count"),
                "preview_actions": model_only.get("model_preview_action_count"),
                "page_sections": model_only.get("model_page_detail_section_count"),
                "page_ops": model_only.get("model_page_detail_possible_operation_count"),
            },
        ),
        _requirement(
            "official_candidate_fully_system_model_generated",
            provenance.get("meets_fully_model_generated_demo_requirement") is True,
            evidence={
                "provenance_status": provenance.get("status"),
                "actual_model_call_evidence_count": provenance.get("actual_model_call_evidence_count"),
                "assisted_or_human_review_evidence_count": provenance.get("assisted_or_human_review_evidence_count"),
                "blocking_reasons": provenance.get("blocking_reasons"),
            },
        ),
        _requirement(
            "pending_calibration_resolved",
            _int_value(summary.get("precise_pending_calibration_count")) == 0,
            evidence={"precise_pending_calibration_count": summary.get("precise_pending_calibration_count")},
        ),
        _requirement(
            "no_execute_no_submit_safety",
            safety.get("model_started") is False
            and _int_value(safety.get("live_clicks")) == 0
            and _int_value(safety.get("live_fills")) == 0
            and _int_value(safety.get("live_submits")) == 0
            and safety.get("execute_binding_enabled") is False
            and safety.get("runtime_pathgraph_promotion") is False,
            evidence={
                "model_started": safety.get("model_started"),
                "live_clicks": safety.get("live_clicks"),
                "live_fills": safety.get("live_fills"),
                "live_submits": safety.get("live_submits"),
                "execute_binding_enabled": safety.get("execute_binding_enabled"),
                "runtime_pathgraph_promotion": safety.get("runtime_pathgraph_promotion"),
            },
        ),
    ]


def _presentation_acceptance(
    scaffold: dict[str, Any],
    *,
    root: Path,
    scaffold_file: Path,
) -> dict[str, Any]:
    evidence = _dict(scaffold.get("presentation_evidence"))
    base = {
        "contract_version": "learning_interface_presentation_acceptance_v1",
        "accepted": False,
        "acceptance_status": "not_covered",
        "same_source_three_image_evidence": False,
        "frontend_revision_matches": False,
        "desktop_viewport_covered": False,
        "narrow_viewport_covered": False,
        "blocking_reasons": ["missing_presentation_evidence"],
        "interpretation": (
            "Current-revision presentation acceptance for the Learning Interface. It requires same-source original, "
            "Stage1, and final-fusion evidence plus trace, desktop/narrow panel captures, current frontend hashes, "
            "latest-fusion loading, resizer verification, and bbox-geometry verification."
        ),
    }
    if not evidence:
        return base

    blockers: list[str] = []
    if evidence.get("contract_version") != "learning_interface_presentation_evidence_v1":
        blockers.append("invalid_presentation_evidence_contract")

    required_paths = (
        "source_screenshot_path",
        "stage1_overlay_path",
        "final_fusion_overlay_path",
        "trace_path",
        "desktop_panel_screenshot_path",
        "narrow_panel_screenshot_path",
    )
    resolved_paths: dict[str, Path | None] = {}
    artifact_evidence: dict[str, dict[str, Any]] = {}
    for key in required_paths:
        raw_path = str(evidence.get(key) or "").strip()
        resolved = _resolve_generated_path(raw_path, root=root, scaffold_file=scaffold_file)
        exists = bool(resolved and resolved.is_file())
        resolved_paths[key] = resolved if exists else None
        artifact_evidence[key] = {
            "path": raw_path,
            "resolved_path": str(resolved) if resolved else "",
            "exists": exists,
            "sha256_prefix": _sha256_prefix(resolved) if exists and resolved else "",
        }
        if not exists:
            blockers.append(f"missing_{key}")

    source_path = resolved_paths.get("source_screenshot_path")
    actual_source_sha = _sha256(source_path) if source_path else ""
    declared_source_hashes = [
        str(evidence.get("source_screenshot_sha256") or "").strip().lower(),
        str(evidence.get("stage1_source_screenshot_sha256") or "").strip().lower(),
        str(evidence.get("final_source_screenshot_sha256") or "").strip().lower(),
    ]
    same_source = (
        bool(actual_source_sha)
        and all(len(value) == 64 for value in declared_source_hashes)
        and len(set(declared_source_hashes)) == 1
        and declared_source_hashes[0] == actual_source_sha
    )
    if not same_source:
        blockers.append("same_source_three_image_evidence_failed")

    distinct_visuals = {
        str(resolved_paths.get("source_screenshot_path") or ""),
        str(resolved_paths.get("stage1_overlay_path") or ""),
        str(resolved_paths.get("final_fusion_overlay_path") or ""),
    }
    if "" in distinct_visuals or len(distinct_visuals) != 3:
        blockers.append("original_stage1_final_paths_not_distinct")

    panel_js = root / "app" / "web_panel" / "panel.js"
    panel_css = root / "app" / "web_panel" / "panel.css"
    current_panel_js_sha = _sha256(panel_js) if panel_js.is_file() else ""
    current_panel_css_sha = _sha256(panel_css) if panel_css.is_file() else ""
    frontend_matches = (
        bool(current_panel_js_sha)
        and bool(current_panel_css_sha)
        and str(evidence.get("panel_js_sha256") or "").strip().lower() == current_panel_js_sha
        and str(evidence.get("panel_css_sha256") or "").strip().lower() == current_panel_css_sha
    )
    if not frontend_matches:
        blockers.append("frontend_revision_mismatch")

    desktop_viewport = _dict(evidence.get("desktop_viewport"))
    narrow_viewport = _dict(evidence.get("narrow_viewport"))
    desktop_covered = (
        resolved_paths.get("desktop_panel_screenshot_path") is not None
        and _int_value(desktop_viewport.get("width")) >= 1000
        and _int_value(desktop_viewport.get("height")) > 0
    )
    narrow_width = _int_value(narrow_viewport.get("width"))
    narrow_covered = (
        resolved_paths.get("narrow_panel_screenshot_path") is not None
        and 0 < narrow_width <= 430
        and _int_value(narrow_viewport.get("height")) > 0
    )
    if not desktop_covered:
        blockers.append("desktop_viewport_not_covered")
    if not narrow_covered:
        blockers.append("narrow_viewport_not_covered")

    boolean_requirements = (
        "latest_fusion_loaded",
        "pathgraph_resizer_verified",
        "page_detail_bbox_geometry_verified",
        "stale_template_content_absent",
        "stale_draft_content_absent",
    )
    for key in boolean_requirements:
        if evidence.get(key) is not True:
            blockers.append(f"{key}_not_verified")

    blockers = _unique_text(blockers)
    accepted = not blockers
    return {
        **base,
        "accepted": accepted,
        "acceptance_status": "accepted_current_presentation" if accepted else "invalid_or_incomplete",
        "same_source_three_image_evidence": same_source,
        "frontend_revision_matches": frontend_matches,
        "desktop_viewport_covered": desktop_covered,
        "narrow_viewport_covered": narrow_covered,
        "artifact_evidence": artifact_evidence,
        "source_screenshot_sha256": actual_source_sha,
        "desktop_viewport": desktop_viewport,
        "narrow_viewport": narrow_viewport,
        "blocking_reasons": blockers,
    }


def _requirement(requirement_id: str, passed: bool, *, evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "requirement_id": requirement_id,
        "status": "passed" if passed else "failed",
        "evidence": evidence,
    }


def _blocking_reasons(scaffold: dict[str, Any], requirements: list[dict[str, Any]]) -> list[str]:
    reasons = []
    if _requirement_status(requirements, "official_candidate_fully_system_model_generated") != "passed":
        reasons.append("official_candidate_not_fully_system_model_generated")
    if _requirement_status(requirements, "pending_calibration_resolved") != "passed":
        reasons.append("pending_calibration_remaining")
    if _requirement_status(requirements, "no_execute_no_submit_safety") != "passed":
        reasons.append("safety_contract_failed")
    if _dict(scaffold.get("display_readiness")).get("model_only_demo_ready") is not True:
        reasons.append("model_only_demo_chain_not_ready")
    return reasons


def _fresh_model_chain_acceptance(
    scaffold: dict[str, Any],
    requirements: list[dict[str, Any]],
    blocking_reasons: list[str],
) -> dict[str, Any]:
    provenance = _dict(scaffold.get("model_provenance_audit"))
    actual_count = _int_value(provenance.get("actual_model_call_evidence_count"))
    assisted_count = _int_value(provenance.get("assisted_or_human_review_evidence_count"))
    provenance_blockers = [
        str(item)
        for item in (provenance.get("blocking_reasons") or [])
        if str(item).strip()
    ]
    blockers: list[str] = []
    if actual_count <= 0:
        blockers.append("missing_actual_model_call_evidence")
    if assisted_count > 0:
        blockers.append("contains_assisted_or_human_review_evidence")
    if provenance.get("meets_fully_model_generated_demo_requirement") is not True:
        blockers.append("provenance_does_not_meet_fully_model_generated_requirement")
    if _requirement_status(requirements, "pending_calibration_resolved") != "passed":
        blockers.append("pending_calibration_remaining")
    if _requirement_status(requirements, "no_execute_no_submit_safety") != "passed":
        blockers.append("safety_contract_failed")
    blockers.extend(provenance_blockers)
    blockers.extend(blocking_reasons)
    unique_blockers = _unique_text(blockers)
    accepted = not unique_blockers
    if accepted:
        status = "accepted_fresh_model_chain"
    elif assisted_count > 0 or provenance.get("meets_fully_model_generated_demo_requirement") is not True:
        status = "blocked_mixed_or_assisted_evidence"
    elif actual_count <= 0:
        status = "blocked_missing_actual_model_evidence"
    elif "pending_calibration_remaining" in unique_blockers:
        status = "blocked_pending_calibration"
    else:
        status = "blocked"
    source_breakdown = {
        "actual_model_call": actual_count,
        "assisted_or_human_review": assisted_count,
        "fixture_only": _int_value(provenance.get("fixture_only_evidence_count")),
        "recorded_model_output": _int_value(provenance.get("recorded_model_output_evidence_count")),
    }
    acceptance = {
        "contract_version": "learning_mode_fresh_model_chain_acceptance_v1",
        "accepted": accepted,
        "acceptance_status": status,
        "counts_as_final_goal_completion": accepted,
        "actual_model_call_evidence_count": actual_count,
        "assisted_or_human_review_evidence_count": assisted_count,
        "source_breakdown": source_breakdown,
        "blocking_reasons": unique_blockers,
        "required_for_acceptance": [
            "actual_model_call_evidence_count > 0",
            "assisted_or_human_review_evidence_count == 0",
            "meets_fully_model_generated_demo_requirement == true",
            "pending_calibration_resolved",
            "no_execute_no_submit_safety",
        ],
        "interpretation": (
            "Strict acceptance gate for the final Learning Mode demo goal. Display-ready model-only previews are useful, "
            "but final completion requires a fresh system/model-generated chain with no assisted or human-curated evidence."
        ),
    }
    acceptance["replacement_plan"] = _fresh_model_chain_replacement_plan(
        scaffold=scaffold,
        accepted=accepted,
        source_breakdown=source_breakdown,
        blocking_reasons=unique_blockers,
    )
    return acceptance


def _fresh_model_chain_replacement_plan(
    *,
    scaffold: dict[str, Any],
    accepted: bool,
    source_breakdown: dict[str, int],
    blocking_reasons: list[str],
) -> dict[str, Any]:
    ready_regions = _ready_region_numbers(scaffold)
    calibration_command = _calibration_command_preview(scaffold, ready_regions=ready_regions)
    refresh_command = _refresh_command_preview(scaffold, calibration_command=calibration_command)
    sources_to_replace = [
        source_type
        for source_type in ("assisted_or_human_review", "fixture_only", "recorded_model_output")
        if _int_value(source_breakdown.get(source_type)) > 0
    ]
    if accepted:
        plan_status = "accepted_no_replacement_required"
    elif "pending_calibration_remaining" in blocking_reasons:
        plan_status = "blocked_until_explicit_model_start_approval"
    else:
        plan_status = "blocked_until_fresh_model_chain"
    replacement_steps = [
        {
            "step_id": "obtain_explicit_model_start_approval",
            "status": "required" if not accepted else "not_required",
            "requires_user_approval": not accepted,
            "may_run_without_user_approval": False,
            "interpretation": "User approval is required before starting the locate/model calibration path.",
        },
        {
            "step_id": "run_fresh_numbered_region_calibration",
            "status": "blocked_until_user_approval" if not accepted else "not_required",
            "requires_user_approval": not accepted,
            "may_run_without_user_approval": False,
            "ready_region_numbers": ready_regions,
            "expected_source_type": "actual_model_call",
            "expected_output": "numbered_region_calibration_report.json",
            **calibration_command,
        },
        {
            "step_id": "refresh_model_generated_scaffold",
            "status": "blocked_until_fresh_calibration_output" if not accepted else "not_required",
            "requires_user_approval": False,
            "may_run_without_user_approval": False,
            "expected_source_type": "actual_model_call",
            "must_replace_source_types": sources_to_replace,
            "expected_outputs": [
                "learn_precise_understanding_candidate.json",
                "learn_page_detail_candidate.json",
                "learn_mode_demo_scaffold.json",
            ],
            **refresh_command,
        },
        {
            "step_id": "rerun_goal_readiness_audit",
            "status": "blocked_until_scaffold_refresh" if not accepted else "ready",
            "requires_user_approval": False,
            "may_run_without_user_approval": accepted,
            "expected_output": REPORT_NAME,
        },
    ]
    return {
        "contract_version": "learning_mode_fresh_model_chain_replacement_plan_v1",
        "replacement_required": not accepted,
        "plan_status": plan_status,
        "current_source_breakdown": dict(source_breakdown),
        "sources_to_replace": sources_to_replace,
        "required_source_type": "actual_model_call",
        "counts_as_model_ability_when_complete": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "live_clicks_allowed": False,
        "live_fills_allowed": False,
        "live_submits_allowed": False,
        "replacement_steps": replacement_steps,
        "interpretation": (
            "Read-only plan for turning the display-ready mixed chain into a final fresh system/model-generated chain. "
            "The plan describes required replacement evidence only; it does not start models, click, fill, submit, or promote Runtime PathGraph."
        ),
    }


def _unique_text(items: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        unique.append(text)
    return unique


def _attach_generated_artifacts(scaffold: dict[str, Any], *, scaffold_file: Path, root: Path) -> dict[str, Any]:
    enriched = dict(scaffold)
    generated = _dict(enriched.get("generated_artifacts"))
    artifact_map = {
        "current_evidence_packet": generated.get("current_evidence_packet_path"),
        "precise_understanding_candidate": generated.get("precise_understanding_candidate_path"),
        "page_detail_candidate": generated.get("page_detail_candidate_path"),
    }
    for key, artifact_path in artifact_map.items():
        if key == "current_evidence_packet" and enriched.get(key):
            continue
        resolved = _resolve_generated_path(artifact_path, root=root, scaffold_file=scaffold_file)
        if resolved and resolved.exists():
            enriched[key] = _read_json(resolved)
    precise = _dict(enriched.get("precise_understanding_candidate"))
    calibration_report = _resolve_generated_path(
        precise.get("source_calibration_report_path"), root=root, scaffold_file=scaffold_file
    )
    if calibration_report and calibration_report.exists():
        enriched["source_calibration_report"] = _read_json(calibration_report)
    return enriched


def _presentation_evidence_template(root: Path) -> dict[str, Any]:
    panel_js = root / "app" / "web_panel" / "panel.js"
    panel_css = root / "app" / "web_panel" / "panel.css"
    return {
        "contract_version": "learning_interface_presentation_evidence_v1",
        "template_only": True,
        "artifact_is_evidence": False,
        "source_screenshot_path": "",
        "stage1_overlay_path": "",
        "final_fusion_overlay_path": "",
        "trace_path": "",
        "desktop_panel_screenshot_path": "",
        "narrow_panel_screenshot_path": "",
        "source_screenshot_sha256": "",
        "stage1_source_screenshot_sha256": "",
        "final_source_screenshot_sha256": "",
        "panel_js_sha256": _sha256(panel_js) if panel_js.is_file() else "",
        "panel_css_sha256": _sha256(panel_css) if panel_css.is_file() else "",
        "desktop_viewport": {"width": 0, "height": 0},
        "narrow_viewport": {"width": 0, "height": 0},
        "latest_fusion_loaded": False,
        "pathgraph_resizer_verified": False,
        "page_detail_bbox_geometry_verified": False,
        "stale_template_content_absent": False,
        "stale_draft_content_absent": False,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _next_actions(scaffold: dict[str, Any], blocking_reasons: list[str], *, root: Path) -> list[dict[str, Any]]:
    summary = _dict(scaffold.get("summary"))
    generated = _dict(scaffold.get("generated_artifacts"))
    ready_regions = _ready_region_numbers(scaffold)
    pending_count = _int_value(summary.get("precise_pending_calibration_count"))
    calibration_command = _calibration_command_preview(scaffold, ready_regions=ready_regions)
    refresh_command = _refresh_command_preview(scaffold, calibration_command=calibration_command)
    actions: list[dict[str, Any]] = []
    if "pending_calibration_remaining" in blocking_reasons:
        actions.append(
            {
                "action_id": "request_explicit_model_start_approval",
                "status": "required",
                "reason": "pending_calibration_remaining",
                "requires_user_approval": True,
                "may_run_without_user_approval": False,
                "ready_region_numbers": ready_regions,
                "pending_calibration_count": pending_count,
                "safety": {
                    "starts_model_after_approval": True,
                    "live_clicks_allowed": False,
                    "live_fills_allowed": False,
                    "live_submits_allowed": False,
                    "execute_binding_enabled": False,
                },
            }
        )
        actions.append(
            {
                "action_id": "run_pending_numbered_region_calibration_batch",
                "status": "blocked_until_user_approval",
                "requires_user_approval": True,
                "may_run_without_user_approval": False,
                "ready_region_numbers": ready_regions,
                "expected_output": "numbered_region_calibration_report.json",
                **calibration_command,
                "interpretation": "Run only after explicit approval to start the locate model; keep real clicks/fills/submits at zero.",
            }
        )
        actions.append(
            {
                "action_id": "refresh_scaffold_after_calibration",
                "status": "blocked_until_calibration_output",
                "requires_user_approval": False,
                "may_run_without_user_approval": False,
                "input_after_previous_step": "numbered_region_calibration_report.json",
                "generated_artifacts_to_refresh": [
                    "precise_understanding_candidate",
                    "page_detail_candidate",
                    "model_generated_pathgraph_preview",
                    "learn_mode_demo_scaffold",
                ],
                **refresh_command,
            }
        )
    if "official_candidate_not_fully_system_model_generated" in blocking_reasons:
        actions.append(
            {
                "action_id": "replace_assisted_official_candidate_with_fresh_model_chain",
                "status": "blocked_until_fresh_model_scaffold",
                "requires_user_approval": True,
                "may_run_without_user_approval": False,
                "current_blocker": "mixed_actual_model_and_assisted_review_evidence",
                "source_scaffold_path": generated.get("model_generated_pathgraph_preview_path"),
                "interpretation": "The model-only preview can be shown in demo, but the official candidate remains mixed until a fresh model chain replaces assisted/reviewed artifacts.",
            }
        )
    if "current_presentation_evidence_not_accepted" in blocking_reasons:
        actions.append(
            {
                "action_id": "capture_current_presentation_evidence",
                "status": "required",
                "requires_user_approval": True,
                "may_run_without_user_approval": False,
                "required_artifacts": [
                    "source_screenshot",
                    "stage1_overlay",
                    "final_fusion_overlay",
                    "trace",
                    "desktop_panel_screenshot",
                    "narrow_panel_screenshot",
                ],
                "required_checks": [
                    "same_source_three_image_evidence",
                    "latest_fusion_loaded",
                    "pathgraph_resizer_verified",
                    "page_detail_bbox_geometry_verified",
                    "frontend_revision_matches",
                    "stale_template_content_absent",
                    "stale_draft_content_absent",
                ],
                "evidence_template": _presentation_evidence_template(root),
                "interpretation": (
                    "Run only after the user resumes live testing. This evidence is presentation verification, "
                    "not click authorization, Execute readiness, model accuracy, or Runtime PathGraph promotion."
                ),
            }
        )
    actions.append(
        {
            "action_id": "rerun_goal_readiness_audit",
            "status": "blocked_until_scaffold_refresh" if blocking_reasons else "ready",
            "requires_user_approval": False,
            "may_run_without_user_approval": not bool(blocking_reasons),
            "expected_output": REPORT_NAME,
        }
    )
    return actions


def _demo_evidence_map(scaffold: dict[str, Any], *, root: Path, scaffold_file: Path) -> list[dict[str, Any]]:
    generated = _dict(scaffold.get("generated_artifacts"))
    summary = _dict(scaffold.get("summary"))
    precise = _dict(scaffold.get("precise_understanding_candidate"))
    page_detail = _dict(scaffold.get("page_detail_candidate"))
    preview = _dict(scaffold.get("model_generated_pathgraph_preview"))
    preview_page_detail = _dict(preview.get("page_detail_preview"))
    preview_page_summary = _dict(preview_page_detail.get("summary"))
    model_only = _dict(scaffold.get("model_only_demo_readiness"))
    page_detail_fields = _page_detail_evidence_fields(page_detail)
    if _int_value(summary.get("precise_pending_calibration_count")) > 0:
        page_detail_fields["readiness_status"] = "needs_pending_calibration"
    return [
        _evidence_item(
            "full_screen_understanding_numbered_regions",
            root=root,
            scaffold_file=scaffold_file,
            artifact_path=precise.get("full_screen_understanding_overlay_path")
            or generated.get("full_screen_understanding_overlay_path"),
            status="available" if precise.get("full_screen_understanding_overlay_path") else "missing",
            role="whole-screen numbered-region overlay",
        ),
        _evidence_item(
            "selection_map_precise_understanding",
            root=root,
            scaffold_file=scaffold_file,
            artifact_path=precise.get("compiled_overlay_path")
            or generated.get("precise_understanding_candidate_path"),
            status="available" if generated.get("precise_understanding_candidate_path") else "missing",
            role="selection map / precise-understanding candidate",
            region_count=_int_value(_dict(precise.get("summary")).get("total_regions") or model_only.get("model_preview_region_count")),
        ),
        _evidence_item(
            "pathgraph_model_preview",
            root=root,
            scaffold_file=scaffold_file,
            artifact_path=preview.get("runtime_path_graph_model_preview_path")
            or generated.get("model_generated_pathgraph_preview_path"),
            status=preview.get("preview_status")
            or (
                "available"
                if (
                    preview.get("runtime_path_graph_model_preview_path")
                    or generated.get("model_generated_pathgraph_preview_path")
                    or _int_value(_dict(preview.get("summary")).get("region_count")) > 0
                    or _int_value(model_only.get("model_preview_region_count")) > 0
                )
                else "missing"
            ),
            role="model-only PathGraph preview",
            region_count=_int_value(_dict(preview.get("summary")).get("region_count") or model_only.get("model_preview_region_count")),
            action_count=_int_value(
                _dict(preview.get("summary")).get("action_template_count") or model_only.get("model_preview_action_count")
            ),
        ),
        _evidence_item(
            "template_like_page_detail",
            root=root,
            scaffold_file=scaffold_file,
            artifact_path=generated.get("page_detail_candidate_path") or generated.get("model_generated_pathgraph_preview_path"),
            status="available"
            if (
                generated.get("page_detail_candidate_path")
                or _int_value(preview_page_summary.get("section_count")) > 0
                or _int_value(model_only.get("model_page_detail_section_count")) > 0
            )
            else "missing",
            role="template-like page detail preview",
            section_count=_int_value(
                preview_page_summary.get("section_count")
                or _dict(page_detail.get("summary")).get("section_count")
                or model_only.get("model_page_detail_section_count")
            ),
            possible_operation_count=_int_value(
                preview_page_summary.get("possible_operation_count")
                or _dict(page_detail.get("summary")).get("possible_operation_count")
                or model_only.get("model_page_detail_possible_operation_count")
            ),
            **page_detail_fields,
        ),
    ]


_DEMO_STAGE_ORDER = [
    "full_screen_understanding_numbered_regions",
    "selection_map_precise_understanding",
    "pathgraph_model_preview",
    "template_like_page_detail",
]

_DEMO_STAGE_PROOF_FIELDS = {
    "full_screen_understanding_numbered_regions": ["artifact_sha256_prefix"],
    "selection_map_precise_understanding": ["artifact_sha256_prefix", "region_count"],
    "pathgraph_model_preview": ["action_count", "artifact_sha256_prefix", "region_count"],
    "template_like_page_detail": [
        "artifact_sha256_prefix",
        "bbox_region_count",
        "layout_mode",
        "layout_section_count",
        "operation_kinds",
        "readiness_status",
    ],
}


def _demo_chain_manifest(
    *,
    evidence_map: list[dict[str, Any]],
    display_demo_ready: bool,
    final_goal_complete: bool,
    blocking_reasons: list[str],
) -> dict[str, Any]:
    evidence_by_stage = {str(item.get("stage_id")): item for item in evidence_map}
    steps = []
    for index, stage_id in enumerate(_DEMO_STAGE_ORDER, start=1):
        evidence = evidence_by_stage.get(stage_id, {})
        expected_proof_fields = _DEMO_STAGE_PROOF_FIELDS.get(stage_id, [])
        proof_fields = [
            field
            for field in expected_proof_fields
            if _has_demo_proof_value(evidence.get(field))
        ]
        missing_proof_fields = [field for field in expected_proof_fields if field not in proof_fields]
        stage_ready = (
            evidence.get("status") not in (None, "", "missing")
            and evidence.get("artifact_exists") is True
            and evidence.get("display_only") is True
            and evidence.get("execute_binding_enabled") is False
            and evidence.get("artifact_is_authorization") is False
            and not missing_proof_fields
        )
        steps.append(
            {
                "ordinal": index,
                "stage_id": stage_id,
                "status": evidence.get("status") or "missing",
                "artifact_path": evidence.get("artifact_path") or "",
                "artifact_exists": evidence.get("artifact_exists") is True,
                "stage_ready_for_display": stage_ready,
                "proof_fields": proof_fields,
                "missing_proof_fields": missing_proof_fields,
                "display_only": evidence.get("display_only") is True,
                "execute_binding_enabled": evidence.get("execute_binding_enabled") is True,
                "artifact_is_authorization": evidence.get("artifact_is_authorization") is True,
            }
        )
    return {
        "contract_version": "learning_mode_demo_chain_manifest_v1",
        "demo_stage_order": list(_DEMO_STAGE_ORDER),
        "chain_can_be_demoed": display_demo_ready and all(item["stage_ready_for_display"] for item in steps),
        "chain_is_final_goal_complete": final_goal_complete,
        "final_goal_blockers": list(blocking_reasons),
        "steps": steps,
        "interpretation": (
            "Display-chain manifest for the interview demo. It proves the requested visual review chain is present and "
            "display-only; it does not authorize Execute, clicks, fills, submit, or Runtime PathGraph promotion."
        ),
    }


def _has_demo_proof_value(value: Any) -> bool:
    if value is None or value == "":
        return False
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    if isinstance(value, int):
        return value > 0
    return True


def _page_detail_evidence_fields(page_detail: dict[str, Any]) -> dict[str, Any]:
    layout = _dict(page_detail.get("layout"))
    sections = _list_of_dicts(layout.get("sections"))
    regions = _list_of_dicts(layout.get("regions"))
    operation_kinds = _page_detail_operation_kinds(sections=sections, regions=regions)
    fields: dict[str, Any] = {}
    if page_detail.get("layout_mode"):
        fields["layout_mode"] = str(page_detail.get("layout_mode"))
    if page_detail.get("readiness_status"):
        fields["readiness_status"] = str(page_detail.get("readiness_status"))
    if sections:
        fields["layout_section_count"] = len(sections)
    bbox_region_count = sum(1 for item in regions if _dict(item.get("bbox")))
    if bbox_region_count:
        fields["bbox_region_count"] = bbox_region_count
    if operation_kinds:
        fields["operation_kinds"] = operation_kinds
    section_summaries = _page_detail_section_summaries(sections)
    if section_summaries:
        fields["layout_section_summaries"] = section_summaries
    return fields


def _page_detail_section_summaries(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for section in sections:
        section_id = str(section.get("section_id") or "").strip()
        if not section_id:
            continue
        summary: dict[str, Any] = {"section_id": section_id}
        bbox = _dict(section.get("bbox"))
        if bbox:
            summary["bbox"] = bbox
        region_count = _int_value(section.get("region_count"))
        if region_count <= 0:
            region_count = len(_list_of_dicts(section.get("regions")))
        summary["region_count"] = region_count
        possible_operations = [
            str(item or "").strip()
            for item in (section.get("possible_operations") or [])
            if str(item or "").strip()
        ]
        if possible_operations:
            summary["possible_operations"] = possible_operations
        operation_summary = _dict(section.get("operation_summary"))
        if operation_summary:
            summary["operation_summary"] = operation_summary
        summaries.append(summary)
    return summaries


def _page_detail_operation_kinds(*, sections: list[dict[str, Any]], regions: list[dict[str, Any]]) -> list[str]:
    kinds: set[str] = set()
    for section in sections:
        for value in section.get("possible_operations") or []:
            text = str(value or "").strip()
            if text:
                kinds.add(text)
        for region in _list_of_dicts(section.get("regions")):
            kind = str(_dict(region.get("possible_operation")).get("kind") or "").strip()
            if kind:
                kinds.add(kind)
    for region in regions:
        kind = str(_dict(region.get("possible_operation")).get("kind") or "").strip()
        if kind:
            kinds.add(kind)
    return sorted(kinds)


def _evidence_item(
    stage_id: str,
    *,
    root: Path,
    scaffold_file: Path,
    artifact_path: Any,
    status: str,
    role: str,
    **extra: Any,
) -> dict[str, Any]:
    artifact_text = str(artifact_path or "")
    resolved = _resolve_generated_path(artifact_text, root=root, scaffold_file=scaffold_file)
    artifact_exists = bool(resolved and resolved.exists())
    item = {
        "stage_id": stage_id,
        "status": status,
        "role": role,
        "artifact_path": artifact_text,
        "artifact_resolved_path": str(resolved) if resolved else "",
        "artifact_exists": artifact_exists,
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }
    if artifact_exists and resolved:
        item["artifact_sha256_prefix"] = _sha256_prefix(resolved)
    item.update({key: value for key, value in extra.items() if value not in (None, "")})
    return item


def _sha256_prefix(path: Path) -> str:
    return _sha256(path)[:12]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _calibration_command_preview(scaffold: dict[str, Any], *, ready_regions: list[int]) -> dict[str, Any]:
    source_report = _dict(scaffold.get("source_calibration_report"))
    source_arg = ""
    source_value = ""
    for key in ("generated_tasks_path", "enriched_tasks_path", "tasks_path", "source_tasks_path"):
        value = str(source_report.get(key) or "").strip()
        if value:
            source_arg = "--tasks"
            source_value = value
            break
    if not source_value:
        value = str(source_report.get("actual_parser_output_path") or "").strip()
        if value:
            source_arg = "--actual-parser-output"
            source_value = value
    next_output_dir = "next_numbered_region_calibration"
    args = [
        "uv",
        "run",
        "python",
        "scripts\\run_numbered_region_calibration_probe.py",
    ]
    command_source_status = "missing_source"
    if source_arg and source_value:
        args.extend([source_arg, source_value])
        command_source_status = "ready"
    args.extend(["--out", next_output_dir, "--regions", ",".join(str(item) for item in ready_regions)])
    return {
        "command_source_status": command_source_status,
        "run_command_args": args,
        "run_command_preview": " ".join(args),
        "command_executes_now": False,
        "requires_user_or_runner_to_start_model": True,
        "start_model_flag_included": False,
        "next_output_dir": next_output_dir,
    }


def _refresh_command_preview(scaffold: dict[str, Any], *, calibration_command: dict[str, Any]) -> dict[str, Any]:
    preview = _embedded_post_batch_refresh_preview(scaffold)
    if preview:
        return {
            "command_source_status": "ready",
            "run_command_args": [],
            "run_command_preview": preview,
            "command_executes_now": False,
            "requires_completed_batch_output": True,
            "start_model_flag_included": "--start-model" in preview,
            "requires_user_or_runner_to_start_model": False,
        }
    trial_path = str(_dict(scaffold.get("model_generated_pathgraph_preview")).get("source_path") or "").strip()
    evidence_integrity = _dict(_dict(scaffold.get("current_evidence_packet")).get("evidence_integrity"))
    source_status = _dict(evidence_integrity.get("source_status_report"))
    base_status_path = str(source_status.get("path") or source_status.get("declared_path") or "").strip()
    next_output_dir = str(calibration_command.get("next_output_dir") or "next_numbered_region_calibration")
    rerun_report_path = str(Path(next_output_dir) / "numbered_region_calibration_report.json")
    out_dir = "post_batch_refresh"
    args = [
        "uv",
        "run",
        "python",
        "scripts\\refresh_learn_fusion_after_calibration_batch.py",
    ]
    command_source_status = "missing_source"
    if trial_path and base_status_path:
        args.extend(["--trial", trial_path, "--base-status", base_status_path])
        command_source_status = "ready"
    args.extend(["--rerun-report", rerun_report_path, "--out", out_dir])
    return {
        "command_source_status": command_source_status,
        "run_command_args": args,
        "run_command_preview": " ".join(args),
        "command_executes_now": False,
        "requires_completed_batch_output": True,
        "start_model_flag_included": False,
        "requires_user_or_runner_to_start_model": False,
        "expected_rerun_report_path": rerun_report_path,
        "next_output_dir": out_dir,
    }


def _embedded_post_batch_refresh_preview(scaffold: dict[str, Any]) -> str:
    for container in (
        _dict(scaffold.get("current_evidence_packet")),
        _dict(scaffold.get("precise_understanding_candidate")),
        _dict(scaffold.get("model_generated_pathgraph_preview")),
    ):
        for key in ("calibration_batch_plan", "pathgraph_preflight_plan", "model_start_runbook"):
            value = _dict(container.get(key)).get("post_batch_refresh_command_preview")
            if value:
                return str(value)
        value = container.get("post_batch_refresh_command_preview")
        if value:
            return str(value)
    return ""


def _next_action_status(next_actions: list[dict[str, Any]], final_goal_complete: bool) -> str:
    if final_goal_complete:
        return "complete"
    if any(item.get("action_id") == "request_explicit_model_start_approval" for item in next_actions):
        return "awaiting_explicit_model_start_approval"
    if any(item.get("action_id") == "capture_current_presentation_evidence" for item in next_actions):
        return "awaiting_presentation_verification"
    if any(str(item.get("status") or "").startswith("blocked") for item in next_actions):
        return "blocked_until_prior_artifact"
    return "ready_for_rerun"


def _ready_region_numbers(scaffold: dict[str, Any]) -> list[int]:
    candidates: list[Any] = []
    for container in (
        _dict(scaffold.get("current_evidence_packet")),
        _dict(scaffold.get("precise_understanding_candidate")),
        _dict(scaffold.get("model_only_demo_readiness")),
    ):
        candidates.extend(_list_of_dicts(container.get("pending_calibration_batch")))
        candidates.extend(_list_of_dicts(container.get("calibration_backlog")))
        candidates.extend(_list_of_dicts(container.get("items")))
    packet = _dict(scaffold.get("current_evidence_packet"))
    calibration = _dict(packet.get("calibration"))
    readiness = _dict(calibration.get("readiness_summary"))
    for key in (
        "pending_ready_region_numbers",
        "calibration_batch_ready_region_numbers",
        "batch_ready_region_numbers",
        "ready_region_numbers",
    ):
        value = readiness.get(key) or calibration.get(key) or packet.get(key)
        if isinstance(value, list):
            return sorted({_int_value(item) for item in value if _int_value(item) > 0})
    precise = _dict(scaffold.get("precise_understanding_candidate"))
    summary = _dict(precise.get("summary"))
    value = summary.get("pending_ready_region_numbers") or precise.get("calibration_batch_ready_region_numbers")
    if isinstance(value, list):
        return sorted({_int_value(item) for item in value if _int_value(item) > 0})
    return sorted(
        {
            _int_value(item.get("region_no"))
            for item in candidates
            if _int_value(item.get("region_no")) > 0 and _is_ready_calibration_region(item)
        }
    )


def _is_ready_calibration_region(item: dict[str, Any]) -> bool:
    calibration_state = str(item.get("calibration_state") or "").lower()
    required_next_step = str(item.get("required_next_step") or "").lower()
    status = str(item.get("triage_status") or item.get("status") or item.get("calibration_status") or "").lower()
    if calibration_state == "pending_execute_dry_run_calibration":
        return True
    if required_next_step == "run_execute_dry_run_calibration_for_numbered_region":
        return True
    if calibration_state in {
        "review_before_calibration",
        "calibrated_safe_intercept_review_required",
        "blocked",
    }:
        return False
    if status in {"review_before_calibration", "blocked", "gate_rejected", "pre_click_rejected"}:
        return False
    return not calibration_state and not status


def _requirement_status(requirements: list[dict[str, Any]], requirement_id: str) -> str:
    for item in requirements:
        if item.get("requirement_id") == requirement_id:
            return str(item.get("status") or "not_covered")
    return "not_covered"


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _resolve_path(path: str | Path, root: Path) -> Path:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = root / resolved
    return resolved.resolve()


def _resolve_generated_path(path: Any, *, root: Path, scaffold_file: Path) -> Path | None:
    if not path:
        return None
    resolved = Path(str(path))
    if resolved.is_absolute():
        return resolved.resolve()
    root_relative = (root / resolved).resolve()
    if root_relative.exists():
        return root_relative
    return (scaffold_file.parent / resolved).resolve()


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return str(path.resolve())


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit Learning Mode demo goal readiness from a scaffold report.")
    parser.add_argument("--scaffold", required=True, help="Path to learn_mode_demo_scaffold.json.")
    parser.add_argument(
        "--presentation-evidence",
        help="Optional standalone learning_interface_presentation_evidence_v1 JSON file.",
    )
    parser.add_argument("--out", help="Directory for learning_mode_demo_goal_readiness_report.json.")
    parser.add_argument("--json", action="store_true", help="Print the report as JSON.")
    args = parser.parse_args()
    report_learning_mode_demo_goal_readiness(
        scaffold_path=args.scaffold,
        presentation_evidence_path=args.presentation_evidence,
        out_dir=args.out,
        json_stdout=args.json,
    )


if __name__ == "__main__":
    main()
