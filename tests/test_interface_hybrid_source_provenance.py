from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path

import pytest


def _durable_snapshot(root: Path) -> dict[str, tuple[int, str]]:
    files = sorted(
        path for path in root.rglob("*")
        if path.is_file() and path.name != ".review-write.lock"
    )
    return {
        path.relative_to(root).as_posix(): (
            len(path.read_bytes()),
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in files
    }


def _assert_rejected_without_durable_writes(root: Path, operation, pattern: str) -> None:
    before = _durable_snapshot(root)
    with pytest.raises(ValueError, match=pattern):
        operation()
    assert _durable_snapshot(root) == before


def _canonical_hybrid_review(tmp_path: Path):
    from scripts.prove_portfolio_hybrid_v1_1_persistence import (
        _managed_proof_owner_context,
        _run_public_managed_hybrid_lifecycle,
        _save_public_large_review,
        fake_bounded_vista_runner,
        fake_omni_runner,
        fake_qwen_runner,
    )
    from app.learn.learning_draft_review_service import (
        load_interface_workflow_review_transaction,
    )

    root = tmp_path / "hybrid-source"
    store_path = root / "runtime_state" / "learning-workflow-runs.json"
    with _managed_proof_owner_context(
        root,
        workflow_store_path=store_path,
        omni_runner=fake_omni_runner,
        qwen_runner=fake_qwen_runner,
        vista_runner=fake_bounded_vista_runner,
    ) as (composition, store, _registry):
        lifecycle = _run_public_managed_hybrid_lifecycle(
            root, composition=composition, store=store
        )
        large = _save_public_large_review(root, workflow_store=store, lifecycle=lifecycle)
        source_path = Path(large["reviewed_candidate_path"]).relative_to(root).as_posix()
        review = load_interface_workflow_review_transaction(
            draft_source_paths=[source_path, source_path],
            workflow_run_ids_by_source={source_path: lifecycle["workflow_run_id"]},
            discover_related_sidecars=False,
            goal="Open a detail and stop at the application entry boundary.",
            application_identity={"url": "https://managed.example.test/jobs"},
            project_root=root,
            workflow_store=store,
        )
        return root, review, source_path


def test_hybrid_v2_provenance_round_trips_and_rejects_source_or_raw_tamper(
    tmp_path: Path,
) -> None:
    from app.learn.interface_workflow_service import (
        save_interface_workflow_review_transaction,
    )

    root, review, source_path = _canonical_hybrid_review(tmp_path)
    node = review["nodes"][0]
    provenance = node["hybrid_review_source_provenance"]
    assert provenance["contract_version"] == "interface_hybrid_review_source_provenance_v1"
    assert provenance["sources"] == [
        {
            "source_path": source_path,
            "source_sha256": node["evidence"]["source_sha256"],
            "projection_ref": provenance["sources"][0]["projection_ref"],
        }
    ]
    assert node["source_paths"] == [source_path]

    saved = save_interface_workflow_review_transaction(
        review, project_root=root, out_dir=None
    )
    saved_node = saved["saved_review"]["nodes"][0]
    assert saved_node["hybrid_review_source_provenance"] == provenance
    assert saved_node["regions"] == node["regions"]

    variants: list[tuple[dict, str]] = []
    source_sha_tamper = deepcopy(review)
    source_sha_tamper["nodes"][0]["hybrid_review_source_provenance"]["sources"][0]["source_sha256"] = "0" * 64
    variants.append((source_sha_tamper, "hybrid review source"))
    projection_ref_tamper = deepcopy(review)
    projection_ref_tamper["nodes"][0]["hybrid_review_source_provenance"]["sources"][0]["projection_ref"]["content_sha256"] = "0" * 64
    variants.append((projection_ref_tamper, "hybrid review source"))
    dropped_source = deepcopy(review)
    dropped_source["nodes"][0]["source_paths"] = []
    variants.append((dropped_source, "hybrid review source"))
    duplicate_source = deepcopy(review)
    duplicate_source["nodes"][0]["source_paths"] = [source_path, source_path]
    variants.append((duplicate_source, "hybrid review source"))
    added_source = deepcopy(review)
    added_source["nodes"][0]["source_paths"].append("missing-reviewed-source.json")
    added_source["nodes"][0]["hybrid_review_source_provenance"]["sources"].append({
        "source_path": "missing-reviewed-source.json",
        "source_sha256": "0" * 64,
        "projection_ref": deepcopy(provenance["sources"][0]["projection_ref"]),
    })
    variants.append((added_source, "hybrid review source"))
    escaped_source = deepcopy(review)
    escaped_source["nodes"][0]["source_paths"] = ["../escaped-reviewed-source.json"]
    escaped_source["nodes"][0]["hybrid_review_source_provenance"]["sources"] = [{
        "source_path": "../escaped-reviewed-source.json",
        "source_sha256": "0" * 64,
        "projection_ref": deepcopy(provenance["sources"][0]["projection_ref"]),
    }]
    variants.append((escaped_source, "hybrid review source"))
    for candidate, pattern in variants:
        _assert_rejected_without_durable_writes(
            root,
            lambda candidate=candidate: save_interface_workflow_review_transaction(
                candidate, project_root=root, out_dir=None
            ),
            pattern,
        )

    for field_name in (
        "model_proposal",
        "review_decisions",
        "reviewed_geometry",
        "reviewed_semantics",
        "human_point_proposal",
    ):
        raw_tamper = deepcopy(review)
        raw_tamper["nodes"][0]["regions"][0][field_name] = {"tampered": True}
        _assert_rejected_without_durable_writes(
            root,
            lambda raw_tamper=raw_tamper: save_interface_workflow_review_transaction(
                raw_tamper, project_root=root, out_dir=None
            ),
            "hybrid review raw evidence",
        )

    for field_name in ("label", "bbox", "provider_provenance", "tombstone", "active"):
        rendered_tamper = deepcopy(review)
        rendered_tamper["nodes"][0]["regions"][0][field_name] = {"tampered": True}
        _assert_rejected_without_durable_writes(
            root,
            lambda rendered_tamper=rendered_tamper: save_interface_workflow_review_transaction(
                rendered_tamper, project_root=root, out_dir=None
            ),
            "hybrid review region",
        )

def test_hybrid_v2_validation_does_not_accept_mixed_or_unknown_raw_candidates(
    tmp_path: Path,
) -> None:
    from app.learn.interface_workflow_service import (
        save_interface_workflow_review_transaction,
    )

    root, review, _source_path = _canonical_hybrid_review(tmp_path)
    mixed = deepcopy(review)
    mixed["nodes"][0]["selection_replay_provenance"] = {
        "contract_version": "interface_selection_replay_provenance_v1",
        "execution_origin": "replay",
        "simulated_offline": True,
        "projection_ref": {"id": "selection/test", "content_sha256": "0" * 64},
    }
    with pytest.raises(ValueError, match="mixed selection and hybrid"):
        save_interface_workflow_review_transaction(mixed, project_root=root, out_dir=None)

    unknown = deepcopy(review)
    unknown["nodes"][0].pop("hybrid_review_source_provenance")
    unknown_region = unknown["nodes"][0]["regions"][0]
    unknown_region["kind"] = "unknown_candidate_kind"
    for field_name in (
        "model_proposal",
        "review_decisions",
        "reviewed_geometry",
        "reviewed_semantics",
    ):
        unknown_region.pop(field_name, None)
    assert unknown_region.get("candidate_id")
    assert "human_point_proposal" in unknown_region
    with pytest.raises(ValueError, match="selection replay source"):
        save_interface_workflow_review_transaction(unknown, project_root=root, out_dir=None)

    generic_region = deepcopy(unknown_region)
    generic_region.pop("candidate_id", None)
    generic_region["unrecognized_note"] = {"preserve": "manual"}
    from app.learn import interface_workflow_review as review_module
    assert review_module._selection_provenance_indicated(
        {"regions": [generic_region]}
    ) is False


def test_hybrid_v2_rejects_source_drift_and_editable_copy_as_authority(
    tmp_path: Path,
) -> None:
    from app.learn.interface_workflow_service import (
        save_interface_workflow_review_transaction,
    )

    root, review, source_path = _canonical_hybrid_review(tmp_path)
    first = save_interface_workflow_review_transaction(
        review, project_root=root, out_dir=None
    )
    repeated = save_interface_workflow_review_transaction(
        first["saved_review"], project_root=root, out_dir=None
    )
    saved_node = repeated["saved_review"]["nodes"][0]
    assert saved_node["source_paths"] == [source_path]

    editable_only = deepcopy(review)
    editable_relative = saved_node["editable_review_source_path"]
    editable_path = root / editable_relative
    editable_sha256 = hashlib.sha256(editable_path.read_bytes()).hexdigest()
    editable_node = editable_only["nodes"][0]
    editable_node["source_paths"] = [editable_relative]
    editable_node["hybrid_review_source_provenance"]["sources"] = [{
        "source_path": editable_relative,
        "source_sha256": editable_sha256,
        "projection_ref": deepcopy(
            editable_node["hybrid_review_source_provenance"]["sources"][0]["projection_ref"]
        ),
    }]
    _assert_rejected_without_durable_writes(
        root,
        lambda: save_interface_workflow_review_transaction(
            editable_only, project_root=root, out_dir=None
        ),
        "hybrid review source",
    )

    source_file = root / source_path
    source_file.write_bytes(source_file.read_bytes() + b"\n")
    _assert_rejected_without_durable_writes(
        root,
        lambda: save_interface_workflow_review_transaction(review, project_root=root, out_dir=None),
        "hybrid review source",
    )


def test_hybrid_v2_prewrite_snapshot_rejects_source_change_without_dest_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn import interface_workflow_review as review_module
    from app.learn.interface_workflow_service import (
        save_interface_workflow_review_transaction,
    )

    root, review, source_path = _canonical_hybrid_review(tmp_path)
    destination_root = root / "artifacts" / "interface-workflow-reviews"
    before_destination = _durable_snapshot(destination_root) if destination_root.exists() else {}
    original_validate = review_module._validate_hybrid_review_source_provenance

    def validate_then_change_source(nodes, *, project_root):
        result = original_validate(nodes, project_root=project_root)
        source = root / source_path
        source.write_bytes(source.read_bytes() + b"\n")
        return result

    monkeypatch.setattr(
        review_module,
        "_validate_hybrid_review_source_provenance",
        validate_then_change_source,
    )
    with pytest.raises(ValueError, match="hybrid authoritative source changed before materialization"):
        save_interface_workflow_review_transaction(review, project_root=root, out_dir=None)
    after_destination = _durable_snapshot(destination_root) if destination_root.exists() else {}
    assert after_destination == before_destination


def test_hybrid_v2_and_selection_v1_nodes_save_together(tmp_path: Path) -> None:
    from app.learn.draft_review import load_learning_draft_review
    from app.learn.hybrid.selection_persistence import persist_selection_review_trial
    from app.learn.interface_workflow_review import build_interface_workflow_review
    from app.learn.interface_workflow_service import (
        save_interface_workflow_review_transaction,
    )
    from app.learn.workflow_tasks.hybrid_selection import run_hybrid_selection_task
    from tests.test_learning_selection_roundtrip import _payload

    root, hybrid_review, _source_path = _canonical_hybrid_review(tmp_path)
    _facts, payload = _payload(root)
    selection_path = persist_selection_review_trial(
        project_root=root, payload=payload, response=run_hybrid_selection_task(payload)
    )
    selection_review = load_learning_draft_review(selection_path, project_root=root)
    selection_graph = build_interface_workflow_review(
        goal=hybrid_review["workflow"]["goal"],
        application_identity=hybrid_review["workflow"]["application_identity"],
        draft_sources=[selection_review],
    )
    selection_node = selection_graph["nodes"][0]
    combined = deepcopy(hybrid_review)
    combined["nodes"].append(selection_node)
    combined["workflow"]["node_ids"].append(selection_node["node_id"])
    saved = save_interface_workflow_review_transaction(
        combined, project_root=root, out_dir=None
    )
    assert {node["node_id"] for node in saved["saved_review"]["nodes"]} == {
        node["node_id"] for node in combined["nodes"]
    }


@pytest.mark.parametrize("mutation", ["drop", "duplicate", "add", "erase_provenance_only"])
def test_hybrid_source_requires_complete_candidate_identity_set(tmp_path: Path, mutation: str) -> None:
    from app.learn.interface_workflow_service import save_interface_workflow_review_transaction

    root, review, _source_path = _canonical_hybrid_review(tmp_path)
    node = review["nodes"][0]
    assert node["regions"]
    if mutation == "duplicate":
        node["regions"].append(deepcopy(node["regions"][0]))
    elif mutation == "add":
        extra = deepcopy(node["regions"][0])
        extra.update(region_id="unknown", candidate_id="unknown")
        node["regions"].append(extra)
    elif mutation == "drop":
        node["regions"] = []
    else:
        node.pop("hybrid_review_source_provenance")
    _assert_rejected_without_durable_writes(
        root, lambda: save_interface_workflow_review_transaction(review, project_root=root, out_dir=None),
        "hybrid review",
    )


def test_selection_source_still_classifies_node_when_client_erases_metadata(tmp_path: Path) -> None:
    from app.learn.interface_workflow_review import build_interface_workflow_review
    from app.learn.interface_workflow_service import save_interface_workflow_review_transaction
    from tests.test_learning_selection_save_integrity import _selection_trial

    _trial, loaded = _selection_trial(tmp_path)
    review = build_interface_workflow_review(
        goal="Keep source classification", application_identity={"url": "https://fixture.example.test"},
        draft_sources=[loaded],
    )
    node = review["nodes"][0]
    assert node["selection_replay_provenance"]
    node["regions"] = []
    node.pop("selection_replay_provenance")
    _assert_rejected_without_durable_writes(
        tmp_path, lambda: save_interface_workflow_review_transaction(review, project_root=tmp_path, out_dir=None),
        "selection replay provenance",
    )


def test_distinct_hybrid_parents_reject_before_first_save(tmp_path: Path) -> None:
    from app.learn.draft_review import validate_reviewed_template_candidate_source
    from app.learn.interface_workflow_service import save_interface_workflow_review_transaction

    root, review, source_path = _canonical_hybrid_review(tmp_path)
    clone = root / "artifacts" / "second-reviewed-candidate.json"
    clone.write_bytes((root / source_path).read_bytes())
    clone_ref = validate_reviewed_template_candidate_source(clone, project_root=root)
    node = review["nodes"][0]
    node["source_paths"].append(clone_ref["id"])
    second = deepcopy(node["hybrid_review_source_provenance"]["sources"][0])
    second["source_path"] = clone_ref["id"]
    assert second["source_sha256"] == clone_ref["content_sha256"]
    node["hybrid_review_source_provenance"]["sources"].append(second)
    _assert_rejected_without_durable_writes(
        root, lambda: save_interface_workflow_review_transaction(review, project_root=root, out_dir=None),
        "one canonical source per node",
    )


def test_late_hybrid_source_change_never_rebinds_verified_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import json
    from app.learn import interface_workflow_review as review_module
    from app.learn.interface_workflow_service import save_interface_workflow_review_transaction

    root, review, source_path = _canonical_hybrid_review(tmp_path)
    expected_sha = review["nodes"][0]["hybrid_review_source_provenance"]["sources"][0]["source_sha256"]
    materialize = review_module._materialize_durable_node_evidence

    def replace_after_preflight(*args, **kwargs):
        materialize(*args, **kwargs)
        source = root / source_path
        source.write_bytes(source.read_bytes() + b"\n")

    monkeypatch.setattr(review_module, "_materialize_durable_node_evidence", replace_after_preflight)
    saved = save_interface_workflow_review_transaction(review, project_root=root, out_dir=None)
    node = saved["saved_review"]["nodes"][0]
    assert node["evidence"]["authoritative_source_ref"] == {"id": source_path, "content_sha256": expected_sha}
    assert hashlib.sha256((root / source_path).read_bytes()).hexdigest() != expected_sha
    registry = review_module.load_interface_workflow_library_registry(project_root=root)
    record = registry["workflows"][saved["workflow_id"]]
    integrity = review_module.evaluate_interface_workflow_node_integrity(
        review=saved["saved_review"], node=node, record=record, project_root=root,
        source_asset_sha256=hashlib.sha256(Path(saved["path"]).read_bytes()).hexdigest(),
    )
    assert integrity["integrity_verified"] is False
    assert integrity["eligibility"]["agent_usable"] is False
    assert json.loads(Path(saved["path"]).read_text(encoding="utf-8"))["nodes"][0]["evidence"]["authoritative_source_ref"]["content_sha256"] == expected_sha
