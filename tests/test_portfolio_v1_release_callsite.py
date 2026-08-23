from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import pytest

from app.agent.reviewed_workflow_asset import (
    content_sha256,
    validate_reviewed_workflow_asset,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "portfolio_v1_release_callsite"
ASSET_ID = "workflow_portfolio_v1_seek_apply_entry_fe297b5738f8c17790429e925ceab6f0"
ASSET_SHA256 = "a9eb42d9439568770735f69ff109e6d93b86085507414d62ee49cfef33bb1d1b"
SOURCE_WORKFLOW_ID = "portfolio_v1_seek_apply_entry"
SOURCE_WORKFLOW_SHA256 = "9ca9de68ae7a6dcd9f18c10384f2cefb63b6d83648ea10a95e1c5ef9c4283968"
SOURCE_SCREENSHOT_SHA256 = "274658095317e1aed1a9a68d6a3e7a80a6edddcde2e3d94bb11937932258ff1b"
HUMAN_REVIEW_OVERLAY_SHA256 = "27478cff6c05724a6e5929c7b725764d79f2c5864ecf9c7d61bef503fac877cb"
EXPECTED_RELEASE_MANIFEST: dict[str, Any] = {
    "contract_version": "portfolio_v1_release_callsite_fixture_v1",
    "asset_id": ASSET_ID,
    "asset_content_sha256": ASSET_SHA256,
    "source_workflow_id": SOURCE_WORKFLOW_ID,
    "source_workflow_sha256": SOURCE_WORKFLOW_SHA256,
    "reviewed_revision_hash": (
        "8e512cb94091ad8fd1c67afeba55ff68477c542da28de9da8f05de6416ce4ed7"
    ),
    "current_revision_hash": (
        "8e512cb94091ad8fd1c67afeba55ff68477c542da28de9da8f05de6416ce4ed7"
    ),
    "evidence_sha256": (
        "a201d537ebba727167bc0005e1a246213a5b6aa4a105fdbfb2ea011078a41fab"
    ),
    "job_detail_node_revision_hash": (
        "4d58e3774612275359a5627753e159697b036c66c614103d272b44c7612432c1"
    ),
    "source_screenshot_sha256": SOURCE_SCREENSHOT_SHA256,
    "human_review_overlay_sha256": HUMAN_REVIEW_OVERLAY_SHA256,
    "application_identity_key": "web:nz.seek.com",
    "canonical_origin": "https://nz.seek.com",
    "application_identity": {
        "contract_version": "application_identity_v1",
        "identity_schema_version": 1,
        "kind": "web",
        "identity_key": "web:nz.seek.com",
        "identity_status": "resolved",
        "name": "nz.seek.com",
        "display_name": "nz.seek.com",
        "canonical_domain": "nz.seek.com",
        "canonical_origin": "https://nz.seek.com",
        "executable_identity": None,
        "product_identity": None,
        "source_evidence": {
            "url_or_domain_provided": True,
            "browser_process_detected": False,
        },
        "artifact_is_authorization": False,
    },
    "human_approved_node_ids": ["job_detail"],
    "reviewed_state_source_node_id": "job_detail",
    "stop_boundary_source_node_id": "apply_entry",
    "semantic_action": "open_apply_flow",
    "requires_user_confirmation": True,
    "artifact_is_authorization": False,
    "execute_binding_enabled": False,
    "fixture_is_live_proof": False,
}


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    assert isinstance(value, dict)
    return value


def _validate_release_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    assert manifest == EXPECTED_RELEASE_MANIFEST
    return manifest


def _load_release_fixture() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    manifest = _validate_release_manifest(_json(FIXTURE_ROOT / "manifest.json"))
    workflow = _json(FIXTURE_ROOT / "reviewed_workflow.json")
    asset = validate_reviewed_workflow_asset(
        _json(FIXTURE_ROOT / "reviewed_workflow_asset_v2.json")
    )
    return manifest, workflow, asset


def test_exact_portfolio_release_fixture_is_content_addressed_and_non_authorizing() -> None:
    manifest_path = FIXTURE_ROOT / "manifest.json"
    workflow_path = FIXTURE_ROOT / "reviewed_workflow.json"
    asset_path = FIXTURE_ROOT / "reviewed_workflow_asset_v2.json"
    source_path = FIXTURE_ROOT / "source_screenshot.png"
    overlay_path = FIXTURE_ROOT / "human_review_overlay.png"

    manifest, workflow, asset = _load_release_fixture()
    assert sha256(workflow_path.read_bytes()).hexdigest() == SOURCE_WORKFLOW_SHA256
    assert sha256(asset_path.read_bytes()).hexdigest() == ASSET_SHA256
    assert content_sha256(asset) == ASSET_SHA256
    assert sha256(source_path.read_bytes()).hexdigest() == SOURCE_SCREENSHOT_SHA256
    assert sha256(overlay_path.read_bytes()).hexdigest() == HUMAN_REVIEW_OVERLAY_SHA256
    assert manifest["asset_id"] == asset["asset_id"] == ASSET_ID
    assert asset["source_review_lineage"]["source_workflow_id"] == SOURCE_WORKFLOW_ID
    assert (
        asset["source_review_lineage"]["source_workflow_sha256"]
        == SOURCE_WORKFLOW_SHA256
    )
    assert asset["safety"] == {
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "final_submit_forbidden": True,
        "fresh_grounding_required": True,
        "historical_coordinates_used": False,
        "post_action_verification_required": True,
        "real_action_requires_gate": True,
    }
    assert workflow["workflow"]["workflow_id"] == SOURCE_WORKFLOW_ID

    states = {item["source_node_id"]: item for item in asset["states"]}
    assert states["job_detail"]["availability"] == "reviewed"
    assert states["apply_entry"]["availability"] == "stop_boundary"
    assert states["apply_entry"]["allowed_transition_ids"] == []
    assert len(asset["transitions"]) == 1
    transition = asset["transitions"][0]
    assert transition["semantic_action"] == "open_apply_flow"
    assert transition["source_state_id"] == states["job_detail"]["state_id"]
    assert transition["target_state_id"] == states["apply_entry"]["state_id"]
    assert transition["risk_policy"]["requires_user_confirmation"] is True
    assert transition["risk_policy"]["automatic_execution_allowed"] is False
    assert asset["source_review_lineage"]["human_approved_node_ids"] == [
        "job_detail"
    ]
    assert ASSET_ID != SOURCE_WORKFLOW_ID


def test_release_manifest_rejects_frozen_contract_drift() -> None:
    manifest = deepcopy(_json(FIXTURE_ROOT / "manifest.json"))
    manifest["application_identity"]["canonical_origin"] = "https://example.invalid"

    with pytest.raises(AssertionError):
        _validate_release_manifest(manifest)
