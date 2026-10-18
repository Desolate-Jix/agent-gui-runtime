"""只读预览独立归属、无执行权限与无持久化副作用。"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from pydantic import ValidationError

from tests.test_reviewed_workflow_compiler_v2 import _persist_reviewed_workflow


ROOT = Path(__file__).resolve().parents[1]


def _snapshot(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def _published(root):
    from app.api import reviewed_workflows as api

    _, digest = _persist_reviewed_workflow(root)
    result = api.publish_reviewed_workflow_asset_endpoint(
        api.PanelPublishReviewedWorkflowAssetRequest(
            application_identity_key="web:nz.seek.com", workflow_id="seek_home_to_apply",
            expected_source_workflow_sha256=digest, expected_registry_revision=0,
        ), project_root=root,
    )
    assert result.success is True
    asset = result.data["compile_result"]["asset"]
    state = next(s for s in asset["states"] if s["availability"] == "reviewed")
    digest = result.data["publish_result"]["content_sha256"]
    observation = {
        "contract_version": "reviewed_workflow_current_observation_v1",
        "asset_id": asset["asset_id"], "expected_asset_content_sha256": digest,
        "capture_id": "synthetic-preview", "screenshot_sha256": "b" * 64,
        "viewport_size": {"width": 1440, "height": 900},
        "origin": asset["application"]["canonical_origin"],
        "observed_anchor_evidence": [
            {"anchor_id": a["anchor_id"], "matched": True,
             "evidence_ref": "synthetic:" + a["anchor_id"], "confidence": 0.95}
            for a in state["identity_anchors"]
        ],
    }
    return {"asset_id": asset["asset_id"], "expected_content_sha256": digest,
            "current_observation": observation}


@pytest.mark.parametrize("case,expected_error", [
    ("resolved", None), ("hash_mismatch", "reviewed_workflow_preview_hash_mismatch"),
    ("empty", "reviewed_workflow_preview_observation_required"),
    ("omitted", "reviewed_workflow_preview_observation_required"),
    ("unresolved", "reviewed_workflow_preview_unresolved"),
    ("missing_asset", "reviewed_workflow_preview_failed"),
    ("corrupt_registry", "reviewed_workflow_preview_failed"),
])
def test_formal_preview_is_read_only_for_success_and_failures(tmp_path, monkeypatch, case, expected_error):
    from app.api import reviewed_workflows as api
    from app.api import action
    from app.core.input_controller import input_controller
    from app.core.screenshot import screenshot_service

    request_type = api.PanelPreviewReviewedWorkflowReplayRequest
    request = _published(tmp_path)
    if case == "hash_mismatch":
        request["expected_content_sha256"] = "0" * 64
    elif case == "empty":
        request["current_observation"] = {}
    elif case == "omitted":
        request.pop("current_observation")
    elif case == "unresolved":
        request["current_observation"]["observed_anchor_evidence"] = []
    elif case == "missing_asset":
        request["asset_id"] = "absent"
    elif case == "corrupt_registry":
        (tmp_path / "runtime_state/reviewed-workflow-assets-v2/registry.json").write_text("{", encoding="utf-8")
    before = _snapshot(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("read-only preview must not capture, execute or publish")

    monkeypatch.setattr(screenshot_service, "capture_window", forbidden)
    monkeypatch.setattr(action, "execute_recognition_plan", forbidden)
    monkeypatch.setattr(input_controller, "click_point", forbidden)
    monkeypatch.setattr(input_controller, "scroll_window", forbidden)
    monkeypatch.setattr(api.ReviewedWorkflowAssetStore, "publish", forbidden)
    result = api.preview_reviewed_workflow_replay_endpoint(request_type(**request), project_root=tmp_path)
    assert result.success is (expected_error is None)
    assert (result.error.code if result.error else None) == expected_error
    assert result.data["mode"] == "read_only_preview"
    for flag in ("would_call_action_api", "execution_authorized", "artifact_is_authorization", "execute_binding_enabled"):
        assert result.data[flag] is False
    assert str(tmp_path) not in (result.error.details if result.error else "")
    assert _snapshot(tmp_path) == before


def test_preview_rejects_client_root_and_asset_override():
    from app.api.reviewed_workflows import PanelPreviewReviewedWorkflowReplayRequest

    for key in ("project_root", "asset"):
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            PanelPreviewReviewedWorkflowReplayRequest.model_validate({
                "asset_id": "example", "expected_content_sha256": "a" * 64, key: "untrusted",
            })


def test_preview_import_and_resolution_work_without_legacy_panel_in_foreign_cwd(tmp_path):
    script = r'''
import builtins
import json
from pathlib import Path
import sys
original_import = builtins.__import__
def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    for candidate in [name, *(name + "." + item for item in (fromlist or ()))]:
        if candidate in {"app.main", "app.api.panel", "app.web_panel"} or candidate.startswith("app.web_panel."):
            raise AssertionError("legacy import: " + candidate)
    return original_import(name, globals, locals, fromlist, level)
builtins.__import__ = guarded_import
from app.api.reviewed_workflows import PanelPreviewReviewedWorkflowReplayRequest, preview_reviewed_workflow_replay_endpoint
from tests.test_reviewed_workflow_preview_ownership import _published, _snapshot
root = Path.cwd()
request = PanelPreviewReviewedWorkflowReplayRequest(**_published(root))
before = _snapshot(root)
result = preview_reviewed_workflow_replay_endpoint(request, project_root=root)
assert result.success is True
assert result.data["state_resolution"]["status"] == "resolved"
assert result.data["execution_authorized"] is False
assert _snapshot(root) == before
assert not {"app.main", "app.api.panel", "app.web_panel"} & sys.modules.keys()
print(json.dumps({"resolved": True, "read_only": True, "legacy_loaded": False}))
'''
    environment = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
                       AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH=":memory:",
                       HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    result = subprocess.run([sys.executable, "-c", script], cwd=tmp_path, env=environment,
                            capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stderr + result.stdout
    assert json.loads(result.stdout.splitlines()[-1]) == {"resolved": True, "read_only": True, "legacy_loaded": False}
