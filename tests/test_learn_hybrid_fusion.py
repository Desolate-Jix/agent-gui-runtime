from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path

import pytest

from app.learn.hybrid.contracts import load_hybrid_config
from app.learn.recognition.uei.canonical import canonical_json_bytes, seal_immutable
from tests.test_learn_hybrid_contracts import binding_fixture, inventory_fixture


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _inputs(*, candidate_count: int = 1) -> tuple[dict, dict, dict, dict]:
    inventory = inventory_fixture(candidate_count=candidate_count)
    bindings = binding_fixture(inventory=inventory)
    bundle = {"capture_identity": deepcopy(inventory["capture_identity"])}
    return load_hybrid_config(PROJECT_ROOT), bundle, inventory, bindings


def _fuse(*, config: dict, bundle: dict, inventory: dict, bindings: dict) -> dict:
    from app.learn.hybrid.fusion import fuse_hybrid_candidates

    return fuse_hybrid_candidates(
        config=config,
        capture_bundle=bundle,
        omni_inventory=inventory,
        qwen_bindings=bindings,
    )


@pytest.mark.parametrize(
    ("state", "expected_review", "expected_eligible"),
    [
        ("BOUND", False, True),
        ("AMBIGUOUS", True, False),
        ("CONFLICT", True, False),
        ("ORPHAN", True, False),
        ("ORPHAN_SEMANTIC", True, False),
        ("LOW_CONFIDENCE", True, False),
        ("UNBOUND", True, False),
        ("CAPTURE_MISMATCH", True, False),
        ("REVIEW_REQUIRED", True, False),
    ],
)
def test_review_policy_is_closed_and_only_bound_is_vista_eligible(
    state: str,
    expected_review: bool,
    expected_eligible: bool,
) -> None:
    from app.learn.hybrid.fusion import fusion_review_policy

    assert fusion_review_policy(state) == {
        "review_required": expected_review,
        "vista_eligible": expected_eligible,
    }


def test_unique_exact_binding_at_threshold_is_bound_and_config_sha_is_included() -> None:
    config, bundle, inventory, bindings = _inputs()
    bindings["bindings"][0]["semantic_confidence"] = config["fusion"][
        "semantic_confidence_threshold"
    ]

    result = _fuse(
        config=config,
        bundle=bundle,
        inventory=inventory,
        bindings=bindings,
    )

    assert result["config_sha256"] == config["config_sha256"]
    assert result["candidates"][0]["state"] == "BOUND"
    assert result["candidates"][0]["reason"] == "unique_exact_binding"
    assert result["candidates"][0]["vista_eligible"] is True
    assert result["candidates"][0]["review_required"] is False


def test_below_configured_semantic_threshold_is_low_confidence() -> None:
    config, bundle, inventory, bindings = _inputs()
    bindings["bindings"][0]["semantic_confidence"] = (
        config["fusion"]["semantic_confidence_threshold"] - 0.01
    )

    record = _fuse(
        config=config,
        bundle=bundle,
        inventory=inventory,
        bindings=bindings,
    )["candidates"][0]

    assert record["state"] == "LOW_CONFIDENCE"
    assert record["review_required"] is True
    assert record["vista_eligible"] is False


def test_semantic_threshold_is_read_from_the_sealed_config() -> None:
    config, bundle, inventory, bindings = _inputs()
    config["fusion"]["semantic_confidence_threshold"] = 0.95
    config_without_sha = {key: value for key, value in config.items() if key != "config_sha256"}
    config["config_sha256"] = hashlib.sha256(
        canonical_json_bytes(config_without_sha)
    ).hexdigest()

    record = _fuse(
        config=config,
        bundle=bundle,
        inventory=inventory,
        bindings=bindings,
    )["candidates"][0]

    assert bindings["bindings"][0]["semantic_confidence"] == 0.92
    assert record["state"] == "LOW_CONFIDENCE"


def test_explicit_binding_disagreement_is_conflict_and_never_upgrades_from_context() -> None:
    config, bundle, inventory, bindings = _inputs()
    bindings["bindings"][0]["ambiguity"] = "OCR_UIA_DISAGREEMENT"

    record = _fuse(
        config=config,
        bundle=bundle,
        inventory=inventory,
        bindings=bindings,
    )["candidates"][0]

    assert record["state"] == "CONFLICT"
    assert record["review_required"] is True
    assert record["vista_eligible"] is False


@pytest.mark.parametrize(
    ("confidence_delta", "expected_state"),
    [(0.05, "AMBIGUOUS"), (0.051, "CONFLICT")],
)
def test_duplicate_overlapping_semantic_relation_uses_configured_tie_delta(
    confidence_delta: float,
    expected_state: str,
) -> None:
    config, bundle, inventory, bindings = _inputs(candidate_count=2)
    second = inventory["candidates"][1]
    second["bbox_original"] = deepcopy(inventory["candidates"][0]["bbox_original"])
    second_item = inventory["provider_result"]["items"][1]
    second_item["capture_bbox"] = deepcopy(second["bbox_original"])
    inventory["provider_result"] = seal_immutable(
        {k: deepcopy(v) for k, v in inventory["provider_result"].items() if k != "content_sha256"}
    )
    inventory["provider_result_ref"] = {
        "id": inventory["provider_result"]["result_id"],
        "content_sha256": inventory["provider_result"]["content_sha256"],
    }
    for candidate in inventory["candidates"]:
        candidate["provider_result_ref"] = deepcopy(inventory["provider_result_ref"])
        candidate["provenance"] = seal_immutable(
            {
                "contract_version": "hybrid_candidate_provenance_v1",
                "provider_result_ref": deepcopy(inventory["provider_result_ref"]),
                "source_item_id": candidate["source_item_id"],
            }
        )
    # 稳定 ID 依赖 provider-result 引用，因此沿用既有生成器重建。
    from app.learn.hybrid.contracts import stable_candidate_id

    for candidate, binding in zip(inventory["candidates"], bindings["bindings"], strict=True):
        candidate["candidate_id"] = stable_candidate_id(
            provider_result_ref=inventory["provider_result_ref"],
            source_item_id=candidate["source_item_id"],
        )
        binding["candidate_id"] = candidate["candidate_id"]
        binding["role"] = "button"
        binding["label"] = "Apply"
        binding["relation"] = "primary_action"
    bindings["capture_identity"] = deepcopy(inventory["capture_identity"])
    bindings["bindings"][0]["semantic_confidence"] = 0.90
    bindings["bindings"][1]["semantic_confidence"] = 0.90 - confidence_delta

    states = [
        item["state"]
        for item in _fuse(
            config=config,
            bundle=bundle,
            inventory=inventory,
            bindings=bindings,
        )["candidates"]
    ]

    assert states == [expected_state, expected_state]


def test_non_overlapping_duplicate_semantic_relation_is_conflict() -> None:
    config, bundle, inventory, bindings = _inputs(candidate_count=2)
    for binding in bindings["bindings"]:
        binding.update({"role": "button", "label": "Apply", "relation": "primary_action"})

    states = [
        item["state"]
        for item in _fuse(
            config=config,
            bundle=bundle,
            inventory=inventory,
            bindings=bindings,
        )["candidates"]
    ]

    assert states == ["CONFLICT", "CONFLICT"]


def test_inactive_filter_and_missing_binding_preserve_candidate_records() -> None:
    config, bundle, inventory, bindings = _inputs(candidate_count=2)
    inventory["candidates"][0]["active"] = False
    inventory["candidates"][0]["inactive_reason"] = "filtered_by_provider_policy"
    bindings["bindings"] = [bindings["bindings"][0]]

    result = _fuse(
        config=config,
        bundle=bundle,
        inventory=inventory,
        bindings=bindings,
    )

    assert len(result["candidates"]) == len(inventory["candidates"])
    assert result["candidates"][0]["state"] == "UNBOUND"
    assert result["candidates"][0]["reason"] == "inactive:filtered_by_provider_policy"
    assert result["candidates"][1]["state"] == "UNBOUND"
    assert result["candidates"][1]["reason"] == "missing_qwen_binding"


def test_uia_or_ocr_context_without_qwen_binding_cannot_upgrade_to_bound() -> None:
    config, bundle, inventory, bindings = _inputs()
    bundle["context"] = {
        "sources": [
            {"source_kind": "uia", "candidate_id": inventory["candidates"][0]["candidate_id"]},
            {"source_kind": "ocr", "candidate_id": inventory["candidates"][0]["candidate_id"]},
        ]
    }
    bindings["bindings"] = []

    record = _fuse(
        config=config,
        bundle=bundle,
        inventory=inventory,
        bindings=bindings,
    )["candidates"][0]

    assert record["state"] == "UNBOUND"
    assert record["vista_eligible"] is False


def test_orphan_semantic_forces_review_without_fabricating_or_deleting_candidates() -> None:
    config, bundle, inventory, bindings = _inputs(candidate_count=2)
    bindings["orphan_semantics"] = [
        {
            "semantic_id": "semantic/missing-apply",
            "role": "button",
            "label": "Apply",
            "description": "important element has no Omni candidate",
            "reason": "ORPHAN_SEMANTIC",
        }
    ]

    result = _fuse(
        config=config,
        bundle=bundle,
        inventory=inventory,
        bindings=bindings,
    )

    assert [item["candidate_id"] for item in result["candidates"]] == [
        item["candidate_id"] for item in inventory["candidates"]
    ]
    assert {item["state"] for item in result["candidates"]} == {"REVIEW_REQUIRED"}
    assert all(item["reason"] == "orphan_semantic_requires_review" for item in result["candidates"])


def test_result_order_geometry_provenance_and_inputs_are_deterministic_and_immutable() -> None:
    config, bundle, inventory, bindings = _inputs(candidate_count=3)
    bindings["bindings"].reverse()
    before = canonical_json_bytes(
        {"config": config, "bundle": bundle, "inventory": inventory, "bindings": bindings}
    )

    first = _fuse(config=config, bundle=bundle, inventory=inventory, bindings=bindings)
    second = _fuse(config=config, bundle=bundle, inventory=inventory, bindings=bindings)

    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert [item["candidate_id"] for item in first["candidates"]] == [
        item["candidate_id"] for item in inventory["candidates"]
    ]
    assert [canonical_json_bytes(item["bbox_original"]) for item in first["candidates"]] == [
        canonical_json_bytes(item["bbox_original"]) for item in inventory["candidates"]
    ]
    assert canonical_json_bytes(
        {"config": config, "bundle": bundle, "inventory": inventory, "bindings": bindings}
    ) == before


def test_sealed_inventory_and_bindings_are_accepted_but_tampering_is_rejected() -> None:
    config, bundle, inventory, bindings = _inputs()
    sealed_inventory = seal_immutable(inventory)
    sealed_bindings = seal_immutable(bindings)

    assert _fuse(
        config=config,
        bundle=bundle,
        inventory=sealed_inventory,
        bindings=sealed_bindings,
    )["candidates"][0]["state"] == "BOUND"

    sealed_inventory["candidates"][0]["active"] = False
    with pytest.raises(ValueError, match="content_sha256"):
        _fuse(
            config=config,
            bundle=bundle,
            inventory=sealed_inventory,
            bindings=sealed_bindings,
        )


def test_valid_cross_capture_bundle_becomes_review_required_capture_mismatch() -> None:
    from tests.test_learn_hybrid_contracts import capture_fixture

    config, bundle, inventory, bindings = _inputs()
    bundle["capture_identity"] = capture_fixture(image_sha="cd" * 32)

    result = _fuse(
        config=config,
        bundle=bundle,
        inventory=inventory,
        bindings=bindings,
    )

    assert {item["state"] for item in result["candidates"]} == {"CAPTURE_MISMATCH"}
    assert all(item["review_required"] is True for item in result["candidates"])
    assert all(item["vista_eligible"] is False for item in result["candidates"])


def test_malformed_capture_identity_is_rejected() -> None:
    config, bundle, inventory, bindings = _inputs()
    bundle["capture_identity"]["capture_id"] = "capture-other"

    with pytest.raises(ValueError, match="capture identity"):
        _fuse(
            config=config,
            bundle=bundle,
            inventory=inventory,
            bindings=bindings,
        )
