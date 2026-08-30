from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from app.learn.hybrid.contracts import (
    SEMANTIC_TARGET_IDENTITY_VERSION,
    canonical_semantic_target_key,
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


def inventory_fixture(
    *, candidate_count: int = 1, provider_confidence: int | float | None = 0.9
) -> dict:
    capture = capture_fixture()
    provider_id = "local.runtime/omniparser"
    profile_id = "local.runtime/omniparser/shadow-v2"
    generic_ref = {"id": "synthetic/ref", "content_sha256": "12" * 32}
    items = []
    for index in range(candidate_count):
        left = 10 + (index * 120)
        items.append(
            {
                "source_item_id": f"omni-item-{index}",
                "source_id_origin": "provider",
                "kind": "element",
                "safe_text": f"candidate {index}",
                "safe_role": "button",
                "safe_states": [],
                "source_bbox": [left, 20, left + 100, 70],
                "capture_bbox": [left, 20, left + 100, 70],
                "source_coordinate_space": "capture_pixel_xyxy",
                "coordinate_transform_ref": None,
                "opaque_attributes": {},
                "provider_confidence": provider_confidence,
            }
        )
    provider_result = seal_immutable(
        {
            "contract_version": "provider_safe_result_v1",
            "result_id": "result/omni-001",
            "request_ref": generic_ref,
            "requested_provider_id": provider_id,
            "requested_profile_id": profile_id,
            "registration_resolution": "resolved",
            "manifest_resolution": "resolved",
            "registration_ref": generic_ref,
            "manifest_ref": generic_ref,
            "provider_id": provider_id,
            "profile_id": profile_id,
            "provider_version": "omniparser-v2.0",
            "capture_lineage_ref": deepcopy(capture["capture_lineage_ref"]),
            "status": "success",
            "review_only": True,
            "items": items,
            "redaction_summary": {
                "redacted_item_count": 0,
                "redacted_field_count": 0,
                "secret_detected": False,
                "sensitive_categories": [],
            },
        }
    )
    provider_result_ref = {
        "id": provider_result["result_id"],
        "content_sha256": provider_result["content_sha256"],
    }
    candidates = []
    for item in items:
        source_item_id = item["source_item_id"]
        provenance = seal_immutable(
            {
                "contract_version": "hybrid_candidate_provenance_v1",
                "provider_result_ref": provider_result_ref,
                "source_item_id": source_item_id,
            }
        )
        candidates.append(
            {
                "candidate_id": stable_candidate_id(
                    provider_result_ref=provider_result_ref,
                    source_item_id=source_item_id,
                ),
                "provider_result_ref": provider_result_ref,
                "source_item_id": source_item_id,
                "bbox_original": deepcopy(item["capture_bbox"]),
                "coordinate_space": "capture_pixel_xyxy",
                "confidence": item["provider_confidence"],
                "active": True,
                "inactive_reason": None,
                "provenance": provenance,
            }
        )
    return {
        "contract_version": "hybrid_omni_inventory_v1",
        "capture_identity": capture,
        "provider_result_ref": provider_result_ref,
        "provider_result": provider_result,
        "provider_id": provider_id,
        "provider_revision": "omniparser-v2.0",
        "candidates": candidates,
        **NON_AUTHORIZING,
    }


def binding_fixture(
    *,
    candidate_id: str | None = None,
    extra: dict | None = None,
    inventory: dict | None = None,
) -> dict:
    inventory = inventory or inventory_fixture()
    bindings = []
    for index, candidate in enumerate(inventory["candidates"]):
        binding = {
            "candidate_id": candidate_id or candidate["candidate_id"],
            "role": "button",
            "label": f"Apply {index}",
            "description": "opens the application flow",
            "semantic_confidence": 0.92,
            "task_relevance": 0.8,
            "relation": "primary_action",
            "ambiguity": None,
        }
        binding.update(extra or {})
        bindings.append(binding)
    return {
        "contract_version": "hybrid_qwen_bindings_v1",
        "capture_identity": deepcopy(inventory["capture_identity"]),
        "context_ref": {"id": "hybrid-context/test", "content_sha256": "56" * 32},
        "semantic_target_identity_version": SEMANTIC_TARGET_IDENTITY_VERSION,
        "bindings": bindings,
        "ambiguity_sets": [],
        "orphan_semantics": [],
        **NON_AUTHORIZING,
    }


def fusion_fixture(
    *,
    state: str = "BOUND",
    capture_identity: dict | None = None,
    inventory: dict | None = None,
) -> dict:
    inventory = inventory or inventory_fixture()
    return {
        "contract_version": "hybrid_fusion_result_v1",
        "capture_identity": capture_identity or deepcopy(inventory["capture_identity"]),
        "config_sha256": "34" * 32,
        "candidates": [
            {
                "candidate_id": candidate["candidate_id"],
                "bbox_original": deepcopy(candidate["bbox_original"]),
                "coordinate_space": "capture_pixel_xyxy",
                "active": candidate["active"],
                "inactive_reason": candidate["inactive_reason"],
                "state": state,
                "vista_eligible": state == "BOUND",
                "review_required": state != "BOUND",
                "reason": "unique_binding" if state == "BOUND" else "not_bound",
            }
            for candidate in inventory["candidates"]
        ],
        **NON_AUTHORIZING,
    }


def test_semantic_target_identity_is_shared_versioned_and_canonical() -> None:
    left = {
        "role": " Button ",
        "label": "ＡＰＰＬＹ",
        "description": "  Open   flow ",
        "relation": " Primary_Action ",
    }
    right = {
        "role": "button",
        "label": "apply",
        "description": "open flow",
        "relation": "primary_action",
    }

    assert SEMANTIC_TARGET_IDENTITY_VERSION == "hybrid_semantic_target_identity_v1"
    assert canonical_semantic_target_key(left) == canonical_semantic_target_key(right)


def test_fusion_filtering_fact_must_copy_omni_active_and_reason_exactly() -> None:
    inventory = inventory_fixture()
    bindings = binding_fixture(inventory=inventory)
    fusion = fusion_fixture(inventory=inventory)
    fusion["candidates"][0]["active"] = False

    with pytest.raises(ValueError, match="active fact"):
        validate_fusion_result(fusion, inventory, bindings)

    fusion = fusion_fixture(inventory=inventory)
    fusion["candidates"][0]["inactive_reason"] = "invented"
    with pytest.raises(ValueError, match="inactive_reason"):
        validate_fusion_result(fusion, inventory, bindings)


def permitted_roi_fixture(inventory: dict) -> dict:
    candidate = inventory["candidates"][0]
    return seal_immutable(
        {
            "contract_version": "hybrid_permitted_roi_v1",
            "roi_id": "roi/candidate-001",
            "candidate_id": candidate["candidate_id"],
            "capture_lineage_ref": deepcopy(inventory["capture_identity"]["capture_lineage_ref"]),
            "coordinate_space": "capture_pixel_xyxy",
            "xyxy": [20, 25, 100, 65],
            "permitted_for_refinement": True,
        }
    )


def vista_fixture(*, state: str = "BOUND", inventory: dict | None = None) -> dict:
    inventory = inventory or inventory_fixture()
    fusion = fusion_fixture(state=state, inventory=inventory)
    candidate = inventory["candidates"][0]
    candidate_bbox_ref = seal_immutable(
        {
            "contract_version": "hybrid_candidate_bbox_ref_v1",
            "candidate_id": candidate["candidate_id"],
            "provider_result_ref": candidate["provider_result_ref"],
            "coordinate_space": "capture_pixel_xyxy",
            "xyxy": deepcopy(candidate["bbox_original"]),
        }
    )
    roi_ref = permitted_roi_fixture(inventory)
    return {
        "contract_version": "hybrid_vista_proposals_v1",
        "capture_identity": deepcopy(fusion["capture_identity"]),
        "proposals": [
            {
                "candidate_id": candidate["candidate_id"],
                "fusion_state": state,
                "candidate_bbox_ref": candidate_bbox_ref,
                "roi_ref": roi_ref,
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


def test_omni_inventory_preserves_null_provider_confidence_and_requires_exact_match() -> None:
    value = inventory_fixture(provider_confidence=None)

    validated = validate_omni_inventory(value)

    assert validated["candidates"][0]["confidence"] is None
    assert validated["provider_result"]["items"][0]["provider_confidence"] is None

    mismatched = inventory_fixture(provider_confidence=None)
    mismatched["candidates"][0]["confidence"] = 0.0
    with pytest.raises(ValueError, match="immutable provider result"):
        validate_omni_inventory(mismatched)


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
    bindings = binding_fixture(inventory=inventory)
    value = fusion_fixture(state="AMBIGUOUS")
    value["candidates"][0]["vista_eligible"] = True

    with pytest.raises(ValueError, match="non-BOUND candidate cannot be VISTA eligible"):
        validate_fusion_result(value, inventory, bindings)


def test_vista_rejects_non_bound_candidate_even_if_submitted():
    inventory = inventory_fixture()
    bindings = binding_fixture(inventory=inventory)
    fusion = fusion_fixture(state="AMBIGUOUS", inventory=inventory)

    with pytest.raises(ValueError, match="VISTA requires BOUND fusion state"):
        validate_vista_proposals(
            vista_fixture(state="AMBIGUOUS", inventory=inventory),
            fusion,
            inventory,
            bindings,
            {},
        )


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
        (validate_omni_inventory, inventory_fixture, lambda: ()),
        (validate_qwen_bindings, binding_fixture, lambda: (inventory_fixture(),)),
        (
            validate_fusion_result,
            fusion_fixture,
            lambda: (inventory_fixture(), binding_fixture()),
        ),
        (
            validate_vista_proposals,
            vista_fixture,
            lambda: (
                fusion_fixture(),
                inventory_fixture(),
                binding_fixture(),
                {
                    inventory_fixture()["candidates"][0]["candidate_id"]:
                    permitted_roi_fixture(inventory_fixture())
                },
            ),
        ),
    ],
)
def test_all_hybrid_contracts_enforce_non_authorizing_flags(
    field, bad_value, validator, value_factory, context_factory
):
    value = value_factory()
    value[field] = bad_value

    with pytest.raises(ValueError, match="non-authorizing invariant"):
        validator(value, *context_factory())


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


def test_omni_rejects_cross_capture_provider_result():
    inventory = inventory_fixture()
    other_capture = capture_fixture(image_sha="cd" * 32)
    inventory["provider_result"]["capture_lineage_ref"] = other_capture["capture_lineage_ref"]
    inventory["provider_result"] = seal_immutable(inventory["provider_result"])
    inventory["provider_result_ref"] = {
        "id": inventory["provider_result"]["result_id"],
        "content_sha256": inventory["provider_result"]["content_sha256"],
    }

    with pytest.raises(ValueError, match="provider result capture identity mismatch"):
        validate_omni_inventory(inventory)


def test_omni_rejects_provider_derived_bbox_outside_capture_bounds():
    inventory = inventory_fixture()
    inventory["provider_result"]["items"][0]["capture_bbox"] = [10, 20, 1300, 70]
    inventory["provider_result"] = seal_immutable(inventory["provider_result"])
    provider_ref = {
        "id": inventory["provider_result"]["result_id"],
        "content_sha256": inventory["provider_result"]["content_sha256"],
    }
    candidate = inventory["candidates"][0]
    candidate["provider_result_ref"] = provider_ref
    candidate["bbox_original"] = [10, 20, 1300, 70]
    candidate["candidate_id"] = stable_candidate_id(
        provider_result_ref=provider_ref, source_item_id=candidate["source_item_id"]
    )
    candidate["provenance"] = seal_immutable(
        {
            "contract_version": "hybrid_candidate_provenance_v1",
            "provider_result_ref": provider_ref,
            "source_item_id": candidate["source_item_id"],
        }
    )
    inventory["provider_result_ref"] = provider_ref

    with pytest.raises(ValueError, match="inside capture bounds"):
        validate_omni_inventory(inventory)


def test_fusion_requires_exact_inventory_coverage_and_qwen_binding():
    inventory = inventory_fixture(candidate_count=2)
    bindings = binding_fixture(inventory=inventory)
    fusion = fusion_fixture(inventory=inventory)
    fusion["candidates"].pop()

    with pytest.raises(ValueError, match="exact Omni candidate coverage"):
        validate_fusion_result(fusion, inventory, bindings)

    fusion = fusion_fixture(inventory=inventory)
    bindings["bindings"] = []
    with pytest.raises(ValueError, match="BOUND requires one valid Qwen binding"):
        validate_fusion_result(fusion, inventory, bindings)


def test_vista_rejects_forged_id_and_geometry_substitution():
    inventory = inventory_fixture()
    bindings = binding_fixture(inventory=inventory)
    fusion = fusion_fixture(inventory=inventory)

    forged = vista_fixture(inventory=inventory)
    forged["proposals"][0]["candidate_id"] = "candidate/" + "ff" * 32
    with pytest.raises(ValueError, match="unknown candidate_id"):
        validate_vista_proposals(
            forged,
            fusion,
            inventory,
            bindings,
            {inventory["candidates"][0]["candidate_id"]: permitted_roi_fixture(inventory)},
        )

    replaced = vista_fixture(inventory=inventory)
    replaced_bbox = replaced["proposals"][0]["candidate_bbox_ref"]
    replaced_bbox["xyxy"] = [11, 20, 110, 70]
    replaced["proposals"][0]["candidate_bbox_ref"] = seal_immutable(replaced_bbox)
    with pytest.raises(ValueError, match="candidate bbox substitution"):
        validate_vista_proposals(
            replaced,
            fusion,
            inventory,
            bindings,
            {inventory["candidates"][0]["candidate_id"]: permitted_roi_fixture(inventory)},
        )


def test_vista_rejects_unsealed_or_out_of_capture_roi_and_outside_point():
    inventory = inventory_fixture()
    bindings = binding_fixture(inventory=inventory)
    fusion = fusion_fixture(inventory=inventory)

    unsealed = vista_fixture(inventory=inventory)
    unsealed["proposals"][0]["roi_ref"]["xyxy"][0] = 19
    with pytest.raises(ValueError, match="ROI content_sha256 mismatch"):
        validate_vista_proposals(
            unsealed,
            fusion,
            inventory,
            bindings,
            {inventory["candidates"][0]["candidate_id"]: permitted_roi_fixture(inventory)},
        )

    substituted = vista_fixture(inventory=inventory)
    substituted_roi = substituted["proposals"][0]["roi_ref"]
    substituted_roi["xyxy"] = [21, 25, 100, 65]
    substituted["proposals"][0]["roi_ref"] = seal_immutable(substituted_roi)
    with pytest.raises(ValueError, match="does not match permitted ROI"):
        validate_vista_proposals(
            substituted,
            fusion,
            inventory,
            bindings,
            {inventory["candidates"][0]["candidate_id"]: permitted_roi_fixture(inventory)},
        )

    outside_capture = vista_fixture(inventory=inventory)
    roi = outside_capture["proposals"][0]["roi_ref"]
    roi["xyxy"] = [20, 25, 1300, 65]
    outside_capture["proposals"][0]["roi_ref"] = seal_immutable(roi)
    with pytest.raises(ValueError, match="ROI must be inside capture bounds"):
        validate_vista_proposals(
            outside_capture,
            fusion,
            inventory,
            bindings,
            {inventory["candidates"][0]["candidate_id"]: outside_capture["proposals"][0]["roi_ref"]},
        )

    outside_point = vista_fixture(inventory=inventory)
    outside_point["proposals"][0]["point"]["xy"] = [5, 5]
    with pytest.raises(ValueError, match="inside ROI and candidate bbox"):
        validate_vista_proposals(
            outside_point,
            fusion,
            inventory,
            bindings,
            {inventory["candidates"][0]["candidate_id"]: permitted_roi_fixture(inventory)},
        )


def test_provenance_is_closed_canonical_and_numbers_reject_booleans():
    inventory = inventory_fixture()
    inventory["candidates"][0]["provenance"]["approved_to_click"] = True
    with pytest.raises(ValueError, match="candidate provenance is not closed"):
        validate_omni_inventory(inventory)

    inventory = inventory_fixture()
    inventory["provider_result"]["items"][0]["opaque_attributes"] = {"score": float("nan")}
    with pytest.raises(ValueError, match="finite"):
        validate_omni_inventory(inventory)

    inventory = inventory_fixture()
    inventory["provider_result"]["items"][0]["opaque_attributes"] = {
        "approved_to_click": True
    }
    with pytest.raises(ValueError, match="authority-shaped"):
        validate_omni_inventory(inventory)

    inventory = inventory_fixture()
    inventory["candidates"][0]["bbox_original"][0] = True
    with pytest.raises(ValueError, match="finite number"):
        validate_omni_inventory(inventory)


@pytest.mark.parametrize("bad_value", [{"not", "json"}, float("inf"), float("-inf")])
def test_provider_result_rejects_nested_non_json_or_nonfinite_values(bad_value):
    inventory = inventory_fixture()
    inventory["provider_result"]["items"][0]["opaque_attributes"] = {
        "bad_value": bad_value
    }

    with pytest.raises(ValueError, match="JSON|finite"):
        validate_omni_inventory(inventory)


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


def test_config_rejects_duplicate_or_reordered_fusion_states(tmp_path):
    source = json.loads((PROJECT_ROOT / "configs" / "learn_hybrid_v1_1.json").read_text(encoding="utf-8"))
    config_dir = tmp_path / "configs"
    config_dir.mkdir()

    source["fusion"]["states"].append("BOUND")
    (config_dir / "learn_hybrid_v1_1.json").write_text(
        json.dumps(source, ensure_ascii=False), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="exact canonical order"):
        load_hybrid_config(tmp_path)

    source["fusion"]["states"] = list(reversed(source["fusion"]["states"][:-1]))
    (config_dir / "learn_hybrid_v1_1.json").write_text(
        json.dumps(source, ensure_ascii=False), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="exact canonical order"):
        load_hybrid_config(tmp_path)


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
def test_config_rejects_every_authorization_flag_mutation(tmp_path, field, bad_value):
    source = json.loads((PROJECT_ROOT / "configs" / "learn_hybrid_v1_1.json").read_text(encoding="utf-8"))
    source[field] = bad_value
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "learn_hybrid_v1_1.json").write_text(
        json.dumps(source, ensure_ascii=False), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="non-authorizing invariant"):
        load_hybrid_config(tmp_path)
