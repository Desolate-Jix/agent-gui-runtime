from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "artifacts" / "benchmarks" / "generic_quick_apply_demo_manifest_v1.json"


def _load_manifest() -> dict:
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8-sig"))
    assert isinstance(payload, dict)
    return payload


def test_demo_manifest_requires_layered_metrics() -> None:
    manifest = _load_manifest()

    assert manifest["contract_version"] == "generic_quick_apply_demo_manifest_v1"
    assert manifest["final_submit_forbidden"] is True
    assert manifest["required_metrics"] == [
        "interface_identification",
        "agent_decision",
        "candidate_recall",
        "point_grounding",
        "gate_decision",
        "operation_dispatch",
        "operation_effect",
        "read_completion",
        "form_inventory",
        "safe_fill_effect",
        "dynamic_question_decision",
        "final_submit_guard",
        "full_no_submit_e2e",
    ]


def test_demo_manifest_keeps_live_coverage_not_covered_until_attempted() -> None:
    manifest = _load_manifest()
    baseline = manifest["coverage_baseline"]

    for metric_name in (
        "live_safe_fill",
        "live_dynamic_question_decision",
        "full_no_submit_e2e",
    ):
        metric = baseline[metric_name]
        assert metric["attempted"] == 0
        assert metric["rate"] == "not_covered"

    assert baseline["fixture_safe_fill"]["source_scope"] == "fixture_only"
    assert manifest["claim_policy"]["combined_success_rate_forbidden"] is True
    assert manifest["claim_policy"]["fixture_pass_is_live_evidence"] is False


def test_demo_manifest_declares_current_capture_and_no_submit_safety() -> None:
    manifest = _load_manifest()
    safety = manifest["safety"]

    assert safety["current_capture_required"] is True
    assert safety["gate_required_for_real_actions"] is True
    assert safety["historical_coordinates_forbidden"] is True
    assert safety["artifact_is_authorization"] is False
    assert safety["submit_clicks_expected"] == 0
    assert safety["final_submissions_expected"] == 0
    assert set(safety["forbidden_actions"]) >= {
        "final_submit",
        "submit_application",
        "send_application",
        "complete_application",
        "confirm_final_submission",
        "payment",
    }


def test_demo_manifest_declares_required_evidence_without_raw_pii() -> None:
    manifest = _load_manifest()

    assert manifest["pii_policy"]["raw_values_in_trace_forbidden"] is True
    assert manifest["pii_policy"]["allowed_trace_fields"] == [
        "field_name",
        "policy_decision",
        "source_reference",
        "value_length",
        "value_sha256",
        "redacted_preview",
    ]
    assert manifest["required_evidence"] == [
        "agent_decision",
        "current_observation",
        "selected_candidate",
        "gate_decision",
        "operation_result",
        "effect_verification",
        "trace_path",
        "screenshot_path",
    ]
