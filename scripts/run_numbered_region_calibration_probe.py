from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.models.request import ExecuteRecognitionPlanRequest
from app.api.models.request import OperationRuntimeContextModel
from app.learn.recognition.locator_tasks import LOCATOR_TASK_CARDS_CONTRACT


ExecuteFn = Callable[[ExecuteRecognitionPlanRequest], dict[str, Any]]


def build_seeded_candidate(region: dict[str, Any]) -> dict[str, Any]:
    bbox = _bbox(region.get("rough_bbox_hint") or region.get("bbox") or {})
    point = {"x": bbox["x"] + bbox["w"] // 2, "y": bbox["y"] + bbox["h"] // 2}
    region_no = int(region.get("region_no") or 0)
    item_id = str(region.get("item_id") or region.get("id") or region_no).strip()
    label = _text(region.get("label"), region.get("text"), item_id)
    role = _text(region.get("role"), "button")
    return {
        "contract_version": "seeded_candidate_v1",
        "candidate_id": f"numbered_region_{region_no}_{item_id}",
        "source": "numbered_region_calibration_probe_v1",
        "label": label,
        "role": role,
        "bbox": bbox,
        "click_point": point,
        "score": 0.82,
        "risk_class": "safe_click_allowed",
        "expected_effect": f"calibrate numbered region #{region_no}; dry-run only",
    }


def build_tasks_from_actual_parser_locator_cards(
    actual_parser_output: dict[str, Any],
    *,
    max_regions: int | None = None,
) -> dict[str, Any]:
    cards_payload = actual_parser_output.get("locator_task_cards") if isinstance(actual_parser_output, dict) else {}
    if not isinstance(cards_payload, dict):
        cards_payload = {}
    cards = cards_payload.get("cards") if isinstance(cards_payload.get("cards"), list) else []
    limit = max_regions if isinstance(max_regions, int) and max_regions > 0 else len(cards)
    regions: list[dict[str, Any]] = []
    for index, card in enumerate(cards[:limit], start=1):
        if not isinstance(card, dict):
            continue
        bbox = _bbox(card.get("rough_bbox_hint") if isinstance(card.get("rough_bbox_hint"), dict) else {})
        label = _label_from_locator_card(card, fallback=f"locator card {index}")
        region = {
            "region_no": index,
            "item_id": _text(card.get("source_item_id"), f"locator_card_{index}"),
            "label": label,
            "role": _text(card.get("target_role"), card.get("item_type"), "other"),
            "text": _text(card.get("target_visible_text"), card.get("target_name")),
            "text_lines": [str(item) for item in card.get("text_lines", [])] if isinstance(card.get("text_lines"), list) else [],
            "rough_bbox_hint": bbox,
            "evidence_level": _text(card.get("evidence_level"), "unknown"),
            "source_evidence": card.get("source_evidence") if isinstance(card.get("source_evidence"), list) else [],
            "locator_task_card": card,
            "prompt": _prompt_from_learn_locator_card(card, region_no=index, target_name=label),
        }
        regions.append(region)
    return {
        "contract_version": "numbered_region_calibration_tasks_v1",
        "source_contract": str(actual_parser_output.get("contract_version") or ""),
        "locator_task_cards_contract": str(cards_payload.get("contract_version") or LOCATOR_TASK_CARDS_CONTRACT),
        "prompt_profile": "locator_task_card_execute_calibration_v1",
        "app_name": _text((actual_parser_output.get("model_config") or {}).get("app_name") if isinstance(actual_parser_output.get("model_config"), dict) else "", "SEEK"),
        "screenshot_path": str(actual_parser_output.get("screenshot_path") or ""),
        "regions": regions,
        "interpretation": "Generated from learn_locator_task_cards_v1 for dry-run Execute calibration only; no click authorization.",
    }


def _label_from_locator_card(card: dict[str, Any], *, fallback: str) -> str:
    name = _text(card.get("target_name"), card.get("target_visible_text"), fallback)
    role = _text(card.get("target_role"), card.get("item_type"), "")
    text_lines = [str(item).strip() for item in card.get("text_lines", [])] if isinstance(card.get("text_lines"), list) else []
    first_line = next((item for item in text_lines if item), "")
    if first_line and _needs_visible_text_disambiguation(name=name, role=role):
        if first_line.lower() not in name.lower():
            return f"{name}: {first_line}"
    return name


def _needs_visible_text_disambiguation(*, name: str, role: str) -> bool:
    lowered_name = name.strip().lower()
    lowered_role = role.strip().lower()
    return lowered_role == "card" or lowered_name in {
        "job listing card",
        "job card",
        "listing card",
        "result card",
        "search result",
    }


def _prompt_from_learn_locator_card(card: dict[str, Any], *, region_no: int, target_name: str | None = None) -> str:
    neighbors = card.get("neighbor_context") if isinstance(card.get("neighbor_context"), dict) else {}
    text_lines = [str(item).strip() for item in card.get("text_lines", [])] if isinstance(card.get("text_lines"), list) else []
    return "\n".join(
        [
            f"You are locating exactly one GUI target from learning locator task card #{region_no}.",
            f"Target name: {_text(target_name, card.get('target_name'))}",
            f"Target role: {_text(card.get('target_role'))}",
            f"Target visible text: {_text(card.get('target_visible_text'))}",
            f"Visual description: {_text(card.get('visual_description'))}",
            f"Text lines: {' | '.join(text_lines) if text_lines else 'none'}",
            f"Boundary definition: {_text(card.get('boundary_definition'), 'smallest visible target boundary')}",
            f"Clickable-area hint: {_text(card.get('clickable_area_hint'), card.get('interaction_target'), 'safe interior point')}",
            f"Evidence level: {_text(card.get('evidence_level'), 'unknown')}; source evidence: {card.get('source_evidence') if isinstance(card.get('source_evidence'), list) else []}",
            f"Left neighbor: {neighbors.get('left') or 'none'}",
            f"Right neighbor: {neighbors.get('right') or 'none'}",
            f"Above neighbor: {neighbors.get('above') or 'none'}",
            f"Below neighbor: {neighbors.get('below') or 'none'}",
            "The rough bbox is only a hint and may be wrong. Prefer the visible text lines, boundary definition, and clickable-area hint when choosing the precise point.",
            "Do not click browser toolbar, clear icons, final submit, send, confirm, payment, or surrounding containers.",
            f"Return {_text(card.get('expected_precise_output'), 'tight visible target bbox and safe interior point in full screenshot coordinates')}.",
        ]
    )


def enrich_regions_with_parser_context(tasks: dict[str, Any], parser_output: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(tasks)
    inventory_by_id = _inventory_by_id(parser_output)
    vision_by_id = _vision_regions_by_id(parser_output)
    regions = [dict(item) for item in tasks.get("regions", []) if isinstance(item, dict)]
    enriched_regions: list[dict[str, Any]] = []
    for region in regions:
        item_id = str(region.get("item_id") or region.get("id") or "").strip()
        inventory_item = inventory_by_id.get(item_id, {})
        vision_item = vision_by_id.get(item_id, {})
        card = _locator_task_card(region=region, inventory_item=inventory_item, vision_item=vision_item, all_regions=regions)
        region["locator_task_card"] = card
        region["prompt"] = _locator_prompt_from_card(card)
        enriched_regions.append(region)
    enriched["regions"] = enriched_regions
    enriched["prompt_profile"] = "numbered_region_detailed_locator_v1"
    return enriched


def _inventory_by_id(parser_output: dict[str, Any]) -> dict[str, dict[str, Any]]:
    items = parser_output.get("screen_inventory")
    if not isinstance(items, list):
        items = parser_output.get("raw_screen_inventory") if isinstance(parser_output.get("raw_screen_inventory"), list) else []
    out: dict[str, dict[str, Any]] = {}
    for item in items:
        if isinstance(item, dict) and item.get("item_id"):
            out[str(item["item_id"])] = item
    return out


def _vision_regions_by_id(parser_output: dict[str, Any]) -> dict[str, dict[str, Any]]:
    sources = ((parser_output.get("observe_bundle") or {}).get("sources") or {}) if isinstance(parser_output.get("observe_bundle"), dict) else {}
    vision = sources.get("vision") if isinstance(sources.get("vision"), dict) else {}
    out: dict[str, dict[str, Any]] = {}
    for item in vision.get("regions") or []:
        if isinstance(item, dict) and item.get("region_id"):
            out[str(item["region_id"])] = item
    return out


def _locator_task_card(
    *,
    region: dict[str, Any],
    inventory_item: dict[str, Any],
    vision_item: dict[str, Any],
    all_regions: list[dict[str, Any]],
) -> dict[str, Any]:
    label = _text(region.get("label"), inventory_item.get("label"), vision_item.get("label"))
    role = _text(region.get("role"), inventory_item.get("role"), vision_item.get("role"))
    bbox = _bbox(region.get("rough_bbox_hint") or region.get("bbox") or {})
    visible_text = _text(inventory_item.get("text"), inventory_item.get("label"), vision_item.get("ocr_text"), label)
    description = _text(vision_item.get("description"), inventory_item.get("description"), _role_description(role))
    neighbors = _neighbor_context(region, all_regions)
    metadata = inventory_item.get("metadata") if isinstance(inventory_item.get("metadata"), dict) else {}
    return {
        "contract_version": "numbered_region_locator_task_card_v1",
        "region_no": region.get("region_no"),
        "target_name": label,
        "target_role": role,
        "target_visible_text": visible_text,
        "visual_description": description,
        "text_lines": [str(item) for item in vision_item.get("text_lines") or []],
        "evidence_level": _text(region.get("evidence_level"), inventory_item.get("evidence_level"), "unknown"),
        "source_evidence": inventory_item.get("source_evidence") if isinstance(inventory_item.get("source_evidence"), list) else [],
        "uia_control_type": metadata.get("control_type"),
        "uia_patterns": metadata.get("patterns") if isinstance(metadata.get("patterns"), list) else [],
        "rough_bbox_hint": bbox,
        "rough_bbox_policy": "hint_only_can_be_replaced",
        "interaction_target": _interaction_target(label=label, role=role, visible_text=visible_text),
        "neighbor_context": neighbors,
        "must_not_click": ["browser toolbar", "clear icon", "final submit", "send", "confirm", "payment"],
        "expected_precise_output": "tight visible target bbox and safe interior point in full screenshot coordinates",
    }


def _locator_prompt_from_card(card: dict[str, Any]) -> str:
    neighbors = card.get("neighbor_context") if isinstance(card.get("neighbor_context"), dict) else {}
    neighbor_lines = [
        f"Left neighbor: {neighbors.get('left') or 'none'}",
        f"Right neighbor: {neighbors.get('right') or 'none'}",
        f"Above neighbor: {neighbors.get('above') or 'none'}",
        f"Below neighbor: {neighbors.get('below') or 'none'}",
    ]
    return "\n".join(
        [
            f"You are locating exactly one GUI target inside numbered region #{card.get('region_no')}.",
            f"Target name: {card.get('target_name')}",
            f"Target role: {card.get('target_role')}",
            f"Target visible text: {card.get('target_visible_text')}",
            f"Visual description: {card.get('visual_description')}",
            f"Evidence level: {card.get('evidence_level')}; source evidence: {card.get('source_evidence')}",
            f"UIA control type: {card.get('uia_control_type')}; UIA patterns: {card.get('uia_patterns')}",
            *neighbor_lines,
            f"Interaction target: {card.get('interaction_target')}",
            "The rough bbox is only a hint and may be wrong. You may completely replace it if visual/OCR/UIA evidence says the real control is elsewhere inside the local context.",
            "Do not click browser toolbar, clear icons, final submit, send, confirm, payment, or surrounding containers.",
            f"Return {card.get('expected_precise_output')}.",
        ]
    )


def _neighbor_context(region: dict[str, Any], all_regions: list[dict[str, Any]]) -> dict[str, str | None]:
    bbox = _bbox(region.get("rough_bbox_hint") or region.get("bbox") or {})
    center_x = bbox["x"] + bbox["w"] / 2
    center_y = bbox["y"] + bbox["h"] / 2
    candidates: list[tuple[str, float, str]] = []
    for other in all_regions:
        if other is region or other.get("region_no") == region.get("region_no"):
            continue
        obox = _bbox(other.get("rough_bbox_hint") or other.get("bbox") or {})
        ox = obox["x"] + obox["w"] / 2
        oy = obox["y"] + obox["h"] / 2
        label = f"#{other.get('region_no')} {_text(other.get('label'), other.get('item_id'))}"
        if abs(oy - center_y) <= max(80, bbox["h"] * 1.5):
            if ox < center_x:
                candidates.append(("left", center_x - ox, label))
            elif ox > center_x:
                candidates.append(("right", ox - center_x, label))
        if abs(ox - center_x) <= max(160, bbox["w"] * 0.75):
            if oy < center_y:
                candidates.append(("above", center_y - oy, label))
            elif oy > center_y:
                candidates.append(("below", oy - center_y, label))
    out: dict[str, str | None] = {"left": None, "right": None, "above": None, "below": None}
    for direction in out:
        matches = sorted((item for item in candidates if item[0] == direction), key=lambda item: item[1])
        if matches:
            out[direction] = matches[0][2]
    return out


def _interaction_target(*, label: str, role: str, visible_text: str) -> str:
    role_text = role.casefold()
    if "input" in role_text or "edit" in role_text:
        return f"click inside the input body for {visible_text or label}, not the clear icon or surrounding header"
    if "button" in role_text:
        return f"click the visible button body labeled {visible_text or label}, preferably near the visual center"
    return f"locate the visible target area for {visible_text or label}; avoid nested unrelated controls"


def _role_description(role: str) -> str:
    if "input" in role.casefold():
        return "editable input control"
    if "button" in role.casefold():
        return "clickable button control"
    return "visible page element"


def classify_case_outcome(
    *,
    success: bool,
    pre_click_allowed: bool | None,
    candidate_summary: dict[str, Any],
    error_code: str | None,
    evidence_level: str | None = None,
) -> dict[str, Any]:
    vista_used = bool(candidate_summary.get("vista_point_grounding_used"))
    vista_inside = bool(candidate_summary.get("vista_point_inside_candidate_bbox"))
    seed_fallback = bool(candidate_summary.get("seeded_candidate_primary_point_used"))
    if success and pre_click_allowed is True and str(evidence_level or "").casefold() == "semantic_region_only":
        return {
            "status": "needs_human_review",
            "category": "semantic_region_only_seed_requires_review",
            "promotable_to_learning_draft": False,
        }
    if success and pre_click_allowed is True and vista_used and vista_inside and not seed_fallback:
        return {
            "status": "passed",
            "category": "vista_point_inside_seed_bbox_gate_allowed",
            "promotable_to_learning_draft": True,
        }
    if success and pre_click_allowed is True and vista_used and seed_fallback and not vista_inside:
        return {
            "status": "needs_human_review",
            "category": "model_disagreed_with_seed_fallback_used",
            "promotable_to_learning_draft": False,
        }
    if pre_click_allowed is False or error_code == "pre_click_rejected":
        return {
            "status": "gate_rejected",
            "category": error_code or "pre_click_gate_rejected",
            "promotable_to_learning_draft": False,
        }
    return {
        "status": "failed",
        "category": error_code or "recognition_chain_failed_or_incomplete",
        "promotable_to_learning_draft": False,
    }


def run_numbered_region_calibration_probe(
    *,
    tasks_path: Path | None,
    out_dir: Path,
    region_numbers: Iterable[int],
    execute_fn: ExecuteFn | None = None,
    parser_output_path: Path | None = None,
    enrich_prompts: bool = False,
    write_enriched_tasks: Path | None = None,
    actual_parser_output_path: Path | None = None,
    write_generated_tasks: Path | None = None,
) -> dict[str, Any]:
    if actual_parser_output_path is not None:
        actual_parser_output = json.loads(actual_parser_output_path.read_text(encoding="utf-8"))
        tasks = build_tasks_from_actual_parser_locator_cards(actual_parser_output)
        if write_generated_tasks is not None:
            write_generated_tasks.parent.mkdir(parents=True, exist_ok=True)
            write_generated_tasks.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")
    elif tasks_path is not None:
        tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
    else:
        raise ValueError("either --tasks or --actual-parser-output is required")
    parser_output_used: str | None = None
    enriched_tasks_path: str | None = None
    if enrich_prompts:
        if parser_output_path is None:
            raise ValueError("--enrich-prompts requires --parser-output")
        parser_output = json.loads(parser_output_path.read_text(encoding="utf-8"))
        tasks = enrich_regions_with_parser_context(tasks, parser_output)
        parser_output_used = str(parser_output_path)
        if write_enriched_tasks is not None:
            write_enriched_tasks.parent.mkdir(parents=True, exist_ok=True)
            write_enriched_tasks.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")
            enriched_tasks_path = str(write_enriched_tasks.resolve())
    out_dir.mkdir(parents=True, exist_ok=True)
    wanted = {int(item) for item in region_numbers}
    regions = [item for item in tasks.get("regions", []) if int(item.get("region_no") or 0) in wanted]
    execute = execute_fn or _execute_recognition_plan
    cases: list[dict[str, Any]] = []
    for region in regions:
        seed = build_seeded_candidate(region)
        response = execute(_request_for_region(tasks=tasks, region=region, seed=seed))
        case = _case_from_response(region=region, seed=seed, response=response)
        cases.append(case)
    report = {
        "contract_version": "numbered_region_calibration_probe_v1",
        "tasks_path": str(tasks_path) if tasks_path is not None else None,
        "actual_parser_output_path": str(actual_parser_output_path) if actual_parser_output_path is not None else None,
        "generated_tasks_path": str(write_generated_tasks.resolve()) if write_generated_tasks is not None and write_generated_tasks.exists() else None,
        "prompt_profile": tasks.get("prompt_profile") or "source_tasks_prompt",
        "parser_output_path": parser_output_used,
        "enriched_tasks_path": enriched_tasks_path,
        "screenshot_path": tasks.get("screenshot_path"),
        "region_numbers": sorted(wanted),
        "summary": _summary(cases),
        "cases": cases,
    }
    report["full_screen_understanding_summary"] = _full_screen_understanding_summary(tasks=tasks, cases=cases)
    report["calibration_backlog"] = _calibration_backlog(tasks=tasks, cases=cases)
    report["fused_precise_understanding"] = _fused_precise_understanding(tasks=tasks, cases=cases)
    full_overlay_path = _write_full_screen_understanding_overlay(tasks=tasks, cases=cases, out_dir=out_dir)
    if full_overlay_path:
        report["full_screen_understanding_overlay_path"] = full_overlay_path
    overlay_path = _write_compiled_overlay(report=report, out_dir=out_dir)
    if overlay_path:
        report["compiled_overlay_path"] = overlay_path
    report_path = out_dir / "numbered_region_calibration_report.json"
    report["report_path"] = str(report_path.resolve())
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _request_for_region(*, tasks: dict[str, Any], region: dict[str, Any], seed: dict[str, Any]) -> ExecuteRecognitionPlanRequest:
    semantic_action = _semantic_action_for_region(region)
    return ExecuteRecognitionPlanRequest(
        goal=str(region.get("prompt") or f"Calibrate numbered region #{region.get('region_no')}: {seed['label']}"),
        task=semantic_action,
        app_name=str(tasks.get("app_name") or "SEEK"),
        provider_mode="local_grounding",
        agent_mode="execute",
        image_path=str(tasks["screenshot_path"]),
        capture_live=False,
        dry_run=True,
        top_k=5,
        metadata={
            "seeded_candidate_v1": seed,
            "numbered_region_calibration": {
                "contract_version": "numbered_region_calibration_request_v1",
                "region_no": region.get("region_no"),
                "display_only": True,
                "execute_binding_enabled": False,
            },
        },
        operation_context=OperationRuntimeContextModel(semantic_action=semantic_action),
    )


def request_for_region_for_test(
    *,
    tasks: dict[str, Any],
    region: dict[str, Any],
    seed: dict[str, Any],
) -> ExecuteRecognitionPlanRequest:
    return _request_for_region(tasks=tasks, region=region, seed=seed)


def _semantic_action_for_region(region: dict[str, Any]) -> str:
    role = str(region.get("role") or "").casefold()
    label = str(region.get("label") or "").casefold()
    if "input" in role or "textbox" in role:
        return "fill_field"
    if role == "card" and any(term in label for term in ("job", "listing", "result")):
        return "open_detail"
    return "click_target"


def _execute_recognition_plan(request: ExecuteRecognitionPlanRequest) -> dict[str, Any]:
    from app.api import action as action_api

    response = action_api.execute_recognition_plan(request)
    data = response.data or {}
    result = data.get("result") if isinstance(data.get("result"), dict) else data
    return {
        "success": bool(response.success),
        "message": response.message,
        "error": response.error.model_dump() if response.error else None,
        "result": result if isinstance(result, dict) else {},
    }


def _case_from_response(*, region: dict[str, Any], seed: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    result = response.get("result") if isinstance(response.get("result"), dict) else {}
    plan = result.get("recognition_plan") if isinstance(result.get("recognition_plan"), dict) else {}
    pre_click = plan.get("pre_click_decision") if isinstance(plan.get("pre_click_decision"), dict) else {}
    candidate_summary = ((plan.get("candidate_result") or {}).get("summary") or {}) if isinstance(plan.get("candidate_result"), dict) else {}
    narrow_summary = ((plan.get("narrow_search_result") or {}).get("summary") or {}) if isinstance(plan.get("narrow_search_result"), dict) else {}
    vista = ((plan.get("parse_result") or {}).get("vista_point_grounding") or {}) if isinstance(plan.get("parse_result"), dict) else {}
    error = response.get("error") if isinstance(response.get("error"), dict) else {}
    error_code = error.get("code")
    outcome = classify_case_outcome(
        success=bool(response.get("success")),
        pre_click_allowed=pre_click.get("allowed") if "allowed" in pre_click else None,
        candidate_summary=candidate_summary,
        error_code=error_code,
        evidence_level=str(region.get("evidence_level") or ""),
    )
    return {
        "region_no": region.get("region_no"),
        "label": seed["label"],
        "role": seed["role"],
        "evidence_level": region.get("evidence_level"),
        "seeded_candidate": seed,
        "success": bool(response.get("success")),
        "message": response.get("message"),
        "error": error or None,
        "outcome": outcome,
        "vista_point": vista.get("point"),
        "vista_stage": vista.get("vista_stage"),
        "vista_image_preprocess": vista.get("image_preprocess"),
        "pre_click_allowed": pre_click.get("allowed"),
        "pre_click_reasons": pre_click.get("reasons"),
        "selected_click_point": result.get("selected_click_point"),
        "candidate_summary": candidate_summary,
        "narrow_summary": narrow_summary,
        "trace_path": result.get("trace_path"),
        "recognition_plan_trace_path": result.get("recognition_plan_trace_path"),
        "recognition_plan_overlay": result.get("recognition_plan_overlay"),
        "real_clicks": 0,
    }


def _summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for case in cases:
        status = str((case.get("outcome") or {}).get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return {
        "attempted": len(cases),
        "passed": counts.get("passed", 0),
        "needs_human_review": counts.get("needs_human_review", 0),
        "gate_rejected": counts.get("gate_rejected", 0),
        "failed": counts.get("failed", 0),
        "real_clicks": sum(int(case.get("real_clicks") or 0) for case in cases),
        "status_counts": counts,
        "interpretation": "dry-run numbered-region calibration probe; no live click; not recognition accuracy",
    }


def _fused_precise_understanding(*, tasks: dict[str, Any], cases: list[dict[str, Any]]) -> dict[str, Any]:
    items = [_fusion_item(case) for case in cases]
    total_locator_cards = len([item for item in tasks.get("regions", []) if isinstance(item, dict)])
    promotable = [
        item for item in items if (item.get("promotion_policy") or {}).get("promotable_to_pathgraph_candidate_review") is True
    ]
    safe_intercepts = [item for item in items if item.get("calibration_status") == "gate_rejected"]
    return {
        "contract_version": "learn_precise_understanding_fusion_v1",
        "source_contract": "numbered_region_calibration_probe_v1",
        "source_prompt_profile": str(tasks.get("prompt_profile") or ""),
        "screenshot_path": str(tasks.get("screenshot_path") or ""),
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "summary": {
            "total_locator_cards": total_locator_cards,
            "calibrated_cases": len(items),
            "uncalibrated_locator_cards": max(0, total_locator_cards - len(items)),
            "attempted": len(items),
            "promotable_to_pathgraph_candidate_review": len(promotable),
            "needs_human_review": len([item for item in items if item.get("calibration_status") == "needs_human_review"]),
            "safe_intercepts": len(safe_intercepts),
            "failed": len([item for item in items if item.get("calibration_status") == "failed"]),
            "real_clicks": sum(int(item.get("real_clicks") or 0) for item in items),
        },
        "calibration_backlog": _calibration_backlog(tasks=tasks, cases=cases),
        "items": items,
        "interpretation": (
            "Fusion of screen-understanding locator cards and Execute dry-run grounding evidence. "
            "It is review/preparation evidence only, not PathGraph promotion and not click authorization."
        ),
    }


def _calibration_backlog(*, tasks: dict[str, Any], cases: list[dict[str, Any]]) -> dict[str, Any]:
    calibrated_region_numbers = {int(case.get("region_no") or 0) for case in cases if isinstance(case, dict)}
    items = [
        _calibration_backlog_item(region)
        for region in tasks.get("regions", [])
        if isinstance(region, dict) and int(region.get("region_no") or 0) not in calibrated_region_numbers
    ]
    ready = [item for item in items if item.get("ready_for_execute_dry_run") is True]
    review = [item for item in items if item.get("ready_for_execute_dry_run") is not True]
    return {
        "contract_version": "numbered_region_calibration_backlog_v1",
        "summary": {
            "uncalibrated_locator_cards": len(items),
            "ready_for_execute_dry_run": len(ready),
            "review_before_calibration": len(review),
            "display_only": True,
            "execute_binding_enabled": False,
        },
        "items": items,
        "interpretation": (
            "Uncalibrated screen-understanding locator cards queued for future Execute dry-run calibration. "
            "This backlog is review/planning evidence only and does not authorize clicks."
        ),
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def _calibration_backlog_item(region: dict[str, Any]) -> dict[str, Any]:
    triage = _calibration_backlog_triage(region)
    return {
        "region_no": region.get("region_no"),
        "source_item_id": _text(region.get("item_id"), region.get("id")),
        "label": _text(region.get("label"), region.get("text")),
        "role": _text(region.get("role"), "other"),
        "evidence_level": _text(region.get("evidence_level"), "unknown"),
        "rough_bbox_hint": _bbox(region.get("rough_bbox_hint") or region.get("bbox") or {}),
        "suggested_semantic_action": _semantic_action_for_region(region),
        "calibration_lane": triage["calibration_lane"],
        "ready_for_execute_dry_run": triage["ready_for_execute_dry_run"],
        "review_reason": triage["review_reason"],
        "prompt": str(region.get("prompt") or ""),
        "required_next_step": "run_execute_dry_run_calibration_for_numbered_region",
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def _calibration_backlog_triage(region: dict[str, Any]) -> dict[str, Any]:
    role = str(region.get("role") or "").strip().casefold()
    label = str(region.get("label") or region.get("text") or "").strip().casefold()
    if role in {"other", "region", "layout", "container", "section", "text", "label"}:
        return {
            "calibration_lane": "review_before_calibration",
            "ready_for_execute_dry_run": False,
            "review_reason": "non_actionable_or_page_structure_role",
        }
    if any(term in label for term in ("placeholder", "job count", "indicator", "display details here", "select a job")):
        return {
            "calibration_lane": "review_before_calibration",
            "ready_for_execute_dry_run": False,
            "review_reason": "non_actionable_or_page_structure_label",
        }
    return {
        "calibration_lane": "ready_for_execute_dry_run",
        "ready_for_execute_dry_run": True,
        "review_reason": "",
    }


def _full_screen_understanding_summary(*, tasks: dict[str, Any], cases: list[dict[str, Any]]) -> dict[str, Any]:
    total_locator_cards = len([item for item in tasks.get("regions", []) if isinstance(item, dict)])
    calibrated_cases = len(cases)
    return {
        "total_locator_cards": total_locator_cards,
        "calibrated_cases": calibrated_cases,
        "uncalibrated_locator_cards": max(0, total_locator_cards - calibrated_cases),
        "display_only": True,
        "execute_binding_enabled": False,
    }


def _fusion_item(case: dict[str, Any]) -> dict[str, Any]:
    seed = case.get("seeded_candidate") if isinstance(case.get("seeded_candidate"), dict) else {}
    outcome = case.get("outcome") if isinstance(case.get("outcome"), dict) else {}
    status = str(outcome.get("status") or "failed")
    promotable = bool(outcome.get("promotable_to_learning_draft"))
    block_reason = _promotion_block_reason(case=case, status=status)
    return {
        "region_no": case.get("region_no"),
        "source_item_id": _source_item_id_from_seed(seed),
        "label": case.get("label"),
        "role": case.get("role"),
        "evidence_level": case.get("evidence_level"),
        "rough_bbox_hint": seed.get("bbox") if isinstance(seed.get("bbox"), dict) else {},
        "seed_click_point": seed.get("click_point") if isinstance(seed.get("click_point"), dict) else {},
        "vista_point": case.get("vista_point") if isinstance(case.get("vista_point"), dict) else {},
        "selected_click_point": case.get("selected_click_point") if isinstance(case.get("selected_click_point"), dict) else {},
        "calibration_status": status,
        "failure_category": str(outcome.get("category") or ""),
        "point_quality": _point_quality(case),
        "gate_safety": _gate_safety(case),
        "promotion_policy": {
            "promotable_to_pathgraph_candidate_review": promotable,
            "block_reason": block_reason,
            "requires_human_review": not promotable,
            "execute_binding_enabled": False,
        },
        "trace_path": case.get("trace_path"),
        "recognition_plan_trace_path": case.get("recognition_plan_trace_path"),
        "overlay_path": (case.get("recognition_plan_overlay") or {}).get("output_path")
        if isinstance(case.get("recognition_plan_overlay"), dict)
        else None,
        "real_clicks": int(case.get("real_clicks") or 0),
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def _source_item_id_from_seed(seed: dict[str, Any]) -> str:
    candidate_id = str(seed.get("candidate_id") or "")
    prefix = "numbered_region_"
    if candidate_id.startswith(prefix):
        parts = candidate_id[len(prefix) :].split("_", 1)
        if len(parts) == 2:
            return parts[1]
    return ""


def _promotion_block_reason(*, case: dict[str, Any], status: str) -> str:
    if status == "passed":
        return ""
    evidence_level = str(case.get("evidence_level") or "").casefold()
    if evidence_level == "semantic_region_only":
        return "semantic_only_requires_cross_evidence_or_human_review"
    if status == "gate_rejected":
        return "pre_click_gate_rejected"
    if status == "needs_human_review":
        return "locator_model_or_seed_requires_human_review"
    return "calibration_not_validated"


def _point_quality(case: dict[str, Any]) -> str:
    summary = case.get("candidate_summary") if isinstance(case.get("candidate_summary"), dict) else {}
    if summary.get("vista_point_inside_candidate_bbox") is True:
        return "vista_point_inside_seed_bbox"
    if summary.get("vista_point_inside_candidate_bbox") is False:
        return "vista_point_outside_seed_bbox"
    return "not_evaluated"


def _gate_safety(case: dict[str, Any]) -> str:
    if case.get("pre_click_allowed") is True:
        return "passed_allowed_dry_run"
    if case.get("pre_click_allowed") is False:
        return "passed_rejected"
    return "not_evaluated"


def _write_compiled_overlay(*, report: dict[str, Any], out_dir: Path) -> str | None:
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return None
    screenshot_path = Path(str(report.get("screenshot_path") or ""))
    if not screenshot_path.exists():
        return None
    image = Image.open(screenshot_path).convert("RGB")
    draw = ImageDraw.Draw(image)
    colors = {
        "passed": (0, 180, 80),
        "needs_human_review": (230, 150, 0),
        "gate_rejected": (220, 50, 50),
        "failed": (160, 50, 200),
    }
    for case in report.get("cases", []):
        seed = case.get("seeded_candidate") if isinstance(case.get("seeded_candidate"), dict) else {}
        bbox = _bbox(seed.get("bbox") or {})
        status = str((case.get("outcome") or {}).get("status") or "failed")
        color = colors.get(status, (120, 120, 120))
        x1, y1 = bbox["x"], bbox["y"]
        x2, y2 = bbox["x"] + bbox["w"], bbox["y"] + bbox["h"]
        draw.rectangle((x1, y1, x2, y2), outline=color, width=4)
        point = case.get("vista_point") if isinstance(case.get("vista_point"), dict) else None
        if point:
            px, py = int(point["x"]), int(point["y"])
            draw.ellipse((px - 8, py - 8, px + 8, py + 8), outline=color, width=4)
        draw.text((x1, max(0, y1 - 18)), f"#{case.get('region_no')} {status}", fill=color)
    output = out_dir / "numbered_region_calibration_overlay.png"
    image.save(output)
    return str(output.resolve())


def _write_full_screen_understanding_overlay(
    *,
    tasks: dict[str, Any],
    cases: list[dict[str, Any]],
    out_dir: Path,
) -> str | None:
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return None
    screenshot_path = Path(str(tasks.get("screenshot_path") or ""))
    if not screenshot_path.exists():
        return None
    image = Image.open(screenshot_path).convert("RGB")
    draw = ImageDraw.Draw(image)
    calibrated_by_region = {
        int(case.get("region_no") or 0): case for case in cases if isinstance(case, dict) and case.get("region_no") is not None
    }
    raw_color = (70, 120, 220)
    status_colors = {
        "passed": (0, 180, 80),
        "needs_human_review": (230, 150, 0),
        "gate_rejected": (220, 50, 50),
        "failed": (160, 50, 200),
    }
    for region in tasks.get("regions", []):
        if not isinstance(region, dict):
            continue
        region_no = int(region.get("region_no") or 0)
        bbox = _bbox(region.get("rough_bbox_hint") or region.get("bbox") or {})
        if bbox["w"] <= 0 or bbox["h"] <= 0:
            continue
        x1, y1 = bbox["x"], bbox["y"]
        x2, y2 = bbox["x"] + bbox["w"], bbox["y"] + bbox["h"]
        case = calibrated_by_region.get(region_no)
        if case is None:
            draw.rectangle((x1, y1, x2, y2), outline=raw_color, width=2)
            draw.text((x1, max(0, y1 - 16)), f"#{region_no} parser", fill=raw_color)
            continue
        status = str((case.get("outcome") or {}).get("status") or "failed")
        color = status_colors.get(status, (120, 120, 120))
        draw.rectangle((x1, y1, x2, y2), outline=color, width=4)
        selected = case.get("selected_click_point") if isinstance(case.get("selected_click_point"), dict) else None
        vista = case.get("vista_point") if isinstance(case.get("vista_point"), dict) else None
        if selected:
            sx, sy = int(selected["x"]), int(selected["y"])
            draw.line((sx - 10, sy, sx + 10, sy), fill=color, width=3)
            draw.line((sx, sy - 10, sx, sy + 10), fill=color, width=3)
        if vista:
            vx, vy = int(vista["x"]), int(vista["y"])
            draw.ellipse((vx - 7, vy - 7, vx + 7, vy + 7), outline=color, width=3)
        draw.text((x1, max(0, y1 - 16)), f"#{region_no} {status}", fill=color)
    output = out_dir / "full_screen_understanding_overlay.png"
    image.save(output)
    return str(output.resolve())


def _bbox(value: dict[str, Any]) -> dict[str, int]:
    return {
        "x": int(value.get("x") or 0),
        "y": int(value.get("y") or 0),
        "w": int(value.get("w") or value.get("width") or 0),
        "h": int(value.get("h") or value.get("height") or 0),
    }


def _text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _parse_region_numbers(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a dry-run numbered-region calibration probe through Execute Mode.")
    parser.add_argument("--tasks", type=Path)
    parser.add_argument("--actual-parser-output", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--regions", default="1,2,3,5,12")
    parser.add_argument("--parser-output", type=Path)
    parser.add_argument("--enrich-prompts", action="store_true")
    parser.add_argument("--write-enriched-tasks", type=Path)
    parser.add_argument("--write-generated-tasks", type=Path)
    parser.add_argument("--start-model", action="store_true")
    parser.add_argument("--stop-model", action="store_true")
    args = parser.parse_args()

    if args.start_model:
        from app.core.model_server import ensure_model_server

        print(json.dumps(ensure_model_server(stage="locate", profile_id="vista_4b_transformers", wait_until_ready=True, wait_seconds=90), ensure_ascii=False))
    try:
        report = run_numbered_region_calibration_probe(
            tasks_path=args.tasks,
            out_dir=args.out,
            region_numbers=_parse_region_numbers(args.regions),
            parser_output_path=args.parser_output,
            enrich_prompts=args.enrich_prompts,
            write_enriched_tasks=args.write_enriched_tasks,
            actual_parser_output_path=args.actual_parser_output,
            write_generated_tasks=args.write_generated_tasks,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    finally:
        if args.stop_model:
            from app.core.model_server import profile_for_stage, stop_model_server

            print(json.dumps(stop_model_server(profile_for_stage("locate", "vista_4b_transformers")), ensure_ascii=False))


if __name__ == "__main__":
    raise SystemExit(main())
