from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
RELEASE_ROOT = REPO_ROOT / "release" / "portfolio-v1"
MANIFEST_PATH = RELEASE_ROOT / "review-draft-manifest.json"
WORKSPACE_ROOT = RELEASE_ROOT / "reviewed-asset-workspace"
SOURCE_PATH = WORKSPACE_ROOT / "artifacts" / "interface-workflow-reviews" / "portfolio_v1_seek_apply_entry" / "reviewed_workflow.json"
REGISTRY_PATH = WORKSPACE_ROOT / "artifacts" / "interface-workflow-reviews" / "registry.json"


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _walk_path_values(value: Any, key: str = "") -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for child_key, child in value.items():
            values.extend(_walk_path_values(child, str(child_key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            values.extend(_walk_path_values(child, f"{key}[{index}]"))
    elif isinstance(value, str) and "path" in key.casefold():
        values.append((key, value))
    return values


def _assert_project_relative_paths(payload: Any) -> None:
    for key, raw_path in _walk_path_values(payload):
        path = Path(raw_path)
        assert not path.is_absolute(), f"{key} must be project-relative: {raw_path}"
        assert ".." not in path.parts, f"{key} must not escape project root: {raw_path}"
        assert not raw_path.startswith(("\\\\", "/")), f"{key} must be portable: {raw_path}"


def _assert_existing_workspace_paths(payload: Any) -> None:
    for key, raw_path in _walk_path_values(payload):
        if not raw_path:
            continue
        resolved = (WORKSPACE_ROOT / raw_path).resolve()
        assert resolved.is_relative_to(WORKSPACE_ROOT.resolve()), f"{key} escapes workspace"
        assert resolved.is_file(), f"{key} is missing from portable workspace: {raw_path}"


def _forbidden_runtime_geometry(value: Any) -> None:
    forbidden = {"x", "y", "bbox", "hwnd", "window_handle"}
    if isinstance(value, dict):
        for key, child in value.items():
            assert str(key).casefold() not in forbidden, f"runtime geometry leaked through {key}"
            _forbidden_runtime_geometry(child)
    elif isinstance(value, list):
        for child in value:
            _forbidden_runtime_geometry(child)


def test_portfolio_v1_review_draft_manifest_is_explicitly_non_authoritative() -> None:
    manifest = _read(MANIFEST_PATH)

    assert manifest["contract_version"] == "portfolio_v1_review_draft_manifest_v1"
    assert manifest["evidence_grade"] == "review_draft_with_sanitized_clean_job_detail_and_historical_apply_entry_derivative"
    assert manifest["human_review_completed"] is False
    assert manifest["controlled_live_workflow_proven"] is False
    assert manifest["runtime_dispatch_authorization"] is False
    assert manifest["compiled_release_asset_present"] is False
    assert manifest["approved_node_ids"] == []
    assert manifest["pending_human_review_node_ids"] == ["job_detail"]
    assert manifest["stop_boundary_node_ids"] == ["apply_entry"]
    _assert_project_relative_paths(manifest)


def test_portfolio_v1_workspace_registry_and_source_paths_are_portable() -> None:
    manifest = _read(MANIFEST_PATH)
    registry = _read(REGISTRY_PATH)
    source = _read(SOURCE_PATH)

    _assert_project_relative_paths(manifest)
    _assert_project_relative_paths(registry)
    _assert_project_relative_paths(source)
    _assert_existing_workspace_paths(registry)
    _assert_existing_workspace_paths(source)
    assert (WORKSPACE_ROOT / manifest["source_workflow_path"]).is_file()
    assert manifest["workspace_root"] == "release/portfolio-v1/reviewed-asset-workspace"
    record = registry["workflows"][manifest["workflow_id"]]
    assert record["path"] == "artifacts/interface-workflow-reviews/portfolio_v1_seek_apply_entry/reviewed_workflow.json"
    assert (WORKSPACE_ROOT / Path(record["path"])).resolve().is_relative_to(REPO_ROOT.resolve())
    assert (WORKSPACE_ROOT / Path(record["path"])).resolve() == SOURCE_PATH.resolve()
    assert record["source_asset_sha256"] == _sha256(SOURCE_PATH)


def test_portfolio_v1_workspace_json_contains_no_runtime_geometry() -> None:
    workspace_json_paths = sorted(WORKSPACE_ROOT.rglob("*.json"))

    assert workspace_json_paths
    for path in workspace_json_paths:
        _forbidden_runtime_geometry(_read(path))


def test_portfolio_v1_node_evidence_is_present_and_hash_bound_to_review_source() -> None:
    source = _read(SOURCE_PATH)

    for node in source["nodes"]:
        evidence = node["evidence"]
        expected_sha256 = evidence["source_screenshot_sha256"]
        for field in (
            "source_screenshot_path",
            "review_revision_source_screenshot_path",
        ):
            evidence_path = (WORKSPACE_ROOT / evidence[field]).resolve()
            assert evidence_path.is_relative_to(WORKSPACE_ROOT.resolve())
            assert evidence_path.is_file(), f"{node['node_id']} evidence is missing: {evidence[field]}"
            assert _sha256(evidence_path) == expected_sha256

        review_source_path = (WORKSPACE_ROOT / node["editable_review_source_path"]).resolve()
        assert review_source_path.is_relative_to(WORKSPACE_ROOT.resolve())
        review_source = _read(review_source_path)
        screen = review_source["draft"]["page_details"]["screen"]
        assert screen["source_image_sha256"] == expected_sha256
        source_image_path = (WORKSPACE_ROOT / screen["source_image_path"]).resolve()
        assert source_image_path.is_relative_to(WORKSPACE_ROOT.resolve())
        assert source_image_path.is_file()
        assert _sha256(source_image_path) == expected_sha256


def test_portfolio_v1_job_detail_uses_an_editable_clean_capture_not_a_preboxed_derivative() -> None:
    source = _read(SOURCE_PATH)
    job_detail = next(node for node in source["nodes"] if node["node_id"] == "job_detail")
    evidence = job_detail["evidence"]
    review_source = _read(WORKSPACE_ROOT / job_detail["editable_review_source_path"])
    screen = review_source["draft"]["page_details"]["screen"]

    assert evidence["source_image_kind"] == "sanitized_clean_capture"
    assert evidence["editable_base_allowed"] is True
    assert len(evidence["source_capture_sha256"]) == 64
    assert evidence["sanitization_transform"] == "crop_top_160_bottom_1380_keep_full_width"
    assert screen["source_image_kind"] == "sanitized_clean_capture"
    assert screen["editable_base_allowed"] is True
    assert screen["source_capture_sha256"] == evidence["source_capture_sha256"]
    assert screen["sanitization_transform"] == evidence["sanitization_transform"]
    assert evidence["source_screenshot_sha256"] != "321370fa2098ff4db67440db2041b40a8ebe02d4c275d74c33a1bab61c4d31ad"


def test_portfolio_v1_source_is_two_state_one_edge_with_aligned_semantic_identity() -> None:
    source = _read(SOURCE_PATH)
    workflow = source["workflow"]
    nodes = {node["node_id"]: node for node in source["nodes"]}
    edges = source["edges"]

    assert workflow["node_ids"] == ["job_detail", "apply_entry"]
    assert workflow["edge_ids"] == ["open_apply_flow"]
    assert set(nodes) == {"job_detail", "apply_entry"}
    assert len(edges) == 1
    edge = edges[0]
    assert edge["edge_id"] == "open_apply_flow"
    assert edge["operation_id"] == "open_apply_flow"
    assert edge["action_template_id"] == "open_apply_flow"
    assert edge["source_node_id"] == "job_detail"
    assert edge["target_node_id"] == "apply_entry"
    assert edge["requires_user_confirmation"] is True


def test_portfolio_v1_job_detail_has_agent_responsibility_and_reviewable_apply_action() -> None:
    source = _read(SOURCE_PATH)
    job_detail = next(node for node in source["nodes"] if node["node_id"] == "job_detail")

    assert job_detail["review_status"] == "needs_human_review"
    assert job_detail["reviewed_by_human"] is False
    assert isinstance(job_detail.get("responsibility"), str) and job_detail["responsibility"].strip()
    descriptor = next(item for item in job_detail["content_descriptors"] if item["content_id"] == "job_detail_structure")
    assert descriptor["content_behavior"] == "fixed_structure"
    assert descriptor["agent_usage"] == "identity_anchor"
    control = next(item for item in job_detail["controls"] if item["control_id"] == "apply")
    assert control["role"] == "button"
    assert control["purpose"]
    action = next(item for item in job_detail["action_candidates"] if item["action_template_id"] == "open_apply_flow")
    assert action["semantic_action"] == "open_apply_flow"
    assert action["action_type"] == "open_apply_flow"
    assert action["target_interface_id"] == "apply_entry"
    assert action["review_status"] == "needs_human_review"
    assert action["display_only"] is True
    assert action["execute_binding_enabled"] is False
    assert action["verification_rule_ids"] == ["application_entry_visible"]
    verification_rule = next(
        item
        for item in job_detail["verification_rules"]
        if item["rule_id"] == "application_entry_visible"
    )
    assert verification_rule["description"].strip()


def test_portfolio_v1_apply_entry_is_learning_stop_boundary_without_mutating_actions() -> None:
    source = _read(SOURCE_PATH)
    apply_entry = next(node for node in source["nodes"] if node["node_id"] == "apply_entry")

    assert apply_entry["review_status"] == "needs_learning"
    assert apply_entry["reviewed_by_human"] is False
    assert apply_entry["action_candidates"] == []
    assert apply_entry["blockers"]
    assert any(item["safe_stop_required"] is True for item in apply_entry["blockers"])
    serialized = json.dumps(apply_entry, ensure_ascii=False).casefold()
    for forbidden in ("fill_field", "continue_next_step", "final_submit", "send", "confirm", "payment"):
        assert forbidden not in serialized


def test_portfolio_v1_unreviewed_draft_cannot_compile_to_runtime_asset() -> None:
    from app.agent.reviewed_workflow_compiler import compile_reviewed_workflow_asset_v2

    source_bytes = SOURCE_PATH.read_bytes()
    result = compile_reviewed_workflow_asset_v2(
        project_root=WORKSPACE_ROOT,
        source_workflow_path=SOURCE_PATH.relative_to(WORKSPACE_ROOT),
        expected_source_workflow_sha256=hashlib.sha256(source_bytes).hexdigest(),
    )

    assert result["status"] == "blocked"
    assert result["asset"] is None
    assert "source_node_not_human_reviewed" in {item["code"] for item in result["blocked_reasons"]}
    _forbidden_runtime_geometry(result)
