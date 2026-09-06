from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path


CATALOG_PATH = Path(__file__).resolve().parents[1] / "configs" / "benchmarks" / "learning_selection_acceptance_v1.json"
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _catalog() -> dict[str, object]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def _outcomes(rows: list[dict[str, object]]) -> dict[str, int]:
    counts = Counter(str(row["baseline_outcome"]) for row in rows)
    return {outcome: counts[outcome] for outcome in ("correct", "wrong", "abstained")}


def test_catalog_has_exactly_pinned_joined_35_targets() -> None:
    catalog = _catalog()
    assert catalog["contract_version"] == "learning_selection_acceptance_catalog_v1"
    inference_rows = catalog["inference_rows"]
    scoring_rows = catalog["scoring_rows"]
    assert isinstance(inference_rows, list)
    assert isinstance(scoring_rows, list)
    assert len(inference_rows) == len(scoring_rows) == 35
    inference_keys = {(row["suite"], row["case_id"], row["target_id"]) for row in inference_rows}
    scoring_keys = {(row["suite"], row["case_id"], row["target_id"]) for row in scoring_rows}
    assert len(inference_keys) == len(scoring_keys) == 35
    assert inference_keys == scoring_keys
    for row in inference_rows:
        assert isinstance(row["target_text"], str) and row["target_text"]
        assert SHA256.fullmatch(str(row["image_sha256"]))
        assert len(row["image_size"]) == 2
        assert all(isinstance(value, int) and value > 0 for value in row["image_size"])
        assert row["source_manifest_refs"]


def test_catalog_pins_non_human_baseline_outcomes_and_lineage() -> None:
    catalog = _catalog()
    scoring_rows = catalog["scoring_rows"]
    assert isinstance(scoring_rows, list)
    assert _outcomes(scoring_rows) == {"correct": 26, "wrong": 0, "abstained": 9}
    fixed = [row for row in scoring_rows if row["suite"] == "fixed25"]
    public = [row for row in scoring_rows if row["suite"] == "public10"]
    assert _outcomes(fixed) == {"correct": 18, "wrong": 0, "abstained": 7}
    assert _outcomes(public) == {"correct": 8, "wrong": 0, "abstained": 2}
    assert all(row["human_correction_applied"] is False for row in scoring_rows)
    assert all(row["outcome_provenance"] == "recomputed_from_frozen_baseline_artifacts" for row in fixed)
    assert all(row["outcome_provenance"] == "recorded_public_chain_score" for row in public)
    for row in scoring_rows:
        ground_truth = row["ground_truth"]
        assert isinstance(ground_truth, dict)
        assert ground_truth["source_ref"]["path"]
        assert SHA256.fullmatch(ground_truth["source_ref"]["sha256"])
        scorer = row["scorer_source_ref"]
        assert scorer["path"] and SHA256.fullmatch(scorer["sha256"])
        source = row["prediction_source_ref"]
        if source is None:
            assert row["prior_prediction"] is None
            assert row["raw_prediction_sha256"] is None
        else:
            assert source["path"] and SHA256.fullmatch(source["sha256"])


def test_catalog_source_refs_are_sha_pinned() -> None:
    catalog = _catalog()
    refs = catalog["source_refs"]
    assert set(refs) == {
        "fixed_bindings", "fixed_roi_requests", "fixed_vista_report", "fixed_gold", "fixed_scorer",
        "public_manifest", "public_requests", "public_chain_score", "public_gold",
    }
    for reference in refs.values():
        assert reference["path"]
        assert SHA256.fullmatch(reference["sha256"])


def test_catalog_bytes_match_both_production_pins() -> None:
    from hashlib import sha256
    from app.learn.hybrid.static_capture import FROZEN_SELECTION_CATALOG_SHA256
    from scripts.run_learning_selection_acceptance import FROZEN_CATALOG_SHA256

    # 真实目录字节必须在 Git 检出后仍满足两个生产消费者的冻结身份。
    assert sha256(CATALOG_PATH.read_bytes()).hexdigest() == FROZEN_SELECTION_CATALOG_SHA256
    assert FROZEN_CATALOG_SHA256 == FROZEN_SELECTION_CATALOG_SHA256
