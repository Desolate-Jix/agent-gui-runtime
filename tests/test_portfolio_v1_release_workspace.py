from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
RELEASE_ROOT = REPO_ROOT / "release" / "portfolio-v1"
MANIFEST_PATH = RELEASE_ROOT / "review-draft-manifest.json"
WORKSPACE_ROOT = RELEASE_ROOT / "reviewed-asset-workspace"
SOURCE_PATH = WORKSPACE_ROOT / "artifacts" / "interface-workflow-reviews" / "portfolio_v1_seek_apply_entry" / "reviewed_workflow.json"
REGISTRY_PATH = WORKSPACE_ROOT / "artifacts" / "interface-workflow-reviews" / "registry.json"
ASSET_REGISTRY_PATH = WORKSPACE_ROOT / "runtime_state" / "reviewed-workflow-assets-v2" / "registry.json"
SOURCE_SHA256 = "a934acc82708cfd956110ba2bba35e8d0bc317af9e095606efab87c5f3e027bc"
ASSET_SHA256 = "8284e1729409aa0a4f6a751a1a03d85fc51db1c7d53d473bd012455a3fc391b7"
ASSET_ID = "workflow_portfolio_v1_seek_apply_entry_fe297b5738f8c17790429e925ceab6f0"
ASSET_PATH = WORKSPACE_ROOT / "runtime_state" / "reviewed-workflow-assets-v2" / "objects" / f"{ASSET_SHA256}.json"
ARCHIVAL_LINEAGE_PATH = WORKSPACE_ROOT / "archival-lineage.json"
CORRECTION_MEMORY_ROOT = WORKSPACE_ROOT / "artifacts" / "learning-correction-memory"
HISTORICAL_PREBOXED_SHA256 = "321370fa2098ff4db67440db2041b40a8ebe02d4c275d74c33a1bab61c4d31ad"


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_files() -> list[Path]:
    return sorted(
        path
        for path in WORKSPACE_ROOT.rglob("*.json")
        if path != ARCHIVAL_LINEAGE_PATH
    )


def _walk_path_values(value: Any, key: str = "") -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for child_key, child in value.items():
            values.extend(_walk_path_values(child, str(child_key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            values.extend(_walk_path_values(child, f"{key}[{index}]"))
    elif isinstance(value, str):
        normalized_key = key.casefold()
        looks_like_sha256 = len(value) == 64 and all(character in "0123456789abcdef" for character in value.casefold())
        if "path" in normalized_key and "sha256" not in normalized_key and not looks_like_sha256:
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


def test_portfolio_v1_release_manifest_records_reviewed_non_authoritative_asset() -> None:
    manifest = _read(MANIFEST_PATH)

    assert manifest["contract_version"] == "portfolio_v1_release_manifest_v1"
    assert manifest["evidence_grade"] == "human_reviewed_source_with_sanitized_evidence_and_compiled_asset"
    assert manifest["human_review_completed"] is True
    assert manifest["compiled_release_asset_present"] is True
    assert manifest["controlled_live_workflow_proven"] is True
    assert any(
        "one bounded controlled-live open_apply_flow path" in note.lower()
        for note in manifest["notes"]
    )
    assert manifest["runtime_dispatch_authorization"] is False
    assert manifest["artifact_is_authorization"] is False
    assert manifest["execute_binding_enabled"] is False
    assert manifest["approved_node_ids"] == ["job_detail"]
    assert manifest["pending_human_review_node_ids"] == []
    assert manifest["stop_boundary_node_ids"] == ["apply_entry"]
    assert manifest["source_workflow_sha256"] == SOURCE_SHA256
    assert manifest["compiled_asset_id"] == ASSET_ID
    assert manifest["compiled_asset_sha256"] == ASSET_SHA256
    assert manifest["compiled_asset_path"] == ASSET_PATH.relative_to(WORKSPACE_ROOT).as_posix()
    assert manifest["compiled_asset_registry_path"] == ASSET_REGISTRY_PATH.relative_to(WORKSPACE_ROOT).as_posix()
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
    assert (WORKSPACE_ROOT / Path(record["path"])).resolve() == SOURCE_PATH.resolve()
    assert record["source_asset_sha256"] == SOURCE_SHA256 == _sha256(SOURCE_PATH)


def test_portfolio_v1_exported_json_paths_are_recursively_complete_or_explicitly_unresolved() -> None:
    lineage = _read(ARCHIVAL_LINEAGE_PATH)

    assert lineage["contract_version"] == "portfolio_v1_archival_lineage_v1"
    assert lineage["source_workflow_sha256"] == SOURCE_SHA256
    assert lineage["compiled_asset_sha256"] == ASSET_SHA256
    assert lineage["artifact_is_authorization"] is False
    assert lineage["execute_binding_enabled"] is False
    _assert_project_relative_paths(lineage)
    current_review_source = lineage["current_review_source"]
    current_review_source_path = WORKSPACE_ROOT / current_review_source["path"]
    assert current_review_source["authoritative_for_current_review"] is True
    assert current_review_source_path.is_file()
    assert _sha256(current_review_source_path) == current_review_source["sha256"]
    unresolved = lineage["unresolved_archival_artifacts"]
    allowlisted = {item["expected_path"]: item for item in unresolved}
    referenced_missing: set[str] = set()

    for document_path in _json_files():
        payload = _read(document_path)
        _assert_project_relative_paths(payload)
        for key, raw_path in _walk_path_values(payload):
            if not raw_path:
                continue
            resolved = (WORKSPACE_ROOT / raw_path).resolve()
            assert resolved.is_relative_to(WORKSPACE_ROOT.resolve()), f"{key} escapes workspace"
            if resolved.is_file():
                continue
            referenced_missing.add(raw_path)
            assert raw_path in allowlisted, (
                f"{document_path.relative_to(WORKSPACE_ROOT).as_posix()}:{key} "
                f"is missing without an explicit archival allowlist entry: {raw_path}"
            )

    assert referenced_missing == set(allowlisted)
    for expected_path, item in allowlisted.items():
        expected_sha256 = item["expected_sha256"]
        assert item["status"] == "unresolved_archival_source_snapshot"
        assert item["non_authoritative"] is True
        assert item["required_for_compiled_asset"] is False
        assert item["artifact_is_authorization"] is False
        assert item["execute_binding_enabled"] is False
        assert expected_sha256 in Path(expected_path).name
        assert not (WORKSPACE_ROOT / expected_path).exists()


def test_portfolio_v1_archival_candidates_bind_recovered_evidence_and_declare_missing_source_snapshots() -> None:
    source = _read(SOURCE_PATH)
    job_detail = next(node for node in source["nodes"] if node["node_id"] == "job_detail")
    candidate_paths = [
        Path(path)
        for path in job_detail["source_paths"]
        if path.endswith("reviewed_template_candidate.json")
    ]

    assert len(candidate_paths) == 5
    for candidate_path in candidate_paths:
        candidate = _read(WORKSPACE_ROOT / candidate_path)
        candidate_dir = candidate_path.parent
        source_sha256 = candidate["source"]["sha256"]
        unresolved_source_path = candidate["source"]["source_path"]
        assert unresolved_source_path == candidate["source"]["original_draft_path"]
        assert unresolved_source_path == candidate["audit"]["source_trial_path"]
        assert unresolved_source_path == candidate["audit"]["original_draft_path"]
        assert source_sha256 in Path(unresolved_source_path).name
        assert not (WORKSPACE_ROOT / unresolved_source_path).exists()

        patch = _read(WORKSPACE_ROOT / candidate["audit"]["human_review_patch_path"])
        assert patch["source_draft_path"] == unresolved_source_path
        assert patch["source_draft_sha256"] == source_sha256

        correction = candidate["audit"]["correction_memory"]
        correction_path = WORKSPACE_ROOT / correction["correction_entry_path"]
        assert correction_path.is_file()
        correction_entry = _read(correction_path)
        assert correction_entry["source"]["draft_path"] == unresolved_source_path
        assert correction_entry["source"]["draft_sha256"] == source_sha256
        assert correction_entry["artifact_is_authorization"] is False
        assert correction_entry["execute_binding_enabled"] is False

        screenshot_path = WORKSPACE_ROOT / candidate["draft"]["page_details"]["screen"]["source_image_path"]
        screenshot_sha256 = candidate["draft"]["page_details"]["screen"]["source_image_sha256"]
        assert screenshot_path.is_file()
        assert _sha256(screenshot_path) == screenshot_sha256
        assert patch["screenshot_path"] == screenshot_path.relative_to(WORKSPACE_ROOT).as_posix()
        assert patch["screenshot_sha256"] == screenshot_sha256
        assert correction_entry["evidence"]["screenshot_path"] == screenshot_path.relative_to(WORKSPACE_ROOT).as_posix()
        assert correction_entry["evidence"]["screenshot_sha256"] == screenshot_sha256

        assert candidate_dir.name.startswith("job_detail_")

    registry = _read(CORRECTION_MEMORY_ROOT / "registry.json")
    assert registry["contract_version"] == "learning_surface_rule_registry_v1"
    assert registry["candidate_rules_affect_production"] is False
    assert registry["model_activation_allowed"] is False
    assert registry["artifact_is_authorization"] is False
    assert registry["execute_binding_enabled"] is False
    assert len(registry["rules"]) == 5
    for rule in registry["rules"]:
        entry_path = WORKSPACE_ROOT / rule["correction_entry_path"]
        assert entry_path.is_file()
        assert _sha256(entry_path) == rule["correction_sha256"]
        assert rule["status"] == "candidate"
        assert rule["production_eligible"] is False


def test_portfolio_v1_historical_preboxed_capture_is_a_non_authoritative_negative_control() -> None:
    lineage = _read(ARCHIVAL_LINEAGE_PATH)
    negative_control = lineage["negative_controls"]["historical_preboxed_capture"]
    image_path = WORKSPACE_ROOT / negative_control["path"]

    assert negative_control["sha256"] == HISTORICAL_PREBOXED_SHA256
    assert negative_control["source_image_kind"] == "historical_preboxed_capture"
    assert negative_control["editable_base_allowed"] is False
    assert negative_control["authoritative_current_source"] is False
    assert negative_control["artifact_is_authorization"] is False
    assert image_path.is_file()
    assert _sha256(image_path) == HISTORICAL_PREBOXED_SHA256


def test_portfolio_v1_critical_json_is_reviewable_without_hash_normalization() -> None:
    expected_attributes = {
        path: {
            "text": "unset",
            "eol": "unspecified",
            "diff": "set",
            "binary": "unspecified",
            "whitespace": "cr-at-eol",
        }
        for path in (SOURCE_PATH, ASSET_PATH)
    }
    paths = list(expected_attributes)
    command = [
        "git",
        "check-attr",
        "text",
        "eol",
        "diff",
        "binary",
        "whitespace",
        "--",
        *(path.relative_to(REPO_ROOT).as_posix() for path in paths),
    ]
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    for path in paths:
        relative = path.relative_to(REPO_ROOT).as_posix()
        for attribute, expected in expected_attributes[path].items():
            assert f"{relative}: {attribute}: {expected}" in completed.stdout
        filtered = subprocess.run(
            ["git", "hash-object", "--path", relative, relative],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.strip()
        raw = subprocess.run(
            ["git", "hash-object", "--no-filters", relative],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.strip()
        assert filtered == raw, f"Git attributes must preserve exact staged bytes for {relative}"

    assert _sha256(SOURCE_PATH) == SOURCE_SHA256
    assert _sha256(ASSET_PATH) == ASSET_SHA256


def test_portfolio_v1_review_source_may_keep_evidence_geometry_but_compiled_asset_cannot() -> None:
    source = _read(SOURCE_PATH)
    asset = _read(ASSET_PATH)

    job_detail = next(node for node in source["nodes"] if node["node_id"] == "job_detail")
    assert any("bbox" in region for region in job_detail["regions"])
    _forbidden_runtime_geometry(asset)
    assert asset["safety"]["historical_coordinates_used"] is False
    assert asset["safety"]["fresh_grounding_required"] is True


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
    assert edge["review_status"] == "human_approved"
    assert edge["reviewed_by_human"] is True
    assert edge["requires_user_confirmation"] is True


def test_portfolio_v1_job_detail_is_reviewed_with_one_executable_and_one_read_only_region() -> None:
    source = _read(SOURCE_PATH)
    job_detail = next(node for node in source["nodes"] if node["node_id"] == "job_detail")

    assert job_detail["review_status"] == "human_approved"
    assert job_detail["reviewed_by_human"] is True
    assert isinstance(job_detail.get("responsibility"), str) and job_detail["responsibility"].strip()
    by_label = {item["label"]: item for item in job_detail["regions"]}
    quick_apply = by_label["Quick apply"]
    save = by_label["Save"]
    assert quick_apply["semantic_action"] == "open_apply_flow"
    assert quick_apply["artifact_is_authorization"] is False
    assert quick_apply["execute_binding_enabled"] is False
    assert save["semantic_action"] == "read_only"
    assert save["destination"] == {"kind": "none"}
    assert save["artifact_is_authorization"] is False
    assert save["execute_binding_enabled"] is False

    control = next(item for item in job_detail["controls"] if item["control_id"] == "apply")
    assert control["role"] == "button"
    assert control["review_status"] == "human_approved"
    action = next(item for item in job_detail["action_candidates"] if item["action_template_id"] == "open_apply_flow")
    assert action["semantic_action"] == "open_apply_flow"
    assert action["target_interface_id"] == "apply_entry"
    assert action["review_status"] == "human_approved"
    assert action["display_only"] is True
    assert action["execute_binding_enabled"] is False
    assert action["verification_rule_ids"] == ["application_entry_visible"]


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


def test_portfolio_v1_reviewed_source_compiles_to_exact_checked_in_asset() -> None:
    from app.agent.reviewed_workflow_asset import canonical_json_bytes
    from app.agent.reviewed_workflow_compiler import compile_reviewed_workflow_asset_v2

    result = compile_reviewed_workflow_asset_v2(
        project_root=WORKSPACE_ROOT,
        source_workflow_path=SOURCE_PATH.relative_to(WORKSPACE_ROOT),
        expected_source_workflow_sha256=SOURCE_SHA256,
    )

    assert result["status"] == "compiled"
    assert result["blocked_reasons"] == []
    assert result["source_review_lineage"]["human_approved_node_ids"] == ["job_detail"]
    assert hashlib.sha256(canonical_json_bytes(result["asset"])).hexdigest() == ASSET_SHA256
    assert canonical_json_bytes(result["asset"]) == ASSET_PATH.read_bytes()
    asset = result["asset"]
    assert asset["safety"]["artifact_is_authorization"] is False
    assert asset["safety"]["execute_binding_enabled"] is False
    states = {state["source_node_id"]: state for state in asset["states"]}
    assert states["job_detail"]["availability"] == "reviewed"
    assert len(states["job_detail"]["allowed_transition_ids"]) == 1
    assert {anchor["label"] for anchor in states["job_detail"]["identity_anchors"]} >= {"Quick apply", "Save"}
    assert states["apply_entry"]["availability"] == "stop_boundary"
    assert states["apply_entry"]["allowed_transition_ids"] == []
    assert len(asset["transitions"]) == 1
    assert asset["transitions"][0]["semantic_action"] == "open_apply_flow"
    assert "save" not in json.dumps(asset["transitions"], ensure_ascii=False).casefold()
    _forbidden_runtime_geometry(asset)


def test_portfolio_v1_fresh_process_reloads_exact_active_asset(tmp_path: Path) -> None:
    portable_root = tmp_path / "portable-release-workspace"
    shutil.copytree(WORKSPACE_ROOT, portable_root)
    script = """
import hashlib
import json
import sys
from pathlib import Path
from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore, canonical_json_bytes

root = Path(sys.argv[1])
asset_id = sys.argv[2]
asset = ReviewedWorkflowAssetStore(project_root=root).load_active(asset_id)
print(json.dumps({
    "asset_id": asset["asset_id"],
    "content_sha256": hashlib.sha256(canonical_json_bytes(asset)).hexdigest(),
    "source_workflow_sha256": asset["source_review_lineage"]["source_workflow_sha256"],
    "artifact_is_authorization": asset["safety"]["artifact_is_authorization"],
    "execute_binding_enabled": asset["safety"]["execute_binding_enabled"],
}, sort_keys=True))
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    completed = subprocess.run(
        [sys.executable, "-c", script, str(portable_root), ASSET_ID],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    proof = json.loads(completed.stdout)

    assert proof == {
        "artifact_is_authorization": False,
        "asset_id": ASSET_ID,
        "content_sha256": ASSET_SHA256,
        "execute_binding_enabled": False,
        "source_workflow_sha256": SOURCE_SHA256,
    }


def test_portfolio_v1_asset_registry_uses_workspace_relative_paths() -> None:
    registry = _read(ASSET_REGISTRY_PATH)

    assert registry["contract_version"] == "reviewed_workflow_asset_registry_v2"
    assert registry["active_by_asset"] == {ASSET_ID: ASSET_SHA256}
    record = registry["objects"][ASSET_SHA256]
    assert record["object_path"] == ASSET_PATH.relative_to(WORKSPACE_ROOT).as_posix()
    assert record["content_sha256"] == ASSET_SHA256
    assert record["asset_id"] == ASSET_ID
    _assert_project_relative_paths(registry)
