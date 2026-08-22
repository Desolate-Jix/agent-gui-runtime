from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from tests.test_reviewed_workflow_compiler_v2 import _base_review, _persist_reviewed_workflow


@pytest.fixture(autouse=True)
def _restore_panel_root(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.panel as panel_api

    monkeypatch.setattr(panel_api, "ROOT_DIR", panel_api.ROOT_DIR)


def _request_source(tmp_path: Path) -> tuple[str, str, str]:
    source, digest = _persist_reviewed_workflow(tmp_path)
    import app.api.panel as panel_api

    panel_api.ROOT_DIR = tmp_path
    return "web:nz.seek.com", "seek_home_to_apply", digest


def _workflow_source(tmp_path: Path, workflow_id: str) -> Path:
    registry_path = tmp_path / "artifacts" / "interface-workflow-reviews" / "registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    return tmp_path / registry["workflows"][workflow_id]["path"]


def test_compile_endpoint_compiles_server_resolved_registry_source(tmp_path: Path) -> None:
    import app.api.panel as panel_api

    application_identity_key, workflow_id, digest = _request_source(tmp_path)
    response = panel_api.compile_reviewed_workflow_asset_endpoint(
        panel_api.PanelCompileReviewedWorkflowAssetRequest(
            application_identity_key=application_identity_key,
            workflow_id=workflow_id,
            expected_source_workflow_sha256=digest,
        )
    )

    assert response.success is True
    assert response.data["result"]["status"] == "compiled"
    assert response.data["result"]["asset"]["asset_id"]
    assert not (tmp_path / "runtime_state" / "reviewed-workflow-assets-v2").exists()


def test_compile_endpoint_blocks_stale_sha_without_writing_cas(tmp_path: Path) -> None:
    import app.api.panel as panel_api

    application_identity_key, workflow_id, _ = _request_source(tmp_path)
    response = panel_api.compile_reviewed_workflow_asset_endpoint(
        panel_api.PanelCompileReviewedWorkflowAssetRequest(
            application_identity_key=application_identity_key,
            workflow_id=workflow_id,
            expected_source_workflow_sha256="0" * 64,
        )
    )

    assert response.success is False
    assert response.error.code == "reviewed_workflow_compile_blocked"
    assert not (tmp_path / "runtime_state" / "reviewed-workflow-assets-v2").exists()


def test_compile_endpoint_blocks_unreviewed_or_dangerous_workflow(tmp_path: Path) -> None:
    import app.api.panel as panel_api

    application_identity_key, workflow_id, digest = _request_source(tmp_path)
    source = _workflow_source(tmp_path, workflow_id)
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["nodes"][0]["reviewed_by_human"] = False
    payload["nodes"][0]["review_status"] = "needs_human_review"
    source.write_text(json.dumps(payload), encoding="utf-8")
    changed_digest = sha256(source.read_bytes()).hexdigest()
    registry_path = tmp_path / "artifacts" / "interface-workflow-reviews" / "registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["workflows"][workflow_id]["source_asset_sha256"] = changed_digest
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    response = panel_api.compile_reviewed_workflow_asset_endpoint(
        panel_api.PanelCompileReviewedWorkflowAssetRequest(
            application_identity_key=application_identity_key,
            workflow_id=workflow_id,
            expected_source_workflow_sha256=changed_digest,
        )
    )

    assert digest != changed_digest
    assert response.success is False
    assert response.error.code == "reviewed_workflow_compile_blocked"
    assert not (tmp_path / "runtime_state" / "reviewed-workflow-assets-v2").exists()


def test_publish_endpoint_recompiles_publishes_and_rejects_cas_conflict(tmp_path: Path) -> None:
    import app.api.panel as panel_api

    application_identity_key, workflow_id, digest = _request_source(tmp_path)
    request = panel_api.PanelPublishReviewedWorkflowAssetRequest(
        application_identity_key=application_identity_key,
        workflow_id=workflow_id,
        expected_source_workflow_sha256=digest,
        expected_registry_revision=0,
    )
    published = panel_api.publish_reviewed_workflow_asset_endpoint(request)
    assert published.success is True
    assert published.data["publish_result"]["registry_revision"] == 1

    second_review = _base_review()
    second_review["workflow"]["workflow_id"] = "seek_second_workflow"
    _, second_digest = _persist_reviewed_workflow(tmp_path, second_review)
    conflict = panel_api.publish_reviewed_workflow_asset_endpoint(
        panel_api.PanelPublishReviewedWorkflowAssetRequest(
            application_identity_key=application_identity_key,
            workflow_id="seek_second_workflow",
            expected_source_workflow_sha256=second_digest,
            expected_registry_revision=0,
        )
    )
    assert conflict.success is False
    assert conflict.error.code == "reviewed_workflow_publish_failed"
    registry = panel_api.ReviewedWorkflowAssetStore(project_root=tmp_path).registry()
    assert registry["registry_revision"] == 1
    assert set(registry["active_by_asset"]) == {published.data["publish_result"]["asset_id"]}


def test_publish_request_rejects_client_supplied_asset(tmp_path: Path) -> None:
    import app.api.panel as panel_api

    application_identity_key, workflow_id, digest = _request_source(tmp_path)
    with pytest.raises(ValidationError):
        panel_api.PanelPublishReviewedWorkflowAssetRequest.model_validate(
            {
                "application_identity_key": application_identity_key,
                "workflow_id": workflow_id,
                "expected_source_workflow_sha256": digest,
                "expected_registry_revision": 0,
                "asset": {"asset_id": "attacker-controlled"},
            }
        )


def test_preview_is_read_only_and_never_calls_capture_or_action_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.panel as panel_api

    application_identity_key, workflow_id, digest = _request_source(tmp_path)
    published = panel_api.publish_reviewed_workflow_asset_endpoint(
        panel_api.PanelPublishReviewedWorkflowAssetRequest(
            application_identity_key=application_identity_key,
            workflow_id=workflow_id,
            expected_source_workflow_sha256=digest,
            expected_registry_revision=0,
        )
    )
    asset = published.data["compile_result"]["asset"]
    state = next(state for state in asset["states"] if state["availability"] == "reviewed")
    current_observation = {
        "contract_version": "reviewed_workflow_current_observation_v1",
        "asset_id": asset["asset_id"],
        "expected_asset_content_sha256": published.data["publish_result"]["content_sha256"],
        "capture_id": "capture-preview",
        "screenshot_sha256": "b" * 64,
        "viewport_size": {"width": 1440, "height": 900},
        "origin": asset["application"]["canonical_origin"],
        "observed_anchor_evidence": [
            {"anchor_id": anchor["anchor_id"], "matched": True, "evidence_ref": f"preview:{anchor['anchor_id']}", "confidence": 0.95}
            for anchor in state["identity_anchors"]
        ],
    }

    response = panel_api.preview_reviewed_workflow_replay_endpoint(
        panel_api.PanelPreviewReviewedWorkflowReplayRequest(
            asset_id=asset["asset_id"],
            expected_content_sha256=published.data["publish_result"]["content_sha256"],
            current_observation=current_observation,
        )
    )

    assert response.success is True
    assert response.data["mode"] == "read_only_preview"
    assert response.data["would_call_action_api"] is False
    assert response.data["execution_authorized"] is False
    assert response.data["state_resolution"]["status"] == "resolved"


def test_preview_blocks_content_hash_mismatch(tmp_path: Path) -> None:
    import app.api.panel as panel_api

    application_identity_key, workflow_id, digest = _request_source(tmp_path)
    published = panel_api.publish_reviewed_workflow_asset_endpoint(
        panel_api.PanelPublishReviewedWorkflowAssetRequest(
            application_identity_key=application_identity_key,
            workflow_id=workflow_id,
            expected_source_workflow_sha256=digest,
            expected_registry_revision=0,
        )
    )
    response = panel_api.preview_reviewed_workflow_replay_endpoint(
        panel_api.PanelPreviewReviewedWorkflowReplayRequest(
            asset_id=published.data["publish_result"]["asset_id"],
            expected_content_sha256="0" * 64,
            current_observation={},
        )
    )
    assert response.success is False
    assert response.error.code == "reviewed_workflow_preview_hash_mismatch"


def test_actual_http_preview_is_read_only_and_unresolved_is_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.api.action as action_api
    import app.api.panel as panel_api
    from app.core.input_controller import input_controller
    from app.core.screenshot import screenshot_service
    from app.main import app

    application_identity_key, workflow_id, digest = _request_source(tmp_path)
    published = panel_api.publish_reviewed_workflow_asset_endpoint(
        panel_api.PanelPublishReviewedWorkflowAssetRequest(
            application_identity_key=application_identity_key,
            workflow_id=workflow_id,
            expected_source_workflow_sha256=digest,
            expected_registry_revision=0,
        )
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("preview must not capture or execute")

    monkeypatch.setattr(screenshot_service, "capture_window", forbidden)
    monkeypatch.setattr(action_api, "execute_recognition_plan", forbidden)
    monkeypatch.setattr(input_controller, "click_point", forbidden)
    monkeypatch.setattr(input_controller, "scroll_window", forbidden)
    with TestClient(app) as client:
        response = client.post(
            "/panel/preview_reviewed_workflow_replay",
            json={
                "asset_id": published.data["publish_result"]["asset_id"],
                "expected_content_sha256": published.data["publish_result"]["content_sha256"],
                "current_observation": {},
            },
        )
    body = response.json()
    assert response.status_code == 200
    assert body["success"] is False
    assert body["error"]["code"] == "reviewed_workflow_preview_observation_required"
    assert body["data"]["mode"] == "read_only_preview"
    assert body["data"]["would_call_action_api"] is False


def test_compile_rejects_malformed_registry_shape_without_path_leak(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.api.panel as panel_api

    application_identity_key, workflow_id, digest = _request_source(tmp_path)
    monkeypatch.setattr(
        panel_api,
        "load_interface_workflow_library_registry",
        lambda **kwargs: {"applications": [], "workflows": {}, "registry_revision": 0},
    )
    response = panel_api.compile_reviewed_workflow_asset_endpoint(
        panel_api.PanelCompileReviewedWorkflowAssetRequest(
            application_identity_key=application_identity_key,
            workflow_id=workflow_id,
            expected_source_workflow_sha256=digest,
        )
    )
    assert response.success is False
    assert response.error.code == "reviewed_workflow_compile_failed"
    assert str(tmp_path) not in response.error.details


def test_compile_reports_current_cas_revision_without_mutating_existing_cas(
    tmp_path: Path,
) -> None:
    import app.api.panel as panel_api

    application_identity_key, workflow_id, digest = _request_source(tmp_path)
    published = panel_api.publish_reviewed_workflow_asset_endpoint(
        panel_api.PanelPublishReviewedWorkflowAssetRequest(
            application_identity_key=application_identity_key,
            workflow_id=workflow_id,
            expected_source_workflow_sha256=digest,
            expected_registry_revision=0,
        )
    )
    store = panel_api.ReviewedWorkflowAssetStore(project_root=tmp_path)
    before = store.registry()
    compiled = panel_api.compile_reviewed_workflow_asset_endpoint(
        panel_api.PanelCompileReviewedWorkflowAssetRequest(
            application_identity_key=application_identity_key,
            workflow_id=workflow_id,
            expected_source_workflow_sha256=digest,
        )
    )
    assert published.success is True
    assert compiled.success is True
    assert compiled.data["registry_revision"] == before["registry_revision"] == 1
    assert store.registry() == before


def test_publish_blocks_injected_source_mutation_after_compile_without_cas_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.api.panel as panel_api

    application_identity_key, workflow_id, digest = _request_source(tmp_path)
    source = _workflow_source(tmp_path, workflow_id)
    real_compile = panel_api._compile_reviewed_workflow_request

    def compile_then_mutate(request):
        result = real_compile(request)
        source.write_bytes(source.read_bytes() + b"\n")
        return result

    monkeypatch.setattr(panel_api, "_compile_reviewed_workflow_request", compile_then_mutate)
    response = panel_api.publish_reviewed_workflow_asset_endpoint(
        panel_api.PanelPublishReviewedWorkflowAssetRequest(
            application_identity_key=application_identity_key,
            workflow_id=workflow_id,
            expected_source_workflow_sha256=digest,
            expected_registry_revision=0,
        )
    )
    assert response.success is False
    assert response.error.code == "reviewed_workflow_source_changed"
    assert not (tmp_path / "runtime_state" / "reviewed-workflow-assets-v2").exists()


def test_publish_rejects_compiled_source_workflow_identity_substitution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.panel as panel_api

    application_identity_key, workflow_id, digest = _request_source(tmp_path)
    real_compile = panel_api._compile_reviewed_workflow_request

    def compile_then_substitute_identity(request):
        result = real_compile(request)
        result["asset"]["source_review_lineage"]["source_workflow_id"] = (
            "different.reviewed.workflow"
        )
        return result

    monkeypatch.setattr(
        panel_api,
        "_compile_reviewed_workflow_request",
        compile_then_substitute_identity,
    )
    response = panel_api.publish_reviewed_workflow_asset_endpoint(
        panel_api.PanelPublishReviewedWorkflowAssetRequest(
            application_identity_key=application_identity_key,
            workflow_id=workflow_id,
            expected_source_workflow_sha256=digest,
            expected_registry_revision=0,
        )
    )

    assert response.success is False
    assert response.error.code == "reviewed_workflow_source_changed"
    assert not (tmp_path / "runtime_state" / "reviewed-workflow-assets-v2").exists()


def test_compile_hides_injected_oserror_absolute_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.api.panel as panel_api

    application_identity_key, workflow_id, digest = _request_source(tmp_path)
    monkeypatch.setattr(
        panel_api,
        "_compile_reviewed_workflow_request",
        lambda request: (_ for _ in ()).throw(OSError(r"C:\private\reviewed_workflow.json")),
    )
    response = panel_api.compile_reviewed_workflow_asset_endpoint(
        panel_api.PanelCompileReviewedWorkflowAssetRequest(
            application_identity_key=application_identity_key,
            workflow_id=workflow_id,
            expected_source_workflow_sha256=digest,
        )
    )
    assert response.success is False
    assert response.error.code == "reviewed_workflow_compile_failed"
    assert "C:\\private" not in response.error.details


def test_actual_loader_rejects_malformed_registry_before_values_iteration(
    tmp_path: Path,
) -> None:
    import app.api.panel as panel_api

    application_identity_key, workflow_id, digest = _request_source(tmp_path)
    registry_path = tmp_path / "artifacts" / "interface-workflow-reviews" / "registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["workflows"] = []
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    response = panel_api.compile_reviewed_workflow_asset_endpoint(
        panel_api.PanelCompileReviewedWorkflowAssetRequest(
            application_identity_key=application_identity_key,
            workflow_id=workflow_id,
            expected_source_workflow_sha256=digest,
        )
    )
    assert response.success is False
    assert response.error.code == "reviewed_workflow_compile_failed"


def test_preview_omitted_observation_returns_read_only_envelope(tmp_path: Path) -> None:
    import app.api.panel as panel_api
    from app.main import app

    application_identity_key, workflow_id, digest = _request_source(tmp_path)
    published = panel_api.publish_reviewed_workflow_asset_endpoint(
        panel_api.PanelPublishReviewedWorkflowAssetRequest(
            application_identity_key=application_identity_key,
            workflow_id=workflow_id,
            expected_source_workflow_sha256=digest,
            expected_registry_revision=0,
        )
    )
    with TestClient(app) as client:
        response = client.post("/panel/preview_reviewed_workflow_replay", json={
            "asset_id": published.data["publish_result"]["asset_id"],
            "expected_content_sha256": published.data["publish_result"]["content_sha256"],
        })
    assert response.status_code == 200
    assert response.json()["error"]["code"] == "reviewed_workflow_preview_observation_required"


def test_compile_sanitizes_blocked_reason_path_for_compile_and_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.api.panel as panel_api

    application_identity_key, workflow_id, digest = _request_source(tmp_path)
    blocked = {"contract_version": "reviewed_workflow_compile_result_v2", "status": "blocked", "asset": None, "blocked_reasons": [{"code": "source_workflow_read_failed", "message": r"C:\private\secret.json"}]}
    monkeypatch.setattr(panel_api, "_compile_reviewed_workflow_request", lambda request: blocked)
    request = panel_api.PanelCompileReviewedWorkflowAssetRequest(application_identity_key=application_identity_key, workflow_id=workflow_id, expected_source_workflow_sha256=digest)
    compile_response = panel_api.compile_reviewed_workflow_asset_endpoint(request)
    publish_response = panel_api.publish_reviewed_workflow_asset_endpoint(panel_api.PanelPublishReviewedWorkflowAssetRequest(**request.model_dump(), expected_registry_revision=0))
    assert "C:\\private" not in str(compile_response.data)
    assert "C:\\private" not in str(publish_response.data)


def test_compile_hides_corrupt_cas_registry_path(tmp_path: Path) -> None:
    import app.api.panel as panel_api

    application_identity_key, workflow_id, digest = _request_source(tmp_path)
    cas_registry = tmp_path / "runtime_state" / "reviewed-workflow-assets-v2" / "registry.json"
    cas_registry.parent.mkdir(parents=True)
    cas_registry.write_text(r'{"path":"C:\\private\\cas.json"}', encoding="utf-8")
    response = panel_api.compile_reviewed_workflow_asset_endpoint(panel_api.PanelCompileReviewedWorkflowAssetRequest(application_identity_key=application_identity_key, workflow_id=workflow_id, expected_source_workflow_sha256=digest))
    assert response.success is False
    assert "C:\\private" not in response.error.details
