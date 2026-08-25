from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil

import pytest
from PIL import Image, ImageStat

from app.learn.hybrid.benchmark import contains_gold_fields
from scripts.seal_portfolio_hybrid_v1_1_corpus import (
    ANNOTATOR_IDENTITY_HASH,
    EXPECTED_CONTEXT_POLICY,
    EXPECTED_PROVIDER_REVISIONS,
    EXPECTED_SHARED_BUDGET,
    PENDING_REVIEWER_IDENTITY_HASH,
    _validate_gold_document,
    content_sha256,
    generate_synthetic_corpus,
    load_and_verify_corpus_seal,
    png_dimensions,
    provider_manifest_projection,
    verify_corpus_seal,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests/fixtures/portfolio_hybrid_v1_1"
MANIFEST = FIXTURE_ROOT / "corpus-manifest.v1.json"


def _manifest() -> dict[str, object]:
    return load_and_verify_corpus_seal(MANIFEST, root=ROOT)


def _copy_sealed_tree(tmp_path: Path, manifest: dict[str, object]) -> Path:
    for item in manifest["artifacts"].values():
        source = ROOT / item["path"]
        target = tmp_path / item["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    for screen in manifest["screenshots"]:
        source = ROOT / screen["path"]
        target = tmp_path / screen["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    target_manifest = tmp_path / "tests/fixtures/portfolio_hybrid_v1_1/corpus-manifest.v1.json"
    target_manifest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(MANIFEST, target_manifest)
    return target_manifest


def test_offline_synthetic_corpus_regeneration_is_deterministic(tmp_path: Path) -> None:
    first_root = tmp_path / "first/corpus"
    second_root = tmp_path / "second/corpus"
    first_gold = tmp_path / "first/gold.v1.json"
    second_gold = tmp_path / "second/gold.v1.json"
    first = generate_synthetic_corpus(first_root, first_gold)
    second = generate_synthetic_corpus(second_root, second_gold)
    assert first == second
    assert first_gold.read_bytes() == second_gold.read_bytes()
    assert [path.read_bytes() for path in sorted(first_root.rglob("*.png"))] == [
        path.read_bytes() for path in sorted(second_root.rglob("*.png"))
    ]


def test_offline_regeneration_matches_the_sealed_draft_bytes(tmp_path: Path) -> None:
    current_gold = json.loads((FIXTURE_ROOT / "gold.v1.json").read_text(encoding="utf-8"))
    regenerated_root = tmp_path / "corpus"
    regenerated_gold = tmp_path / "gold.v1.json"
    generate_synthetic_corpus(
        regenerated_root,
        regenerated_gold,
        reviewer_identity_hash=current_gold["targets"][0]["reviewer_identity_hash"],
        review_status=current_gold["review_state"],
    )
    assert regenerated_gold.read_bytes() == (FIXTURE_ROOT / "gold.v1.json").read_bytes()
    assert [path.read_bytes() for path in sorted(regenerated_root.rglob("*.png"))] == [
        path.read_bytes() for path in sorted((FIXTURE_ROOT / "corpus").rglob("*.png"))
    ]


def test_seal_has_exact_24_screen_enumeration_and_disjoint_partitions() -> None:
    manifest = _manifest()
    screens = manifest["screenshots"]
    assert len(screens) == 24
    expected = [
        f"tests/fixtures/portfolio_hybrid_v1_1/corpus/{partition}/case-{index:03d}.png"
        for partition, indexes in (("regression", range(1, 13)), ("holdout", range(13, 25)))
        for index in indexes
    ]
    assert [item["path"] for item in screens] == expected
    assert len({item["sha256"] for item in screens}) == 24
    regression = {item["screen_id"] for item in screens if item["partition"] == "regression"}
    holdout = {item["screen_id"] for item in screens if item["partition"] == "holdout"}
    assert len(regression) == len(holdout) == 12
    assert regression.isdisjoint(holdout)
    actual_pngs = sorted(
        path.relative_to(ROOT).as_posix()
        for path in (FIXTURE_ROOT / "corpus").rglob("*.png")
    )
    assert actual_pngs == sorted(expected)


def test_pngs_are_valid_fixed_size_and_targets_are_reviewable() -> None:
    manifest = _manifest()
    by_screen = {item["screen_id"]: item for item in manifest["screenshots"]}
    for screen in manifest["screenshots"]:
        assert png_dimensions(ROOT / screen["path"]) == (screen["width"], screen["height"])
        assert (screen["width"], screen["height"]) == (1280, 720)
        assert screen["source_kind"] == "privacy_safe_synthetic"
        assert screen["privacy_review_status"] in {"pending_independent_review", "approved"}
    assert sum(item["source_provenance"] == "existing_five_screen_regression" for item in manifest["screenshots"]) == 5
    for screen in manifest["screenshots"]:
        if screen["source_provenance"] == "existing_five_screen_regression":
            assert screen["partition"] == "regression"

    targets = manifest["gold_records"]
    assert 100 <= len(targets) <= 200
    assert sum(item["partition"] == "holdout" for item in targets) >= 50
    assert len({item["target_id"] for item in targets}) == len(targets)
    for target in targets:
        screen = by_screen[target["screen_id"]]
        assert target["partition"] == screen["partition"]
        assert target["important_target"] is True
        assert target["role"] in {"button", "checkbox", "combobox", "link", "menuitem", "tab", "textbox"}
        assert target["label"].strip()
        x1, y1, x2, y2 = target["bbox"]
        assert 0 <= x1 < x2 <= screen["width"]
        assert 0 <= y1 < y2 <= screen["height"]
        assert target["acceptable_regions"] == [target["bbox"]]
        assert target["review_status"] in {"pending_independent_review", "approved"}
        with Image.open(ROOT / screen["path"]) as image:
            crop = image.crop(tuple(target["bbox"]))
            assert all(low < high for low, high in ImageStat.Stat(crop).extrema)


def test_manifest_binds_all_frozen_inputs_and_canonical_gold() -> None:
    manifest = _manifest()
    assert manifest["contract_version"] == "portfolio_hybrid_v1_1_corpus_manifest_v1"
    assert manifest["provider_revisions"] == EXPECTED_PROVIDER_REVISIONS
    assert manifest["shared_budget"] == EXPECTED_SHARED_BUDGET
    assert manifest["shared_context_policy"] == EXPECTED_CONTEXT_POLICY
    assert set(manifest["artifacts"]) == {
        "gold", "gate_config", "benchmark_producer", "benchmark_runner", "scorer", "sealer"
    }
    assert manifest["gate_config_identity"]["artifact_sha256"] == manifest["artifacts"]["gate_config"]["sha256"]
    assert manifest["gold_records_sha256"] == content_sha256({"gold_records": manifest["gold_records"]})
    gold = json.loads((ROOT / manifest["artifacts"]["gold"]["path"]).read_text(encoding="utf-8"))
    assert gold["targets"] == manifest["gold_records"]


@pytest.mark.parametrize(("partition", "case_count"), [("regression", 60), ("holdout", 60)])
def test_sealed_partitions_have_no_predictions_and_provider_projection_has_no_gold(
    partition: str, case_count: int
) -> None:
    manifest = _manifest()
    assert manifest["prediction_counts"] == {"regression": 0, "holdout": 0, "total": 0}
    assert manifest["holdout_prediction_count"] == 0
    projection = provider_manifest_projection(manifest, partition=partition)
    assert not contains_gold_fields(projection)
    assert set(projection) == {
        "contract_version", "benchmark_ref", "corpus_id", "partition",
        "provider_revisions", "shared_budget", "shared_context_policy", "cases",
        "artifact_is_authorization", "execute_binding_enabled",
    }
    assert len(projection["cases"]) == case_count
    serialized = json.dumps(projection, ensure_ascii=False).casefold()
    for forbidden in ("gold", "annotator", "reviewer", "acceptable", "scorer", "private"):
        assert forbidden not in serialized


def test_fixture_tree_contains_no_prediction_artifact_or_sensitive_text() -> None:
    forbidden_names = {"prediction", "predictions", "provider-output", "provider_output"}
    for path in FIXTURE_ROOT.rglob("*"):
        assert not any(token in path.name.casefold() for token in forbidden_names)
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (FIXTURE_ROOT / "gold.v1.json", MANIFEST)
    ).casefold()
    for token in (
        "password", "secret", "api_key", "access_token", "private_key",
        "@gmail.com", "@outlook.com", "phone number", "credit card",
    ):
        assert token not in text


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    [
        ("provider_revisions", {**EXPECTED_PROVIDER_REVISIONS, "qwen": "mutated"}, "provider revisions"),
        ("shared_budget", {**EXPECTED_SHARED_BUDGET, "max_provider_calls_per_case": 4}, "shared budget"),
        ("shared_context_policy", {**EXPECTED_CONTEXT_POLICY, "ocr": "disabled"}, "context policy"),
    ],
)
def test_rehashed_model_budget_or_context_mutation_is_rejected(
    field: str, replacement: dict[str, object], message: str
) -> None:
    manifest = _manifest()
    mutated = deepcopy(manifest)
    mutated[field] = replacement
    mutated[f"{field}_sha256"] = content_sha256({field: replacement})
    mutated["content_sha256"] = content_sha256(
        {key: value for key, value in mutated.items() if key != "content_sha256"}
    )
    with pytest.raises(ValueError, match=message):
        verify_corpus_seal(mutated, root=ROOT)


def test_any_bound_artifact_or_screenshot_byte_mutation_is_rejected(tmp_path: Path) -> None:
    manifest = _manifest()
    copied_manifest = _copy_sealed_tree(tmp_path, manifest)
    copied = load_and_verify_corpus_seal(copied_manifest, root=tmp_path)
    mutations = [item["path"] for item in copied["artifacts"].values()]
    mutations.extend(item["path"] for item in copied["screenshots"])
    for relative in mutations:
        target = tmp_path / relative
        original = target.read_bytes()
        target.write_bytes(original + b"mutation")
        with pytest.raises(ValueError, match="artifact seal mismatch|screenshot seal mismatch"):
            load_and_verify_corpus_seal(copied_manifest, root=tmp_path)
        target.write_bytes(original)


def test_any_manifest_byte_mutation_is_rejected_even_if_json_value_is_unchanged(tmp_path: Path) -> None:
    copied_manifest = _copy_sealed_tree(tmp_path, _manifest())
    copied_manifest.write_bytes(copied_manifest.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="manifest bytes are not canonical"):
        load_and_verify_corpus_seal(copied_manifest, root=tmp_path)


@pytest.mark.parametrize(
    "reviewer_identity_hash",
    [PENDING_REVIEWER_IDENTITY_HASH, ANNOTATOR_IDENTITY_HASH],
)
def test_gold_validation_rejects_approved_with_non_independent_reviewer(
    reviewer_identity_hash: str,
) -> None:
    gold = json.loads((FIXTURE_ROOT / "gold.v1.json").read_text(encoding="utf-8"))
    gold["review_state"] = "approved"
    for target in gold["targets"]:
        target["review_status"] = "approved"
        target["reviewer_identity_hash"] = reviewer_identity_hash
    with pytest.raises(ValueError, match="approved review requires an independent reviewer identity"):
        _validate_gold_document(gold)


@pytest.mark.parametrize(
    "reviewer_identity_hash",
    [PENDING_REVIEWER_IDENTITY_HASH, ANNOTATOR_IDENTITY_HASH],
)
def test_seal_verification_rejects_approved_with_non_independent_reviewer(
    reviewer_identity_hash: str,
) -> None:
    manifest = _manifest()
    manifest["seal_state"] = "approved"
    manifest["reviewer_identity_hash"] = reviewer_identity_hash
    manifest["content_sha256"] = content_sha256(
        {key: value for key, value in manifest.items() if key != "content_sha256"}
    )
    with pytest.raises(ValueError, match="approved seal requires an independent reviewer identity"):
        verify_corpus_seal(manifest, root=ROOT)
