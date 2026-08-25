from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest


FORBIDDEN_RUNTIME_POINT_FIELDS = {
    "actual_point",
    "click_point",
    "clickpoint",
    "confirmed_point",
    "expected_point",
    "screen_point",
    "target_point",
}


def _canonical_sha256(value: object) -> str:
    from app.learn.recognition.uei.canonical import canonical_json_bytes

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


@pytest.mark.parametrize("field", sorted(FORBIDDEN_RUNTIME_POINT_FIELDS))
def test_runtime_point_scanner_rejects_every_forbidden_spelling(field: str) -> None:
    """捕获拼写变体绕过发布资产历史坐标扫描。"""

    from scripts.prove_portfolio_hybrid_v1_1_persistence import (
        _runtime_point_fields,
    )

    assert _runtime_point_fields({"safety": {field: [12, 34]}}) == [field]


def test_runtime_point_scanner_allows_only_exact_fresh_grounding_policy() -> None:
    """捕获策略形状在错误位置或坐标值下被误放行。"""

    from scripts.prove_portfolio_hybrid_v1_1_persistence import (
        _runtime_point_fields,
    )

    valid = {
        "transitions": [
            {
                "preconditions": {
                    "grounding": {"click_point": {"required": True}}
                }
            }
        ]
    }
    assert _runtime_point_fields(valid) == []

    coordinate_value = json.loads(json.dumps(valid))
    coordinate_value["transitions"][0]["preconditions"]["grounding"][
        "click_point"
    ] = [12, 34]
    assert _runtime_point_fields(coordinate_value) == ["click_point"]
    assert _runtime_point_fields(
        {"safety": {"grounding": {"click_point": {"required": True}}}}
    ) == ["click_point"]


def test_managed_hybrid_save_survives_real_restart_and_publishes_once(
    tmp_path: Path,
) -> None:
    """捕获进程复用、非确定编译、重复发布和历史坐标进入运行资产。"""

    from scripts.prove_portfolio_hybrid_v1_1_persistence import (
        run_managed_two_process_persistence_proof,
    )
    import scripts.prove_portfolio_hybrid_v1_1_persistence as proof_module

    proof = run_managed_two_process_persistence_proof(tmp_path)

    assert not hasattr(proof_module, "_StaticWorkflowStore")
    assert not hasattr(proof_module, "_hybrid_projection")
    assert not hasattr(proof_module, "_workflow_state")

    assert proof["contract_version"] == "portfolio_hybrid_v1_1_persistence_proof_v1"
    assert proof["proof_mode"] == "managed_e2e_fake_provider_boundaries"
    assert proof["sequence"] == [
        "save",
        "compile_without_publish_a",
        "terminate_process_a",
        "fresh_process_b",
        "reload_exact_saved_bytes",
        "compile_without_publish_b",
        "compare_sha",
        "publish_b_once",
        "verify_registry_cas",
    ]
    assert proof["provider_boundary_trace"] == [
        "omni",
        "qwen",
        "fusion",
        "vista",
        "review",
    ]
    assert proof["managed_lifecycle_task_trace"] == [
        "panel_learning_hybrid_omni_discovery",
        "panel_learning_hybrid_qwen_binding",
        "panel_learning_hybrid_fusion",
        "panel_learning_calibration_sequence",
        "panel_learning_hybrid_review_projection",
    ]
    receipts = proof["managed_lifecycle_receipts"]
    assert [receipt["task_kind"] for receipt in receipts] == proof[
        "managed_lifecycle_task_trace"
    ]
    assert all(receipt["worker_status"] == "completed" for receipt in receipts)
    assert all(receipt["adoption_status"] == "adopted" for receipt in receipts)
    assert all(receipt["operation_id"] == receipts[0]["operation_id"] for receipt in receipts)
    assert proof["managed_review_projection_receipt"]["worker_id"] == receipts[-1][
        "worker_id"
    ]
    assert proof["large_review_save"]["status"] == "saved"
    assert proof["large_review_save"]["reviewed_candidate_contains_vista_proposal"] is True
    assert proof["large_review_save"]["reviewed_candidate_contains_human_proposal"] is True
    assert proof["server_http_boundary"] is True
    assert proof["managed_reviewed_source_path"] == proof["large_review_save"][
        "reviewed_candidate_path"
    ]
    assert proof["managed_reviewed_source_sha256"] == proof["large_review_save"][
        "reviewed_candidate_sha256"
    ]
    reviewed_path = Path(proof["managed_reviewed_source_path"])
    reviewed_bytes = reviewed_path.read_bytes()
    reviewed_candidate = json.loads(reviewed_bytes.decode("utf-8-sig"))
    assert hashlib.sha256(reviewed_bytes).hexdigest() == proof[
        "managed_reviewed_source_sha256"
    ]
    projection = reviewed_candidate["draft"]["hybrid_review_projection"]
    lineage = reviewed_candidate["draft"]["capture_lineage_ref"]
    assert proof["managed_capture_lineage_ref"] == lineage
    assert proof["managed_capture_lineage_digest"] == lineage["content_sha256"]
    assert proof["managed_projection_ledger_digest"] == projection["content_sha256"]
    assert proof["managed_decision_ledger_digest"] == _canonical_sha256(
        projection["review_decisions"]
    )
    assert proof["compiler_source_path"] == proof["saved_source_path"]
    assert proof["compiler_source_references_managed_reviewed_source"] is True
    compiler_review = json.loads(
        Path(proof["compiler_source_path"]).read_text(encoding="utf-8-sig")
    )
    source_node = next(
        node
        for node in compiler_review["nodes"]
        if node["node_id"] == proof["compiler_reviewed_source_node_id"]
    )
    assert proof["compiler_reviewed_source_field"] == "nodes[*].source_paths"
    assert proof["compiler_reviewed_source_relative_path"] in source_node["source_paths"]
    assert source_node["source_paths"] == [
        proof["compiler_reviewed_source_relative_path"]
    ]
    assert proof["compiler_reviewed_source_sha256"] == hashlib.sha256(
        reviewed_bytes
    ).hexdigest()
    assert proof["review_source_vista_proposal_present"] is True
    assert proof["review_source_human_proposal_present"] is True
    assert proof["public_reload_b_exact_managed_bytes"] is True
    reload_identity = proof["public_reload_b_identity"]
    assert proof["expected_reload_identity"] == reload_identity
    assert reload_identity["source_path"] == proof[
        "compiler_reviewed_source_relative_path"
    ]
    assert reload_identity["source_sha256"] == hashlib.sha256(reviewed_bytes).hexdigest()
    assert reload_identity["capture_lineage_ref"] == lineage
    assert reload_identity["projection_ledger_digest"] == projection["content_sha256"]
    assert reload_identity["decision_ledger_digest"] == _canonical_sha256(
        projection["review_decisions"]
    )
    assert proof["server_pid_a"] != proof["server_pid_b"]
    assert proof["server_a_exit_code"] == 0
    assert proof["server_b_exit_code"] == 0
    assert proof["process_a_terminated_before_b"] is True
    assert proof["all_subprocesses_terminated"] is True
    assert proof["source_sha_a"] == proof["source_sha_b"] == proof["saved_source_sha256"]
    assert proof["source_bytes_sha256"] == hashlib.sha256(
        Path(proof["saved_source_path"]).read_bytes()
    ).hexdigest()
    assert proof["compiled_asset_sha_a"] == proof["compiled_asset_sha_b"]
    assert proof["compile_a_status"] == proof["compile_b_status"] == "compiled"
    assert proof["compile_a_registry_revision_before"] == 0
    assert proof["compile_a_registry_revision_after"] == 0
    assert proof["compile_a_read_only_snapshot_before"] == proof[
        "compile_a_read_only_snapshot_after"
    ]
    assert proof["compile_a_read_only_snapshot_before"]["cas_object_sha256_by_name"] == {}
    assert proof["publish_count"] == 1
    assert proof["publish_status"] == "published"
    assert proof["duplicate_publish_status"] == "already_published"
    assert proof["registry_revision_before"] == 0
    assert proof["registry_revision_after"] == 1
    assert proof["registry_publish_event_count"] == 1
    publish_event = proof["single_publish_event"]
    assert publish_event["asset_id"] == proof["published_asset_id"]
    assert publish_event["content_sha256"] == proof["compiled_asset_sha_b"]
    assert publish_event["registry_revision"] == proof["registry_revision_after"]
    assert publish_event["event_type"] == "publish"
    assert publish_event["artifact_is_authorization"] is False
    assert proof["publish_snapshot_after"] == proof["duplicate_snapshot_after"]
    assert proof["event_count_delta"] == 1
    assert proof["registry_cas_verified"] is True
    assert proof["active_content_sha256"] == proof["compiled_asset_sha_b"]
    assert proof["object_file_sha256"] == proof["compiled_asset_sha_b"]
    assert proof["load_active_content_sha256"] == proof["compiled_asset_sha_b"]
    assert proof["published_runtime_point_fields"] == []
    assert proof["fresh_runtime_grounding_required"] is True
    assert proof["runtime_gate_required"] is True
    assert proof["post_action_verification_required"] is True
    assert proof["artifact_is_authorization"] is False
    assert proof["execute_binding_enabled"] is False
    assert proof["all_predicates_satisfied"] is True
    assert proof["predicate_results"]["exact_compiler_reviewed_source_binding"] is True
    assert proof["predicate_results"]["exact_public_reload_identity"] is True
    assert proof["predicate_results"]["duplicate_full_snapshot_unchanged"] is True
    assert proof["predicate_results"]["single_publish_event_bound"] is True

    proof_path = Path(proof["proof_artifact_path"])
    assert proof_path.is_file()
    persisted = json.loads(proof_path.read_text(encoding="utf-8"))
    assert persisted["proof_sha256"] == proof["proof_sha256"]
    canonical_scope = dict(persisted)
    canonical_scope.pop("proof_sha256")
    canonical_scope.pop("proof_file_sha256", None)
    assert _canonical_sha256(canonical_scope) == proof["proof_sha256"]
    assert hashlib.sha256(proof_path.read_bytes()).hexdigest() == proof[
        "proof_file_sha256"
    ]
    assert FORBIDDEN_RUNTIME_POINT_FIELDS.isdisjoint(
        persisted["published_runtime_point_fields"]
    )


def test_hand_written_fixture_is_explicit_no_publish_negative_control(
    tmp_path: Path,
) -> None:
    """捕获把手写 fixture 冒充 managed E2E 或意外写入发布 registry。"""

    from scripts.prove_portfolio_hybrid_v1_1_persistence import (
        run_fixture_negative_control,
    )

    fixture = Path("tests/fixtures/portfolio_hybrid_v1_1/reviewed_hybrid_source.json")
    proof = run_fixture_negative_control(
        project_root=tmp_path,
        fixture_path=fixture,
    )

    assert proof["contract_version"] == "portfolio_hybrid_v1_1_persistence_proof_v1"
    assert proof["proof_mode"] == "fixture_negative_control_only"
    assert proof["publish_attempted"] is False
    assert proof["registry_exists"] is False
    assert proof["compiled_status"] == "compiled"
    assert proof["compiled_runtime_point_fields"] == []
    assert proof["fixture_contains_non_authorizing_proposals"] is True


def test_publish_integrity_predicates_reject_hidden_duplicate_and_event_mutations() -> None:
    from scripts.prove_portfolio_hybrid_v1_1_persistence import (
        _publish_integrity_predicates,
        _require_proof_predicates,
    )

    event = {
        "event_type": "publish",
        "asset_id": "asset/one",
        "content_sha256": "a" * 64,
        "registry_revision": 1,
        "artifact_is_authorization": False,
    }
    published = {
        "registry_revision": 1,
        "event_count": 1,
        "registry_raw": {"sha256": "b" * 64},
        "registry_events": [event],
        "registry_objects": {},
        "cas_object_sha256_by_name": {"a.json": "a" * 64},
        "relevant_store_files": {},
    }
    assert all(
        _publish_integrity_predicates(
            publish_snapshot=published,
            duplicate_snapshot=deepcopy(published),
            single_event=event,
            expected_asset_id="asset/one",
            expected_content_sha256="a" * 64,
            expected_registry_revision=1,
        ).values()
    )
    hidden_duplicate = deepcopy(published)
    hidden_duplicate["registry_raw"]["sha256"] = "c" * 64
    duplicate_predicates = _publish_integrity_predicates(
        publish_snapshot=published,
        duplicate_snapshot=hidden_duplicate,
        single_event=event,
        expected_asset_id="asset/one",
        expected_content_sha256="a" * 64,
        expected_registry_revision=1,
    )
    assert duplicate_predicates["duplicate_full_snapshot_unchanged"] is False
    with pytest.raises(RuntimeError, match="duplicate_full_snapshot_unchanged"):
        _require_proof_predicates(duplicate_predicates)
    for field, wrong_value in (
        ("event_type", "replace"),
        ("asset_id", "asset/stale"),
        ("content_sha256", "c" * 64),
        ("registry_revision", 2),
        ("artifact_is_authorization", True),
    ):
        wrong_event = {**event, field: wrong_value}
        event_predicates = _publish_integrity_predicates(
            publish_snapshot=published,
            duplicate_snapshot=deepcopy(published),
            single_event=wrong_event,
            expected_asset_id="asset/one",
            expected_content_sha256="a" * 64,
            expected_registry_revision=1,
        )
        assert event_predicates["single_publish_event_bound"] is False
        with pytest.raises(RuntimeError, match="single_publish_event_bound"):
            _require_proof_predicates(event_predicates)


def test_exact_reload_and_node_binding_reject_each_identity_mutation() -> None:
    from scripts.prove_portfolio_hybrid_v1_1_persistence import (
        _exact_task8_source_node,
        _reload_identity_matches,
    )

    reviewed = "artifacts/learning-draft-review/reviewed.json"
    node = {"node_id": "home", "source_paths": [reviewed]}
    assert _exact_task8_source_node([node], reviewed_relative=reviewed) == node
    assert _exact_task8_source_node(
        [{**node, "source_paths": [reviewed, "other.json"]}],
        reviewed_relative=reviewed,
    ) is None
    assert _exact_task8_source_node(
        [node, {"node_id": "duplicate", "source_paths": [reviewed]}],
        reviewed_relative=reviewed,
    ) is None

    expected = {
        "source_path": reviewed,
        "source_sha256": "a" * 64,
        "capture_lineage_ref": {"id": "capture/one", "content_sha256": "b" * 64},
        "projection_ledger_digest": "c" * 64,
        "decision_ledger_digest": "d" * 64,
    }
    assert _reload_identity_matches(expected=expected, actual=deepcopy(expected))
    for field, wrong_value in (
        ("source_path", "stale.json"),
        ("source_sha256", "e" * 64),
        (
            "capture_lineage_ref",
            {"id": "capture/stale", "content_sha256": "f" * 64},
        ),
        ("projection_ledger_digest", "1" * 64),
        ("decision_ledger_digest", "2" * 64),
    ):
        mutated = {**deepcopy(expected), field: wrong_value}
        assert not _reload_identity_matches(expected=expected, actual=mutated)
