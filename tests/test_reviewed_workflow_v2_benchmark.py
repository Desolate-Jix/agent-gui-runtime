from __future__ import annotations

import copy
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_reviewed_workflow_asset_v2 import _asset
from tests.test_reviewed_workflow_replay_v2 import _gate, _grounding, _observation, _operation


def _sha(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _manifest(asset: dict, cases: list[dict]) -> dict:
    from app.agent.reviewed_workflow_asset import validate_reviewed_workflow_asset
    from scripts import run_reviewed_workflow_v2_benchmark as benchmark

    canonical = validate_reviewed_workflow_asset(asset)
    normalized = benchmark._validate_cases(cases)
    valid = [case for case in normalized if case["fixture_valid"]]
    phase_result_sha256 = {}
    for case in valid:
        result = benchmark._runtime(canonical, case)
        phase_result_sha256[case["case_id"]] = {
            name: evidence["derived_result_digest_sha256"]
            for name, evidence in result["evidence"].items()
            if evidence["attempted"]
        }
    return {
        "contract_version": "reviewed_workflow_v2_benchmark_fixture_manifest_v1",
        "asset_sha256": _sha(canonical),
        "valid_cases_sha256": _sha(valid),
        "case_sha256": {case["case_id"]: _sha(case) for case in normalized},
        "phase_result_sha256": phase_result_sha256,
    }


def _bare_events(case_id: str, *, would_dispatch: bool = True, claimed_verified: bool = True) -> list[dict]:
    return [
        {"event_type": "proposal", "semantic_action": "open_detail"},
        {"event_type": "dispatch", "would_dispatch": would_dispatch},
        {"event_type": "post_verification", "claimed_post_action_verified": claimed_verified},
        {"event_type": "evidence", "evidence_refs": [f"bare_{case_id}"]},
    ]


def _run(asset: dict, cases: list[dict], *, manifest: dict | None = None, **kwargs) -> dict:
    from scripts.run_reviewed_workflow_v2_benchmark import run_reviewed_workflow_v2_contract_benchmark

    fixture_manifest = manifest or (_manifest(asset, cases) if isinstance(cases, list) and cases else {})
    return run_reviewed_workflow_v2_contract_benchmark(asset, cases, fixture_manifest=fixture_manifest, **kwargs)


def _case(
    asset: dict,
    case_id: str,
    *,
    observation: dict,
    transition_id: str,
    expected_classification: str,
    expected_failure_code: str | None,
    grounding: dict | None = None,
    gate: dict | None = None,
    operation: dict | None = None,
    post_observation: dict | None = None,
    attempts_used: int = 0,
    invalid_point_category: str | None = None,
) -> dict:
    return {
        "case_id": case_id,
        "category": case_id,
        "fixture_valid": True,
        "fixture_invalid_reason": "",
        "bare_events": _bare_events(case_id),
        "expected": {
            "bare": {"classification": "recorded_ungated_dispatch_claimed_verified", "failure_code": None},
            "runtime": {"classification": expected_classification, "failure_code": expected_failure_code},
        },
        "current_observation": observation,
        "transition_id": transition_id,
        "grounding": grounding,
        "gate": gate,
        "operation": operation,
        "post_observation": post_observation,
        "attempts_used": attempts_used,
        "invalid_point_category": invalid_point_category,
    }


def _valid_detail_case(asset: dict) -> dict:
    observation = _observation(asset, "capture-1", "a" * 64, "anchor_homepage", "job_card")
    from app.agent.reviewed_workflow_replay import resolve_current_state, select_verified_transition

    selection = select_verified_transition(
        asset,
        resolve_current_state(asset, observation),
        transition_id="open_detail",
        current_observation=observation,
    )
    result = _case(
        asset,
        "valid_open_detail",
        observation=observation,
        transition_id="open_detail",
        expected_classification="verified",
        expected_failure_code=None,
        grounding=_grounding(asset),
        gate=_gate(asset, selection),
        operation=_operation(selection),
        post_observation=_observation(asset, "capture-2", "b" * 64, "anchor_detail", "quick_apply"),
    )
    result["category"] = "verified_open_detail"
    return result


def _valid_apply_case(asset: dict) -> dict:
    observation = _observation(asset, "capture-3", "c" * 64, "anchor_detail", "quick_apply")
    from app.agent.reviewed_workflow_replay import resolve_current_state, select_verified_transition

    selection = select_verified_transition(
        asset,
        resolve_current_state(asset, observation),
        transition_id="open_apply_flow",
        current_observation=observation,
    )
    result = _case(
        asset,
        "valid_open_apply_flow",
        observation=observation,
        transition_id="open_apply_flow",
        expected_classification="verified",
        expected_failure_code=None,
        grounding=_grounding(asset, "capture-3", "c" * 64) | {"transition_id": "open_apply_flow", "source_state_id": "detail", "element_ref": "quick_apply", "evidence_refs": ["grounding:capture-3:quick_apply"]},
        gate=_gate(asset, selection, "capture-3", "c" * 64) | {"selected_element_id": "quick_apply"},
        operation=_operation(selection),
        post_observation=_observation(asset, "capture-4", "d" * 64, "anchor_apply_entry"),
    )
    result["category"] = "verified_open_apply_flow"
    result["bare_events"][0]["semantic_action"] = "open_apply_flow"
    return result


def _matrix(asset: dict) -> list[dict]:
    valid = _valid_detail_case(asset)
    cases = [valid, _valid_apply_case(asset)]

    unresolved = copy.deepcopy(valid)
    unresolved["case_id"] = "unresolved"
    unresolved["category"] = "unresolved"
    unresolved["current_observation"]["observed_anchor_evidence"] = []
    unresolved["bare_events"] = _bare_events("unresolved", would_dispatch=False, claimed_verified=False)
    unresolved["operation"]["action_executed"] = False
    unresolved["operation"]["post_action_verified"] = False
    unresolved["expected"]["bare"] = {"classification": "recorded_no_dispatch", "failure_code": "not_dispatched"}
    unresolved["expected"]["runtime"] = {"classification": "blocked", "failure_code": "current_state_unresolved"}
    cases.append(unresolved)

    mutations = [
        ("ambiguous", lambda item: item["current_observation"].update({"observed_anchor_evidence": _observation(asset, "capture-1", "a" * 64, "anchor_homepage", "anchor_detail")["observed_anchor_evidence"]}), "current_state_ambiguous"),
        ("wrong_origin", lambda item: item["current_observation"].update({"origin": "https://evil.example"}), "unexpected_origin"),
        ("transition_not_available", lambda item: item.update({"transition_id": "missing_transition"}), "transition_not_available"),
        ("stale_capture", lambda item: item["grounding"].update({"capture_id": "older-capture"}), "capture_lineage_mismatch"),
        ("stale_candidate", lambda item: item["grounding"].update({"candidate_current": False}), "stale_candidate"),
        ("low_margin", lambda item: item["grounding"].update({"score_margin": 0.01}), "grounding_ambiguous"),
        ("out_of_bounds_point", lambda item: item["grounding"].update({"click_point": {"x": 9999, "y": 9999}}), "target_unresolved"),
        ("gate_rejection", lambda item: item["gate"].update({"allowed": False}), "pre_click_rejected"),
        ("missing_operation_evidence", lambda item: item["operation"].update({"evidence_refs": []}), "operation_evidence_missing"),
        ("same_post_capture", lambda item: item["post_observation"].update({"capture_id": "capture-1", "screenshot_sha256": "a" * 64}), "post_capture_not_new"),
        ("destination_mismatch", lambda item: item["post_observation"].update({"observed_anchor_evidence": _observation(asset, "capture-2", "b" * 64, "anchor_homepage", "job_card")["observed_anchor_evidence"]}), "destination_mismatch"),
    ]
    for case_id, mutate, failure_code in mutations:
        item = copy.deepcopy(valid)
        item["case_id"] = case_id
        item["category"] = case_id
        mutate(item)
        item["expected"]["runtime"] = {"classification": "blocked", "failure_code": failure_code}
        if failure_code not in {"operation_evidence_missing", "post_capture_not_new", "destination_mismatch"}:
            item["operation"]["action_executed"] = False
            item["operation"]["post_action_verified"] = False
        if case_id == "out_of_bounds_point":
            item["category"] = "invalid_point"
            item["invalid_point_category"] = "outside_viewport"
        cases.append(item)

    recovery_once = copy.deepcopy(valid)
    recovery_once["case_id"] = "recovery_once"
    recovery_once["category"] = "recovery_once"
    recovery_once["grounding"]["candidate_current"] = False
    recovery_once["operation"]["action_executed"] = False
    recovery_once["operation"]["post_action_verified"] = False
    recovery_once["expected"]["runtime"] = {"classification": "blocked", "failure_code": "stale_candidate"}
    cases.append(recovery_once)
    recovery_exhausted = copy.deepcopy(recovery_once)
    recovery_exhausted["case_id"] = "recovery_exhausted"
    recovery_exhausted["category"] = "recovery_exhausted"
    recovery_exhausted["attempts_used"] = 1
    cases.append(recovery_exhausted)

    invalid = {
        "case_id": "excluded_invalid_fixture",
        "category": "fixture_invalid",
        "fixture_valid": False,
        "fixture_invalid_reason": "fixture_declared_invalid",
        "bare_events": _bare_events("excluded_invalid_fixture", would_dispatch=False, claimed_verified=False),
        "expected": {
            "bare": {"classification": "recorded_no_dispatch", "failure_code": "not_dispatched"},
            "runtime": {"classification": "blocked", "failure_code": "fixture_invalid"},
        },
    }
    cases.append(invalid)
    return cases


def test_contract_benchmark_pins_offline_matrix_and_safe_metrics() -> None:
    ticks = iter(range(0, 1_000_000, 100))
    report = _run(_asset(), _matrix(_asset()), repeats=3, clock_ns=lambda: next(ticks))

    assert report["contract_version"] == "reviewed_workflow_v2_contract_benchmark_report_v1"
    assert report["scope"] == {
        "synthetic_offline_contract_replay": True,
        "live_gui_actions": 0,
        "model_calls": 0,
        "final_submit_attempts": 0,
        "execution_authorized": False,
    }
    assert report["fixture_validity"] == {"total": 17, "valid": 16, "invalid_excluded": 1}
    assert report["acceptance"] == {"passed": True, "reasons": []}
    assert report["fixture_pins"]["asset_sha256"]
    assert report["fixture_pins"]["valid_cases_sha256"]
    assert set(report["fixture_pins"]["case_sha256"]) == {item["case_id"] for item in _matrix(_asset())}
    assert report["coverage_manifest"]["passed"] is True
    assert report["summary"]["runtime_expected_match_fraction"] == 1.0
    assert report["summary"]["bare_fixture_pin_match_fraction"] == 1.0
    assert report["safety"]["runtime_unsafe_dispatches"] == 0
    assert report["safety"]["runtime_wrong_continuations"] == 0
    assert report["safety"]["runtime_dispatch_reached"] > 0
    assert report["summary"]["successful_verification_evidence"]["complete"] == 2
    assert report["misclick_risk_proxy"]["invalid_point_categories"] == {"outside_viewport": 1}
    assert report["cases"][-1]["included_in_denominator"] is False
    assert report["cases"][-1]["fixture_valid"] is False
    assert all(item["recovery"]["repeat_action"] is False for item in report["cases"] if item["fixture_valid"])
    assert all(item["recovery"]["attempts_used"] <= 1 for item in report["cases"] if item["fixture_valid"])
    assert next(item for item in report["cases"] if item["case_id"] == "recovery_once")["recovery"]["decision"] == "reobserve_and_reground_once"
    assert next(item for item in report["cases"] if item["case_id"] == "recovery_exhausted")["recovery"]["failure_code"] == "recovery_exhausted"
    assert {row["phase"] for row in report["latency"]["summary"]} == {"bare_classify", "bare_total", "runtime_total", "state_resolution", "transition_selection", "grounding_gate", "post_verification"}
    assert next(row for row in report["latency"]["summary"] if row["phase"] == "bare_classify")["sample_count"] == 16 * 3
    assert all(row["sample_count"] == 3 and math.isfinite(row["median_ns"]) and math.isfinite(row["p95_ns"]) for row in report["latency"]["per_case"][0]["phases"][:2])
    assert next(row for row in report["latency"]["per_case"] if row["case_id"] == "unresolved")["phases"][-1] == {"phase": "post_verification", "coverage": "not_covered", "sample_count": 0, "median_ns": None, "p95_ns": None}
    assert all("bbox" not in json.dumps(item, ensure_ascii=False) and "click_point" not in json.dumps(item, ensure_ascii=False) for item in report["cases"])
    assert "live GUI" in " ".join(report["limitations"])
    assert report["cases"][0]["bare"]["actual"] == {"classification": "recorded_ungated_dispatch_claimed_verified", "failure_code": None}
    assert "accuracy" not in json.dumps(report, ensure_ascii=False).lower()
    assert {item["case_id"] for item in _matrix(_asset()) if item["fixture_valid"]} >= {
        "valid_open_detail", "valid_open_apply_flow", "unresolved", "ambiguous", "wrong_origin",
        "transition_not_available", "stale_capture", "stale_candidate", "low_margin", "out_of_bounds_point",
        "gate_rejection", "missing_operation_evidence", "same_post_capture", "destination_mismatch",
        "recovery_once", "recovery_exhausted",
    }
    assert set(report["coverage_manifest"]["required_categories"]) <= set(report["coverage_manifest"]["observed_categories"])


def test_contract_benchmark_rejects_invalid_asset_cases_and_repeat_count() -> None:
    with pytest.raises(ValueError, match="asset"):
        _run({}, [])
    with pytest.raises(ValueError, match="cases"):
        _run(_asset(), {"case_id": "not-a-list"})
    with pytest.raises(ValueError, match="repeats"):
        _run(_asset(), [], repeats=0)


def test_contract_benchmark_rejects_closed_record_schema_unsafe_id_final_submit_and_negative_clock() -> None:
    record_extra = _matrix(_asset())
    record_extra[0]["bare_events"][0]["extra"] = True
    with pytest.raises(ValueError, match="bare_events"):
        _run(_asset(), record_extra)

    nested_extra = _matrix(_asset())
    nested_extra[0]["operation"]["unexpected"] = True
    with pytest.raises(ValueError, match="operation"):
        _run(_asset(), nested_extra)

    unsafe_id = _matrix(_asset())
    unsafe_id[0]["case_id"] = "unsafe-id"
    with pytest.raises(ValueError, match="case_id"):
        _run(_asset(), unsafe_id)

    safe_character_pii = _matrix(_asset())
    safe_character_pii[0]["case_id"] = "alice_smith_phone_12345"
    with pytest.raises(ValueError, match="canonical category identifier"):
        _run(_asset(), safe_character_pii)

    final_submit = _matrix(_asset())
    final_submit[0]["bare_events"][0]["semantic_action"] = "final_submit"
    with pytest.raises(ValueError, match="final_submit"):
        _run(_asset(), final_submit)

    forbidden_dispatch = _matrix(_asset())
    forbidden_dispatch[0]["operation"]["action_type"] = "payment"
    with pytest.raises(ValueError, match="forbidden"):
        _run(_asset(), forbidden_dispatch)

    pii_reason = _matrix(_asset())
    pii_reason[-1]["fixture_invalid_reason"] = "unsafe.reason"
    with pytest.raises(ValueError, match="fixture_invalid_reason"):
        _run(_asset(), pii_reason)

    safe_character_secret = _matrix(_asset())
    safe_character_secret[-1]["fixture_invalid_reason"] = "secret_token_value"
    with pytest.raises(ValueError, match="canonical excluded identifier"):
        _run(_asset(), safe_character_secret)

    safe_character_expected = _matrix(_asset())
    safe_character_expected[-1]["expected"]["runtime"]["failure_code"] = "secret_token_value"
    with pytest.raises(ValueError, match="canonical excluded identifier"):
        _run(_asset(), safe_character_expected)

    safe_character_bare_expected = _matrix(_asset())
    safe_character_bare_expected[0]["expected"]["bare"]["failure_code"] = "secret_token_value"
    with pytest.raises(ValueError, match="expected.bare must match recorded events"):
        _run(_asset(), safe_character_bare_expected)

    with pytest.raises(ValueError, match="negative elapsed"):
        _run(_asset(), _matrix(_asset()), repeats=1, clock_ns=iter([100, 99]).__next__)


def test_contract_benchmark_reports_fixture_pin_mismatch_and_coverage_failure_without_accuracy_label() -> None:
    pin_mismatch = _matrix(_asset())
    pin_mismatch[0]["expected"]["bare"] = {"classification": "recorded_no_dispatch", "failure_code": "not_dispatched"}
    with pytest.raises(ValueError, match="expected.bare must match recorded events"):
        _run(_asset(), pin_mismatch, manifest=_manifest(_asset(), _matrix(_asset())), repeats=1)

    undercovered = _matrix(_asset())[:2]
    coverage_report = _run(_asset(), undercovered, repeats=1)
    assert coverage_report["coverage_manifest"]["passed"] is False
    assert coverage_report["acceptance"]["passed"] is False
    assert any("coverage" in reason for reason in coverage_report["acceptance"]["reasons"])

    no_verified = _matrix(_asset())[2:-1]
    no_verified_report = _run(_asset(), no_verified, repeats=1)
    assert no_verified_report["summary"]["successful_verification_evidence"]["coverage"] == "not_covered"

    relabeled_clone = _matrix(_asset())
    relabeled_clone[0]["category"] = "verified_open_apply_flow"
    with pytest.raises(ValueError, match="canonical category identifier"):
        _run(_asset(), relabeled_clone)


def test_contract_benchmark_rejects_invalid_point_substitution_and_phase_digest_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    valid_point = _matrix(_asset())
    invalid_case = next(case for case in valid_point if case["category"] == "invalid_point")
    invalid_case["grounding"]["click_point"] = {"x": 220, "y": 240}
    with pytest.raises(ValueError, match="invalid_point declared category mismatches geometry"):
        _run(_asset(), valid_point)

    ineligible = _matrix(_asset())
    next(case for case in ineligible if case["category"] == "invalid_point")["grounding"]["eligible"] = False
    with pytest.raises(ValueError, match="invalid_point requires current eligible candidate"):
        _run(_asset(), ineligible)

    malformed_bbox = _matrix(_asset())
    malformed = next(case for case in malformed_bbox if case["category"] == "invalid_point")
    malformed["grounding"]["bbox"]["w"] = -1
    malformed["grounding"]["click_point"] = {"x": 220, "y": 240}
    malformed["invalid_point_category"] = "outside_bbox"
    with pytest.raises(ValueError, match="invalid_point requires valid contained bbox"):
        _run(_asset(), malformed_bbox)

    asset, cases = _asset(), _matrix(_asset())
    phase_manifest = _manifest(asset, cases)
    phase_manifest["phase_result_sha256"]["valid_open_detail"]["state_resolution"] = "0" * 64
    report = _run(asset, cases, manifest=phase_manifest, repeats=1)
    assert report["acceptance"]["passed"] is False
    assert "derived evidence completeness failure" in report["acceptance"]["reasons"]

    manifest = _manifest(asset, cases)
    import scripts.run_reviewed_workflow_v2_benchmark as benchmark

    monkeypatch.setattr(benchmark, "resolve_current_state", lambda *_args, **_kwargs: {"status": "blocked", "failure_code": "probe"})
    report = _run(asset, cases, manifest=manifest, repeats=1)
    assert report["acceptance"]["passed"] is False
    assert "derived evidence completeness failure" in report["acceptance"]["reasons"]


def test_contract_benchmark_cli_writes_utf8_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from scripts import run_reviewed_workflow_v2_benchmark as benchmark

    asset_path = tmp_path / "asset.json"
    cases_path = tmp_path / "cases.json"
    manifest_path = tmp_path / "manifest.json"
    out_path = tmp_path / "report.json"
    asset_path.write_text(json.dumps(_asset(), ensure_ascii=False), encoding="utf-8")
    cases_path.write_text(json.dumps(_matrix(_asset()), ensure_ascii=False), encoding="utf-8")
    manifest_path.write_text(json.dumps(_manifest(_asset(), _matrix(_asset())), ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["benchmark", "--asset", str(asset_path), "--cases", str(cases_path), "--manifest", str(manifest_path), "--out", str(out_path), "--repeats", "1"])

    assert benchmark.main() == 0
    assert json.loads(out_path.read_text(encoding="utf-8"))["contract_version"] == "reviewed_workflow_v2_contract_benchmark_report_v1"
    assert json.loads(capsys.readouterr().out)["report_path"] == str(out_path)


def test_contract_benchmark_cli_does_not_write_non_accepting_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import run_reviewed_workflow_v2_benchmark as benchmark

    asset_path = tmp_path / "asset.json"
    cases_path = tmp_path / "cases.json"
    manifest_path = tmp_path / "manifest.json"
    out_path = tmp_path / "report.json"
    asset_path.write_text(json.dumps(_asset(), ensure_ascii=False), encoding="utf-8")
    cases_path.write_text(json.dumps(_matrix(_asset())[:2], ensure_ascii=False), encoding="utf-8")
    manifest_path.write_text(json.dumps(_manifest(_asset(), _matrix(_asset())[:2]), ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["benchmark", "--asset", str(asset_path), "--cases", str(cases_path), "--manifest", str(manifest_path), "--out", str(out_path)])

    with pytest.raises(SystemExit) as exited:
        benchmark.main()
    assert exited.value.code != 0
    assert not out_path.exists()


def test_contract_benchmark_script_direct_help_imports_repo(tmp_path: Path) -> None:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "run_reviewed_workflow_v2_benchmark.py"

    completed = subprocess.run(
        [sys.executable, str(script_path), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--manifest" in completed.stdout
