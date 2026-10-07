import json
from pathlib import Path

import pytest

from app.learning_memory.benchmark_manifest import (
    FAMILIES, digest, freeze_manifest, load_manifest, verify_candidate,
)


def candidate(tmp_path):
    root = tmp_path / "candidate"
    scoring = root / "app/learning_memory/benchmark_scoring.py"
    scoring.parent.mkdir(parents=True)
    scoring.write_text("SCORE = 1\n", encoding="utf-8")
    script = root / "scripts/benchmark.py"
    script.parent.mkdir(parents=True)
    script.write_text("RUN = 1\n", encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname='sample'\n", encoding="utf-8")
    artifact = tmp_path / "recipe.json"
    artifact.write_text('{"version": 1}', encoding="utf-8")
    return root, artifact


def pilot_spec(artifact):
    value = spec(artifact)
    value["purpose"] = "pilot"
    value["cases"] = [case for case in value["cases"]
                      if case["task_family"] == FAMILIES[0]
                      and int(case["case_id"].rsplit("-", 1)[1]) < 2]
    for case in value["cases"]:
        case["routes"] = ["A", "C"]
    return value


def test_pilot_freezes_six_pairs_without_formal_quota(tmp_path):
    root, artifact = candidate(tmp_path)
    path = tmp_path / "pilot.json"
    frozen = freeze_manifest(pilot_spec(artifact), root=root, destination=path)
    assert load_manifest(path)["purpose"] == "pilot"
    verify_candidate(frozen, root=root)
    assert len(frozen["cases"]) == 6


@pytest.mark.parametrize("change", ["missing", "extra", "family", "b", "negative", "formal", "invalid"])
def test_pilot_does_not_weaken_formal_or_accept_invalid_cohorts(tmp_path, change):
    from copy import deepcopy
    root, artifact = candidate(tmp_path)
    value = pilot_spec(artifact)
    if change == "missing":
        value["cases"].pop()
    elif change == "extra":
        extra = deepcopy(value["cases"][0]); extra["case_id"] = "extra"
        value["cases"].append(extra)
    elif change == "family":
        value["cases"][0]["task_family"] = FAMILIES[1]
    elif change == "b":
        value["cases"][0]["routes"].append("B")
    elif change == "negative":
        value["cases"][0].update(variation="negative", is_negative=True)
    else:
        value["purpose"] = "formal" if change == "formal" else "unknown"
    with pytest.raises(ValueError):
        freeze_manifest(value, root=root, destination=tmp_path / "bad.json")


def test_explicit_formal_and_legacy_manifest_hashes_remain_valid(tmp_path):
    root, artifact = candidate(tmp_path)
    legacy = freeze_manifest(spec(artifact), root=root, destination=tmp_path / "legacy.json")
    assert "purpose" not in legacy
    assert load_manifest(tmp_path / "legacy.json") == legacy
    value = spec(artifact); value["purpose"] = "formal"
    explicit = freeze_manifest(value, root=root, destination=tmp_path / "formal.json")
    assert load_manifest(tmp_path / "formal.json") == explicit


def test_purpose_remains_inside_frozen_hash(tmp_path):
    root, artifact = candidate(tmp_path)
    path = tmp_path / "formal.json"
    value = spec(artifact); value["purpose"] = "formal"
    frozen = freeze_manifest(value, root=root, destination=path)
    frozen.pop("purpose")
    path.write_text(json.dumps(frozen), encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        load_manifest(path)


def spec(artifact):
    cases = []
    for family in FAMILIES:
        for variation, count in (("stable", 8), ("unseen", 6), ("layout", 6)):
            for index in range(count):
                cases.append({"case_id": f"{family}-{variation}-{index}", "task_family": family,
                              "variation": variation, "cohort": "scored", "seed": index,
                              "inputs": {"key": f"value-{index}"},
                              "success_rule": {"all": [{"path": ["result", "value"], "equals": "value"}]},
                              "timeout_seconds": 10, "cold_or_warm": "warm", "is_negative": False,
                              "routes": ["A", "C", "B"] if variation == "stable" and index < 5 else ["C", "A"]})
    return {"benchmark_id": "freeze-001", "model": {"source": "agent_current", "model": "same-model",
            "config_digest": "a" * 64}, "cases": cases,
            "artifacts": [{"kind": "recipe", "path": str(artifact.resolve()), "version": "v1"}]}


def test_freeze_load_and_verify_exact_candidate(tmp_path):
    root, artifact = candidate(tmp_path)
    path = tmp_path / "manifest.json"
    frozen = freeze_manifest(spec(artifact), root=root, destination=path)
    assert frozen == load_manifest(path)
    assert frozen["manifest_sha256"] == digest({k: v for k, v in frozen.items() if k != "manifest_sha256"})
    assert set(frozen["source_files"]) == {"app/learning_memory/benchmark_scoring.py", "scripts/benchmark.py", "pyproject.toml"}
    assert frozen["scoring_sha256"] == frozen["source_files"]["app/learning_memory/benchmark_scoring.py"]
    assert "content" not in frozen["artifacts"][0]
    verify_candidate(frozen, root=root)
    with pytest.raises(FileExistsError):
        freeze_manifest(spec(artifact), root=root, destination=path)


@pytest.mark.parametrize("change", ["edit", "delete", "add", "artifact"])
def test_source_or_named_artifact_drift_rejected(tmp_path, change):
    root, artifact = candidate(tmp_path)
    frozen = freeze_manifest(spec(artifact), root=root, destination=tmp_path / "manifest.json")
    if change == "edit":
        (root / "scripts/benchmark.py").write_text("RUN = 2\n", encoding="utf-8")
    elif change == "delete":
        (root / "scripts/benchmark.py").unlink()
    elif change == "add":
        (root / "app/new.py").write_text("NEW = 1\n", encoding="utf-8")
    else:
        artifact.write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="changed|drift|missing"):
        verify_candidate(frozen, root=root)


def test_manifest_checksum_and_shape_drift_rejected(tmp_path):
    root, artifact = candidate(tmp_path)
    path = tmp_path / "manifest.json"
    freeze_manifest(spec(artifact), root=root, destination=path)
    value = json.loads(path.read_text(encoding="utf-8"))
    value["cases"][0]["seed"] = 999
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="checksum|digest|changed"):
        load_manifest(path)


def test_quota_cannot_use_retries_negative_or_warmup(tmp_path):
    root, artifact = candidate(tmp_path)
    value = spec(artifact)
    value["cases"] = [case for case in value["cases"] if case["case_id"] != f"{FAMILIES[0]}-stable-0"]
    value["cases"].append({**value["cases"][0], "case_id": "negative-1", "variation": "negative", "is_negative": True})
    with pytest.raises(ValueError, match="quota"):
        freeze_manifest(value, root=root, destination=tmp_path / "manifest.json")


def test_cold_warm_negative_and_warmup_validation(tmp_path):
    root, artifact = candidate(tmp_path)
    value = spec(artifact)
    value["cases"][0]["cold_or_warm"] = "ambient"
    with pytest.raises(ValueError, match="cold_or_warm"):
        freeze_manifest(value, root=root, destination=tmp_path / "invalid.json")
    value = spec(artifact)
    value["cases"][0]["is_negative"] = True
    with pytest.raises(ValueError, match="negative"):
        freeze_manifest(value, root=root, destination=tmp_path / "invalid.json")
    value = spec(artifact)
    for index in range(4):
        value["cases"].append({**value["cases"][0], "case_id": f"warmup-{index}",
                               "cohort": "warmup", "routes": ["A", "C"]})
    with pytest.raises(ValueError, match="warmup"):
        freeze_manifest(value, root=root, destination=tmp_path / "invalid.json")


def test_empty_artifact_list_is_allowed(tmp_path):
    root, artifact = candidate(tmp_path)
    value = spec(artifact)
    value["artifacts"] = []
    frozen = freeze_manifest(value, root=root, destination=tmp_path / "manifest.json")
    verify_candidate(frozen, root=root)


def test_success_rule_requires_explicit_receipt_paths(tmp_path):
    root, artifact = candidate(tmp_path)
    value = spec(artifact)
    value["cases"][0]["success_rule"] = {"all": [{"path": [], "equals": True}]}
    with pytest.raises(ValueError, match="success_rule"):
        freeze_manifest(value, root=root, destination=tmp_path / "invalid.json")


def test_existing_learning_app_fixture_is_part_of_source_snapshot(tmp_path):
    root, artifact = candidate(tmp_path)
    fixture = root / "tests/fixtures/learning_workflow_app.py"
    fixture.parent.mkdir(parents=True)
    fixture.write_text("APP = 1\n", encoding="utf-8")
    frozen = freeze_manifest(spec(artifact), root=root, destination=tmp_path / "manifest.json")
    assert "tests/fixtures/learning_workflow_app.py" in frozen["source_files"]
    fixture.write_text("APP = 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="source changed"):
        verify_candidate(frozen, root=root)
