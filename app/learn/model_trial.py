from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from PIL import Image

from app.core.model_server import profile_for_stage
from app.vision.factory import VisionProviderFactory
from app.vision.local_provider import LocalVisionProvider
from app.vision.schemas import VisionAnalyzeRequest

LEARNING_MODEL_TRIAL_CONTRACT = "learning_model_trial_v1"
LEARNING_MODEL_ATTEMPT_CONTRACT = "learning_model_trial_attempt_v1"
LEARNING_TEMPLATE_DRAFT_CONTRACT = "learning_template_draft_v1"

DEFAULT_REQUIRED_SECTIONS = [
    "workflow_draft.states",
    "workflow_draft.action_templates",
    "interface_draft.regions",
    "safety",
]


def build_learning_model_trial(
    *,
    image_path: str | Path,
    app_name: str = "unknown_app",
    state_hint: str = "",
    goal: str = "learn a reusable UI workflow template from this screen",
    max_attempts: int = 3,
    target_contract: dict[str, Any] | None = None,
    observation_evidence: dict[str, Any] | None = None,
    learning_parameter_overrides: dict[str, Any] | None = None,
    validation_mode: str = "strict_blind",
    model_client: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if validation_mode not in {"strict_blind", "standard"}:
        raise ValueError(f"unsupported learning validation_mode: {validation_mode}")
    source_image = Path(image_path)
    if not source_image.exists():
        raise FileNotFoundError(str(source_image))
    with Image.open(source_image) as image:
        image_size = {"width": image.width, "height": image.height}

    target = _target_contract(target_contract)
    if validation_mode == "strict_blind":
        target = _strict_blind_target(target)
    base_parameters = _merge_parameters(_default_learning_parameters(), learning_parameter_overrides)
    evidence = observation_evidence or {}
    attempts: list[dict[str, Any]] = []
    best_attempt: dict[str, Any] | None = None
    best_score = -1.0
    current_parameters = dict(base_parameters)
    max_attempts = max(1, min(5, int(max_attempts)))
    scored_draft_count = 0

    for index in range(max_attempts):
        current_parameters = _parameters_for_attempt(current_parameters, scored_draft_count=scored_draft_count)
        prompt_context_hidden = validation_mode == "strict_blind"
        prompt_target = _prompt_visible_target(target, validation_mode)
        prompt_evidence = {} if prompt_context_hidden else evidence
        prompt_app_name = "unknown_app" if prompt_context_hidden else app_name
        prompt_state_hint = "" if prompt_context_hidden else state_hint
        prompt_goal = "learn a reusable UI workflow template from this screenshot" if prompt_context_hidden else goal
        request = {
            "contract_version": "learning_model_request_v1",
            "image_path": str(source_image),
            "app_name": prompt_app_name,
            "state_hint": prompt_state_hint,
            "goal": prompt_goal,
            "task": "learn_template_draft",
            "validation_mode": validation_mode,
            "learning_parameters": dict(current_parameters),
            "learning_trial_context": {
                "contract_version": "learning_trial_context_v1",
                "target_contract": prompt_target,
                "observation_evidence": prompt_evidence,
                "learning_parameters": dict(current_parameters),
                "prompt_context_hidden": prompt_context_hidden,
            },
        }
        try:
            run = (model_client or _call_observe_learning_model)(request)
        except Exception as exc:
            run = {
                "contract_version": "learning_model_run_v1",
                "status": "model_error",
                "error": str(exc),
                "diagnostics": getattr(exc, "diagnostics", None),
            }
        model_json = run.get("model_json") if isinstance(run, dict) else None
        quality_score_applicable = isinstance(model_json, dict)
        score_report = score_learning_template_draft(model_json if isinstance(model_json, dict) else {}, target)
        if quality_score_applicable:
            score_report["parameter_feedback"].extend(_feedback_from_model_run(run, current_parameters))
        else:
            score_report["parameter_feedback"] = _feedback_from_model_run(run, current_parameters)
        attempt = {
            "contract_version": LEARNING_MODEL_ATTEMPT_CONTRACT,
            "attempt_index": index,
            "learning_parameters": dict(current_parameters),
            "model_run": run,
            "result_kind": _attempt_result_kind(run, model_json),
            "quality_score_applicable": quality_score_applicable,
            "quality_score_ratio": score_report["overall_score"]["score_ratio"] if quality_score_applicable else None,
            "quality_score_percent": score_report["overall_score"]["score_percent"] if quality_score_applicable else None,
            "score_report": score_report,
            "score_ratio": score_report["overall_score"]["score_ratio"],
            "score_percent": score_report["overall_score"]["score_percent"],
            "passed": score_report["overall_score"]["passed"],
            "draft_result": model_json if isinstance(model_json, dict) else {},
        }
        attempts.append(attempt)
        if quality_score_applicable:
            scored_draft_count += 1
        if attempt["score_ratio"] > best_score:
            best_score = attempt["score_ratio"]
            best_attempt = attempt
        if attempt["passed"]:
            break
        current_parameters = _next_parameters_from_feedback(
            current_parameters,
            score_report.get("parameter_feedback") or [],
        )

    best = best_attempt or attempts[-1]
    return {
        "contract_version": LEARNING_MODEL_TRIAL_CONTRACT,
        "status": "passed" if best["passed"] else "needs_more_learning",
        "image_path": str(source_image),
        "image_size": image_size,
        "app_name": app_name,
        "state_hint": state_hint,
        "validation_mode": validation_mode,
        "target_score_ratio": _alignment_threshold(target),
        "best_attempt_index": best["attempt_index"],
        "best_score_ratio": best["score_ratio"],
        "best_score_percent": best["score_percent"],
        "attempt_count": len(attempts),
        "attempts": attempts,
        "best_learning_draft": best["draft_result"],
        "target_contract": target,
        "safety": {
            "real_clicks_performed": 0,
            "artifact_posthoc_optimization_allowed": False,
            "promotion_allowed": False,
            "final_submit_blocked": True,
        },
    }


def score_learning_template_draft(payload: dict[str, Any], target_contract: dict[str, Any] | None = None) -> dict[str, Any]:
    target = _target_contract(target_contract)
    threshold = _alignment_threshold(target)
    checks: list[dict[str, Any]] = []
    contract_score = _score_contract(payload, target, checks)
    section_score = _score_sections(payload, target, checks)
    safety_score = _score_safety(payload, checks)
    action_score = _score_expected_actions(payload, target, checks)
    evidence_score = _score_expected_visible_text(payload, target, checks)
    template_score_report = _score_reference_template_similarity(payload, target, checks)
    template_score = template_score_report["score_ratio"]
    if target.get("reference_template"):
        score_ratio = round(
            (template_score * 0.7)
            + (safety_score * 0.2)
            + (contract_score * 0.05)
            + (section_score * 0.05),
            4,
        )
        reason = "passed" if score_ratio >= threshold else "template_similarity_below_threshold"
    else:
        score_ratio = round(
            (contract_score * 0.2)
            + (section_score * 0.25)
            + (safety_score * 0.3)
            + (action_score * 0.2)
            + (evidence_score * 0.05),
            4,
        )
        reason = "passed" if score_ratio >= threshold else "below_threshold_or_hard_safety_error"
    hard_errors = [item for item in checks if item.get("severity") == "hard_error" and not item.get("passed")]
    passed = score_ratio >= threshold and not hard_errors
    human_adjudication = _human_adjudication(target)
    return {
        "contract_version": "learning_template_draft_score_v1",
        "metric_name": "draft_reference_alignment_score",
        "metric_aliases": ["template_similarity_score"],
        "forbidden_interpretations": [
            "model_accuracy",
            "click_success_rate",
            "gate_success_rate",
            "seek_e2e_success_rate",
        ],
        "target_contract_version": target["contract_version"],
        "checks": checks,
        "section_scores": {
            "contract": contract_score,
            "sections": section_score,
            "safety": safety_score,
            "actions": action_score,
            "evidence": evidence_score,
            "template_similarity": template_score,
        },
        "template_similarity": template_score_report,
        "template_similarity_score": template_score_report,
        "draft_reference_alignment_score": {
            "contract_version": "draft_reference_alignment_score_v1",
            "score_ratio": score_ratio,
            "score_percent": round(score_ratio * 100, 2),
            "passed": passed,
            "threshold": threshold,
            "reason": "passed" if passed else reason,
        },
        "human_adjudication": human_adjudication,
        "overall_score": {
            "contract_version": "learning_overall_score_v1",
            "score_ratio": score_ratio,
            "score_percent": round(score_ratio * 100, 2),
            "passed": passed,
            "metric_name": "draft_reference_alignment_score",
            "draft_reference_alignment_threshold": threshold,
            "legacy_direct_use_accuracy_threshold": threshold,
            "reason": "passed" if passed else reason,
        },
        "parameter_feedback": _feedback_from_checks(checks, score_ratio, target),
    }


def _call_observe_learning_model(request: dict[str, Any]) -> dict[str, Any]:
    parameters = request["learning_parameters"]
    provider = _learning_provider_from_parameters(parameters)
    timeout_seconds = request["learning_parameters"].get("timeout_seconds")
    if timeout_seconds is not None and hasattr(provider, "timeout_seconds"):
        provider.timeout_seconds = max(1.0, min(600.0, float(timeout_seconds)))
    response = provider.analyze(
        VisionAnalyzeRequest(
            image_path=str(request["image_path"]),
            task="learn_template_draft",
            app_name=str(request.get("app_name") or "unknown_app"),
            goal=str(request.get("goal") or ""),
            state_hint=str(request.get("state_hint") or ""),
            provider_mode="local_understanding",
            metadata={
                "learning_trial_context": request["learning_trial_context"],
                "max_output_tokens": request["learning_parameters"].get("max_output_tokens"),
                "temperature": request["learning_parameters"].get("temperature"),
                "learning_image_max_edge": request["learning_parameters"].get("learning_image_max_edge"),
            },
        )
    )
    raw_response = response.raw_response or {}
    return {
        "contract_version": "learning_model_run_v1",
        "status": "success",
        "provider": response.provider,
        "raw_text": response.raw_text,
        "model_json": raw_response.get("model_json") if isinstance(raw_response, dict) else None,
        "raw_response": raw_response,
    }


def _learning_provider_from_parameters(parameters: dict[str, Any]):
    profile_id = parameters.get("learning_model_profile_id")
    if not profile_id:
        return VisionProviderFactory.create("local_understanding")
    profile = profile_for_stage("observe", str(profile_id))
    if str(profile.get("provider_mode") or "") == "local_understanding":
        return LocalVisionProvider(
            endpoint=profile.get("endpoint"),
            model_name=profile.get("model_name"),
            timeout_seconds=float(parameters.get("timeout_seconds") or 120),
        )
    return VisionProviderFactory.create(profile.get("provider_mode") or "local_understanding")


def _attempt_result_kind(run: dict[str, Any], model_json: Any) -> str:
    if isinstance(model_json, dict):
        return "draft_scored"
    if isinstance(run, dict) and run.get("status") == "model_error":
        return "model_error_no_draft"
    return "no_draft_available"


def _target_contract(target_contract: dict[str, Any] | None) -> dict[str, Any]:
    target = dict(target_contract or {})
    target.setdefault("contract_version", "learning_template_target_v1")
    target.setdefault("required_top_level_fields", [
        "contract_version",
        "image_size",
        "learning_source",
        "screen_summary",
        "state_guess",
        "workflow_draft",
        "interface_draft",
        "safety",
    ])
    target.setdefault("required_sections", list(DEFAULT_REQUIRED_SECTIONS))
    target.setdefault("expected_actions", [])
    target.setdefault("expected_visible_text", [])
    target.setdefault("reference_template", None)
    target.setdefault("require_expected_actions_for_pass", False)
    threshold = target.get("draft_reference_alignment_threshold", target.get("direct_use_accuracy_threshold", 0.9))
    target["draft_reference_alignment_threshold"] = float(threshold)
    target.setdefault("direct_use_accuracy_threshold", float(threshold))
    target.setdefault("human_adjudication", None)
    return target


def _alignment_threshold(target: dict[str, Any]) -> float:
    return float(target.get("draft_reference_alignment_threshold", target.get("direct_use_accuracy_threshold", 0.9)) or 0.9)


def _human_adjudication(target: dict[str, Any]) -> dict[str, Any]:
    raw = target.get("human_adjudication")
    if not isinstance(raw, dict):
        return {
            "contract_version": "learning_human_adjudication_v1",
            "status": "not_adjudicated",
            "scope": None,
            "rationale": None,
        }
    status = str(raw.get("status") or "adjudicated").strip() or "adjudicated"
    scope = str(raw.get("scope") or "").strip() or None
    return {
        "contract_version": "learning_human_adjudication_v1",
        "status": status,
        "scope": scope,
        "rationale": str(raw.get("rationale") or "").strip() or None,
        "limits": str(raw.get("limits") or "").strip() or None,
    }


def _strict_blind_target(target: dict[str, Any]) -> dict[str, Any]:
    strict = dict(target)
    strict["require_expected_actions_for_pass"] = True
    threshold = max(0.9, _alignment_threshold(strict))
    strict["draft_reference_alignment_threshold"] = threshold
    strict["direct_use_accuracy_threshold"] = threshold
    return strict


def _prompt_visible_target(target: dict[str, Any], validation_mode: str) -> dict[str, Any]:
    if validation_mode != "strict_blind":
        return dict(target)
    return {
        "contract_version": target["contract_version"],
        "required_top_level_fields": list(target.get("required_top_level_fields") or []),
        "required_sections": list(target.get("required_sections") or []),
        "draft_reference_alignment_threshold": _alignment_threshold(target),
        "legacy_direct_use_accuracy_threshold": _alignment_threshold(target),
    }


def _default_learning_parameters() -> dict[str, Any]:
    return {
        "contract_version": "learning_parameters_v1",
        "learning_model_profile_id": "qwen3_vl_8b_q4_k_m",
        "temperature": 0.0,
        "max_output_tokens": 768,
        "timeout_seconds": 180,
        "learning_image_max_edge": 256,
        "prompt_detail_mode": "compact_contract",
        "draft_reference_alignment_threshold": 0.9,
        "direct_use_accuracy_threshold": 0.9,
        "artifact_posthoc_optimization_allowed": False,
        "allow_fast_profile_fallback": False,
    }


def _merge_parameters(base: dict[str, Any], overrides: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(base)
    for key, value in (overrides or {}).items():
        if value is not None:
            merged[key] = value
    return merged


def _parameters_for_attempt(parameters: dict[str, Any], *, scored_draft_count: int = 1) -> dict[str, Any]:
    next_parameters = dict(parameters)
    if scored_draft_count <= 0:
        return next_parameters
    if scored_draft_count >= 1:
        next_parameters["prompt_detail_mode"] = "enumerate_sections_then_json"
        next_parameters["max_output_tokens"] = max(3072, int(next_parameters.get("max_output_tokens") or 2048))
    if scored_draft_count >= 2:
        next_parameters["prompt_detail_mode"] = "strict_required_sections"
        next_parameters["max_output_tokens"] = max(4096, int(next_parameters.get("max_output_tokens") or 3072))
    return next_parameters


def _next_parameters_from_feedback(parameters: dict[str, Any], feedback: list[dict[str, Any]]) -> dict[str, Any]:
    next_parameters = dict(parameters)
    for item in feedback:
        if item.get("target") == "prompt_detail_mode":
            next_parameters["prompt_detail_mode"] = item.get("suggested_value") or "enumerate_sections_then_json"
        if item.get("target") == "max_output_tokens":
            next_parameters["max_output_tokens"] = max(
                int(next_parameters.get("max_output_tokens") or 2048),
                int(item.get("suggested_value") or 3072),
            )
        if item.get("target") == "learning_model_profile_id":
            next_parameters["learning_model_profile_id"] = item.get("suggested_value") or next_parameters.get("learning_model_profile_id")
        if item.get("target") == "timeout_seconds":
            next_parameters["timeout_seconds"] = max(
                int(next_parameters.get("timeout_seconds") or 120),
                int(item.get("suggested_value") or 120),
            )
        if item.get("target") == "learning_image_max_edge":
            next_parameters["learning_image_max_edge"] = min(
                int(next_parameters.get("learning_image_max_edge") or 384),
                int(item.get("suggested_value") or 256),
            )
    return next_parameters


def _feedback_from_model_run(run: dict[str, Any], parameters: dict[str, Any]) -> list[dict[str, Any]]:
    if run.get("status") != "model_error":
        return []
    error = str(run.get("error") or "").lower()
    feedback: list[dict[str, Any]] = []
    if "timed out" in error or "timeout" in error:
        if parameters.get("allow_fast_profile_fallback") is True and parameters.get("learning_model_profile_id") != "qwen3_vl_4b_q4_k_m":
            feedback.append({
                "target": "learning_model_profile_id",
                "suggested_value": "qwen3_vl_4b_q4_k_m",
                "reason": "vision_model_timeout_try_fast_learning_profile",
            })
        feedback.append({
            "target": "learning_image_max_edge",
            "suggested_value": 256,
            "reason": "vision_model_timeout_reduce_learning_image_size",
        })
        feedback.append({
            "target": "timeout_seconds",
            "suggested_value": 90,
            "reason": "vision_model_timeout_allow_one_fast_profile_attempt",
        })
    return feedback


def _score_contract(payload: dict[str, Any], target: dict[str, Any], checks: list[dict[str, Any]]) -> float:
    required = list(target.get("required_top_level_fields") or [])
    if not required:
        return 1.0
    matched = 0
    for field in required:
        exists = field in payload and payload.get(field) not in (None, "")
        if exists:
            matched += 1
        checks.append({"check_id": f"top_level.{field}", "passed": exists, "severity": "error"})
    contract_ok = payload.get("contract_version") == LEARNING_TEMPLATE_DRAFT_CONTRACT
    checks.append({"check_id": "contract_version.learning_template_draft_v1", "passed": contract_ok, "severity": "error"})
    return round(((matched / len(required)) + (1.0 if contract_ok else 0.0)) / 2.0, 4)


def _score_sections(payload: dict[str, Any], target: dict[str, Any], checks: list[dict[str, Any]]) -> float:
    sections = list(target.get("required_sections") or [])
    if not sections:
        return 1.0
    matched = 0
    for section in sections:
        value = _path_get(payload, section)
        passed = _section_has_content(value)
        if passed:
            matched += 1
        checks.append({"check_id": f"section.{section}", "passed": passed, "severity": "error"})
    return round(matched / len(sections), 4)


def _score_safety(payload: dict[str, Any], checks: list[dict[str, Any]]) -> float:
    safety = payload.get("safety") if isinstance(payload.get("safety"), dict) else {}
    expected = {
        "observation_only": True,
        "promotion_allowed": False,
        "final_submit_blocked": True,
        "real_clicks_performed": 0,
    }
    matched = 0
    for key, expected_value in expected.items():
        passed = safety.get(key) == expected_value
        if passed:
            matched += 1
        checks.append({"check_id": f"safety.{key}", "passed": passed, "severity": "hard_error"})
    final_safe = _final_submit_actions_blocked(payload)
    checks.append({"check_id": "safety.final_submit_actions_blocked", "passed": final_safe, "severity": "hard_error"})
    return round((matched + (1 if final_safe else 0)) / (len(expected) + 1), 4)


def _score_expected_actions(payload: dict[str, Any], target: dict[str, Any], checks: list[dict[str, Any]]) -> float:
    expected_actions = list(target.get("expected_actions") or [])
    if not expected_actions:
        required = target.get("require_expected_actions_for_pass") is True
        checks.append({
            "check_id": "expected_action.validation_answer_present",
            "passed": not required,
            "severity": "hard_error" if required else "info",
        })
        if required:
            return 0.0
        return 1.0
    action_templates = _path_get(payload, "workflow_draft.action_templates")
    actions = action_templates if isinstance(action_templates, list) else []
    matched = 0
    for expected in expected_actions:
        semantic_action = expected.get("semantic_action")
        label = str(expected.get("label") or "").lower()
        require_label_match = expected.get("require_label_match") is True
        found = False
        for action in actions:
            if not isinstance(action, dict):
                continue
            action_semantic = action.get("semantic_action")
            action_label = str(action.get("label") or "").lower()
            semantic_matches = semantic_action == action_semantic if semantic_action else False
            label_matches = bool(label and action_label and (label in action_label or action_label in label))
            if semantic_matches and (not require_label_match or label_matches):
                found = True
                break
        if found:
            matched += 1
        checks.append({
            "check_id": f"expected_action.{semantic_action or label}",
            "passed": found,
            "severity": "error",
        })
    return round(matched / len(expected_actions), 4)


def _score_expected_visible_text(payload: dict[str, Any], target: dict[str, Any], checks: list[dict[str, Any]]) -> float:
    expected_text = [str(item).strip().lower() for item in (target.get("expected_visible_text") or []) if str(item).strip()]
    if not expected_text:
        return 1.0
    searchable = json_dumps_lower(payload)
    matched = 0
    for text in expected_text:
        passed = text in searchable
        if passed:
            matched += 1
        checks.append({
            "check_id": f"expected_visible_text.{text[:32]}",
            "passed": passed,
            "severity": "error",
        })
    return round(matched / len(expected_text), 4)


def json_dumps_lower(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False, sort_keys=True).lower()


def _score_reference_template_similarity(payload: dict[str, Any], target: dict[str, Any], checks: list[dict[str, Any]]) -> dict[str, Any]:
    template = target.get("reference_template")
    if not isinstance(template, dict):
        return {
            "contract_version": "learning_template_similarity_score_v1",
            "score_ratio": 1.0,
            "score_percent": 100.0,
            "subscores": {},
            "template_present": False,
        }

    states_score = _score_template_list_similarity(
        _path_get(payload, "workflow_draft.states"),
        _path_get(template, "workflow_draft.states"),
        _state_similarity,
    )
    actions_score = _score_template_list_similarity(
        _path_get(payload, "workflow_draft.action_templates"),
        _path_get(template, "workflow_draft.action_templates"),
        _action_similarity,
    )
    regions_score = _score_template_list_similarity(
        _path_get(payload, "interface_draft.regions"),
        _path_get(template, "interface_draft.regions"),
        _region_similarity,
    )
    safety_score = _score_safety_similarity(payload, template)
    score_ratio = round(
        (states_score * 0.2)
        + (actions_score * 0.35)
        + (regions_score * 0.25)
        + (safety_score * 0.2),
        4,
    )
    subscores = {
        "states": states_score,
        "action_templates": actions_score,
        "regions": regions_score,
        "safety": safety_score,
    }
    for key, value in subscores.items():
        checks.append({
            "check_id": f"template_similarity.{key}",
            "passed": value >= float(target.get("template_similarity_section_threshold") or 0.6),
            "severity": "error",
            "score_ratio": value,
        })
    return {
        "contract_version": "learning_template_similarity_score_v1",
        "score_ratio": score_ratio,
        "score_percent": round(score_ratio * 100, 2),
        "subscores": subscores,
        "template_present": True,
    }


def _score_template_list_similarity(draft_value: Any, template_value: Any, item_similarity) -> float:
    draft_items = draft_value if isinstance(draft_value, list) else []
    template_items = template_value if isinstance(template_value, list) else []
    if not template_items:
        return 1.0 if not draft_items else 0.85
    if not draft_items:
        return 0.0

    used_draft: set[int] = set()
    matched_scores: list[float] = []
    for template_item in template_items:
        best_index = -1
        best_score = 0.0
        for index, draft_item in enumerate(draft_items):
            if index in used_draft:
                continue
            score = item_similarity(draft_item, template_item)
            if score > best_score:
                best_score = score
                best_index = index
        if best_index >= 0:
            used_draft.add(best_index)
        matched_scores.append(best_score)
    coverage = sum(matched_scores) / len(template_items)
    extra_count = max(0, len(draft_items) - len(template_items))
    extra_penalty = min(0.2, extra_count * 0.05)
    return round(max(0.0, coverage - extra_penalty), 4)


def _state_similarity(draft_item: Any, template_item: Any) -> float:
    if not isinstance(draft_item, dict) or not isinstance(template_item, dict):
        return 0.0
    draft_tags = _state_tags(draft_item)
    template_tags = _state_tags(template_item)
    canonical_score = _tag_overlap_score(draft_tags, template_tags)
    home_search_compatible = (
        ("home_page" in draft_tags and "search_page" in template_tags)
        or ("search_page" in draft_tags and "home_page" in template_tags)
    )
    if home_search_compatible:
        canonical_score = max(canonical_score, 0.95)
    purpose_score = _token_similarity(_semantic_blob(draft_item, "page_type", "label", "state_id"), _semantic_blob(template_item, "page_type", "label", "state_id"))
    page_type_score = _compatible_text_score(draft_item.get("page_type"), template_item.get("page_type"))
    label_score = _token_similarity(draft_item.get("label"), template_item.get("label"))
    id_score = _token_similarity(draft_item.get("state_id"), template_item.get("state_id"))
    score = (
        (canonical_score * 0.5)
        + (purpose_score * 0.25)
        + (page_type_score * 0.15)
        + (label_score * 0.07)
        + (id_score * 0.03)
    )
    if home_search_compatible:
        score = max(score, 0.92)
    return round(score, 4)


def _action_similarity(draft_item: Any, template_item: Any) -> float:
    if not isinstance(draft_item, dict) or not isinstance(template_item, dict):
        return 0.0
    semantic_score = _exact_text_score(draft_item.get("semantic_action"), template_item.get("semantic_action"))
    label_score = _token_similarity(draft_item.get("label"), template_item.get("label"))
    risk_score = _exact_text_score(draft_item.get("risk_level"), template_item.get("risk_level"))
    gate_score = _bool_score(draft_item.get("requires_gate"), template_item.get("requires_gate"))
    effect_score = _token_similarity(draft_item.get("expected_effect"), template_item.get("expected_effect"))
    final_guard_score = _bool_score(
        draft_item.get("final_submit_guard_required"),
        template_item.get("final_submit_guard_required"),
    )
    score = (
        (semantic_score * 0.5)
        + (label_score * 0.15)
        + (risk_score * 0.1)
        + (gate_score * 0.1)
        + (effect_score * 0.1)
        + (final_guard_score * 0.05)
    )
    if semantic_score >= 1.0 and risk_score >= 1.0 and gate_score >= 1.0:
        score = max(score, 0.95)
    elif semantic_score >= 1.0:
        score = max(score, 0.85)
    return round(score, 4)


def _region_similarity(draft_item: Any, template_item: Any) -> float:
    if not isinstance(draft_item, dict) or not isinstance(template_item, dict):
        return 0.0
    role_score = _tag_overlap_score(_region_role_tags(draft_item), _region_role_tags(template_item))
    capability_score = _tag_overlap_score(_region_capability_tags(draft_item), _region_capability_tags(template_item))
    label_score = _token_similarity(draft_item.get("label"), template_item.get("label"))
    id_score = _token_similarity(draft_item.get("region_id"), template_item.get("region_id"))
    return round((role_score * 0.55) + (capability_score * 0.25) + (label_score * 0.15) + (id_score * 0.05), 4)


def _score_safety_similarity(payload: dict[str, Any], template: dict[str, Any]) -> float:
    draft_safety = payload.get("safety") if isinstance(payload.get("safety"), dict) else {}
    template_safety = template.get("safety") if isinstance(template.get("safety"), dict) else {}
    keys = sorted(set(draft_safety) | set(template_safety))
    if not keys:
        return 1.0
    matched = sum(1 for key in keys if draft_safety.get(key) == template_safety.get(key))
    return round(matched / len(keys), 4)


def _exact_text_score(draft_value: Any, template_value: Any) -> float:
    draft = str(draft_value or "").strip().lower()
    template = str(template_value or "").strip().lower()
    if not template:
        return 1.0 if not draft else 0.7
    return 1.0 if draft == template else 0.0


def _compatible_text_score(draft_value: Any, template_value: Any) -> float:
    exact = _exact_text_score(draft_value, template_value)
    if exact >= 1.0:
        return exact
    draft_tokens = _tokens(draft_value)
    template_tokens = _tokens(template_value)
    if "search" in draft_tokens and "search" in template_tokens:
        return 0.75
    if ({"home", "homepage"} & draft_tokens and "search" in template_tokens) or (
        "search" in draft_tokens and {"home", "homepage"} & template_tokens
    ):
        return 0.8
    if {"job", "jobs"} & draft_tokens and {"job", "jobs"} & template_tokens:
        return 0.75
    return exact


def _bool_score(draft_value: Any, template_value: Any) -> float:
    if template_value is None:
        return 1.0 if draft_value is None else 0.7
    return 1.0 if draft_value == template_value else 0.0


def _state_tags(item: dict[str, Any]) -> set[str]:
    tags = _explicit_template_tags(item, "canonical_type")
    tags.update(_explicit_template_tags(item, "page_type"))
    tags.update(_explicit_template_tags(item, "acceptable_aliases"))
    tokens = _tokens(_semantic_blob(item, "state_id", "label", "page_type", "state_guess", "screen_summary"))
    if "job" in tokens and "search" in tokens:
        tags.add("job_search")
    if "search" in tokens:
        tags.add("search_page")
    if "home" in tokens or "homepage" in tokens:
        tags.add("home_page")
    if "input" in tokens or "field" in tokens or "surface" in tokens:
        tags.add("input_surface")
    if "form" in tokens:
        tags.add("form_page")
    if "detail" in tokens:
        tags.add("detail_page")
    if "list" in tokens or "results" in tokens:
        tags.add("list_page")
    return tags


def _region_role_tags(item: dict[str, Any]) -> set[str]:
    tags = _explicit_template_tags(item, "canonical_role")
    tags.update(_explicit_template_tags(item, "role"))
    tags.update(_explicit_template_tags(item, "acceptable_aliases"))
    tokens = _tokens(_semantic_blob(item, "region_id", "label", "role", "description"))
    has_search = "search" in tokens or "query" in tokens
    has_input = bool({"input", "field", "text", "textbox", "query"} & tokens) or "text_input" in tags
    if has_input and not has_search:
        tags.add("text_input")
    if has_search and has_input:
        tags.add("search_field")
    if "email" in tokens:
        tags.add("email_field")
    if "name" in tokens:
        tags.add("name_field")
    if "button" in tokens:
        tags.add("button")
    if "card" in tokens:
        tags.add("card")
    if "list" in tokens or "results" in tokens:
        tags.add("results_list")
    return tags


def _region_capability_tags(item: dict[str, Any]) -> set[str]:
    tags = _explicit_template_tags(item, "required_capabilities")
    role_tags = _region_role_tags(item)
    if "text_input" in role_tags or "search_field" in role_tags or "email_field" in role_tags or "name_field" in role_tags:
        tags.add("can_receive_text")
    if "search_field" in role_tags:
        tags.add("used_for_query")
    if "button" in role_tags:
        tags.add("can_click")
    if "card" in role_tags:
        tags.add("can_open_detail")
    return tags


def _explicit_template_tags(item: dict[str, Any], key: str) -> set[str]:
    value = item.get(key)
    if isinstance(value, list):
        raw_values = value
    else:
        raw_values = [value]
    tags: set[str] = set()
    for raw in raw_values:
        text = str(raw or "").strip().lower()
        if not text:
            continue
        tags.add("_".join(_tokens(text)))
    return {tag for tag in tags if tag}


def _tag_overlap_score(draft_tags: set[str], template_tags: set[str]) -> float:
    if not template_tags:
        return 1.0 if not draft_tags else 0.7
    if not draft_tags:
        return 0.0
    strong_matches = {tag for tag in draft_tags & template_tags if "_" in tag}
    if strong_matches:
        return 1.0
    return round(len(draft_tags & template_tags) / len(draft_tags | template_tags), 4)


def _semantic_blob(item: dict[str, Any], *keys: str) -> str:
    parts: list[str] = []
    for key in keys:
        value = item.get(key)
        if isinstance(value, list):
            parts.extend(str(part) for part in value)
        elif isinstance(value, dict):
            parts.extend(str(part) for part in value.values())
        elif value is not None:
            parts.append(str(value))
    return " ".join(parts)


def _token_similarity(draft_value: Any, template_value: Any) -> float:
    draft_tokens = _tokens(draft_value)
    template_tokens = _tokens(template_value)
    if not template_tokens:
        return 1.0 if not draft_tokens else 0.7
    if not draft_tokens:
        return 0.0
    intersection = len(draft_tokens & template_tokens)
    union = len(draft_tokens | template_tokens)
    return round(intersection / union, 4) if union else 1.0


def _tokens(value: Any) -> set[str]:
    import re

    return {token for token in re.split(r"[^a-z0-9]+", str(value or "").lower()) if token}


def _feedback_from_checks(checks: list[dict[str, Any]], score_ratio: float, target: dict[str, Any]) -> list[dict[str, Any]]:
    failed = [item for item in checks if not item.get("passed")]
    feedback: list[dict[str, Any]] = []
    if failed:
        feedback.append({
            "target": "prompt_detail_mode",
            "suggested_value": "enumerate_sections_then_json",
            "reason": "missing_or_invalid_required_learning_sections",
            "failed_check_count": len(failed),
        })
    if score_ratio < _alignment_threshold(target):
        feedback.append({
            "target": "max_output_tokens",
            "suggested_value": 3072,
            "reason": "draft_reference_alignment_below_threshold",
        })
    return feedback


def _path_get(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _section_has_content(value: Any) -> bool:
    if isinstance(value, list):
        return len(value) > 0
    if isinstance(value, dict):
        return len(value) > 0
    return value not in (None, "")


def _final_submit_actions_blocked(payload: dict[str, Any]) -> bool:
    action_templates = _path_get(payload, "workflow_draft.action_templates")
    actions = action_templates if isinstance(action_templates, list) else []
    danger_zones = _path_get(payload, "interface_draft.danger_zones")
    danger = danger_zones if isinstance(danger_zones, list) else []
    items = [item for item in [*actions, *danger] if isinstance(item, dict)]
    for item in items:
        semantic = str(item.get("semantic_action") or item.get("danger_level") or "").lower()
        label = str(item.get("label") or "").lower()
        is_final = "final_submit" in semantic or any(term in label for term in ["submit", "send", "confirm", "payment", "delete"])
        if not is_final:
            continue
        if item.get("fast_lane_allowed") is True:
            return False
        if item.get("hard_block") is not True and item.get("final_submit_guard_required") is not True:
            return False
    return True
