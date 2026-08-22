from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile

import pytest


def _base_review() -> dict:
    node_ids = ["home", "detail", "apply_entry"]
    return {
        "contract_version": "single_application_workflow_review_v1",
        "workflow": {
            "workflow_id": "seek_home_to_apply",
            "goal": "Open a job detail then the same-site application entry.",
            "application_identity": {"url": "https://nz.seek.com/jobs"},
            "entry_node_id": "home",
            "node_ids": node_ids,
            "edge_ids": ["home_to_detail", "detail_to_apply"],
            "review_status": "human_approved",
        },
        "nodes": [
            {
                "node_id": "home",
                "display_name": "SEEK job results",
                "surface_type": "results",
                "state_signature": "seek-home",
                "source_paths": [],
                "evidence": {},
                "controls": [{"control_id": "job_card", "label": "Job result"}],
                "regions": [],
                "review_status": "needs_human_review",
                "reviewed_by_human": False,
            },
            {
                "node_id": "detail",
                "display_name": "SEEK job detail",
                "surface_type": "detail",
                "state_signature": "seek-detail",
                "source_paths": [],
                "evidence": {},
                "controls": [{"control_id": "quick_apply", "label": "Quick apply"}],
                "regions": [],
                "review_status": "needs_human_review",
                "reviewed_by_human": False,
            },
            {
                "node_id": "apply_entry",
                "display_name": "Application entry boundary",
                "surface_type": "application",
                "state_signature": "seek-apply-entry",
                "source_paths": [],
                "evidence": {},
                "controls": [],
                "regions": [],
                "review_status": "needs_learning",
                "reviewed_by_human": False,
            },
        ],
        "edges": [
            {
                "edge_id": "home_to_detail",
                "operation_id": "home_to_detail",
                "source_node_id": "home",
                "target_node_id": "detail",
                "action_type": "open_detail",
                "target_control_id": "job_card",
                "target_region_id": "",
                "risk_level": "low",
                "requires_user_confirmation": False,
                "preconditions": [],
                "success_conditions": ["Job detail identity is visible"],
                "failure_conditions": [],
                "review_status": "human_approved",
            },
            {
                "edge_id": "detail_to_apply",
                "operation_id": "detail_to_apply",
                "source_node_id": "detail",
                "target_node_id": "apply_entry",
                "action_type": "open_apply_flow",
                "target_control_id": "quick_apply",
                "target_region_id": "",
                "risk_level": "low",
                "requires_user_confirmation": False,
                "preconditions": [],
                "success_conditions": ["Same-site application entry is visible"],
                "failure_conditions": [],
                "review_status": "human_approved",
            },
        ],
        "safety": {},
    }


def _persist_reviewed_workflow(tmp_path: Path, review: dict | None = None) -> tuple[Path, str]:
    from app.learn.interface_workflow_review import (
        build_interface_node_review_revision,
        save_interface_workflow_review_candidate,
    )

    first = save_interface_workflow_review_candidate(review or _base_review(), project_root=tmp_path)
    path = Path(first["path"])
    review = json.loads(path.read_text(encoding="utf-8"))
    for node in review["nodes"][:2]:
        node["review_status"] = "human_approved"
        node["reviewed_by_human"] = True
        node["human_review_confirmation"] = {
            "contract_version": "interface_node_human_review_confirmation_v1",
            "revision": build_interface_node_review_revision(review, node_id=node["node_id"]),
        }
    saved = save_interface_workflow_review_candidate(review, project_root=tmp_path)
    source = Path(saved["path"])
    return source, hashlib.sha256(source.read_bytes()).hexdigest()


def _compile(tmp_path: Path):
    from app.agent.reviewed_workflow_compiler import compile_reviewed_workflow_asset_v2

    source, digest = _persist_reviewed_workflow(tmp_path)
    result = compile_reviewed_workflow_asset_v2(
        project_root=tmp_path,
        source_workflow_path=source.relative_to(tmp_path),
        expected_source_workflow_sha256=digest,
    )
    return source, digest, result


def _run_compile(tmp_path: Path, source: Path, digest: str) -> dict:
    from app.agent.reviewed_workflow_compiler import compile_reviewed_workflow_asset_v2

    return compile_reviewed_workflow_asset_v2(
        project_root=tmp_path,
        source_workflow_path=source.relative_to(tmp_path),
        expected_source_workflow_sha256=digest,
    )


def _registry_path(tmp_path: Path) -> Path:
    return tmp_path / "artifacts" / "interface-workflow-reviews" / "registry.json"


def _rebind_registry_source_sha(tmp_path: Path, digest: str) -> None:
    registry_path = _registry_path(tmp_path)
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["workflows"]["seek_home_to_apply"]["source_asset_sha256"] = digest
    registry_path.write_text(json.dumps(registry, ensure_ascii=False), encoding="utf-8")


def test_compiles_reviewed_seek_path_to_safe_stop_boundary_without_writing_store(tmp_path: Path) -> None:
    source, digest, result = _compile(tmp_path)

    assert result["contract_version"] == "reviewed_workflow_compile_result_v2"
    assert result["status"] == "compiled"
    assert result["blocked_reasons"] == []
    asset = result["asset"]
    assert asset["contract_version"] == "reviewed_workflow_asset_v2"
    assert asset["source_review_lineage"]["source_workflow_sha256"] == digest
    assert [state["availability"] for state in asset["states"]] == [
        "stop_boundary", "reviewed", "reviewed"
    ]
    boundary = next(state for state in asset["states"] if state["source_node_id"] == "apply_entry")
    assert boundary["allowed_transition_ids"] == []
    assert {edge["semantic_action"] for edge in asset["transitions"]} == {"open_detail", "open_apply_flow"}
    serialized = json.dumps(asset, ensure_ascii=False)
    assert '"x":' not in serialized and "hwnd" not in serialized
    assert not (tmp_path / "runtime_state" / "reviewed-workflow-assets-v2").exists()
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest


@pytest.mark.parametrize(
    ("semantic_action", "edge_id", "success_condition"),
    [
        ("open_detail", "home_to_detail", "Job detail identity is visible"),
        ("open_apply_flow", "detail_to_apply", "Same-site application entry is visible"),
    ],
)
def test_compiled_transition_uses_closed_target_state_identity_post_verification_rule(
    tmp_path: Path,
    semantic_action: str,
    edge_id: str,
    success_condition: str,
) -> None:
    from app.agent.reviewed_workflow_compiler import _safe_id

    review = _base_review()
    source_edge = next(item for item in review["edges"] if item["edge_id"] == edge_id)
    source_edge["success_conditions"] = [f"  {success_condition}  "]
    source, digest = _persist_reviewed_workflow(tmp_path, review)

    result = _run_compile(tmp_path, source, digest)

    assert result["status"] == "compiled"
    transition = next(
        item
        for item in result["asset"]["transitions"]
        if item["semantic_action"] == semantic_action
    )
    expected_rule_id = _safe_id(
        "rule_",
        f"{edge_id}:target_state_identity:{transition['target_state_id']}",
    )
    assert transition["post_action_verification"] == {
        "requires_new_capture": True,
        "semantic_success_rules": [
            {"rule_id": expected_rule_id, "type": "target_state_identity"}
        ],
    }
    assert transition["expected_effect"]["semantic_success_rules"] == [
        {
            "rule_id": _safe_id("rule_", f"{edge_id}:success_conditions:1"),
            "type": "source_semantic_success_condition",
            "condition": success_condition,
        }
    ]


def test_blocks_mismatched_source_sha_and_registry_record(tmp_path: Path) -> None:
    source, digest = _persist_reviewed_workflow(tmp_path)
    from app.agent.reviewed_workflow_compiler import compile_reviewed_workflow_asset_v2

    mismatch = compile_reviewed_workflow_asset_v2(
        project_root=tmp_path,
        source_workflow_path=source.relative_to(tmp_path),
        expected_source_workflow_sha256="0" * 64,
    )
    assert mismatch["status"] == "blocked"
    assert {item["code"] for item in mismatch["blocked_reasons"]} == {"source_workflow_sha256_mismatch"}

    registry_path = tmp_path / "artifacts" / "interface-workflow-reviews" / "registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["workflows"]["seek_home_to_apply"]["source_asset_sha256"] = "1" * 64
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    result = compile_reviewed_workflow_asset_v2(
        project_root=tmp_path,
        source_workflow_path=source.relative_to(tmp_path),
        expected_source_workflow_sha256=digest,
    )
    assert result["status"] == "blocked"
    assert "registry_source_asset_sha256_mismatch" in {item["code"] for item in result["blocked_reasons"]}


def test_blocks_edge_only_approval_and_disallowed_actions(tmp_path: Path) -> None:
    source, digest = _persist_reviewed_workflow(tmp_path)
    from app.agent.reviewed_workflow_compiler import compile_reviewed_workflow_asset_v2

    review = json.loads(source.read_text(encoding="utf-8"))
    review["nodes"][0]["reviewed_by_human"] = False
    review["nodes"][0]["review_status"] = "needs_human_review"
    review["edges"][0]["review_status"] = "human_approved"
    source.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
    changed = hashlib.sha256(source.read_bytes()).hexdigest()
    registry_path = tmp_path / "artifacts" / "interface-workflow-reviews" / "registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["workflows"]["seek_home_to_apply"]["source_asset_sha256"] = changed
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    blocked = compile_reviewed_workflow_asset_v2(
        project_root=tmp_path,
        source_workflow_path=source.relative_to(tmp_path),
        expected_source_workflow_sha256=changed,
    )
    assert blocked["status"] == "blocked"
    assert "source_node_not_human_reviewed" in {item["code"] for item in blocked["blocked_reasons"]}


def test_blocks_non_mvp_action_missing_semantic_success_and_unknown_element(tmp_path: Path) -> None:
    from app.agent.reviewed_workflow_compiler import compile_reviewed_workflow_asset_v2

    cases = [
        ("action", "semantic_action_not_mvp_executable"),
        ("success", "success_conditions_missing"),
        ("element", "edge_target_element_invalid"),
    ]
    for index, (case, expected_code) in enumerate(cases):
        review = _base_review()
        edge = review["edges"][0]
        if case == "action":
            edge["action_type"] = "fill_field"
        elif case == "success":
            edge["success_conditions"] = []
        else:
            edge["target_control_id"] = "missing_control"
        case_root = tmp_path / str(index)
        source, digest = _persist_reviewed_workflow(case_root, review)
        result = compile_reviewed_workflow_asset_v2(
            project_root=case_root,
            source_workflow_path=source.relative_to(case_root),
            expected_source_workflow_sha256=digest,
        )
        assert result["status"] == "blocked"
        assert expected_code in {item["code"] for item in result["blocked_reasons"]}


def test_preserves_reviewed_semantic_constraints_and_confirmation_risk(tmp_path: Path) -> None:
    review = _base_review()
    edge = review["edges"][0]
    edge["preconditions"] = ["Signed-in session is visible", "Results pane is active"]
    edge["failure_conditions"] = ["External ATS navigation appears"]
    edge["risk_level"] = "high"
    edge["requires_user_confirmation"] = True
    source, digest = _persist_reviewed_workflow(tmp_path, review)

    result = _run_compile(tmp_path, source, digest)

    assert result["status"] == "compiled"
    transition = next(
        item for item in result["asset"]["transitions"] if item["semantic_action"] == "open_detail"
    )
    constraints = transition["reviewed_semantic_constraints"]
    assert [item["condition"] for item in constraints["preconditions"]] == edge["preconditions"]
    assert [item["condition"] for item in constraints["failure_conditions"]] == edge["failure_conditions"]
    assert transition["risk_policy"] == {
        "risk_level": "high",
        "requires_gate": True,
        "final_submit_forbidden": True,
        "requires_user_confirmation": True,
        "automatic_execution_allowed": False,
    }


def test_registry_embedded_application_identity_is_authoritative(tmp_path: Path) -> None:
    source, digest = _persist_reviewed_workflow(tmp_path)
    registry_path = _registry_path(tmp_path)
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["applications"]["web:nz.seek.com"]["application_identity"] = {
        "url": "https://evil.example/jobs"
    }
    registry_path.write_text(json.dumps(registry), encoding="utf-8")

    result = _run_compile(tmp_path, source, digest)

    assert result["status"] == "blocked"
    assert "registry_embedded_application_identity_mismatch" in {
        item["code"] for item in result["blocked_reasons"]
    }


def test_invalid_source_application_identity_returns_structured_block(tmp_path: Path) -> None:
    source, _ = _persist_reviewed_workflow(tmp_path)
    review = json.loads(source.read_text(encoding="utf-8"))
    review["workflow"]["application_identity"] = {
        "url": "https://nz.seek.com:bad/jobs"
    }
    source.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()

    result = _run_compile(tmp_path, source, digest)

    assert result["status"] == "blocked"
    assert result["asset"] is None
    assert {item["code"] for item in result["blocked_reasons"]} == {
        "application_identity_invalid"
    }
    assert "bad" not in result["blocked_reasons"][0]["detail"]


def test_invalid_registry_embedded_identity_returns_structured_block(tmp_path: Path) -> None:
    source, digest = _persist_reviewed_workflow(tmp_path)
    registry_path = _registry_path(tmp_path)
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["applications"]["web:nz.seek.com"]["application_identity"] = {
        "url": "https://nz.seek.com:bad"
    }
    registry_path.write_text(json.dumps(registry), encoding="utf-8")

    result = _run_compile(tmp_path, source, digest)

    assert result["status"] == "blocked"
    assert result["asset"] is None
    assert {item["code"] for item in result["blocked_reasons"]} == {
        "registry_embedded_application_identity_invalid"
    }
    assert "bad" not in result["blocked_reasons"][0]["detail"]


def test_safe_ids_use_128_bit_suffix_and_are_deterministic() -> None:
    from app.agent.reviewed_workflow_compiler import _safe_id

    first_source = "same normalized prefix " + "a" * 300 + "!"
    second_source = "same normalized prefix " + "a" * 300 + "?"
    first = _safe_id("state_", first_source)
    repeated = _safe_id("state_", first_source)
    second = _safe_id("state_", second_source)

    assert first == repeated
    assert first != second
    assert len(first) <= 128 and len(second) <= 128
    assert len(first.rsplit("_", 1)[1]) >= 32


def test_repeated_compile_is_byte_deterministic(tmp_path: Path) -> None:
    source, digest = _persist_reviewed_workflow(tmp_path)

    first = _run_compile(tmp_path, source, digest)
    second = _run_compile(tmp_path, source, digest)

    assert first == second
    assert json.dumps(first, ensure_ascii=False, sort_keys=True) == json.dumps(
        second, ensure_ascii=False, sort_keys=True
    )


def test_blocks_path_traversal_and_symlink_escape(tmp_path: Path) -> None:
    from app.agent.reviewed_workflow_compiler import compile_reviewed_workflow_asset_v2

    source, digest = _persist_reviewed_workflow(tmp_path)
    traversal = compile_reviewed_workflow_asset_v2(
        project_root=tmp_path,
        source_workflow_path=Path("..") / source.name,
        expected_source_workflow_sha256=digest,
    )
    assert {item["code"] for item in traversal["blocked_reasons"]} == {
        "source_workflow_path_invalid"
    }

    with tempfile.TemporaryDirectory(dir=tmp_path.parent) as external_dir:
        external = Path(external_dir) / "reviewed_workflow.json"
        external.write_bytes(source.read_bytes())
        link = tmp_path / "escaped_workflow.json"
        try:
            link.symlink_to(external)
        except OSError as exc:
            pytest.skip(f"symlink creation unavailable: {exc}")
        escaped = compile_reviewed_workflow_asset_v2(
            project_root=tmp_path,
            source_workflow_path=link.relative_to(tmp_path),
            expected_source_workflow_sha256=digest,
        )
        assert {item["code"] for item in escaped["blocked_reasons"]} == {
            "source_workflow_path_invalid"
        }


def test_blocks_registry_path_mismatch(tmp_path: Path) -> None:
    source, digest = _persist_reviewed_workflow(tmp_path)
    other = source.parent / "other_reviewed_workflow.json"
    other.write_bytes(source.read_bytes())
    registry_path = _registry_path(tmp_path)
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["workflows"]["seek_home_to_apply"]["path"] = str(other)
    registry_path.write_text(json.dumps(registry), encoding="utf-8")

    result = _run_compile(tmp_path, source, digest)

    assert result["status"] == "blocked"
    assert "registry_path_mismatch" in {item["code"] for item in result["blocked_reasons"]}


def test_evidence_tamper_blocks_reviewed_node(tmp_path: Path) -> None:
    review = _base_review()
    evidence_path = tmp_path / "synthetic" / "home.png"
    evidence_path.parent.mkdir(parents=True)
    evidence_path.write_bytes(b"synthetic-image-v1")
    review["nodes"][0]["evidence"] = {
        "source_screenshot_path": "synthetic/home.png"
    }
    source, digest = _persist_reviewed_workflow(tmp_path, review)
    persisted = json.loads(source.read_text(encoding="utf-8"))
    persisted_evidence = tmp_path / persisted["nodes"][0]["evidence"]["source_screenshot_path"]
    persisted_evidence.write_bytes(b"tampered-image-v2")

    result = _run_compile(tmp_path, source, digest)

    assert result["status"] == "blocked"
    assert "source_node_not_human_reviewed" in {
        item["code"] for item in result["blocked_reasons"]
    }


def test_stop_boundary_cannot_have_outgoing_edge(tmp_path: Path) -> None:
    review = _base_review()
    review["nodes"][2]["controls"] = [
        {"control_id": "unsafe_continue", "label": "Continue"}
    ]
    review["workflow"]["edge_ids"].append("boundary_to_home")
    review["edges"].append(
        {
            "edge_id": "boundary_to_home",
            "operation_id": "boundary_to_home",
            "source_node_id": "apply_entry",
            "target_node_id": "home",
            "action_type": "open_detail",
            "target_control_id": "unsafe_continue",
            "target_region_id": "",
            "risk_level": "low",
            "requires_user_confirmation": False,
            "preconditions": [],
            "success_conditions": ["Home is visible"],
            "failure_conditions": [],
            "review_status": "human_approved",
        }
    )
    source, digest = _persist_reviewed_workflow(tmp_path, review)

    result = _run_compile(tmp_path, source, digest)

    assert result["status"] == "blocked"
    assert "stop_boundary_has_outgoing_transition" in {
        item["code"] for item in result["blocked_reasons"]
    }


def test_element_reference_must_belong_to_edge_source_node(tmp_path: Path) -> None:
    review = _base_review()
    review["edges"][0]["target_control_id"] = "quick_apply"
    source, digest = _persist_reviewed_workflow(tmp_path, review)

    result = _run_compile(tmp_path, source, digest)

    assert result["status"] == "blocked"
    assert "edge_target_element_invalid" in {
        item["code"] for item in result["blocked_reasons"]
    }


@pytest.mark.parametrize(
    "action",
    [
        "fill_field",
        "continue_next_step",
        "select_option",
        "read",
        "scroll",
        "wait",
        "unknown_action",
        "open_external_apply",
        "final_submit",
        "send",
        "confirm",
        "payment",
        "delete",
    ],
)
def test_blocks_every_disallowed_action(tmp_path: Path, action: str) -> None:
    source, _ = _persist_reviewed_workflow(tmp_path)
    review = json.loads(source.read_text(encoding="utf-8"))
    review["edges"][0]["action_type"] = action
    source.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    _rebind_registry_source_sha(tmp_path, digest)

    result = _run_compile(tmp_path, source, digest)

    assert result["status"] == "blocked"
    assert "semantic_action_not_mvp_executable" in {
        item["code"] for item in result["blocked_reasons"]
    }


@pytest.mark.parametrize(
    ("field_name", "value", "expected_code"),
    [
        ("preconditions", ["valid", 7], "semantic_condition_malformed"),
        ("failure_conditions", [{"unexpected": True}], "semantic_condition_malformed"),
        ("success_conditions", [""], "semantic_condition_malformed"),
        ("success_conditions", [], "success_conditions_missing"),
    ],
)
def test_blocks_malformed_or_missing_semantic_conditions(
    tmp_path: Path, field_name: str, value: list, expected_code: str
) -> None:
    source, _ = _persist_reviewed_workflow(tmp_path)
    review = json.loads(source.read_text(encoding="utf-8"))
    review["edges"][0][field_name] = value
    source.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    _rebind_registry_source_sha(tmp_path, digest)

    result = _run_compile(tmp_path, source, digest)

    assert result["status"] == "blocked"
    assert expected_code in {item["code"] for item in result["blocked_reasons"]}


def test_edge_edit_after_human_review_breaks_source_revision_authority(tmp_path: Path) -> None:
    source, _ = _persist_reviewed_workflow(tmp_path)
    review = json.loads(source.read_text(encoding="utf-8"))
    review["edges"][0]["success_conditions"] = ["Edited after review"]
    source.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    _rebind_registry_source_sha(tmp_path, digest)

    result = _run_compile(tmp_path, source, digest)

    assert result["status"] == "blocked"
    assert "source_node_not_human_reviewed" in {
        item["code"] for item in result["blocked_reasons"]
    }
