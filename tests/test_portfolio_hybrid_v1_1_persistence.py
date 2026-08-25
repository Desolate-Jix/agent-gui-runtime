from __future__ import annotations

import hashlib
import json
from pathlib import Path


FORBIDDEN_RUNTIME_POINT_FIELDS = {
    "actual_point",
    "click_point",
    "confirmed_point",
    "expected_point",
    "screen_point",
    "target_point",
}


def test_managed_hybrid_save_survives_real_restart_and_publishes_once(
    tmp_path: Path,
) -> None:
    """捕获进程复用、非确定编译、重复发布和历史坐标进入运行资产。"""

    from scripts.prove_portfolio_hybrid_v1_1_persistence import (
        run_managed_two_process_persistence_proof,
    )

    proof = run_managed_two_process_persistence_proof(tmp_path)

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
    assert proof["provider_boundary_trace"] == ["omni", "qwen", "fusion", "vista"]
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
    assert proof["compiler_source_path"] == proof["saved_source_path"]
    assert proof["compiler_source_references_managed_reviewed_source"] is True
    assert proof["review_source_vista_proposal_present"] is True
    assert proof["review_source_human_proposal_present"] is True
    assert proof["public_reload_b_exact_managed_bytes"] is True
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
    assert proof["publish_count"] == 1
    assert proof["publish_status"] == "published"
    assert proof["duplicate_publish_status"] == "already_published"
    assert proof["registry_revision_before"] == 0
    assert proof["registry_revision_after"] == 1
    assert proof["registry_publish_event_count"] == 1
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

    proof_path = Path(proof["proof_artifact_path"])
    assert proof_path.is_file()
    persisted = json.loads(proof_path.read_text(encoding="utf-8"))
    assert persisted["proof_sha256"] == proof["proof_sha256"]
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
