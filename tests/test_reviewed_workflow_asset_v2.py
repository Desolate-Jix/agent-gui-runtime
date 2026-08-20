from __future__ import annotations

import copy
import json
import multiprocessing
from pathlib import Path

import pytest


def _publish_in_child(
    project_root: str,
    asset: dict,
    start_event,
    start_barrier,
    result_queue,
) -> None:
    from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore

    start_event.wait(timeout=10)
    start_barrier.wait(timeout=10)
    try:
        result = ReviewedWorkflowAssetStore(project_root=project_root).publish(
            asset,
            expected_registry_revision=0,
        )
    except Exception as exc:  # 测试子进程必须把结构化结果传回父进程。
        result_queue.put(("error", type(exc).__name__, str(exc)))
    else:
        result_queue.put(("ok", result["asset_id"], result["registry_revision"]))


def _capture_requirements() -> dict:
    return {
        "current_observation": {"required": True},
        "capture": {
            "capture_id": {"required": True},
            "screenshot_sha256": {"required": True},
            "viewport_size": {"required": True},
        },
        "grounding": {
            "required": True,
            "current_target_bbox": {"required": True},
            "click_point": {"required": True},
            "confidence": {"required": True},
            "score_margin": {"required": True},
        },
        "source_state_unique": {"required": True},
        "gate": {
            "required": True,
            "endpoint": "POST /action/execute_recognition_plan",
        },
        "approved_plan_capture_lineage": {"required": True},
    }


def _reviewed_state(state_id: str, *, stop_boundary: bool = False) -> dict:
    action_anchor = {"homepage": "job_card", "detail": "quick_apply"}.get(state_id)
    anchors = [
        {"anchor_id": f"anchor_{state_id}", "label": state_id, "kind": "text"}
    ]
    if action_anchor:
        anchors.append({"anchor_id": action_anchor, "label": action_anchor, "kind": "control"})
    state = {
        "state_id": state_id,
        "source_node_id": f"node_{state_id}",
        "state_type": "application_surface",
        "display_name": state_id.replace("_", " ").title(),
        "identity_anchors": anchors,
        "grounding_profile": {"provider": "current_observation_grounding_v1"},
        "allowed_transition_ids": [],
        "availability": "stop_boundary" if stop_boundary else "reviewed",
    }
    if stop_boundary:
        state.pop("grounding_profile")
    return state


def _transition(transition_id: str = "open_detail") -> dict:
    return {
        "transition_id": transition_id,
        "source_state_id": "homepage",
        "target_state_id": "detail",
        "semantic_action": "open_detail",
        "display_name": "Open detail",
        "element_ref": "job_card",
        "preconditions": _capture_requirements(),
        "expected_effect": {
            "semantic_success": {"target_state_id": "detail"},
        },
        "post_action_verification": {
            "requires_new_capture": True,
            "semantic_success_rules": [
                {"rule_id": "detail_identity", "type": "target_state_identity"}
            ],
        },
        "recovery_policy": {
            "max_attempts": 1,
            "stale_capture": "recapture_and_reground",
            "target_not_found": "one_fresh_grounding",
            "post_action_failure": "observe_without_repeat",
            "destination_mismatch": "safe_stop_human_review",
            "foreground_change": "safe_stop_human_review",
            "unexpected_origin": "safe_stop_human_review",
        },
        "risk_policy": {
            "risk_level": "low",
            "requires_gate": True,
            "final_submit_forbidden": True,
        },
    }


def _asset() -> dict:
    homepage = _reviewed_state("homepage")
    detail = _reviewed_state("detail")
    boundary = _reviewed_state("apply_entry", stop_boundary=True)
    transition = _transition()
    transition2 = copy.deepcopy(transition)
    transition2.update(
        {
            "transition_id": "open_apply_flow",
            "source_state_id": "detail",
            "target_state_id": "apply_entry",
            "semantic_action": "open_apply_flow",
            "element_ref": "quick_apply",
            "expected_effect": {
                "semantic_success": {"target_state_id": "apply_entry"}
            },
            "post_action_verification": {
                "requires_new_capture": True,
                "semantic_success_rules": [
                    {"rule_id": "apply_entry_identity", "type": "target_state_identity"}
                ],
            },
        }
    )
    homepage["allowed_transition_ids"] = ["open_detail"]
    detail["allowed_transition_ids"] = ["open_apply_flow"]
    boundary["allowed_transition_ids"] = []
    return {
        "contract_version": "reviewed_workflow_asset_v2",
        "asset_id": "seek_homepage_quick_apply",
        "application": {
            "identity_status": "resolved",
            "kind": "web",
            "canonical_origin": "https://nz.seek.com",
            "canonical_domain": "nz.seek.com",
            "allow_external_sites": False,
        },
        "source_review_lineage": {
            "source_workflow_path": "synthetic/seek-review.json",
            "source_workflow_sha256": "a" * 64,
            "current_revision_hash": "b" * 64,
            "reviewed_revision_hash": "b" * 64,
            "human_approved_node_ids": ["node_homepage", "node_detail"],
            "reviewed_by_human": True,
            "evidence_sha256": "c" * 64,
        },
        "entry_state_id": "homepage",
        "states": [homepage, detail, boundary],
        "transitions": [transition, transition2],
        "safety": {
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "final_submit_forbidden": True,
            "real_action_requires_gate": True,
            "fresh_grounding_required": True,
            "post_action_verification_required": True,
            "historical_coordinates_used": False,
        },
        "lifecycle": {"status": "compiled", "version": 2},
    }


def test_canonical_content_hash_is_stable_and_excludes_runtime_metadata() -> None:
    from app.agent.reviewed_workflow_asset import (
        canonical_json_bytes,
        content_sha256,
        canonicalize_reviewed_workflow_asset,
    )

    first = _asset()
    second = copy.deepcopy(first)
    second["created_at"] = "2099-01-01T00:00:00Z"
    second["registry_revision"] = 999
    second["content_sha256"] = "f" * 64
    second["states"] = list(reversed(second["states"]))
    second["transitions"] = list(reversed(second["transitions"]))

    assert canonicalize_reviewed_workflow_asset(first) == canonicalize_reviewed_workflow_asset(second)
    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert content_sha256(first) == content_sha256(second)
    assert b"created_at" not in canonical_json_bytes(first)
    assert b"content_sha256" not in canonical_json_bytes(first)


def test_canonical_hash_sorts_nested_semantic_and_post_verification_rules() -> None:
    from app.agent.reviewed_workflow_asset import content_sha256

    first = _asset()
    effect_rules = [
        {"rule_id": "z_effect", "type": "marker_present"},
        {"rule_id": "a_effect", "type": "same_origin"},
    ]
    post_rules = [
        {"rule_id": "z_post", "type": "marker_present"},
        {"rule_id": "a_post", "type": "target_state_identity"},
    ]
    first["transitions"][0]["expected_effect"] = {
        "semantic_success": {"target_state_id": "detail"},
        "semantic_success_rules": effect_rules,
    }
    first["transitions"][0]["post_action_verification"]["semantic_success_rules"] = post_rules
    second = copy.deepcopy(first)
    second["transitions"][0]["expected_effect"]["semantic_success_rules"].reverse()
    second["transitions"][0]["post_action_verification"]["semantic_success_rules"].reverse()

    assert content_sha256(first) == content_sha256(second)


def test_canonical_hash_treats_human_approved_node_ids_as_a_semantic_set() -> None:
    from app.agent.reviewed_workflow_asset import (
        content_sha256,
        validate_reviewed_workflow_asset,
    )

    first = _asset()
    first["source_review_lineage"]["human_approved_node_ids"] = [
        "node_homepage",
        "node_detail",
        "node_homepage",
    ]
    second = _asset()
    second["source_review_lineage"]["human_approved_node_ids"] = [
        "node_detail",
        "node_homepage",
    ]

    assert content_sha256(first) == content_sha256(second)
    assert validate_reviewed_workflow_asset(first)["source_review_lineage"][
        "human_approved_node_ids"
    ] == ["node_detail", "node_homepage"]


def test_validator_accepts_synthetic_seek_three_state_asset() -> None:
    from app.agent.reviewed_workflow_asset import validate_reviewed_workflow_asset

    validated = validate_reviewed_workflow_asset(_asset())
    assert validated["contract_version"] == "reviewed_workflow_asset_v2"
    assert [state["state_id"] for state in validated["states"]] == [
        "apply_entry",
        "detail",
        "homepage",
    ]


def test_validator_rejects_v1_contract_instead_of_normalizing_it() -> None:
    from app.agent.reviewed_workflow_asset import validate_reviewed_workflow_asset

    asset = _asset()
    asset["contract_version"] = "reviewed_workflow_asset_v1"
    with pytest.raises(ValueError, match="contract_version"):
        validate_reviewed_workflow_asset(asset)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("identity_status", "unresolved"),
        ("current_revision_hash", ""),
        ("reviewed_revision_hash", "stale"),
    ],
)
def test_validator_rejects_unresolved_or_stale_identity_lineage(field: str, value: str) -> None:
    from app.agent.reviewed_workflow_asset import validate_reviewed_workflow_asset

    asset = _asset()
    if field == "identity_status":
        asset["application"][field] = value
    else:
        asset["source_review_lineage"][field] = value
    with pytest.raises(ValueError, match="identity|revision"):
        validate_reviewed_workflow_asset(asset)


def test_validator_rejects_duplicate_and_dangling_ids() -> None:
    from app.agent.reviewed_workflow_asset import validate_reviewed_workflow_asset

    duplicate = _asset()
    duplicate["states"][1]["state_id"] = "homepage"
    with pytest.raises(ValueError, match="duplicate state_id"):
        validate_reviewed_workflow_asset(duplicate)

    dangling = _asset()
    dangling["transitions"][0]["target_state_id"] = "missing"
    with pytest.raises(ValueError, match="unknown target_state_id"):
        validate_reviewed_workflow_asset(dangling)


def test_stop_boundary_cannot_declare_outgoing_transitions() -> None:
    from app.agent.reviewed_workflow_asset import validate_reviewed_workflow_asset

    asset = _asset()
    boundary = next(state for state in asset["states"] if state["availability"] == "stop_boundary")
    boundary["allowed_transition_ids"] = ["open_detail"]
    with pytest.raises(ValueError, match="stop_boundary.*empty"):
        validate_reviewed_workflow_asset(asset)


def test_transition_and_source_allowed_transition_ids_are_bidirectionally_consistent() -> None:
    from app.agent.reviewed_workflow_asset import validate_reviewed_workflow_asset

    missing_declaration = _asset()
    missing_declaration["states"][0]["allowed_transition_ids"] = []
    with pytest.raises(ValueError, match="must declare transition"):
        validate_reviewed_workflow_asset(missing_declaration)

    wrong_source = _asset()
    wrong_source["states"][0]["allowed_transition_ids"] = ["open_apply_flow"]
    with pytest.raises(ValueError, match="different source state"):
        validate_reviewed_workflow_asset(wrong_source)


@pytest.mark.parametrize("field", ["click_point", "actual_point", "screen_point", "window_handle", "hwnd", "pid"])
def test_validator_rejects_runtime_coordinates_and_window_identity(field: str) -> None:
    from app.agent.reviewed_workflow_asset import validate_reviewed_workflow_asset

    asset = _asset()
    asset["states"][0][field] = {"x": 1, "y": 2}
    with pytest.raises(ValueError, match="runtime coordinate|window identity"):
        validate_reviewed_workflow_asset(asset)


def test_runtime_coordinate_exemption_is_limited_to_exact_grounding_policy_path() -> None:
    from app.agent.reviewed_workflow_asset import validate_reviewed_workflow_asset

    asset = _asset()
    asset["states"][0]["metadata"] = {
        "preconditions": {"click_point": {"x": 11, "y": 12}}
    }
    with pytest.raises(ValueError, match="runtime coordinate"):
        validate_reviewed_workflow_asset(asset)

    nested_spoof = _asset()
    nested_spoof["states"][0]["metadata"] = {
        "transitions": [
            {
                "preconditions": {
                    "grounding": {"click_point": {"x": 21, "y": 22}}
                }
            }
        ]
    }
    with pytest.raises(ValueError, match="runtime coordinate"):
        validate_reviewed_workflow_asset(nested_spoof)


@pytest.mark.parametrize("field", ["coordinate", "coordinates", "position"])
def test_validator_rejects_coordinate_aliases_outside_runtime_policy(field: str) -> None:
    from app.agent.reviewed_workflow_asset import validate_reviewed_workflow_asset

    asset = _asset()
    asset["states"][0]["identity_anchors"][0][field] = {"x": 4, "y": 5}
    with pytest.raises(ValueError, match="runtime coordinate"):
        validate_reviewed_workflow_asset(asset)


@pytest.mark.parametrize(
    "field",
    [
        "current_target_bbox",
        "target_bbox",
        "bounding_box",
        "boundingbox",
        "rect",
        "current_bbox",
    ],
)
def test_validator_rejects_runtime_bbox_aliases_outside_exact_grounding_policy(
    field: str,
) -> None:
    from app.agent.reviewed_workflow_asset import validate_reviewed_workflow_asset

    asset = _asset()
    asset["states"][0]["metadata"] = {
        field: {"x": 4, "y": 5, "w": 6, "h": 7}
    }
    with pytest.raises(ValueError, match="runtime coordinate"):
        validate_reviewed_workflow_asset(asset)


def test_exact_grounding_bbox_policy_and_reference_only_anchor_bbox_remain_valid() -> None:
    from app.agent.reviewed_workflow_asset import validate_reviewed_workflow_asset

    asset = _asset()
    asset["states"][0]["identity_anchors"][0].update(
        {
            "reference_bbox": {"x": 1, "y": 2, "w": 3, "h": 4},
            "reference_only": True,
        }
    )
    validated = validate_reviewed_workflow_asset(asset)

    grounding = validated["transitions"][0]["preconditions"]["grounding"]
    assert grounding["current_target_bbox"] == {"required": True}
    anchor = next(
        item
        for state in validated["states"]
        for item in state["identity_anchors"]
        if item["anchor_id"] == "anchor_homepage"
    )
    assert anchor["reference_only"] is True


def test_nested_spoof_of_grounding_bbox_policy_is_rejected() -> None:
    from app.agent.reviewed_workflow_asset import validate_reviewed_workflow_asset

    asset = _asset()
    asset["states"][0]["metadata"] = {
        "transitions": [
            {
                "preconditions": {
                    "grounding": {
                        "current_target_bbox": {"x": 1, "y": 2, "w": 3, "h": 4}
                    }
                }
            }
        ]
    }
    with pytest.raises(ValueError, match="runtime coordinate"):
        validate_reviewed_workflow_asset(asset)


@pytest.mark.parametrize(
    ("policy_key", "embedded"),
    [
        ("click_point", {"required": True, "x": 20, "y": 30}),
        ("current_target_bbox", {"required": True, "x": 1, "y": 2, "w": 3, "h": 4}),
    ],
)
def test_precondition_policies_reject_embedded_runtime_geometry(policy_key: str, embedded: dict) -> None:
    from app.agent.reviewed_workflow_asset import validate_reviewed_workflow_asset

    asset = _asset()
    asset["transitions"][0]["preconditions"]["grounding"][policy_key] = embedded
    with pytest.raises(ValueError, match="closed policy|unexpected"):
        validate_reviewed_workflow_asset(asset)


@pytest.mark.parametrize(
    "semantic_action",
    ["final_submit", "submit_application", "send", "confirm", "payment", "purchase", "delete", "open_external_apply"],
)
def test_validator_rejects_dangerous_action_aliases(semantic_action: str) -> None:
    from app.agent.reviewed_workflow_asset import validate_reviewed_workflow_asset

    asset = _asset()
    asset["transitions"][0]["semantic_action"] = semantic_action
    with pytest.raises(ValueError, match="forbidden semantic action"):
        validate_reviewed_workflow_asset(asset)


@pytest.mark.parametrize("reference_field", ["action_ref", "memory_ref", "locator_anchor", "element_ref"])
def test_validator_rejects_dangerous_semantics_hidden_in_reference_ids(reference_field: str) -> None:
    from app.agent.reviewed_workflow_asset import validate_reviewed_workflow_asset

    asset = _asset()
    transition = asset["transitions"][0]
    transition.pop("element_ref", None)
    transition[reference_field] = "reviewed::final_submit"
    with pytest.raises(ValueError, match="forbidden semantic reference"):
        validate_reviewed_workflow_asset(asset)


@pytest.mark.parametrize("dangerous_ref", ["final_submit_button", "delete_account", "openExternalApplyLink"])
def test_validator_rejects_dangerous_tokens_anywhere_in_reference(dangerous_ref: str) -> None:
    from app.agent.reviewed_workflow_asset import validate_reviewed_workflow_asset

    asset = _asset()
    transition = asset["transitions"][0]
    transition.pop("element_ref")
    transition["action_ref"] = f"reviewed::{dangerous_ref}::v2"
    with pytest.raises(ValueError, match="forbidden semantic reference"):
        validate_reviewed_workflow_asset(asset)


@pytest.mark.parametrize(
    "dangerous_ref",
    [
        "payment_button",
        "payment_form",
        "purchase_action",
        "send_email_button",
        "confirm_dialog",
        "submit_control",
    ],
)
def test_validator_rejects_action_leading_danger_tokens(dangerous_ref: str) -> None:
    from app.agent.reviewed_workflow_asset import validate_reviewed_workflow_asset

    asset = _asset()
    transition = asset["transitions"][0]
    transition.pop("element_ref")
    transition["action_ref"] = f"reviewed::{dangerous_ref}::v2"
    with pytest.raises(ValueError, match="forbidden semantic reference"):
        validate_reviewed_workflow_asset(asset)


@pytest.mark.parametrize(
    "safe_ref",
    [
        "sender_profile",
        "sendgrid_dashboard",
        "payment_history_row",
        "confirmation_details_panel",
    ],
)
def test_validator_allows_read_only_references_containing_dangerous_prefixes(
    safe_ref: str,
) -> None:
    from app.agent.reviewed_workflow_asset import validate_reviewed_workflow_asset

    asset = _asset()
    transition = asset["transitions"][0]
    transition.pop("element_ref")
    transition["locator_anchor"] = safe_ref
    validated = validate_reviewed_workflow_asset(asset)
    selected = next(
        item for item in validated["transitions"] if item["transition_id"] == "open_detail"
    )
    assert selected["locator_anchor"] == safe_ref


def test_validator_keeps_safe_semantic_references_allowed() -> None:
    from app.agent.reviewed_workflow_asset import validate_reviewed_workflow_asset

    asset = _asset()
    validated = validate_reviewed_workflow_asset(asset)
    assert {item["element_ref"] for item in validated["transitions"]} == {
        "job_card",
        "quick_apply",
    }


@pytest.mark.parametrize(
    "missing",
    ["current_observation", "capture", "grounding", "gate", "post_action_verification", "expected_effect", "recovery_policy"],
)
def test_validator_requires_capture_grounding_gate_verification_success_and_recovery(missing: str) -> None:
    from app.agent.reviewed_workflow_asset import validate_reviewed_workflow_asset

    asset = _asset()
    if missing in {"post_action_verification", "expected_effect", "recovery_policy"}:
        asset["transitions"][0].pop(missing)
    elif missing == "current_observation":
        asset["transitions"][0]["preconditions"].pop(missing)
    else:
        asset["transitions"][0]["preconditions"].pop(missing)
    with pytest.raises(ValueError, match="required"):
        validate_reviewed_workflow_asset(asset)


def test_gate_endpoint_is_required_and_exact() -> None:
    from app.agent.reviewed_workflow_asset import validate_reviewed_workflow_asset

    missing = _asset()
    missing["transitions"][0]["preconditions"]["gate"].pop("endpoint")
    with pytest.raises(ValueError, match="gate.endpoint.*required"):
        validate_reviewed_workflow_asset(missing)

    wrong = _asset()
    wrong["transitions"][0]["preconditions"]["gate"]["endpoint"] = "POST /action/unsafe"
    with pytest.raises(ValueError, match="gate endpoint is invalid"):
        validate_reviewed_workflow_asset(wrong)


def test_stop_boundary_state_is_valid_without_grounding_or_action() -> None:
    from app.agent.reviewed_workflow_asset import validate_reviewed_workflow_asset

    asset = _asset()
    asset["transitions"][1]["target_state_id"] = "apply_entry"
    validated = validate_reviewed_workflow_asset(asset)
    boundary = next(state for state in validated["states"] if state["state_id"] == "apply_entry")
    assert boundary["availability"] == "stop_boundary"


def test_reference_bbox_requires_reference_only_and_never_becomes_click_point() -> None:
    from app.agent.reviewed_workflow_asset import validate_reviewed_workflow_asset

    asset = _asset()
    anchor = asset["states"][0]["identity_anchors"][0]
    anchor["reference_bbox"] = {"x": 1, "y": 2, "w": 3, "h": 4}
    with pytest.raises(ValueError, match="reference_only"):
        validate_reviewed_workflow_asset(asset)
    anchor["reference_only"] = True
    validated = validate_reviewed_workflow_asset(asset)
    state_and_transition_payload = {
        "states": validated["states"],
        "transitions": [{key: value for key, value in item.items() if key != "preconditions"} for item in validated["transitions"]],
    }
    assert "click_point" not in json.dumps(state_and_transition_payload, ensure_ascii=False)


@pytest.mark.parametrize(
    "source_path",
    [
        "C:/private/review.json",
        "C:\\private\\review.json",
        "//server/share/review.json",
        "/absolute/review.json",
        "../outside/review.json",
        "synthetic/../outside/review.json",
        "synthetic\\seek-review.json",
    ],
)
def test_source_workflow_path_must_be_normalized_project_relative(source_path: str) -> None:
    from app.agent.reviewed_workflow_asset import validate_reviewed_workflow_asset

    asset = _asset()
    asset["source_review_lineage"]["source_workflow_path"] = source_path
    with pytest.raises(ValueError, match="project-relative"):
        validate_reviewed_workflow_asset(asset)


def test_sha_fields_require_64_hex_and_canonicalize_uppercase() -> None:
    from app.agent.reviewed_workflow_asset import validate_reviewed_workflow_asset

    uppercase = _asset()
    for field in (
        "source_workflow_sha256",
        "current_revision_hash",
        "reviewed_revision_hash",
        "evidence_sha256",
    ):
        uppercase["source_review_lineage"][field] = "A" * 64
    validated = validate_reviewed_workflow_asset(uppercase)
    assert {
        validated["source_review_lineage"][field]
        for field in (
            "source_workflow_sha256",
            "current_revision_hash",
            "reviewed_revision_hash",
            "evidence_sha256",
        )
    } == {"a" * 64}

    invalid = _asset()
    invalid["source_review_lineage"]["evidence_sha256"] = "not-a-sha"
    with pytest.raises(ValueError, match="64 hexadecimal"):
        validate_reviewed_workflow_asset(invalid)


@pytest.mark.parametrize("allow_external_sites", [None, "false", 0])
def test_web_application_requires_explicit_boolean_external_site_policy(
    allow_external_sites,
) -> None:
    from app.agent.reviewed_workflow_asset import validate_reviewed_workflow_asset

    asset = _asset()
    if allow_external_sites is None:
        asset["application"].pop("allow_external_sites")
    else:
        asset["application"]["allow_external_sites"] = allow_external_sites
    with pytest.raises(ValueError, match="allow_external_sites.*boolean"):
        validate_reviewed_workflow_asset(asset)


def test_safety_flags_are_non_authorizing_and_gate_required() -> None:
    from app.agent.reviewed_workflow_asset import validate_reviewed_workflow_asset

    asset = _asset()
    for key in ("artifact_is_authorization", "execute_binding_enabled", "historical_coordinates_used"):
        asset["safety"][key] = True
        with pytest.raises(ValueError, match="safety"):
            validate_reviewed_workflow_asset(asset)
        asset["safety"][key] = False
    asset["safety"]["real_action_requires_gate"] = False
    with pytest.raises(ValueError, match="safety"):
        validate_reviewed_workflow_asset(asset)


def test_cas_store_publishes_immutable_object_and_reloads_from_v2_root(tmp_path: Path) -> None:
    from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore

    store = ReviewedWorkflowAssetStore(project_root=tmp_path)
    result = store.publish(_asset(), expected_registry_revision=0)
    assert result["status"] == "published"
    assert result["object_path"].startswith("runtime_state/reviewed-workflow-assets-v2/objects/")
    assert (tmp_path / result["object_path"]).exists()
    loaded = ReviewedWorkflowAssetStore(project_root=tmp_path).load_active("seek_homepage_quick_apply")
    assert loaded["contract_version"] == "reviewed_workflow_asset_v2"
    assert loaded["safety"]["artifact_is_authorization"] is False
    assert not (tmp_path / "runtime_state" / "reviewed-runtime-assets").exists()


def test_same_content_publish_is_idempotent_and_does_not_advance_revision(tmp_path: Path) -> None:
    from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore

    store = ReviewedWorkflowAssetStore(project_root=tmp_path)
    first = store.publish(_asset(), expected_registry_revision=0)
    second = store.publish(_asset(), expected_registry_revision=0)
    assert second["status"] == "already_published"
    assert second["content_sha256"] == first["content_sha256"]
    assert second["registry_revision"] == first["registry_revision"] == 1
    assert len(store.registry()["events"]) == 1


def test_semantic_change_creates_new_object_and_preserves_old(tmp_path: Path) -> None:
    from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore

    store = ReviewedWorkflowAssetStore(project_root=tmp_path)
    first = store.publish(_asset(), expected_registry_revision=0)
    changed = _asset()
    changed["transitions"][0]["display_name"] = "Open job detail"
    second = store.publish(changed, expected_registry_revision=1)
    assert second["content_sha256"] != first["content_sha256"]
    assert second["registry_revision"] == 2
    assert (tmp_path / first["object_path"]).exists()
    assert (tmp_path / second["object_path"]).exists()
    loaded = store.load_active("seek_homepage_quick_apply")
    detail_transition = next(item for item in loaded["transitions"] if item["transition_id"] == "open_detail")
    assert detail_transition["display_name"] == "Open job detail"


def test_store_enforces_registry_cas_and_rejects_tampering_and_v1(tmp_path: Path) -> None:
    from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore

    store = ReviewedWorkflowAssetStore(project_root=tmp_path)
    store.publish(_asset(), expected_registry_revision=0)
    with pytest.raises(ValueError, match="registry revision mismatch"):
        store.publish({**_asset(), "lifecycle": {"status": "changed", "version": 2}}, expected_registry_revision=0)

    registry = json.loads((tmp_path / "runtime_state" / "reviewed-workflow-assets-v2" / "registry.json").read_text(encoding="utf-8"))
    object_path = tmp_path / registry["objects"][next(iter(registry["objects"]))]["object_path"]
    object_path.write_text(object_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        store.load_active("seek_homepage_quick_apply")

    v1_root = tmp_path / "v1-only" / "runtime_state" / "reviewed-workflow-assets-v2"
    v1_root.mkdir(parents=True)
    (v1_root / "registry.json").write_text(json.dumps({"contract_version": "reviewed_workflow_asset_registry_v1"}), encoding="utf-8")
    with pytest.raises(ValueError, match="v1|invalid registry"):
        ReviewedWorkflowAssetStore(project_root=tmp_path / "v1-only").registry()


def test_load_active_rejects_registry_identity_substitution(tmp_path: Path) -> None:
    from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore

    store = ReviewedWorkflowAssetStore(project_root=tmp_path)
    first_asset = _asset()
    first = store.publish(first_asset, expected_registry_revision=0)
    second_asset = _asset()
    second_asset["asset_id"] = "other_reviewed_workflow"
    second = store.publish(second_asset, expected_registry_revision=1)

    registry_path = tmp_path / "runtime_state" / "reviewed-workflow-assets-v2" / "registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["active_by_asset"][first_asset["asset_id"]] = second["content_sha256"]
    registry["objects"][second["content_sha256"]]["asset_id"] = first_asset["asset_id"]
    registry_path.write_text(json.dumps(registry, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="payload asset identity mismatch"):
        store.load_active(first_asset["asset_id"])
    assert first["content_sha256"] != second["content_sha256"]


def test_registry_cas_has_exactly_one_cross_process_winner(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    start_event = context.Event()
    start_barrier = context.Barrier(6)
    result_queue = context.Queue()
    processes = []
    for index in range(6):
        asset = _asset()
        asset["asset_id"] = f"parallel_asset_{index}"
        process = context.Process(
            target=_publish_in_child,
            args=(str(tmp_path), asset, start_event, start_barrier, result_queue),
        )
        process.start()
        processes.append(process)
    start_event.set()
    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0
    results = [result_queue.get(timeout=5) for _ in processes]
    winners = [result for result in results if result[0] == "ok"]
    losers = [result for result in results if result[0] == "error"]

    assert len(winners) == 1
    assert all("registry revision mismatch" in result[2] for result in losers), results
    registry_path = tmp_path / "runtime_state" / "reviewed-workflow-assets-v2" / "registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    assert registry["registry_revision"] == 1
    assert len(registry["active_by_asset"]) == 1


def test_stale_registry_lock_marker_does_not_block_publish(tmp_path: Path) -> None:
    from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore

    lock_path = (
        tmp_path
        / "runtime_state"
        / "reviewed-workflow-assets-v2"
        / ".registry.lock"
    )
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text("pid=999999999\n", encoding="ascii")

    result = ReviewedWorkflowAssetStore(project_root=tmp_path).publish(
        _asset(),
        expected_registry_revision=0,
    )

    assert result["status"] == "published"
    assert result["registry_revision"] == 1


def test_store_rejects_symlink_redirection_outside_v2_root(tmp_path: Path) -> None:
    from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore

    external = tmp_path / "external-storage"
    external.mkdir()
    v2_root = tmp_path / "runtime_state" / "reviewed-workflow-assets-v2"
    v2_root.parent.mkdir(parents=True)
    try:
        v2_root.symlink_to(external, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    with pytest.raises(ValueError, match="outside|redirection"):
        ReviewedWorkflowAssetStore(project_root=tmp_path).publish(
            _asset(),
            expected_registry_revision=0,
        )
