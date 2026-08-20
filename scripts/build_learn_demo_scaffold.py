from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.learn.draft_review import clear_learning_draft_sidecar_cache, load_learning_draft_review
from app.learn.pathgraph_candidate import build_model_generated_pathgraph_preview
from scripts.build_learn_page_detail_candidate import build_learn_page_detail_candidate
from scripts.build_learn_precise_understanding_candidate import build_learn_precise_understanding_candidate
from scripts.report_learn_fusion_current_evidence_packet import report_learn_fusion_current_evidence_packet
from scripts.report_learn_fusion_pathgraph_integration_readiness import report_learn_fusion_pathgraph_integration_readiness


REPORT_NAME = "learn_mode_demo_scaffold.json"


def build_learn_demo_scaffold(
    *,
    source_path: str | Path,
    out_dir: str | Path,
    project_root: str | Path | None = None,
    json_stdout: bool = False,
) -> dict[str, Any]:
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    source_file = _resolve_path(source_path, root)
    out = _resolve_path(out_dir, root)
    out.mkdir(parents=True, exist_ok=True)
    source_contract = _source_contract_version(source_file)
    source_is_page_detail_candidate = source_contract == "learn_page_detail_candidate_v1"
    page_detail_source = _page_detail_source_for_scaffold(source_file, root)

    generated: dict[str, Any] = {}
    failures: list[dict[str, str]] = []
    flow_status_overrides: dict[str, str] = {}
    if source_is_page_detail_candidate:
        flow_status_overrides["full_screen_understanding_numbered_regions"] = "skipped_source_is_page_detail_candidate"
        flow_status_overrides["precise_understanding_candidate"] = "skipped_source_is_page_detail_candidate"
        flow_status_overrides["current_evidence_packet"] = "skipped_source_is_page_detail_candidate"
        failures.append(
            {
                "step_id": "precise_understanding_candidate",
                "status": "skipped",
                "reason": "source_is_page_detail_candidate",
            }
        )
        precise = {}
        page_detail = _load_page_detail_candidate_for_scaffold(source_file, failures)
        if page_detail:
            generated["page_detail_candidate_path"] = _relative_path(source_file, root)
    else:
        precise = _run_step(
            failures,
            "precise_understanding_candidate",
            lambda: build_learn_precise_understanding_candidate(source_path=source_file, out_dir=out, project_root=root),
        )
        if precise:
            generated["precise_understanding_candidate_path"] = _display_path(precise.get("report_path"), root=root)
        page_detail = _run_step(
            failures,
            "page_detail_candidate",
            lambda: build_learn_page_detail_candidate(source_path=page_detail_source, out_dir=out, project_root=root),
        )
        if page_detail:
            generated["page_detail_candidate_path"] = _display_path(page_detail.get("report_path"), root=root)

    integration: dict[str, Any] = {}
    if _is_pathgraph_candidate(source_file):
        integration = _run_step(
            failures,
            "pathgraph_integration_readiness",
            lambda: report_learn_fusion_pathgraph_integration_readiness(
                pathgraph_candidate_path=source_file,
                out_dir=out,
                project_root=root,
            ),
        )
        if integration:
            generated["pathgraph_integration_readiness_path"] = _display_path(integration.get("report_path"), root=root)
    else:
        failures.append(
            {
                "step_id": "pathgraph_integration_readiness",
                "status": "skipped",
                "reason": "source_is_not_pathgraph_candidate",
            }
        )

    if source_is_page_detail_candidate:
        failures.append(
            {
                "step_id": "current_evidence_packet",
                "status": "skipped",
                "reason": "source_is_page_detail_candidate",
            }
        )
        current_packet = {}
    else:
        current_packet = _run_step(
            failures,
            "current_evidence_packet",
            lambda: report_learn_fusion_current_evidence_packet(source_path=source_file, out_dir=out, project_root=root),
        )
    if current_packet:
        generated["current_evidence_packet_path"] = _display_path(current_packet.get("report_path"), root=root)

    review = _safe_load_review(source_file, root)
    candidate_review = _dict(review.get("pathgraph_candidate_review"))
    readiness = _dict(candidate_review.get("pathgraph_readiness_summary"))
    model_provenance = _model_provenance_audit(source_file=source_file, review=review, root=root)
    model_preview: dict[str, Any] = {}
    actual_model_source = _first_actual_model_source(model_provenance, root)
    if actual_model_source is not None:
        model_preview = _run_step(
            failures,
            "model_generated_pathgraph_preview",
            lambda: build_model_generated_pathgraph_preview(
                actual_model_source,
                out_dir=out,
                project_root=root,
            ),
        )
        if model_preview:
            generated["model_generated_pathgraph_preview_path"] = _display_path(model_preview.get("report_path"), root=root)
    page_detail_readonly_preview: dict[str, Any] = {}
    if source_is_page_detail_candidate and page_detail:
        page_detail_readonly_preview = _run_step(
            failures,
            "page_detail_readonly_pathgraph_preview",
            lambda: _build_page_detail_readonly_pathgraph_preview(page_detail=page_detail, out_dir=out, root=root),
        )
        if page_detail_readonly_preview:
            generated["page_detail_readonly_pathgraph_preview_path"] = _display_path(
                page_detail_readonly_preview.get("report_path"),
                root=root,
            )
    model_only_demo = _model_only_demo_readiness(model_provenance=model_provenance, model_preview=model_preview)
    page_detail_pathgraph_correspondence = _page_detail_pathgraph_correspondence(
        page_detail=page_detail,
        pathgraph_preview=model_preview or page_detail_readonly_preview,
    )
    page_detail_summary = _dict(page_detail.get("summary")) if page_detail else {}
    readonly_summary = _dict(page_detail_readonly_preview.get("summary")) if page_detail_readonly_preview else {}
    source_identity = _dict(page_detail.get("source_identity")) if page_detail else {}
    same_repaired_source_verified = bool(
        source_identity.get("contract_version") == "learning_repaired_source_identity_v1"
        and source_identity.get("final_numbering_revision")
        and source_identity.get("compiled_overlay_path")
        and source_identity.get("dual_stream_contract") == "learn_stage2_dual_streams_v1"
    )
    report = {
        "contract_version": "learn_mode_demo_scaffold_v1",
        "source_path": _relative_path(source_file, root),
        "source_identity": source_identity,
        "page_detail_candidate_source_path": _relative_path(page_detail_source, root),
        "report_path": str((out / REPORT_NAME).resolve()),
        "generated_artifacts": generated,
        "flow": _flow_steps(
            precise=precise,
            page_detail=page_detail,
            current_packet=current_packet,
            integration=integration,
            readiness=readiness,
            model_preview=model_preview,
            page_detail_readonly_preview=page_detail_readonly_preview,
            flow_status_overrides=flow_status_overrides,
        ),
        "summary": {
            "artifact_count": len(generated),
            "failure_count": len([item for item in failures if item.get("status") != "skipped"]),
            "skipped_count": len([item for item in failures if item.get("status") == "skipped"]),
            "page_detail_region_count": _int_value(_dict(page_detail.get("summary")).get("region_count")) if page_detail else 0,
            "page_detail_section_count": _int_value(_dict(page_detail.get("summary")).get("section_count")) if page_detail else 0,
            "page_detail_display_group_count": _int_value(page_detail_summary.get("display_group_count")),
            "page_detail_list_group_count": _int_value(page_detail_summary.get("list_group_count")),
            "page_detail_possible_operation_count": (
                _int_value(_dict(page_detail.get("summary")).get("possible_operation_count")) if page_detail else 0
            ),
            "precise_pending_calibration_count": (
                _int_value(_dict(precise.get("summary")).get("pending_calibration_count")) if precise else 0
            ),
            "pathgraph_readiness_status": readiness.get("readiness_status"),
            "integration_readiness_status": integration.get("integration_readiness_status") if integration else None,
            "actual_model_call_evidence_count": model_provenance["actual_model_call_evidence_count"],
            "assisted_or_human_review_evidence_count": model_provenance["assisted_or_human_review_evidence_count"],
            "model_generated_pathgraph_preview_status": model_preview.get("preview_status") if model_preview else None,
            "model_generated_pathgraph_preview_region_count": _int_value(
                _dict(model_preview.get("summary")).get("region_count")
            )
            if model_preview
            else 0,
            "model_generated_pathgraph_preview_action_count": _int_value(
                _dict(model_preview.get("summary")).get("action_template_count")
            )
            if model_preview
            else 0,
            "model_generated_page_detail_section_count": _int_value(
                _dict(_dict(model_preview.get("page_detail_preview")).get("summary")).get("section_count")
            )
            if model_preview
            else 0,
            "model_generated_page_detail_possible_operation_count": _int_value(
                _dict(_dict(model_preview.get("page_detail_preview")).get("summary")).get("possible_operation_count")
            )
            if model_preview
            else 0,
            "page_detail_readonly_pathgraph_preview_status": page_detail_readonly_preview.get("preview_status")
            if page_detail_readonly_preview
            else None,
            "page_detail_readonly_pathgraph_preview_region_count": _int_value(readonly_summary.get("region_count")),
            "page_detail_readonly_pathgraph_preview_action_count": _int_value(
                readonly_summary.get("action_template_count")
            ),
            "page_detail_readonly_pathgraph_preview_section_count": _int_value(readonly_summary.get("section_count")),
            "page_detail_readonly_pathgraph_preview_display_group_count": _int_value(
                readonly_summary.get("display_group_count")
            ),
            "page_detail_pathgraph_shared_section_count": len(
                page_detail_pathgraph_correspondence.get("shared_section_ids") or []
            ),
            "page_detail_pathgraph_shared_display_group_count": len(
                page_detail_pathgraph_correspondence.get("shared_display_group_ids") or []
            ),
            "model_only_demo_readiness_status": model_only_demo.get("status"),
            "model_only_demo_ready": model_only_demo.get("ready") is True,
        },
        "model_provenance_audit": model_provenance,
        "page_detail_candidate": page_detail,
        "page_detail_pathgraph_correspondence": page_detail_pathgraph_correspondence,
        "model_generated_pathgraph_preview": model_preview,
        "page_detail_readonly_pathgraph_preview": page_detail_readonly_preview,
        "model_only_demo_readiness": model_only_demo,
        "display_readiness": {
            "learning_draft_can_load": bool(review),
            "pathgraph_detail_can_show_page_detail": bool(page_detail),
            "template_like_layout_available": bool(page_detail and _dict(page_detail.get("summary")).get("section_count")),
            "page_detail_pathgraph_correspondence_ready": (
                page_detail_pathgraph_correspondence.get("correspondence_status") == "layout_correspondence_available"
            ),
            "model_generated_pathgraph_preview_available": bool(model_preview),
            "page_detail_readonly_pathgraph_preview_available": bool(page_detail_readonly_preview),
            "same_repaired_source_verified": same_repaired_source_verified,
            "model_only_demo_ready": model_only_demo.get("ready") is True,
            "requires_pending_calibration": _int_value(_dict(precise.get("summary")).get("pending_calibration_count")) > 0
            if precise
            else False,
            "ready_for_runtime_pathgraph_promotion": False,
            "meets_fully_model_generated_demo_requirement": model_provenance[
                "meets_fully_model_generated_demo_requirement"
            ],
        },
        "failures": failures,
        "safety": {
            "display_only": True,
            "model_started": False,
            "live_clicks": 0,
            "live_fills": 0,
            "live_submits": 0,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "runtime_pathgraph_promotion": False,
        },
        "interpretation": (
            "Review-only Learning Mode demo scaffold. It refreshes existing full-screen/numbered-region review artifacts "
            "into precise-understanding, current-evidence, integration-readiness, and page-detail sidecars for panel display. "
            "It records whether the underlying evidence is fresh model output, assisted review, or mixed. "
            "The model-only demo readiness is separate from official candidate promotion readiness. "
            "It does not start models, click, fill, submit, authorize Execute, or promote Runtime PathGraph."
        ),
    }
    output_path = out / REPORT_NAME
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    clear_learning_draft_sidecar_cache()
    if json_stdout:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def _page_detail_pathgraph_correspondence(*, page_detail: dict[str, Any], pathgraph_preview: dict[str, Any]) -> dict[str, Any]:
    page_layout = _dict(page_detail.get("layout"))
    page_sections = _list_of_dicts(page_layout.get("sections"))
    page_display_groups = _list_of_dicts(page_layout.get("display_groups"))
    preview_page_detail = _dict(pathgraph_preview.get("page_detail_preview"))
    preview_layout = _dict(preview_page_detail.get("layout"))
    preview_sections = _list_of_dicts(preview_layout.get("sections"))
    preview_display_groups = _list_of_dicts(preview_layout.get("display_groups"))
    page_ids = [str(item.get("section_id") or "").strip() for item in page_sections if str(item.get("section_id") or "").strip()]
    preview_ids = [
        str(item.get("section_id") or "").strip()
        for item in preview_sections
        if str(item.get("section_id") or "").strip()
    ]
    page_group_ids = [
        str(item.get("group_id") or "").strip()
        for item in page_display_groups
        if str(item.get("group_id") or "").strip()
    ]
    preview_group_ids = [
        str(item.get("group_id") or "").strip()
        for item in preview_display_groups
        if str(item.get("group_id") or "").strip()
    ]
    shared = sorted(set(page_ids) & set(preview_ids))
    page_only = sorted(set(page_ids) - set(preview_ids))
    preview_only = sorted(set(preview_ids) - set(page_ids))
    shared_groups = sorted(set(page_group_ids) & set(preview_group_ids))
    page_only_groups = sorted(set(page_group_ids) - set(preview_group_ids))
    preview_only_groups = sorted(set(preview_group_ids) - set(page_group_ids))
    if page_sections and preview_sections:
        status = "layout_correspondence_available" if shared else "layout_sources_available_no_shared_sections"
    elif page_sections:
        status = "page_detail_available_pathgraph_preview_missing"
    else:
        status = "page_detail_missing"
    return {
        "contract_version": "learn_page_detail_pathgraph_correspondence_v1",
        "correspondence_status": status,
        "page_detail_candidate_available": bool(page_sections),
        "pathgraph_preview_available": bool(preview_sections),
        "shared_section_ids": shared,
        "page_detail_only_section_ids": page_only,
        "pathgraph_preview_only_section_ids": preview_only,
        "shared_display_group_ids": shared_groups,
        "page_detail_only_display_group_ids": page_only_groups,
        "pathgraph_preview_only_display_group_ids": preview_only_groups,
        "page_detail_layout_source": page_detail.get("contract_version") or "",
        "pathgraph_preview_layout_source": preview_page_detail.get("contract_version") or "",
        "page_detail_sections": _section_summaries(page_sections),
        "pathgraph_preview_sections": _section_summaries(preview_sections),
        "page_detail_display_groups": _display_group_summaries(page_display_groups),
        "pathgraph_preview_display_groups": _display_group_summaries(preview_display_groups),
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "runtime_pathgraph_promotion": False,
        "interpretation": (
            "Display-only correspondence audit between the template-like page detail candidate and the read-only "
            "PathGraph preview page-detail layout. Shared section ids show that both views can be rendered from "
            "matching bar/region buckets, but they are not an exact geometry-equivalence proof and this does not "
            "authorize Execute or Runtime PathGraph promotion."
        ),
    }


def _build_page_detail_readonly_pathgraph_preview(*, page_detail: dict[str, Any], out_dir: Path, root: Path) -> dict[str, Any]:
    layout = _dict(page_detail.get("layout"))
    regions = _list_of_dicts(layout.get("regions"))
    sections = _list_of_dicts(layout.get("sections"))
    display_groups = _list_of_dicts(layout.get("display_groups"))
    states = [_readonly_state_from_section(section, index) for index, section in enumerate(sections)]
    actions = [
        _readonly_action_from_region(region, index)
        for index, region in enumerate(regions)
        if _readonly_action_from_region(region, index)
    ]
    preview_status = "page_detail_readonly_preview_ready" if regions and sections else "page_detail_readonly_preview_incomplete"
    preview_dir = out_dir / "page_detail_readonly_pathgraph_preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    report_path = preview_dir / "page_detail_readonly_pathgraph_preview.json"
    source_identity = _dict(page_detail.get("source_identity"))
    report = {
        "contract_version": "page_detail_readonly_pathgraph_preview_v1",
        "preview_status": preview_status,
        "source_type": "learn_page_detail_candidate_v1",
        "source_identity": source_identity,
        "page_detail_preview": page_detail,
        "readonly_path_graph_preview": {
            "contract_version": "readonly_pathgraph_preview_v1",
            "source_identity": source_identity,
            "states": states,
            "action_templates": actions,
            "transitions": [],
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "runtime_pathgraph_promotion": False,
        },
        "summary": {
            "state_count": len(states),
            "region_count": len(regions),
            "section_count": len(sections),
            "display_group_count": len(display_groups),
            "action_template_count": len(actions),
            "possible_operation_count": sum(1 for item in regions if isinstance(item.get("possible_operation"), dict)),
        },
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "runtime_pathgraph_promotion": False,
        "safety": {
            "display_only": True,
            "model_started": False,
            "live_clicks": 0,
            "live_fills": 0,
            "live_submits": 0,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "runtime_pathgraph_promotion": False,
        },
        "interpretation": (
            "Display-only PathGraph preview synthesized from the reviewed page-detail layout so the panel can show "
            "section/region/group correspondence. It is not a Runtime PathGraph, does not bind Execute, and cannot "
            "authorize clicks, fills, submits, or promotion."
        ),
    }
    report["report_path"] = str(report_path.resolve())
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _readonly_state_from_section(section: dict[str, Any], index: int) -> dict[str, Any]:
    section_id = str(section.get("section_id") or f"section_{index + 1}").strip()
    return {
        "state_id": section_id,
        "label": section.get("label") or section_id,
        "bbox": _section_bbox(section),
        "region_refs": [str(item) for item in section.get("region_numbers") or [] if str(item)],
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _readonly_action_from_region(region: dict[str, Any], index: int) -> dict[str, Any] | None:
    operation = _dict(region.get("possible_operation"))
    kind = _text(operation.get("kind"), operation.get("operation_type"))
    if not kind:
        return None
    region_id = str(region.get("region_id") or f"region_{index + 1}").strip()
    action_id = f"readonly_{index + 1}_{_slug(kind, fallback='inspect')}"
    return {
        "action_template_id": action_id,
        "label": operation.get("label") or region.get("label") or kind,
        "semantic_action": kind,
        "target_region_id": region_id,
        "target_entity": region_id,
        "source_region_no": region.get("region_no"),
        "no_dispatch": True,
        "requires_gate": True,
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "final_submit_forbidden": True,
    }


def _slug(value: str, *, fallback: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")
    return cleaned[:80] or fallback


def _display_group_summaries(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for group in groups:
        group_id = str(group.get("group_id") or "").strip()
        if not group_id:
            continue
        summaries.append(
            {
                "group_id": group_id,
                "role": group.get("role") or "group",
                "label": group.get("label") or group_id,
                "bbox": _normalized_bbox(_dict(group.get("bbox"))),
                "member_region_numbers": [item for item in group.get("member_region_numbers") or []],
            }
        )
    return summaries


def _section_summaries(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for section in sections:
        section_id = str(section.get("section_id") or "").strip()
        if not section_id:
            continue
        summary = {
            "section_id": section_id,
            "label": section.get("label") or section_id,
            "bbox": _section_bbox(section),
            "region_count": _int_value(section.get("region_count")) or len(_list_of_dicts(section.get("regions"))),
            "possible_operations": [
                str(item or "").strip()
                for item in (section.get("possible_operations") or [])
                if str(item or "").strip()
            ],
        }
        operation_summary = _dict(section.get("operation_summary"))
        if operation_summary:
            summary["operation_summary"] = operation_summary
        summaries.append(summary)
    return summaries


def _section_bbox(section: dict[str, Any]) -> dict[str, int]:
    explicit = _dict(section.get("bbox"))
    explicit_box = _normalized_bbox(explicit)
    if explicit_box:
        return explicit_box
    boxes = [_normalized_bbox(_dict(region.get("bbox"))) for region in _list_of_dicts(section.get("regions"))]
    boxes = [box for box in boxes if box]
    if not boxes:
        return {}
    min_x = min(box["x"] for box in boxes)
    min_y = min(box["y"] for box in boxes)
    max_x = max(box["x"] + box["w"] for box in boxes)
    max_y = max(box["y"] + box["h"] for box in boxes)
    return {"x": min_x, "y": min_y, "w": max_x - min_x, "h": max_y - min_y}


def _normalized_bbox(bbox: dict[str, Any]) -> dict[str, int]:
    try:
        x = int(round(float(bbox.get("x"))))
        y = int(round(float(bbox.get("y"))))
        w = int(round(float(bbox.get("w", bbox.get("width")))))
        h = int(round(float(bbox.get("h", bbox.get("height")))))
    except (TypeError, ValueError):
        return {}
    if w <= 0 or h <= 0:
        return {}
    return {"x": x, "y": y, "w": w, "h": h}


def _flow_steps(
    *,
    precise: dict[str, Any],
    page_detail: dict[str, Any],
    current_packet: dict[str, Any],
    integration: dict[str, Any],
    readiness: dict[str, Any],
    model_preview: dict[str, Any],
    page_detail_readonly_preview: dict[str, Any],
    flow_status_overrides: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    overrides = flow_status_overrides or {}

    def status_for(step_id: str, default: str) -> str:
        return overrides.get(step_id) or default

    return [
        {
            "step_id": "full_screen_understanding_numbered_regions",
            "status": status_for(
                "full_screen_understanding_numbered_regions",
                "available" if current_packet else "not_loaded",
            ),
            "artifact_path": _text(current_packet.get("report_path")) if current_packet else "",
        },
        {
            "step_id": "precise_understanding_candidate",
            "status": status_for(
                "precise_understanding_candidate",
                _text(precise.get("readiness_status")) if precise else "failed_or_missing",
            ),
            "artifact_path": _text(precise.get("report_path")) if precise else "",
        },
        {
            "step_id": "pathgraph_candidate_review",
            "status": _text(readiness.get("readiness_status"), readiness.get("validation_status")) or "not_loaded",
        },
        {
            "step_id": "model_generated_pathgraph_preview",
            "status": _text(model_preview.get("preview_status")) if model_preview else "not_available",
            "artifact_path": _text(model_preview.get("report_path")) if model_preview else "",
        },
        {
            "step_id": "page_detail_readonly_pathgraph_preview",
            "status": _text(page_detail_readonly_preview.get("preview_status"))
            if page_detail_readonly_preview
            else "not_available",
            "artifact_path": _text(page_detail_readonly_preview.get("report_path"))
            if page_detail_readonly_preview
            else "",
        },
        {
            "step_id": "pathgraph_integration_readiness",
            "status": _text(integration.get("integration_readiness_status")) if integration else "not_applicable_or_missing",
            "artifact_path": _text(integration.get("report_path")) if integration else "",
        },
        {
            "step_id": "template_like_page_detail",
            "status": _text(page_detail.get("readiness_status")) if page_detail else "failed_or_missing",
            "artifact_path": _text(page_detail.get("report_path")) if page_detail else "",
        },
    ]


def _run_step(failures: list[dict[str, str]], step_id: str, fn) -> dict[str, Any]:
    try:
        result = fn()
        return result if isinstance(result, dict) else {}
    except Exception as exc:  # pragma: no cover - 回传给面板，比吞掉错误更可审计
        failures.append({"step_id": step_id, "status": "failed", "reason": str(exc)})
        return {}


def _load_page_detail_candidate_for_scaffold(source_file: Path, failures: list[dict[str, str]]) -> dict[str, Any]:
    try:
        payload = json.loads(source_file.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        failures.append({"step_id": "page_detail_candidate", "status": "failed", "reason": str(exc)})
        return {}
    if not isinstance(payload, dict) or payload.get("contract_version") != "learn_page_detail_candidate_v1":
        failures.append(
            {
                "step_id": "page_detail_candidate",
                "status": "failed",
                "reason": "source_is_not_learn_page_detail_candidate_v1",
            }
        )
        return {}
    payload = dict(payload)
    payload.setdefault("report_path", str(source_file.resolve()))
    return payload


def _source_contract_version(path: Path) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("contract_version") or "")


def _page_detail_source_for_scaffold(source_file: Path, root: Path) -> Path:
    if not _is_pathgraph_candidate(source_file):
        return source_file
    try:
        wrapper = json.loads(source_file.read_text(encoding="utf-8-sig"))
    except Exception:
        return source_file
    if not isinstance(wrapper, dict):
        return source_file
    candidates: list[Path] = []
    reviewed_value = wrapper.get("reviewed_template_candidate_path")
    if isinstance(reviewed_value, str) and reviewed_value.strip():
        reviewed_path = _resolve_path(reviewed_value, root)
        try:
            reviewed = json.loads(reviewed_path.read_text(encoding="utf-8-sig"))
        except Exception:
            reviewed = {}
        source = _dict(reviewed.get("source")) if isinstance(reviewed, dict) else {}
        for key in ("original_draft_path", "source_trial_path", "source_path"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                candidates.append(_resolve_path(value, root))
        candidates.append(reviewed_path)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return source_file


def _model_provenance_audit(*, source_file: Path, review: dict[str, Any], root: Path) -> dict[str, Any]:
    evidence_paths = _model_provenance_paths(source_file=source_file, review=review, root=root)
    evidence = [_artifact_model_evidence(path=path, root=root, role=role) for role, path in evidence_paths]
    actual_count = sum(1 for item in evidence if item.get("actual_model_call_in_this_run") is True)
    recorded_count = sum(1 for item in evidence if _text(item.get("source_type")).startswith("recorded"))
    assisted_count = sum(
        1
        for item in evidence
        if item.get("reviewed_by_human") is True
        or _text(item.get("source_after_review")) in {"assisted_generation", "mixed", "human_curated"}
        or item.get("counts_as_pure_model_generated") is False
    )
    if actual_count and not assisted_count:
        status = "fresh_model_generated_chain_evidence_present"
    elif actual_count:
        status = "mixed_actual_model_and_assisted_review_evidence"
    elif recorded_count:
        status = "recorded_model_output_only"
    else:
        status = "not_fresh_model_generated"
    blockers = []
    if not actual_count:
        blockers.append("missing_actual_model_call_evidence")
    if assisted_count:
        blockers.append("contains_assisted_or_human_review_evidence")
    meets_requirement = status == "fresh_model_generated_chain_evidence_present"
    return {
        "contract_version": "learn_mode_demo_model_provenance_audit_v1",
        "status": status,
        "meets_fully_model_generated_demo_requirement": meets_requirement,
        "actual_model_call_evidence_count": actual_count,
        "recorded_model_output_evidence_count": recorded_count,
        "assisted_or_human_review_evidence_count": assisted_count,
        "evidence": evidence,
        "blocking_reasons": blockers,
        "interpretation": (
            "This audit separates fresh system-model output from recorded, assisted, or human-reviewed artifacts. "
            "A visible page detail scaffold is not enough to claim a fully model-generated demo."
        ),
    }


def _first_actual_model_source(audit: dict[str, Any], root: Path) -> Path | None:
    for item in _list_of_dicts(audit.get("evidence")):
        if item.get("actual_model_call_in_this_run") is not True:
            continue
        if item.get("counts_as_pure_model_generated") is False:
            continue
        value = item.get("path")
        if isinstance(value, str) and value.strip():
            path = _resolve_path(value, root)
            if path.exists():
                return path
    return None


def _model_only_demo_readiness(*, model_provenance: dict[str, Any], model_preview: dict[str, Any]) -> dict[str, Any]:
    preview_summary = _dict(model_preview.get("summary"))
    page_detail = _dict(model_preview.get("page_detail_preview"))
    page_summary = _dict(page_detail.get("summary"))
    blockers = []
    if _int_value(model_provenance.get("actual_model_call_evidence_count")) < 1:
        blockers.append("missing_actual_model_call_evidence")
    if model_preview.get("preview_status") != "model_generated_preview_ready":
        blockers.append("model_generated_pathgraph_preview_not_ready")
    if _int_value(preview_summary.get("region_count")) < 1:
        blockers.append("model_preview_missing_regions")
    if _int_value(preview_summary.get("action_template_count")) < 1:
        blockers.append("model_preview_missing_actions")
    if page_detail.get("contract_version") != "model_generated_page_detail_preview_v1":
        blockers.append("model_page_detail_preview_missing")
    if _int_value(page_summary.get("section_count")) < 1:
        blockers.append("model_page_detail_missing_sections")
    if _int_value(page_summary.get("possible_operation_count")) < 1:
        blockers.append("model_page_detail_missing_possible_operations")
    ready = not blockers
    return {
        "contract_version": "learn_mode_model_only_demo_readiness_v1",
        "ready": ready,
        "status": "model_only_demo_ready" if ready else "model_only_demo_blocked",
        "blocking_reasons": blockers,
        "actual_model_call_evidence_count": _int_value(model_provenance.get("actual_model_call_evidence_count")),
        "model_preview_status": model_preview.get("preview_status"),
        "model_preview_region_count": _int_value(preview_summary.get("region_count")),
        "model_preview_action_count": _int_value(preview_summary.get("action_template_count")),
        "model_page_detail_section_count": _int_value(page_summary.get("section_count")),
        "model_page_detail_possible_operation_count": _int_value(page_summary.get("possible_operation_count")),
        "official_candidate_fully_model_generated": model_provenance.get(
            "meets_fully_model_generated_demo_requirement"
        )
        is True,
        "interpretation": (
            "Ready means the demo-only chain can show raw model output -> PathGraph preview -> page detail preview. "
            "It does not mean the official reviewed PathGraph candidate is pure-model generated or executable."
        ),
    }


def _model_provenance_paths(*, source_file: Path, review: dict[str, Any], root: Path) -> list[tuple[str, Path]]:
    paths: list[tuple[str, Path]] = [("requested_source", source_file)]
    source = _dict(review.get("source"))
    for key in ("original_draft_path", "source_trial_path", "source_path"):
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            paths.append((f"review_source.{key}", _resolve_path(value, root)))
    try:
        payload = json.loads(source_file.read_text(encoding="utf-8-sig"))
    except Exception:
        payload = {}
    if isinstance(payload, dict):
        for key in ("reviewed_template_candidate_path", "runtime_path_graph_candidate_path", "validation_report_path"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                paths.append((f"wrapper.{key}", _resolve_path(value, root)))
    expanded: list[tuple[str, Path]] = []
    scanned: set[str] = set()
    queue = list(paths)
    while queue:
        role, path = queue.pop(0)
        expanded.append((role, path))
        path_key = str(path.resolve())
        if path_key in scanned or not path.exists():
            continue
        scanned.add(path_key)
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        payload_source = _dict(payload.get("source"))
        for key in ("original_draft_path", "source_trial_path", "source_path"):
            value = payload_source.get(key)
            if isinstance(value, str) and value.strip():
                queue.append((f"{role}.source.{key}", _resolve_path(value, root)))
        for key in (
            "source_path",
            "source_trial_path",
            "reviewed_template_candidate_path",
            "actual_parser_output_path",
            "actual_grounding_output_path",
        ):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                queue.append((f"{role}.{key}", _resolve_path(value, root)))
    seen: set[str] = set()
    unique: list[tuple[str, Path]] = []
    for role, path in expanded:
        path_key = str(path.resolve())
        if path_key in seen:
            continue
        seen.add(path_key)
        unique.append((role, path))
    return unique


def _artifact_model_evidence(*, path: Path, root: Path, role: str) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "role": role,
        "path": _relative_path(path, root),
        "exists": path.exists(),
    }
    if not path.exists():
        return evidence
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        evidence["read_error"] = str(exc)
        return evidence
    if not isinstance(payload, dict):
        evidence["read_error"] = "payload_not_object"
        return evidence
    source = _dict(payload.get("source"))
    evidence.update(
        {
            "contract_version": payload.get("contract_version"),
            "source_type": payload.get("source_type"),
            "actual_model_call_in_this_run": payload.get("actual_model_call_in_this_run") is True,
            "source_after_review": payload.get("source_after_review") or source.get("source_after_review"),
            "counts_as_pure_model_generated": payload.get("counts_as_pure_model_generated"),
            "reviewed_by_human": payload.get("reviewed_by_human") is True,
            "model_generated": payload.get("model_generated") is True or _dict(payload.get("metadata")).get("model_generated") is True,
            "screenshot_path": payload.get("screenshot_path"),
            "screenshot_sha256": payload.get("screenshot_sha256"),
        }
    )
    return evidence


def _safe_load_review(source_file: Path, root: Path) -> dict[str, Any]:
    try:
        return load_learning_draft_review(_relative_path(source_file, root), project_root=root)
    except Exception:
        return {}


def _is_pathgraph_candidate(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return False
    return isinstance(payload, dict) and payload.get("contract_version") == "pathgraph_candidate_v1"


def _resolve_path(path: str | Path, root: Path) -> Path:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = root / resolved
    return resolved.resolve()


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return str(path.resolve())


def _display_path(value: Any, *, root: Path) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return _relative_path(_resolve_path(value, root), root)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a review-only Learning Mode demo scaffold.")
    parser.add_argument("--source", required=True, help="Learning draft source or pathgraph_candidate.json")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--json", action="store_true", help="Print JSON report")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report = build_learn_demo_scaffold(source_path=args.source, out_dir=args.out, json_stdout=args.json)
    return 0 if not report.get("summary", {}).get("failure_count") else 1


if __name__ == "__main__":
    raise SystemExit(main())
