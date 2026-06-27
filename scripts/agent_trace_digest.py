from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


CONTRACT_VERSION = "agent_trace_digest_v1"
DEFAULT_MAX_FILE_MB = 50.0
DEFAULT_MAX_CANDIDATES = 8
DEFAULT_MAX_TEXT_CHARS = 500

IMAGE_KEY_HINTS = (
    "image_path",
    "overlay_path",
    "output_path",
    "screenshot_path",
    "diff_path",
    "crop_path",
)


def build_digest(
    trace_path: str | Path,
    *,
    allow_large: bool = False,
    max_file_mb: float = DEFAULT_MAX_FILE_MB,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    max_text_chars: int = DEFAULT_MAX_TEXT_CHARS,
) -> dict[str, Any]:
    path = Path(trace_path).expanduser()
    resolved = path.resolve()
    if not resolved.exists() or not resolved.is_file():
        return {
            "contract_version": CONTRACT_VERSION,
            "status": "trace_not_found",
            "trace_path": str(path),
        }

    file_size_mb = resolved.stat().st_size / (1024 * 1024)
    base: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "status": "ok",
        "trace_path": str(resolved),
        "file": resolved.name,
        "file_size_mb": round(file_size_mb, 3),
    }
    if file_size_mb > max_file_mb and not allow_large:
        base.update(
            {
                "status": "skipped_large_trace",
                "advice": (
                    "Trace is too large for safe agent context. Re-run with --allow-large only if needed, "
                    "or inspect the panel trace stages and image artifacts instead of pasting the full JSON."
                ),
            }
        )
        return base

    try:
        raw = json.loads(resolved.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        base.update(
            {
                "status": "json_parse_failed",
                "error": {
                    "code": "json_parse_failed",
                    "details": f"{exc.msg}: line {exc.lineno} column {exc.colno}",
                },
            }
        )
        return base

    if not isinstance(raw, dict):
        base.update({"status": "unsupported_trace_shape", "raw_type": type(raw).__name__})
        return base

    trace = raw.get("result") if isinstance(raw.get("result"), dict) else raw
    request = _first_dict(raw.get("request"), trace.get("request")) or {}
    plan = _first_dict(trace.get("recognition_plan"), trace) or {}

    digest = {
        **base,
        "success": raw.get("success", trace.get("success")),
        "message": _compact_text(raw.get("message") or trace.get("message"), max_text_chars),
        "error": _compact_error(raw.get("error") or trace.get("error"), max_text_chars),
        "contract": trace.get("contract_version") or request.get("task") or raw.get("contract_version"),
        "request": _extract_request(request, trace, max_text_chars),
        "timings": _extract_timings(trace),
        "model_io": _extract_model_io(raw, trace, plan, max_text_chars),
        "screen": _extract_screen(trace, plan, max_text_chars),
        "path_graph": _extract_path_graph(trace, plan, max_candidates, max_text_chars),
        "candidates": _extract_candidates(trace, plan, max_candidates, max_text_chars),
        "vista_grounding": _extract_vista_grounding(trace, plan, max_text_chars),
        "gate": _extract_gate(trace, plan, max_candidates, max_text_chars),
        "action": _extract_action(trace, plan, max_text_chars),
        "images": _collect_image_paths(raw, limit=30),
        "agent_handoff": _extract_agent_handoff(trace, max_text_chars),
    }
    digest["summary"] = _make_summary(digest)
    return digest


def format_text(digest: dict[str, Any]) -> str:
    lines = [
        f"Trace digest: {digest.get('file') or digest.get('trace_path')}",
        f"status={digest.get('status')} success={digest.get('success')} contract={digest.get('contract')}",
    ]
    request = digest.get("request") if isinstance(digest.get("request"), dict) else {}
    if request:
        lines.append(
            "request: "
            + ", ".join(
                part
                for part in [
                    f"goal={request.get('goal')}" if request.get("goal") else "",
                    f"app={request.get('app_name')}" if request.get("app_name") else "",
                    f"state={request.get('state_hint')}" if request.get("state_hint") else "",
                    f"dry_run={request.get('dry_run')}" if request.get("dry_run") is not None else "",
                ]
                if part
            )
        )
    screen = digest.get("screen") if isinstance(digest.get("screen"), dict) else {}
    if screen:
        lines.append(f"screen: {screen.get('state_guess') or ''} {screen.get('summary') or ''}".strip())
    vista = digest.get("vista_grounding") if isinstance(digest.get("vista_grounding"), dict) else {}
    if vista:
        lines.append(
            f"vista: policy={vista.get('roi_policy')} source={vista.get('roi_source')} "
            f"tier={vista.get('fallback_tier')} processed={vista.get('processed_size')} point={vista.get('point')}"
        )
    candidates = digest.get("candidates") if isinstance(digest.get("candidates"), dict) else {}
    if candidates:
        lines.append(
            f"candidates: count={candidates.get('count')} recommended={candidates.get('recommended_candidate_id')} "
            f"margin={candidates.get('margin_to_second')}"
        )
        for item in candidates.get("top") or []:
            lines.append(
                "  - "
                + " | ".join(
                    str(part)
                    for part in [
                        item.get("id"),
                        item.get("label"),
                        item.get("role"),
                        f"score={item.get('score')}" if item.get("score") is not None else "",
                        f"risk={item.get('risk_class')}" if item.get("risk_class") else "",
                        f"point={item.get('click_point')}" if item.get("click_point") else "",
                    ]
                    if part not in (None, "")
                )
            )
    gate = digest.get("gate") if isinstance(digest.get("gate"), dict) else {}
    if gate:
        lines.append(f"gate: allowed={gate.get('allowed')} reason={gate.get('reason')}")
    action = digest.get("action") if isinstance(digest.get("action"), dict) else {}
    if action:
        lines.append(f"action: executed={action.get('executed')} verified={action.get('verified')} point={action.get('point')}")
    images = digest.get("images") if isinstance(digest.get("images"), list) else []
    if images:
        lines.append("images:")
        for image in images[:12]:
            lines.append(f"  - {image.get('key')}: {image.get('path')}")
    error = digest.get("error")
    if error:
        lines.append(f"error: {error}")
    return "\n".join(lines)


def _extract_request(request: dict[str, Any], trace: dict[str, Any], max_chars: int) -> dict[str, Any]:
    return _drop_empty(
        {
            "goal": _compact_text(request.get("goal") or trace.get("goal"), max_chars),
            "app_name": request.get("app_name") or trace.get("app_name"),
            "state_hint": _compact_text(request.get("state_hint") or trace.get("state_hint"), max_chars),
            "provider_mode": request.get("provider_mode") or trace.get("provider_mode"),
            "model_profile": request.get("model_profile") or request.get("model_profile_id"),
            "dry_run": request.get("dry_run") if "dry_run" in request else trace.get("dry_run"),
            "capture_live": request.get("capture_live") if "capture_live" in request else trace.get("capture_live"),
            "approved_plan_id": request.get("approved_plan_id") or trace.get("approved_plan_id"),
        }
    )


def _extract_timings(trace: dict[str, Any]) -> dict[str, Any]:
    timings = _first_dict(trace.get("timings"), trace.get("runtime_timing_v1")) or {}
    steps = timings.get("steps") if isinstance(timings.get("steps"), list) else []
    return _drop_empty(
        {
            "total_ms": timings.get("total_ms"),
            "steps": [
                _drop_empty(
                    {
                        "name": step.get("name"),
                        "elapsed_ms": step.get("elapsed_ms") or step.get("duration_ms"),
                    }
                )
                for step in steps[:20]
                if isinstance(step, dict)
            ],
        }
    )


def _extract_model_io(raw: dict[str, Any], trace: dict[str, Any], plan: dict[str, Any], max_chars: int) -> dict[str, Any]:
    model_io = _first_dict(
        trace.get("model_io"),
        plan.get("model_io"),
        raw.get("model_io"),
        _get_dict(trace, "degraded_reason", "model_io"),
        _get_dict(trace, "raw_refs", "model_io"),
    )
    if not model_io:
        return {}
    attempts = model_io.get("attempts") if isinstance(model_io.get("attempts"), list) else []
    return _drop_empty(
        {
            "status": model_io.get("status"),
            "provider": model_io.get("provider") or model_io.get("provider_mode"),
            "model": model_io.get("model_name") or model_io.get("model"),
            "attempt_count": model_io.get("attempt_count") or len(attempts) or None,
            "parse_error": _compact_text(model_io.get("parse_error") or model_io.get("last_parse_error"), max_chars),
            "raw_text_preview": _compact_text(
                model_io.get("raw_text") or model_io.get("raw_response") or _last_attempt_value(attempts, "raw_text"), max_chars
            ),
            "prompt_preview": _compact_text(model_io.get("prompt") or model_io.get("input_prompt"), max_chars),
        }
    )


def _extract_screen(trace: dict[str, Any], plan: dict[str, Any], max_chars: int) -> dict[str, Any]:
    screen_map = _first_dict(trace.get("screen_map"), plan.get("screen_map"), trace.get("parse_result")) or {}
    summary = _first_dict(screen_map.get("summary"), trace.get("summary")) or {}
    return _drop_empty(
        {
            "summary": _compact_text(
                trace.get("screen_summary")
                or screen_map.get("screen_summary")
                or summary.get("screen_summary")
                or summary.get("page_summary"),
                max_chars,
            ),
            "state_guess": _compact_text(trace.get("state_guess") or screen_map.get("state_guess") or summary.get("state_guess"), max_chars),
            "sections_count": _count_list(screen_map.get("sections")),
            "candidate_count": summary.get("candidate_count") or _count_list(screen_map.get("candidates")),
        }
    )


def _extract_path_graph(trace: dict[str, Any], plan: dict[str, Any], max_candidates: int, max_chars: int) -> dict[str, Any]:
    path_graph = _first_dict(trace.get("path_graph"), trace.get("path_map"), plan.get("path_graph"), plan.get("path_map")) or {}
    recall = _first_dict(trace.get("path_graph_recall"), plan.get("path_graph_recall")) or {}
    candidates = _first_list(path_graph.get("candidates"), recall.get("candidates"), path_graph.get("nodes")) or []
    summary = _first_dict(path_graph.get("summary"), recall.get("summary")) or {}
    return _drop_empty(
        {
            "state_id": path_graph.get("state_id") or _get_dict(recall, "state_match").get("state_id"),
            "status": path_graph.get("status") or recall.get("status"),
            "candidate_count": summary.get("candidate_count") or summary.get("recalled_count") or len(candidates) or None,
            "sections": _summarize_sections(path_graph.get("sections"), max_chars),
            "top": _summarize_candidates(candidates, max_candidates, max_chars),
        }
    )


def _extract_candidates(trace: dict[str, Any], plan: dict[str, Any], max_candidates: int, max_chars: int) -> dict[str, Any]:
    candidate_result = _first_dict(trace.get("candidate_result"), plan.get("candidate_result")) or {}
    candidates = _first_list(
        candidate_result.get("candidates"),
        trace.get("candidates"),
        plan.get("candidates"),
        trace.get("screen_map", {}).get("candidates") if isinstance(trace.get("screen_map"), dict) else None,
    ) or []
    top = _summarize_candidates(candidates, max_candidates, max_chars)
    return _drop_empty(
        {
            "count": len(candidates) if candidates else candidate_result.get("candidate_count"),
            "recommended_candidate_id": candidate_result.get("recommended_candidate_id")
            or _get_dict(candidate_result, "recommendation").get("candidate_id")
            or _candidate_id(_first_dict(candidate_result.get("recommended_candidate")) or {}),
            "margin_to_second": candidate_result.get("margin_to_second"),
            "top": top,
        }
    )


def _extract_vista_grounding(trace: dict[str, Any], plan: dict[str, Any], max_chars: int) -> dict[str, Any]:
    parse_result = _first_dict(trace.get("parse_result"), plan.get("parse_result")) or {}
    vista = _first_dict(
        parse_result.get("vista_point_grounding"),
        trace.get("vista_point_grounding"),
        plan.get("vista_point_grounding"),
    ) or {}
    if not vista:
        execution_path = _first_dict(trace.get("execution_path"), plan.get("execution_path")) or {}
        return _drop_empty(
            {
                "roi_policy": execution_path.get("vista_roi_policy"),
                "roi_source": execution_path.get("vista_roi_source"),
                "fallback_tier": execution_path.get("vista_roi_fallback_tier"),
                "processed_size": execution_path.get("vista_processed_size"),
                "crop_bounds_original": execution_path.get("vista_crop_bounds_original"),
            }
        )
    preprocess = vista.get("image_preprocess") if isinstance(vista.get("image_preprocess"), dict) else {}
    return _drop_empty(
        {
            "status": vista.get("status"),
            "stage": vista.get("vista_stage"),
            "roi_policy": preprocess.get("roi_policy"),
            "roi_source": preprocess.get("roi_source"),
            "fallback_tier": preprocess.get("fallback_tier"),
            "processed_size": preprocess.get("processed_size"),
            "crop_bounds_original": preprocess.get("crop_bounds_original"),
            "processed_image_path": preprocess.get("processed_image_path"),
            "point": vista.get("point"),
            "processed_point": vista.get("processed_point"),
            "raw_text_preview": _compact_text(vista.get("raw_text"), max_chars),
        }
    )


def _extract_gate(trace: dict[str, Any], plan: dict[str, Any], max_candidates: int, max_chars: int) -> dict[str, Any]:
    gate = _first_dict(trace.get("pre_click_decision"), plan.get("pre_click_decision"), trace.get("gate"), plan.get("gate")) or {}
    decisions = _first_list(gate.get("candidate_decisions"), gate.get("decisions")) or []
    selected = _first_dict(gate.get("selected_candidate"), gate.get("candidate")) or {}
    return _drop_empty(
        {
            "allowed": gate.get("allowed"),
            "reason": _compact_text(gate.get("reason") or gate.get("summary"), max_chars),
            "reasons": _compact_list(gate.get("reasons"), max_items=8, max_chars=max_chars),
            "selected_candidate_id": gate.get("selected_candidate_id") or _candidate_id(selected),
            "selected_click_point": gate.get("selected_click_point") or gate.get("click_point") or selected.get("click_point"),
            "candidate_decisions": [
                _drop_empty(
                    {
                        "candidate_id": item.get("candidate_id") or item.get("id"),
                        "allowed": item.get("allowed"),
                        "risk_class": item.get("risk_class"),
                        "reason": _compact_text(item.get("reason") or item.get("summary"), max_chars),
                        "reasons": _compact_list(item.get("reasons"), max_items=4, max_chars=max_chars),
                    }
                )
                for item in decisions[:max_candidates]
                if isinstance(item, dict)
            ],
        }
    )


def _extract_action(trace: dict[str, Any], plan: dict[str, Any], max_chars: int) -> dict[str, Any]:
    verification = _first_dict(trace.get("verification"), trace.get("post_click_verification"), plan.get("verification")) or {}
    agent_step = _first_dict(trace.get("agent_step_result"), trace.get("result")) or {}
    point = trace.get("point") or trace.get("click_point") or _get_dict(trace, "executed_action").get("point")
    return _drop_empty(
        {
            "executed": trace.get("action_executed") if "action_executed" in trace else agent_step.get("action_executed"),
            "verified": trace.get("verified") if "verified" in trace else verification.get("verified"),
            "point": point,
            "approved_plan_id": trace.get("approved_plan_id"),
            "failure_reason": _compact_text(trace.get("failure_reason") or agent_step.get("failure_reason"), max_chars),
        }
    )


def _extract_agent_handoff(trace: dict[str, Any], max_chars: int) -> dict[str, Any]:
    handoff = _first_dict(trace.get("agent_step_result"), trace.get("agent_guidance"), trace.get("next_agent_action")) or {}
    return _drop_empty(
        {
            "status": handoff.get("status"),
            "next_action": _compact_text(handoff.get("next_action") or handoff.get("next_agent_action"), max_chars),
            "summary": _compact_text(handoff.get("summary"), max_chars),
        }
    )


def _collect_image_paths(value: Any, *, limit: int, key_path: str = "", depth: int = 0) -> list[dict[str, str]]:
    if depth > 8 or limit <= 0:
        return []
    found: list[dict[str, str]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            next_key = f"{key_path}.{key}" if key_path else str(key)
            if isinstance(item, str) and _looks_like_image_key(str(key), item):
                found.append({"key": next_key, "path": item})
                if len(found) >= limit:
                    return found
            elif isinstance(item, (dict, list)):
                found.extend(_collect_image_paths(item, limit=limit - len(found), key_path=next_key, depth=depth + 1))
                if len(found) >= limit:
                    return found
    elif isinstance(value, list):
        for index, item in enumerate(value[:40]):
            found.extend(_collect_image_paths(item, limit=limit - len(found), key_path=f"{key_path}[{index}]", depth=depth + 1))
            if len(found) >= limit:
                return found
    return found


def _looks_like_image_key(key: str, value: str) -> bool:
    lowered_key = key.lower()
    lowered_value = value.lower()
    return any(hint in lowered_key for hint in IMAGE_KEY_HINTS) and lowered_value.endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp"))


def _summarize_sections(sections: Any, max_chars: int) -> list[dict[str, Any]]:
    if not isinstance(sections, list):
        return []
    output = []
    for section in sections[:12]:
        if not isinstance(section, dict):
            continue
        output.append(
            _drop_empty(
                {
                    "id": section.get("section_id") or section.get("id"),
                    "label": _compact_text(section.get("label") or section.get("name"), max_chars),
                    "role": section.get("role"),
                    "bbox": section.get("bbox"),
                    "count": section.get("candidate_count") or _count_list(section.get("candidates")),
                }
            )
        )
    return output


def _summarize_candidates(candidates: Any, limit: int, max_chars: int) -> list[dict[str, Any]]:
    if not isinstance(candidates, list):
        return []
    output = []
    for item in candidates[:limit]:
        if not isinstance(item, dict):
            continue
        provider_matches = item.get("provider_matches") if isinstance(item.get("provider_matches"), dict) else {}
        policy = item.get("interaction_policy") if isinstance(item.get("interaction_policy"), dict) else {}
        output.append(
            _drop_empty(
                {
                    "id": _candidate_id(item),
                    "label": _compact_text(item.get("label") or item.get("name") or item.get("text"), max_chars),
                    "role": item.get("role") or item.get("type"),
                    "score": item.get("score") or item.get("total_score"),
                    "confidence": item.get("confidence"),
                    "risk_class": item.get("risk_class") or policy.get("risk_class"),
                    "allowed": policy.get("allowed"),
                    "bbox": item.get("bbox") or item.get("semantic_bbox") or item.get("geometry"),
                    "click_point": item.get("click_point") or item.get("point"),
                    "section": item.get("section_id") or item.get("region_id"),
                    "source": item.get("source") or provider_matches.get("source"),
                }
            )
        )
    return output


def _make_summary(digest: dict[str, Any]) -> dict[str, Any]:
    gate = digest.get("gate") if isinstance(digest.get("gate"), dict) else {}
    candidates = digest.get("candidates") if isinstance(digest.get("candidates"), dict) else {}
    action = digest.get("action") if isinstance(digest.get("action"), dict) else {}
    return _drop_empty(
        {
            "gate_allowed": gate.get("allowed"),
            "gate_reason": gate.get("reason"),
            "recommended_candidate_id": candidates.get("recommended_candidate_id"),
            "candidate_count": candidates.get("count"),
            "action_executed": action.get("executed"),
            "post_click_verified": action.get("verified"),
            "image_count": len(digest.get("images") or []),
        }
    )


def _compact_error(value: Any, max_chars: int) -> Any:
    if not isinstance(value, dict):
        return _compact_text(value, max_chars)
    return _drop_empty(
        {
            "code": value.get("code"),
            "details": _compact_text(value.get("details") or value.get("message"), max_chars),
        }
    )


def _compact_list(value: Any, *, max_items: int, max_chars: int) -> list[Any]:
    if not isinstance(value, list):
        return []
    return [_compact_text(item, max_chars) if not isinstance(item, dict) else item for item in value[:max_items]]


def _compact_text(value: Any, max_chars: int) -> str | None:
    if value in (None, ""):
        return None
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 20].rstrip() + f"... [truncated {len(text) - max_chars + 20} chars]"


def _first_dict(*values: Any) -> dict[str, Any] | None:
    for value in values:
        if isinstance(value, dict):
            return value
    return None


def _first_list(*values: Any) -> list[Any] | None:
    for value in values:
        if isinstance(value, list):
            return value
    return None


def _get_dict(value: Any, *keys: str) -> dict[str, Any]:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return {}
        current = current.get(key)
    return current if isinstance(current, dict) else {}


def _last_attempt_value(attempts: list[Any], key: str) -> Any:
    for attempt in reversed(attempts):
        if isinstance(attempt, dict) and attempt.get(key):
            return attempt[key]
    return None


def _count_list(value: Any) -> int | None:
    return len(value) if isinstance(value, list) else None


def _candidate_id(item: dict[str, Any]) -> Any:
    return item.get("candidate_id") or item.get("id") or item.get("element_id")


def _drop_empty(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item not in (None, "", [], {})}


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize a long runtime trace into an agent-readable digest.")
    parser.add_argument("trace_path", help="Path to a trace JSON file.")
    parser.add_argument("--format", choices=["json", "text"], default="json")
    parser.add_argument("--allow-large", action="store_true", help="Parse traces larger than the default safety limit.")
    parser.add_argument("--max-file-mb", type=float, default=DEFAULT_MAX_FILE_MB)
    parser.add_argument("--max-candidates", type=int, default=DEFAULT_MAX_CANDIDATES)
    parser.add_argument("--max-text-chars", type=int, default=DEFAULT_MAX_TEXT_CHARS)
    args = parser.parse_args()

    digest = build_digest(
        args.trace_path,
        allow_large=args.allow_large,
        max_file_mb=args.max_file_mb,
        max_candidates=args.max_candidates,
        max_text_chars=args.max_text_chars,
    )
    if args.format == "text":
        print(format_text(digest))
    else:
        print(json.dumps(digest, ensure_ascii=False, indent=2))
    return 0 if digest.get("status") in {"ok", "skipped_large_trace"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
