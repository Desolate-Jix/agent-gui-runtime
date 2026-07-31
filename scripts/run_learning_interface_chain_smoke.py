from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from app.core.gpu_resources import build_model_resource_preflight
from app.core.model_server import ensure_model_server, profile_for_stage
from app.main import app


@dataclass(frozen=True)
class ChainSmokeCase:
    case_id: str
    trace_path: str
    source_image_path: str
    trace_sha256: str = ""
    source_image_sha256: str = ""
    app_family: str = ""
    interface_category: str = ""
    expectations: dict[str, Any] = field(default_factory=dict)


def build_manifest_cases(manifest_path: Path) -> list[ChainSmokeCase]:
    """从当前分类递归清单加载可复跑且校验过的学习链样本。"""
    resolved_manifest = _resolve_project_path(manifest_path)
    payload = _read_json(resolved_manifest)
    raw_cases = payload.get("cases") if isinstance(payload.get("cases"), list) else []
    cases: list[ChainSmokeCase] = []
    for raw_case in raw_cases:
        if not isinstance(raw_case, dict):
            continue
        case_id = str(raw_case.get("case_id") or "").strip()
        trace_path = str(raw_case.get("trace_path") or "").strip()
        source_image_path = str(raw_case.get("screenshot_path") or raw_case.get("image_path") or "").strip()
        if not case_id or not trace_path or not source_image_path:
            raise ValueError(f"manifest case missing required evidence fields: {case_id or '<unknown>'}")
        resolved_trace = _resolve_project_path(Path(trace_path))
        resolved_image = _resolve_project_path(Path(source_image_path))
        trace_sha256 = str(raw_case.get("trace_sha256") or "").strip().lower()
        source_image_sha256 = str(raw_case.get("screenshot_sha256") or "").strip().lower()
        if not trace_sha256 or not source_image_sha256:
            raise ValueError(f"manifest case missing checksum evidence: {case_id}")
        _require_matching_sha256(resolved_trace, trace_sha256, case_id=case_id, evidence_type="trace")
        _require_matching_sha256(resolved_image, source_image_sha256, case_id=case_id, evidence_type="screenshot")
        expectations = raw_case.get("expectations") if isinstance(raw_case.get("expectations"), dict) else {}
        cases.append(
            ChainSmokeCase(
                case_id=case_id,
                trace_path=str(resolved_trace),
                source_image_path=str(resolved_image),
                trace_sha256=trace_sha256,
                source_image_sha256=source_image_sha256,
                app_family=str(raw_case.get("app_family") or "").strip(),
                interface_category=str(expectations.get("expected_interface_category") or "").strip(),
                expectations=dict(expectations),
            )
        )
    if not cases:
        raise ValueError(f"manifest contains no runnable cases: {resolved_manifest}")
    return cases


def build_manifest_suite_cases(manifest_paths: list[Path]) -> list[ChainSmokeCase]:
    """合并多个验收清单，并禁止重复样本缩小真实分母。"""
    if not manifest_paths:
        raise ValueError("acceptance suite requires at least one manifest")
    cases: list[ChainSmokeCase] = []
    seen: set[str] = set()
    duplicates: set[str] = set()
    for manifest_path in manifest_paths:
        for case in build_manifest_cases(manifest_path):
            if case.case_id in seen:
                duplicates.add(case.case_id)
            else:
                seen.add(case.case_id)
                cases.append(case)
    if duplicates:
        raise ValueError(f"duplicate acceptance case ids: {', '.join(sorted(duplicates))}")
    return cases


def load_resume_completed_case_ids(
    report_paths: list[Path],
    *,
    expected_manifest_paths: list[str],
    known_case_ids: set[str],
) -> list[str]:
    """从同一验收清单的历史报告恢复已完成样本。"""
    expected_manifests = {
        str(_resolve_project_path(Path(value))).casefold() for value in expected_manifest_paths
    }
    completed: list[str] = []
    seen: set[str] = set()
    allowed_contracts = {
        "learning_interface_chain_smoke_report_v2",
        "learning_practical_acceptance_aggregate_v1",
    }
    for report_path in report_paths:
        resolved_report = _resolve_project_path(report_path)
        payload = _read_json(resolved_report)
        contract_version = str(payload.get("contract_version") or "")
        if contract_version not in allowed_contracts:
            raise ValueError(f"unsupported acceptance resume report contract: {resolved_report}")
        report_manifests = {
            str(_resolve_project_path(Path(value))).casefold()
            for value in payload.get("manifest_paths") or []
            if str(value).strip()
        }
        if report_manifests != expected_manifests:
            raise ValueError(f"acceptance resume report manifest set mismatch: {resolved_report}")
        for raw_case_id in payload.get("completed_case_ids") or []:
            case_id = str(raw_case_id).strip()
            if case_id not in known_case_ids:
                raise ValueError(f"acceptance resume report contains unknown completed case: {case_id}")
            if case_id in seen:
                raise ValueError(f"duplicate completed case across acceptance resume reports: {case_id}")
            seen.add(case_id)
            completed.append(case_id)
    return completed


def build_acceptance_batch_plan(
    cases: list[ChainSmokeCase],
    *,
    resource_preflight: dict[str, Any],
    requested_case_ids: list[str] | None = None,
    completed_case_ids: list[str] | None = None,
    requested_batch_size: int | None = None,
    batch_index: int = 0,
) -> dict[str, Any]:
    """按资源建议和显式筛选生成可续跑验收批次。"""
    if batch_index < 0:
        raise ValueError("batch_index must be zero or greater")
    requested = {str(case_id).strip() for case_id in requested_case_ids or [] if str(case_id).strip()}
    known = {case.case_id for case in cases}
    unknown = sorted(requested - known)
    if unknown:
        raise ValueError(f"unknown case ids: {', '.join(unknown)}")
    eligible = [case for case in cases if not requested or case.case_id in requested]
    if not eligible:
        raise ValueError("acceptance batch contains no eligible cases")
    completed = {str(case_id).strip() for case_id in completed_case_ids or [] if str(case_id).strip()}
    if completed and batch_index != 0:
        raise ValueError("batch_index must remain zero when completed_case_ids are supplied")
    unknown_completed = sorted(completed - known)
    if unknown_completed:
        raise ValueError(f"unknown completed case ids: {', '.join(unknown_completed)}")
    completed_in_scope = [case.case_id for case in eligible if case.case_id in completed]
    remaining = [case for case in eligible if case.case_id not in completed]
    if not remaining:
        raise ValueError("all eligible acceptance cases are already completed")

    recommended = max(1, int(resource_preflight.get("recommended_batch_size") or 1))
    batch_size = max(1, int(requested_batch_size or recommended))
    start = batch_index * batch_size
    end = start + batch_size
    selected = remaining[start:end]
    if not selected:
        raise ValueError(
            f"batch_index {batch_index} is outside {len(remaining)} remaining cases with batch_size {batch_size}"
        )
    selected_ids = [case.case_id for case in selected]
    return {
        "contract_version": "learning_interface_acceptance_batch_plan_v1",
        "resource_mode": str(resource_preflight.get("resource_mode") or "unknown"),
        "model_launch_allowed": resource_preflight.get("model_launch_allowed") is True,
        "recommended_batch_size": recommended,
        "batch_size": batch_size,
        "batch_index": batch_index,
        "eligible_case_ids": [case.case_id for case in eligible],
        "completed_case_ids": completed_in_scope,
        "remaining_case_ids": [case.case_id for case in remaining],
        "selected_case_ids": selected_ids,
        "pending_case_ids": [case.case_id for case in remaining if case.case_id not in selected_ids],
    }


def build_resource_blocked_report(
    *,
    batch_plan: dict[str, Any],
    resource_preflight: dict[str, Any],
    out_dir: Path,
    manifest_paths: list[str] | None = None,
    resume_report_paths: list[str] | None = None,
) -> dict[str, Any]:
    """资源不足时在任何真实模型调用前记录可恢复暂停。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "learning_interface_chain_smoke_report.json"
    report = {
        "contract_version": "learning_interface_chain_smoke_report_v2",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "status": "resource_blocked",
        "case_count": 0,
        "invalid_case_count": 0,
        "model_calls_attempted": 0,
        "completed_case_ids": [],
        "pending_case_ids": list(
            batch_plan.get("remaining_case_ids") or batch_plan.get("eligible_case_ids") or []
        ),
        "manifest_paths": list(manifest_paths or []),
        "resume_report_paths": list(resume_report_paths or []),
        "batch_plan": dict(batch_plan),
        "resource_preflight": dict(resource_preflight),
        "safety": _safety_boundary(),
        "report_path": str(report_path),
        "interpretation": (
            "GPU resource gate stopped the acceptance batch before model launch; "
            "pending cases are not counted as passed or failed."
        ),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def build_chain_model_resource_preflight() -> dict[str, Any]:
    """使用精准定位模型配置执行同一套生产资源预检。"""
    return build_model_resource_preflight(profile_for_stage("locate"))


def ensure_acceptance_model_stage(stage: str, *, wait_seconds: float = 600.0) -> dict[str, Any]:
    """启动并等待验收批次需要的真实模型，未就绪时禁止继续。"""

    lifecycle = ensure_model_server(
        stage=stage,
        wait_until_ready=True,
        wait_seconds=wait_seconds,
    )
    status_payload = lifecycle.get("after") if isinstance(lifecycle.get("after"), dict) else lifecycle.get("before")
    status_payload = status_payload if isinstance(status_payload, dict) else {}
    status = str(status_payload.get("status") or "unknown")
    if status != "running":
        raise RuntimeError(f"acceptance model stage {stage} is not ready: {status}")
    profile = lifecycle.get("profile") if isinstance(lifecycle.get("profile"), dict) else {}
    return {
        "stage": stage,
        "status": status,
        "profile_id": str(profile.get("profile_id") or ""),
        "model_id": str(status_payload.get("model_id") or ""),
        "started": lifecycle.get("started") is True,
        "resource_switch": lifecycle.get("resource_switch")
        if isinstance(lifecycle.get("resource_switch"), dict)
        else {},
    }


def evaluate_class_expectations(report: dict[str, Any], expectations: dict[str, Any]) -> dict[str, Any]:
    if not expectations:
        return {
            "contract_version": "learning_interface_class_expectation_audit_v1",
            "status": "not_covered",
            "issues": [],
            "interpretation": "No class-specific expectations were declared for this legacy case.",
        }

    classification = report.get("interface_classification") if isinstance(report.get("interface_classification"), dict) else {}
    class_profile = report.get("class_rule_profile") if isinstance(report.get("class_rule_profile"), dict) else {}
    hierarchy = report.get("ui_hierarchy") if isinstance(report.get("ui_hierarchy"), dict) else {}
    nodes = hierarchy.get("nodes") if isinstance(hierarchy.get("nodes"), list) else []
    nodes = [node for node in nodes if isinstance(node, dict)]
    structure_nodes = [node for node in nodes if str(node.get("level") or "") == "structure_region"]
    structure_types = sorted({str(node.get("component_type") or "") for node in structure_nodes if node.get("component_type")})
    role_counts: dict[str, int] = {}
    for node in nodes:
        role = str(node.get("component_type") or "").strip()
        if role:
            role_counts[role] = role_counts.get(role, 0) + 1
    labels = "\n".join(str(node.get("label") or "") for node in nodes).casefold()

    expected_bar_types = {
        str(value or "").strip() for value in expectations.get("expected_bar_types") or []
    } - {""}
    expected_absent_bar_types = {
        str(value or "").strip() for value in expectations.get("expected_absent_bar_types") or []
    } - {""}
    expected_sub_bar_roles = {
        str(value or "").strip() for value in expectations.get("expected_sub_bar_roles") or []
    } - {""}
    known_bar_types = {"top_bar", "bottom_bar", "left_sidebar", "right_sidebar"}
    declared_bar_types = expected_bar_types | expected_absent_bar_types | known_bar_types
    actual_bar_types = sorted(set(structure_types) & declared_bar_types)

    actual_category = str(classification.get("category") or "").strip()
    actual_strategy = str(class_profile.get("primary_content_strategy") or "").strip()
    stage1_5_partition = report.get("stage1_5_partition") if isinstance(report.get("stage1_5_partition"), dict) else {}
    stage1_5_subregions = (
        stage1_5_partition.get("subregions")
        if isinstance(stage1_5_partition.get("subregions"), list)
        else []
    )
    stage1_5_roles = {
        str(item.get("role") or "").strip()
        for item in stage1_5_subregions
        if isinstance(item, dict) and str(item.get("role") or "").strip()
    }
    sub_bar_evidence_sources: dict[str, str] = {}
    for role in expected_sub_bar_roles:
        if role_counts.get(role, 0) > 0:
            sub_bar_evidence_sources[role] = "ui_hierarchy"
        elif role in stage1_5_roles:
            sub_bar_evidence_sources[role] = "stage1_5_partition"
    if (
        "conversation_navigation_rail" in expected_sub_bar_roles
        and actual_category == "conversation_workspace"
        and "left_sidebar" in structure_types
    ):
        sub_bar_evidence_sources["conversation_navigation_rail"] = "conversation_workspace_left_sidebar_root"
    actual_sub_bar_roles = sorted(sub_bar_evidence_sources)
    expected_category = str(expectations.get("expected_interface_category") or "").strip()
    expected_strategy = str(expectations.get("expected_class_strategy") or "").strip()
    issues: list[str] = []
    if expected_category and actual_category != expected_category:
        issues.append("interface_category_mismatch")
    if expected_strategy and actual_strategy != expected_strategy:
        issues.append("class_strategy_mismatch")

    minimum_structure_regions = int(expectations.get("min_structure_regions") or 0)
    if len(structure_nodes) < minimum_structure_regions:
        issues.append("insufficient_structure_regions")
    minimum_hierarchy_nodes = int(expectations.get("min_hierarchy_nodes") or 0)
    if len(nodes) < minimum_hierarchy_nodes:
        issues.append("insufficient_hierarchy_nodes")

    for required_type in expectations.get("required_structure_types") or []:
        normalized = str(required_type or "").strip()
        if normalized and normalized not in structure_types:
            issues.append(f"missing_structure_type:{normalized}")
    for bar_type in sorted(expected_bar_types):
        if bar_type not in structure_types:
            issues.append(f"missing_expected_bar_type:{bar_type}")
    for bar_type in sorted(expected_absent_bar_types):
        if bar_type in structure_types:
            issues.append(f"unexpected_bar_type:{bar_type}")
    for role in sorted(expected_sub_bar_roles):
        if role not in sub_bar_evidence_sources:
            issues.append(f"missing_expected_sub_bar_role:{role}")
    required_roles = expectations.get("required_group_roles") if isinstance(expectations.get("required_group_roles"), dict) else {}
    for role, minimum in required_roles.items():
        normalized = str(role or "").strip()
        if normalized and role_counts.get(normalized, 0) < int(minimum or 0):
            issues.append(f"insufficient_required_role:{normalized}")
    for role in expectations.get("forbidden_group_roles") or []:
        normalized = str(role or "").strip()
        if normalized and role_counts.get(normalized, 0) > 0:
            issues.append(f"forbidden_group_role_present:{normalized}")
    for role in expectations.get("forbidden_item_roles") or []:
        normalized = str(role or "").strip()
        if normalized and role_counts.get(normalized, 0) > 0:
            issues.append(f"forbidden_item_role_present:{normalized}")
    matched_forbidden_tokens: list[str] = []
    for token in expectations.get("forbidden_label_tokens") or []:
        normalized = str(token or "").strip().casefold()
        if normalized and normalized in labels:
            matched_forbidden_tokens.append(normalized)
            issues.append(f"forbidden_label_token_present:{normalized}")

    return {
        "contract_version": "learning_interface_class_expectation_audit_v1",
        "status": "passed" if not issues else "needs_review",
        "expected": dict(expectations),
        "actual": {
            "interface_category": actual_category,
            "class_strategy": actual_strategy,
            "structure_region_count": len(structure_nodes),
            "structure_types": structure_types,
            "bar_types": actual_bar_types,
            "sub_bar_roles": actual_sub_bar_roles,
            "sub_bar_evidence_sources": sub_bar_evidence_sources,
            "hierarchy_node_count": len(nodes),
            "group_role_counts": role_counts,
            "matched_forbidden_label_tokens": matched_forbidden_tokens,
        },
        "issues": issues,
        "interpretation": "Class-rule conformance and contamination audit; not recognition accuracy evidence.",
    }


def evaluate_saved_class_expectations(
    two_stage_data: dict[str, Any], expectations: dict[str, Any]
) -> dict[str, Any]:
    report_path_value = str(two_stage_data.get("report_path") or "").strip()
    if not expectations:
        audit = evaluate_class_expectations({}, expectations)
        audit["evidence_source"] = "not_covered"
        audit["report_path"] = report_path_value
        return audit
    report_path = _resolve_path(report_path_value)
    if report_path is None or not report_path.exists():
        return {
            "contract_version": "learning_interface_class_expectation_audit_v1",
            "status": "needs_review",
            "expected": dict(expectations),
            "actual": {},
            "issues": ["class_expectation_report_missing"],
            "evidence_source": "saved_two_stage_report_missing",
            "report_path": report_path_value,
            "interpretation": "Class-rule audit requires the complete saved two-stage report; not recognition accuracy evidence.",
        }
    audit = evaluate_class_expectations(_read_json(report_path), expectations)
    audit["evidence_source"] = "saved_two_stage_report"
    audit["report_path"] = report_path_value
    return audit


def summarize_class_expectation_audits(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {"passed": 0, "needs_review": 0, "not_covered": 0}
    for item in case_results:
        audit = item.get("class_expectation_audit") if isinstance(item.get("class_expectation_audit"), dict) else {}
        status = str(audit.get("status") or "not_covered")
        if status in counts:
            counts[status] += 1
        else:
            counts["needs_review"] += 1
    return {
        **counts,
        "interpretation": "Class-rule conformance counts only; not recognition accuracy evidence.",
    }


def _resolve_project_path(path: Path) -> Path:
    resolved = path if path.is_absolute() else ROOT / path
    if not resolved.exists():
        raise FileNotFoundError(f"fixture evidence missing: {resolved}")
    return resolved.resolve()


def _require_matching_sha256(path: Path, expected: str, *, case_id: str, evidence_type: str) -> None:
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError(
            f"{case_id} {evidence_type} checksum mismatch: expected={expected} actual={actual} path={path}"
        )


def _image_evidence(path_value: str) -> dict[str, Any]:
    path = _resolve_path(path_value)
    exists = bool(path and path.exists() and path.is_file())
    return {
        "path": str(path_value or ""),
        "exists": exists,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if exists and path is not None else "",
    }


def build_three_image_audit(*, source_path: str, stage1_path: str, final_path: str) -> dict[str, Any]:
    """记录原图、Stage1 分栏图、最终融合图，供逐图审核而不是混合推断。"""

    source = _image_evidence(source_path)
    stage1 = _image_evidence(stage1_path)
    final = _image_evidence(final_path)
    return {
        "contract_version": "learning_interface_three_image_audit_v1",
        "source": source,
        "stage1_bar_localization": stage1,
        "final_fused_overlay": final,
        "complete": all(item["exists"] for item in (source, stage1, final)),
        "interpretation": "Three separate images for visual review; not recognition accuracy evidence by itself.",
    }


def build_post_calibration_three_image_audit(
    *,
    source_path: str,
    stage1_path: str,
    stage2_path: str,
    deep_calibration: dict[str, Any],
) -> dict[str, Any]:
    verified_final = (
        deep_calibration.get("success") is True
        and deep_calibration.get("final_fusion_overlay") is True
        and deep_calibration.get("base_visual_source") == "two_stage_numbered_overlay"
    )
    audit = build_three_image_audit(
        source_path=source_path,
        stage1_path=stage1_path,
        final_path=str(deep_calibration.get("overlay_path") or "") if verified_final else "",
    )
    audit["stage2_numbered_overlay"] = _image_evidence(stage2_path)
    audit["final_fusion_verified"] = verified_final
    audit["final_fusion_base_visual_source"] = str(deep_calibration.get("base_visual_source") or "")
    return audit


def audit_stage1_geometry(report_path: str) -> dict[str, Any]:
    """用同一报告中的结构证据检查粗栏是否保留了大段无依据空间。"""

    resolved = _resolve_path(report_path)
    if resolved is None or not resolved.exists():
        return {
            "contract_version": "learning_stage1_geometry_audit_v1",
            "status": "not_covered",
            "issues": ["two_stage_report_missing"],
            "report_path": str(report_path or ""),
            "interpretation": "Geometry audit unavailable; this is not recognition accuracy evidence.",
        }
    report = _read_json(resolved)
    stage1_structure = report.get("stage1_structure") if isinstance(report.get("stage1_structure"), dict) else {}
    stage1_localization = (
        report.get("stage1_region_localization")
        if isinstance(report.get("stage1_region_localization"), dict)
        else {}
    )
    structure_regions = (
        stage1_structure.get("structure_regions")
        if isinstance(stage1_structure.get("structure_regions"), list)
        else []
    )
    localized_regions = (
        stage1_localization.get("regions") if isinstance(stage1_localization.get("regions"), list) else []
    )

    def bbox(value: Any) -> dict[str, int] | None:
        if not isinstance(value, dict):
            return None
        try:
            parsed = {key: int(value.get(key) or 0) for key in ("x", "y", "w", "h")}
        except (TypeError, ValueError):
            return None
        return parsed if parsed["w"] > 0 and parsed["h"] > 0 else None

    page_header_boxes = [
        parsed
        for region in structure_regions
        if isinstance(region, dict) and str(region.get("zone_id") or "").casefold() == "page_header"
        for parsed in [bbox(region.get("bbox"))]
        if parsed
    ]
    top_bar_boxes = [
        parsed
        for region in localized_regions
        if isinstance(region, dict) and str(region.get("zone_id") or "").casefold() == "top_bar"
        for parsed in [bbox(region.get("bbox") or region.get("precise_bbox"))]
        if parsed
    ]
    if not page_header_boxes or not top_bar_boxes:
        return {
            "contract_version": "learning_stage1_geometry_audit_v1",
            "status": "not_covered",
            "issues": [],
            "report_path": str(resolved),
            "interpretation": "No comparable top-bar/page-header pair; this is not recognition accuracy evidence.",
        }

    page_header_bottom = max(item["y"] + item["h"] for item in page_header_boxes)
    page_header_height = max(item["h"] for item in page_header_boxes)
    top_bar_bottom = max(item["y"] + item["h"] for item in top_bar_boxes)
    unsupported_extent = max(0, top_bar_bottom - page_header_bottom)
    tolerance = max(48, int(page_header_height * 1.5))
    issues = []
    if unsupported_extent > tolerance:
        issues.append("top_bar_extent_not_supported_by_page_header_evidence")
    return {
        "contract_version": "learning_stage1_geometry_audit_v1",
        "status": "needs_review" if issues else "passed",
        "issues": issues,
        "report_path": str(resolved),
        "top_bar_bottom": top_bar_bottom,
        "page_header_evidence_bottom": page_header_bottom,
        "unsupported_extent": unsupported_extent,
        "tolerance": tolerance,
        "interpretation": "Evidence-consistency audit only; not recognition accuracy or model reliability evidence.",
    }


def build_learn_calibration_metadata(two_stage_report_path: str) -> dict[str, Any]:
    return {
        "learn_all_targets": True,
        "learn_all_targets_reason": "Learning interface chain smoke must calibrate every numbered region before fusion.",
        "two_stage_report_path": str(two_stage_report_path or "").strip(),
        "learn_vista_coordinate_validation": {
            "enabled": True,
            "max_targets": "all",
            "stop_on_failure": False,
            "use_numbered_overlay": True,
        },
    }


def build_protected_cases(regression_root: Path) -> list[ChainSmokeCase]:
    cases: list[ChainSmokeCase] = []
    for case_id in ["applemusic", "qq", "python_org"]:
        case_dir = regression_root / case_id
        reports = sorted(case_dir.glob("learn_two_stage_replay_report_*.json"))
        if not reports:
            raise FileNotFoundError(f"missing replay report for {case_id}: {case_dir}")
        report = _read_json(reports[-1])
        observe_bundle = report.get("observe_bundle") if isinstance(report.get("observe_bundle"), dict) else {}
        source_override = report.get("source_image_override") if isinstance(report.get("source_image_override"), dict) else {}
        trace_path = str(report.get("source_trace_path") or "").strip()
        source_image_path = str(
            source_override.get("path")
            or observe_bundle.get("source_image_path")
            or observe_bundle.get("image_path")
            or ""
        ).strip()
        if not trace_path:
            raise ValueError(f"missing source trace for {case_id}")
        if not source_image_path:
            raise ValueError(f"missing source image for {case_id}")
        cases.append(ChainSmokeCase(case_id=case_id, trace_path=trace_path, source_image_path=source_image_path))
    return cases


def classify_case_quality(summary: dict[str, Any]) -> dict[str, Any]:
    issues: list[str] = []
    case_id = str(summary.get("case_id") or "").strip().lower()
    deep = summary.get("deep_calibration") if isinstance(summary.get("deep_calibration"), dict) else {}
    trial = summary.get("trial") if isinstance(summary.get("trial"), dict) else {}
    two_stage = summary.get("two_stage") if isinstance(summary.get("two_stage"), dict) else {}
    page_detail = summary.get("page_detail") if isinstance(summary.get("page_detail"), dict) else {}
    scaffold = summary.get("scaffold") if isinstance(summary.get("scaffold"), dict) else {}
    draft_counts = trial.get("draft_section_counts") if isinstance(trial.get("draft_section_counts"), dict) else {}

    stage1_gate_status = str(two_stage.get("stage1_gate_status") or "").strip()
    if stage1_gate_status and stage1_gate_status != "passed":
        issues.append("stage1_gate_not_passed")
    if two_stage.get("stage2_numbering_skipped") is True:
        issues.append("stage2_numbering_skipped")
    stage2_was_expected = two_stage.get("stage2_numbering_skipped") is False
    deep_evidence_count = int(deep.get("review_box_count") or 0) + int(deep.get("calibration_target_count") or 0)
    if deep_evidence_count <= 0:
        issues.append("missing_deep_review_boxes")
    if stage2_was_expected and int(trial.get("two_stage_review_region_count") or 0) <= 0:
        issues.append("missing_two_stage_review_regions")
    if int(draft_counts.get("regions") or 0) <= 0:
        issues.append("missing_draft_regions")
    if int(page_detail.get("region_count") or 0) <= 0:
        issues.append("missing_page_detail_regions")
    if scaffold.get("page_detail_readonly_pathgraph_preview_status") != "page_detail_readonly_preview_ready":
        issues.append("missing_readonly_pathgraph_preview")
    stage1_geometry_audit = (
        summary.get("stage1_geometry_audit") if isinstance(summary.get("stage1_geometry_audit"), dict) else {}
    )
    if stage1_geometry_audit.get("status") == "needs_review":
        issues.append("stage1_geometry_needs_review")
    class_expectation_audit = (
        summary.get("class_expectation_audit")
        if isinstance(summary.get("class_expectation_audit"), dict)
        else {}
    )
    if class_expectation_audit.get("status") == "needs_review":
        issues.append("class_expectation_needs_review")

    three_image_audit = summary.get("three_image_audit") if isinstance(summary.get("three_image_audit"), dict) else None
    if three_image_audit is not None and three_image_audit.get("complete") is not True:
        issues.append("three_image_audit_incomplete")

    stress_sample = "python" in case_id
    if stress_sample:
        issues.append("python_org_stress_sample")
    status = "needs_review" if issues else "review_only_chain_ready"
    if stress_sample:
        status = "stress_only_needs_review"

    return {
        "status": status,
        "issues": issues,
        "runtime_pathgraph_ready": False,
        "execute_binding_enabled": False,
        "interpretation": (
            "display/review-only chain quality; not recognition accuracy or Runtime PathGraph readiness. "
            "Python.org is kept as a protected stress sample, not a success baseline."
        ),
    }


def classify_chain_completion(summary: dict[str, Any]) -> dict[str, Any]:
    required_steps = ["two_stage", "deep_calibration", "trial", "page_detail", "scaffold"]
    transport_success = all(bool((summary.get(key) or {}).get("success")) for key in required_steps)
    two_stage = summary.get("two_stage") if isinstance(summary.get("two_stage"), dict) else {}
    issues: list[str] = []
    if str(two_stage.get("stage1_gate_status") or "").strip() != "passed":
        issues.append("stage1_gate_not_passed")
    if two_stage.get("stage2_numbering_skipped") is not False:
        issues.append("stage2_numbering_skipped")
    stage1_geometry_audit = (
        summary.get("stage1_geometry_audit") if isinstance(summary.get("stage1_geometry_audit"), dict) else {}
    )
    if stage1_geometry_audit.get("status") == "needs_review":
        issues.append("stage1_geometry_needs_review")
    class_expectation_audit = (
        summary.get("class_expectation_audit")
        if isinstance(summary.get("class_expectation_audit"), dict)
        else {}
    )
    if class_expectation_audit.get("status") == "needs_review":
        issues.append("class_expectation_needs_review")
    three_image_audit = summary.get("three_image_audit") if isinstance(summary.get("three_image_audit"), dict) else {}
    if three_image_audit.get("complete") is not True:
        issues.append("three_image_audit_incomplete")
    if three_image_audit.get("final_fusion_verified") is not True:
        issues.append("final_fusion_not_verified")
    if not transport_success:
        issues.append("required_step_failed")
    return {
        "success": transport_success and not issues,
        "transport_success": transport_success,
        "issues": issues,
        "interpretation": "Full read-only learning chain completion; not recognition accuracy or Execute readiness.",
    }


def run_case(client: TestClient, case: ChainSmokeCase, out_dir: Path) -> dict[str, Any]:
    trace_path = Path(case.trace_path)
    trace = _read_json(trace_path)
    observe_result = _trace_result(trace)
    source_image_path = str(case.source_image_path)
    source_image = Path(source_image_path)
    if not source_image.exists():
        source_image = ROOT / source_image_path
    if not source_image.exists():
        raise FileNotFoundError(f"{case.case_id} source image missing: {case.source_image_path}")

    state_hint = str(observe_result.get("state_guess") or observe_result.get("state_hint") or "home")
    summary: dict[str, Any] = {
        "case_id": case.case_id,
        "source_trace_path": str(trace_path),
        "source_image_path": str(source_image),
        "state_hint": state_hint,
        "safety": _safety_boundary(),
    }

    two_stage_payload = {
        "app_name": case.case_id,
        "state_hint": state_hint,
        "trace_path": str(trace_path),
        "source_image_path": str(source_image),
        "observe_result": observe_result,
        "require_stage1_gate": True,
        "stage2_region_strategy": "partitioned",
    }
    two_stage = _post_json(client, "/panel/run_learning_two_stage_understanding", two_stage_payload)
    two_stage_data = two_stage.get("data") if isinstance(two_stage.get("data"), dict) else {}
    summary["class_expectation_audit"] = evaluate_saved_class_expectations(two_stage_data, case.expectations)
    fusion = two_stage_data.get("fusion") if isinstance(two_stage_data.get("fusion"), dict) else {}
    fused_boxes = fusion.get("fused_review_boxes") if isinstance(fusion.get("fused_review_boxes"), list) else []
    summary["two_stage"] = {
        "success": bool(two_stage.get("success")),
        "report_path": two_stage_data.get("report_path"),
        "stage1_gate_status": (two_stage_data.get("stage1_gate") or {}).get("status")
        if isinstance(two_stage_data.get("stage1_gate"), dict)
        else "",
        "stage2_numbering_skipped": two_stage_data.get("stage2_numbering_skipped"),
        "stage1_overlay_path": (
            (two_stage_data.get("stage1_region_localization") or {}).get("overlay_path")
            if isinstance(two_stage_data.get("stage1_region_localization"), dict)
            else ""
        )
        or fusion.get("stage1_structure_overlay_path")
        or _two_stage_stage1_overlay_path(two_stage_data),
        "overlay_path": two_stage_data.get("coordinate_overlay_path")
        or two_stage_data.get("compiled_overlay_path")
        or fusion.get("compiled_overlay_path")
        or two_stage_data.get("full_screen_understanding_overlay_path"),
        "review_box_count": len(fused_boxes) or _two_stage_review_box_count(two_stage_data),
    }
    summary["stage1_geometry_audit"] = audit_stage1_geometry(
        str(summary["two_stage"].get("report_path") or "")
    )
    locate_payload = {
        "goal": "learn all visible controls",
        "task": "click_target",
        "app_name": case.case_id,
        "state_hint": state_hint,
        "provider_mode": "local_grounding",
        "agent_mode": "learn",
        "learn_depth": "deep",
        "metadata": build_learn_calibration_metadata(str(summary["two_stage"].get("report_path") or "")),
        "capture_live": False,
        "image_path": str(source_image),
        "observe_trace_path": str(trace_path),
        "dry_run": True,
        "trace": True,
        "write_policy": {"path_graph": False, "element_memory": False, "trace": True},
    }
    locate = _post_json(client, "/vision/locate_target", locate_payload)
    locate_result = ((locate.get("data") or {}).get("result")) if isinstance(locate.get("data"), dict) else {}
    locate_result = locate_result if isinstance(locate_result, dict) else {}
    learn_targets = locate_result.get("learn_all_targets") if isinstance(locate_result.get("learn_all_targets"), dict) else {}
    calibration_overlay = learn_targets.get("overlay") if isinstance(learn_targets.get("overlay"), dict) else {}
    summary["deep_calibration"] = {
        "success": bool(locate.get("success")),
        "location_status": locate_result.get("location_status"),
        "target_count": learn_targets.get("target_count"),
        "calibration_target_count": learn_targets.get("calibration_target_count"),
        "review_box_count": learn_targets.get("review_box_count"),
        "raw_candidate_count": learn_targets.get("raw_candidate_count"),
        "validated_count": learn_targets.get("validated_count"),
        "invalid_count": learn_targets.get("invalid_count"),
        "overlay_path": learn_targets.get("overlay_path") or locate_result.get("coordinate_overlay_path"),
        "final_fusion_overlay": calibration_overlay.get("final_fusion_overlay") is True,
        "base_visual_source": calibration_overlay.get("base_visual_source"),
        "base_overlay_path": calibration_overlay.get("base_overlay_path"),
        "calibration_label_mode": calibration_overlay.get("calibration_label_mode"),
        "model_review_status": (locate_result.get("learn_locate_model_review") or {}).get("status")
        if isinstance(locate_result.get("learn_locate_model_review"), dict)
        else "",
        "model_review_reason": (locate_result.get("learn_locate_model_review") or {}).get("reason")
        if isinstance(locate_result.get("learn_locate_model_review"), dict)
        else "",
        "vista_validation_status": (learn_targets.get("vista_coordinate_validation") or {}).get("status")
        if isinstance(learn_targets.get("vista_coordinate_validation"), dict)
        else "",
        "vista_validated_count": (learn_targets.get("vista_coordinate_validation") or {}).get("validated_count")
        if isinstance(learn_targets.get("vista_coordinate_validation"), dict)
        else 0,
        "vista_inside_count": (learn_targets.get("vista_coordinate_validation") or {}).get("inside_count")
        if isinstance(learn_targets.get("vista_coordinate_validation"), dict)
        else 0,
        "vista_outside_count": (learn_targets.get("vista_coordinate_validation") or {}).get("outside_count")
        if isinstance(learn_targets.get("vista_coordinate_validation"), dict)
        else 0,
        "vista_needs_review_count": (learn_targets.get("vista_coordinate_validation") or {}).get("needs_review_count")
        if isinstance(learn_targets.get("vista_coordinate_validation"), dict)
        else 0,
        "vista_precise_review_pass_count": (learn_targets.get("vista_coordinate_validation") or {}).get(
            "precise_review_pass_count"
        )
        if isinstance(learn_targets.get("vista_coordinate_validation"), dict)
        else 0,
        "trace_path": locate_result.get("trace_path"),
    }
    summary["three_image_audit"] = build_post_calibration_three_image_audit(
        source_path=str(source_image),
        stage1_path=str(summary["two_stage"].get("stage1_overlay_path") or ""),
        stage2_path=str(summary["two_stage"].get("overlay_path") or ""),
        deep_calibration=summary["deep_calibration"],
    )

    observation_evidence = _observation_evidence(
        observe_result=observe_result,
        image_path=str(source_image),
        locate_result=locate_result,
        learn_targets=learn_targets,
    )
    trial = _post_json(
        client,
        "/panel/run_learning_recognition_trial",
        {
            "app_name": case.case_id,
            "state_hint": state_hint,
            "summary": f"protected chain smoke: learn {case.case_id} interface",
            "observation_evidence": observation_evidence,
            "two_stage_report_path": summary["two_stage"].get("report_path"),
        },
    )
    trial_data = trial.get("data") if isinstance(trial.get("data"), dict) else {}
    trial_summary = trial_data.get("summary") if isinstance(trial_data.get("summary"), dict) else {}
    summary["trial"] = {
        "success": bool(trial.get("success")),
        "trial_path": trial_data.get("trial_path"),
        "status": trial_data.get("status"),
        "screen_inventory_count": trial_summary.get("screen_inventory_count"),
        "two_stage_review_region_count": trial_summary.get("two_stage_review_region_count"),
        "two_stage_report_attached": trial_summary.get("two_stage_report_attached"),
        "two_stage_stage1_gate_status": trial_summary.get("two_stage_stage1_gate_status"),
        "two_stage_stage2_numbering_skipped": trial_summary.get("two_stage_stage2_numbering_skipped"),
        "two_stage_review_box_count": trial_summary.get("two_stage_review_box_count"),
        "accepted_for_grounding_count": trial_summary.get("accepted_for_grounding_count"),
        "grounding_validation_count": trial_summary.get("grounding_validation_count"),
        "draft_section_counts": trial_summary.get("draft_section_counts"),
        "precise_understanding_status": trial_summary.get("precise_understanding_status"),
    }

    trial_path = summary["trial"].get("trial_path")
    if trial_path:
        page = _post_json(client, "/panel/create_page_detail_candidate", {"source_path": trial_path})
    else:
        page = {"success": False, "data": {}}
    page_data = page.get("data") if isinstance(page.get("data"), dict) else {}
    page_summary = page_data.get("summary") if isinstance(page_data.get("summary"), dict) else {}
    summary["page_detail"] = {
        "success": bool(page.get("success")),
        "report_path": page_data.get("report_path"),
        "preview_path": page_data.get("preview_path"),
        "region_count": page_summary.get("region_count"),
        "section_count": page_summary.get("section_count"),
    }

    scaffold_source = summary["page_detail"].get("report_path") or trial_path
    if scaffold_source:
        scaffold = _post_json(client, "/panel/create_learning_demo_scaffold", {"source_path": scaffold_source})
    else:
        scaffold = {"success": False, "data": {}}
    scaffold_data = scaffold.get("data") if isinstance(scaffold.get("data"), dict) else {}
    scaffold_summary = scaffold_data.get("summary") if isinstance(scaffold_data.get("summary"), dict) else {}
    summary["scaffold"] = {
        "success": bool(scaffold.get("success")),
        "report_path": scaffold_data.get("report_path"),
        "readiness_status": scaffold_summary.get("readiness_status"),
        "page_detail_readonly_pathgraph_preview_status": scaffold_summary.get(
            "page_detail_readonly_pathgraph_preview_status"
        ),
    }
    summary["quality"] = classify_case_quality(summary)
    chain_completion = classify_chain_completion(summary)
    summary["chain_success"] = chain_completion["success"]
    summary["chain_transport_success"] = chain_completion["transport_success"]
    summary["chain_completion"] = chain_completion
    case_out = out_dir / case.case_id / "learning_interface_chain_smoke.json"
    case_out.parent.mkdir(parents=True, exist_ok=True)
    case_out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary["case_report_path"] = str(case_out)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run protected Learning Interface chain smoke for current recursive surfaces.")
    parser.add_argument(
        "--manifest",
        action="append",
        default=[],
        help="Checksum-validated interface manifest; repeat to combine protected and holdout cases.",
    )
    parser.add_argument(
        "--regression-root",
        default="",
        help="Legacy regression root containing applemusic/qq/python_org replay reports; overrides --manifest.",
    )
    parser.add_argument(
        "--case-id",
        action="append",
        default=[],
        help="Run only this case id; repeat the option to select more than one case.",
    )
    parser.add_argument(
        "--resume-report",
        action="append",
        default=[],
        help="Prior batch or aggregate report whose completed cases must be skipped; repeat as needed.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=0,
        help="Cases in this resumable batch; 0 uses the GPU resource recommendation.",
    )
    parser.add_argument(
        "--batch-index",
        type=int,
        default=0,
        help="Zero-based resumable batch index.",
    )
    parser.add_argument("--out", required=True, help="Output directory for reports and contact sheet.")
    parser.add_argument("--json", action="store_true", help="Print JSON summary.")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_values = list(args.manifest or []) or ["artifacts/benchmarks/interface_class_recursive_manifest_v1.json"]
    manifest_paths = [str(_resolve_project_path(Path(value))) for value in manifest_values]
    all_cases = (
        build_protected_cases(Path(args.regression_root))
        if str(args.regression_root or "").strip()
        else build_manifest_suite_cases([Path(value) for value in manifest_values])
    )
    resume_report_paths = [str(_resolve_project_path(Path(value))) for value in args.resume_report or []]
    completed_case_ids = load_resume_completed_case_ids(
        [Path(value) for value in resume_report_paths],
        expected_manifest_paths=manifest_paths,
        known_case_ids={case.case_id for case in all_cases},
    )
    resource_preflight = build_chain_model_resource_preflight()
    batch_plan = build_acceptance_batch_plan(
        all_cases,
        resource_preflight=resource_preflight,
        requested_case_ids=list(args.case_id or []),
        completed_case_ids=completed_case_ids,
        requested_batch_size=int(args.batch_size) if int(args.batch_size) > 0 else None,
        batch_index=int(args.batch_index),
    )
    if resource_preflight.get("model_launch_allowed") is not True:
        report = build_resource_blocked_report(
            batch_plan=batch_plan,
            resource_preflight=resource_preflight,
            out_dir=out_dir,
            manifest_paths=manifest_paths,
            resume_report_paths=resume_report_paths,
        )
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(f"status={report['status']}")
            print(f"report_path={report['report_path']}")
        return 2

    selected_ids = set(batch_plan["selected_case_ids"])
    cases = [case for case in all_cases if case.case_id in selected_ids]
    model_lifecycle = ensure_acceptance_model_stage("locate")
    client = TestClient(app)
    case_results = [run_case(client, case, out_dir) for case in cases]
    contact_sheet = create_contact_sheet(case_results, out_dir / "learning_interface_chain_contact_sheet.png")
    class_expectation_summary = summarize_class_expectation_audits(case_results)
    report = {
        "contract_version": "learning_interface_chain_smoke_report_v2",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "status": "completed_batch",
        "case_count": len(case_results),
        "completed_case_ids": [item.get("case_id") for item in case_results],
        "pending_case_ids": list(batch_plan.get("pending_case_ids") or []),
        "manifest_paths": manifest_paths,
        "resume_report_paths": resume_report_paths,
        "batch_plan": batch_plan,
        "resource_preflight": resource_preflight,
        "model_lifecycle": model_lifecycle,
        "three_image_audit_complete_count": sum(
            1 for item in case_results if (item.get("three_image_audit") or {}).get("complete") is True
        ),
        "chain_success_count": sum(1 for item in case_results if item.get("chain_success")),
        "review_only_chain_ready_count": sum(
            1 for item in case_results if (item.get("quality") or {}).get("status") == "review_only_chain_ready"
        ),
        "stress_only_needs_review_count": sum(
            1 for item in case_results if (item.get("quality") or {}).get("status") == "stress_only_needs_review"
        ),
        "class_expectation_summary": class_expectation_summary,
        "class_expectation_passed_count": class_expectation_summary["passed"],
        "class_expectation_needs_review_count": class_expectation_summary["needs_review"],
        "class_expectation_not_covered_count": class_expectation_summary["not_covered"],
        "runtime_pathgraph_ready_count": 0,
        "safety": _safety_boundary(),
        "contact_sheet_path": str(contact_sheet),
        "cases": case_results,
        "interpretation": "Protected recursive-interface display/review chain smoke; not recognition accuracy or Execute readiness.",
    }
    report_path = out_dir / "learning_interface_chain_smoke_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"report_path={report_path}")
        print(f"contact_sheet_path={contact_sheet}")
    return 0


def create_contact_sheet(case_results: list[dict[str, Any]], out_path: Path) -> Path:
    thumbs: list[tuple[str, Image.Image]] = []
    for result in case_results:
        for label, path in [
            ("source", (result.get("three_image_audit") or {}).get("source", {}).get("path")),
            (
                "stage1-bar-localization",
                (result.get("three_image_audit") or {}).get("stage1_bar_localization", {}).get("path"),
            ),
            (
                "final-fused-overlay",
                (result.get("three_image_audit") or {}).get("final_fused_overlay", {}).get("path"),
            ),
        ]:
            image_path = _resolve_path(path)
            if image_path and image_path.exists():
                with Image.open(image_path) as image:
                    thumb = image.convert("RGB")
                    thumb.thumbnail((520, 360))
                    canvas = Image.new("RGB", (540, 405), "white")
                    canvas.paste(thumb, ((540 - thumb.width) // 2, 34))
                    draw = ImageDraw.Draw(canvas)
                    draw.text((10, 10), f"{result.get('case_id')} · {label}", fill=(0, 0, 0), font=_font())
                    thumbs.append((f"{result.get('case_id')} {label}", canvas))
    if not thumbs:
        raise ValueError("no overlay images available for contact sheet")
    cols = 2
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 540, rows * 405), (245, 247, 250))
    for index, (_label, thumb) in enumerate(thumbs):
        x = (index % cols) * 540
        y = (index // cols) * 405
        sheet.paste(thumb, (x, y))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    return out_path


def _font() -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("arial.ttf", 16)
    except Exception:
        return ImageFont.load_default()


def _trace_result(trace: dict[str, Any]) -> dict[str, Any]:
    if isinstance(trace.get("result"), dict):
        return trace["result"]
    data = trace.get("data") if isinstance(trace.get("data"), dict) else {}
    if isinstance(data.get("result"), dict):
        return data["result"]
    return trace


def _observation_evidence(
    *,
    observe_result: dict[str, Any],
    image_path: str,
    locate_result: dict[str, Any],
    learn_targets: dict[str, Any],
) -> dict[str, Any]:
    screen_reading = observe_result.get("screen_reading") if isinstance(observe_result.get("screen_reading"), dict) else {}
    targets = learn_targets.get("targets") if isinstance(learn_targets.get("targets"), list) else []
    calibration_targets = (
        learn_targets.get("calibration_targets")
        if isinstance(learn_targets.get("calibration_targets"), list)
        else []
    )
    calibration_evidence_targets = [*targets, *calibration_targets]
    vista_validation = (
        learn_targets.get("vista_coordinate_validation")
        if isinstance(learn_targets.get("vista_coordinate_validation"), dict)
        else {}
    )
    if int(vista_validation.get("validated_count") or 0) > 0:
        coordinate_calibration_status = "model_validation_completed"
    elif calibration_evidence_targets:
        coordinate_calibration_status = "calibration_candidates_available_model_validation_not_run"
    elif learn_targets.get("review_boxes") or learn_targets.get("overlay_path") or locate_result.get("coordinate_overlay_path"):
        coordinate_calibration_status = "review_overlay_only_model_validation_not_run"
    else:
        coordinate_calibration_status = "not_run"
    return {
        "contract_version": "panel_learning_draft_observation_evidence_v1",
        "evidence_source": "protected_recursive_interface_chain_smoke",
        "current_image_path": image_path,
        "screen_size": observe_result.get("screen_size")
        or observe_result.get("viewport_size")
        or observe_result.get("image_size")
        or {},
        "screen_summary": observe_result.get("screen_summary")
        or screen_reading.get("screen_summary")
        or "protected learning interface chain smoke",
        "screen_map": observe_result.get("screen_map") if isinstance(observe_result.get("screen_map"), dict) else {},
        "coordinate_overlay_path": learn_targets.get("overlay_path") or locate_result.get("coordinate_overlay_path") or "",
        "learn_all_targets_summary": {
            "status": learn_targets.get("status"),
            "target_count": learn_targets.get("target_count") or 0,
            "calibration_target_count": learn_targets.get("calibration_target_count") or len(calibration_targets),
            "validated_count": learn_targets.get("validated_count") or 0,
            "invalid_count": learn_targets.get("invalid_count") or 0,
            "review_box_count": learn_targets.get("review_box_count") or 0,
            "vista_validated_count": vista_validation.get("validated_count") or 0,
            "vista_inside_count": vista_validation.get("inside_count") or 0,
            "vista_outside_count": vista_validation.get("outside_count") or 0,
            "vista_needs_review_count": vista_validation.get("needs_review_count") or 0,
            "coordinate_calibration_status": coordinate_calibration_status,
        },
        "calibrated_targets": calibration_evidence_targets[:120],
        "review_boxes": (learn_targets.get("review_boxes") if isinstance(learn_targets.get("review_boxes"), list) else [])[:160],
        "path_map_review_summary": (locate_result.get("path_map_review") or {}).get("summary")
        if isinstance(locate_result.get("path_map_review"), dict)
        else {},
        "no_click_authorization": True,
        "execute_binding_enabled": False,
    }


def _post_json(client: TestClient, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = client.post(path, json=payload)
    try:
        body = response.json()
    except Exception:
        body = {"success": False, "message": response.text}
    body["http_status_code"] = response.status_code
    return body


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _resolve_path(path: Any) -> Path | None:
    path_text = str(path or "").strip()
    if not path_text:
        return None
    candidate = Path(path_text)
    if candidate.exists():
        return candidate
    candidate = ROOT / path_text
    if candidate.exists():
        return candidate
    return None


def _two_stage_review_box_count(two_stage_data: dict[str, Any]) -> int:
    fusion = two_stage_data.get("fusion") if isinstance(two_stage_data.get("fusion"), dict) else {}
    boxes = fusion.get("fused_review_boxes") if isinstance(fusion.get("fused_review_boxes"), list) else []
    if boxes:
        return len(boxes)
    fusion_status = two_stage_data.get("fusion_status") if isinstance(two_stage_data.get("fusion_status"), dict) else {}
    fusion_summary = fusion_status.get("summary") if isinstance(fusion_status.get("summary"), dict) else {}
    status_count = int(fusion_status.get("review_box_count") or fusion_summary.get("fused_review_box_count") or 0)
    if status_count:
        return status_count
    report_path = _resolve_path(two_stage_data.get("report_path"))
    if report_path and report_path.exists():
        try:
            report = _read_json(report_path)
        except Exception:
            return 0
        report_fusion = report.get("fusion") if isinstance(report.get("fusion"), dict) else {}
        report_boxes = (
            report_fusion.get("fused_review_boxes")
            if isinstance(report_fusion.get("fused_review_boxes"), list)
            else []
        )
        if report_boxes:
            return len(report_boxes)
        report_status = report.get("fusion_status") if isinstance(report.get("fusion_status"), dict) else {}
        report_summary = report_status.get("summary") if isinstance(report_status.get("summary"), dict) else {}
        return int(report_status.get("review_box_count") or report_summary.get("fused_review_box_count") or 0)
    return 0


def _two_stage_stage1_overlay_path(
    two_stage_data: dict[str, Any],
    *,
    project_root: Path = ROOT,
) -> str:
    """从同一次两阶段报告读取 Stage1 图，禁止借用历史或猜测文件名。"""
    direct = two_stage_data.get("stage1_region_localization")
    if isinstance(direct, dict) and str(direct.get("overlay_path") or "").strip():
        raw_path = str(direct.get("overlay_path") or "").strip()
    else:
        fusion = two_stage_data.get("fusion") if isinstance(two_stage_data.get("fusion"), dict) else {}
        raw_path = str(fusion.get("stage1_structure_overlay_path") or "").strip()
    if not raw_path:
        report_value = str(two_stage_data.get("report_path") or "").strip()
        report_path = Path(report_value) if report_value else None
        if report_path is not None and not report_path.is_absolute():
            report_path = project_root / report_path
        if report_path is None or not report_path.exists():
            return ""
        try:
            report = _read_json(report_path)
        except (OSError, ValueError, json.JSONDecodeError):
            return ""
        stage1 = report.get("stage1_region_localization")
        if isinstance(stage1, dict):
            raw_path = str(stage1.get("overlay_path") or "").strip()
        if not raw_path:
            report_fusion = report.get("fusion") if isinstance(report.get("fusion"), dict) else {}
            raw_path = str(report_fusion.get("stage1_structure_overlay_path") or "").strip()
    if not raw_path:
        return ""
    resolved = Path(raw_path)
    if not resolved.is_absolute():
        resolved = project_root / resolved
    return str(resolved.resolve()) if resolved.exists() else ""


def _safety_boundary() -> dict[str, Any]:
    return {
        "live_clicks": 0,
        "live_fills": 0,
        "live_submits": 0,
        "execute_binding_enabled": False,
        "runtime_pathgraph_promotion": False,
    }


if __name__ == "__main__":
    raise SystemExit(main())
