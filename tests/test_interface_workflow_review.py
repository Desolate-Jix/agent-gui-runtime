from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import panel as panel_api
from app.main import app
from app.learn.interface_workflow_review import (
    build_interface_workflow_review,
    load_interface_workflow_agent_context,
    load_interface_workflow_library_registry,
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
    review = build_interface_workflow_review(
        goal="Open an item and inspect details",
        application_identity={
            "process": "msedge.exe",
            "url": "https://app.example.com/items",
        },
        draft_sources=[
            _review(
                source_path="artifacts/learning/items.json",
                signature="items",
                summary="Items",
                screenshot_path="artifacts/screenshots/items.png",
            )
        ],
    )
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
    assert context["agent_evidence_workflows"][0]["interfaces"][0]["readiness"]["status"] == "needs_human_review"
    assert context["execution_contract"]["historical_coordinates_forbidden"] is True
    assert context["execution_contract"]["fresh_grounding_required"] is True
    assert context["artifact_is_authorization"] is False


def test_agent_facing_workflow_registry_route_is_available() -> None:
    response = TestClient(app).get("/memory/interface_workflows/registry")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["contract_version"] == "interface_workflow_library_registry_v1"
    assert payload["data"]["artifact_is_authorization"] is False


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
