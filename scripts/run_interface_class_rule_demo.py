from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_CONTRACT = "interface_class_rule_demo_manifest_v1"
REPORT_CONTRACT = "interface_class_rule_demo_report_v1"
AGENT_EVIDENCE_CONTRACT = "interface_class_rule_agent_evidence_v1"

ReplayRunner = Callable[[dict[str, Any], Path], dict[str, Any]]


def run_interface_class_rule_demo(
    *,
    manifest_path: str | Path,
    out_dir: str | Path,
    project_root: str | Path | None = None,
    replay_runner: ReplayRunner | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    manifest_file = _resolve(manifest_path, root=root)
    output_dir = _resolve(out_dir, root=root)
    manifest = json.loads(manifest_file.read_text(encoding="utf-8-sig"))
    if manifest.get("contract_version") != MANIFEST_CONTRACT:
        raise ValueError("unsupported interface class rule demo manifest")

    class_rule_id = str(manifest.get("class_rule_id") or "").strip()
    if not class_rule_id:
        raise ValueError("interface class rule demo manifest requires class_rule_id")

    output_dir.mkdir(parents=True, exist_ok=True)
    runner = replay_runner or _subprocess_replay_runner(root=root)
    valid_cases: list[dict[str, Any]] = []
    invalid_cases: list[dict[str, Any]] = []

    raw_cases = manifest.get("cases") if isinstance(manifest.get("cases"), list) else []
    for index, raw_case in enumerate(raw_cases):
        if not isinstance(raw_case, dict):
            continue
        case = dict(raw_case)
        case_id = str(case.get("case_id") or f"case_{index + 1}").strip()
        trace_path = _resolve(case.get("trace_path"), root=root)
        screenshot_path = _resolve(case.get("screenshot_path"), root=root)
        fixture_error = _fixture_error(
            case_id=case_id,
            case=case,
            trace_path=trace_path,
            screenshot_path=screenshot_path,
            root=root,
        )
        if fixture_error:
            invalid_cases.append(fixture_error)
            continue

        case_output_dir = output_dir / case_id
        case_output_dir.mkdir(parents=True, exist_ok=True)
        replay_input = {
            **case,
            "case_id": case_id,
            "trace_path": str(trace_path),
            "screenshot_path": str(screenshot_path),
        }
        replay_report = runner(replay_input, case_output_dir)
        expected = case.get("expected") if isinstance(case.get("expected"), dict) else {}
        actual = _actual_case_result(replay_report)
        checks = {
            "interface_category": (
                actual["interface_category"] == str(expected.get("interface_category") or "")
            ),
            "primary_content_strategy": (
                actual["primary_content_strategy"]
                == str(expected.get("primary_content_strategy") or "")
            ),
            "root_roles": (
                actual["root_roles"] == _text_list(expected.get("root_roles"))
            ),
            "stage1_gate_status": (
                actual["stage1_gate_status"]
                == str(expected.get("stage1_gate_status") or "")
            ),
        }
        agent_evidence = _build_agent_evidence(
            class_rule_id=class_rule_id,
            case=case,
            actual=actual,
            replay_report=replay_report,
            root=root,
        )
        agent_evidence_path = case_output_dir / "agent_evidence.json"
        agent_evidence_path.write_text(
            json.dumps(agent_evidence, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        routing_passed = checks["interface_category"] and checks["primary_content_strategy"]
        structure_passed = checks["root_roles"] and checks["stage1_gate_status"]
        agent_evidence_passed = _agent_evidence_is_valid(agent_evidence)
        peer_card_inventory = agent_evidence["decision_support"]["peer_card_inventory"]
        peer_card_inventory_summary = {
            "status": str(peer_card_inventory.get("status") or "not_covered"),
            "peer_item_family": str(
                peer_card_inventory.get("peer_item_family") or ""
            ),
            "item_count": int(peer_card_inventory.get("item_count") or 0),
            "readable_item_count": int(
                peer_card_inventory.get("readable_item_count") or 0
            ),
            "review_candidate_count": int(
                peer_card_inventory.get("review_candidate_count") or 0
            ),
        }
        valid_cases.append(
            {
                "case_id": case_id,
                "case_role": str(case.get("case_role") or "unspecified"),
                "source_type": str(case.get("source_type") or "recorded_model_output"),
                "checks": checks,
                "routing_passed": routing_passed,
                "structure_passed": structure_passed,
                "agent_evidence_passed": agent_evidence_passed,
                "peer_card_inventory": peer_card_inventory_summary,
                "passed": routing_passed and structure_passed and agent_evidence_passed,
                "expected": expected,
                "actual": actual,
                "trace_path": _relative_or_absolute(trace_path, root=root),
                "screenshot_path": _relative_or_absolute(screenshot_path, root=root),
                "overlay_path": actual["overlay_path"],
                "replay_report_path": _relative_or_absolute(
                    Path(str(replay_report.get("_report_path") or "")),
                    root=root,
                ),
                "agent_evidence_path": _relative_or_absolute(
                    agent_evidence_path,
                    root=root,
                ),
            }
        )

    routing_metric = _metric(
        valid_cases,
        "routing_passed",
        "recorded-output class-rule routing checks; not model accuracy",
    )
    structure_metric = _metric(
        valid_cases,
        "structure_passed",
        "offline Stage1 root-structure checks; not bbox or live GUI reliability",
    )
    evidence_metric = _metric(
        valid_cases,
        "agent_evidence_passed",
        "read-only Agent evidence contract checks; not execution success",
    )
    positive_count = sum(
        1 for case in valid_cases if case.get("case_role") == "positive"
    )
    non_positive_count = len(valid_cases) - positive_count
    all_passed = bool(valid_cases) and all(case["passed"] for case in valid_cases)
    demo_ready = all_passed and positive_count >= 1 and non_positive_count >= 1
    peer_card_inventory_summary = {
        "cases_with_current_inventory": sum(
            case["peer_card_inventory"]["status"] == "current_peer_items_projected"
            for case in valid_cases
        ),
        "attempted_cases": len(valid_cases),
        "readable_item_total": sum(
            case["peer_card_inventory"]["readable_item_count"]
            for case in valid_cases
        ),
        "review_candidate_total": sum(
            case["peer_card_inventory"]["review_candidate_count"]
            for case in valid_cases
        ),
        "interpretation": (
            "current-screen Agent inventory counts only; not recognition accuracy "
            "or execution reliability"
        ),
    }

    report = {
        "contract_version": REPORT_CONTRACT,
        "manifest_path": _relative_or_absolute(manifest_file, root=root),
        "class_rule_id": class_rule_id,
        "case_count": len(raw_cases),
        "valid_case_count": len(valid_cases),
        "invalid_case_count": len(invalid_cases),
        "demo_readiness": (
            "ready_for_offline_read_only_demo" if demo_ready else "not_ready"
        ),
        "demo_scope": {
            "positive_cases": positive_count,
            "near_negative_or_negative_cases": non_positive_count,
            "model_calls_in_this_run": 0,
            "source": "checksum-validated recorded model output plus deterministic replay",
        },
        "class_rule_routing": routing_metric,
        "stage1_structure_contract": structure_metric,
        "agent_evidence_contract": evidence_metric,
        "peer_card_inventory_summary": peer_card_inventory_summary,
        "model_ability_denominator": {
            "attempted": 0,
            "rate": "not_covered",
            "interpretation": (
                "this replay does not call a model and cannot establish model classification reliability"
            ),
        },
        "cases": valid_cases,
        "failure_cases": [case for case in valid_cases if not case["passed"]],
        "invalid_cases": invalid_cases,
        "safety": {
            "live_clicks": 0,
            "live_fills": 0,
            "live_submits": 0,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        },
        "interpretation": (
            "offline class-rule demo only; validates fixed evidence routing, root structure, "
            "and Agent-readable evidence without measuring model accuracy or live GUI reliability"
        ),
    }
    report_path = output_dir / "interface_class_rule_demo_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report["report_path"] = _relative_or_absolute(report_path, root=root)
    index_path = output_dir / "DEMO.md"
    index_path.write_text(_demo_markdown(report, root=root), encoding="utf-8")
    report["demo_index_path"] = _relative_or_absolute(index_path, root=root)
    return report


def _subprocess_replay_runner(*, root: Path) -> ReplayRunner:
    replay_script = root / "scripts" / "run_learn_two_stage_replay.py"

    def run(case: dict[str, Any], case_out_dir: Path) -> dict[str, Any]:
        command = [
            sys.executable,
            str(replay_script),
            "--trace",
            str(case["trace_path"]),
            "--source-image",
            str(case["screenshot_path"]),
            "--out",
            str(case_out_dir),
            "--require-stage1-gate",
        ]
        completed = subprocess.run(
            command,
            cwd=root,
            text=True,
            capture_output=True,
            encoding="utf-8",
            timeout=180,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise RuntimeError(
                f"class rule replay failed for {case['case_id']}: {detail}"
            )
        report_paths = sorted(
            case_out_dir.glob("learn_two_stage_replay_report_*.json"),
            key=lambda path: path.stat().st_mtime_ns,
        )
        if not report_paths:
            raise RuntimeError(
                f"class rule replay did not produce a report for {case['case_id']}"
            )
        report_path = report_paths[-1]
        report = json.loads(report_path.read_text(encoding="utf-8-sig"))
        report["_report_path"] = str(report_path)
        return report

    return run


def _actual_case_result(report: dict[str, Any]) -> dict[str, Any]:
    classification = (
        report.get("interface_classification")
        if isinstance(report.get("interface_classification"), dict)
        else {}
    )
    profile = (
        report.get("class_rule_profile")
        if isinstance(report.get("class_rule_profile"), dict)
        else classification.get("class_rule_profile")
        if isinstance(classification.get("class_rule_profile"), dict)
        else {}
    )
    localization = (
        report.get("stage1_region_localization")
        if isinstance(report.get("stage1_region_localization"), dict)
        else {}
    )
    regions = localization.get("regions") if isinstance(localization.get("regions"), list) else []
    root_roles = [
        str(region.get("role") or "")
        for region in regions
        if isinstance(region, dict) and str(region.get("role") or "")
    ]
    gate = report.get("stage1_gate") if isinstance(report.get("stage1_gate"), dict) else {}
    overlay = (
        report.get("overlay_status")
        if isinstance(report.get("overlay_status"), dict)
        else {}
    )
    diagnostics = (
        report.get("stage1_structure")
        if isinstance(report.get("stage1_structure"), dict)
        else {}
    )
    diagnostics = (
        diagnostics.get("diagnostics")
        if isinstance(diagnostics.get("diagnostics"), dict)
        else {}
    )
    root_selection = (
        diagnostics.get("root_selection")
        if isinstance(diagnostics.get("root_selection"), dict)
        else {}
    )
    return {
        "interface_category": str(classification.get("category") or ""),
        "classification_status": str(classification.get("status") or ""),
        "classification_source": str(classification.get("source") or ""),
        "primary_content_strategy": str(
            profile.get("primary_content_strategy") or ""
        ),
        "class_rule_profile": profile,
        "root_roles": root_roles,
        "stage1_gate_status": str(gate.get("status") or ""),
        "overlay_path": str(overlay.get("path") or ""),
        "edge_partition_suppressed_without_navigation_evidence": bool(
            root_selection.get(
                "class_rule_edge_partition_suppressed_without_navigation_evidence"
            )
        ),
    }


def _build_agent_evidence(
    *,
    class_rule_id: str,
    case: dict[str, Any],
    actual: dict[str, Any],
    replay_report: dict[str, Any],
    root: Path,
) -> dict[str, Any]:
    localization = (
        replay_report.get("stage1_region_localization")
        if isinstance(replay_report.get("stage1_region_localization"), dict)
        else {}
    )
    regions = localization.get("regions") if isinstance(localization.get("regions"), list) else []
    semantic_regions = [
        {
            "region_id": str(region.get("region_id") or ""),
            "role": str(region.get("role") or ""),
            "label": str(region.get("label") or region.get("role") or ""),
            "purpose": _region_purpose(str(region.get("role") or "")),
        }
        for region in regions
        if isinstance(region, dict) and str(region.get("role") or "")
    ]
    category = actual["interface_category"]
    strategy = actual["primary_content_strategy"]
    stage2 = (
        replay_report.get("stage2_numbering")
        if isinstance(replay_report.get("stage2_numbering"), dict)
        else {}
    )
    enhancement = (
        stage2.get("layout_review_enhancement")
        if isinstance(stage2.get("layout_review_enhancement"), dict)
        else {}
    )
    enhancement_report = (
        enhancement.get("report")
        if isinstance(enhancement.get("report"), dict)
        else {}
    )
    class_rule_context = (
        enhancement_report.get("class_rule_context")
        if isinstance(enhancement_report.get("class_rule_context"), dict)
        else {}
    )
    peer_card_inventory = _agent_peer_card_inventory(
        stage2.get("agent_peer_card_inventory")
    )
    return {
        "contract_version": AGENT_EVIDENCE_CONTRACT,
        "interface_identity": {
            "case_id": str(case.get("case_id") or ""),
            "surface_class": category,
            "classification_status": actual["classification_status"],
            "classification_source": actual["classification_source"],
        },
        "responsibility": _class_responsibility(category, strategy),
        "class_rule": {
            "class_rule_id": class_rule_id,
            "matched": category == class_rule_id,
            "profile": actual["class_rule_profile"],
        },
        "structural_regions": semantic_regions,
        "decision_support": {
            "primary_content_strategy": strategy,
            "interpretation": _strategy_interpretation(strategy),
            "current_observation_required_before_content_decision": True,
            "layout_review_strategy": {
                "class_prior": str(
                    class_rule_context.get("class_prior") or "not_declared"
                ),
                "peer_item_family": str(
                    class_rule_context.get("peer_item_family") or ""
                ),
                "activation": str(
                    class_rule_context.get("activation")
                    or "current_visual_repetition_required"
                ),
                "triggered_by_current_visual_evidence": bool(
                    class_rule_context.get("triggered_by_current_visual_evidence")
                ),
                "normalized_existing_candidate_count": int(
                    enhancement_report.get("normalized_existing_card_count") or 0
                ),
                "review_candidate_count": int(
                    enhancement_report.get("neighbor_proposal_count") or 0
                ),
                "interpretation": (
                    "class prior is advisory; only current visual repetition may produce "
                    "review candidates"
                ),
            },
            "peer_card_inventory": peer_card_inventory,
        },
        "available_actions": [],
        "blockers": [],
        "readiness": {
            "status": "review_evidence_only",
            "agent_can_use_for_structure_reasoning": bool(category and strategy),
            "human_review_required_before_promotion": True,
        },
        "evidence_refs": {
            "source_screenshot_path": _relative_or_absolute(
                _resolve(case.get("screenshot_path"), root=root),
                root=root,
            ),
            "source_trace_path": _relative_or_absolute(
                _resolve(case.get("trace_path"), root=root),
                root=root,
            ),
            "fused_overlay_path": actual["overlay_path"],
        },
        "execution_contract": {
            "observe_before_decision": True,
            "current_capture_required": True,
            "current_target_resolution_required": True,
            "historical_coordinates_forbidden": True,
            "gate_required": True,
            "operation_required": True,
            "trace_required": True,
            "post_action_verification_required": True,
            "final_submit_forbidden": True,
        },
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def _agent_peer_card_inventory(value: Any) -> dict[str, Any]:
    inventory = value if isinstance(value, dict) else {}
    items = inventory.get("items") if isinstance(inventory.get("items"), list) else []
    safe_items = []
    for item in items:
        if not isinstance(item, dict):
            continue
        capabilities = (
            item.get("capabilities")
            if isinstance(item.get("capabilities"), dict)
            else {}
        )
        safe_items.append(
            {
                "candidate_id": str(item.get("candidate_id") or ""),
                "semantic_name": str(item.get("semantic_name") or ""),
                "content_summary": [
                    str(entry)
                    for entry in item.get("content_summary") or []
                    if str(entry).strip()
                ],
                "source_kind": str(item.get("source_kind") or ""),
                "candidate_kind": str(item.get("candidate_kind") or "atomic_card"),
                "agent_decision_status": str(
                    item.get("agent_decision_status") or "review_only_candidate"
                ),
                "review_status": str(item.get("review_status") or "needs_human_review"),
                "inferred_neighbor": item.get("inferred_neighbor") is True,
                "capabilities": {
                    "read_current_content": capabilities.get("read_current_content")
                    is True,
                    "open_detail_candidate": capabilities.get("open_detail_candidate")
                    is True,
                    "requires_fresh_localization": True,
                    "requires_gate": True,
                },
            }
        )
    readable_item_count = sum(
        item.get("agent_decision_status") == "readable_candidate"
        for item in safe_items
    )
    return {
        "contract_version": "agent_peer_card_inventory_v1",
        "status": str(inventory.get("status") or "not_covered"),
        "peer_item_family": str(inventory.get("peer_item_family") or ""),
        "current_visual_evidence_required": True,
        "item_count": len(safe_items),
        "readable_item_count": readable_item_count,
        "review_candidate_count": len(safe_items) - readable_item_count,
        "items": safe_items,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def _agent_evidence_is_valid(evidence: dict[str, Any]) -> bool:
    serialized = json.dumps(evidence, ensure_ascii=False)
    return bool(
        evidence.get("contract_version") == AGENT_EVIDENCE_CONTRACT
        and evidence.get("responsibility")
        and isinstance(evidence.get("structural_regions"), list)
        and evidence.get("decision_support", {}).get("primary_content_strategy")
        and evidence.get("execution_contract", {}).get("historical_coordinates_forbidden")
        and evidence.get("artifact_is_authorization") is False
        and evidence.get("execute_binding_enabled") is False
        and '"bbox"' not in serialized
        and '"click_point"' not in serialized
    )


def _fixture_error(
    *,
    case_id: str,
    case: dict[str, Any],
    trace_path: Path,
    screenshot_path: Path,
    root: Path,
) -> dict[str, Any] | None:
    for kind, path in (("trace", trace_path), ("screenshot", screenshot_path)):
        if not path.is_file():
            return {
                "case_id": case_id,
                "failure_category": "missing_fixture",
                "fixture_kind": kind,
                "path": _relative_or_absolute(path, root=root),
            }
        expected = str(case.get(f"{kind}_sha256") or "").strip().casefold()
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if not expected or expected != actual:
            return {
                "case_id": case_id,
                "failure_category": "stale_fixture",
                "fixture_kind": kind,
                "expected_sha256": expected,
                "actual_sha256": actual,
                "path": _relative_or_absolute(path, root=root),
            }
    return None


def _metric(
    cases: list[dict[str, Any]],
    field: str,
    interpretation: str,
) -> dict[str, Any]:
    attempted = len(cases)
    passed = sum(1 for case in cases if case.get(field) is True)
    return {
        "passed": passed,
        "attempted": attempted,
        "rate": round(passed / attempted, 4) if attempted else "not_covered",
        "interpretation": interpretation,
    }


def _class_responsibility(category: str, strategy: str) -> str:
    if strategy == "independent_content_modules":
        return (
            "Recognize a portal composed of independent peer modules; reason about each "
            "module separately and re-observe current module content before acting."
        )
    if strategy == "feed_items":
        return (
            "Recognize a sequential information feed; treat repeated items as current "
            "content and re-observe before choosing an item."
        )
    if strategy == "search_results":
        return (
            "Recognize a search-results workspace; use the current query and result "
            "items as live evidence before selecting a result."
        )
    return f"Recognize the current {category or 'unknown'} interface structure."


def _strategy_interpretation(strategy: str) -> str:
    return {
        "independent_content_modules": (
            "Peer modules are separate content containers, not one sequential feed."
        ),
        "feed_items": "Repeated content is ordered as a feed.",
        "search_results": "Repeated content is tied to the current search query.",
    }.get(strategy, "Use the current observation to interpret this interface.")


def _region_purpose(role: str) -> str:
    return {
        "top_bar": "Host or page-level navigation and controls.",
        "left_nav": "Side navigation only when current semantic evidence confirms it.",
        "right_panel": "Secondary information or controls.",
        "main_content": "Primary content viewport governed by the selected class rule.",
        "bottom_status": "Status or composer area at the bottom edge.",
    }.get(role, "Structural region from the current observation.")


def _demo_markdown(report: dict[str, Any], *, root: Path) -> str:
    lines = [
        "# Interface Class Rule Demo",
        "",
        f"- Class rule: `{report['class_rule_id']}`",
        f"- Readiness: `{report['demo_readiness']}`",
        "- Scope: offline recorded-output replay; no model call, click, fill, or submit.",
        "",
        "| Case | Role | Category | Strategy | Roots | Result |",
        "|---|---|---|---|---|---|",
    ]
    for case in report["cases"]:
        actual = case["actual"]
        lines.append(
            "| {case_id} | {role} | {category} | {strategy} | {roots} | {result} |".format(
                case_id=case["case_id"],
                role=case["case_role"],
                category=actual["interface_category"],
                strategy=actual["primary_content_strategy"],
                roots=", ".join(actual["root_roles"]),
                result="pass" if case["passed"] else "fail",
            )
        )
    lines.extend(["", "## Evidence", ""])
    for case in report["cases"]:
        screenshot = _markdown_path(case["screenshot_path"], root=root)
        overlay = _markdown_path(case["overlay_path"], root=root)
        evidence = _markdown_path(case["agent_evidence_path"], root=root)
        lines.extend(
            [
                f"### {case['case_id']}",
                "",
                f"- [Original screenshot]({screenshot})",
                f"- [Fused overlay]({overlay})",
                f"- [Agent-readable evidence]({evidence})",
                "",
            ]
        )
    lines.extend(
        [
            "## Interpretation",
            "",
            report["interpretation"],
            "",
        ]
    )
    return "\n".join(lines)


def _markdown_path(value: str, *, root: Path) -> str:
    path = Path(str(value or ""))
    if not path.is_absolute():
        path = root / path
    return path.resolve().as_posix()


def _resolve(value: Any, *, root: Path) -> Path:
    path = Path(str(value or ""))
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _relative_or_absolute(path: Path, *, root: Path) -> str:
    if not str(path):
        return ""
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(root))
    except ValueError:
        return str(resolved)


def _text_list(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = run_interface_class_rule_demo(
        manifest_path=args.manifest,
        out_dir=args.out,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"report_path={report['report_path']}")
        print(f"demo_index_path={report['demo_index_path']}")
        print(f"demo_readiness={report['demo_readiness']}")


if __name__ == "__main__":
    main()
