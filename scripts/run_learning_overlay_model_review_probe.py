from __future__ import annotations

import argparse
import base64
from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sys
from typing import Any
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.learn.recognition.model_review import (
    FOCUSED_CARD_REVIEW_ROLES,
    apply_review_patch,
    build_focused_group_review_prompt,
    build_missing_region_candidate_review_prompt,
    build_missing_region_candidates,
    build_missing_locator_tasks,
    build_model_review_prompt,
    consolidate_missing_region_candidates,
    enforce_group_review_only_patch,
    enforce_missing_candidate_decision_policy,
    enforce_focused_semantic_transition,
    exclude_candidates_covered_by_missing_repairs,
    focused_card_review_records,
    merge_focused_group_reviews,
    merge_missing_region_audit,
    merge_deterministic_review_keeps,
    normalize_model_review_protocol,
    partition_model_review_scope,
    parse_focused_group_review_response,
    parse_missing_region_candidate_review_response,
    parse_model_review_response,
    render_focused_group_review_overlay,
    render_model_review_input_overlay,
    render_review_overlays,
    resolve_missing_region_audit_candidates,
    score_review_against_adjudication,
    validate_review_patch,
)
from app.learn.recognition.review_workflow import run_review_repair_workflow


FULL_PAGE_PROMPT_CHAR_LIMIT = 12_000


def _requires_preflight_group_batches(prompt: str) -> bool:
    return len(prompt) > FULL_PAGE_PROMPT_CHAR_LIMIT


def run_probe(
    *,
    stage2_json_path: Path,
    out_dir: Path,
    overlay_path: Path | None = None,
    screenshot_path: Path | None = None,
    recorded_response_path: Path | None = None,
    adjudication_path: Path | None = None,
    endpoint: str = "http://127.0.0.1:13240/v1/chat/completions",
    model_name: str = "Qwen3VL-8B-Instruct-Q4_K_M.gguf",
    timeout_seconds: float = 240.0,
) -> dict[str, Any]:
    source = _load_json(stage2_json_path)
    stage2, source_context = _extract_stage2(source)
    resolved_overlay = overlay_path or _path_from_source(source_context, "compiled_overlay_path")
    resolved_screenshot = screenshot_path or _path_from_source(source_context, "source_image_path")
    if resolved_overlay is None or not resolved_overlay.exists():
        raise FileNotFoundError(f"composite overlay is required: {resolved_overlay}")
    if resolved_screenshot is None or not resolved_screenshot.exists():
        raise FileNotFoundError(f"source screenshot is required: {resolved_screenshot}")

    out_dir.mkdir(parents=True, exist_ok=True)
    review_scope = partition_model_review_scope(stage2)
    model_stage2 = review_scope["model_stage2"]
    review_input = render_model_review_input_overlay(
        resolved_screenshot,
        model_stage2,
        out_dir / "model_review_input_overlay.png",
    )
    prompt = build_model_review_prompt(model_stage2)
    prompt_path = out_dir / "model_review_prompt.txt"
    prompt_path.write_text(prompt, encoding="utf-8")

    actual_model_call = recorded_response_path is None
    endpoint_response: dict[str, Any] | None = None
    full_page_call_mode = "recorded_model_output" if not actual_model_call else "single_full_page_call"
    full_page_model_called = False
    if recorded_response_path is not None:
        raw_text = recorded_response_path.read_text(encoding="utf-8-sig")
        source_type = "recorded_model_output"
    elif _requires_preflight_group_batches(prompt):
        raw_text = json.dumps({"group_reviews": [], "missing": []}, ensure_ascii=False)
        source_type = "actual_model_call"
        full_page_call_mode = "preflight_batched"
    else:
        endpoint_response = _call_model(
            endpoint=endpoint,
            model_name=model_name,
            image_path=Path(review_input["overlay_path"]),
            prompt=prompt,
            timeout_seconds=timeout_seconds,
        )
        raw_text = _message_text(endpoint_response)
        source_type = "actual_model_call"
        full_page_model_called = True

    raw_path = out_dir / "raw_model_output.txt"
    raw_path.write_text(raw_text, encoding="utf-8")
    if endpoint_response is not None:
        _write_json(out_dir / "raw_endpoint_response.json", endpoint_response)

    schema_repair_retry = {"attempted": False, "succeeded": False, "max_attempts": 1}
    schema_repair_prompt_path: Path | None = None
    schema_repair_raw_path: Path | None = None
    try:
        parsed_patch = parse_model_review_response(raw_text)
    except ValueError as exc:
        if not actual_model_call:
            raise
        schema_repair_retry["attempted"] = True
        _write_json(
            out_dir / "initial_parse_error.json",
            {
                "error_type": type(exc).__name__,
                "message": str(exc),
                "raw_model_output_path": str(raw_path.resolve()),
            },
        )
        schema_repair_prompt = (
            "Repair only the JSON syntax of the previous GUI review response. Preserve its review decisions and reasons. "
            "Return one valid JSON object with arrays group_reviews and missing, with no markdown and no commentary. "
            "Do not invent region IDs, boxes, actions, or extra reviews.\n\nPrevious response:\n"
            + raw_text
        )
        schema_repair_prompt_path = out_dir / "schema_repair_prompt.txt"
        schema_repair_prompt_path.write_text(schema_repair_prompt, encoding="utf-8")
        schema_repair_response = _call_model(
            endpoint=endpoint,
            model_name=model_name,
            image_path=Path(review_input["overlay_path"]),
            prompt=schema_repair_prompt,
            timeout_seconds=timeout_seconds,
        )
        schema_repair_raw = _message_text(schema_repair_response)
        schema_repair_raw_path = out_dir / "schema_repair_raw_model_output.txt"
        schema_repair_raw_path.write_text(schema_repair_raw, encoding="utf-8")
        _write_json(out_dir / "schema_repair_endpoint_response.json", schema_repair_response)
        parsed_patch = parse_model_review_response(schema_repair_raw)
        schema_repair_retry["succeeded"] = True
    _write_json(out_dir / "parsed_full_page_review_patch.json", parsed_patch)
    parsed_patch = enforce_group_review_only_patch(parsed_patch)
    parsed_patch = normalize_model_review_protocol(
        model_stage2,
        parsed_patch,
        review_id_map=review_input["review_id_map"],
    )
    _write_json(out_dir / "normalized_full_page_review_patch.json", parsed_patch)
    omitted_group_followup = {
        "attempted_groups": 0,
        "batch_count": 0,
        "resolved_groups": 0,
        "remaining_needs_human_review": 0,
        "batch_size": 8,
    }
    if actual_model_call:
        parsed_patch, omitted_group_followup = _review_omitted_groups(
            stage2=model_stage2,
            base_patch=parsed_patch,
            screenshot_path=resolved_screenshot,
            out_dir=out_dir / "omitted_group_followup",
            endpoint=endpoint,
            model_name=model_name,
            timeout_seconds=timeout_seconds,
            batch_size=8,
        )
    parsed_patch = merge_deterministic_review_keeps(
        parsed_patch,
        review_scope["deterministic_keep_reviews"],
    )
    focused_summary = {
        "attempted": 0,
        "parsed": 0,
        "protocol_failed": 0,
        "candidate_roles": sorted(FOCUSED_CARD_REVIEW_ROLES),
    }
    if actual_model_call:
        focused_reviews: list[dict[str, Any]] = []
        focused_dir = out_dir / "focused_reviews"
        focused_dir.mkdir(parents=True, exist_ok=True)
        for index, record in enumerate(focused_card_review_records(stage2), start=1):
            focused_summary["attempted"] += 1
            focused_prompt = build_focused_group_review_prompt(record)
            stem = f"{index:02d}_{str(record['review_id']).casefold()}"
            (focused_dir / f"{stem}_prompt.txt").write_text(focused_prompt, encoding="utf-8")
            focused_input = render_focused_group_review_overlay(
                resolved_screenshot,
                record,
                focused_dir / f"{stem}_focused_overlay.png",
            )
            _write_json(focused_dir / f"{stem}_input.json", focused_input)
            try:
                focused_endpoint_response = _call_model(
                    endpoint=endpoint,
                    model_name=model_name,
                    image_path=Path(focused_input["overlay_path"]),
                    prompt=focused_prompt,
                    timeout_seconds=timeout_seconds,
                )
                focused_raw = _message_text(focused_endpoint_response)
                (focused_dir / f"{stem}_raw.txt").write_text(focused_raw, encoding="utf-8")
                _write_json(focused_dir / f"{stem}_endpoint_response.json", focused_endpoint_response)
                focused_review = parse_focused_group_review_response(
                    focused_raw,
                    expected_region_id=str(record["review_id"]),
                    source_region_id=str(record["region_id"]),
                    source_role=str(record.get("role") or ""),
                )
                focused_review["region_id"] = str(record["region_id"])
                focused_review = enforce_focused_semantic_transition(record, focused_review)
                _write_json(focused_dir / f"{stem}_parsed.json", focused_review)
                focused_reviews.append(focused_review)
                focused_summary["parsed"] += 1
            except (OSError, TimeoutError, ValueError) as exc:
                focused_summary["protocol_failed"] += 1
                error = {
                    "region_id": str(record["region_id"]),
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "case_outcome": "needs_human_review",
                }
                _write_json(focused_dir / f"{stem}_error.json", error)
                focused_reviews.append(
                    {
                        "region_id": str(record["region_id"]),
                        "decision": "needs_human_review",
                        "new_role": None,
                        "structural_repair": "none",
                        "reason": f"focused review protocol failure: {type(exc).__name__}: {exc}",
                    }
                )
        parsed_patch = merge_focused_group_reviews(
            stage2=stage2,
            base_patch=parsed_patch,
            focused_reviews=focused_reviews,
        )
    missing_region_audit = {
        "attempted": False,
        "parsed": False,
        "missing_count": 0,
        "protocol_failed": False,
        "protocol_failed_count": 0,
        "accepted_count": 0,
        "rejected_count": 0,
        "candidate_calls_attempted": 0,
        "prompt_version": "learning_missing_region_candidate_review_prompt_v1",
        "input_overlay_path": None,
        "prompt_path": None,
        "raw_model_output_path": None,
        "error_path": None,
        "candidate_path": None,
        "candidate_decisions_path": None,
        "candidate_count": 0,
    }
    if actual_model_call:
        preliminary_patch = validate_review_patch(
            stage2,
            parsed_patch,
            require_complete_group_coverage=True,
        )
        preliminary_stage2 = apply_review_patch(stage2, preliminary_patch)
        missing_audit_dir = out_dir / "missing_region_audit"
        missing_audit_dir.mkdir(parents=True, exist_ok=True)
        missing_candidates = consolidate_missing_region_candidates(
            exclude_candidates_covered_by_missing_repairs(
                build_missing_region_candidates(preliminary_stage2),
                preliminary_patch,
            )
        )
        missing_candidates_path = missing_audit_dir / "missing_region_candidates.json"
        _write_json(missing_candidates_path, missing_candidates)
        missing_overlay = render_model_review_input_overlay(
            resolved_screenshot,
            preliminary_stage2,
            missing_audit_dir / "reviewed_missing_audit_overlay.png",
            include_stage1_roots=False,
            missing_candidates=missing_candidates["candidates"],
        )
        missing_region_audit.update(
            {
                "attempted": bool(missing_candidates["candidate_count"]),
                "input_overlay_path": missing_overlay["overlay_path"],
                "candidate_path": str(missing_candidates_path.resolve()),
                "candidate_count": missing_candidates["candidate_count"],
            }
        )
        selected_missing: list[dict[str, Any]] = []
        candidate_decisions: list[dict[str, Any]] = []
        protocol_errors: list[dict[str, Any]] = []
        candidate_review_dir = missing_audit_dir / "candidate_reviews"
        for candidate in missing_candidates["candidates"]:
            candidate_id = str(candidate["candidate_id"])
            candidate_dir = candidate_review_dir / candidate_id
            candidate_dir.mkdir(parents=True, exist_ok=True)
            candidate_overlay = render_model_review_input_overlay(
                resolved_screenshot,
                preliminary_stage2,
                candidate_dir / "candidate_overlay.png",
                include_stage1_roots=False,
                missing_candidates=[candidate],
            )
            candidate_prompt = build_missing_region_candidate_review_prompt(preliminary_stage2, candidate)
            candidate_prompt_path = candidate_dir / "prompt.txt"
            candidate_prompt_path.write_text(candidate_prompt, encoding="utf-8")
            missing_region_audit["candidate_calls_attempted"] += 1
            try:
                candidate_response = _call_model(
                    endpoint=endpoint,
                    model_name=model_name,
                    image_path=Path(candidate_overlay["overlay_path"]),
                    prompt=candidate_prompt,
                    timeout_seconds=timeout_seconds,
                )
                candidate_raw = _message_text(candidate_response)
                candidate_raw_path = candidate_dir / "raw_model_output.txt"
                candidate_raw_path.write_text(candidate_raw, encoding="utf-8")
                _write_json(candidate_dir / "raw_endpoint_response.json", candidate_response)
                decision = enforce_missing_candidate_decision_policy(
                    parse_missing_region_candidate_review_response(
                        candidate_raw,
                        expected_candidate_id=candidate_id,
                    ),
                    candidate,
                )
                _write_json(candidate_dir / "parsed_decision.json", decision)
                candidate_decisions.append(
                    {
                        **decision,
                        "status": "parsed",
                        "overlay_path": candidate_overlay["overlay_path"],
                        "prompt_path": str(candidate_prompt_path.resolve()),
                        "raw_model_output_path": str(candidate_raw_path.resolve()),
                    }
                )
                if decision["decision"] == "accept_candidate":
                    selected_missing.append(
                        {
                            key: decision[key]
                            for key in (
                                "candidate_id",
                                "description",
                                "expected_role",
                                "repair_route",
                                "reason",
                            )
                        }
                    )
                else:
                    missing_region_audit["rejected_count"] += 1
            except (OSError, TimeoutError, ValueError) as exc:
                error = {
                    "candidate_id": candidate_id,
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
                _write_json(candidate_dir / "error.json", error)
                protocol_errors.append(error)
                candidate_decisions.append(
                    {
                        **error,
                        "status": "protocol_failed",
                        "overlay_path": candidate_overlay["overlay_path"],
                        "prompt_path": str(candidate_prompt_path.resolve()),
                    }
                )
        candidate_decisions_path = missing_audit_dir / "candidate_decisions.json"
        _write_json(candidate_decisions_path, {"candidate_decisions": candidate_decisions})
        selected_missing_patch = {"missing": selected_missing}
        _write_json(missing_audit_dir / "selected_missing_patch.json", selected_missing_patch)
        missing_patch = resolve_missing_region_audit_candidates(
            selected_missing_patch,
            missing_candidates,
        )
        _write_json(missing_audit_dir / "parsed_missing_patch.json", missing_patch)
        parsed_patch = merge_missing_region_audit(parsed_patch, missing_patch)
        if protocol_errors:
            parsed_patch = merge_missing_region_audit(
                parsed_patch,
                None,
                protocol_error=f"{len(protocol_errors)} candidate review protocol failure(s)",
            )
            error_path = missing_audit_dir / "errors.json"
            _write_json(error_path, {"errors": protocol_errors})
            missing_region_audit["error_path"] = str(error_path.resolve())
        missing_region_audit.update(
            {
                "parsed": not protocol_errors,
                "protocol_failed": bool(protocol_errors),
                "protocol_failed_count": len(protocol_errors),
                "accepted_count": len(missing_patch["missing"]),
                "missing_count": len(missing_patch["missing"]),
                "candidate_decisions_path": str(candidate_decisions_path.resolve()),
            }
        )
    _write_json(out_dir / "parsed_review_patch.json", parsed_patch)
    validated_patch = validate_review_patch(stage2, parsed_patch, require_complete_group_coverage=True)
    _write_json(out_dir / "validated_review_patch.json", validated_patch)
    workflow = run_review_repair_workflow(
        stage2=stage2,
        validated_patch=validated_patch,
        screenshot_path=str(resolved_screenshot.resolve()),
    )
    _write_json(out_dir / "review_repair_workflow.json", workflow)
    reviewed_stage2 = workflow["recomposed_stage2"]
    reviewed_stage2_path = out_dir / "reviewed_stage2.json"
    _write_json(reviewed_stage2_path, reviewed_stage2)
    repair_handoff = workflow["repair_handoff"]
    repair_path = out_dir / "missing_repair_handoff.json"
    _write_json(repair_path, repair_handoff)
    overlay_outputs = render_review_overlays(
        screenshot_path=resolved_screenshot,
        before_stage2=stage2,
        after_stage2=reviewed_stage2,
        validated_patch=validated_patch,
        out_dir=out_dir / "overlays",
    )
    adjudication_score: dict[str, Any] | None = None
    if adjudication_path is not None:
        adjudication_score = score_review_against_adjudication(
            stage2,
            reviewed_stage2,
            _load_json(adjudication_path),
        )
        _write_json(out_dir / "review_adjudication_score.json", adjudication_score)

    report = {
        "contract_version": "learning_overlay_model_review_probe_report_v1",
        "created_at": datetime.now(UTC).isoformat(),
        "status": "review_patch_validated",
        "source_type": source_type,
        "actual_model_call": actual_model_call,
        "model_name": model_name,
        "prompt_version": "learning_overlay_model_review_prompt_v3",
        "schema_version": "learning_model_review_patch_v1",
        "parser_version": "learning_model_review_parser_v1",
        "inference_parameters": {
            "temperature": 0.0,
            "max_tokens": 4096,
            "response_format": "json_object",
        },
        "input_capture_sha256": hashlib.sha256(resolved_screenshot.read_bytes()).hexdigest(),
        "source_graph_revision": _graph_revision(stage2),
        "endpoint": endpoint if actual_model_call else None,
        "stage2_json_path": str(stage2_json_path.resolve()),
        "screenshot_path": str(resolved_screenshot.resolve()),
        "composite_overlay_path": str(resolved_overlay.resolve()),
        "before_review_overlay_path": str(resolved_overlay.resolve()),
        "model_review_input_overlay_path": review_input["overlay_path"],
        "model_review_input_group_count": review_input["group_count"],
        "model_review_scope": _model_review_scope_summary(stage2, review_scope),
        "full_page_call_mode": full_page_call_mode,
        "full_page_model_called": full_page_model_called,
        "full_page_prompt_chars": len(prompt),
        "full_page_prompt_char_limit": FULL_PAGE_PROMPT_CHAR_LIMIT,
        "prompt_path": str(prompt_path.resolve()),
        "raw_model_output_path": str(raw_path.resolve()),
        "raw_model_output_is_deterministic_batch_seed": full_page_call_mode == "preflight_batched",
        "schema_repair_retry": schema_repair_retry,
        "schema_repair_prompt_path": str(schema_repair_prompt_path.resolve()) if schema_repair_prompt_path else None,
        "schema_repair_raw_model_output_path": str(schema_repair_raw_path.resolve()) if schema_repair_raw_path else None,
        "omitted_group_followup": omitted_group_followup,
        "parsed_review_patch_path": str((out_dir / "parsed_review_patch.json").resolve()),
        "normalized_full_page_review_patch_path": str(
            (out_dir / "normalized_full_page_review_patch.json").resolve()
        ),
        "protocol_adjustment_count": len(parsed_patch.get("protocol_adjustments") or []),
        "validated_review_patch_path": str((out_dir / "validated_review_patch.json").resolve()),
        "reviewed_stage2_path": str(reviewed_stage2_path.resolve()),
        "missing_repair_handoff_path": str(repair_path.resolve()),
        **overlay_outputs,
        "adjudication_path": str(adjudication_path.resolve()) if adjudication_path is not None else None,
        "adjudication": adjudication_score,
        "review_summary": reviewed_stage2.get("model_review_summary"),
        "workflow_state": workflow["workflow_state"],
        "completed_review_only": workflow["completed"],
        "removal_resolutions": workflow["removal_resolutions"],
        "replacement_integrity_gate": workflow["replacement_integrity_gate"],
        "repair_pending_count": workflow["repair_pending_count"],
        "review_repair_workflow_path": str((out_dir / "review_repair_workflow.json").resolve()),
        "focused_review": focused_summary,
        "missing_region_audit": missing_region_audit,
        "repair_summary": {
            "precise_locator_count": repair_handoff["precise_locator_count"],
            "stage1_repartition_count": repair_handoff["stage1_repartition_count"],
        },
        "safety": {
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "real_clicks": 0,
            "live_fills": 0,
            "live_submits": 0,
        },
        "interpretation": (
            "Experimental model review of a composite learning overlay. A valid patch is review evidence only; "
            "missing targets still require precise grounding or Stage1 repartition repair."
        ),
    }
    report_path = out_dir / "learning_overlay_model_review_report.json"
    report["report_path"] = str(report_path.resolve())
    _write_json(report_path, report)
    return report


def _model_review_scope_summary(
    stage2: dict[str, Any],
    review_scope: dict[str, Any],
) -> dict[str, Any]:
    roles_by_id = {
        str(group.get("group_id") or ""): str(group.get("role") or "")
        for root in stage2.get("regions", [])
        if isinstance(root, dict)
        for group in root.get("subregion_groups", [])
        if isinstance(group, dict)
    }
    deterministic_keep_roles: dict[str, int] = {}
    for review in review_scope.get("deterministic_keep_reviews", []):
        region_id = str(review.get("region_id") or "")
        role = roles_by_id.get(region_id, "unknown")
        deterministic_keep_roles[role] = deterministic_keep_roles.get(role, 0) + 1
    return {
        "contract_version": "learning_model_review_scope_v1",
        "source_group_count": len(roles_by_id),
        "model_group_count": int(review_scope.get("model_group_count") or 0),
        "deterministic_keep_count": int(review_scope.get("deterministic_keep_count") or 0),
        "deterministic_keep_roles": deterministic_keep_roles,
        "interpretation": "deterministic leaf invariants are not model review decisions",
    }


def _review_omitted_groups(
    *,
    stage2: dict[str, Any],
    base_patch: dict[str, Any],
    screenshot_path: Path,
    out_dir: Path,
    endpoint: str,
    model_name: str,
    timeout_seconds: float,
    batch_size: int,
) -> tuple[dict[str, Any], dict[str, int]]:
    omitted_ids = sorted(
        {
            str(item.get("region_id") or "")
            for item in base_patch.get("protocol_adjustments", [])
            if isinstance(item, dict)
            and item.get("category") == "omitted_group_safe_stopped"
            and str(item.get("region_id") or "")
        }
    )
    summary = {
        "attempted_groups": len(omitted_ids),
        "batch_count": 0,
        "resolved_groups": 0,
        "remaining_needs_human_review": len(omitted_ids),
        "batch_size": int(batch_size),
        "retry_round_count": 0,
    }
    if not omitted_ids:
        return base_patch, summary

    out_dir.mkdir(parents=True, exist_ok=True)
    merged = deepcopy(base_patch)
    reviews_by_id = {
        str(item.get("region_id") or ""): deepcopy(item)
        for item in merged.get("group_reviews", [])
        if isinstance(item, dict) and str(item.get("region_id") or "")
    }
    merged_missing = [deepcopy(item) for item in merged.get("missing", []) if isinstance(item, dict)]
    merged_needs_review = [
        deepcopy(item) for item in merged.get("needs_human_review", []) if isinstance(item, dict)
    ]
    merged_adjustments = [
        deepcopy(item) for item in merged.get("protocol_adjustments", []) if isinstance(item, dict)
    ]
    resolved_ids: set[str] = set()

    round_batch_sizes = list(dict.fromkeys((int(batch_size), max(1, int(batch_size) // 2), 1)))
    pending_retry_ids = list(omitted_ids)
    for round_index, round_batch_size in enumerate(round_batch_sizes):
        if not pending_retry_ids:
            break
        if round_index > 0:
            summary["retry_round_count"] += 1
        next_retry_ids: set[str] = set()
        for batch_index, start in enumerate(
            range(0, len(pending_retry_ids), round_batch_size),
            start=1,
        ):
            batch_ids = pending_retry_ids[start : start + round_batch_size]
            summary["batch_count"] += 1
            subset = _stage2_group_subset(stage2, set(batch_ids))
            batch_stem = (
                f"batch_{batch_index:02d}"
                if round_index == 0
                else f"retry_{round_index:02d}_batch_{batch_index:02d}"
            )
            batch_input = render_model_review_input_overlay(
                screenshot_path,
                subset,
                out_dir / f"{batch_stem}_overlay.png",
            )
            prompt = (
                "Follow-up audit only for groups omitted by an earlier response. Review every required ID below; "
                "do not repeat or modify any other group.\n\n"
                + build_model_review_prompt(subset)
            )
            (out_dir / f"{batch_stem}_prompt.txt").write_text(prompt, encoding="utf-8")
            _write_json(out_dir / f"{batch_stem}_input.json", batch_input)
            try:
                endpoint_response = _call_model(
                    endpoint=endpoint,
                    model_name=model_name,
                    image_path=Path(batch_input["overlay_path"]),
                    prompt=prompt,
                    timeout_seconds=timeout_seconds,
                )
                raw = _message_text(endpoint_response)
                (out_dir / f"{batch_stem}_raw.txt").write_text(raw, encoding="utf-8")
                _write_json(out_dir / f"{batch_stem}_endpoint_response.json", endpoint_response)
                parsed = normalize_model_review_protocol(
                    subset,
                    enforce_group_review_only_patch(parse_model_review_response(raw)),
                    review_id_map=batch_input["review_id_map"],
                )
                _write_json(out_dir / f"{batch_stem}_parsed.json", parsed)
            except (OSError, TimeoutError, ValueError) as exc:
                next_retry_ids.update(batch_ids)
                _write_json(
                    out_dir / f"{batch_stem}_error.json",
                    {
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                        "case_outcome": "needs_human_review",
                        "group_ids": batch_ids,
                    },
                )
                continue

            omitted_again = {
                str(item.get("region_id") or "")
                for item in parsed.get("protocol_adjustments", [])
                if isinstance(item, dict)
                and item.get("category") == "omitted_group_safe_stopped"
                and str(item.get("region_id") or "") in batch_ids
            }
            next_retry_ids.update(omitted_again)
            for review in parsed.get("group_reviews", []):
                if not isinstance(review, dict):
                    continue
                region_id = str(review.get("region_id") or "")
                if region_id not in batch_ids:
                    continue
                reviews_by_id[region_id] = deepcopy(review)
                if review.get("decision") != "needs_human_review":
                    resolved_ids.add(region_id)
                    next_retry_ids.discard(region_id)
            merged_missing.extend(deepcopy(item) for item in parsed.get("missing", []) if isinstance(item, dict))
            merged_needs_review.extend(
                deepcopy(item) for item in parsed.get("needs_human_review", []) if isinstance(item, dict)
            )
            merged_adjustments.extend(
                deepcopy(item) for item in parsed.get("protocol_adjustments", []) if isinstance(item, dict)
            )
        pending_retry_ids = sorted(next_retry_ids.difference(resolved_ids))

    merged["group_reviews"] = [reviews_by_id[region_id] for region_id in sorted(reviews_by_id)]
    merged["missing"] = merged_missing
    merged["needs_human_review"] = merged_needs_review
    merged["protocol_adjustments"] = [
        item
        for item in merged_adjustments
        if not (
            item.get("category") == "omitted_group_safe_stopped"
            and str(item.get("region_id") or "") in resolved_ids
        )
    ]
    merged["protocol_adjustments"].extend(
        {"category": "omitted_group_followup_resolved", "region_id": region_id}
        for region_id in sorted(resolved_ids)
    )
    summary["resolved_groups"] = len(resolved_ids)
    summary["remaining_needs_human_review"] = len(set(omitted_ids).difference(resolved_ids))
    return merged, summary


def _stage2_group_subset(stage2: dict[str, Any], group_ids: set[str]) -> dict[str, Any]:
    subset = deepcopy(stage2)
    subset_regions: list[dict[str, Any]] = []
    for root in subset.get("regions", []):
        if not isinstance(root, dict):
            continue
        groups = [
            group
            for group in root.get("subregion_groups", [])
            if isinstance(group, dict) and str(group.get("group_id") or "") in group_ids
        ]
        if not groups:
            continue
        root["subregion_groups"] = groups
        subset_regions.append(root)
    subset["regions"] = subset_regions
    return subset


def _graph_revision(stage2: dict[str, Any]) -> str:
    canonical = json.dumps(stage2, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _extract_stage2(source: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    two_stage = source.get("two_stage_understanding")
    if isinstance(two_stage, dict) and isinstance(two_stage.get("stage2_numbering"), dict):
        return two_stage["stage2_numbering"], two_stage
    if isinstance(source.get("stage2_numbering"), dict):
        return source["stage2_numbering"], source
    if isinstance(source.get("regions"), list):
        return source, source
    raise ValueError("input JSON does not contain Stage2 numbering")


def _path_from_source(source: dict[str, Any], key: str) -> Path | None:
    value: Any = source.get(key)
    if key == "compiled_overlay_path" and not value:
        fusion = source.get("fusion")
        value = fusion.get(key) if isinstance(fusion, dict) else None
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def _call_model(
    *,
    endpoint: str,
    model_name: str,
    image_path: Path,
    prompt: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    image_url = "data:image/png;base64," + base64.b64encode(image_path.read_bytes()).decode("ascii")
    payload = {
        "model": model_name,
        "temperature": 0.0,
        "max_tokens": 4096,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": "You audit GUI region overlays. Return one valid JSON object only.",
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            },
        ],
    }
    request = Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=float(timeout_seconds)) as response:
        decoded = json.loads(response.read().decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("model endpoint response must be a JSON object")
    return decoded


def _message_text(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("model endpoint returned no choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str) and content.strip():
        return content.strip()
    if isinstance(content, list):
        text = "\n".join(
            str(item.get("text") or "") for item in content if isinstance(item, dict) and item.get("text")
        ).strip()
        if text:
            return text
    raise ValueError("model endpoint returned no text content")


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a display-only model review over a Learning Mode overlay.")
    parser.add_argument("--stage2-json", type=Path, required=True)
    parser.add_argument("--overlay", type=Path)
    parser.add_argument("--screenshot", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--recorded-response", type=Path)
    parser.add_argument("--adjudication", type=Path)
    parser.add_argument("--endpoint", default="http://127.0.0.1:13240/v1/chat/completions")
    parser.add_argument("--model-name", default="Qwen3VL-8B-Instruct-Q4_K_M.gguf")
    parser.add_argument("--timeout-seconds", type=float, default=240.0)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    report = run_probe(
        stage2_json_path=args.stage2_json,
        out_dir=args.out,
        overlay_path=args.overlay,
        screenshot_path=args.screenshot,
        recorded_response_path=args.recorded_response,
        adjudication_path=args.adjudication,
        endpoint=args.endpoint,
        model_name=args.model_name,
        timeout_seconds=args.timeout_seconds,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(report["report_path"])


if __name__ == "__main__":
    main()
