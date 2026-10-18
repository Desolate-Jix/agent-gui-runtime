from __future__ import annotations

from copy import deepcopy
import gc
import hashlib
import json
from pathlib import Path

import pytest

from app.agent.desktop_backend import DeterministicFakeBackend
from app.agent.agent_observation_adapter import _trusted_reviewed_blockers
from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
from app.agent.runtime_receipt_store import RuntimeReceiptStore
from app.api.agent_runtime import AgentRuntimeCallsiteError, LocalAgentRuntimeCallsite
from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore
from app.agent.reviewed_workflow_compiler import compile_reviewed_workflow_asset_v2
from app.learn.interface_workflow_review import build_interface_node_review_revision
from tests.test_agent_runtime_actual_adapter_portfolio_v1 import _StableWindowManager
from tests.test_live_controller_portfolio_confirmation_v1 import _compiled_portfolio_asset
from tests.test_live_runtime_composition_w3b import (
    _OriginReader,
    _SequencedRecognitionRunner,
    _SequencedScreenshotService,
    _UIAProvider,
    _state_payloads,
)


def _sparse_compiled_callsite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    asset_override: dict | None = None,
) -> tuple[dict, LocalAgentRuntimeCallsite, DeterministicFakeBackend]:
    import app.agent.live_runtime_composition as composition
    import app.core.screenshot as screenshot_module
    import app.core.window_manager as window_module
    import app.operation.screen_reading.uia_provider as uia_module

    asset = asset_override or _compiled_portfolio_asset(tmp_path)
    states = {item["source_node_id"]: item for item in asset["states"]}
    detail_state = states["job_detail"]
    asset_store = ReviewedWorkflowAssetStore(project_root=tmp_path)
    assert asset_store.publish(asset, expected_registry_revision=0)["status"] == "published"

    manager = _StableWindowManager()
    screenshot = _SequencedScreenshotService(tmp_path, colors=[(1, 20, 30)])
    origin = _OriginReader(origin="https://nz.seek.com")
    uia = _UIAProvider(handle=4242, process_id=9001)
    runner = _SequencedRecognitionRunner(
        [_state_payloads(asset, detail_state["state_id"])]
    )
    backend = DeterministicFakeBackend()
    monkeypatch.setattr(screenshot_module, "screenshot_service", screenshot)
    monkeypatch.setattr(window_module, "window_manager", manager)
    monkeypatch.setattr(uia_module, "uia_provider", uia)
    monkeypatch.setattr(composition, "WindowsUIAOriginReader", lambda **_kwargs: origin)
    monkeypatch.setattr(composition, "_run_existing_read_only_recognition", runner)
    monkeypatch.setattr(composition, "ExistingWindowsBackendAdapter", lambda: backend)

    receipt_store = RuntimeReceiptStore(project_root=tmp_path)
    callsite = LocalAgentRuntimeCallsite(
        project_root=tmp_path,
        asset_store=asset_store,
        window_manager=manager,
        claim_store=RuntimeIntentClaimStore(
            project_root=tmp_path,
            receipt_store=receipt_store,
        ),
    )
    return asset, callsite, backend


@pytest.fixture
def sparse_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    active = _sparse_compiled_callsite(tmp_path, monkeypatch)
    try:
        yield active
    finally:
        active[1]._clear_active()
        del active
        gc.collect()


def test_compiled_v2_projection_runs_sparse_human_reviewed_entry(sparse_runtime) -> None:
    _, callsite, backend = sparse_runtime

    observation = callsite.start_session()

    assert observation.state.status == "matched"
    assert [item.semantic_action for item in observation.available_actions] == [
        "open_apply_flow",
        "safe_stop",
    ]
    assert backend.dispatch_count == 0


def test_compiled_v2_projection_rejects_asset_not_equal_to_current_recompile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = _compiled_portfolio_asset(tmp_path)
    forged = deepcopy(original)
    forged["transitions"][0]["display_name"] = "forged-operation"
    _, callsite, backend = _sparse_compiled_callsite(
        tmp_path,
        monkeypatch,
        asset_override=forged,
    )

    with pytest.raises(AgentRuntimeCallsiteError):
        callsite.start_session()

    assert backend.attempt_count == backend.dispatch_count == 0


def test_compiled_v2_projection_rejects_changed_source_before_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asset, callsite, backend = _sparse_compiled_callsite(tmp_path, monkeypatch)
    source = tmp_path / asset["source_review_lineage"]["source_workflow_path"]
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["workflow"]["goal"] = "changed after compilation"
    source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(AgentRuntimeCallsiteError):
        callsite.start_session()

    assert backend.attempt_count == backend.dispatch_count == 0


def test_compiled_v2_projection_rejects_registry_lineage_change_before_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asset, callsite, backend = _sparse_compiled_callsite(tmp_path, monkeypatch)
    registry_path = tmp_path / "artifacts" / "interface-workflow-reviews" / "registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    workflow_id = asset["source_review_lineage"]["source_workflow_id"]
    registry["workflows"][workflow_id]["source_asset_sha256"] = "0" * 64
    registry_path.write_text(json.dumps(registry, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(AgentRuntimeCallsiteError):
        callsite.start_session()

    assert backend.attempt_count == backend.dispatch_count == 0


def test_null_reviewed_blockers_remain_malformed(
) -> None:
    context = {
        "workflows": [
            {
                "contract_version": "single_application_workflow_review_v1",
                "workflow": {"workflow_id": "workflow"},
                "nodes": [{"node_id": "detail", "blockers": None}],
            }
        ]
    }

    with pytest.raises(ValueError, match="reviewed blockers must be an array"):
        _trusted_reviewed_blockers(
            context,
            workflow_id="workflow",
            source_node_id="detail",
            projected=[],
        )


def test_compiler_rejects_current_source_with_revoked_granular_control_approval(
    tmp_path: Path,
) -> None:
    asset = _compiled_portfolio_asset(tmp_path)
    source = tmp_path / asset["source_review_lineage"]["source_workflow_path"]
    review = json.loads(source.read_text(encoding="utf-8"))
    review["nodes"][0]["controls"][0]["reviewed_by_human"] = False
    source_bytes = json.dumps(review, ensure_ascii=False).encode("utf-8")
    source.write_bytes(source_bytes)

    registry_path = tmp_path / "artifacts" / "interface-workflow-reviews" / "registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    workflow_id = asset["source_review_lineage"]["source_workflow_id"]
    registry_record = registry["workflows"][workflow_id]
    registry_record["source_asset_sha256"] = hashlib.sha256(source_bytes).hexdigest()
    registry_record["reviewed_node_revision_hashes"]["job_detail"] = (
        hashlib.sha256(
            json.dumps(
                build_interface_node_review_revision(review, node_id="job_detail"),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
    )
    registry_path.write_text(json.dumps(registry, ensure_ascii=False), encoding="utf-8")

    compiled = compile_reviewed_workflow_asset_v2(
        project_root=tmp_path,
        source_workflow_path=source.relative_to(tmp_path),
        expected_source_workflow_sha256=hashlib.sha256(source_bytes).hexdigest(),
    )

    assert compiled["status"] == "blocked"
    assert {
        item["code"] for item in compiled["blocked_reasons"]
    } >= {"edge_target_control_approval_invalid"}
