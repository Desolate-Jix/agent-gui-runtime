from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image


def _write_reviewed_candidate(root: Path) -> Path:
    screenshot = root / "artifacts" / "screenshots" / "sample.png"
    screenshot.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (800, 600), "white").save(screenshot)
    screenshot_sha256 = hashlib.sha256(screenshot.read_bytes()).hexdigest()

    candidate = {
        "contract_version": "reviewed_template_candidate_v1",
        "reviewed_by_human": True,
        "review_status": "approved_as_assisted_template",
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "final_submit_forbidden": True,
        "source": {
            "source_path": "artifacts/learning-runs/sample/trial_result.json",
            "sha256": "a" * 64,
        },
        "draft": {
            "states": [
                {
                    "state_id": "search_page",
                    "name": "Search page",
                    "screen_summary": "A search form is visible.",
                }
            ],
            "regions": [
                {
                    "region_id": "search_input",
                    "label": "Search",
                    "role": "input",
                    "bbox": {"x": 100, "y": 80, "w": 320, "h": 42},
                    "source_section_id": "search_page",
                },
                {
                    "region_id": "search_button",
                    "label": "Search",
                    "role": "button",
                    "bbox": {"x": 430, "y": 80, "w": 90, "h": 42},
                    "source_section_id": "search_page",
                },
            ],
            "action_templates": [
                {
                    "action_template_id": "fill_search",
                    "label": "Fill search",
                    "semantic_action": "fill_field",
                    "target_region_id": "search_input",
                },
                {
                    "action_template_id": "submit_search",
                    "label": "Submit search",
                    "semantic_action": "click",
                    "target_region_id": "search_button",
                },
            ],
            "verification_rules": [
                {
                    "rule_id": "search_results_visible",
                    "type": "state_change",
                }
            ],
            "page_details": {
                "screen": {
                    "source_image_path": "artifacts/screenshots/sample.png",
                    "source_image_sha256": screenshot_sha256,
                    "width": 800,
                    "height": 600,
                }
            },
        },
        "audit": {
            "human_review_patch_revision": 3,
            "human_review_patch_path": "artifacts/learning-draft-review/sample/human_review_patch_v3.json",
        },
    }
    path = root / "artifacts" / "learning-draft-review" / "sample" / "reviewed_template_candidate.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _write_external_apply_region_candidate(root: Path) -> Path:
    source_path = _write_reviewed_candidate(root)
    candidate = json.loads(source_path.read_text(encoding="utf-8"))
    external_region = candidate["draft"]["regions"][1]
    external_region.update(
        {
            "region_id": "external_apply",
            "label": "Apply on company site",
            "description": "Leaves the current site to open the employer application.",
            "semantic_action": "open_external_apply",
            "action_type": "open_external_apply",
            "risk_level": "dangerous",
            "human_review": {"status": "approved"},
        }
    )
    candidate["draft"]["action_templates"] = [
        {
            "action_template_id": "review_external_apply",
            "label": "Apply on company site",
            "semantic_action": "read_only",
            "target_region_id": "external_apply",
        },
        {
            "action_template_id": "stale_fill_field",
            "label": "Display-only email field",
            "semantic_action": "fill_field",
            "target_region_id": "search_input",
        },
    ]
    source_path.write_text(
        json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return source_path


def test_publish_reviewed_candidate_creates_restart_loadable_agent_memory(tmp_path: Path) -> None:
    from app.agent.reviewed_interface_memory import ReviewedInterfaceMemoryStore

    source_path = _write_reviewed_candidate(tmp_path)
    store = ReviewedInterfaceMemoryStore(project_root=tmp_path)

    published = store.publish(
        source_path=source_path,
        interface_id="sample_search",
        expected_registry_revision=0,
    )

    restarted_store = ReviewedInterfaceMemoryStore(project_root=tmp_path)
    loaded = restarted_store.load_active("sample_search")

    assert published["status"] == "published"
    assert loaded["contract_version"] == "reviewed_interface_memory_v1"
    assert loaded["interface_id"] == "sample_search"
    assert loaded["source"]["reviewed_candidate_sha256"] == hashlib.sha256(source_path.read_bytes()).hexdigest()
    assert loaded["review"]["human_review_patch_revision"] == 3
    assert loaded["agent_usage"]["agent_consumable"] is True
    assert loaded["agent_usage"]["runtime_resolution_enabled"] is True
    assert loaded["artifact_is_authorization"] is False
    assert loaded["execute_binding_enabled"] is False


def test_publish_reviewed_candidate_accepts_full_screen_bbox_as_reference_viewport(tmp_path: Path) -> None:
    from app.agent.reviewed_interface_memory import ReviewedInterfaceMemoryStore

    source_path = _write_reviewed_candidate(tmp_path)
    candidate = json.loads(source_path.read_text(encoding="utf-8"))
    screen = candidate["draft"]["page_details"]["screen"]
    screen.pop("width")
    screen.pop("height")
    screen["bbox"] = {"x": 0, "y": 0, "w": 800, "h": 600}
    source_path.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    store = ReviewedInterfaceMemoryStore(project_root=tmp_path)
    store.publish(source_path=source_path, interface_id="sample_search", expected_registry_revision=0)

    loaded = store.load_active("sample_search")
    assert loaded["source"]["reference_viewport"] == {"width": 800, "height": 600}


def test_publish_projects_safe_human_reviewed_region_actions_only(tmp_path: Path) -> None:
    from app.agent.reviewed_interface_memory import ReviewedInterfaceMemoryStore

    source_path = _write_reviewed_candidate(tmp_path)
    candidate = json.loads(source_path.read_text(encoding="utf-8"))
    candidate["draft"]["action_templates"] = []
    job_region = candidate["draft"]["regions"][1]
    job_region.update(
        {
            "label": "Graduate job card",
            "description": "Open this in-site job detail only.",
            "semantic_action": "open_detail",
            "human_review": {"status": "approved"},
        }
    )
    candidate["draft"]["regions"].append(
        {
            "region_id": "final_submit",
            "label": "Submit application",
            "description": "Submit the completed application.",
            "role": "button",
            "bbox": {"x": 430, "y": 500, "w": 180, "h": 42},
            "semantic_action": "final_submit",
            "human_review": {"status": "approved"},
        }
    )
    source_path.write_text(
        json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    store = ReviewedInterfaceMemoryStore(project_root=tmp_path)
    store.publish(
        source_path=source_path,
        interface_id="seek_home",
        expected_registry_revision=0,
    )

    memory = store.load_active("seek_home")
    assert [action["source_action_template_id"] for action in memory["actions"]] == [
        "region_action_search_button"
    ]
    action = memory["actions"][0]
    assert action["semantic_action"] == "open_detail"
    assert action["danger_class"] == "low_risk"
    assert action["automatic_execution_allowed"] is True
    assert action["target_element_id"] == "seek_home::element::search_button"


def test_publish_projects_globally_approved_manual_open_apply_region_with_destination(
    tmp_path: Path,
) -> None:
    from app.agent.reviewed_interface_memory import ReviewedInterfaceMemoryStore

    source_path = _write_reviewed_candidate(tmp_path)
    candidate = json.loads(source_path.read_text(encoding="utf-8"))
    candidate["draft"]["action_templates"] = []
    candidate["draft"]["regions"] = [
        {
            "region_id": "manual_region_33",
            "label": "Quick apply",
            "role": "button",
            "bbox": {"x": 71, "y": 1173, "w": 143, "h": 47},
            "description": (
                "Opens the SEEK-hosted application flow for job 93615952 and stops before any form fill."
            ),
            "semantic_action": "open_apply_flow",
            "action_type": "open_apply_flow",
            "verification_rule": (
                "After click, active URL origin remains https://nz.seek.com, no new tab opens, "
                "and the application flow is visible. Stop before fill, upload, Continue, or final submit."
            ),
            "risk_level": "normal",
            "requires_human_review": True,
            "destination": {
                "kind": "url",
                "url": "https://nz.seek.com/job/93615952/apply?sol=demo",
            },
            "real_action_requires_gate": True,
        }
    ]
    source_path.write_text(
        json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    store = ReviewedInterfaceMemoryStore(project_root=tmp_path)
    store.publish(
        source_path=source_path,
        interface_id="seek_job_93615952_quick_apply_detail",
        expected_registry_revision=0,
    )

    memory = store.load_active("seek_job_93615952_quick_apply_detail")
    action = next(
        action
        for action in memory["actions"]
        if action["source_action_template_id"] == "region_action_manual_region_33"
    )
    assert action["semantic_action"] == "open_apply_flow"
    assert action["destination_url"] == "https://nz.seek.com/job/93615952/apply?sol=demo"
    assert action["danger_class"] == "low_risk"
    assert action["automatic_execution_allowed"] is True
    context = store.agent_context("seek_job_93615952_quick_apply_detail")
    assert [item["action_id"] for item in context["available_actions"]] == [
        action["action_id"]
    ]


def test_publish_projects_external_apply_region_as_explicit_blocked_action(tmp_path: Path) -> None:
    from app.agent.reviewed_interface_memory import ReviewedInterfaceMemoryStore

    source_path = _write_external_apply_region_candidate(tmp_path)
    store = ReviewedInterfaceMemoryStore(project_root=tmp_path)

    store.publish(source_path=source_path, interface_id="seek_detail", expected_registry_revision=0)

    memory = store.load_active("seek_detail")
    projected = next(
        action
        for action in memory["actions"]
        if action["source_action_template_id"] == "region_action_external_apply"
    )
    assert projected["semantic_action"] == "open_external_apply"
    assert projected["danger_class"] == "blocked_high_risk"
    assert projected["automatic_execution_allowed"] is False
    assert projected["target_element_id"] == "seek_detail::element::external_apply"


def test_agent_context_excludes_projected_external_apply_action(tmp_path: Path) -> None:
    from app.agent.reviewed_interface_memory import ReviewedInterfaceMemoryStore

    source_path = _write_external_apply_region_candidate(tmp_path)
    store = ReviewedInterfaceMemoryStore(project_root=tmp_path)
    store.publish(source_path=source_path, interface_id="seek_detail", expected_registry_revision=0)

    context = store.agent_context("seek_detail")

    assert context["available_actions"] == []


def test_agent_resolves_natural_language_goal_to_unique_low_risk_memory_action(tmp_path: Path) -> None:
    from app.agent.reviewed_interface_memory import ReviewedInterfaceMemoryStore

    source_path = _write_reviewed_candidate(tmp_path)
    store = ReviewedInterfaceMemoryStore(project_root=tmp_path)
    store.publish(source_path=source_path, interface_id="sample_search", expected_registry_revision=0)

    click_resolution = store.resolve_action_for_goal(
        interface_id="sample_search",
        goal="Click the Search button",
    )
    fill_resolution = store.resolve_action_for_goal(
        interface_id="sample_search",
        goal="Type keywords into the Search field",
    )

    assert click_resolution["status"] == "selected"
    assert click_resolution["action_id"] == "sample_search::action::submit_search"
    assert click_resolution["automatic_execution_allowed"] is True
    assert click_resolution["resolution_source"] == "deterministic_semantic_memory_match"
    assert fill_resolution["status"] == "selected"
    assert fill_resolution["action_id"] == "sample_search::action::fill_search"


def test_agent_rejects_ambiguous_natural_language_memory_action(tmp_path: Path) -> None:
    from app.agent.reviewed_interface_memory import ReviewedInterfaceMemoryStore

    source_path = _write_reviewed_candidate(tmp_path)
    store = ReviewedInterfaceMemoryStore(project_root=tmp_path)
    store.publish(source_path=source_path, interface_id="sample_search", expected_registry_revision=0)

    resolution = store.resolve_action_for_goal(
        interface_id="sample_search",
        goal="Search",
    )

    assert resolution["status"] == "ambiguous"
    assert resolution["action_id"] is None
    assert resolution["automatic_execution_allowed"] is False


def test_execution_failure_feedback_is_persisted_and_points_back_to_human_review(tmp_path: Path) -> None:
    from app.agent.reviewed_interface_memory import ReviewedInterfaceMemoryStore

    source_path = _write_reviewed_candidate(tmp_path)
    store = ReviewedInterfaceMemoryStore(project_root=tmp_path)
    store.publish(source_path=source_path, interface_id="sample_search", expected_registry_revision=0)

    feedback = store.record_execution_feedback(
        interface_id="sample_search",
        action_id="sample_search::action::submit_search",
        goal="Click the Search button",
        failure_category="current_surface_text_anchor_missing",
        failure_details={"required_text_anchors": ["Search"]},
        trace_path="logs/traces/actions/example.json",
    )

    feedback_path = tmp_path / feedback["feedback_path"]
    payload = json.loads(feedback_path.read_text(encoding="utf-8"))
    assert payload["contract_version"] == "operational_memory_execution_feedback_v1"
    assert payload["review_status"] == "needs_human_review"
    assert payload["review_target"]["reviewed_candidate_path"] == source_path.relative_to(tmp_path).as_posix()
    assert payload["review_target"]["source_action_template_id"] == "submit_search"
    assert payload["review_target"]["source_region_id"] == "search_button"
    assert payload["trace_path"] == "logs/traces/actions/example.json"


def test_published_memory_uses_stable_semantic_ids_without_old_click_coordinates(tmp_path: Path) -> None:
    from app.agent.reviewed_interface_memory import ReviewedInterfaceMemoryStore

    source_path = _write_reviewed_candidate(tmp_path)
    store = ReviewedInterfaceMemoryStore(project_root=tmp_path)
    store.publish(source_path=source_path, interface_id="sample_search", expected_registry_revision=0)

    memory = store.load_active("sample_search")
    elements = {item["source_region_id"]: item for item in memory["elements"]}
    actions = {item["source_action_template_id"]: item for item in memory["actions"]}

    assert elements["search_input"]["element_id"] == "sample_search::element::search_input"
    assert elements["search_button"]["element_id"] == "sample_search::element::search_button"
    assert elements["search_input"]["locator_profile"]["reference_bbox"] == {
        "x": 100,
        "y": 80,
        "w": 320,
        "h": 42,
    }
    assert elements["search_input"]["locator_profile"]["normalized_bbox"] == {
        "x": 0.125,
        "y": pytest.approx(0.133333, abs=0.000001),
        "w": 0.4,
        "h": 0.07,
    }
    assert actions["fill_search"]["target_element_id"] == "sample_search::element::search_input"
    assert actions["submit_search"]["target_element_id"] == "sample_search::element::search_button"

    serialized = json.dumps(memory, ensure_ascii=False)
    assert "selected_click_point" not in serialized
    assert "click_point" not in serialized
    assert "window_handle" not in serialized


def test_reviewed_memory_keeps_semantic_label_separate_from_visible_text_anchor(tmp_path: Path) -> None:
    from app.agent.reviewed_interface_memory import ReviewedInterfaceMemoryStore

    source_path = _write_reviewed_candidate(tmp_path)
    candidate = json.loads(source_path.read_text(encoding="utf-8"))
    apply_region = candidate["draft"]["regions"][1]
    apply_region["label"] = "Apply entry button"
    apply_region["observed_text"] = "Apply"
    source_path.write_text(
        json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    store = ReviewedInterfaceMemoryStore(project_root=tmp_path)
    store.publish(source_path=source_path, interface_id="sample_search", expected_registry_revision=0)

    memory = store.load_active("sample_search")
    element = next(item for item in memory["elements"] if item["source_region_id"] == "search_button")

    assert element["label"] == "Apply entry button"
    assert element["locator_profile"]["text_anchors"] == ["Apply"]
    assert element["locator_profile"]["visible_text_anchors"] == ["Apply"]
    assert element["locator_profile"]["text_anchor_source"] == "human_review_observed_text"


def test_publish_rejects_unreviewed_or_stale_screenshot_candidate(tmp_path: Path) -> None:
    from app.agent.reviewed_interface_memory import ReviewedInterfaceMemoryStore

    source_path = _write_reviewed_candidate(tmp_path)
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    payload["review_status"] = "needs_human_review"
    source_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    store = ReviewedInterfaceMemoryStore(project_root=tmp_path)
    with pytest.raises(ValueError, match="approved human review"):
        store.publish(source_path=source_path, interface_id="sample_search", expected_registry_revision=0)

    payload["review_status"] = "approved_as_assisted_template"
    source_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    screenshot = tmp_path / "artifacts" / "screenshots" / "sample.png"
    screenshot.write_bytes(b"changed-after-review")

    with pytest.raises(ValueError, match="screenshot checksum mismatch"):
        store.publish(source_path=source_path, interface_id="sample_search", expected_registry_revision=0)


def test_publish_uses_registry_revision_cas_and_preserves_previous_object(tmp_path: Path) -> None:
    from app.agent.reviewed_interface_memory import ReviewedInterfaceMemoryStore

    source_path = _write_reviewed_candidate(tmp_path)
    store = ReviewedInterfaceMemoryStore(project_root=tmp_path)
    first = store.publish(source_path=source_path, interface_id="sample_search", expected_registry_revision=0)

    with pytest.raises(ValueError, match="registry revision mismatch"):
        store.publish(source_path=source_path, interface_id="sample_search", expected_registry_revision=0)

    second = store.publish(source_path=source_path, interface_id="sample_search", expected_registry_revision=1)
    registry = store.registry()

    assert first["object_sha256"] == second["object_sha256"]
    assert registry["registry_revision"] == 2
    assert registry["active_by_interface"]["sample_search"] == second["object_sha256"]
    assert len(registry["events"]) == 2


def test_memory_api_publishes_loads_and_exposes_agent_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    from app.agent.reviewed_interface_memory import ReviewedInterfaceMemoryStore
    from app.main import app
    import app.api.memory as memory_api

    source_path = _write_reviewed_candidate(tmp_path)
    monkeypatch.setattr(
        memory_api,
        "memory_store",
        ReviewedInterfaceMemoryStore(project_root=tmp_path),
    )
    client = TestClient(app)

    publish_response = client.post(
        "/memory/reviewed_interfaces/publish",
        json={
            "source_path": str(source_path),
            "interface_id": "sample_search",
            "expected_registry_revision": 0,
        },
    )
    load_response = client.get("/memory/reviewed_interfaces/sample_search")
    context_response = client.get("/memory/reviewed_interfaces/sample_search/agent_context")

    assert publish_response.status_code == 200
    assert publish_response.json()["success"] is True
    assert load_response.json()["data"]["interface_id"] == "sample_search"
    context = context_response.json()["data"]
    assert context["contract_version"] == "agent_operational_memory_context_v1"
    assert context["interface_id"] == "sample_search"
    assert context["available_actions"][0]["target_element_id"].startswith("sample_search::element::")
    assert context["execution_contract"]["current_capture_required"] is True
    assert context["execution_contract"]["historical_coordinates_forbidden"] is True
    assert context["execution_contract"]["gate_required"] is True


def test_memory_api_reports_stale_registry_revision_as_structured_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    from app.agent.reviewed_interface_memory import ReviewedInterfaceMemoryStore
    from app.main import app
    import app.api.memory as memory_api

    source_path = _write_reviewed_candidate(tmp_path)
    monkeypatch.setattr(
        memory_api,
        "memory_store",
        ReviewedInterfaceMemoryStore(project_root=tmp_path),
    )
    client = TestClient(app)
    payload = {
        "source_path": str(source_path),
        "interface_id": "sample_search",
        "expected_registry_revision": 0,
    }
    assert client.post("/memory/reviewed_interfaces/publish", json=payload).json()["success"] is True

    stale = client.post("/memory/reviewed_interfaces/publish", json=payload).json()

    assert stale["success"] is False
    assert stale["error"]["code"] == "reviewed_interface_memory_publish_failed"
    assert "registry revision mismatch" in stale["error"]["details"]


def test_memory_action_seed_uses_current_capture_roi_and_forbids_historical_point_reuse(
    tmp_path: Path,
) -> None:
    from app.agent.reviewed_interface_memory import ReviewedInterfaceMemoryStore

    source_path = _write_reviewed_candidate(tmp_path)
    current_capture = tmp_path / "artifacts" / "screenshots" / "current.png"
    Image.new("RGB", (1600, 900), "white").save(current_capture)
    store = ReviewedInterfaceMemoryStore(project_root=tmp_path)
    store.publish(source_path=source_path, interface_id="sample_search", expected_registry_revision=0)

    seed = store.build_current_capture_action_seed(
        interface_id="sample_search",
        action_id="sample_search::action::submit_search",
        image_path=current_capture,
    )

    assert seed["contract_version"] == "seeded_candidate_v1"
    assert seed["stable_element_id"] == "sample_search::element::search_button"
    assert seed["bbox"] == {"x": 860, "y": 120, "w": 180, "h": 63}
    assert seed["click_point"] == {"x": 950, "y": 152}
    assert seed["current_capture"]["viewport_size"] == {"width": 1600, "height": 900}
    assert seed["current_capture"]["screenshot_sha256"] == hashlib.sha256(current_capture.read_bytes()).hexdigest()
    assert seed["current_capture"]["freshness"] == "current_capture"
    assert seed["require_current_grounding"] is True
    assert seed["historical_click_point_reused"] is False
    assert seed["risk_class"] == "safe_click_allowed"


def test_open_apply_flow_seed_preserves_reviewed_destination_for_navigation_guard(
    tmp_path: Path,
) -> None:
    from app.agent.reviewed_interface_memory import ReviewedInterfaceMemoryStore

    source_path = _write_reviewed_candidate(tmp_path)
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    payload["draft"]["action_templates"].append(
        {
            "action_template_id": "open_apply_flow",
            "label": "Apply",
            "semantic_action": "open_apply_flow",
            "target_region_id": "search_button",
            "destination": {"kind": "url", "url": "https://nz.seek.com/job/1/apply"},
        }
    )
    source_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    store = ReviewedInterfaceMemoryStore(project_root=tmp_path)
    store.publish(source_path=source_path, interface_id="seek_detail", expected_registry_revision=0)

    seed = store.build_current_capture_action_seed(
        interface_id="seek_detail",
        action_id="seek_detail::action::open_apply_flow",
        image_path=tmp_path / "artifacts" / "screenshots" / "sample.png",
    )

    assert seed["destination_url"] == "https://nz.seek.com/job/1/apply"


def test_memory_action_seed_rejects_high_risk_action_before_model_or_gate(
    tmp_path: Path,
) -> None:
    from app.agent.reviewed_interface_memory import ReviewedInterfaceMemoryStore

    source_path = _write_reviewed_candidate(tmp_path)
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    payload["draft"]["action_templates"].append(
        {
            "action_template_id": "final_submit",
            "label": "Submit application",
            "semantic_action": "final_submit",
            "target_region_id": "search_button",
        }
    )
    source_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    store = ReviewedInterfaceMemoryStore(project_root=tmp_path)
    store.publish(source_path=source_path, interface_id="sample_search", expected_registry_revision=0)

    with pytest.raises(ValueError, match="blocked high-risk"):
        store.build_current_capture_action_seed(
            interface_id="sample_search",
            action_id="sample_search::action::final_submit",
            image_path=tmp_path / "artifacts" / "screenshots" / "sample.png",
        )


def test_publish_blocks_external_apply_flow_from_automatic_execution(tmp_path: Path) -> None:
    from app.agent.reviewed_interface_memory import ReviewedInterfaceMemoryStore

    source_path = _write_reviewed_candidate(tmp_path)
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    payload["draft"]["action_templates"].append(
        {
            "action_template_id": "open_external_application",
            "label": "Apply on company site",
            "semantic_action": "open_external_apply",
            "target_region_id": "search_button",
        }
    )
    source_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    store = ReviewedInterfaceMemoryStore(project_root=tmp_path)

    store.publish(source_path=source_path, interface_id="sample_search", expected_registry_revision=0)

    memory = store.load_active("sample_search")
    action = next(
        item
        for item in memory["actions"]
        if item["source_action_template_id"] == "open_external_application"
    )
    assert action["semantic_action"] == "open_external_apply"
    assert action["danger_class"] == "blocked_high_risk"
    assert action["automatic_execution_allowed"] is False


@pytest.mark.parametrize(
    ("action_id", "label"),
    [
        ("submit_application", "Submit application"),
        ("send_application", "Send application"),
        ("complete_application", "Complete"),
        ("confirm_application", "Confirm"),
        ("delete_record", "Delete record"),
        ("make_payment", "Make payment"),
    ],
)
def test_memory_action_seed_rejects_high_risk_click_labels(
    tmp_path: Path,
    action_id: str,
    label: str,
) -> None:
    from app.agent.reviewed_interface_memory import ReviewedInterfaceMemoryStore

    source_path = _write_reviewed_candidate(tmp_path)
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    payload["draft"]["action_templates"].append(
        {
            "action_template_id": action_id,
            "label": label,
            "semantic_action": "click",
            "target_region_id": "search_button",
        }
    )
    source_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    store = ReviewedInterfaceMemoryStore(project_root=tmp_path)
    store.publish(source_path=source_path, interface_id="sample_search", expected_registry_revision=0)

    with pytest.raises(ValueError, match="blocked high-risk"):
        store.build_current_capture_action_seed(
            interface_id="sample_search",
            action_id=f"sample_search::action::{action_id}",
            image_path=tmp_path / "artifacts" / "screenshots" / "sample.png",
        )


def test_publish_accepts_real_review_candidate_nested_screen_size_contract(
    tmp_path: Path,
) -> None:
    from app.agent.reviewed_interface_memory import ReviewedInterfaceMemoryStore

    source_path = _write_reviewed_candidate(tmp_path)
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    screen = payload["draft"]["page_details"]["screen"]
    screen["screen_size"] = {
        "width": screen.pop("width"),
        "height": screen.pop("height"),
    }
    source_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    store = ReviewedInterfaceMemoryStore(project_root=tmp_path)
    published = store.publish(
        source_path=source_path,
        interface_id="sample_search",
        expected_registry_revision=0,
    )

    assert published["status"] == "published"
    assert store.load_active("sample_search")["source"]["reference_viewport"] == {
        "width": 800,
        "height": 600,
    }
