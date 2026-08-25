from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.api import panel as panel_api
from app.main import app
from app.learn import interface_workflow_review as workflow_review_module
from app.learn.draft_review import load_learning_draft_review
from app.learn.interface_workflow_review import (
    build_blocked_interface_projection,
    build_interface_workflow_review,
    load_interface_workflow_agent_context,
    load_interface_workflow_library_registry,
    load_interface_workflow_review_context,
    project_interface_review_eligibility,
    save_interface_workflow_review_candidate,
)


def _review(
    *,
    source_path: str,
    signature: str,
    summary: str,
    screenshot_path: str,
    overlay_path: str = "",
) -> dict:
    return {
        "contract_version": "learning_draft_review_v1",
        "source": {
            "source_path": source_path,
            "sha256": f"sha-{signature}",
        },
        "review_status": "needs_human_review",
        "draft": {
            "contract_version": "learning_template_draft_v1",
            "screen_summary": summary,
            "state_guess": "generic_surface",
            "state_signature": signature,
            "source_image_path": screenshot_path,
            "numbered_map_path": overlay_path,
            "states": [{"state_id": f"{signature}-state", "label": summary}],
            "regions": [
                {
                    "region_id": f"{signature}-region",
                    "label": "Primary control",
                    "bbox": {"x": 10, "y": 20, "width": 100, "height": 40},
                    "click_point": {"x": 40, "y": 40},
                }
            ],
            "action_templates": [
                {
                    "action_template_id": f"{signature}-action",
                    "label": "Open",
                    "action_type": "click",
                    "target_region_id": f"{signature}-region",
                    "actual_point": {"x": 40, "y": 40},
                }
            ],
            "page_details": {
                "screen": {
                    "summary": summary,
                    "image_path": screenshot_path,
                },
                "compiled_overlay_path": overlay_path,
            },
        },
    }


def _mark_reviewed_and_agent_readable(review: dict) -> dict:
    review["review_status"] = "human_approved"
    review["reviewed_by_human"] = True
    review["draft"]["agent_description"] = "Open the primary item safely."
    review["draft"]["content_descriptors"] = [
        {
            "content_id": "primary-anchor",
            "source_id": "primary-anchor",
            "label": "Primary item",
            "semantic_name": "Primary item",
            "content_behavior": "fixed_label",
        }
    ]
    review["draft"]["controls"] = [
        {
            "control_id": "primary-control",
            "semantic_name": "Primary item",
            "purpose": "Open the primary item",
            "role": "button",
        }
    ]
    review["draft"]["action_templates"][0]["target_control_id"] = "primary-control"
    review["draft"]["action_templates"][0]["agent_description"] = (
        "Open the selected primary item."
    )
    review["draft"]["action_templates"][0]["review_status"] = "human_approved"
    return review


def _confirm_current_node_revision(review: dict, node: dict) -> None:
    node["review_status"] = "human_approved"
    node["reviewed_by_human"] = True
    node["human_review_confirmation"] = {
        "contract_version": "interface_node_human_review_confirmation_v1",
        "revision": workflow_review_module.build_interface_node_review_revision(
            review,
            node_id=node["node_id"],
        ),
    }


def test_editable_action_templates_do_not_copy_control_ids_into_region_namespace() -> None:
    templates = workflow_review_module._editable_action_templates(
        {
            "action_candidates": [
                {
                    "action_template_id": "open_apply_flow",
                    "semantic_action": "open_apply_flow",
                    "source_control_id": "apply",
                    "target_control_id": "apply",
                    "target_region_id": "",
                    "target_interface_id": "apply_entry",
                }
            ]
        }
    )

    assert templates[0]["target_control_id"] == "apply"
    assert templates[0]["target_region_id"] == ""


def _write_review_evidence(tmp_path: Path, *reviews: dict) -> None:
    for index, review in enumerate(reviews, start=1):
        draft = review["draft"]
        screenshot_path = tmp_path / draft["source_image_path"]
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (64, 48), (index, index, index)).save(screenshot_path)
        source_path = tmp_path / review["source"]["source_path"]
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(
            json.dumps(
                {
                    "contract_version": "learning_draft_review_v1",
                    "review_status": review["review_status"],
                    "draft": draft,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        review["source"]["sha256"] = hashlib.sha256(source_path.read_bytes()).hexdigest()


def test_node_review_source_preserves_stable_workflow_node_identity(tmp_path: Path) -> None:
    source = tmp_path / "artifacts" / "node-review-sources" / "interface_existing123.json"
    source.parent.mkdir(parents=True)
    source.write_text(
        json.dumps(
            {
                "contract_version": "interface_workflow_node_review_source_v1",
                "workflow_id": "workflow_existing",
                "node_id": "interface_existing123",
                "draft": {
                    "contract_version": "learning_template_draft_v1",
                    "screen_summary": "Existing interface",
                    "state_signature": "stable-screen-signature",
                    "states": [],
                    "regions": [],
                    "action_templates": [],
                },
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    candidate = tmp_path / "artifacts" / "learning-draft-review" / "reviewed.json"
    candidate.parent.mkdir(parents=True)
    candidate.write_text(
        json.dumps(
            {
                "contract_version": "reviewed_template_candidate_v1",
                "source": {
                    "source_path": "artifacts/node-review-sources/interface_existing123.json",
                    "original_draft_path": "artifacts/node-review-sources/interface_existing123.json",
                },
                "review_status": "approved_as_assisted_template",
                "reviewed_by_human": True,
                "source_after_review": "assisted_generation",
                "draft": {
                    "contract_version": "learning_template_draft_v1",
                    "screen_summary": "Existing interface",
                    "state_signature": "stable-screen-signature",
                    "states": [],
                    "regions": [],
                    "action_templates": [],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    loaded = load_learning_draft_review(
        candidate,
        project_root=tmp_path,
        discover_related_sidecars=False,
    )
    review = build_interface_workflow_review(
        goal="Preserve reviewed interface identity",
        application_identity={"kind": "native", "name": "Example"},
        draft_sources=[loaded],
    )

    assert loaded["workflow_node_identity"] == {
        "workflow_id": "workflow_existing",
        "node_id": "interface_existing123",
    }
    assert review["workflow"]["entry_node_id"] == "interface_existing123"
    assert review["workflow"]["node_ids"] == ["interface_existing123"]
    assert review["nodes"][0]["node_id"] == "interface_existing123"
    assert review["nodes"][0]["review_status"] == "approved_as_assisted_template"
    assert review["nodes"][0]["reviewed_by_human"] is True


def test_builds_generic_nodes_and_edges_without_seek_fields() -> None:
    result = build_interface_workflow_review(
        goal="Open an item and review its details",
        application_identity={"name": "ExampleApp", "process": "example.exe"},
        draft_sources=[
            _review(
                source_path="artifacts/learning/a.json",
                signature="list",
                summary="Item list",
                screenshot_path="artifacts/screenshots/list.png",
                overlay_path="artifacts/review-overlays/list.png",
            ),
            _review(
                source_path="artifacts/learning/b.json",
                signature="detail",
                summary="Item details",
                screenshot_path="artifacts/screenshots/detail.png",
                overlay_path="artifacts/review-overlays/detail.png",
            ),
        ],
    )

    assert result["contract_version"] == "single_application_workflow_review_v1"
    assert result["display_only"] is True
    assert result["artifact_is_authorization"] is False
    assert result["execute_binding_enabled"] is False
    assert result["workflow"]["goal"] == "Open an item and review its details"
    assert result["workflow"]["application_identity"]["name"] == "ExampleApp"
    assert len(result["nodes"]) == 2
    assert len(result["edges"]) == 1
    assert result["edges"][0]["source_node_id"] == result["nodes"][0]["node_id"]
    assert result["edges"][0]["target_node_id"] == result["nodes"][1]["node_id"]
    assert "seek" not in str(result).lower()


def test_reuses_state_signature_for_duplicate_interface() -> None:
    first = _review(
        source_path="artifacts/learning/a.json",
        signature="same-screen",
        summary="Settings",
        screenshot_path="artifacts/screenshots/settings-a.png",
    )
    second = _review(
        source_path="artifacts/learning/b.json",
        signature="same-screen",
        summary="Settings again",
        screenshot_path="artifacts/screenshots/settings-b.png",
    )

    result = build_interface_workflow_review(
        goal="Change a setting",
        application_identity={"name": "ExampleApp"},
        draft_sources=[first, second],
    )

    assert len(result["nodes"]) == 1
    assert result["nodes"][0]["observation_count"] == 2
    assert len(result["nodes"][0]["source_paths"]) == 2
    assert result["edges"] == []


def test_missing_overlay_is_explicit_and_does_not_borrow_previous_node() -> None:
    result = build_interface_workflow_review(
        goal="Review screens",
        application_identity={"name": "ExampleApp"},
        draft_sources=[
            _review(
                source_path="artifacts/learning/a.json",
                signature="with-overlay",
                summary="First",
                screenshot_path="artifacts/screenshots/first.png",
                overlay_path="artifacts/review-overlays/first.png",
            ),
            _review(
                source_path="artifacts/learning/b.json",
                signature="without-overlay",
                summary="Second",
                screenshot_path="artifacts/screenshots/second.png",
            ),
        ],
    )

    first, second = result["nodes"]
    assert first["evidence"]["fused_overlay_path"].endswith("first.png")
    assert second["evidence"]["fused_overlay_path"] == ""
    assert second["evidence"]["numbered_overlay_path"] == ""
    assert second["evidence_status"] == "overlay_missing"
    assert second["evidence"]["source_screenshot_path"].endswith("second.png")


def test_runtime_click_coordinates_are_not_persisted() -> None:
    result = build_interface_workflow_review(
        goal="Open an item",
        application_identity={"name": "ExampleApp"},
        draft_sources=[
            _review(
                source_path="artifacts/learning/a.json",
                signature="screen",
                summary="Screen",
                screenshot_path="artifacts/screenshots/screen.png",
            )
        ],
    )

    serialized = str(result)
    assert "click_point" not in serialized
    assert "actual_point" not in serialized
    assert result["nodes"][0]["regions"][0]["bbox"] == {
        "x": 10,
        "y": 20,
        "width": 100,
        "height": 40,
    }
    assert result["safety"]["runtime_requires_fresh_grounding"] is True


def test_panel_loads_generic_interface_workflow_review(
    tmp_path: Path,
    monkeypatch,
) -> None:
    for name, signature in (("first", "list"), ("second", "detail")):
        source_path = tmp_path / "artifacts" / "learning" / f"{name}.json"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(
            json.dumps(
                {
                    "contract_version": "learning_template_draft_v1",
                    "screen_summary": name.title(),
                    "state_guess": "generic_surface",
                    "state_signature": signature,
                    "states": [{"state_id": signature, "label": name.title()}],
                    "regions": [],
                    "action_templates": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)

    response = TestClient(app).post(
        "/panel/load_interface_workflow_review",
        json={
            "goal": "Open an item",
            "application_identity": {"name": "ExampleApp"},
            "draft_source_paths": [
                "artifacts/learning/first.json",
                "artifacts/learning/second.json",
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["contract_version"] == "single_application_workflow_review_v1"
    assert len(payload["data"]["nodes"]) == 2
    assert len(payload["data"]["edges"]) == 1
    assert payload["data"]["artifact_is_authorization"] is False


def test_panel_reports_invalid_workflow_review_source_without_failing_valid_nodes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    valid_path = tmp_path / "artifacts" / "learning" / "valid.json"
    valid_path.parent.mkdir(parents=True, exist_ok=True)
    valid_path.write_text(
        json.dumps(
            {
                "contract_version": "learning_template_draft_v1",
                "screen_summary": "Valid screen",
                "state_signature": "valid",
                "states": [{"state_id": "valid", "label": "Valid"}],
                "regions": [],
                "action_templates": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)

    payload = TestClient(app).post(
        "/panel/load_interface_workflow_review",
        json={
            "goal": "Review screens",
            "application_identity": {"name": "ExampleApp"},
            "draft_source_paths": [
                "artifacts/learning/valid.json",
                "../outside-project.json",
            ],
        },
    ).json()

    assert payload["success"] is True
    assert len(payload["data"]["nodes"]) == 1
    assert payload["data"]["invalid_sources"][0]["source_path"] == "../outside-project.json"
    assert payload["data"]["invalid_sources"][0]["failure_category"] == "invalid_review_source"


def test_panel_workflow_review_can_skip_related_sidecar_discovery(
    monkeypatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_load_learning_draft_review(
        source_path: str,
        *,
        project_root: Path,
        discover_related_sidecars: bool = True,
    ) -> dict[str, object]:
        calls.append(
            {
                "source_path": source_path,
                "project_root": project_root,
                "discover_related_sidecars": discover_related_sidecars,
            }
        )
        return _review(
            source_path=source_path,
            signature=Path(source_path).stem,
            summary=Path(source_path).stem,
        )

    monkeypatch.setattr(
        panel_api,
        "load_learning_draft_review",
        fake_load_learning_draft_review,
    )

    payload = TestClient(app).post(
        "/panel/load_interface_workflow_review",
        json={
            "goal": "Refresh known workflow evidence",
            "application_identity": {"name": "ExampleApp"},
            "draft_source_paths": [
                "artifacts/learning/first.json",
                "artifacts/learning/second.json",
            ],
            "discover_related_sidecars": False,
        },
    ).json()

    assert payload["success"] is True
    assert [call["discover_related_sidecars"] for call in calls] == [False, False]


def test_saved_workflow_review_candidate_remains_display_only_and_removes_runtime_points(
    tmp_path: Path,
) -> None:
    review = build_interface_workflow_review(
        goal="打开设置并检查选项",
        application_identity={"name": "示例软件"},
        draft_sources=[
            _review(
                source_path="artifacts/learning/a.json",
                signature="settings",
                summary="设置界面",
                screenshot_path="artifacts/screenshots/settings.png",
            )
        ],
    )
    review["display_only"] = False
    review["artifact_is_authorization"] = True
    review["execute_binding_enabled"] = True
    review["nodes"][0]["click_point"] = {"x": 50, "y": 60}
    review["nodes"][0]["regions"][0]["actual_point"] = {"x": 40, "y": 40}

    result = save_interface_workflow_review_candidate(
        review,
        project_root=tmp_path,
    )

    saved_path = Path(result["path"])
    saved = json.loads(saved_path.read_text(encoding="utf-8"))
    serialized = saved_path.read_text(encoding="utf-8")
    assert saved["display_only"] is True
    assert saved["artifact_is_authorization"] is False
    assert saved["execute_binding_enabled"] is False
    assert saved["workflow"]["published_memory_version"] is None
    assert saved["safety"]["review_draft_only"] is True
    assert "click_point" not in serialized
    assert "actual_point" not in serialized
    assert "示例软件" in serialized
    assert result["review_status"] == "needs_human_review"
    assert result["published"] is False


def test_saved_workflow_materializes_editable_evidence_for_each_interface(
    tmp_path: Path,
) -> None:
    screenshot_path = tmp_path / "artifacts" / "screenshots" / "settings.png"
    screenshot_path.parent.mkdir(parents=True)
    Image.new("RGB", (320, 180), "white").save(screenshot_path)
    review = build_interface_workflow_review(
        goal="打开设置并检查选项",
        application_identity={"name": "示例软件"},
        draft_sources=[
            _review(
                source_path="configs/demo/settings.json",
                signature="settings",
                summary="设置界面",
                screenshot_path="artifacts/screenshots/settings.png",
            )
        ],
    )

    result = save_interface_workflow_review_candidate(review, project_root=tmp_path)

    saved = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    node = saved["nodes"][0]
    editable_path = str(node["editable_review_source_path"])
    assert editable_path.startswith("artifacts/interface-workflow-reviews/")
    assert node["source_paths"][0] == editable_path
    assert (tmp_path / editable_path).is_file()

    loaded = load_learning_draft_review(editable_path, project_root=tmp_path)
    assert loaded["draft"]["screen_summary"] == "设置界面"
    loaded_source_image_path = loaded["draft"]["page_details"]["screen"]["source_image_path"]
    assert loaded_source_image_path.startswith(
        "artifacts/interface-workflow-reviews/"
    )
    assert loaded_source_image_path.endswith(
        "/node-evidence/interface_aeda63a77ff2/source_screenshot_path.png"
    )
    assert (tmp_path / loaded_source_image_path).is_file()
    assert loaded["artifact_is_authorization"] is False
    assert loaded["execute_binding_enabled"] is False


def test_saved_workflow_keeps_reviewed_candidate_as_exact_authoritative_source(
    tmp_path: Path,
) -> None:
    reviewed_path = (
        tmp_path / "artifacts" / "learning-draft-review" / "reviewed.json"
    )
    reviewed_path.parent.mkdir(parents=True)
    reviewed_path.write_text(
        json.dumps(
            {
                "contract_version": "reviewed_template_candidate_v1",
                "draft": {"contract_version": "learning_template_draft_v1"},
            }
        ),
        encoding="utf-8",
    )
    review = build_interface_workflow_review(
        goal="Review exact source lineage",
        application_identity={"name": "ExampleApp"},
        draft_sources=[
            _review(
                source_path=reviewed_path.relative_to(tmp_path).as_posix(),
                signature="reviewed-source",
                summary="Reviewed source",
                screenshot_path="artifacts/screenshots/reviewed.png",
            )
        ],
    )

    result = save_interface_workflow_review_candidate(review, project_root=tmp_path)

    node = json.loads(Path(result["path"]).read_text(encoding="utf-8"))["nodes"][0]
    assert node["source_paths"] == [reviewed_path.relative_to(tmp_path).as_posix()]
    assert "/node-review-sources/" in node["editable_review_source_path"]
    assert (tmp_path / node["editable_review_source_path"]).is_file()


def test_saved_workflow_owns_durable_node_evidence_after_source_cleanup(
    tmp_path: Path,
) -> None:
    screenshot_path = tmp_path / "artifacts" / "screenshots" / "settings.png"
    overlay_path = tmp_path / "artifacts" / "review-overlays" / "settings.png"
    screenshot_path.parent.mkdir(parents=True)
    overlay_path.parent.mkdir(parents=True)
    Image.new("RGB", (320, 180), "white").save(screenshot_path)
    Image.new("RGB", (320, 180), "blue").save(overlay_path)
    review = build_interface_workflow_review(
        goal="Review settings",
        application_identity={"name": "ExampleApp"},
        draft_sources=[
            _review(
                source_path="configs/demo/settings.json",
                signature="settings",
                summary="Settings",
                screenshot_path="artifacts/screenshots/settings.png",
                overlay_path="artifacts/review-overlays/settings.png",
            )
        ],
    )

    result = save_interface_workflow_review_candidate(review, project_root=tmp_path)

    saved = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    node = saved["nodes"][0]
    durable_screenshot = tmp_path / node["evidence"]["source_screenshot_path"]
    durable_overlay = tmp_path / node["evidence"]["fused_overlay_path"]
    assert durable_screenshot.is_file()
    assert durable_overlay.is_file()
    assert durable_screenshot.parent.parent.name == "node-evidence"
    assert durable_overlay.parent == durable_screenshot.parent
    assert node["evidence"]["source_screenshot_sha256"]

    screenshot_path.unlink()
    overlay_path.unlink()
    assert durable_screenshot.is_file()
    assert durable_overlay.is_file()

    editable_path = tmp_path / node["editable_review_source_path"]
    editable = json.loads(editable_path.read_text(encoding="utf-8"))
    assert editable["draft"]["page_details"]["screen"]["source_image_path"] == (
        node["evidence"]["source_screenshot_path"]
    )
    assert editable["draft"]["page_details"]["screen"]["source_image_sha256"] == (
        node["evidence"]["source_screenshot_sha256"]
    )


def test_saved_workflow_review_preserves_runtime_audit_without_reusable_points(
    tmp_path: Path,
) -> None:
    review = build_interface_workflow_review(
        goal="读取当前页面并安全停止",
        application_identity={"name": "示例软件"},
        draft_sources=[
            _review(
                source_path="artifacts/learning/a.json",
                signature="results",
                summary="结果界面",
                screenshot_path="artifacts/screenshots/results.png",
            )
        ],
    )
    interface_id = review["nodes"][0]["node_id"]
    review["runtime_report"] = {
        "final_status": "safe_stop",
        "stop_reason": "gate_rejected",
        "steps": [
            {
                "interface_id": interface_id,
                "agent_decision": "open_detail",
                "gate_allowed": False,
                "dispatch_success": False,
                "action_executed": False,
                "effect_verified": False,
                "trace_path": "logs/traces/example.json",
                "click_point": {"x": 120, "y": 240},
            }
        ],
    }

    result = save_interface_workflow_review_candidate(review, project_root=tmp_path)

    saved_path = Path(result["path"])
    saved = json.loads(saved_path.read_text(encoding="utf-8"))
    serialized = saved_path.read_text(encoding="utf-8")
    assert saved["runtime_report"]["final_status"] == "safe_stop"
    assert saved["runtime_report"]["steps"][0]["agent_decision"] == "open_detail"
    assert saved["runtime_report"]["steps"][0]["gate_allowed"] is False
    assert saved["runtime_report"]["steps"][0]["trace_path"] == "logs/traces/example.json"
    assert "click_point" not in serialized


def test_agent_context_reloads_saved_runtime_audit_without_reusable_points(
    tmp_path: Path,
) -> None:
    review = build_interface_workflow_review(
        goal="读取当前页面并安全停止",
        application_identity={
            "process": "msedge.exe",
            "url": "https://app.example.com/items",
        },
        draft_sources=[
            _review(
                source_path="artifacts/learning/a.json",
                signature="results",
                summary="结果界面",
                screenshot_path="artifacts/screenshots/results.png",
            )
        ],
    )
    interface_id = review["nodes"][0]["node_id"]
    review["runtime_report"] = {
        "contract_version": "navigation_reading_controller_report_v1",
        "session_id": "session_review_rehearsal",
        "final_status": "safe_stop",
        "stop_reason": "gate_rejected",
        "steps": [
            {
                "interface_id": interface_id,
                "agent_decision": "open_detail",
                "gate_allowed": False,
                "dispatch_success": False,
                "action_executed": False,
                "effect_verified": False,
                "trace_path": "logs/traces/example.json",
                "click_point": {"x": 120, "y": 240},
            }
        ],
    }
    save_interface_workflow_review_candidate(review, project_root=tmp_path)

    context = load_interface_workflow_agent_context(
        project_root=tmp_path,
        application_identity_key="web:app.example.com",
    )

    loaded = context["workflows"][0]["runtime_report"]
    assert loaded["session_id"] == "session_review_rehearsal"
    assert loaded["final_status"] == "safe_stop"
    assert loaded["steps"][0]["interface_id"] == interface_id
    assert loaded["steps"][0]["trace_path"] == "logs/traces/example.json"
    assert "click_point" not in json.dumps(loaded, ensure_ascii=False)


def test_saved_workflow_review_is_indexed_by_canonical_application_identity(
    tmp_path: Path,
) -> None:
    review = build_interface_workflow_review(
        goal="Review a job and open its application flow",
        application_identity={
            "name": "Microsoft Edge",
            "process": "msedge.exe",
            "url": "https://www.seek.co.nz/jobs",
        },
        draft_sources=[
            _review(
                source_path="artifacts/learning/jobs.json",
                signature="jobs",
                summary="Job list",
                screenshot_path="artifacts/screenshots/jobs.png",
            )
        ],
    )

    result = save_interface_workflow_review_candidate(
        review,
        project_root=tmp_path,
    )

    registry = json.loads(
        (tmp_path / "artifacts" / "interface-workflow-reviews" / "registry.json").read_text(
            encoding="utf-8"
        )
    )
    assert result["application_identity_key"] == "web:seek.co.nz"
    assert result["library_index_status"] == "indexed"
    assert registry["applications"]["web:seek.co.nz"]["workflow_ids"] == [
        review["workflow"]["workflow_id"]
    ]
    assert registry["workflows"][review["workflow"]["workflow_id"]]["path"] == result["path"]


def test_browser_workflow_without_domain_is_saved_but_not_silently_indexed_as_edge(
    tmp_path: Path,
) -> None:
    review = build_interface_workflow_review(
        goal="Review current page",
        application_identity={
            "name": "Microsoft Edge",
            "process": "msedge.exe",
        },
        draft_sources=[
            _review(
                source_path="artifacts/learning/page.json",
                signature="page",
                summary="Current page",
                screenshot_path="artifacts/screenshots/page.png",
            )
        ],
    )

    result = save_interface_workflow_review_candidate(
        review,
        project_root=tmp_path,
    )

    assert Path(result["path"]).exists()
    assert result["application_identity_key"] is None
    assert result["library_index_status"] == "identity_unresolved"
    assert result["identity_status"] == "needs_domain_review"


def test_agent_can_load_reviewed_workflow_context_by_application_identity(
    tmp_path: Path,
) -> None:
    reviewed_source = _review(
        source_path="artifacts/learning/items.json",
        signature="items",
        summary="Items",
        screenshot_path="artifacts/screenshots/items.png",
    )
    _mark_reviewed_and_agent_readable(reviewed_source)
    _write_review_evidence(tmp_path, reviewed_source)
    review = build_interface_workflow_review(
        goal="Open an item and inspect details",
        application_identity={
            "process": "msedge.exe",
            "url": "https://app.example.com/items",
        },
        draft_sources=[reviewed_source],
    )
    _confirm_current_node_revision(review, review["nodes"][0])
    save_interface_workflow_review_candidate(review, project_root=tmp_path)

    registry = load_interface_workflow_library_registry(project_root=tmp_path)
    context = load_interface_workflow_agent_context(
        project_root=tmp_path,
        application_identity_key="web:app.example.com",
    )

    assert registry["applications"]["web:app.example.com"]["workflow_ids"] == [
        review["workflow"]["workflow_id"]
    ]
    assert context["application_identity_key"] == "web:app.example.com"
    assert context["workflow_count"] == 1
    assert context["workflows"][0]["nodes"][0]["display_name"] == "Items"
    assert context["agent_evidence_workflows"][0]["interfaces"][0]["interface"]["display_name"] == "Items"
    assert context["agent_evidence_workflows"][0]["interfaces"][0]["readiness"]["status"] == "agent_usable"
    assert context["agent_ready"] is True
    assert context["blocked_interfaces"] == []
    assert context["execution_contract"]["historical_coordinates_forbidden"] is True
    assert context["execution_contract"]["fresh_grounding_required"] is True
    assert context["artifact_is_authorization"] is False


def test_agent_context_blocks_unreviewed_workflow_nodes(tmp_path: Path) -> None:
    reviewed_source = _review(
        source_path="artifacts/learning/reviewed.json",
        signature="reviewed",
        summary="Reviewed interface",
        screenshot_path="artifacts/screenshots/reviewed.png",
    )
    _mark_reviewed_and_agent_readable(reviewed_source)
    unreviewed_source = _review(
        source_path="artifacts/learning/unreviewed.json",
        signature="unreviewed",
        summary="Unreviewed interface",
        screenshot_path="artifacts/screenshots/unreviewed.png",
    )
    _write_review_evidence(tmp_path, reviewed_source, unreviewed_source)
    review = build_interface_workflow_review(
        goal="Review both interfaces",
        application_identity={"url": "https://example.test/items"},
        draft_sources=[reviewed_source, unreviewed_source],
    )
    _confirm_current_node_revision(review, review["nodes"][0])
    save_interface_workflow_review_candidate(review, project_root=tmp_path)

    context = load_interface_workflow_agent_context(
        project_root=tmp_path,
        application_identity_key="web:example.test",
    )

    assert context["agent_ready"] is False
    assert len(context["agent_usable_interfaces"]) == 1
    assert context["blocked_interfaces"] == [
        {
            "workflow_id": review["workflow"]["workflow_id"],
            "interface_id": review["nodes"][1]["node_id"],
            "display_name": "Unreviewed interface",
            "availability": "blocked_unreviewed_interface",
            "agent_usable": False,
            "reason": "human_review_required",
        }
    ]
    serialized = json.dumps(context, ensure_ascii=False)
    assert "unreviewed-action" not in serialized


def test_panel_review_context_keeps_unreviewed_workflow_nodes(tmp_path: Path) -> None:
    reviewed_source = _review(
        source_path="artifacts/learning/reviewed.json",
        signature="reviewed",
        summary="Reviewed interface",
        screenshot_path="artifacts/screenshots/reviewed.png",
    )
    _mark_reviewed_and_agent_readable(reviewed_source)
    unreviewed_source = _review(
        source_path="artifacts/learning/unreviewed.json",
        signature="unreviewed",
        summary="Unreviewed interface",
        screenshot_path="artifacts/screenshots/unreviewed.png",
    )
    review = build_interface_workflow_review(
        goal="Review both interfaces",
        application_identity={"url": "https://example.test/items"},
        draft_sources=[reviewed_source, unreviewed_source],
    )
    _confirm_current_node_revision(review, review["nodes"][0])
    result = save_interface_workflow_review_candidate(review, project_root=tmp_path)

    context = load_interface_workflow_review_context(
        project_root=tmp_path,
        application_identity_key="web:example.test",
        workflow_id=result["workflow_id"],
    )

    assert context["workflow"]["workflow_id"] == result["workflow_id"]
    assert [node["review_status"] for node in context["nodes"]] == [
        "human_approved",
        "needs_human_review",
    ]
    assert context["artifact_is_authorization"] is False


def test_saved_workflow_review_reload_preserves_exact_node_edge_identity(tmp_path: Path) -> None:
    sources = [
        _review(
            source_path=f"artifacts/learning/{name}.json",
            signature=name,
            summary=name.title(),
            screenshot_path=f"artifacts/screenshots/{name}.png",
        )
        for name in ("home", "detail", "documents")
    ]
    for source in sources:
        _mark_reviewed_and_agent_readable(source)
    _write_review_evidence(tmp_path, *sources)
    review = build_interface_workflow_review(
        goal="Open details and then documents",
        application_identity={"url": "https://app.example.com/jobs"},
        draft_sources=sources,
    )
    node_ids = ["interface_home", "interface_detail", "interface_documents"]
    for node, node_id in zip(review["nodes"], node_ids, strict=True):
        node["node_id"] = node_id
        node["review_status"] = "human_approved"
        node["reviewed_by_human"] = True
    review["workflow"].update(
        {
            "workflow_id": "workflow_exact_identity",
            "entry_node_id": node_ids[0],
            "node_ids": node_ids,
            "edge_ids": ["edge_open_detail", "edge_open_apply"],
            "review_status": "human_approved",
        }
    )
    review["edges"] = [
        {
            "edge_id": "edge_open_detail",
            "operation_id": "edge_open_detail",
            "source_node_id": node_ids[0],
            "target_node_id": node_ids[1],
            "action_type": "open_detail",
            "target_control_id": "",
            "target_region_id": "",
            "risk_level": "low",
            "requires_user_confirmation": False,
            "preconditions": [],
            "success_conditions": ["detail visible"],
            "failure_conditions": [],
            "review_status": "human_approved",
        },
        {
            "edge_id": "edge_open_apply",
            "operation_id": "edge_open_apply",
            "source_node_id": node_ids[1],
            "target_node_id": node_ids[2],
            "action_type": "open_apply_flow",
            "target_control_id": "",
            "target_region_id": "",
            "risk_level": "low",
            "requires_user_confirmation": False,
            "preconditions": [],
            "success_conditions": ["documents visible"],
            "failure_conditions": [],
            "review_status": "human_approved",
        },
    ]
    for node in review["nodes"]:
        _confirm_current_node_revision(review, node)

    saved = save_interface_workflow_review_candidate(review, project_root=tmp_path)
    reloaded = load_interface_workflow_review_context(
        project_root=tmp_path,
        application_identity_key="web:app.example.com",
        workflow_id=saved["workflow_id"],
    )

    assert reloaded["workflow"]["workflow_id"] == "workflow_exact_identity"
    assert reloaded["workflow"]["review_status"] == "human_approved"
    assert [node["node_id"] for node in reloaded["nodes"]] == node_ids
    assert [node["review_status"] for node in reloaded["nodes"]] == [
        "human_approved",
        "human_approved",
        "human_approved",
    ]
    assert [edge["edge_id"] for edge in reloaded["edges"]] == [
        "edge_open_detail",
        "edge_open_apply",
    ]
    assert [edge["action_type"] for edge in reloaded["edges"]] == [
        "open_detail",
        "open_apply_flow",
    ]
    assert [edge["review_status"] for edge in reloaded["edges"]] == [
        "human_approved",
        "human_approved",
    ]


def test_blocked_interface_does_not_expose_actionable_evidence() -> None:
    blocked = build_blocked_interface_projection(
        {
            "node_id": "pending_form",
            "display_name": "Pending form",
            "controls": [{"control_id": "email", "bbox": [1, 2, 3, 4]}],
            "action_candidates": [
                {"action_type": "fill_field", "click_point": {"x": 2, "y": 3}}
            ],
        },
        workflow_id="flow_pending",
        reason="human_review_required",
    )

    serialized = json.dumps(blocked, ensure_ascii=False)
    assert "controls" not in blocked
    assert "actions" not in blocked
    assert "bbox" not in serialized
    assert "click_point" not in serialized


def test_agent_facing_workflow_registry_route_is_available() -> None:
    response = TestClient(app).get("/memory/interface_workflows/registry")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["contract_version"] == "interface_workflow_library_registry_v1"
    assert payload["data"]["artifact_is_authorization"] is False


def test_workflow_registry_projects_interface_review_groups(tmp_path: Path) -> None:
    reviewed = _review(
        source_path="artifacts/learning/reviewed.json",
        signature="reviewed",
        summary="Reviewed interface",
        screenshot_path="artifacts/screenshots/reviewed.png",
    )
    reviewed["review_status"] = "human_approved"
    reviewed["reviewed_by_human"] = True
    unreviewed = _review(
        source_path="artifacts/learning/unreviewed.json",
        signature="unreviewed",
        summary="Unreviewed interface",
        screenshot_path="artifacts/screenshots/unreviewed.png",
    )
    _write_review_evidence(tmp_path, reviewed, unreviewed)
    review = build_interface_workflow_review(
        goal="Review both interfaces",
        application_identity={"name": "ExampleApp", "process": "example.exe"},
        draft_sources=[reviewed, unreviewed],
    )
    _confirm_current_node_revision(review, review["nodes"][0])
    result = save_interface_workflow_review_candidate(review, project_root=tmp_path)

    registry = load_interface_workflow_library_registry(project_root=tmp_path)
    record = registry["workflows"][result["workflow_id"]]

    assert [item["display_name"] for item in record["review_groups"]["reviewed"]] == [
        "Reviewed interface"
    ]
    assert [item["display_name"] for item in record["review_groups"]["unreviewed"]] == [
        "Unreviewed interface"
    ]
    assert record["review_counts"] == {"reviewed": 1, "unreviewed": 1}


def test_interface_review_eligibility_fails_closed_for_unreviewed() -> None:
    result = project_interface_review_eligibility(
        {"review_status": "reviewed_candidate", "reviewed_by_human": False}
    )

    assert result == {
        "review_bucket": "unreviewed",
        "agent_usable": False,
        "agent_eligibility_reason": "human_review_required",
    }


def test_interface_review_eligibility_accepts_human_reviewed_node() -> None:
    revision_hash = "a" * 64
    result = project_interface_review_eligibility(
        {
            "review_status": "human_approved",
            "reviewed_by_human": True,
            "reviewed_revision_hash": revision_hash,
            "current_revision_hash": revision_hash,
        }
    )

    assert result == {
        "review_bucket": "reviewed",
        "agent_usable": True,
        "agent_eligibility_reason": "human_reviewed_current_revision",
    }


def test_interface_review_eligibility_rejects_unbound_human_review_fact() -> None:
    result = project_interface_review_eligibility(
        {"review_status": "human_approved", "reviewed_by_human": True}
    )

    assert result == {
        "review_bucket": "unreviewed",
        "agent_usable": False,
        "agent_eligibility_reason": "human_review_revision_missing",
    }


def test_saved_artifact_requires_explicit_human_review_fact_for_each_revision(
    tmp_path: Path,
) -> None:
    source = _review(
        source_path="artifacts/learning/items.json",
        signature="items",
        summary="Items",
        screenshot_path="artifacts/screenshots/items.png",
    )
    _mark_reviewed_and_agent_readable(source)
    source["draft"]["content_descriptors"][0].update(
        {
            "agent_usage": "identity_anchor",
            "read_policy": "on_interface_match",
        }
    )
    _write_review_evidence(tmp_path, source)
    review = build_interface_workflow_review(
        goal="Review one interface",
        application_identity={"url": "https://review.example.test/items"},
        draft_sources=[source],
    )
    node = review["nodes"][0]
    node["review_status"] = "human_approved"
    node.pop("reviewed_by_human", None)

    missing_fact = save_interface_workflow_review_candidate(
        review,
        project_root=tmp_path,
    )
    missing_payload = json.loads(
        Path(missing_fact["path"]).read_text(encoding="utf-8")
    )
    assert missing_payload["nodes"][0]["reviewed_by_human"] is False
    assert missing_payload["nodes"][0]["review_status"] == "needs_human_review"
    missing_context = load_interface_workflow_agent_context(
        project_root=tmp_path,
        application_identity_key="web:review.example.test",
    )
    assert missing_context["agent_ready"] is False
    assert len(missing_context["blocked_interfaces"]) == 1

    node["review_status"] = "human_approved"
    node["reviewed_by_human"] = True
    node["human_review_confirmation"] = {
        "contract_version": "interface_node_human_review_confirmation_v1",
        "revision": workflow_review_module.build_interface_node_review_revision(
            review,
            node_id=node["node_id"],
        ),
    }
    confirmed = save_interface_workflow_review_candidate(
        review,
        project_root=tmp_path,
    )
    confirmed_payload = json.loads(
        Path(confirmed["path"]).read_text(encoding="utf-8")
    )
    assert confirmed_payload["nodes"][0]["reviewed_by_human"] is True
    confirmed_context = load_interface_workflow_agent_context(
        project_root=tmp_path,
        application_identity_key="web:review.example.test",
    )
    assert confirmed_context["agent_ready"] is True
    assert len(confirmed_context["agent_usable_interfaces"]) == 1

    node["controls"] = [
        {"control_id": "edited", "semantic_name": "Edited current revision"}
    ]
    node["review_status"] = "needs_human_review"
    node["reviewed_by_human"] = False
    edited = save_interface_workflow_review_candidate(
        review,
        project_root=tmp_path,
    )
    edited_payload = json.loads(Path(edited["path"]).read_text(encoding="utf-8"))
    assert edited_payload["nodes"][0]["reviewed_by_human"] is False
    edited_context = load_interface_workflow_agent_context(
        project_root=tmp_path,
        application_identity_key="web:review.example.test",
    )
    assert edited_context["agent_ready"] is False
    assert len(edited_context["blocked_interfaces"]) == 1


def test_stale_human_review_fact_is_revoked_after_semantic_edit(tmp_path: Path) -> None:
    source = _review(
        source_path="artifacts/learning/stale.json",
        signature="stale",
        summary="Stale review",
        screenshot_path="artifacts/screenshots/stale.png",
    )
    _mark_reviewed_and_agent_readable(source)
    review = build_interface_workflow_review(
        goal="Reject stale human review",
        application_identity={"url": "https://stale.example.test/items"},
        draft_sources=[source],
    )
    node = review["nodes"][0]
    node["review_status"] = "human_approved"
    node["reviewed_by_human"] = True
    node["human_review_confirmation"] = {
        "contract_version": "interface_node_human_review_confirmation_v1",
        "revision": workflow_review_module.build_interface_node_review_revision(
            review,
            node_id=node["node_id"],
        ),
    }

    node["controls"] = [
        {
            "control_id": "changed-after-review",
            "semantic_name": "Changed after the human confirmation",
        }
    ]
    saved = save_interface_workflow_review_candidate(review, project_root=tmp_path)
    payload = json.loads(Path(saved["path"]).read_text(encoding="utf-8"))
    persisted = payload["nodes"][0]

    assert persisted["review_status"] == "needs_human_review"
    assert persisted["reviewed_by_human"] is False
    assert persisted["reviewed_revision_hash"] == ""
    assert len(persisted["current_revision_hash"]) == 64


def test_panel_projection_uses_normalized_review_not_raw_human_label(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = _review(
        source_path="artifacts/learning/label-only.json",
        signature="label-only",
        summary="Label only approval",
        screenshot_path="artifacts/screenshots/label-only.png",
    )
    _mark_reviewed_and_agent_readable(source)
    source["draft"]["content_descriptors"][0].update(
        {
            "agent_usage": "identity_anchor",
            "read_policy": "on_interface_match",
        }
    )
    review = build_interface_workflow_review(
        goal="Reject label-only approval",
        application_identity={"url": "https://label-only.example.test/items"},
        draft_sources=[source],
    )
    node = review["nodes"][0]
    node["review_status"] = "human_approved"
    node["reviewed_by_human"] = True
    node.pop("human_review_confirmation", None)
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)

    response = TestClient(app).post(
        "/panel/save_interface_workflow_review",
        json={"review": review},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True, body
    projection = body["data"]["interface_asset_projection"]
    assert projection["agent_evidence_projection"]["agent_usable_count"] == 0
    assert projection["agent_evidence_projection"]["needs_human_review_count"] == 1
    saved_review = json.loads(
        Path(body["data"]["path"]).read_text(encoding="utf-8")
    )
    assert saved_review["nodes"][0]["reviewed_by_human"] is False
    asset_path = tmp_path / projection["interface_results"][0]["asset_path"]
    asset = json.loads(asset_path.read_text(encoding="utf-8"))
    assert asset["review"]["reviewed_by_human"] is False
    assert asset["review"]["reviewed_revision_hash"] == ""


def test_panel_save_persists_client_confirmed_review_with_confirmed_point_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = _review(
        source_path="artifacts/learning/confirmed-point.json",
        signature="confirmed-point",
        summary="Confirmed point metadata",
        screenshot_path="artifacts/screenshots/confirmed-point.png",
    )
    _mark_reviewed_and_agent_readable(source)
    source["draft"]["content_descriptors"][0].update(
        {
            "agent_usage": "identity_anchor",
            "read_policy": "on_interface_match",
        }
    )
    _write_review_evidence(tmp_path, source)
    review = build_interface_workflow_review(
        goal="Persist one explicitly reviewed interface",
        application_identity={"url": "https://confirmed-point.example.test/items"},
        draft_sources=[source],
    )
    node = review["nodes"][0]
    node["confirmed_point"] = {"x": 40, "y": 40}
    node["review_status"] = "human_approved"
    node["reviewed_by_human"] = True
    client_review = deepcopy(review)
    client_review["nodes"][0].pop("confirmed_point")
    client_revision = workflow_review_module.build_interface_node_review_revision(
        client_review,
        node_id=node["node_id"],
    )
    node["human_review_confirmation"] = {
        "contract_version": "interface_node_human_review_confirmation_v1",
        "revision": client_revision,
    }
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)

    response = TestClient(app).post(
        "/panel/save_interface_workflow_review",
        json={"review": review},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True, body
    saved_path = Path(body["data"]["path"])
    saved = json.loads(saved_path.read_text(encoding="utf-8"))
    assert body["data"]["saved_review"] == saved
    persisted_node = saved["nodes"][0]
    registry = load_interface_workflow_library_registry(project_root=tmp_path)
    record = registry["workflows"][body["data"]["workflow_id"]]
    context = load_interface_workflow_agent_context(
        project_root=tmp_path,
        application_identity_key="web:confirmed-point.example.test",
    )

    assert persisted_node["reviewed_by_human"] is True
    assert persisted_node["current_revision_hash"] == persisted_node["reviewed_revision_hash"]
    assert record["source_asset_sha256"] == hashlib.sha256(saved_path.read_bytes()).hexdigest()
    assert record["reviewed_node_revision_hashes"] == {
        persisted_node["node_id"]: persisted_node["reviewed_revision_hash"]
    }
    assert record["reviewed_node_evidence_sha256"][persisted_node["node_id"]]
    assert context["agent_ready"] is True
    assert context["agent_usable_interfaces"] == [{
        "workflow_id": body["data"]["workflow_id"],
        "interface_id": persisted_node["node_id"],
        "display_name": "Confirmed point metadata",
        "agent_usable": True,
    }]

    evidence_path = tmp_path / persisted_node["evidence"]["source_screenshot_path"]
    evidence_path.write_bytes(b"changed-after-human-approval")
    stale_context = load_interface_workflow_agent_context(
        project_root=tmp_path,
        application_identity_key="web:confirmed-point.example.test",
    )

    assert stale_context["agent_ready"] is False
    assert stale_context["agent_usable_interfaces"] == []
    assert stale_context["blocked_interfaces"][0]["reason"] == (
        "human_review_revision_mismatch"
    )


def _save_durably_confirmed_workflow(tmp_path: Path, *, host: str) -> tuple[dict, dict]:
    source = _review(
        source_path=f"artifacts/learning/{host}.json",
        signature=host,
        summary="Durably confirmed interface",
        screenshot_path=f"artifacts/screenshots/{host}.png",
    )
    _mark_reviewed_and_agent_readable(source)
    source["draft"]["content_descriptors"][0].update(
        {
            "agent_usage": "identity_anchor",
            "read_policy": "on_interface_match",
        }
    )
    _write_review_evidence(tmp_path, source)
    review = build_interface_workflow_review(
        goal="Confirm one durable interface",
        application_identity={"url": f"https://{host}.example.test/items"},
        draft_sources=[source],
    )
    _confirm_current_node_revision(review, review["nodes"][0])
    first_save = save_interface_workflow_review_candidate(review, project_root=tmp_path)
    materialized = json.loads(Path(first_save["path"]).read_text(encoding="utf-8"))
    _confirm_current_node_revision(materialized, materialized["nodes"][0])
    final_save = save_interface_workflow_review_candidate(
        materialized,
        project_root=tmp_path,
    )
    persisted = json.loads(Path(final_save["path"]).read_text(encoding="utf-8"))
    return final_save, persisted


def test_save_revalidates_human_confirmation_after_evidence_materialization(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = _review(
        source_path="artifacts/learning/materialization.json",
        signature="materialization",
        summary="Materialization revalidation",
        screenshot_path="artifacts/screenshots/materialization.png",
    )
    _mark_reviewed_and_agent_readable(source)
    _write_review_evidence(tmp_path, source)
    review = build_interface_workflow_review(
        goal="Revalidate after materialization",
        application_identity={"url": "https://materialization.example.test/items"},
        draft_sources=[source],
    )
    _confirm_current_node_revision(review, review["nodes"][0])
    original_materialize = workflow_review_module._materialize_durable_node_evidence

    def materialize_with_semantic_change(*args, **kwargs) -> None:
        original_materialize(*args, **kwargs)
        args[0][0]["manual_revision"] = {
            "semantic_description": "changed during materialization"
        }

    monkeypatch.setattr(
        workflow_review_module,
        "_materialize_durable_node_evidence",
        materialize_with_semantic_change,
    )

    saved = save_interface_workflow_review_candidate(review, project_root=tmp_path)
    persisted = json.loads(Path(saved["path"]).read_text(encoding="utf-8"))

    assert persisted["nodes"][0]["reviewed_by_human"] is False
    assert persisted["nodes"][0]["review_status"] == "needs_human_review"
    assert persisted["nodes"][0]["reviewed_revision_hash"] == ""


def test_tampered_evidence_stays_blocked_after_panel_save_refresh(
    tmp_path: Path,
    monkeypatch,
) -> None:
    saved, persisted = _save_durably_confirmed_workflow(
        tmp_path,
        host="refresh-tampered",
    )
    node = persisted["nodes"][0]
    evidence_path = tmp_path / node["evidence"]["source_screenshot_path"]
    evidence_path.write_bytes(b"tampered-after-persisted-human-approval")
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)

    response = TestClient(app).post(
        "/panel/save_interface_workflow_review",
        json={"review": persisted},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True, body
    refreshed = json.loads(Path(body["data"]["path"]).read_text(encoding="utf-8"))
    context = load_interface_workflow_agent_context(
        project_root=tmp_path,
        application_identity_key="web:refresh-tampered.example.test",
    )

    assert refreshed["nodes"][0]["reviewed_by_human"] is False
    assert refreshed["nodes"][0]["review_status"] == "needs_human_review"
    assert context["agent_ready"] is False
    assert context["blocked_interfaces"][0]["reason"] == "human_review_required"
    assert saved["artifact_is_authorization"] is False


def test_registry_review_groups_match_agent_context_when_evidence_digest_is_tampered(
    tmp_path: Path,
) -> None:
    saved, persisted = _save_durably_confirmed_workflow(
        tmp_path,
        host="projection-tampered",
    )
    node = persisted["nodes"][0]
    evidence_path = tmp_path / node["evidence"]["source_screenshot_path"]
    expected_digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    registry = load_interface_workflow_library_registry(project_root=tmp_path)
    record = registry["workflows"][saved["workflow_id"]]

    assert record["reviewed_node_evidence_sha256"][node["node_id"]][
        "source_screenshot_path"
    ] == expected_digest

    evidence_path.write_bytes(b"tampered-registry-projection-evidence")
    registry_after_tamper = load_interface_workflow_library_registry(project_root=tmp_path)
    review_group = registry_after_tamper["workflows"][saved["workflow_id"]][
        "review_groups"
    ]["unreviewed"]
    context = load_interface_workflow_agent_context(
        project_root=tmp_path,
        application_identity_key="web:projection-tampered.example.test",
    )

    assert review_group == [{
        "node_id": node["node_id"],
        "display_name": "Durably confirmed interface",
        "state_type": "unknown",
        "review_status": "human_approved",
        "reviewed_by_human": True,
        "agent_usable": False,
        "agent_eligibility_reason": "human_review_revision_mismatch",
        "editable_review_source_path": node["editable_review_source_path"],
        "source_paths": node["source_paths"],
    }]
    assert registry_after_tamper["workflows"][saved["workflow_id"]]["review_groups"][
        "reviewed"
    ] == []
    assert context["agent_ready"] is False
    assert context["agent_usable_interfaces"] == []
    assert context["blocked_interfaces"][0]["reason"] == review_group[0][
        "agent_eligibility_reason"
    ]


def test_interface_review_eligibility_rejects_projection_error() -> None:
    result = project_interface_review_eligibility(
        {"review_status": "human_approved", "reviewed_by_human": True},
        projection_error="stale_fixture",
    )

    assert result == {
        "review_bucket": "unreviewed",
        "agent_usable": False,
        "agent_eligibility_reason": "stale_fixture",
    }


def test_pending_hierarchy_integrity_revalidation_blocks_agent_use(tmp_path: Path) -> None:
    source = _review(
        source_path="artifacts/learning/ambiguous.json",
        signature="ambiguous-hierarchy",
        summary="Ambiguous hierarchy",
        screenshot_path="artifacts/screenshots/ambiguous.png",
    )
    source["draft"]["page_details"]["hierarchy_ownership_review"] = {
        "contract_version": "hierarchy_ownership_review_revision_v1",
        "status": "corrected_needs_integrity_revalidation",
        "integrity_revalidation_status": "pending",
        "canonical_revision_sha256": "canonical-review-sha",
        "agent_usable": False,
        "reviewed_by_human": True,
    }
    review = build_interface_workflow_review(
        goal="Review ambiguous hierarchy",
        application_identity={"url": "https://hierarchy.example.test"},
        draft_sources=[source],
    )
    node = review["nodes"][0]
    _confirm_current_node_revision(review, node)

    saved = save_interface_workflow_review_candidate(review, project_root=tmp_path)
    payload = json.loads(Path(saved["path"]).read_text(encoding="utf-8"))
    persisted_node = payload["nodes"][0]
    context = load_interface_workflow_agent_context(
        project_root=tmp_path,
        application_identity_key="web:hierarchy.example.test",
    )

    assert persisted_node["hierarchy_ownership_review"]["integrity_revalidation_status"] == "pending"
    assert persisted_node["reviewed_by_human"] is True
    assert context["agent_ready"] is False
    assert context["agent_usable_interfaces"] == []
    assert context["blocked_interfaces"][0]["reason"] == "hierarchy_integrity_revalidation_required"


def test_save_workflow_review_candidate_rejects_unknown_contract(
    tmp_path: Path,
) -> None:
    try:
        save_interface_workflow_review_candidate(
            {"contract_version": "unknown_contract"},
            project_root=tmp_path,
        )
    except ValueError as exc:
        assert "single_application_workflow_review_v1" in str(exc)
    else:
        raise AssertionError("unknown workflow review contract must be rejected")


def test_panel_saves_reviewed_workflow_without_publishing_memory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    review = build_interface_workflow_review(
        goal="Review settings",
        application_identity={"name": "ExampleApp"},
        draft_sources=[
            _review(
                source_path="artifacts/learning/a.json",
                signature="settings",
                summary="Settings",
                screenshot_path="artifacts/screenshots/settings.png",
            )
        ],
    )
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)

    response = TestClient(app).post(
        "/panel/save_interface_workflow_review",
        json={"review": review},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert Path(payload["data"]["path"]).exists()
    assert payload["data"]["published"] is False
    assert payload["data"]["artifact_is_authorization"] is False
    assert payload["data"]["interface_asset_projection"]["status"] == "saved"
    assert payload["data"]["interface_asset_projection"]["saved_interface_count"] == 1
    assert Path(
        tmp_path,
        payload["data"]["interface_asset_projection"]["graph_result"]["graph_path"],
    ).is_file()


def test_panel_saves_empty_workflow_before_first_interface_is_attached(
    tmp_path: Path,
    monkeypatch,
) -> None:
    review = build_interface_workflow_review(
        goal="学习新闻网站流程",
        application_identity={"url": "https://www.example.test"},
        draft_sources=[],
    )
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)

    response = TestClient(app).post(
        "/panel/save_interface_workflow_review",
        json={"review": review},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert Path(payload["data"]["path"]).exists()
    assert payload["data"]["node_count"] == 0
    assert payload["data"]["interface_asset_projection"] == {
        "status": "not_covered",
        "reason": "workflow_has_no_interface_nodes",
        "saved_interface_count": 0,
        "saved_transition_count": 0,
        "artifact_is_authorization": False,
    }


def test_delete_unreferenced_learning_evidence_removes_only_managed_file(
    tmp_path: Path,
) -> None:
    evidence_path = tmp_path / "artifacts" / "learning-runs" / "run-1" / "trial_result.json"
    sibling_path = evidence_path.parent / "source.png"
    evidence_path.parent.mkdir(parents=True)
    evidence_path.write_text('{"contract_version":"learning_trial_v1"}\n', encoding="utf-8")
    sibling_path.write_bytes(b"image")

    result = workflow_review_module.delete_learning_evidence(
        project_root=tmp_path,
        source_path=evidence_path,
    )

    assert result["deleted"] is True
    assert result["deleted_path"] == "artifacts/learning-runs/run-1/trial_result.json"
    assert not evidence_path.exists()
    assert sibling_path.exists()
    assert result["associated_files_preserved"] is True


def test_delete_learning_evidence_rejects_source_referenced_by_workflow(
    tmp_path: Path,
) -> None:
    evidence_path = tmp_path / "artifacts" / "learning-runs" / "run-1" / "trial_result.json"
    evidence_path.parent.mkdir(parents=True)
    evidence_path.write_text('{"contract_version":"learning_trial_v1"}\n', encoding="utf-8")
    review = build_interface_workflow_review(
        goal="Read one interface",
        application_identity={"name": "ExampleApp"},
        draft_sources=[
            _review(
                source_path=str(evidence_path),
                signature="home",
                summary="Home",
                screenshot_path="artifacts/screenshots/home.png",
            )
        ],
    )
    review["workflow"]["workflow_id"] = "workflow-using-evidence"
    save_interface_workflow_review_candidate(review, project_root=tmp_path)

    with pytest.raises(ValueError, match="workflow-using-evidence"):
        workflow_review_module.delete_learning_evidence(
            project_root=tmp_path,
            source_path=evidence_path,
        )

    assert evidence_path.exists()


def test_delete_learning_evidence_rejects_path_outside_managed_roots(
    tmp_path: Path,
) -> None:
    outside_path = tmp_path / "README.md"
    outside_path.write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError, match="managed learning evidence roots"):
        workflow_review_module.delete_learning_evidence(
            project_root=tmp_path,
            source_path=outside_path,
        )

    assert outside_path.exists()


def test_delete_interface_workflow_keeps_shared_single_interface_evidence(
    tmp_path: Path,
) -> None:
    evidence_path = tmp_path / "artifacts" / "learning-runs" / "shared" / "trial_result.json"
    evidence_path.parent.mkdir(parents=True)
    evidence_path.write_text('{"contract_version":"learning_trial_v1"}\n', encoding="utf-8")
    saved_paths: dict[str, Path] = {}
    for workflow_id in ("workflow-one", "workflow-two"):
        review = build_interface_workflow_review(
            goal=f"Review {workflow_id}",
            application_identity={"name": "ExampleApp"},
            draft_sources=[
                _review(
                    source_path=str(evidence_path),
                    signature=workflow_id,
                    summary=workflow_id,
                    screenshot_path="artifacts/screenshots/home.png",
                )
            ],
        )
        review["workflow"]["workflow_id"] = workflow_id
        saved = save_interface_workflow_review_candidate(review, project_root=tmp_path)
        saved_paths[workflow_id] = Path(saved["path"])

    result = workflow_review_module.delete_interface_workflow_review_candidate(
        project_root=tmp_path,
        workflow_id="workflow-one",
    )

    assert result["deleted"] is True
    assert result["single_interface_evidence_deleted"] is False
    assert not saved_paths["workflow-one"].exists()
    assert saved_paths["workflow-two"].exists()
    assert evidence_path.exists()
    registry = load_interface_workflow_library_registry(project_root=tmp_path)
    assert set(registry["workflows"]) == {"workflow-two"}
    application = next(iter(registry["applications"].values()))
    assert application["workflow_ids"] == ["workflow-two"]


def test_panel_delete_learning_evidence_endpoint_returns_auditable_result(
    tmp_path: Path,
    monkeypatch,
) -> None:
    evidence_path = tmp_path / "artifacts" / "learning-runs" / "run-1" / "trial_result.json"
    evidence_path.parent.mkdir(parents=True)
    evidence_path.write_text('{"contract_version":"learning_trial_v1"}\n', encoding="utf-8")
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)

    response = TestClient(app).post(
        "/panel/delete_learning_evidence",
        json={"source_path": str(evidence_path)},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["deleted"] is True
    assert payload["data"]["artifact_is_authorization"] is False
    assert payload["data"]["trace_path"]


def test_panel_delete_interface_workflow_endpoint_preserves_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    evidence_path = tmp_path / "artifacts" / "learning-runs" / "run-1" / "trial_result.json"
    evidence_path.parent.mkdir(parents=True)
    evidence_path.write_text('{"contract_version":"learning_trial_v1"}\n', encoding="utf-8")
    review = build_interface_workflow_review(
        goal="Read one interface",
        application_identity={"name": "ExampleApp"},
        draft_sources=[
            _review(
                source_path=str(evidence_path),
                signature="home",
                summary="Home",
                screenshot_path="artifacts/screenshots/home.png",
            )
        ],
    )
    review["workflow"]["workflow_id"] = "workflow-to-delete"
    save_interface_workflow_review_candidate(review, project_root=tmp_path)
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)

    response = TestClient(app).post(
        "/panel/delete_interface_workflow",
        json={"workflow_id": "workflow-to-delete"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["single_interface_evidence_deleted"] is False
    assert evidence_path.exists()


def test_save_workflow_review_candidate_accepts_valid_two_node_path(
    tmp_path: Path,
) -> None:
    review = build_interface_workflow_review(
        goal="Open an item and inspect details",
        application_identity={"name": "ExampleApp"},
        draft_sources=[
            _review(
                source_path="artifacts/learning/list.json",
                signature="list",
                summary="Item list",
                screenshot_path="artifacts/screenshots/list.png",
            ),
            _review(
                source_path="artifacts/learning/detail.json",
                signature="detail",
                summary="Item details",
                screenshot_path="artifacts/screenshots/detail.png",
            ),
        ],
    )

    result = save_interface_workflow_review_candidate(
        review,
        project_root=tmp_path,
    )

    assert result["node_count"] == 2
    assert result["edge_count"] == 1


def test_save_workflow_review_candidate_accepts_routine_agent_operation(
    tmp_path: Path,
) -> None:
    review = build_interface_workflow_review(
        goal="Open an item and inspect details",
        application_identity={"name": "ExampleApp"},
        draft_sources=[
            _review(
                source_path="artifacts/learning/list.json",
                signature="list",
                summary="Item list",
                screenshot_path="artifacts/screenshots/list.png",
            ),
            _review(
                source_path="artifacts/learning/detail.json",
                signature="detail",
                summary="Item details",
                screenshot_path="artifacts/screenshots/detail.png",
            ),
        ],
    )
    review["edges"][0].update(
        {
            "operation_id": "open_item_detail",
            "display_name": "Open item detail",
            "action_type": "open_detail",
            "target_control_id": "item_card_1",
            "risk_level": "low",
            "requires_user_confirmation": False,
        }
    )

    result = save_interface_workflow_review_candidate(
        review,
        project_root=tmp_path,
    )

    saved = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    edge = saved["edges"][0]
    assert edge["operation_id"] == "open_item_detail"
    assert edge["action_type"] == "open_detail"
    assert edge["target_control_id"] == "item_card_1"
    assert edge["risk_level"] == "low"
    assert edge["requires_user_confirmation"] is False
    assert edge["execute_binding_enabled"] is False


def test_save_workflow_review_candidate_accepts_open_modal_operation(
    tmp_path: Path,
) -> None:
    review = build_interface_workflow_review(
        goal="Open and inspect a policy dialog",
        application_identity={"name": "ExampleApp"},
        draft_sources=[
            _review(
                source_path="artifacts/learning/list.json",
                signature="list",
                summary="Item list",
                screenshot_path="artifacts/screenshots/list.png",
            ),
            _review(
                source_path="artifacts/learning/policy.json",
                signature="policy",
                summary="Policy dialog",
                screenshot_path="artifacts/screenshots/policy.png",
            ),
        ],
    )
    review["edges"][0].update(
        {
            "operation_id": "open_policy_modal",
            "display_name": "Open policy dialog",
            "action_type": "open_modal",
            "target_control_id": "policy_button",
            "risk_level": "low",
            "requires_user_confirmation": False,
        }
    )

    result = save_interface_workflow_review_candidate(
        review,
        project_root=tmp_path,
    )

    saved = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    assert saved["edges"][0]["action_type"] == "open_modal"


def test_save_workflow_review_candidate_accepts_multiple_operations_from_one_interface(
    tmp_path: Path,
) -> None:
    review = build_interface_workflow_review(
        goal="Choose one of several actions from the same interface",
        application_identity={"name": "ExampleApp"},
        draft_sources=[
            _review(
                source_path="artifacts/learning/home.json",
                signature="home",
                summary="Home",
                screenshot_path="artifacts/screenshots/home.png",
            ),
            _review(
                source_path="artifacts/learning/detail.json",
                signature="detail",
                summary="Item details",
                screenshot_path="artifacts/screenshots/detail.png",
            ),
            _review(
                source_path="artifacts/learning/filter.json",
                signature="filter",
                summary="Filter panel",
                screenshot_path="artifacts/screenshots/filter.png",
            ),
        ],
    )
    source_node_id = review["nodes"][0]["node_id"]
    detail_node_id = review["nodes"][1]["node_id"]
    filter_node_id = review["nodes"][2]["node_id"]
    review["edges"] = [
        {
            **review["edges"][0],
            "edge_id": "edge_open_detail",
            "operation_id": "open_detail",
            "display_name": "Open item details",
            "source_node_id": source_node_id,
            "target_node_id": detail_node_id,
            "action_type": "open_detail",
            "target_control_id": "item_card",
        },
        {
            **review["edges"][1],
            "edge_id": "edge_open_filter",
            "operation_id": "open_filter",
            "display_name": "Open filters",
            "source_node_id": source_node_id,
            "target_node_id": filter_node_id,
            "action_type": "open_detail",
            "target_control_id": "filter_button",
        },
    ]
    review["workflow"]["edge_ids"] = [
        "edge_open_detail",
        "edge_open_filter",
    ]

    result = save_interface_workflow_review_candidate(
        review,
        project_root=tmp_path,
    )

    saved = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    assert result["edge_count"] == 2
    assert {edge["source_node_id"] for edge in saved["edges"]} == {source_node_id}
    assert {edge["target_node_id"] for edge in saved["edges"]} == {
        detail_node_id,
        filter_node_id,
    }
    assert saved["artifact_is_authorization"] is False
    assert all(edge["execute_binding_enabled"] is False for edge in saved["edges"])


@pytest.mark.parametrize(
    "action_type",
    ["final_submit", "submit", "send", "confirm", "payment", "delete"],
)
def test_save_workflow_review_candidate_rejects_forbidden_operation(
    action_type: str,
    tmp_path: Path,
) -> None:
    review = build_interface_workflow_review(
        goal="Open an item and inspect details",
        application_identity={"name": "ExampleApp"},
        draft_sources=[
            _review(
                source_path="artifacts/learning/list.json",
                signature="list",
                summary="Item list",
                screenshot_path="artifacts/screenshots/list.png",
            ),
            _review(
                source_path="artifacts/learning/detail.json",
                signature="detail",
                summary="Item details",
                screenshot_path="artifacts/screenshots/detail.png",
            ),
        ],
    )
    review["edges"][0]["action_type"] = action_type

    with pytest.raises(ValueError, match="forbidden review action type"):
        save_interface_workflow_review_candidate(
            review,
            project_root=tmp_path,
        )


def test_save_workflow_review_candidate_rejects_dangling_transition(
    tmp_path: Path,
) -> None:
    review = build_interface_workflow_review(
        goal="Open an item and inspect details",
        application_identity={"name": "ExampleApp"},
        draft_sources=[
            _review(
                source_path="artifacts/learning/list.json",
                signature="list",
                summary="Item list",
                screenshot_path="artifacts/screenshots/list.png",
            ),
            _review(
                source_path="artifacts/learning/detail.json",
                signature="detail",
                summary="Item details",
                screenshot_path="artifacts/screenshots/detail.png",
            ),
        ],
    )
    review["edges"][0]["target_node_id"] = "missing_node"

    with pytest.raises(ValueError, match="unknown target node"):
        save_interface_workflow_review_candidate(
            review,
            project_root=tmp_path,
        )


def test_save_workflow_review_candidate_rejects_duplicate_nodes_and_missing_entry(
    tmp_path: Path,
) -> None:
    review = build_interface_workflow_review(
        goal="Review a screen",
        application_identity={"name": "ExampleApp"},
        draft_sources=[
            _review(
                source_path="artifacts/learning/screen.json",
                signature="screen",
                summary="Screen",
                screenshot_path="artifacts/screenshots/screen.png",
            )
        ],
    )
    review["nodes"].append(dict(review["nodes"][0]))

    with pytest.raises(ValueError, match="duplicate node_id"):
        save_interface_workflow_review_candidate(
            review,
            project_root=tmp_path,
        )

    review["nodes"].pop()
    review["workflow"]["entry_node_id"] = "missing_node"
    with pytest.raises(ValueError, match="entry_node_id"):
        save_interface_workflow_review_candidate(
            review,
            project_root=tmp_path,
        )
