from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_hybrid_proof_fixture_preserves_canonical_source_provenance() -> None:
    from scripts.prove_portfolio_hybrid_v1_1_persistence import _base_workflow_review

    provenance = {
        "contract_version": "interface_hybrid_review_source_provenance_v1",
        "source": {"source_path": "fixture/review.json", "sha256": "a" * 64},
        "projection_ref": {"id": "fixture-projection", "content_sha256": "b" * 64},
    }
    regions = [{"region_id": "r1", "candidate_id": "c1", "kind": "hybrid_review_candidate"}]
    workflow = _base_workflow_review(
        workflow_id="fixture",
        reviewed_candidate_path="fixture/review.json",
        reviewed_candidate_sha256="a" * 64,
        reviewed_candidate={"draft": {"hybrid_review_projection": {"candidates": [{"candidate_id": "c1"}]}}},
        maintained_home_regions=regions,
        maintained_home_provenance=provenance,
    )
    home = workflow["nodes"][0]
    assert home["hybrid_review_source_provenance"] == provenance
    assert home["regions"] == regions
    home["hybrid_review_source_provenance"]["source"]["sha256"] = "changed"
    assert provenance["source"]["sha256"] == "a" * 64


def test_hybrid_proof_pre_save_builder_uses_maintained_owners_without_legacy_modules(tmp_path: Path) -> None:
    marker = tmp_path / "legacy-blocker-active.txt"
    result_path = tmp_path / "result.json"
    (tmp_path / "sitecustomize.py").write_text(
        """import importlib.abc
import os
from pathlib import Path


class LegacyBlocker(importlib.abc.MetaPathFinder):
    prefixes = ("app.main", "app.api.panel", "app.web_panel")

    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == prefix or fullname.startswith(prefix + ".") for prefix in self.prefixes):
            raise ModuleNotFoundError("blocked legacy import: " + fullname)
        return None


import sys
sys.meta_path.insert(0, LegacyBlocker())
Path(os.environ["R8W_LEGACY_BLOCKER_MARKER"]).write_text("active", encoding="utf-8")
""",
        encoding="utf-8",
    )
    environment = dict(
        os.environ,
        PYTHONPATH=os.pathsep.join((str(tmp_path), str(ROOT))),
        PYTHONUTF8="1",
        PYTHONIOENCODING="utf-8",
        R8W_LEGACY_BLOCKER_MARKER=str(marker),
        AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH=":memory:",
        AGENT_GUI_TEST_DENY_REAL_MODEL_WRAPPER="1",
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        QT_QPA_PLATFORM="offscreen",
    )
    program = """
import json
import os
from pathlib import Path
from scripts.prove_portfolio_hybrid_v1_1_persistence import (
    _base_workflow_review,
    _managed_proof_owner_context,
    _run_public_managed_hybrid_lifecycle,
    _save_public_large_review,
    fake_bounded_vista_runner,
    fake_omni_runner,
    fake_qwen_runner,
)
from app.learn.learning_draft_review_service import load_interface_workflow_review_transaction
root = Path(os.environ["R8W_SYNTHETIC_ROOT"])
workflow_store_path = root / "runtime_state" / "learning-workflow-runs.json"
with _managed_proof_owner_context(
    root,
    workflow_store_path=workflow_store_path,
    omni_runner=fake_omni_runner,
    qwen_runner=fake_qwen_runner,
    vista_runner=fake_bounded_vista_runner,
) as (composition, store, _registry):
    lifecycle = _run_public_managed_hybrid_lifecycle(root, composition=composition, store=store)
    large = _save_public_large_review(root, workflow_store=store, lifecycle=lifecycle)
    reviewed_path = Path(large["reviewed_candidate_path"])
    reviewed_relative = reviewed_path.relative_to(root).as_posix()
    maintained = load_interface_workflow_review_transaction(
        draft_source_paths=[reviewed_relative],
        workflow_run_ids_by_source={reviewed_relative: lifecycle["workflow_run_id"]},
        discover_related_sidecars=False,
        goal="Open a detail and stop at the application entry boundary.",
        application_identity={"url": "https://managed.example.test/jobs"},
        project_root=root,
        workflow_store=store,
    )
    workflow = _base_workflow_review(
        workflow_id="portfolio_hybrid_v1_1_managed",
        reviewed_candidate_path=reviewed_relative,
        reviewed_candidate_sha256=large["reviewed_candidate_sha256"],
        reviewed_candidate=large["reviewed_candidate"],
        maintained_home_regions=maintained["nodes"][0]["regions"],
        maintained_home_provenance=maintained["nodes"][0]["hybrid_review_source_provenance"],
    )
reviewed = json.loads(reviewed_path.read_text(encoding="utf-8-sig"))
home = next(node for node in workflow["nodes"] if node["node_id"] == "home")
proposal = reviewed["draft"]["hybrid_review_projection"]
proof = home.get("evidence", {}).get("hybrid_review_evidence", {})
result = {
    "reviewed_candidate_path": reviewed_relative,
    "reviewed_candidate_sha256": large["reviewed_candidate_sha256"],
    "managed_lifecycle_task_trace": lifecycle["managed_lifecycle_task_trace"],
    "r8w_fixture_checks": {
        "source_path": proof.get("source_path") == reviewed_relative,
        "source_sha256": proof.get("source_sha256") == large["reviewed_candidate_sha256"],
        "candidate": proof.get("candidate") == proposal["candidates"][0],
        "projection": proof.get("projection") == proposal,
        "home_regions_match_maintained_builder": home.get("regions") == maintained["nodes"][0]["regions"],
        "home_provenance_matches_maintained_builder": home.get("hybrid_review_source_provenance") == maintained["nodes"][0]["hybrid_review_source_provenance"],
        "target_region_id_empty": all(
            action.get("target_region_id") == "" for action in home.get("action_candidates", [])
        ),
        "controls_unchanged": home.get("controls") == [{"control_id": "job_card", "label": "Managed result"}],
        "three_nodes_two_edges": len(workflow.get("nodes", [])) == 3 and len(workflow.get("edges", [])) == 2,
        "authorization_flags": (
            proof.get("display_only") is True
            and proof.get("artifact_is_authorization") is False
            and proof.get("execute_binding_enabled") is False
            and workflow.get("display_only") is True
            and workflow.get("artifact_is_authorization") is False
            and workflow.get("execute_binding_enabled") is False
        ),
    },
}
Path(os.environ["R8W_RESULT_PATH"]).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
"""
    environment["R8W_SYNTHETIC_ROOT"] = str(tmp_path / "synthetic-proof")
    environment["R8W_RESULT_PATH"] = str(result_path)
    completed = subprocess.run(
        [sys.executable, "-c", program],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert marker.read_text(encoding="utf-8") == "active"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["managed_lifecycle_task_trace"] == [
        "panel_learning_hybrid_omni_discovery",
        "panel_learning_hybrid_qwen_binding",
        "panel_learning_hybrid_fusion",
        "panel_learning_calibration_sequence",
        "panel_learning_hybrid_review_projection",
    ]
    assert result["r8w_fixture_checks"] == {
        "source_path": True,
        "source_sha256": True,
        "candidate": True,
        "projection": True,
        "home_regions_match_maintained_builder": True,
        "home_provenance_matches_maintained_builder": True,
        "target_region_id_empty": True,
        "controls_unchanged": True,
        "three_nodes_two_edges": True,
        "authorization_flags": True,
    }


def test_hybrid_proof_canonical_builder_save_preserves_maintained_regions(tmp_path: Path) -> None:
    marker = tmp_path / "legacy-blocker-active.txt"
    result_path = tmp_path / "result.json"
    (tmp_path / "sitecustomize.py").write_text(
        """import importlib.abc
import os
from pathlib import Path


class LegacyBlocker(importlib.abc.MetaPathFinder):
    prefixes = ("app.main", "app.api.panel", "app.web_panel")

    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == prefix or fullname.startswith(prefix + ".") for prefix in self.prefixes):
            raise ModuleNotFoundError("blocked legacy import: " + fullname)
        return None


import sys
sys.meta_path.insert(0, LegacyBlocker())
Path(os.environ["R8W_LEGACY_BLOCKER_MARKER"]).write_text("active", encoding="utf-8")
""",
        encoding="utf-8",
    )
    environment = dict(
        os.environ,
        PYTHONPATH=os.pathsep.join((str(tmp_path), str(ROOT))),
        PYTHONUTF8="1",
        PYTHONIOENCODING="utf-8",
        R8W_LEGACY_BLOCKER_MARKER=str(marker),
        AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH=":memory:",
        AGENT_GUI_TEST_DENY_REAL_MODEL_WRAPPER="1",
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        QT_QPA_PLATFORM="offscreen",
    )
    program = """
import json
import os
from pathlib import Path
from scripts.prove_portfolio_hybrid_v1_1_persistence import (
    _managed_proof_owner_context,
    _run_public_managed_hybrid_lifecycle,
    _save_public_large_review,
    fake_bounded_vista_runner,
    fake_omni_runner,
    fake_qwen_runner,
)
from app.learn.interface_workflow_service import save_interface_workflow_review_transaction
from app.learn.learning_draft_review_service import load_interface_workflow_review_transaction
root = Path(os.environ["R8W_SYNTHETIC_ROOT"])
workflow_store_path = root / "runtime_state" / "learning-workflow-runs.json"
with _managed_proof_owner_context(
    root,
    workflow_store_path=workflow_store_path,
    omni_runner=fake_omni_runner,
    qwen_runner=fake_qwen_runner,
    vista_runner=fake_bounded_vista_runner,
) as (composition, store, _registry):
    lifecycle = _run_public_managed_hybrid_lifecycle(root, composition=composition, store=store)
    large = _save_public_large_review(root, workflow_store=store, lifecycle=lifecycle)
    reviewed_path = Path(large["reviewed_candidate_path"])
    reviewed_relative = reviewed_path.relative_to(root).as_posix()
    canonical = load_interface_workflow_review_transaction(
        draft_source_paths=[reviewed_relative],
        workflow_run_ids_by_source={reviewed_relative: lifecycle["workflow_run_id"]},
        discover_related_sidecars=False,
        goal="Open a detail and stop at the application entry boundary.",
        application_identity={"url": "https://managed.example.test/jobs"},
        project_root=root,
        workflow_store=store,
    )
    before = canonical["nodes"][0]
    saved = save_interface_workflow_review_transaction(canonical, project_root=root, out_dir=None)
after = saved["saved_review"]["nodes"][0]
Path(os.environ["R8W_RESULT_PATH"]).write_text(json.dumps({
    "source_paths": after["source_paths"] == before["source_paths"],
    "regions": after["regions"] == before["regions"],
    "selection_replay_provenance": after["selection_replay_provenance"] == before["selection_replay_provenance"],
    "hybrid_review_source_provenance": bool(before["hybrid_review_source_provenance"]) and after["hybrid_review_source_provenance"] == before["hybrid_review_source_provenance"],
    "display_only": after["display_only"] is True,
    "artifact_is_authorization": after["artifact_is_authorization"] is False,
    "execute_binding_enabled": after["execute_binding_enabled"] is False,
}, ensure_ascii=False), encoding="utf-8")
"""
    environment["R8W_SYNTHETIC_ROOT"] = str(tmp_path / "synthetic-canonical-save")
    environment["R8W_RESULT_PATH"] = str(result_path)
    completed = subprocess.run(
        [sys.executable, "-c", program],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert marker.read_text(encoding="utf-8") == "active"
    assert json.loads(result_path.read_text(encoding="utf-8")) == {
        "source_paths": True,
        "regions": True,
        "selection_replay_provenance": True,
        "hybrid_review_source_provenance": True,
        "display_only": True,
        "artifact_is_authorization": True,
        "execute_binding_enabled": True,
    }


def test_hybrid_proof_factory_exposes_owner_schemas_and_errors(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient
    from scripts.prove_portfolio_hybrid_v1_1_persistence import _create_proof_app

    application = _create_proof_app(
        root=tmp_path,
        workflow_store_path=tmp_path / "runtime_state" / "learning-workflow-runs.json",
    )
    schema = application.openapi()
    paths = schema["paths"]
    assert set(paths) >= {
        "/_proof/reviewed-workflow/compile",
        "/_proof/reviewed-workflow/publish",
        "/_proof/learning-draft-review/load",
    }
    for path in (
        "/_proof/reviewed-workflow/compile",
        "/_proof/reviewed-workflow/publish",
        "/_proof/learning-draft-review/load",
    ):
        assert "requestBody" in paths[path]["post"]

    with TestClient(application) as client:
        compile_response = client.post(
            "/_proof/reviewed-workflow/compile",
            json={
                "application_identity_key": "proof.example.test",
                "workflow_id": "missing-workflow",
                "expected_source_workflow_sha256": "0" * 64,
            },
        )
        publish_response = client.post(
            "/_proof/reviewed-workflow/publish",
            json={
                "application_identity_key": "proof.example.test",
                "workflow_id": "missing-workflow",
                "expected_source_workflow_sha256": "0" * 64,
                "expected_registry_revision": 0,
            },
        )
        load_response = client.post(
            "/_proof/learning-draft-review/load",
            json={
                "source_path": "missing-draft.json",
                "workflow_run_id": None,
                "discover_related_sidecars": False,
            },
        )

    for response in (compile_response, publish_response, load_response):
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is False
        assert isinstance(body["error"], dict)


def test_hybrid_proof_servers_restart_with_openapi_and_close_listener(tmp_path: Path) -> None:
    import socket
    from urllib.parse import urlparse

    from app.learn.workflow_store import LearningWorkflowRunStore
    from scripts.prove_portfolio_hybrid_v1_1_persistence import (
        _http_json,
        _start_proof_server,
        _stop_proof_server,
    )

    def assert_listener_closed(server: dict[str, object]) -> None:
        address = urlparse(str(server["base_url"]))
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.settimeout(1)
            assert listener.connect_ex((address.hostname or "127.0.0.1", address.port or 0)) != 0

    def assert_store_lock_released() -> None:
        reopened = LearningWorkflowRunStore(state_path=workflow_store_path)
        reopened.close()

    root = tmp_path / "loopback-proof"
    workflow_store_path = root / "runtime_state" / "learning-workflow-runs.json"
    first = _start_proof_server(root=root, workflow_store_path=workflow_store_path, label="a")
    try:
        first_schema = _http_json(f"{first['base_url']}/openapi.json")
        first_pid = first["process"].pid
        assert "/_proof/reviewed-workflow/compile" in first_schema["paths"]
    finally:
        first_exit, first_stdout, first_stderr = _stop_proof_server(first)
    assert first_exit == 0, first_stdout + first_stderr
    assert_listener_closed(first)
    assert_store_lock_released()

    second = _start_proof_server(root=root, workflow_store_path=workflow_store_path, label="b")
    try:
        second_schema = _http_json(f"{second['base_url']}/openapi.json")
        assert second["process"].pid != first_pid
        assert "/_proof/learning-draft-review/load" in second_schema["paths"]
    finally:
        second_exit, second_stdout, second_stderr = _stop_proof_server(second)
    assert second_exit == 0, second_stdout + second_stderr
    assert_listener_closed(second)
    assert_store_lock_released()


def test_hybrid_proof_factory_owns_explicit_store_without_global_reuse(
    tmp_path: Path, monkeypatch: object
) -> None:
    from fastapi.testclient import TestClient
    from app.learn import workflow_store as workflow_store_module
    from scripts.prove_portfolio_hybrid_v1_1_persistence import _create_proof_app

    workflow_store_path = tmp_path / "runtime_state" / "learning-workflow-runs.json"

    class GlobalStoreSentinel:
        _state_path = workflow_store_path.resolve()
        closed = False

        def close(self) -> None:
            self.closed = True

    sentinel = GlobalStoreSentinel()
    monkeypatch.setattr(workflow_store_module, "learning_workflow_run_store", sentinel)
    application = _create_proof_app(root=tmp_path, workflow_store_path=workflow_store_path)
    with TestClient(application):
        assert application.state.workflow_store is not sentinel
    assert sentinel.closed is False
