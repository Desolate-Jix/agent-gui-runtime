from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path

import pytest

from app.learn.hybrid.contracts import (
    load_hybrid_config,
    stable_candidate_id,
    validate_capture_identity,
    validate_fusion_result,
    validate_omni_inventory,
    validate_qwen_bindings,
    validate_vista_proposals,
)
from app.learn.recognition.uei.canonical import canonical_json_bytes, seal_immutable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
IMAGE_SHA = "ab" * 32
NON_AUTHORIZING = {
    "artifact_is_authorization": False,
    "execute_binding_enabled": False,
    "final_submit_forbidden": True,
    "real_action_requires_gate": True,
    "authorization_scope": "display_and_review_only",
}


def capture_fixture(*, image_sha: str = IMAGE_SHA) -> dict:
    artifact = seal_immutable(
        {
            "contract_version": "artifact_ref_v1",
            "artifact_id": "artifact/server-owned/capture-001.png",
            "artifact_sha256": image_sha,
            "media_type": "image/png",
            "byte_length": 4096,
            "restricted": True,
        }
    )
    artifact_ref = {
        "id": artifact["artifact_id"],
        "content_sha256": artifact["content_sha256"],
    }
    lineage = seal_immutable(
        {
            "contract_version": "capture_lineage_v1",
            "capture_id": "capture-001",
            "artifact_ref": artifact_ref,
            "artifact_sha256": image_sha,
            "image_size": {"width": 1280, "height": 720},
            "capture_coordinate_space": "capture_pixel_xyxy",
            "captured_at": "2026-08-25T00:00:00Z",
        }
    )
    return {
        "contract_version": "hybrid_capture_identity_v1",
        "capture_id": "capture-001",
        "capture_lineage_ref": {
            "id": lineage["capture_id"],
            "content_sha256": lineage["content_sha256"],
        },
        "capture_lineage": lineage,
        "artifact_ref": artifact_ref,
        "artifact": artifact,
        "artifact_sha256": image_sha,
        "screenshot_sha256": image_sha,
        "image_size": {"width": 1280, "height": 720},
        "capture_coordinate_space": "capture_pixel_xyxy",
        "captured_at": "2026-08-25T00:00:00Z",
        "workflow_revision": "workflow-rev-1",
    }


def inventory_fixture() -> dict:
    provider_result_ref = {"id": "result/omni-001", "content_sha256": "12" * 32}
    source_item_id = "omni-item-0"
    return {
        "contract_version": "hybrid_omni_inventory_v1",
        "capture_identity": capture_fixture(),
        "provider_result_ref": provider_result_ref,
        "provider_id": "omniparser_v2",
        "provider_revision": "omniparser-v2.0",
        "candidates": [
            {
                "candidate_id": stable_candidate_id(
                    provider_result_ref=provider_result_ref,
                    source_item_id=source_item_id,
                ),
                "provider_result_ref": provider_result_ref,
                "source_item_id": source_item_id,
                "bbox_original": [10, 20, 110, 70],
                "coordinate_space": "capture_pixel_xyxy",
                "confidence": 0.9,
                "active": True,
                "inactive_reason": None,
                "raw_provenance": {"source_index": 0},
            }
        ],
        **NON_AUTHORIZING,
    }


def binding_fixture(*, candidate_id: str | None = None, extra: dict | None = None) -> dict:
    inventory = inventory_fixture()
    binding = {
        "candidate_id": candidate_id or inventory["candidates"][0]["candidate_id"],
        "role": "button",
        "label": "Apply",
        "description": "opens the application flow",
        "semantic_confidence": 0.92,
        "task_relevance": 0.8,
        "relation": "primary_action",
        "ambiguity": None,
    }
    binding.update(extra or {})
    return {
        "contract_version": "hybrid_qwen_bindings_v1",
        "capture_identity": deepcopy(inventory["capture_identity"]),
        "bindings": [binding],
        "orphan_semantics": [],
        **NON_AUTHORIZING,
    }


def fusion_fixture(*, state: str = "BOUND", capture_identity: dict | None = None) -> dict:
    candidate_id = inventory_fixture()["candidates"][0]["candidate_id"]
    return {
        "contract_version": "hybrid_fusion_result_v1",
        "capture_identity": capture_identity or capture_fixture(),
        "config_sha256": "34" * 32,
        "candidates": [
            {
                "candidate_id": candidate_id,
                "state": state,
                "vista_eligible": state == "BOUND",
                "review_required": state != "BOUND",
                "reason": "unique_binding" if state == "BOUND" else "not_bound",
            }
        ],
        **NON_AUTHORIZING,
    }


def vista_fixture(*, state: str = "BOUND") -> dict:
    fusion = fusion_fixture(state=state)
    return {
        "contract_version": "hybrid_vista_proposals_v1",
        "capture_identity": deepcopy(fusion["capture_identity"]),
        "proposals": [
            {
                "candidate_id": fusion["candidates"][0]["candidate_id"],
                "fusion_state": state,
                "candidate_bbox_ref": {
                    "coordinate_space": "capture_pixel_xyxy",
                    "xyxy": [10, 20, 110, 70],
                },
                "roi_ref": {
                    "coordinate_space": "capture_pixel_xyxy",
                    "xyxy": [20, 25, 100, 65],
                },
                "point": {
                    "coordinate_space": "capture_pixel_xyxy",
                    "xy": [60, 45],
                },
                "confidence": 0.86,
                "evidence": ["vista-local"],
                "status": "PROPOSED",
                "review_required": True,
            }
        ],
        **NON_AUTHORIZING,
    }


def test_stable_candidate_id_is_canonical_and_deterministic():
    ref_a = {"id": "result/omni-001", "content_sha256": "12" * 32}
    ref_b = {"content_sha256": "12" * 32, "id": "result/omni-001"}
    expected_payload = {"provider_result_ref": ref_a, "source_item_id": "source-7"}
    expected = "candidate/" + hashlib.sha256(canonical_json_bytes(expected_payload)).hexdigest()

    assert stable_candidate_id(provider_result_ref=ref_a, source_item_id="source-7") == expected
    assert stable_candidate_id(provider_result_ref=ref_b, source_item_id="source-7") == expected
    assert stable_candidate_id(provider_result_ref=ref_a, source_item_id="source-8") != expected


def test_capture_lineage_object_hash_is_independent_from_image_hash():
    value = capture_fixture()

    assert value["capture_lineage_ref"]["content_sha256"] != value["screenshot_sha256"]
    assert validate_capture_identity(value) == value


def test_capture_rejects_lineage_that_names_different_artifact_sha():
    value = capture_fixture()
    value["capture_lineage"]["artifact_sha256"] = "cd" * 32
    value["capture_lineage"] = seal_immutable(value["capture_lineage"])
    value["capture_lineage_ref"]["content_sha256"] = value["capture_lineage"]["content_sha256"]

    with pytest.raises(ValueError, match="lineage artifact SHA mismatch"):
        validate_capture_identity(value)


def test_capture_requires_matching_artifact_and_screenshot_sha():
    value = capture_fixture()
    value["artifact_sha256"] = "ef" * 32

    with pytest.raises(ValueError, match="artifact_sha256 must equal screenshot_sha256"):
        validate_capture_identity(value)


def test_omni_inventory_rejects_duplicate_or_reused_candidate_ids():
    value = inventory_fixture()
    value["candidates"].append(deepcopy(value["candidates"][0]))
    with pytest.raises(ValueError, match="duplicate candidate_id"):
        validate_omni_inventory(value)

    value = inventory_fixture()
    value["candidates"][0]["candidate_id"] = "candidate/" + "ff" * 32
    with pytest.raises(ValueError, match="candidate_id does not match stable identity"):
        validate_omni_inventory(value)


def test_qwen_binding_is_candidate_id_closed_and_cannot_replace_geometry():
    with pytest.raises(ValueError, match="unknown candidate_id"):
        validate_qwen_bindings(binding_fixture(candidate_id="foreign"), inventory_fixture())
    with pytest.raises(ValueError, match="geometry is forbidden"):
        validate_qwen_bindings(
            binding_fixture(extra={"bbox": [1, 2, 3, 4]}),
            inventory_fixture(),
        )


def test_qwen_rejects_duplicate_candidate_binding():
    value = binding_fixture()
    value["bindings"].append(deepcopy(value["bindings"][0]))

    with pytest.raises(ValueError, match="duplicate candidate_id"):
        validate_qwen_bindings(value, inventory_fixture())


def test_conflicting_capture_lineage_refs_fail_closed():
    inventory = inventory_fixture()
    value = binding_fixture()
    value["capture_identity"] = capture_fixture(image_sha="cd" * 32)

    with pytest.raises(ValueError, match="conflicting capture identity"):
        validate_qwen_bindings(value, inventory)


def test_only_bound_fusion_candidate_is_vista_eligible():
    inventory = inventory_fixture()
    value = fusion_fixture(state="AMBIGUOUS")
    value["candidates"][0]["vista_eligible"] = True

    with pytest.raises(ValueError, match="non-BOUND candidate cannot be VISTA eligible"):
        validate_fusion_result(value, inventory)


def test_vista_rejects_non_bound_candidate_even_if_submitted():
    fusion = fusion_fixture(state="AMBIGUOUS")

    with pytest.raises(ValueError, match="VISTA requires BOUND fusion state"):
        validate_vista_proposals(vista_fixture(state="AMBIGUOUS"), fusion)


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("artifact_is_authorization", True),
        ("execute_binding_enabled", True),
        ("final_submit_forbidden", False),
        ("real_action_requires_gate", False),
        ("authorization_scope", "runtime"),
    ],
)
@pytest.mark.parametrize(
    ("validator", "value_factory", "context_factory"),
    [
        (validate_omni_inventory, inventory_fixture, None),
        (validate_qwen_bindings, binding_fixture, inventory_fixture),
        (validate_fusion_result, fusion_fixture, inventory_fixture),
        (validate_vista_proposals, vista_fixture, fusion_fixture),
    ],
)
def test_all_hybrid_contracts_enforce_non_authorizing_flags(
    field, bad_value, validator, value_factory, context_factory
):
    value = value_factory()
    value[field] = bad_value

    with pytest.raises(ValueError, match="non-authorizing invariant"):
        if context_factory is None:
            validator(value)
        else:
            validator(value, context_factory())


def test_geometry_uses_only_capture_pixel_xyxy_and_finite_numbers():
    inventory = inventory_fixture()
    inventory["candidates"][0]["coordinate_space"] = "normalized_xyxy"
    with pytest.raises(ValueError, match="capture_pixel_xyxy"):
        validate_omni_inventory(inventory)

    inventory = inventory_fixture()
    inventory["candidates"][0]["bbox_original"][2] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        validate_omni_inventory(inventory)


def test_validators_return_deep_copies():
    source = inventory_fixture()
    validated = validate_omni_inventory(source)
    validated["candidates"][0]["bbox_original"][0] = 999

    assert source["candidates"][0]["bbox_original"][0] == 10


def test_load_hybrid_config_is_versioned_closed_and_non_authorizing():
    config = load_hybrid_config(PROJECT_ROOT)

    assert config["contract_version"] == "learn_hybrid_config_v1_1"
    assert config["model_order"] == [
        "capture",
        "omniparser",
        "qwen",
        "deterministic_fusion",
        "vista",
        "human_review",
    ]
    assert config["coordinate_space"] == "capture_pixel_xyxy"
    assert config["fusion"]["vista_eligible_states"] == ["BOUND"]
    assert config["artifact_is_authorization"] is False
    assert config["execute_binding_enabled"] is False
    assert len(config["config_sha256"]) == 64
