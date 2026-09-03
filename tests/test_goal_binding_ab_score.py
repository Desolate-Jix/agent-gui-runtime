from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from app.learn.recognition.uei.canonical import seal_immutable


_INCUMBENT = "qwen3_vl_8b_q4_k_m"


def _cleanup(provider: str = _INCUMBENT) -> dict[str, object]:
    return {
        "contract_version": "simple_native_provider_cleanup_v1",
        "provider": provider,
        "verified": True,
        "cleanup_status": "verified",
        "owned_processes": [],
        "provider_processes_after": [],
        "helper_processes_after": [],
        "orphan_descendant_pids": [],
        "active_listeners_after": [],
        "lease_files_after": [],
    }


def _write_inputs(tmp_path: Path, *, statuses: tuple[str, ...] = ("BOUND",) * 5, region_bound: bool = False) -> tuple[Path, Path]:
    snapshot_ref = {"id": "omni-snapshot/test", "sha256": "a" * 64}
    cases: list[dict[str, object]] = []
    targets: list[dict[str, object]] = []
    for case_number in range(1, 6):
        case_id = f"case-{case_number:03d}"
        capture_ref = {"id": f"capture/{case_id}", "sha256": f"{case_number:x}" * 64}
        goals: list[dict[str, object]] = []
        trace: list[dict[str, object]] = []
        for goal_index, status in enumerate(statuses):
            label = f"target-{goal_index + 1}"
            goal = {
                "goal_id": f"{case_id}/goal-{goal_index + 1:02d}",
                "goal_text": f"Select the button labeled '{label}'",
                "semantic_role": "button",
                "semantic_label": label,
            }
            goals.append(goal)
            correct_id = f"candidate/{case_id}/{goal_index + 1:02d}"
            selected_id = correct_id if status == "BOUND" else None
            bbox = [10, 10, 30, 30]
            if status == "BOUND" and goal_index == 1 and not region_bound:
                selected_id, bbox = "candidate/wrong", [50, 50, 70, 70]
            elif status == "BOUND" and goal_index == 1 and region_bound:
                selected_id = "candidate/not-listed"
            binding = {
                "contract_version": "goal_binding_provider_result_v1",
                "goal_index": goal_index,
                "candidate_index": goal_index if status == "BOUND" else None,
                "candidate_id": selected_id,
                "status": status,
                "reason": None if status == "BOUND" else ("provider_abstained" if status == "UNBOUND" else "malformed_native_output"),
                "binding_basis": "direct_candidate_index" if status in {"BOUND", "UNBOUND"} else "native_point",
                "confidence": 0.9 if status != "PROVIDER_FAILURE" else None,
                "canonical_capture_pixel_point": None,
                "provider_id": _INCUMBENT,
                "native_output_ref": {"id": f"native/{case_id}/{goal_index}", "sha256": "b" * 64},
                "omni_snapshot_ref": snapshot_ref,
                "capture_ref": capture_ref,
                "artifact_is_authorization": False,
            }
            selected = None if status != "BOUND" else {
                "candidate_id": selected_id,
                "candidate_index": goal_index,
                "bbox_original": bbox,
                "center_capture_pixel": [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2],
                "capture_ref": capture_ref,
                "omni_snapshot_ref": snapshot_ref,
            }
            trace.append({
                "slot": "binder", **goal,
                "native_raw": "{}",
                "native_raw_sha256": "c" * 64,
                "native_parsed": {"status": "ok"} if status != "PROVIDER_FAILURE" else None,
                "native_parsed_sha256": "d" * 64 if status != "PROVIDER_FAILURE" else None,
                "canonical_binding": binding,
                "canonical_binding_sha256": "e" * 64,
                "selected_candidate": selected,
                "native_error": None,
                "native_error_sha256": None,
                "parent_capture_id": capture_ref["id"].split("/", 1)[1],
                "parent_omni_snapshot_ref": snapshot_ref,
            })
            targets.append({
                "screen_id": case_id,
                "role": "button",
                "label": label,
                "goal": goal["goal_text"],
                "partition": "regression",
                "acceptable_candidate_ids": [correct_id],
                "acceptable_regions": [[10, 10, 30, 30]],
            })
        cases.append({
            "case_id": case_id,
            "goal_count": 5,
            "goals": goals,
            "capture": {
                "capture_id": capture_ref["id"].split("/", 1)[1],
                "screenshot_sha256": capture_ref["sha256"],
                "image_size": {"width": 100, "height": 80},
                "capture_path": str(tmp_path / f"{case_id}.png"),
            },
            "trace": trace,
        })
    valid_count = sum(status != "PROVIDER_FAILURE" for status in statuses) * 5
    payload = seal_immutable({
        "contract_version": "simple_native_provider_diagnostic_v2",
        "regression_diagnostic_only": True,
        "promotion_eligible": False,
        "screen_count": 5,
        "target_count": 25,
        "metrics": {
            "denominator": 25,
            "binder": {"attempted": 25, "schema_valid": valid_count, "schema_invalid": 25 - valid_count, "timeout": 0, "latency_p50_ms": 1, "latency_p95_ms": 2, "raw_output_bytes": 50},
            "vista": {"attempted": 0, "schema_valid": 0, "schema_invalid": 0, "timeout": 0, "latency_p50_ms": 0, "latency_p95_ms": 0, "raw_output_bytes": 0},
            "omni": {"attempted": 0, "schema_valid": 0, "schema_invalid": 0, "timeout": 0, "latency_p50_ms": 0, "latency_p95_ms": 0, "raw_output_bytes": 0},
            "abstained": 0,
            "correct_selected": 0,
            "wrong_selected": 0,
        },
        "cases": cases,
        "provider_phase_cleanup": [_cleanup()],
        "cleanup_receipt": _cleanup(),
        "action_candidates": [],
        "artifact_is_authorization": False,
        "execute_binding": False,
        "arm_id": "arm-a",
        "provider_id": _INCUMBENT,
        "omni_snapshot_ref": snapshot_ref,
    })
    artifact = tmp_path / "provider-diagnostic.json"
    artifact.write_text(json.dumps(payload), encoding="utf-8")
    gold = tmp_path / "gold.json"
    gold.write_text(json.dumps({"targets": targets}), encoding="utf-8")
    return artifact, gold


def test_binder_scorer_reads_gold_only_after_artifact_is_finalized(tmp_path: Path) -> None:
    from app.learn.hybrid.goal_binding_ab_score import score_goal_binding_arm

    artifact, _ = _write_inputs(tmp_path)
    raw = json.loads(artifact.read_text(encoding="utf-8")); raw.pop("content_sha256")
    artifact.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="finalized"):
        score_goal_binding_arm(provider_artifact=artifact, gold_path=tmp_path / "must-not-open.json")


def test_binder_score_counts_correct_wrong_unbound_and_provider_failure_over_25(tmp_path: Path) -> None:
    from app.learn.hybrid.goal_binding_ab_score import score_goal_binding_arm

    artifact, gold = _write_inputs(tmp_path, statuses=("BOUND", "BOUND", "UNBOUND", "PROVIDER_FAILURE", "UNBOUND"))
    report = score_goal_binding_arm(provider_artifact=artifact, gold_path=gold)
    assert report["metrics"]["correct"] == {"numerator": 5, "denominator": 25}
    assert report["metrics"]["wrong"] == {"numerator": 5, "denominator": 25}
    assert report["metrics"]["unbound_abstain"] == {"numerator": 10, "denominator": 25}
    assert report["metrics"]["provider_failure_abstain"] == {"numerator": 5, "denominator": 25}


def test_correctness_matches_frozen_acceptable_candidate_or_region_rule(tmp_path: Path) -> None:
    from app.learn.hybrid.goal_binding_ab_score import score_goal_binding_arm

    artifact, gold = _write_inputs(tmp_path, region_bound=True)
    report = score_goal_binding_arm(provider_artifact=artifact, gold_path=gold)
    assert report["metrics"]["correct"] == {"numerator": 25, "denominator": 25}
    assert report["metrics"]["wrong"] == {"numerator": 0, "denominator": 25}


def test_scorer_rejects_resealed_non_deterministic_selected_geometry(tmp_path: Path) -> None:
    from app.learn.hybrid.goal_binding_ab_score import score_goal_binding_arm

    artifact, gold = _write_inputs(tmp_path)
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    payload["cases"][0]["trace"][1]["selected_candidate"]["center_capture_pixel"] = [20, 20]
    artifact.write_text(json.dumps(seal_immutable({key: value for key, value in payload.items() if key != "content_sha256"})), encoding="utf-8")
    with pytest.raises(ValueError, match="geometry"):
        score_goal_binding_arm(provider_artifact=artifact, gold_path=gold)


def test_scorer_projects_real_frozen_gold_to_the_five_frozen_cases(tmp_path: Path) -> None:
    from app.learn.hybrid.goal_binding_ab_score import score_goal_binding_arm

    artifact, _ = _write_inputs(tmp_path, region_bound=True)
    real_gold = Path(__file__).parent / "fixtures" / "portfolio_hybrid_v1_1" / "gold.v1.json"
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    records = json.loads(real_gold.read_text(encoding="utf-8"))["targets"]
    wanted = {f"case-{number:03d}" for number in range(1, 6)}
    by_case = {
        case_id: [record for record in records if record["partition"] == "regression" and record["screen_id"] == case_id]
        for case_id in wanted
    }
    for case in payload["cases"]:
        for index, target in enumerate(by_case[case["case_id"]]):
            goal = case["goals"][index]
            goal.update({"goal_text": target["goal"], "semantic_role": target["role"], "semantic_label": target["label"]})
            binder = case["trace"][index]
            binder.update(goal)
            binding = binder["canonical_binding"]
            binding.update({"goal_index": index, "candidate_index": index, "candidate_id": target["acceptable_candidate_ids"][0], "provider_id": _INCUMBENT})
            bbox = target["acceptable_regions"][0]
            binder["selected_candidate"].update({
                "candidate_id": binding["candidate_id"], "candidate_index": index,
                "bbox_original": bbox,
                "center_capture_pixel": [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2],
            })
    artifact.write_text(json.dumps(seal_immutable({key: value for key, value in payload.items() if key != "content_sha256"})), encoding="utf-8")
    report = score_goal_binding_arm(provider_artifact=artifact, gold_path=real_gold)
    assert report["metrics"]["correct"] == {"numerator": 25, "denominator": 25}


def test_scorer_rejects_resealed_binding_provider_or_goal_index_mismatch(tmp_path: Path) -> None:
    from app.learn.hybrid.goal_binding_ab_score import score_goal_binding_arm

    artifact, gold = _write_inputs(tmp_path)
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    binding = payload["cases"][0]["trace"][0]["canonical_binding"]
    binding.update({"provider_id": "other-provider", "binding_basis": "native_point", "canonical_capture_pixel_point": [20, 20]})
    artifact.write_text(json.dumps(seal_immutable({key: value for key, value in payload.items() if key != "content_sha256"})), encoding="utf-8")
    with pytest.raises(ValueError, match="provider provenance"):
        score_goal_binding_arm(provider_artifact=artifact, gold_path=gold)
    artifact, gold = _write_inputs(tmp_path)
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    payload["cases"][0]["trace"][0]["canonical_binding"]["goal_index"] = 4
    artifact.write_text(json.dumps(seal_immutable({key: value for key, value in payload.items() if key != "content_sha256"})), encoding="utf-8")
    with pytest.raises(ValueError, match="goal provenance"):
        score_goal_binding_arm(provider_artifact=artifact, gold_path=gold)


def test_scorer_uses_one_artifact_byte_read_before_opening_gold(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.learn.hybrid.goal_binding_ab_score import score_goal_binding_arm

    artifact, gold = _write_inputs(tmp_path)
    original = artifact.read_bytes()
    real_read_bytes = Path.read_bytes
    real_read_text = Path.read_text
    calls = 0

    def read_bytes_once(path: Path) -> bytes:
        nonlocal calls
        if path == artifact:
            calls += 1
            if calls > 1:
                raise AssertionError("provider artifact was reread")
            artifact.write_bytes(original + b" ")
            return original
        return real_read_bytes(path)

    def reject_artifact_text_read(path: Path, *args: object, **kwargs: object) -> str:
        if path == artifact:
            raise AssertionError("provider artifact text was read separately")
        return real_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", read_bytes_once)
    monkeypatch.setattr(Path, "read_text", reject_artifact_text_read)
    report = score_goal_binding_arm(provider_artifact=artifact, gold_path=gold)
    assert calls == 1
    assert report["provider_artifact_sha256"] == sha256(original).hexdigest()


def test_hard_gate_requires_zero_wrong_25_parse_10_correct_and_zero_residue() -> None:
    from app.learn.hybrid.goal_binding_ab_score import evaluate_binding_hard_gate

    receipt = _cleanup()
    report = {"arm_id": "arm-a", "provider_id": _INCUMBENT, "cleanup_receipt": receipt, "metrics": {"wrong": {"numerator": 0, "denominator": 25}, "native_parse_success": {"numerator": 25, "denominator": 25}, "correct": {"numerator": 10, "denominator": 25}}}
    assert evaluate_binding_hard_gate(binder_report=report, cleanup_receipt=_cleanup())["passed"] is True
    assert evaluate_binding_hard_gate(binder_report=deepcopy(report) | {"metrics": deepcopy(report["metrics"]) | {"wrong": {"numerator": 1, "denominator": 25}}}, cleanup_receipt=_cleanup())["passed"] is False
    assert evaluate_binding_hard_gate(binder_report=report, cleanup_receipt=_cleanup() | {"lease_files_after": ["x"]})["passed"] is False
    assert evaluate_binding_hard_gate(binder_report=report, cleanup_receipt=_cleanup("other-provider"))["passed"] is False


def test_numeric_score_never_promotes_failed_safety_gate(tmp_path: Path) -> None:
    from app.learn.hybrid.goal_binding_ab_score import build_goal_binding_matrix, score_goal_binding_arm

    artifact, gold = _write_inputs(tmp_path)
    report = score_goal_binding_arm(provider_artifact=artifact, gold_path=gold)
    report["metrics"]["wrong"] = {"numerator": 1, "denominator": 25}
    matrix = build_goal_binding_matrix(arm_reports=[report])
    assert matrix["winner_arm_id"] is None
    assert matrix["arms"][0]["presentation_score"] is None


def test_presentation_weights_total_100_for_passers_only(tmp_path: Path) -> None:
    from app.learn.hybrid.goal_binding_ab_score import build_goal_binding_matrix, score_goal_binding_arm

    artifact, gold = _write_inputs(tmp_path, region_bound=True)
    report = score_goal_binding_arm(provider_artifact=artifact, gold_path=gold)
    report["metrics"]["end_to_end_correct"] = {"numerator": 25, "denominator": 25}
    report["metrics"]["protocol_stability"] = {"numerator": 25, "denominator": 25}
    report["metrics"]["latency_score"] = {"numerator": 25, "denominator": 25}
    report["metrics"]["peak_vram_score"] = {"numerator": 25, "denominator": 25}
    report["metrics"]["vista_gain"] = {"numerator": 25, "denominator": 25}
    report["metrics"]["lifecycle_cleanup"] = {"numerator": 25, "denominator": 25}
    matrix = build_goal_binding_matrix(arm_reports=[report])
    assert matrix["arms"][0]["presentation_score"] == 100


def test_matrix_rejects_mixed_snapshot_or_capture_lineage(tmp_path: Path) -> None:
    from app.learn.hybrid.goal_binding_ab_score import build_goal_binding_matrix, score_goal_binding_arm

    artifact, gold = _write_inputs(tmp_path)
    first = score_goal_binding_arm(provider_artifact=artifact, gold_path=gold)
    second = deepcopy(first); second["arm_id"] = "arm-b"; second["omni_snapshot_ref"]["sha256"] = "f" * 64
    with pytest.raises(ValueError, match="snapshot"):
        build_goal_binding_matrix(arm_reports=[first, second])


def test_matrix_is_regression_only_non_authorizing_and_no_holdout(tmp_path: Path) -> None:
    from app.learn.hybrid.goal_binding_ab_score import build_goal_binding_matrix, score_goal_binding_arm

    artifact, gold = _write_inputs(tmp_path)
    report = score_goal_binding_arm(provider_artifact=artifact, gold_path=gold)
    matrix = build_goal_binding_matrix(arm_reports=[report])
    assert matrix["regression_diagnostic_only"] is True
    assert matrix["artifact_is_authorization"] is False
    assert matrix["contains_holdout"] is False
    bad = deepcopy(report); bad["contains_holdout"] = True
    with pytest.raises(ValueError, match="holdout"):
        build_goal_binding_matrix(arm_reports=[bad])
    bad = deepcopy(report); bad["execute_binding"] = True
    with pytest.raises(ValueError, match="authorizing"):
        build_goal_binding_matrix(arm_reports=[bad])
