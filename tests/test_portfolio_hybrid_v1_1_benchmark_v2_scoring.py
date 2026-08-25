from __future__ import annotations

from copy import deepcopy
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "score_portfolio_hybrid_v1_1_benchmark_v2_private.py"
GATE = ROOT / "configs" / "benchmarks" / "portfolio_hybrid_v1_1_gate.v2.json"
SAFETY = {"artifact_is_authorization": False, "execute_binding_enabled": False, "display_only": True}


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def ref(name: str, value: object | None = None) -> dict[str, str]:
    return {"id": name, "content_sha256": hashlib.sha256(canonical(value if value is not None else name)).hexdigest()}


def write_json(path: Path, value: object) -> None:
    path.write_bytes(canonical(value) + b"\n")


def automatic_row(case: str, arm: str, target: str, *, status: str = "validated") -> dict[str, object]:
    shared = {
        "case_id": case,
        "arm_id": arm,
        "selected_target_id": target,
        "candidate_id": f"candidate/{case}",
        "target_binding_ref": f"binding/{case}",
        "eligibility": "ELIGIBLE",
        "fusion_ref": f"fusion/{case}",
        "capture_ref": f"capture/{case}",
        "bbox_ref": f"bbox/{case}",
        "bbox": [0, 0, 2, 2],
        "vista_request_ref": f"request/{case}",
        "submission_status": "SUBMITTED",
    }
    if arm == "omni_to_qwen_vista":
        shared["vista_result"] = {
            "status": status,
            "proposal_lineage": {key: shared[key] for key in (
                "case_id", "selected_target_id", "vista_request_ref", "candidate_id",
                "fusion_ref", "capture_ref", "target_binding_ref", "bbox_ref",
            )},
            "canonical_capture_pixel_point": [3, 3] if case == "opaque/1" else [1, 1],
        }
    return shared


def private_fixture() -> dict[str, object]:
    parent = ref("parent/seal")
    return {
        "contract_version": "portfolio_hybrid_v1_1_private_manifest_v2_synthetic",
        "source_parent_ref": parent,
        "partition": "holdout",
        "cases": [
            {"case_id": "opaque/1", "target_id": "target/right/1", "important": True, "acceptable_regions": [[2, 2, 4, 4]]},
            {"case_id": "opaque/2", "target_id": "target/right/2", "important": True, "acceptable_regions": [[0, 0, 2, 2]]},
        ],
    }


def prediction_run() -> tuple[dict[str, object], dict[str, object]]:
    private = private_fixture()
    rows = []
    for case, target in (("opaque/1", "target/right/1"), ("opaque/2", "target/right/2")):
        for arm in ("qwen_only", "omni_only_discovery", "omni_to_qwen", "omni_to_qwen_vista"):
            selected = target
            if arm == "qwen_only" and case == "opaque/1":
                selected = "target/wrong"
            rows.append(automatic_row(case, arm, selected))
    lifecycle = {
        "contract_version": "benchmark_v2_lifecycle_receipt_v1",
        "id": "lifecycle/1",
        "content_sha256": "a" * 64,
        "complete": True,
        "lifecycle_verified": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    run = {
        "contract_version": "benchmark_v2_prediction_run_v1",
        "source_parent_ref": deepcopy(private["source_parent_ref"]),
        "partition": "holdout",
        "attempt_ref": ref("attempt/1"),
        "lifecycle_ref": {"id": lifecycle["id"], "content_sha256": lifecycle["content_sha256"]},
        "regression_precondition_ref": {"id": "regression/1", "content_sha256": "b" * 64, "status": "PASS"},
        "pre_review_rows": rows,
        "vista_proposals": [row["vista_result"] for row in rows if row["arm_id"] == "omni_to_qwen_vista"],
        "safety": deepcopy(SAFETY),
    }
    return run, lifecycle


def run_scorer(tmp_path: Path, private: dict[str, object], run: dict[str, object], lifecycle: dict[str, object]) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    private_path, run_path, life_path = (tmp_path / name for name in ("private.json", "run.json", "life.json"))
    output_path, public_path = tmp_path / "private-output.json", tmp_path / "public-ref.json"
    for path, value in ((private_path, private), (run_path, run), (life_path, lifecycle)):
        write_json(path, value)
    process = subprocess.run(
        [sys.executable, str(SCRIPT), "--private-manifest", str(private_path), "--prediction-run", str(run_path), "--lifecycle", str(life_path), "--private-output", str(output_path), "--public-ref", str(public_path)],
        cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", close_fds=True, check=False,
    )
    return process, output_path, public_path


def test_prediction_record_pre_review_is_immutable_and_review_chain_is_append_only() -> None:
    from app.learn.hybrid.benchmark_v2_predictions import append_review_decisions, seal_automatic_prediction
    pre = {"contract_version": "benchmark_v2_pre_review_v1", "prediction_id": "prediction/1", "rows": [automatic_row("opaque/1", "omni_to_qwen_vista", "target/1")], "safety": deepcopy(SAFETY)}
    record = seal_automatic_prediction(request_ref=ref("request/run"), pre_review=pre, execution_refs=[ref("execution/1")], lifecycle_ref=ref("lifecycle/1"))
    original_ref = deepcopy(record["pre_review_ref"])
    decision = {"decision_id": "decision/1", "predecessor_ref": record["revision_ref"], "target_binding_ref": "binding/opaque/1", "disposition": "corrected", "replacement_candidate_id": "candidate/reviewed"}
    revised = append_review_decisions(record, [decision])
    assert revised["pre_review_ref"] == original_ref
    assert revised["post_review"]["rows"][0]["candidate_id"] == "candidate/reviewed"
    assert revised["decisions"][0]["predecessor_ref"] == record["revision_ref"]
    assert canonical(append_review_decisions(revised, [decision])) == canonical(revised)
    tampered = deepcopy(revised); tampered["pre_review_ref"]["content_sha256"] = "0" * 64
    with pytest.raises(ValueError): append_review_decisions(tampered, [])


def test_prediction_requires_exact_binding_candidate_eligibility_and_vista_reason() -> None:
    from app.learn.hybrid.benchmark_v2_predictions import seal_automatic_prediction
    pre = {"contract_version": "benchmark_v2_pre_review_v1", "prediction_id": "prediction/1", "rows": [automatic_row("opaque/1", "omni_to_qwen_vista", "target/1")], "safety": deepcopy(SAFETY)}
    for mutate in ("missing_binding", "unsent", "ineligible_request", "missing_reason"):
        changed = deepcopy(pre); row = changed["rows"][0]
        if mutate == "missing_binding": row.pop("target_binding_ref")
        elif mutate == "unsent": row["submission_status"] = "NOT_SUBMITTED"
        elif mutate == "ineligible_request": row["eligibility"] = "INELIGIBLE"
        else:
            row["eligibility"] = "INELIGIBLE"; row.pop("vista_request_ref"); row.pop("submission_status")
        with pytest.raises(ValueError): seal_automatic_prediction(request_ref=ref("request/run"), pre_review=changed, execution_refs=[ref("execution/1")], lifecycle_ref=ref("lifecycle/1"))


def test_private_scorer_uses_automatic_rows_and_emits_only_public_ref(tmp_path: Path) -> None:
    private = private_fixture(); run, lifecycle = prediction_run()
    process, output, public = run_scorer(tmp_path, private, run, lifecycle)
    assert process.returncode == 0, process.stderr
    assert process.stdout.count("\n") == 1
    stdout_ref = json.loads(process.stdout)
    assert stdout_ref == json.loads(public.read_text(encoding="utf-8"))
    assert set(stdout_ref) == {"status", "score_ref", "content_sha256", "artifact_is_authorization", "execute_binding_enabled"}
    assert "opaque/" not in public.read_text(encoding="utf-8")
    score = json.loads(output.read_text(encoding="utf-8"))
    assert score["automatic"]["wrong_target_count"] == 0
    assert score["point_metric"] == {"gain_numerator": 1, "submitted_count": 2, "gain": "1/2"}
    assert score["gate"]["status"] == "PASS"
    assert score["safety"] == SAFETY


def test_human_review_cannot_hide_automatic_error(tmp_path: Path) -> None:
    private = private_fixture(); run, lifecycle = prediction_run()
    bad = next(row for row in run["pre_review_rows"] if row["case_id"] == "opaque/1" and row["arm_id"] == "omni_to_qwen_vista")
    bad["selected_target_id"] = "target/wrong"
    bad["vista_result"]["proposal_lineage"]["selected_target_id"] = "target/wrong"
    run["post_review_rows"] = deepcopy(run["pre_review_rows"])
    next(row for row in run["post_review_rows"] if row["case_id"] == "opaque/1" and row["arm_id"] == "omni_to_qwen_vista")["selected_target_id"] = "target/right/1"
    process, output, _ = run_scorer(tmp_path, private, run, lifecycle)
    assert process.returncode == 0
    assert json.loads(output.read_text(encoding="utf-8"))["gate"]["status"] == "FAIL"


@pytest.mark.parametrize("mutation", ["duplicate", "missing", "same_sha_wrong_lineage", "unsent", "cross_target", "extra_better", "zero_submitted"])
def test_private_scorer_fails_closed_on_invalid_run(tmp_path: Path, mutation: str) -> None:
    private = private_fixture(); run, lifecycle = prediction_run()
    if mutation == "duplicate": run["pre_review_rows"].append(deepcopy(run["pre_review_rows"][0]))
    elif mutation == "missing": run["pre_review_rows"].pop()
    elif mutation == "same_sha_wrong_lineage": run["source_parent_ref"]["id"] = "parent/wrong"
    elif mutation == "unsent": next(row for row in run["pre_review_rows"] if row["arm_id"] == "omni_to_qwen_vista")["submission_status"] = "NOT_SUBMITTED"
    elif mutation == "cross_target": next(row for row in run["pre_review_rows"] if row["arm_id"] == "omni_to_qwen_vista")["target_binding_ref"] = "binding/other"
    elif mutation == "extra_better": run["vista_proposals"].append({**deepcopy(run["vista_proposals"][0]), "canonical_capture_pixel_point": [2, 2]})
    else:
        for row in run["pre_review_rows"]:
            if row["arm_id"] in {"omni_to_qwen", "omni_to_qwen_vista"}:
                row["eligibility"] = "INELIGIBLE"; row.pop("vista_request_ref"); row.pop("submission_status"); row["ineligible_reason"] = "no_candidate"; row.pop("vista_result", None)
        run["vista_proposals"] = []
    process, _, _ = run_scorer(tmp_path, private, run, lifecycle)
    assert process.returncode != 0
    sensitive = json.dumps(private, sort_keys=True)
    assert all(token not in process.stderr for token in ("opaque/1", "target/right/1", str(tmp_path), sensitive))


def test_failed_vista_remains_in_denominator_and_regression_is_precondition(tmp_path: Path) -> None:
    private = private_fixture(); run, lifecycle = prediction_run()
    vista = next(row for row in run["pre_review_rows"] if row["case_id"] == "opaque/2" and row["arm_id"] == "omni_to_qwen_vista")
    vista["vista_result"] = {"status": "timeout", "proposal_lineage": vista["vista_result"]["proposal_lineage"]}
    run["vista_proposals"] = [row["vista_result"] for row in run["pre_review_rows"] if row["arm_id"] == "omni_to_qwen_vista"]
    process, output, _ = run_scorer(tmp_path, private, run, lifecycle)
    assert process.returncode == 0
    assert json.loads(output.read_text(encoding="utf-8"))["point_metric"]["submitted_count"] == 2
    run["regression_precondition_ref"]["status"] = "FAIL"
    process, _, _ = run_scorer(tmp_path / "again", private, run, lifecycle)
    assert process.returncode != 0


def test_gate_and_import_boundary_are_closed_non_authorizing() -> None:
    gate = json.loads(GATE.read_text(encoding="utf-8"))
    assert gate["automatic_split"] == "pre_review"
    assert gate["holdout_role"] == "automatic_gate"
    assert gate["regression_role"] == "precondition_only"
    assert gate["safety"] == SAFETY
    prediction_tree = ast.parse((ROOT / "app/learn/hybrid/benchmark_v2_predictions.py").read_text(encoding="utf-8"))
    imports = {node.module for node in ast.walk(prediction_tree) if isinstance(node, ast.ImportFrom)}
    assert "app.learn.hybrid.benchmark_scorer_v2" not in imports
    raw = GATE.read_text(encoding="utf-8").casefold()
    assert "click_point" not in raw and "runtime" not in raw
