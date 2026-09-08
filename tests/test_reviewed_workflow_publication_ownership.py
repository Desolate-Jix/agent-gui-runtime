"""编译与发布必须在无旧网页环境运行，并与旧保存路径共用锁。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Event


ROOT = Path(__file__).resolve().parents[1]


def test_headless_runtime_does_not_expose_legacy_publication_routes():
    from app.api.application import create_runtime_app

    application = create_runtime_app()
    assert not any(getattr(route, "path", "").startswith("/panel/") for route in application.routes)


def test_publication_is_independent_of_legacy_panel_and_cwd(tmp_path):
    script = r'''
import builtins
import json
from pathlib import Path
import sys

original_import = builtins.__import__
def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    candidates = [name, *(name + "." + item for item in (fromlist or ()))]
    for candidate in candidates:
        if candidate in {"app.main", "app.api.panel", "app.web_panel"} or candidate.startswith("app.web_panel."):
            raise AssertionError("legacy import: " + candidate)
    return original_import(name, globals, locals, fromlist, level)
builtins.__import__ = guarded_import
from app.api import reviewed_workflows as api
from tests.test_reviewed_workflow_compiler_v2 import _persist_reviewed_workflow
root = Path.cwd()
_, digest = _persist_reviewed_workflow(root)
request = api.PanelCompileReviewedWorkflowAssetRequest(
    application_identity_key="web:nz.seek.com", workflow_id="seek_home_to_apply",
    expected_source_workflow_sha256=digest,
)
compiled = api.compile_reviewed_workflow_asset_endpoint(request, project_root=root)
assert compiled.success is True, compiled
assert compiled.data["registry_revision"] == 0
assert not (root / "runtime_state" / "reviewed-workflow-assets-v2").exists()
publish_request = api.PanelPublishReviewedWorkflowAssetRequest(
    **request.model_dump(), expected_registry_revision=0,
)
published = api.publish_reviewed_workflow_asset_endpoint(publish_request, project_root=root)
assert published.success is True, published
assert published.data["publish_result"]["registry_revision"] == 1
assert published.data["artifact_is_authorization"] is False
assert published.data["execute_binding_enabled"] is False
from scripts.prove_portfolio_hybrid_v1_1_persistence import _worker_compile
worker_root = root / "independent-worker"
source, worker_digest = _persist_reviewed_workflow(worker_root)
worker_result = _worker_compile(
    root=worker_root, source_relative=source.relative_to(worker_root).as_posix(),
    expected_sha=worker_digest, application_identity_key="web:nz.seek.com",
    workflow_id="seek_home_to_apply", publish=True,
)
assert worker_result["registry_revision_before"] == 0
assert worker_result["registry_revision_after"] == 1
assert worker_result["registry_publish_event_count"] == 1
assert worker_result["registry_cas_verified"] is True
assert not {"app.main", "app.api.panel", "app.web_panel"} & sys.modules.keys()
print(json.dumps({"compiled": True, "published_revision": 1, "legacy_loaded": False, "worker_cas_verified": True}))
'''
    environment = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
                       AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH=":memory:",
                       HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    result = subprocess.run([sys.executable, "-c", script], cwd=tmp_path, env=environment,
                            capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stderr + result.stdout
    assert json.loads(result.stdout.splitlines()[-1]) == {
        "compiled": True, "published_revision": 1, "legacy_loaded": False, "worker_cas_verified": True,
    }


def test_publication_waits_for_the_same_lock_used_by_panel_save_delete(tmp_path, monkeypatch):
    from app.api import panel, reviewed_workflows as api
    from app.learn.interface_workflow_lock import interface_workflow_lock
    from tests.test_reviewed_workflow_compiler_v2 import _persist_reviewed_workflow

    assert panel._interface_workflow_lock is interface_workflow_lock
    _, digest = _persist_reviewed_workflow(tmp_path)
    request = api.PanelPublishReviewedWorkflowAssetRequest(
        application_identity_key="web:nz.seek.com", workflow_id="seek_home_to_apply",
        expected_source_workflow_sha256=digest, expected_registry_revision=0,
    )
    compile_entered = Event()
    started = Event()
    original_compile = api._compile_reviewed_workflow_request

    def observe_compile(*args, **kwargs):
        compile_entered.set()
        return original_compile(*args, **kwargs)

    monkeypatch.setattr(api, "_compile_reviewed_workflow_request", observe_compile)

    def publish():
        started.set()
        return api.publish_reviewed_workflow_asset_endpoint(request, project_root=tmp_path)

    with ThreadPoolExecutor(max_workers=1) as executor:
        with panel._interface_workflow_lock("seek_home_to_apply"):
            pending = executor.submit(publish)
            assert started.wait(5)
            assert not compile_entered.wait(0.2)
            assert not (tmp_path / "runtime_state" / "reviewed-workflow-assets-v2").exists()
        response = pending.result(timeout=10)
    assert compile_entered.is_set()
    assert response.success is True
    assert response.data["publish_result"]["registry_revision"] == 1
