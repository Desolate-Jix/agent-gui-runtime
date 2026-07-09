from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.model_server import profile_for_stage
from app.vision.local_provider import LocalVisionProvider
from scripts.run_model_learning_template_benchmark import (
    _check_agent_usable,
    _check_loader_compatibility,
    _extra_unsafe_actions,
    _load_json,
    _missing_required_field_reports,
    _path_get,
    _relative_path,
    _required_field_validation,
    _resolve_path,
)


PATCH_CONTRACT_VERSION = "learning_template_missing_sections_patch_v1"
PATCH_REPORT_CONTRACT_VERSION = "model_learning_missing_sections_patch_retry_report_v1"


def build_missing_sections_patch_prompt_payload(
    *,
    case_id: str,
    image_path: str,
    original_draft: dict[str, Any],
    required_field_validation: dict[str, Any],
    hidden_reference_template: Any | None = None,
    scoring_diff: Any | None = None,
) -> dict[str, Any]:
    missing = list(required_field_validation.get("missing_required_fields") or [])
    retry_plan = required_field_validation.get("retry_plan") if isinstance(required_field_validation.get("retry_plan"), dict) else {}
    requested = [
        item
        for item in retry_plan.get("missing_required_sections", [])
        if isinstance(item, dict) and item.get("logical_field") in missing
    ]
    return {
        "contract_version": "learning_template_missing_sections_patch_prompt_v1",
        "case_id": case_id,
        "image_path": image_path,
        "task": "repair_missing_required_sections_only",
        "missing_required_fields": missing,
        "missing_required_sections": requested,
        "original_draft": copy.deepcopy(original_draft),
        "allowed_patch_schema": {
            "schema_version": PATCH_CONTRACT_VERSION,
            "case_id": case_id,
            "patch_sections": {
                field: [] if field in {"blockers", "verification_rules"} else {}
                for field in missing
            },
            "notes": [],
        },
        "rules": [
            "Return JSON only.",
            "Return only the requested missing sections inside patch_sections.",
            "Do not regenerate the full learning_template_draft_v1 template.",
            "Do not include workflow_draft, interface_draft, action_templates, states, or regions unless they are explicitly requested.",
            "Blockers must be linked to surface/action risk and must not authorize final submit, send, complete, payment, account creation, upload, login, captcha, or privacy consent.",
            "Verification rules must be structured objects linked to an action or surface and include expected observation evidence.",
            "If you cannot ground a section to the original draft, leave it empty and add a warning note.",
        ],
        "source_policy": {
            "reference_in_prompt": False,
            "scoring_answers_in_prompt": False,
            "holdout_data_in_prompt": False,
            "counts_as_pure_model_generated": False,
        },
    }


def patch_prompt_text(prompt_payload: dict[str, Any]) -> str:
    return (
        "You are repairing missing sections in a GUI Agent Runtime learning template.\n"
        "Return exactly one JSON object matching allowed_patch_schema.\n"
        "Do not return markdown. Do not regenerate the full template.\n\n"
        f"patch_retry_context:\n{json.dumps(prompt_payload, ensure_ascii=False, indent=2)}"
    )


def validate_missing_sections_patch(patch: Any, retry_plan: dict[str, Any] | None) -> dict[str, Any]:
    reject_reasons: list[str] = []
    if not isinstance(patch, dict):
        return {"status": "rejected", "reject_reasons": ["patch_not_json_object"]}

    if patch.get("contract_version") == "learning_template_draft_v1" or any(
        key in patch for key in ("workflow_draft", "interface_draft", "action_templates", "states", "regions")
    ):
        reject_reasons.append("full_template_regeneration_not_allowed")

    if patch.get("schema_version") != PATCH_CONTRACT_VERSION:
        reject_reasons.append("wrong_patch_schema_version")

    patch_sections = patch.get("patch_sections")
    if not isinstance(patch_sections, dict):
        reject_reasons.append("patch_sections_missing")
        patch_sections = {}

    requested = {
        str(item.get("logical_field"))
        for item in ((retry_plan or {}).get("missing_required_sections") or [])
        if isinstance(item, dict) and item.get("logical_field")
    }
    provided = set(str(key) for key in patch_sections.keys())
    unrequested = sorted(provided - requested)
    if unrequested:
        reject_reasons.append("unrequested_patch_sections")
    missing_requested = sorted(requested - provided)
    if missing_requested:
        reject_reasons.append("requested_patch_sections_missing")

    if _patch_contains_unsafe_action(patch_sections):
        reject_reasons.append("unsafe_action_in_patch")
    if "blockers" in patch_sections and not _linked_blockers_valid(patch_sections.get("blockers")):
        reject_reasons.append("generic_or_unlinked_blockers")
    if "verification_rules" in patch_sections and not _structured_verification_rules_valid(
        patch_sections.get("verification_rules")
    ):
        reject_reasons.append("generic_or_unstructured_verification_rules")

    return {
        "status": "accepted" if not reject_reasons else "rejected",
        "reject_reasons": reject_reasons,
        "requested_sections": sorted(requested),
        "provided_sections": sorted(provided),
    }


def merge_missing_sections_patch(
    original_draft: dict[str, Any],
    patch: dict[str, Any],
    *,
    source_after_retry: str = "mixed",
) -> dict[str, Any]:
    merged = copy.deepcopy(original_draft)
    patch_sections = patch.get("patch_sections") if isinstance(patch.get("patch_sections"), dict) else {}
    if "blockers" in patch_sections:
        safety = merged.setdefault("safety", {})
        if isinstance(safety, dict):
            safety["blockers"] = copy.deepcopy(patch_sections["blockers"])
    if "verification_rules" in patch_sections:
        workflow = merged.setdefault("workflow_draft", {})
        if isinstance(workflow, dict):
            workflow["verification_rules"] = copy.deepcopy(patch_sections["verification_rules"])
    tracking = merged.setdefault("_source_tracking", {})
    if isinstance(tracking, dict):
        tracking.update(
            {
                "source_after_retry": source_after_retry,
                "template_source": source_after_retry,
                "patch_source": "actual_model_call_retry",
                "counts_as_pure_model_generated": False,
                "deterministic_completion_used": False,
            }
        )
    return merged


def run_patch_retry(
    manifest_path: str | Path,
    out_dir: str | Path,
    *,
    limit: int = 3,
    project_root: str | Path | None = None,
    profile_id: str = "qwen3_vl_8b_q4_k_m",
) -> dict[str, Any]:
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    manifest_file = _resolve_path(manifest_path, root)
    out_path = Path(out_dir)
    if not out_path.is_absolute():
        out_path = root / out_path
    out_path.mkdir(parents=True, exist_ok=True)

    manifest = _load_json(manifest_file)
    raw_cases = [case for case in (manifest.get("cases") or []) if isinstance(case, dict)]
    selected_cases = [
        case for case in raw_cases if str(case.get("generated_template_source") or case.get("case_source")) == "actual_model_call"
    ][: max(0, int(limit))]

    case_results: list[dict[str, Any]] = []
    for raw_case in selected_cases:
        case_results.append(_run_patch_retry_case(raw_case, out_path, root, profile_id))

    metrics = _patch_retry_metrics(case_results)
    report = {
        "contract_version": PATCH_REPORT_CONTRACT_VERSION,
        "generated_at": datetime.now().isoformat(),
        "manifest_path": _relative_path(manifest_file, root),
        "actual_model_call_cases": len(case_results),
        "holdout_used_for_tuning": False,
        "selected_config_changed": False,
        "live_submit": False,
        "live_safe_fill": False,
        "cases": case_results,
        "missing_required_sections_patch_retry": metrics,
        "interpretation": "targeted actual-model retry for missing sections only; not pure one-shot model ability",
    }
    report_path = out_path / "missing_sections_patch_retry_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _run_patch_retry_case(raw_case: dict[str, Any], out_path: Path, root: Path, profile_id: str) -> dict[str, Any]:
    case_id = str(raw_case.get("case_id") or "unnamed_case")
    case_dir = out_path / "cases" / _safe_name(case_id)
    case_dir.mkdir(parents=True, exist_ok=True)
    generated_path = _resolve_path(str(raw_case["generated_template_path"]), root)
    image_path = _resolve_path(str(raw_case["screenshot_path"]), root)
    original_draft = _load_json(generated_path)
    before_missing = _missing_fields(original_draft)
    validation = _required_field_validation(
        before_missing,
        "actual_model_call",
        field_reports=_missing_required_field_reports(original_draft),
    )
    prompt_payload = build_missing_sections_patch_prompt_payload(
        case_id=case_id,
        image_path=_relative_path(image_path, root),
        original_draft=original_draft,
        required_field_validation=validation,
    )
    prompt_payload_path = case_dir / "retry_prompt_payload.json"
    prompt_text_path = case_dir / "retry_prompt.txt"
    prompt_payload_path.write_text(json.dumps(prompt_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    prompt_text = patch_prompt_text(prompt_payload)
    prompt_text_path.write_text(prompt_text, encoding="utf-8")

    before_unsafe = _extra_unsafe_actions(original_draft)
    before_loader = _check_loader_compatibility(original_draft, case_id, case_dir, root)
    before_agent = _check_agent_usable(original_draft)
    raw_output_path = case_dir / "retry_raw_output.txt"
    patch_path = case_dir / "retry_patch.json"
    merged_path = case_dir / "merged_template.json"

    model_result = _call_patch_model(image_path, prompt_text, profile_id=profile_id)
    raw_output_path.write_text(str(model_result["raw_text"] or ""), encoding="utf-8")
    patch = model_result["model_json"] if isinstance(model_result.get("model_json"), dict) else {}
    patch_path.write_text(json.dumps(patch, ensure_ascii=False, indent=2), encoding="utf-8")
    patch_validation = validate_missing_sections_patch(patch, validation.get("retry_plan"))

    merged = None
    after_missing = before_missing
    after_unsafe = before_unsafe
    after_loader: dict[str, Any] | None = None
    after_agent: dict[str, Any] | None = None
    source_after_retry = None
    counts_as_pure = False
    if patch_validation["status"] == "accepted":
        merged = merge_missing_sections_patch(original_draft, patch, source_after_retry="mixed")
        merged_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
        after_missing = _missing_fields(merged)
        after_unsafe = _extra_unsafe_actions(merged)
        after_loader = _check_loader_compatibility(merged, f"{case_id}_merged", case_dir, root)
        after_agent = _check_agent_usable(merged)
        source_after_retry = "mixed"
        counts_as_pure = False

    reject_reasons = post_merge_reject_reasons(
        patch_validation_status=str(patch_validation["status"]),
        existing_reject_reasons=list(patch_validation.get("reject_reasons") or []),
        before_unsafe=before_unsafe,
        after_unsafe=after_unsafe,
        before_loader=before_loader,
        after_loader=after_loader if patch_validation["status"] == "accepted" else None,
    )
    final_patch_status = "accepted" if patch_validation["status"] == "accepted" and not reject_reasons else "rejected"

    return {
        "case_id": case_id,
        "retry_executed": True,
        "retry_prompt_path": _relative_path(prompt_text_path, root),
        "retry_prompt_payload_path": _relative_path(prompt_payload_path, root),
        "retry_raw_output_path": _relative_path(raw_output_path, root),
        "retry_patch_path": _relative_path(patch_path, root),
        "merged_template_path": _relative_path(merged_path, root) if merged is not None else None,
        "missing_required_fields_before_retry": before_missing,
        "missing_required_fields_after_retry": after_missing,
        "patch_parse_status": "passed" if isinstance(patch, dict) and patch else "failed",
        "patch_validation_status": final_patch_status,
        "patch_reject_reason": reject_reasons or None,
        "source_after_retry": source_after_retry,
        "counts_as_pure_model_generated": counts_as_pure,
        "extra_unsafe_actions_before": before_unsafe,
        "extra_unsafe_actions_after": after_unsafe,
        "loader_compatibility_before": before_loader.get("passed"),
        "loader_compatibility_after": after_loader.get("passed") if after_loader is not None else None,
        "agent_usable_before": before_agent.get("passed"),
        "agent_usable_after": after_agent.get("passed") if after_agent is not None else None,
        "classification_before": "invalid_or_unsafe_template",
        "classification_after": "usable_template_candidate"
        if after_loader is not None
        and after_agent is not None
        and not after_missing
        and not after_unsafe
        and after_loader.get("passed")
        and after_agent.get("passed")
        else "invalid_or_unsafe_template",
        "model_provider": model_result.get("provider"),
        "model_name": model_result.get("model_name"),
    }


def post_merge_reject_reasons(
    *,
    patch_validation_status: str,
    existing_reject_reasons: list[str],
    before_unsafe: list[dict[str, Any]],
    after_unsafe: list[dict[str, Any]],
    before_loader: dict[str, Any],
    after_loader: dict[str, Any] | None,
) -> list[str]:
    reject_reasons = list(existing_reject_reasons)
    if patch_validation_status != "accepted":
        return reject_reasons
    if len(after_unsafe) > len(before_unsafe) and "unsafe_action_increase_after_merge" not in reject_reasons:
        reject_reasons.append("unsafe_action_increase_after_merge")
    if (
        after_loader is not None
        and before_loader.get("passed")
        and not after_loader.get("passed")
        and "loader_compatibility_regressed" not in reject_reasons
    ):
        reject_reasons.append("loader_compatibility_regressed")
    return reject_reasons


def _call_patch_model(image_path: Path, prompt_text: str, *, profile_id: str) -> dict[str, Any]:
    profile = profile_for_stage("observe", profile_id)
    provider = LocalVisionProvider(
        endpoint=profile.get("endpoint"),
        model_name=profile.get("model_name"),
        timeout_seconds=240.0,
    )
    raw_response = provider._call_openai_compatible_endpoint(
        image_path,
        prompt_text,
        max_tokens=2048,
        temperature=0.0,
    )
    raw_text = provider._extract_message_text(raw_response)
    model_json = provider._parse_json_object(raw_text)
    return {
        "provider": "local",
        "model_name": profile.get("model_name"),
        "raw_text": raw_text,
        "model_json": model_json,
        "raw_response": raw_response,
    }


def _patch_retry_metrics(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "attempted": len(case_results),
        "patch_parse_passed": sum(1 for case in case_results if case.get("patch_parse_status") == "passed"),
        "patch_validation_passed": sum(1 for case in case_results if case.get("patch_validation_status") == "accepted"),
        "missing_fields_reduced": sum(
            1
            for case in case_results
            if len(case.get("missing_required_fields_after_retry") or [])
            < len(case.get("missing_required_fields_before_retry") or [])
        ),
        "became_usable_template_candidate": sum(
            1 for case in case_results if case.get("classification_after") == "usable_template_candidate"
        ),
        "interpretation": "targeted actual-model retry for missing sections only; not pure one-shot model ability",
    }


def _missing_fields(draft: Any) -> list[str]:
    reports = _missing_required_field_reports(draft)
    return [item["logical_field"] for item in reports if not item["found"]]


def _linked_blockers_valid(value: Any) -> bool:
    blockers = [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []
    if not blockers:
        return False
    for item in blockers:
        has_id = bool(item.get("blocker_id"))
        linked = any(item.get(key) for key in ("applies_to_action_template_id", "action_template_id", "surface", "risk"))
        policy = any(item.get(key) for key in ("policy", "hard_block", "requires_user_review", "safe_stop"))
        if not (has_id and linked and policy):
            return False
    return True


def _structured_verification_rules_valid(value: Any) -> bool:
    rules = [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []
    if not rules:
        return False
    for item in rules:
        has_id = bool(item.get("rule_id"))
        linked = any(item.get(key) for key in ("applies_to_action_template_id", "action_template_id", "surface"))
        observable = any(item.get(key) for key in ("expected_observation", "expected_state", "evidence_source", "check"))
        if not (has_id and linked and observable):
            return False
    return True


def _patch_contains_unsafe_action(patch_sections: dict[str, Any]) -> bool:
    for key in ("action_templates", "actions", "danger_zones"):
        value = patch_sections.get(key)
        items = value if isinstance(value, list) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            haystack = " ".join(str(item.get(field) or "") for field in ("label", "semantic_action", "description"))
            if any(term in haystack.casefold() for term in ("submit", "send", "complete", "final_submit", "payment")):
                return True
    return False


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value)[:120] or "case"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--profile-id", default="qwen3_vl_8b_q4_k_m")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = run_patch_retry(args.manifest, args.out, limit=args.limit, profile_id=args.profile_id)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"wrote {Path(args.out) / 'missing_sections_patch_retry_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
