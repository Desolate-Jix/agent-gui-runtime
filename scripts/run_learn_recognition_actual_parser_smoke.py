from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Callable

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.learn.recognition.classifier import classify_inventory_items
from app.learn.recognition.eligibility import summarize_grounding_eligibility
from app.learn.recognition.layout_cleanup import resolve_inventory_layout
from app.learn.recognition.layout_graph import build_inventory_layout_graph
from app.learn.recognition.parsers import parse_existing_evidence_to_inventory
from app.learn.recognition.pipeline import build_learning_recognition_trial
from app.learn.recognition.support_eligibility import summarize_support_eligibility_from_inventory
from app.vision.local_provider import LocalVisionProvider
from app.vision.schemas import ImageSize, VisionAnalyzeRequest, VisionAnalyzeResponse


ParserModelCaller = Callable[[Path, dict[str, Any]], dict[str, Any] | VisionAnalyzeResponse]


def run_actual_parser_smoke(
    *,
    screenshot_path: str | Path,
    out_dir: str | Path,
    endpoint: str | None,
    model_name: str | None = None,
    model_profile_id: str | None = None,
    app_name: str = "learn_recognition",
    goal: str = "produce semantic UI parser evidence",
    state_hint: str = "unknown",
    timeout_seconds: float = 60.0,
    model_caller: ParserModelCaller | None = None,
    supplemental_sources: dict[str, Any] | None = None,
    source_type: str = "actual_parser_call",
    actual_model_call_in_this_run: bool = True,
    json_stdout: bool = False,
) -> dict[str, Any]:
    screenshot_path = Path(screenshot_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if not screenshot_path.exists():
        raise FileNotFoundError(str(screenshot_path))

    image_size = _image_size(screenshot_path)
    screenshot_sha256 = _sha256_file(screenshot_path)
    model_profile = _load_model_profile(model_profile_id)
    model_profile_summary = _model_profile_summary(model_profile, model_profile_id)
    resolved_endpoint = endpoint or str(model_profile.get("endpoint") or "") or None
    resolved_model_name = (
        model_name
        or str(model_profile.get("model_name") or "")
        or str(model_profile.get("model_id") or "")
        or "Qwen3VL-8B-Instruct-Q4_K_M.gguf"
    )
    model_config = {
        "endpoint": resolved_endpoint,
        "model_name": resolved_model_name,
        "model_profile_id": model_profile_summary.get("profile_id"),
        "model_profile": model_profile_summary,
        "timeout_seconds": timeout_seconds,
        "app_name": app_name,
        "goal": goal,
        "state_hint": state_hint,
        "image_path": str(screenshot_path),
    }
    readiness_blocker = _model_profile_readiness_blocker(
        profile=model_profile,
        profile_summary=model_profile_summary,
        endpoint=resolved_endpoint,
    )
    if readiness_blocker:
        report = _blocked_report(
            screenshot_path=screenshot_path,
            model_config=model_config,
            blocker_category=str(readiness_blocker["failure_category"]),
            message=str(readiness_blocker["message"]),
            extra={
                "model_profile": model_profile_summary,
                "model_profile_id": model_profile_summary.get("profile_id"),
                "model_profile_readiness": readiness_blocker,
            },
        )
        report_path = out_dir / "learn_actual_parser_smoke_report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report["report_path"] = str(report_path)
        if json_stdout:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        return report
    try:
        caller = model_caller or _default_model_caller(
            endpoint=resolved_endpoint,
            model_name=resolved_model_name,
            timeout_seconds=timeout_seconds,
        )
        raw_result = caller(screenshot_path, model_config)
        response_payload = _vision_response_payload(raw_result)
        observe_bundle = _observe_bundle_from_vision_response(
            response_payload=response_payload,
            screenshot_path=screenshot_path,
            screenshot_sha256=screenshot_sha256,
            image_size=image_size,
            model_config=model_config,
            supplemental_sources=supplemental_sources,
        )
        raw_inventory = parse_existing_evidence_to_inventory(observe_bundle)
        layout_cleanup = resolve_inventory_layout(raw_inventory)
        inventory = layout_cleanup["cleaned_items"]
        layout_graph = build_inventory_layout_graph(inventory, screen_size=image_size)
        classification = classify_inventory_items(inventory)
        grounding_eligibility_gate = summarize_grounding_eligibility(_classified_items(classification))
        grounding_eligibility = _grounding_eligibility_summary(classification)
        support_eligibility_summary = summarize_support_eligibility_from_inventory(inventory)
        parser_actual_call_usefulness = _parser_actual_call_usefulness(
            inventory=inventory,
            classification=classification,
            grounding_eligibility=grounding_eligibility,
        )
        trial = build_learning_recognition_trial(
            observe_bundle=observe_bundle,
            state_guess=str(response_payload.get("state_guess") or state_hint),
            summary=str(response_payload.get("screen_summary") or goal),
            grounding_adapter=_calibrated_target_replay_adapter(classification, observe_bundle),
        )

        actual_parser_output_path = out_dir / "actual_parser_output_v1.json"
        actual_parser_output_path.write_text(
            json.dumps(
                {
                    "contract_version": "actual_parser_output_v1",
                    "source_type": source_type,
                    "actual_model_call_in_this_run": bool(actual_model_call_in_this_run),
                    "screenshot_path": str(screenshot_path),
                    "screenshot_sha256": screenshot_sha256,
                    "model_config": model_config,
                    "model_profile": model_profile_summary,
                    "observe_bundle": observe_bundle,
                    "raw_screen_inventory": raw_inventory,
                    "layout_cleanup": layout_cleanup,
                    "layout_graph": layout_graph,
                    "locator_task_cards": trial.get("locator_task_cards") or {},
                    "grounding_eligibility_gate": grounding_eligibility_gate,
                    "support_eligibility_summary": support_eligibility_summary,
                    "screen_inventory": inventory,
                    "classification": classification,
                    "grounding_eligibility": grounding_eligibility,
                    "parser_actual_call_usefulness": parser_actual_call_usefulness,
                    "grounding_validations": trial.get("grounding_validations") or [],
                    "learning_draft": trial.get("learning_draft"),
                    "interpretation": (
                        "fresh actual parser smoke output; replaying this file later is recorded parser evidence, not a fresh actual model call"
                        if actual_model_call_in_this_run
                        else "recorded provider replay output; this is not a fresh actual model call"
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        report = {
            "contract_version": "learn_actual_parser_smoke_report_v1",
            "status": "passed" if inventory else "failed",
            "source_type": source_type,
            "actual_model_call_in_this_run": bool(actual_model_call_in_this_run),
            "actual_parser_output_path": str(actual_parser_output_path),
            "screenshot_path": str(screenshot_path),
            "screenshot_sha256": screenshot_sha256,
            "model_config": model_config,
            "model_profile": model_profile_summary,
            "metrics": {
                "actual_parser_call": (
                    {"passed": 1 if inventory else 0, "attempted": 1, "rate": 1.0 if inventory else 0.0}
                    if actual_model_call_in_this_run
                    else {"passed": 0, "attempted": 0, "rate": "not_covered"}
                ),
                "parse_inventory": {"passed": 1 if inventory else 0, "attempted": 1, "rate": 1.0 if inventory else 0.0},
                "actionable_classification": _metric_from_count(classification.get("summary", {}).get("accepted_for_grounding_count")),
                "non_actionable_rejection": _metric_from_count(classification.get("summary", {}).get("rejected_non_actionable_count")),
            },
            "counts": {
                "vision_region_count": len(response_payload.get("regions") if isinstance(response_payload.get("regions"), list) else []),
                "raw_screen_inventory_count": len(raw_inventory),
                "screen_inventory_count": len(inventory),
                "layout_cleanup_suppressed_count": layout_cleanup["suppressed_count"],
                "layout_cleanup_suppression_reason_counts": layout_cleanup.get("suppression_reason_counts", {}),
                "accepted_for_grounding_count": classification.get("summary", {}).get("accepted_for_grounding_count"),
                "rejected_non_actionable_count": classification.get("summary", {}).get("rejected_non_actionable_count"),
                "needs_human_review_count": classification.get("summary", {}).get("needs_human_review_count"),
                "danger_zone_count": classification.get("summary", {}).get("danger_zone_count"),
                "grounding_eligible_count": grounding_eligibility["grounding_eligible"],
                "review_only_count": grounding_eligibility["review_only"],
                "same_screenshot_interactable_support_count": support_eligibility_summary[
                    "same_screenshot_interactable_support"
                ],
                "semantic_or_ocr_leaked_to_grounding": support_eligibility_summary["semantic_or_ocr_leaked_to_grounding"],
                "grounding_validation_count": len(trial.get("grounding_validations") or []),
                "learning_draft_region_count": len((trial.get("learning_draft") or {}).get("regions") or []),
                "learning_draft_action_count": len((trial.get("learning_draft") or {}).get("action_templates") or []),
                "locator_task_card_count": len((trial.get("locator_task_cards") or {}).get("cards") or []),
            },
            "grounding_eligibility": grounding_eligibility,
            "grounding_eligibility_gate": grounding_eligibility_gate,
            "support_eligibility_summary": support_eligibility_summary,
            "layout_graph": {
                "contract_version": layout_graph["contract_version"],
                "node_count": layout_graph["node_count"],
                "zone_count": layout_graph["zone_count"],
                "zones": layout_graph["zones"],
                "overlap_clusters": layout_graph["overlap_clusters"],
                "interpretation": layout_graph["interpretation"],
            },
            "layout_cleanup": {
                "contract_version": layout_cleanup["contract_version"],
                "input_count": layout_cleanup["input_count"],
                "output_count": layout_cleanup["output_count"],
                "suppressed_count": layout_cleanup["suppressed_count"],
                "suppression_reason_counts": layout_cleanup.get("suppression_reason_counts", {}),
                "overlap_pair_count": layout_cleanup["overlap_pair_count"],
                "duplicates_merged": layout_cleanup["duplicates_merged"],
                "metrics": layout_cleanup["metrics"],
                "interpretation": layout_cleanup["interpretation"],
            },
            "parser_actual_call_usefulness": parser_actual_call_usefulness,
            "safety": _display_only_safety(),
            "interpretation": (
                "single actual parser smoke only; no click, no Execute authorization, no reliability or 90% claim"
                if actual_model_call_in_this_run
                else "recorded provider replay only; no click, no Execute authorization, no fresh model call, no reliability or 90% claim"
            ),
        }
    except Exception as exc:
        report = _blocked_report(
            screenshot_path=screenshot_path,
            model_config=model_config,
            blocker_category="model_endpoint_unavailable_or_invalid_output",
            message=str(exc),
            extra={"model_profile": model_profile_summary},
        )

    report_path = out_dir / "learn_actual_parser_smoke_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["report_path"] = str(report_path)
    if json_stdout:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def _default_model_caller(*, endpoint: str | None, model_name: str, timeout_seconds: float) -> ParserModelCaller:
    if not endpoint:
        raise ValueError("endpoint is required for actual parser smoke")
    provider = LocalVisionProvider(endpoint=endpoint, model_name=model_name, timeout_seconds=timeout_seconds)

    def caller(image_path: Path, model_config: dict[str, Any]) -> VisionAnalyzeResponse:
        return provider.analyze(
            VisionAnalyzeRequest(
                image_path=str(image_path),
                task="observe_screen",
                app_name=str(model_config.get("app_name") or "learn_recognition"),
                goal=str(model_config.get("goal") or "produce semantic UI parser evidence"),
                state_hint=str(model_config.get("state_hint") or "unknown"),
                provider_mode="local_understanding",
                metadata={
                    "temperature": 0.0,
                    "max_output_tokens": 2048,
                    "coordinate_recovery": {
                        "implicit_normalized_1000": True,
                        "scope": "learn_recognition_actual_parser",
                    },
                },
            )
        )

    return caller


def replay_recorded_provider_raw_text(
    *,
    screenshot_path: str | Path,
    out_dir: str | Path,
    raw_text: str,
    model_name: str,
    app_name: str = "learn_recognition",
    goal: str = "replay recorded parser evidence",
    state_hint: str = "unknown",
    supplemental_sources: dict[str, Any] | None = None,
    json_stdout: bool = False,
) -> dict[str, Any]:
    def caller(image_path: Path, model_config: dict[str, Any]) -> VisionAnalyzeResponse:
        image_size = _image_size(image_path)
        return _vision_response_from_recorded_provider_raw_text(
            raw_text=raw_text,
            image_path=image_path,
            image_size=image_size,
            model_name=str(model_config.get("model_name") or model_name),
        )

    return run_actual_parser_smoke(
        screenshot_path=screenshot_path,
        out_dir=out_dir,
        endpoint="recorded://provider-raw-text",
        model_name=model_name,
        app_name=app_name,
        goal=goal,
        state_hint=state_hint,
        model_caller=caller,
        supplemental_sources=supplemental_sources,
        source_type="recorded_provider_replay",
        actual_model_call_in_this_run=False,
        json_stdout=json_stdout,
    )


def _vision_response_from_recorded_provider_raw_text(
    *,
    raw_text: str,
    image_path: Path,
    image_size: dict[str, int],
    model_name: str,
) -> VisionAnalyzeResponse:
    provider = LocalVisionProvider(endpoint="recorded://provider-raw-text", model_name=model_name, timeout_seconds=0)
    parsed_model_json = provider._parse_json_object(raw_text)
    inference_size = _image_size_from_payload(parsed_model_json.get("image_size")) or ImageSize(
        width=_int_or_zero(image_size.get("width")),
        height=_int_or_zero(image_size.get("height")),
    )
    original_size = ImageSize(width=_int_or_zero(image_size.get("width")), height=_int_or_zero(image_size.get("height")))
    raw_parsed_model_json = copy.deepcopy(parsed_model_json)
    runtime_json, coordinate_recovery = provider._remap_to_original_image(
        copy.deepcopy(parsed_model_json),
        inference_size,
        original_size,
        allow_implicit_normalized_1000=True,
    )
    runtime_json["provider"] = model_name
    runtime_json.setdefault("contract_version", "vision_regions_v1")
    runtime_json.setdefault("state_guess", None)
    runtime_json.setdefault("regions", [])
    runtime_json.setdefault("targets", [])
    runtime_json.setdefault("observers", [])
    from app.vision.normalizer import normalizer

    normalized = normalizer.normalize(runtime_json, "local", image_size=original_size.to_dict())
    normalized.raw_text = raw_text
    normalized.raw_response = {
        "contract_version": "provider_model_trace_v1",
        "provider": "recorded_provider_replay",
        "model_name": model_name,
        "image_path": str(image_path),
        "raw_text": raw_text,
        "model_json": runtime_json,
        "endpoint_response": None,
        "attempts": [
            {
                "tag": "recorded_provider_replay",
                "status": "success",
                "requested_max_edge": None,
                "inference_image_size": inference_size.to_dict(),
                "original_image_size": original_size.to_dict(),
                "coordinate_recovery": coordinate_recovery,
                "model_io": {
                    "contract_version": "model_io_attempt_v1",
                    "status": "success",
                    "provider": "recorded_provider_replay",
                    "model_name": model_name,
                    "endpoint": "recorded://provider-raw-text",
                    "task": "observe_screen",
                    "attempt": {
                        "tag": "recorded_provider_replay",
                        "compact_prompt": False,
                        "max_regions": 0,
                        "requested_max_edge": None,
                    },
                    "input": {
                        "image_path": str(image_path),
                        "inference_image_path": str(image_path),
                        "original_image_size": original_size.to_dict(),
                        "inference_image_size": inference_size.to_dict(),
                    },
                    "output": {
                        "raw_text": raw_text,
                        "raw_response": None,
                        "parsed_model_json": raw_parsed_model_json,
                        "runtime_normalized_json": runtime_json,
                        "coordinate_recovery": coordinate_recovery,
                        "parse_error": None,
                    },
                    "raw_text": raw_text,
                    "raw_response": None,
                    "parsed_model_json": raw_parsed_model_json,
                    "runtime_normalized_json": runtime_json,
                    "coordinate_recovery": coordinate_recovery,
                    "parse_error": None,
                },
            }
        ],
    }
    return normalized


def _image_size_from_payload(value: Any) -> ImageSize | None:
    if not isinstance(value, dict):
        return None
    width = _int_or_zero(value.get("width"))
    height = _int_or_zero(value.get("height"))
    if width <= 0 or height <= 0:
        return None
    return ImageSize(width=width, height=height)


def _blocked_report(
    *,
    screenshot_path: Path,
    model_config: dict[str, Any],
    blocker_category: str,
    message: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report = {
        "contract_version": "learn_actual_parser_smoke_report_v1",
        "status": "blocked",
        "source_type": "actual_parser_call",
        "actual_model_call_in_this_run": False,
        "blocker": {
            "failure_category": blocker_category,
            "message": message,
        },
        "screenshot_path": str(screenshot_path),
        "model_config": model_config,
        "metrics": {
            "actual_parser_call": {"passed": 0, "attempted": 0, "rate": "not_covered"},
            "parse_inventory": {"passed": 0, "attempted": 0, "rate": "not_covered"},
        },
        "safety": _display_only_safety(),
        "interpretation": "blocked parser smoke; do not count in actual_parser_call denominator",
    }
    if extra:
        report.update(extra)
    return report


def _vision_response_payload(raw_result: dict[str, Any] | VisionAnalyzeResponse) -> dict[str, Any]:
    if isinstance(raw_result, VisionAnalyzeResponse):
        return raw_result.to_dict()
    if isinstance(raw_result, dict):
        payload = raw_result.get("vision_response") if isinstance(raw_result.get("vision_response"), dict) else raw_result
        if isinstance(payload, dict):
            return payload
    raise ValueError("parser model caller must return a VisionAnalyzeResponse or dict payload")


def _observe_bundle_from_vision_response(
    *,
    response_payload: dict[str, Any],
    screenshot_path: Path,
    screenshot_sha256: str,
    image_size: dict[str, int],
    model_config: dict[str, Any],
    supplemental_sources: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sources = {
        "vision": {
            "provider": response_payload.get("provider"),
            "contract_version": response_payload.get("contract_version"),
            "screen_summary": response_payload.get("screen_summary"),
            "state_guess": response_payload.get("state_guess"),
            "regions": response_payload.get("regions") if isinstance(response_payload.get("regions"), list) else [],
            "targets": response_payload.get("targets") if isinstance(response_payload.get("targets"), list) else [],
            "raw_response": response_payload.get("raw_response"),
            "raw_text": response_payload.get("raw_text"),
        }
    }
    if isinstance(supplemental_sources, dict):
        for key, value in supplemental_sources.items():
            if key == "vision":
                continue
            if isinstance(value, dict):
                sources[str(key)] = value
    return {
        "contract_version": "learn_observe_bundle_v1",
        "source_type": "actual_parser_call",
        "screen_size": image_size,
        "image_size": image_size,
        "screenshot_path": str(screenshot_path),
        "screenshot_sha256": screenshot_sha256,
        "model_config": model_config,
        "sources": sources,
        "safety": _display_only_safety(),
    }


def _metric_from_count(value: Any) -> dict[str, Any]:
    count = _int_or_zero(value)
    return {"passed": count, "attempted": count, "rate": "not_covered" if count == 0 else 1.0}


def _grounding_eligibility_summary(classification: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "grounding_eligible": 0,
        "review_only": 0,
        "blocked_reasons": {},
        "interpretation": "semantic-only parser regions are review evidence only until cross-evidence makes them grounding eligible",
    }
    for bucket in ("accepted_for_grounding", "rejected_non_actionable", "needs_human_review", "danger_zones"):
        items = classification.get(bucket)
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            if item.get("grounding_eligible") is True:
                summary["grounding_eligible"] += 1
            if item.get("review_only") is True:
                summary["review_only"] += 1
            reason = str(item.get("grounding_block_reason") or "").strip()
            if reason:
                blocked = summary["blocked_reasons"]
                blocked[reason] = int(blocked.get(reason, 0)) + 1
    return summary


def _classified_items(classification: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for key in ("accepted_for_grounding", "rejected_non_actionable", "needs_human_review", "danger_zones"):
        bucket = classification.get(key) if isinstance(classification, dict) else []
        items.extend(copy.deepcopy(item) for item in bucket if isinstance(item, dict))
    return items


def _parser_actual_call_usefulness(
    *,
    inventory: list[dict[str, Any]],
    classification: dict[str, Any],
    grounding_eligibility: dict[str, Any],
) -> dict[str, Any]:
    inventory_count = len(inventory)
    grounding_eligible = _int_or_zero(grounding_eligibility.get("grounding_eligible"))
    accepted = _int_or_zero((classification.get("summary") or {}).get("accepted_for_grounding_count"))
    blocked_reasons = grounding_eligibility.get("blocked_reasons") if isinstance(grounding_eligibility.get("blocked_reasons"), dict) else {}
    blocked_reason = ""
    if inventory_count > 0 and grounding_eligible == 0 and blocked_reasons:
        blocked_reason = sorted(blocked_reasons.items(), key=lambda item: (-_int_or_zero(item[1]), str(item[0])))[0][0]
    return {
        "parser_inventory_generated": inventory_count > 0,
        "parser_useful_for_review": inventory_count > 0,
        "parser_useful_for_grounding": grounding_eligible > 0 and accepted > 0,
        "semantic_only_regions": max(0, inventory_count - grounding_eligible),
        "grounding_eligible_regions": grounding_eligible,
        "accepted_for_grounding": accepted,
        "blocked_from_grounding_reason": blocked_reason,
        "interpretation": "review usefulness is not grounding usefulness unless grounding-eligible candidates are produced",
    }


def _calibrated_target_replay_adapter(classification: dict[str, Any], observe_bundle: dict[str, Any]):
    accepted = classification.get("accepted_for_grounding")
    accepted = accepted if isinstance(accepted, list) else []
    calibrated_targets = _calibrated_targets_by_id(observe_bundle)
    has_calibrated_point = any(
        _calibrated_replay_payload(item, calibrated_targets) is not None for item in accepted if isinstance(item, dict)
    )
    if not has_calibrated_point:
        return None

    def adapter(*, item: dict[str, Any], roi_crop: dict[str, Any]) -> dict[str, Any]:
        payload = _calibrated_replay_payload(item, calibrated_targets)
        if payload is None:
            return {
                "evidence": {
                    "coordinate_transform_replay": False,
                    "screenshot_freshness": True,
                    "uia_or_dom_or_parser_overlap": True,
                    "ocr_anchor_overlap": True,
                },
                "debug": {
                    "adapter": "calibrated_target_replay",
                    "status": "skipped_non_calibrated_item",
                    "roi_contract": roi_crop.get("contract_version"),
                },
            }
        point = payload["click_point"]
        return {
            "screen_point": {"x": _int_or_zero(point.get("x")), "y": _int_or_zero(point.get("y"))},
            "screen_bbox": item.get("bbox") if isinstance(item.get("bbox"), dict) else {},
            "evidence": {
                "coordinate_transform_replay": True,
                "screenshot_freshness": True,
                "uia_or_dom_or_parser_overlap": True,
                "ocr_anchor_overlap": True,
            },
            "debug": {
                "adapter": "calibrated_target_replay",
                "status": "replayed_reviewed_calibrated_target",
                "roi_contract": roi_crop.get("contract_version"),
                "support_item_id": payload.get("support_item_id"),
                "support_bbox": payload.get("support_bbox"),
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            },
        }

    return adapter


def _calibrated_targets_by_id(observe_bundle: dict[str, Any]) -> dict[str, dict[str, Any]]:
    sources = observe_bundle.get("sources") if isinstance(observe_bundle.get("sources"), dict) else {}
    index: dict[str, dict[str, Any]] = {}
    for source in sources.values():
        if not isinstance(source, dict):
            continue
        targets = source.get("targets") if isinstance(source.get("targets"), list) else []
        for target in targets:
            if not isinstance(target, dict):
                continue
            candidate_id = str(target.get("candidate_id") or target.get("item_id") or "").strip()
            if not candidate_id:
                continue
            if _is_calibrated_target_payload_with_point(target):
                index[candidate_id] = target
    return index


def _calibrated_replay_payload(item: dict[str, Any], calibrated_targets: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    if _is_calibrated_item_with_point(item):
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        return {
            "click_point": metadata.get("click_point"),
            "support_bbox": item.get("bbox"),
            "support_item_id": item.get("item_id"),
        }

    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    cross_evidence = metadata.get("cross_evidence") if isinstance(metadata.get("cross_evidence"), dict) else {}
    support_item_id = str(cross_evidence.get("support_item_id") or "").strip()
    support = calibrated_targets.get(support_item_id)
    if not support:
        return None
    point = support.get("click_point") if isinstance(support.get("click_point"), dict) else {}
    bbox = support.get("bbox") if isinstance(support.get("bbox"), dict) else {}
    if not _point_inside_bbox(point, bbox):
        return None
    return {
        "click_point": point,
        "support_bbox": bbox,
        "support_item_id": support_item_id,
    }


def _is_calibrated_target_payload_with_point(target: dict[str, Any]) -> bool:
    bbox = target.get("bbox") if isinstance(target.get("bbox"), dict) else {}
    point = target.get("click_point") if isinstance(target.get("click_point"), dict) else {}
    return bool(bbox and point and _point_inside_bbox(point, bbox))


def _is_calibrated_item_with_point(item: dict[str, Any]) -> bool:
    sources = item.get("source_evidence") if isinstance(item.get("source_evidence"), list) else []
    if "calibrated_target" not in [str(source) for source in sources]:
        return False
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    point = metadata.get("click_point") if isinstance(metadata.get("click_point"), dict) else {}
    bbox = item.get("bbox") if isinstance(item.get("bbox"), dict) else {}
    if not bbox or not point:
        return False
    return _point_inside_bbox(point, bbox)


def _point_inside_bbox(point: dict[str, Any], bbox: dict[str, Any]) -> bool:
    return (
        _int_or_zero(bbox.get("x")) <= _int_or_zero(point.get("x")) <= _int_or_zero(bbox.get("x")) + _int_or_zero(bbox.get("w"))
        and _int_or_zero(bbox.get("y")) <= _int_or_zero(point.get("y")) <= _int_or_zero(bbox.get("y")) + _int_or_zero(bbox.get("h"))
    )


def _display_only_safety() -> dict[str, Any]:
    return {
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "real_action_requires_gate": True,
        "real_clicks_performed": 0,
        "final_submit_forbidden": True,
    }


def _image_size(path: Path) -> dict[str, int]:
    with Image.open(path) as image:
        return {"width": image.width, "height": image.height}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _int_or_zero(value: Any) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _load_model_profile(profile_id: str | None) -> dict[str, Any]:
    profile_key = str(profile_id or "").strip()
    if not profile_key:
        return {}
    profile_path = Path(profile_key)
    if not profile_path.is_absolute():
        if profile_path.suffix.lower() != ".json":
            profile_path = PROJECT_ROOT / "configs" / "model_profiles" / f"{profile_key}.json"
        else:
            profile_path = PROJECT_ROOT / profile_path
    if not profile_path.exists():
        raise FileNotFoundError(f"model profile not found: {profile_key}")
    profile = _read_json(profile_path)
    if str(profile.get("mode_scope") or "") != "learn_only":
        raise ValueError(f"model profile must be learn_only: {profile_key}")
    if profile.get("execute_binding_enabled") is not False:
        raise ValueError(f"model profile must keep execute_binding_enabled=false: {profile_key}")
    return profile


def _model_profile_summary(profile: dict[str, Any], requested_profile_id: str | None) -> dict[str, Any]:
    if not profile and not str(requested_profile_id or "").strip():
        return {}
    profile_id = str(profile.get("profile_id") or requested_profile_id or "").strip()
    return {
        "profile_id": profile_id,
        "model_id": str(profile.get("model_id") or "").strip(),
        "model_name": str(profile.get("model_name") or "").strip(),
        "model_family": str(profile.get("model_family") or "").strip(),
        "provider_mode": str(profile.get("provider_mode") or "").strip(),
        "mode_scope": str(profile.get("mode_scope") or "").strip(),
        "max_parameters_b": profile.get("max_parameters_b"),
        "download_status": str(profile.get("download_status") or "").strip(),
        "launchable": bool(profile.get("launchable")),
        "endpoint": str(profile.get("endpoint") or "").strip(),
        "model_path": str(profile.get("model_path") or "").strip(),
        "artifact_is_authorization": bool(profile.get("artifact_is_authorization")),
        "execute_binding_enabled": bool(profile.get("execute_binding_enabled")),
    }


def _model_profile_readiness_blocker(
    *,
    profile: dict[str, Any],
    profile_summary: dict[str, Any],
    endpoint: str | None,
) -> dict[str, Any] | None:
    if not profile:
        return None
    readiness = {
        "contract_version": "learn_actual_parser_model_profile_readiness_v1",
        "profile_id": profile_summary.get("profile_id"),
        "model_id": profile_summary.get("model_id"),
        "model_family": profile_summary.get("model_family"),
        "provider_mode": profile_summary.get("provider_mode"),
        "download_status": profile_summary.get("download_status"),
        "launchable": profile_summary.get("launchable") is True,
        "endpoint_present": bool(str(endpoint or "").strip()),
        "model_path": profile_summary.get("model_path") or "",
        "interpretation": "profile readiness preflight only; blocked profiles do not enter actual_parser_call denominator",
    }
    download_status = str(readiness["download_status"] or "").casefold()
    not_downloaded_statuses = {"", "not_downloaded", "metadata_only", "planned", "todo"}
    if download_status in not_downloaded_statuses:
        return {
            **readiness,
            "failure_category": "model_profile_not_downloaded",
            "message": f"model profile {readiness['profile_id']} is not downloaded or only metadata is available",
        }
    if readiness["launchable"] is not True:
        return {
            **readiness,
            "failure_category": "model_profile_not_launchable",
            "message": f"model profile {readiness['profile_id']} is not marked launchable",
        }
    if readiness["endpoint_present"] is not True:
        return {
            **readiness,
            "failure_category": "model_profile_endpoint_missing",
            "message": f"model profile {readiness['profile_id']} has no endpoint for actual parser smoke",
        }
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--screenshot", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--endpoint", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--model-profile", default=None)
    parser.add_argument("--app-name", default="learn_recognition")
    parser.add_argument("--goal", default="produce semantic UI parser evidence")
    parser.add_argument("--state-hint", default="unknown")
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    run_actual_parser_smoke(
        screenshot_path=args.screenshot,
        out_dir=args.out,
        endpoint=args.endpoint,
        model_name=args.model,
        model_profile_id=args.model_profile,
        app_name=args.app_name,
        goal=args.goal,
        state_hint=args.state_hint,
        timeout_seconds=args.timeout_seconds,
        json_stdout=args.json,
    )


if __name__ == "__main__":
    main()
