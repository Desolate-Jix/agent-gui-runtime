from __future__ import annotations

import importlib.util
import json
from pathlib import Path


RUNNER_PATH = Path(__file__).resolve().parents[1] / "scripts" / "seek_mvp_traversal_runner.py"
spec = importlib.util.spec_from_file_location("seek_mvp_traversal_runner", RUNNER_PATH)
assert spec is not None and spec.loader is not None
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def _response(result: dict) -> dict:
    return {"success": True, "message": "ok", "data": {"result": result}, "error": None}


def _resize_response(payload: dict | None = None) -> dict:
    requested = payload or {"width": 2560, "height": 1400, "left": 0, "top": 0, "focus": True}
    width = int(requested.get("width") or 2560)
    height = int(requested.get("height") or 1400)
    return {
        "success": True,
        "message": "Bound window resized",
        "data": {
            "contract_version": "bound_window_resize_v1",
            "requested": requested,
            "after": {"rect": {"left": 0, "top": 0, "right": width, "bottom": height}},
        },
        "error": None,
    }


def _non_resize_endpoints(calls: list[tuple[str, dict]]) -> list[str]:
    return [endpoint for endpoint, _ in calls if endpoint != "/session/resize_bound_window"]


def _non_resize_calls(calls: list[tuple[str, dict]]) -> list[tuple[str, dict]]:
    return [(endpoint, payload) for endpoint, payload in calls if endpoint != "/session/resize_bound_window"]


def _resize_payloads(calls: list[tuple[str, dict]]) -> list[dict]:
    return [payload for endpoint, payload in calls if endpoint == "/session/resize_bound_window"]


def _cards_observation() -> dict:
    return {
        "contract_version": "screen_observation_v1",
        "trace_path": "logs/traces/vision/cards.json",
        "image_size": {"width": 1200, "height": 1000},
        "screen_inventory": {
            "contract_version": "screen_inventory_v1",
            "available_actions": [
                {
                    "id": "action_job_1",
                    "label": "Software Engineer (Test Systems)",
                    "bbox": {"x": 24, "y": 400, "w": 410, "h": 220},
                    "click_point": {"x": 220, "y": 510},
                }
            ],
            "page_elements": [
                {"id": "company", "text": "Quantifi Photonics", "bbox": {"x": 40, "y": 454, "w": 180, "h": 22}},
                {"id": "location", "text": "Rosedale, Auckland", "bbox": {"x": 40, "y": 488, "w": 180, "h": 22}},
                {"id": "work_type", "text": "Full time", "bbox": {"x": 40, "y": 522, "w": 100, "h": 22}},
            ],
            "cards": [
                {
                    "id": "card_job_1",
                    "label": "Software Engineer (Test Systems)",
                    "bbox": {"x": 24, "y": 400, "w": 410, "h": 220},
                    "primary_action_id": "action_job_1",
                    "child_action_ids": ["action_job_1"],
                    "child_page_element_ids": ["company", "location", "work_type"],
                }
            ],
        },
    }


def _empty_observation() -> dict:
    return {
        "contract_version": "screen_observation_v1",
        "trace_path": "logs/traces/vision/empty.json",
        "image_size": {"width": 2560, "height": 1400},
        "screen_inventory": {
            "contract_version": "screen_inventory_v1",
            "available_actions": [],
            "page_elements": [
                {"id": "footer", "text": "Job seekers", "bbox": {"x": 600, "y": 900, "w": 200, "h": 30}},
            ],
            "cards": [],
        },
    }


def _second_cards_observation() -> dict:
    payload = _cards_observation()
    inventory = payload["screen_inventory"]
    inventory["available_actions"][0] = {
        "id": "action_job_2",
        "label": "Senior Backend Developer",
        "bbox": {"x": 24, "y": 400, "w": 410, "h": 220},
        "click_point": {"x": 220, "y": 510},
    }
    inventory["page_elements"] = [
        {"id": "title2", "text": "Senior Backend Developer", "bbox": {"x": 40, "y": 454, "w": 220, "h": 22}},
        {"id": "company2", "text": "Example Systems", "bbox": {"x": 40, "y": 488, "w": 180, "h": 22}},
        {"id": "location2", "text": "Auckland CBD, Auckland", "bbox": {"x": 40, "y": 522, "w": 220, "h": 22}},
    ]
    inventory["cards"][0] = {
        "id": "card_job_2",
        "label": "Job listing",
        "bbox": {"x": 24, "y": 400, "w": 410, "h": 220},
        "primary_action_id": "action_job_2",
        "child_action_ids": ["action_job_2"],
        "child_page_element_ids": ["title2", "company2", "location2"],
    }
    return payload


def _detail_observation(
    *,
    include_responsibilities: bool,
    include_requirements: bool = True,
    detail_bottom_reached: bool = True,
) -> dict:
    page_elements = [
        {"id": "title", "text": "Software Engineer (Test Systems)", "bbox": {"x": 520, "y": 440, "w": 380, "h": 34}},
        {"id": "company", "text": "Quantifi Photonics", "bbox": {"x": 520, "y": 490, "w": 220, "h": 24}},
        {"id": "location", "text": "Rosedale, Auckland", "bbox": {"x": 520, "y": 535, "w": 220, "h": 24}},
        {"id": "work_type", "text": "Full time", "bbox": {"x": 520, "y": 580, "w": 140, "h": 24}},
    ]
    if include_requirements:
        page_elements.append(
            {
            "id": "requirements",
            "text": "Requirements: C# programming experience and test automation skills.",
            "bbox": {"x": 520, "y": 700, "w": 560, "h": 40},
            }
        )
    if include_responsibilities:
        page_elements.append(
            {
                "id": "responsibilities",
                "text": "You will build and support test systems for photonics products.",
                "bbox": {"x": 520, "y": 760, "w": 560, "h": 40},
            }
        )
    return {
        "contract_version": "screen_observation_v1",
        "trace_path": "logs/traces/vision/detail-complete.json" if include_responsibilities else "logs/traces/vision/detail-first.json",
        "image_size": {"width": 1200, "height": 1000},
        "screen_inventory": {
            "contract_version": "screen_inventory_v1",
            "available_actions": [
                {
                    "id": "apply",
                    "label": "Apply",
                    "bbox": {"x": 520, "y": 820, "w": 110, "h": 48},
                    "click_point": {"x": 575, "y": 844},
                },
                {
                    "id": "save",
                    "label": "Save",
                    "bbox": {"x": 650, "y": 820, "w": 88, "h": 48},
                    "click_point": {"x": 694, "y": 844},
                },
            ],
            "page_elements": page_elements,
            "cards": [
                {
                    "id": "left_card_job_1",
                    "label": "Software Engineer (Test Systems)",
                    "bbox": {"x": 24, "y": 400, "w": 410, "h": 220},
                    "primary_action_id": None,
                    "child_action_ids": [],
                    "child_page_element_ids": ["title", "company", "location"],
                }
            ],
        },
        "detail_bottom_reached": detail_bottom_reached,
    }


def _company_page_observation() -> dict:
    return {
        "contract_version": "screen_observation_v1",
        "trace_path": "logs/traces/vision/company-page.json",
        "image_size": {"width": 1200, "height": 1000},
        "screen_inventory": {
            "contract_version": "screen_inventory_v1",
            "available_actions": [],
            "page_elements": [
                {"id": "related", "text": "Related resources", "bbox": {"x": 40, "y": 240, "w": 180, "h": 24}},
                {"id": "job_seekers", "text": "Job seekers", "bbox": {"x": 40, "y": 390, "w": 150, "h": 24}},
                {"id": "about", "text": "About SEEK", "bbox": {"x": 620, "y": 440, "w": 150, "h": 24}},
            ],
            "cards": [],
        },
    }


def _second_detail_observation() -> dict:
    payload = _detail_observation(include_responsibilities=True)
    inventory = payload["screen_inventory"]
    inventory["page_elements"][0] = {
        "id": "title",
        "text": "Senior Backend Developer",
        "bbox": {"x": 520, "y": 440, "w": 380, "h": 34},
    }
    inventory["page_elements"][1] = {
        "id": "company",
        "text": "Example Systems",
        "bbox": {"x": 520, "y": 490, "w": 220, "h": 24},
    }
    inventory["page_elements"][2] = {
        "id": "location",
        "text": "Auckland CBD, Auckland",
        "bbox": {"x": 520, "y": 535, "w": 220, "h": 24},
    }
    payload["trace_path"] = "logs/traces/vision/second-detail.json"
    return payload


def _apply_flow_observation() -> dict:
    return {
        "contract_version": "screen_observation_v1",
        "trace_path": "logs/traces/vision/apply-flow.json",
        "image_size": {"width": 1200, "height": 1000},
        "screen_inventory": {
            "contract_version": "screen_inventory_v1",
            "available_actions": [
                {
                    "id": "save_draft",
                    "label": "Save draft",
                    "bbox": {"x": 700, "y": 840, "w": 120, "h": 44},
                    "click_point": {"x": 760, "y": 862},
                }
            ],
            "page_elements": [
                {"id": "apply_header", "text": "Apply with SEEK", "bbox": {"x": 520, "y": 200, "w": 220, "h": 32}},
                {"id": "cover_letter", "text": "Cover letter", "bbox": {"x": 520, "y": 420, "w": 160, "h": 28}},
            ],
            "cards": [],
        },
    }


def _third_party_ats_observation() -> dict:
    payload = _apply_flow_observation()
    payload["trace_path"] = "logs/traces/vision/workday-apply-flow.json"
    payload["screen_inventory"]["available_actions"] = [{"id": "workday_apply", "label": "Apply"}]
    payload["screen_inventory"]["page_elements"] = [
        {"id": "vendor", "text": "Workday", "bbox": {"x": 520, "y": 180, "w": 120, "h": 32}},
        {"id": "title", "text": "Software Developer, Advisor", "bbox": {"x": 520, "y": 240, "w": 320, "h": 32}},
        {"id": "company", "text": "Fiserv careers", "bbox": {"x": 520, "y": 300, "w": 220, "h": 28}},
    ]
    return payload


def _final_submit_guard(*, enabled: bool) -> dict:
    return {
        "contract_version": "final_submit_guard_v1",
        "enabled": enabled,
        "allowed": True,
        "selected_candidate_id": "apply" if enabled else "job_card",
        "selected_texts": ["Apply"] if enabled else ["Software Engineer (Test Systems)"],
        "matched_terms": [],
        "reason": "no_final_submit_candidate_detected" if enabled else "guard_disabled",
    }


def _dry_response(*, final_submit_guard_enabled: bool = False) -> dict:
    return _response(
        {
            "approved_plan_id": "approved-job-1",
            "trace_path": "logs/traces/actions/dry.json",
            "final_submit_guard": _final_submit_guard(enabled=final_submit_guard_enabled),
            "agent_step_result": {
                "status": "dry_run_ready",
                "approved_plan_id": "approved-job-1",
                "selected_click_point": {"x": 220, "y": 510},
                "evidence": {
                    "recognition_plan_trace_path": "logs/traces/vision/plan.json",
                    "coordinate_overlay_path": "artifacts/review-overlays/plan.png",
                },
            },
            "pre_click_decision": {"allowed": True},
        }
    )


def _execute_response(*, final_submit_guard_enabled: bool = False) -> dict:
    return _response(
        {
            "trace_path": "logs/traces/actions/click.json",
            "final_submit_guard": _final_submit_guard(enabled=final_submit_guard_enabled),
            "agent_step_result": {
                "status": "verified",
                "selected_click_point": {"x": 220, "y": 510},
                "evidence": {"action_trace_path": "logs/traces/actions/click.json"},
            },
        }
    )


def _scroll_response() -> dict:
    return _response(
        {
            "contract_version": "scroll_action_v2",
            "trace_path": "logs/traces/actions/scroll.json",
            "precondition_decision": {"allowed": True},
            "scroll_effect_validation": {"status": "changed"},
        }
    )


def test_execute_job_card_sends_seeded_candidate_metadata(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    def fake_post_json(_base_url, endpoint, payload, _timeout):
        calls.append((endpoint, payload))
        if endpoint == "/session/resize_bound_window":
            return _resize_response(payload)
        if endpoint == "/action/execute_recognition_plan" and payload.get("dry_run") is True:
            return _dry_response()
        if endpoint == "/action/execute_recognition_plan" and payload.get("dry_run") is False:
            return _execute_response()
        raise AssertionError(endpoint)

    monkeypatch.setattr(runner, "_post_json", fake_post_json)
    monkeypatch.setattr(
        runner,
        "_verify_post_click_job_detail",
        lambda base_url, *, app_name, job, timeout: {"ok": True, "detail_title": job["title"]},
    )

    result = runner._execute_job_card(
        "http://127.0.0.1:8000",
        app_name="msedge",
        job={
            "job_id": "job-1",
            "title": "Software Engineer",
            "company": "Example Co",
            "card_bbox": {"x": 24, "y": 400, "w": 410, "h": 220},
            "click_point": {"x": 220, "y": 510},
            "evidence": {"texts": ["Software Engineer", "Example Co", "Auckland"]},
        },
        execute_clicks=True,
        timeout=5,
    )

    assert result["opened"] is True
    assert _non_resize_endpoints(calls) == [
        "/action/execute_recognition_plan",
        "/action/execute_recognition_plan",
    ]
    for _, payload in calls:
        seed = payload["metadata"]["seeded_candidate"]
        assert seed["contract_version"] == "seeded_candidate_v1"
        assert seed["source"] == "seek_job_card_v1"
        assert seed["label"] == "Software Engineer | Example Co"
        assert seed["container_id"] == "seek:results_list"
        assert seed["bbox"] == {"x": 24, "y": 400, "w": 410, "h": 220}
        assert seed["click_point"] == {"x": 220, "y": 510}
        assert seed["safety"]["require_point_inside_seed_bbox"] is True


def test_execute_job_card_uses_learned_artifact_constraints(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []
    artifact = {
        "contract_version": "seek_learn_artifact_export_v1",
        "learned_app_profile": {
            "contract_version": "learned_app_profile_v1",
            "profile_id": "seek_search_results_detail_mvp_v1",
            "page_type": "seek_search_results_with_detail",
            "safety_policy": {"policy_id": "seek_final_submit_forbidden_v1", "final_submit": "forbidden"},
            "action_templates": [
                {
                    "action_id": "open_job_card",
                    "candidate_constraints": {
                        "required_container_id": "seek:results_list",
                        "use_seeded_candidate": True,
                    },
                    "verification_policy": {
                        "post_click": "detail_title_company_must_match_clicked_card",
                    },
                }
            ],
        },
    }

    def fake_post_json(_base_url, endpoint, payload, _timeout):
        calls.append((endpoint, payload))
        if endpoint == "/session/resize_bound_window":
            return _resize_response(payload)
        if endpoint == "/action/execute_recognition_plan" and payload.get("dry_run") is True:
            return _dry_response()
        if endpoint == "/action/execute_recognition_plan" and payload.get("dry_run") is False:
            return _execute_response()
        raise AssertionError(endpoint)

    monkeypatch.setattr(runner, "_post_json", fake_post_json)
    monkeypatch.setattr(
        runner,
        "_verify_post_click_job_detail",
        lambda base_url, *, app_name, job, timeout: {"ok": True, "detail_title": job["title"]},
    )

    result = runner._execute_job_card(
        "http://127.0.0.1:8000",
        app_name="msedge",
        job={
            "job_id": "job-1",
            "title": "Software Engineer",
            "company": "Example Co",
            "card_bbox": {"x": 24, "y": 400, "w": 410, "h": 220},
            "click_point": {"x": 220, "y": 510},
        },
        execute_clicks=True,
        timeout=5,
        learned_artifact=artifact,
    )

    assert result["opened"] is True
    for _, payload in calls:
        metadata = payload["metadata"]
        assert metadata["learned_app_profile_ref"]["profile_id"] == "seek_search_results_detail_mvp_v1"
        assert metadata["candidate_constraints"]["required_container_id"] == "seek:results_list"
        assert metadata["verification_policy"]["post_click"] == "detail_title_company_must_match_clicked_card"
        assert metadata["learned_safety_policy"]["final_submit"] == "forbidden"
        assert metadata["seeded_candidate"]["candidate_constraints"]["required_container_id"] == "seek:results_list"


def test_runner_opens_card_scrolls_detail_and_writes_report(tmp_path, monkeypatch) -> None:
    out_path = tmp_path / "seek-report.json"
    calls: list[tuple[str, dict]] = []
    observations = [
        _cards_observation(),
        _detail_observation(include_responsibilities=False, include_requirements=False, detail_bottom_reached=False),
        _detail_observation(include_responsibilities=False, include_requirements=False, detail_bottom_reached=False),
        _detail_observation(include_responsibilities=True),
    ]

    def fake_post(base_url, endpoint, payload, timeout):
        calls.append((endpoint, payload))
        if endpoint == "/session/resize_bound_window":
            return _resize_response(payload)
        if endpoint == "/apps/open":
            return {"success": True, "message": "opened", "data": {"bound": True}, "error": None}
        if endpoint == "/vision/observe_screen":
            return _response(observations.pop(0))
        if endpoint == "/action/execute_recognition_plan" and payload.get("dry_run") is True:
            return _dry_response(final_submit_guard_enabled=bool((payload.get("metadata") or {}).get("seek_apply_entry")))
        if endpoint == "/action/execute_recognition_plan" and payload.get("dry_run") is False:
            return _execute_response(final_submit_guard_enabled=bool((payload.get("metadata") or {}).get("seek_apply_entry")))
        if endpoint == "/action/scroll":
            assert payload["scroll_scope"] == "container"
            assert payload["target_pane"] == "job_detail"
            assert payload["target_container_id"] == "seek:job_detail"
            assert payload["dry_run"] is False
            return _scroll_response()
        raise AssertionError(f"unexpected endpoint {endpoint}")

    monkeypatch.setattr(runner, "_post_json", fake_post)

    code = runner.main(
        [
            "--out",
            str(out_path),
            "--max-jobs",
            "1",
            "--max-detail-scrolls",
            "2",
            "--execute-clicks",
        ]
    )

    assert code == 0
    endpoints = _non_resize_endpoints(calls)
    assert endpoints == [
        "/apps/open",
        "/vision/observe_screen",
        "/action/execute_recognition_plan",
        "/action/execute_recognition_plan",
        "/vision/observe_screen",
        "/vision/observe_screen",
        "/action/scroll",
        "/vision/observe_screen",
    ]
    assert _resize_payloads(calls)[0]["width"] == 2560
    assert _resize_payloads(calls)[0]["height"] == 1400
    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert report["contract_version"] == "seek_mvp_run_report_v1"
    assert report["mode"] == "no_apply_traversal"
    assert report["jobs_seen"] == 1
    assert report["jobs_opened"] == 1
    assert report["jobs_fully_read"] == 1
    assert report["final_submissions"] == 0
    assert len(report["job_archives"]) == 1
    job_archive = report["job_archives"][0]
    assert job_archive["decision"] == "need_user_review"
    archive_path = Path(job_archive["path"])
    assert archive_path.parent == tmp_path / "seek-report_job_archives"
    archive = json.loads(archive_path.read_text(encoding="utf-8"))
    assert archive["contract_version"] == "seek_job_archive_v1"
    assert archive["title"] == "Software Engineer (Test Systems)"
    assert archive["card"]["title"] == "Software Engineer (Test Systems)"
    assert archive["detail_read"]["complete"] is True
    assert archive["detail_read"]["read_container_id"] == "seek:job_detail"
    assert archive["detail_read"]["scroll_count"] == 1
    assert archive["match_decision"]["decision"] == "need_user_review"
    assert archive["safety"]["final_submission_performed"] is False
    assert report["candidate_profile_readiness"]["contract_version"] == "candidate_profile_readiness_v1"
    assert report["candidate_profile_readiness"]["decision"] == "blocked_need_real_candidate_profile"
    step = report["traversal_steps"][0]
    assert step["card_click"]["opened"] is True
    assert step["detail_read"]["completeness"]["complete"] is True
    assert step["detail_read"]["coordinate_strategy"] == "fixed_seek_job_detail_container_after_card_click"
    assert step["detail_read"]["read_container_id"] == "seek:job_detail"
    assert step["detail_read"]["uses_precise_relocation"] is False
    assert step["detail_read"]["scrolls"][0]["trace_path"] == "logs/traces/actions/scroll.json"
    assert step["detail_read"]["scrolls"][0]["scroll_scope"] == "container"
    assert step["detail_read"]["scrolls"][0]["target_pane"] == "job_detail"
    assert step["detail_read"]["scrolls"][0]["target_container_id"] == "seek:job_detail"
    assert [scroll["wheel_clicks"] for scroll in step["detail_read"]["scrolls"]] == [4]
    assert step["match_decision"]["decision"] == "need_user_review"
    assert step["match_decision"]["fit_summary"].startswith("need_user_review with score")
    assert step["match_decision"]["recommended_next_action"] == "ask_user_or_gpt_for_review"
    assert report["need_user_review"] == 1
    assert report["candidate_profile_loaded"] is False


def test_runner_stops_when_initial_observation_has_no_job_cards(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []
    observations = [_empty_observation()]

    def fake_post(base_url, endpoint, payload, timeout):
        calls.append((endpoint, payload))
        if endpoint == "/session/resize_bound_window":
            return _resize_response(payload)
        if endpoint == "/apps/open":
            return {"success": True, "message": "opened", "data": {"bound": True}, "error": None}
        if endpoint == "/vision/observe_screen":
            return _response(observations.pop(0))
        raise AssertionError(f"unexpected endpoint {endpoint}")

    monkeypatch.setattr(runner, "_post_json", fake_post)

    report = runner.run_traversal(
        base_url="http://runtime",
        app_name="edge",
        url="https://www.seek.co.nz/software-engineer-jobs/in-All-Auckland",
        max_jobs=5,
        max_detail_scrolls=2,
        max_results_scrolls=8,
        execute_clicks=True,
        timeout=10,
    )

    assert _non_resize_endpoints(calls) == ["/apps/open", "/vision/observe_screen"]
    assert report["jobs_seen"] == 0
    assert report["jobs_opened"] == 0
    assert report["results_list_scrolls"] == []
    assert report["stop_reason"] == "blocked_no_initial_job_cards"


def test_runner_resets_detail_pane_before_next_card_click(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []
    observations = [
        _cards_observation(),
        _detail_observation(include_responsibilities=True),
        _detail_observation(include_responsibilities=True),
        _second_cards_observation(),
        _second_detail_observation(),
        _second_detail_observation(),
    ]

    def fake_post(base_url, endpoint, payload, timeout):
        calls.append((endpoint, payload))
        if endpoint == "/session/resize_bound_window":
            return _resize_response(payload)
        if endpoint == "/apps/open":
            return {"success": True, "message": "opened", "data": {"bound": True}, "error": None}
        if endpoint == "/vision/observe_screen":
            return _response(observations.pop(0))
        if endpoint == "/action/execute_recognition_plan" and payload.get("dry_run") is True:
            return _dry_response()
        if endpoint == "/action/execute_recognition_plan" and payload.get("dry_run") is False:
            return _execute_response()
        if endpoint == "/action/scroll":
            return _scroll_response()
        raise AssertionError(f"unexpected endpoint {endpoint}")

    monkeypatch.setattr(runner, "_post_json", fake_post)

    report = runner.run_traversal(
        base_url="http://runtime",
        app_name="edge",
        url="https://www.seek.co.nz/software-engineer-jobs/in-All-Auckland",
        max_jobs=2,
        max_detail_scrolls=1,
        max_results_scrolls=1,
        execute_clicks=True,
        timeout=10,
    )

    scroll_payloads = [payload for endpoint, payload in calls if endpoint == "/action/scroll"]
    assert scroll_payloads[0]["target_container_id"] == "seek:results_list"
    assert scroll_payloads[0]["direction"] == "down"
    assert scroll_payloads[1]["target_container_id"] == "seek:job_detail"
    assert scroll_payloads[1]["direction"] == "up"
    assert scroll_payloads[1]["reason"] == "reset_seek_job_detail_before_next_card_click"
    assert report["jobs_opened"] == 2
    assert report["traversal_steps"][1]["pre_click_detail_reset"]["success"] is True
    assert report["traversal_steps"][1]["pre_click_detail_reset"]["attempted"] is True
    assert report["traversal_steps"][1]["pre_click_detail_reset"]["wrong_scope_detected"] is False
    assert report["accuracy_summary"]["post_click_layout_drift_count"] == 0
    assert report["accuracy_summary"]["pre_click_detail_reset_count"] == 1
    assert report["accuracy_summary"]["pre_click_detail_reset_wrong_scope_count"] == 0
    assert report["accuracy_summary"]["title_extraction_from_body_count"] == 0


def test_runner_does_not_open_detail_when_click_execution_disabled(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []
    observations = [_cards_observation()]

    def fake_post(base_url, endpoint, payload, timeout):
        calls.append((endpoint, payload))
        if endpoint == "/session/resize_bound_window":
            return _resize_response(payload)
        if endpoint == "/vision/observe_screen":
            return _response(observations.pop(0))
        if endpoint == "/action/execute_recognition_plan":
            assert payload["dry_run"] is True
            return _dry_response()
        raise AssertionError(f"unexpected endpoint {endpoint}")

    monkeypatch.setattr(runner, "_post_json", fake_post)

    report = runner.run_traversal(
        base_url="http://runtime",
        app_name="edge",
        url=None,
        max_jobs=1,
        max_detail_scrolls=1,
        execute_clicks=False,
        timeout=10,
    )

    assert _non_resize_endpoints(calls) == ["/vision/observe_screen", "/action/execute_recognition_plan"]
    assert report["jobs_seen"] == 1
    assert report["jobs_opened"] == 0
    assert report["traversal_steps"][0]["card_click"]["failure_reason"] == "execute_clicks_disabled"
    assert report["final_submissions"] == 0


def test_runner_scrolls_results_list_to_collect_more_jobs(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []
    observations = [_cards_observation(), _second_cards_observation()]

    def fake_post(base_url, endpoint, payload, timeout):
        calls.append((endpoint, payload))
        if endpoint == "/session/resize_bound_window":
            return _resize_response(payload)
        if endpoint == "/vision/observe_screen":
            return _response(observations.pop(0))
        if endpoint == "/action/execute_recognition_plan":
            assert payload["dry_run"] is True
            return _dry_response()
        if endpoint == "/action/scroll":
            assert payload["scroll_scope"] == "container"
            assert payload["target_pane"] == "results_list"
            assert payload["target_container_id"] == "seek:results_list"
            return _scroll_response()
        raise AssertionError(f"unexpected endpoint {endpoint}")

    monkeypatch.setattr(runner, "_post_json", fake_post)

    report = runner.run_traversal(
        base_url="http://runtime",
        app_name="edge",
        url=None,
        max_jobs=2,
        max_detail_scrolls=1,
        execute_clicks=False,
        timeout=10,
        max_results_scrolls=1,
    )

    assert _non_resize_endpoints(calls) == [
        "/vision/observe_screen",
        "/action/execute_recognition_plan",
        "/action/scroll",
        "/vision/observe_screen",
        "/action/execute_recognition_plan",
    ]
    assert report["jobs_seen"] == 2
    assert report["jobs_opened"] == 0
    assert len(report["results_list_scrolls"]) == 1
    assert report["results_list_scrolls"][0]["scroll_scope"] == "container"
    assert report["results_list_scrolls"][0]["target_pane"] == "results_list"
    assert report["results_list_scrolls"][0]["target_container_id"] == "seek:results_list"
    assert report["accuracy_summary"]["contract_version"] == "seek_mvp_accuracy_summary_v1"
    assert report["accuracy_summary"]["results_list_scroll_count"] == 1
    assert report["accuracy_summary"]["wrong_scope_scroll_count"] == 0
    assert report["accuracy_summary"]["status"] == "pass"
    assert [step["card"]["title"] for step in report["traversal_steps"]] == [
        "Software Engineer (Test Systems)",
        "Senior Backend Developer",
    ]


def test_scroll_results_list_uses_learned_artifact_target(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []
    artifact = {
        "contract_version": "learned_app_profile_v1",
        "profile_id": "seek_search_results_detail_mvp_v1",
        "page_type": "seek_search_results_with_detail",
        "action_templates": [
            {
                "action_id": "load_more_results",
                "scroll_target": {"target_pane": "results_list", "target_container_id": "seek:results_list"},
            }
        ],
    }

    def fake_post(base_url, endpoint, payload, timeout):
        calls.append((endpoint, payload))
        if endpoint == "/session/resize_bound_window":
            return _resize_response(payload)
        assert endpoint == "/action/scroll"
        return _scroll_response()

    monkeypatch.setattr(runner, "_post_json", fake_post)

    result = runner._scroll_results_list(
        "http://runtime",
        timeout=10,
        learned_artifact=artifact,
        container_bbox={"x": 612, "y": 350, "w": 460, "h": 720},
    )

    assert calls[0][1]["target_pane"] == "results_list"
    assert calls[0][1]["target_container_id"] == "seek:results_list"
    assert calls[0][1]["container_bbox"] == {"x": 612, "y": 350, "width": 460, "height": 720}
    assert result["learned_artifact_source"] == "learned_app_profile_v1"


def test_runner_continues_results_scroll_after_one_no_new_card_page(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []
    observations = [_cards_observation(), _cards_observation(), _second_cards_observation()]

    def fake_post(base_url, endpoint, payload, timeout):
        calls.append((endpoint, payload))
        if endpoint == "/session/resize_bound_window":
            return _resize_response(payload)
        if endpoint == "/vision/observe_screen":
            return _response(observations.pop(0))
        if endpoint == "/action/execute_recognition_plan":
            assert payload["dry_run"] is True
            return _dry_response()
        if endpoint == "/action/scroll":
            assert payload["target_container_id"] == "seek:results_list"
            return _scroll_response()
        raise AssertionError(f"unexpected endpoint {endpoint}")

    monkeypatch.setattr(runner, "_post_json", fake_post)

    report = runner.run_traversal(
        base_url="http://runtime",
        app_name="edge",
        url=None,
        max_jobs=2,
        max_detail_scrolls=1,
        execute_clicks=False,
        timeout=10,
        max_results_scrolls=2,
    )

    assert _non_resize_endpoints(calls) == [
        "/vision/observe_screen",
        "/action/execute_recognition_plan",
        "/action/scroll",
        "/vision/observe_screen",
        "/action/scroll",
        "/vision/observe_screen",
        "/action/execute_recognition_plan",
    ]
    assert [scroll["new_jobs_added"] for scroll in report["results_list_scrolls"]] == [0, 1]
    assert [scroll["wheel_clicks"] for scroll in report["results_list_scrolls"]] == [4, 8]
    assert report["jobs_seen"] == 2
    assert [step["card"]["title"] for step in report["traversal_steps"]] == [
        "Software Engineer (Test Systems)",
        "Senior Backend Developer",
    ]


def test_adaptive_wheel_clicks_increases_then_caps() -> None:
    assert runner._adaptive_wheel_clicks(base=4, repeated_observations=0) == 4
    assert runner._adaptive_wheel_clicks(base=4, repeated_observations=1) == 8
    assert runner._adaptive_wheel_clicks(base=4, repeated_observations=3) == 12


def test_detail_scroll_uses_scroll_count_to_increase_wheel_clicks(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []
    observations = [
        _detail_observation(include_responsibilities=False, include_requirements=False, detail_bottom_reached=False),
        _detail_observation(include_responsibilities=False, include_requirements=True, detail_bottom_reached=False),
        _detail_observation(include_responsibilities=False, include_requirements=True, detail_bottom_reached=False),
    ]

    def fake_post(base_url, endpoint, payload, timeout):
        calls.append((endpoint, payload))
        if endpoint == "/vision/observe_screen":
            return _response(observations.pop(0))
        if endpoint == "/action/scroll":
            return _scroll_response()
        raise AssertionError(endpoint)

    monkeypatch.setattr(runner, "_post_json", fake_post)

    result = runner._read_detail_until_complete(
        "http://runtime",
        app_name="edge",
        max_scrolls=2,
        timeout=10,
    )

    assert [payload["wheel_clicks"] for endpoint, payload in calls if endpoint == "/action/scroll"] == [4, 8]
    assert [payload["container_bbox"]["x"] for endpoint, payload in calls if endpoint == "/action/scroll"] == [484, 484]
    assert [scroll["wheel_clicks"] for scroll in result["scrolls"]] == [4, 8]
    assert result["completeness"]["stop_reason"] == "right_detail_no_progress_after_scroll"


def test_detail_scroll_stops_when_right_detail_does_not_change(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []
    observations = [
        _detail_observation(include_responsibilities=False, include_requirements=False, detail_bottom_reached=False),
        _detail_observation(include_responsibilities=False, include_requirements=False, detail_bottom_reached=False),
        _detail_observation(include_responsibilities=False, include_requirements=True, detail_bottom_reached=False),
    ]

    def fake_post(base_url, endpoint, payload, timeout):
        calls.append((endpoint, payload))
        if endpoint == "/vision/observe_screen":
            return _response(observations.pop(0))
        if endpoint == "/action/scroll":
            return _scroll_response()
        raise AssertionError(endpoint)

    monkeypatch.setattr(runner, "_post_json", fake_post)

    result = runner._read_detail_until_complete(
        "http://runtime",
        app_name="edge",
        max_scrolls=3,
        timeout=10,
    )

    scroll_payloads = [payload for endpoint, payload in calls if endpoint == "/action/scroll"]
    assert [payload["wheel_clicks"] for payload in scroll_payloads] == [4]
    assert scroll_payloads[0]["target_container_id"] == "seek:job_detail"
    assert scroll_payloads[0]["container_bbox"]["x"] == 484
    assert result["scrolls"][0]["right_detail_no_progress_after_scroll"] is True
    assert result["scrolls"][0]["adaptive_stop_reason"] == "right_detail_content_unchanged_after_scroll"
    assert result["completeness"]["should_scroll"] is False
    assert result["completeness"]["stop_reason"] == "right_detail_no_progress_after_scroll"


def test_runner_scores_profile_and_saves_suitable_job(tmp_path, monkeypatch) -> None:
    out_path = tmp_path / "seek-report.json"
    saved_dir = tmp_path / "saved-jobs"
    profile_path = tmp_path / "candidate.json"
    profile_path.write_text(
        json.dumps(
            {
                "contract_version": "candidate_profile_v1",
                "profile_source": "real_user_candidate_profile_v1",
                "profile_purpose": "real_resume_profile",
                "candidate_name": "Alex Chen",
                "email": "alex@example.com",
                "phone": "+64 21 555 0123",
                "experience_summary": ["Built production-style C# and test automation projects."],
                "skills": ["C#", "test automation", "photonics"],
                "target_roles": ["Software Engineer"],
                "location_constraints": ["Auckland"],
                "work_rights_summary": "Open work rights in New Zealand.",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    observations = [
        _cards_observation(),
        _detail_observation(include_responsibilities=True),
        _detail_observation(include_responsibilities=True),
    ]

    def fake_post(base_url, endpoint, payload, timeout):
        if endpoint == "/session/resize_bound_window":
            return _resize_response(payload)
        if endpoint == "/apps/open":
            return {"success": True, "message": "opened", "data": {"bound": True}, "error": None}
        if endpoint == "/vision/observe_screen":
            return _response(observations.pop(0))
        if endpoint == "/action/execute_recognition_plan" and payload.get("dry_run") is True:
            return _dry_response(final_submit_guard_enabled=bool((payload.get("metadata") or {}).get("seek_apply_entry")))
        if endpoint == "/action/execute_recognition_plan" and payload.get("dry_run") is False:
            return _execute_response(final_submit_guard_enabled=bool((payload.get("metadata") or {}).get("seek_apply_entry")))
        raise AssertionError(f"unexpected endpoint {endpoint}")

    monkeypatch.setattr(runner, "_post_json", fake_post)

    code = runner.main(
        [
            "--out",
            str(out_path),
            "--saved-jobs-dir",
            str(saved_dir),
            "--candidate-profile",
            str(profile_path),
            "--max-jobs",
            "1",
            "--max-detail-scrolls",
            "1",
            "--execute-clicks",
        ]
    )

    assert code == 0
    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert report["candidate_profile_loaded"] is True
    assert report["strong_apply"] == 1
    assert report["saved_jobs"]
    saved_path = Path(report["saved_jobs"][0]["path"])
    assert saved_path.exists()
    saved = json.loads(saved_path.read_text(encoding="utf-8"))
    assert saved["contract_version"] == "saved_seek_job_record_v1"
    assert saved["decision"]["decision"] == "strong_apply"
    trace_path = Path(report["traversal_trace_path"])
    assert trace_path.exists()
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    assert trace["contract_version"] == "seek_mvp_traversal_trace_v1"
    assert trace["summary"]["jobs_seen"] == report["jobs_seen"]
    assert trace["summary"]["final_submissions"] == 0
    assert trace["traversal_events"][0]["card"]["title"] == "Software Engineer (Test Systems)"
    assert trace["traversal_events"][0]["detail_read"]["complete"] is True
    assert trace["traversal_events"][0]["match_decision"]["decision"] == "strong_apply"
    assert trace["safety"]["submit_clicks"] == 0
    assert trace["safety"]["final_submissions"] == 0
    report_text = json.dumps(report, ensure_ascii=False)
    saved_text = json.dumps(saved, ensure_ascii=False)
    trace_text = json.dumps(trace, ensure_ascii=False)
    assert "alex@example.com" not in report_text
    assert "+64 21 555 0123" not in report_text
    assert "alex@example.com" not in saved_text
    assert "+64 21 555 0123" not in saved_text
    assert "alex@example.com" not in trace_text
    assert "+64 21 555 0123" not in trace_text


def test_runner_no_apply_matching_runs_when_profile_source_not_live_ready(tmp_path, monkeypatch) -> None:
    out_path = tmp_path / "seek-report.json"
    saved_dir = tmp_path / "saved-jobs"
    profile_path = tmp_path / "candidate.json"
    profile_path.write_text(
        json.dumps(
            {
                "contract_version": "candidate_profile_v1",
                "profile_purpose": "real_resume_profile",
                "candidate_name": "Alex Chen",
                "email": "alex@example.com",
                "phone": "+64 21 555 0123",
                "experience_summary": ["Built production-style C# and test automation projects."],
                "skills": ["C#", "test automation", "photonics"],
                "target_roles": ["Software Engineer"],
                "location_constraints": ["Auckland"],
                "work_rights_summary": "Open work rights in New Zealand.",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    calls: list[tuple[str, dict]] = []
    observations = [
        _cards_observation(),
        _detail_observation(include_responsibilities=True),
        _detail_observation(include_responsibilities=True),
    ]

    def fake_post(base_url, endpoint, payload, timeout):
        calls.append((endpoint, payload))
        if endpoint == "/session/resize_bound_window":
            return _resize_response(payload)
        if endpoint == "/apps/open":
            return {"success": True, "message": "opened", "data": {"bound": True}, "error": None}
        if endpoint == "/vision/observe_screen":
            return _response(observations.pop(0))
        if endpoint == "/action/execute_recognition_plan" and payload.get("dry_run") is True:
            return _dry_response()
        if endpoint == "/action/execute_recognition_plan" and payload.get("dry_run") is False:
            return _execute_response()
        raise AssertionError(f"unexpected endpoint {endpoint}")

    monkeypatch.setattr(runner, "_post_json", fake_post)

    code = runner.main(
        [
            "--out",
            str(out_path),
            "--saved-jobs-dir",
            str(saved_dir),
            "--candidate-profile",
            str(profile_path),
            "--max-jobs",
            "1",
            "--max-detail-scrolls",
            "1",
            "--execute-clicks",
        ]
    )

    assert code == 0
    assert all(endpoint != "/action/type_text" for endpoint, _ in calls)
    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert report["candidate_profile_readiness"]["matching_ready"] is True
    assert report["candidate_profile_readiness"]["live_smoke_ready"] is False
    assert report["apply_entry_profile_gate"]["enabled"] is False
    assert report["apply_entry_profile_gate"]["allowed"] is True
    assert report["strong_apply"] == 1
    assert report["application_flows_started"] == 0
    assert report["saved_jobs"]
    report_text = json.dumps(report, ensure_ascii=False)
    assert "alex@example.com" not in report_text
    assert "+64 21 555 0123" not in report_text


def test_runner_apply_entry_for_strong_apply_starts_flow_and_stops(tmp_path, monkeypatch) -> None:
    out_path = tmp_path / "seek-report.json"
    saved_dir = tmp_path / "saved-jobs"
    profile_path = tmp_path / "candidate.json"
    profile_path.write_text(
        json.dumps(
            {
                "contract_version": "candidate_profile_v1",
                "profile_source": "real_user_candidate_profile_v1",
                "profile_purpose": "real_resume_profile",
                "candidate_name": "Alex Chen",
                "email": "alex@example.com",
                "experience_summary": ["Built production-style C# and test automation projects."],
                "skills": ["C#", "test automation", "photonics"],
                "target_roles": ["Software Engineer"],
                "location_constraints": ["Auckland"],
                "work_rights_summary": "Open work rights in New Zealand.",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    calls: list[tuple[str, dict]] = []
    observations = [
        _cards_observation(),
        _detail_observation(include_responsibilities=True),
        _detail_observation(include_responsibilities=True),
        _detail_observation(include_responsibilities=True),
        _apply_flow_observation(),
    ]

    def fake_post(base_url, endpoint, payload, timeout):
        calls.append((endpoint, payload))
        if endpoint == "/session/resize_bound_window":
            return _resize_response(payload)
        if endpoint == "/apps/open":
            return {"success": True, "message": "opened", "data": {"bound": True}, "error": None}
        if endpoint == "/vision/observe_screen":
            return _response(observations.pop(0))
        if endpoint == "/action/execute_recognition_plan" and payload.get("dry_run") is True:
            return _dry_response(final_submit_guard_enabled=bool((payload.get("metadata") or {}).get("seek_apply_entry")))
        if endpoint == "/action/execute_recognition_plan" and payload.get("dry_run") is False:
            return _execute_response(final_submit_guard_enabled=bool((payload.get("metadata") or {}).get("seek_apply_entry")))
        raise AssertionError(f"unexpected endpoint {endpoint}")

    monkeypatch.setattr(runner, "_post_json", fake_post)

    code = runner.main(
        [
            "--out",
            str(out_path),
            "--saved-jobs-dir",
            str(saved_dir),
            "--candidate-profile",
            str(profile_path),
            "--max-jobs",
            "2",
            "--max-detail-scrolls",
            "1",
            "--execute-clicks",
            "--apply-entry",
        ]
    )

    assert code == 0
    assert _non_resize_endpoints(calls) == [
        "/apps/open",
        "/vision/observe_screen",
        "/action/execute_recognition_plan",
        "/action/execute_recognition_plan",
        "/vision/observe_screen",
        "/vision/observe_screen",
        "/vision/observe_screen",
        "/action/execute_recognition_plan",
        "/action/execute_recognition_plan",
        "/vision/observe_screen",
    ]
    apply_dry_payload = _non_resize_calls(calls)[7][1]
    assert apply_dry_payload["dry_run"] is True
    assert apply_dry_payload["metadata"]["forbid_final_submit"] is True
    assert apply_dry_payload["metadata"]["required_container_id"] == "seek:job_detail"
    assert "Do not click Submit" in apply_dry_payload["goal"]
    assert "SeniorAndroid" not in apply_dry_payload["goal"]

    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert report["mode"] == "apply_entry_traversal"
    assert len(report["traversal_steps"]) == 1
    assert report["application_flows_started"] == 1
    assert report["forms_filled_until_review"] == 0
    assert report["form_fields_filled"] == 0
    assert report["continue_clicks"] == 0
    assert report["submit_clicks"] == 0
    assert report["cover_letters_generated"] == 1
    assert report["cover_letter_drafts"][0]["contract_version"] == "cover_letter_draft_v1"
    assert report["cover_letter_drafts"][0]["status"] == "draft_only_not_pasted"
    assert report["application_answer_plans"][0]["contract_version"] == "application_answer_plan_v1"
    assert report["application_answer_plans"][0]["filled"] is False
    assert report["final_submissions"] == 0
    assert report["final_submit_guard_active"] is True
    assert report["final_submit_visible_blockers"][0]["contract_version"] == "final_submit_visible_blocker_v1"
    assert report["final_submit_visible_blockers"][0]["blocked"] is False
    trace = json.loads(Path(report["traversal_trace_path"]).read_text(encoding="utf-8"))
    assert trace["contract_version"] == "seek_mvp_traversal_trace_v1"
    assert trace["apply_entries"][0]["status"] == "blocked_need_user_or_gpt_decision"
    assert trace["apply_entries"][0]["stop_reason"] == "no_auto_safe_known_fields_to_fill"
    assert trace["apply_entries"][0]["pre_apply_detail_verification"]["ok"] is True
    assert trace["safety"]["submit_clicks"] == 0
    assert trace["safety"]["final_submissions"] == 0
    entry = report["apply_entries"][0]
    assert entry["status"] == "blocked_need_user_or_gpt_decision"
    assert entry["pre_apply_detail_verification"]["contract_version"] == "pre_apply_detail_verification_v1"
    assert entry["pre_apply_detail_verification"]["ok"] is True
    assert entry["pre_apply_detail_verification"]["title_matches"] is True
    assert entry["pre_apply_detail_verification"]["company_matches"] is True
    assert entry["application_flow_started"] is True
    assert entry["application_flow_state"]["state_type"] == "cover_letter_field_detected"
    assert entry["application_flow_state"]["application_form_inventory"]["cover_letter_field_detected"] is True
    assert entry["final_submit_visible_blocker"]["blocked"] is False
    assert entry["cover_letter_generated"] is True
    assert entry["cover_letter_draft"]["status"] == "draft_only_not_pasted"
    assert entry["application_answer_plan_generated"] is True
    assert entry["application_answer_plan"]["status"] == "planned_only_not_filled"
    assert entry["application_answer_plan"]["filled"] is False
    assert entry["safe_form_fill_attempt"]["enabled"] is False
    assert entry["safe_form_fill_attempt"]["filled"] is False
    assert entry["apply_click"]["container_id"] == "seek:job_detail"
    assert entry["continue_clicks"] == 0
    assert entry["submit_clicks"] == 0
    assert entry["form_fields_filled"] == 0
    assert entry["final_submission_performed"] is False
    assert entry["apply_entry_semantics"]["apply_click_is_final_submit"] is False
    assert entry["apply_entry_semantics"]["true_final_submit_policy"] == "blocked_until_explicit_user_review"
    assert entry["final_submit_guard"]["contract_version"] == "final_submit_guard_v1"
    assert entry["final_submit_guard"]["enabled"] is True
    assert entry["final_submit_guard"]["allowed"] is True


def test_runner_apply_entry_defers_third_party_ats_without_downstream_plans(tmp_path, monkeypatch) -> None:
    out_path = tmp_path / "seek-report.json"
    saved_dir = tmp_path / "saved-jobs"
    profile_path = tmp_path / "candidate.json"
    profile_path.write_text(
        json.dumps(
            {
                "contract_version": "candidate_profile_v1",
                "profile_source": "real_user_candidate_profile_v1",
                "profile_purpose": "real_resume_profile",
                "candidate_name": "Alex Chen",
                "email": "alex@example.com",
                "experience_summary": ["Built production-style C# and test automation projects."],
                "skills": ["C#", "test automation", "photonics"],
                "target_roles": ["Software Engineer"],
                "location_constraints": ["Auckland"],
                "work_rights_summary": "Open work rights in New Zealand.",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    calls: list[tuple[str, dict]] = []
    observations = [
        _cards_observation(),
        _detail_observation(include_responsibilities=True),
        _detail_observation(include_responsibilities=True),
        _detail_observation(include_responsibilities=True),
        _third_party_ats_observation(),
    ]

    def fake_post(base_url, endpoint, payload, timeout):
        calls.append((endpoint, payload))
        if endpoint == "/session/resize_bound_window":
            return _resize_response(payload)
        if endpoint == "/apps/open":
            return {"success": True, "message": "opened", "data": {"bound": True}, "error": None}
        if endpoint == "/vision/observe_screen":
            return _response(observations.pop(0))
        if endpoint == "/action/execute_recognition_plan" and payload.get("dry_run") is True:
            return _dry_response(final_submit_guard_enabled=bool((payload.get("metadata") or {}).get("seek_apply_entry")))
        if endpoint == "/action/execute_recognition_plan" and payload.get("dry_run") is False:
            return _execute_response(final_submit_guard_enabled=bool((payload.get("metadata") or {}).get("seek_apply_entry")))
        raise AssertionError(f"unexpected endpoint {endpoint}")

    monkeypatch.setattr(runner, "_post_json", fake_post)

    code = runner.main(
        [
            "--out",
            str(out_path),
            "--saved-jobs-dir",
            str(saved_dir),
            "--candidate-profile",
            str(profile_path),
            "--max-jobs",
            "2",
            "--max-detail-scrolls",
            "1",
            "--execute-clicks",
            "--apply-entry",
        ]
    )

    assert code == 0
    report = json.loads(out_path.read_text(encoding="utf-8"))
    entry = report["apply_entries"][0]
    assert entry["application_flow_state"]["state_type"] == "third_party_ats"
    assert entry["apply_flow_decision"]["state_type"] == "third_party_ats_deferred"
    assert entry["apply_flow_decision"]["decision"] == "stop"
    assert entry["stop_reason"] == "third_party_ats_deferred"
    assert entry["cover_letter_generated"] is False
    assert entry["application_answer_plan_generated"] is False
    assert "cover_letter_draft" not in entry
    assert "application_answer_plan" not in entry
    assert "safe_form_fill_attempt" not in entry
    assert entry["form_fields_filled"] == 0
    assert entry["submit_clicks"] == 0
    assert entry["final_submission_performed"] is False
    assert report["cover_letter_drafts"] == []
    assert report["application_answer_plans"] == []
    assert report["safe_form_fill_attempts"] == []
    assert report["apply_flow_summary"]["third_party_ats_deferred"] == 1
    assert report["apply_flow_summary"]["seek_internal_flows"] == 0
    assert report["apply_flow_summary"]["answer_plans_generated"] == 0
    assert report["apply_flow_summary"]["forms_filled"] == 0
    assert report["final_submissions"] == 0


def test_execute_apply_entry_goal_prefers_merged_card_title_over_observed_ocr(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    monkeypatch.setattr(
        runner,
        "_verify_pre_apply_job_detail",
        lambda *_args, **_kwargs: {
            "contract_version": "pre_apply_detail_verification_v1",
            "ok": True,
            "observed_title": "SeniorAndroid Developer",
            "observed_company": "Fiserv",
            "title_matches": True,
            "company_matches": True,
            "apply_visible": True,
        },
    )

    def fake_post(base_url, endpoint, payload, timeout):
        calls.append((endpoint, payload))
        assert endpoint == "/action/execute_recognition_plan"
        return _dry_response(final_submit_guard_enabled=True)

    monkeypatch.setattr(runner, "_post_json", fake_post)

    attempt = runner._execute_apply_entry(
        "http://runtime",
        app_name="edge",
        job={"job_id": "job1", "title": "Senior Android Developer", "company": "Fiserv"},
        detail={
            "job_id": "job1",
            "title": "SeniorAndroid Developer",
            "company": "Fiserv",
            "apply_button_state": {"visible": True, "label": "Apply", "click_point": {"x": 1, "y": 2}},
        },
        match_decision={"decision": "maybe_apply", "job_id": "job1"},
        candidate_profile=None,
        execute_clicks=False,
        timeout=5,
        allow_maybe_apply=True,
    )

    assert attempt["status"] == "dry_run_ready"
    assert "Senior Android Developer" in calls[0][1]["goal"]
    assert "SeniorAndroid" not in calls[0][1]["goal"]


def test_execute_apply_entry_blocks_need_user_review_before_click(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(runner, "_verify_pre_apply_job_detail", lambda *_args, **_kwargs: calls.append("verify"))
    monkeypatch.setattr(runner, "_post_json", lambda *_args, **_kwargs: calls.append("post"))

    attempt = runner._execute_apply_entry(
        "http://runtime",
        app_name="edge",
        job={"job_id": "job1", "title": "Intermediate Developer", "company": "Enlighten Designs Ltd"},
        detail={
            "job_id": "job1",
            "title": "Intermediate Developer",
            "company": "Enlighten Designs Ltd",
            "apply_button_state": {"visible": True, "label": "Quick apply", "click_point": {"x": 1, "y": 2}},
        },
        match_decision={"decision": "need_user_review", "job_id": "job1"},
        candidate_profile=None,
        execute_clicks=True,
        timeout=5,
    )

    assert attempt["status"] == "skipped"
    assert attempt["eligible"] is False
    assert attempt["executed"] is False
    assert attempt["application_flow_started"] is False
    assert attempt["stop_reason"] == "decision_not_eligible_for_apply_entry"
    assert calls == []


def test_runner_apply_entry_blocks_when_current_detail_no_longer_matches(tmp_path, monkeypatch) -> None:
    out_path = tmp_path / "seek-report.json"
    profile_path = tmp_path / "candidate.json"
    profile_path.write_text(
        json.dumps(
            {
                "contract_version": "candidate_profile_v1",
                "profile_source": "real_user_candidate_profile_v1",
                "profile_purpose": "real_resume_profile",
                "candidate_name": "Alex Chen",
                "email": "alex@example.com",
                "experience_summary": ["Built production-style C# and test automation projects."],
                "skills": ["C#", "test automation", "photonics"],
                "target_roles": ["Software Engineer"],
                "location_constraints": ["Auckland"],
                "work_rights_summary": "Open work rights in New Zealand.",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    calls: list[tuple[str, dict]] = []
    observations = [
        _cards_observation(),
        _detail_observation(include_responsibilities=True),
        _detail_observation(include_responsibilities=True),
        _second_detail_observation(),
    ]

    def fake_post(base_url, endpoint, payload, timeout):
        calls.append((endpoint, payload))
        if endpoint == "/session/resize_bound_window":
            return _resize_response(payload)
        if endpoint == "/apps/open":
            return {"success": True, "message": "opened", "data": {"bound": True}, "error": None}
        if endpoint == "/vision/observe_screen":
            return _response(observations.pop(0))
        if endpoint == "/action/execute_recognition_plan" and payload.get("dry_run") is True:
            return _dry_response(final_submit_guard_enabled=bool((payload.get("metadata") or {}).get("seek_apply_entry")))
        if endpoint == "/action/execute_recognition_plan" and payload.get("dry_run") is False:
            return _execute_response(final_submit_guard_enabled=bool((payload.get("metadata") or {}).get("seek_apply_entry")))
        raise AssertionError(f"unexpected endpoint {endpoint}")

    monkeypatch.setattr(runner, "_post_json", fake_post)

    code = runner.main(
        [
            "--out",
            str(out_path),
            "--candidate-profile",
            str(profile_path),
            "--max-jobs",
            "2",
            "--max-detail-scrolls",
            "1",
            "--execute-clicks",
            "--apply-entry",
        ]
    )

    assert code == 0
    assert _non_resize_endpoints(calls) == [
        "/apps/open",
        "/vision/observe_screen",
        "/action/execute_recognition_plan",
        "/action/execute_recognition_plan",
        "/vision/observe_screen",
        "/vision/observe_screen",
        "/vision/observe_screen",
    ]
    report = json.loads(out_path.read_text(encoding="utf-8"))
    entry = report["apply_entries"][0]
    assert entry["status"] == "blocked_need_user_or_gpt_decision"
    assert entry["stop_reason"] == "pre_apply_detail_verification_failed"
    assert entry["executed"] is False
    assert entry["application_flow_started"] is False
    verification = entry["pre_apply_detail_verification"]
    assert verification["ok"] is False
    assert verification["title_matches"] is False
    assert "detail_title_mismatch" in verification["failure_reasons"]
    assert report["submit_clicks"] == 0
    assert report["final_submissions"] == 0


def test_pre_apply_verification_ignores_unreliable_close_icon_company(monkeypatch) -> None:
    monkeypatch.setattr(runner, "_observe", lambda *_args, **_kwargs: {"trace_path": "trace.json"})
    monkeypatch.setattr(
        runner,
        "extract_seek_job_detail",
        lambda *_args, **_kwargs: {
            "title": "Intermediate Engineer - AI Automation & Integration",
            "company": "X",
            "apply_button_state": {"visible": True, "label": "Quick apply button"},
        },
    )

    verification = runner._verify_pre_apply_job_detail(
        "http://127.0.0.1:8000",
        app_name="seek",
        job={"title": "Intermediate Engineer - AI Automation & Integration", "company": "Inde Technology"},
        detail={"title": "Intermediate Engineer - AI Automation & Integration", "company": "Inde Technology"},
        timeout=1,
    )

    assert verification["ok"] is True
    assert verification["title_matches"] is True
    assert verification["observed_company"] == "X"
    assert verification["observed_company_reliable"] is False
    assert verification["company_matches"] is True
    assert "detail_company_mismatch" not in verification["failure_reasons"]


def test_runner_apply_entry_blocks_when_profile_not_live_ready(tmp_path, monkeypatch) -> None:
    out_path = tmp_path / "seek-report.json"
    profile_path = tmp_path / "candidate.json"
    profile_path.write_text(
        json.dumps(
            {
                "contract_version": "candidate_profile_v1",
                "profile_purpose": "smoke_test_only_not_user_resume",
                "experience_summary": ["Synthetic smoke profile. Do not use for real applications."],
                "skills": ["C#", "photonics"],
                "target_roles": ["Software Engineer"],
                "location_constraints": ["Auckland"],
                "email": "smoke@example.com",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    calls: list[tuple[str, dict]] = []
    observations = [
        _cards_observation(),
        _detail_observation(include_responsibilities=True),
        _detail_observation(include_responsibilities=True),
    ]

    def fake_post(base_url, endpoint, payload, timeout):
        calls.append((endpoint, payload))
        if endpoint == "/session/resize_bound_window":
            return _resize_response(payload)
        if endpoint == "/apps/open":
            return {"success": True, "message": "opened", "data": {"bound": True}, "error": None}
        if endpoint == "/vision/observe_screen":
            return _response(observations.pop(0))
        if endpoint == "/action/execute_recognition_plan" and payload.get("dry_run") is True:
            return _dry_response()
        if endpoint == "/action/execute_recognition_plan" and payload.get("dry_run") is False:
            return _execute_response()
        raise AssertionError(f"unexpected endpoint {endpoint}")

    monkeypatch.setattr(runner, "_post_json", fake_post)

    code = runner.main(
        [
            "--out",
            str(out_path),
            "--candidate-profile",
            str(profile_path),
            "--max-jobs",
            "2",
            "--max-detail-scrolls",
            "1",
            "--execute-clicks",
            "--apply-entry",
            "--fill-safe-fields",
        ]
    )

    assert code == 0
    assert _non_resize_endpoints(calls) == [
        "/apps/open",
        "/vision/observe_screen",
        "/action/execute_recognition_plan",
        "/action/execute_recognition_plan",
        "/vision/observe_screen",
        "/vision/observe_screen",
    ]
    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert report["candidate_profile_readiness"]["decision"] == "blocked_need_real_candidate_profile"
    assert report["apply_entry_profile_gate"]["allowed"] is False
    assert report["apply_entry_profile_gate"]["enabled"] is True
    assert report["application_flows_started"] == 0
    assert report["form_fields_filled"] == 0
    assert report["submit_clicks"] == 0
    assert report["final_submissions"] == 0
    entry = report["apply_entries"][0]
    assert entry["status"] == "blocked_need_real_candidate_profile"
    assert entry["stop_reason"] == "apply_entry_requires_real_candidate_profile"
    assert entry["executed"] is False
    assert entry["application_flow_started"] is False
    assert entry["profile_gate"]["missing_requirements"]


def test_safe_form_fill_attempt_uses_gated_focus_then_type_text(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []
    answer_plan = {
        "contract_version": "application_answer_plan_v1",
        "status": "planned_only_not_filled",
        "planned_answers": [
            {
                "category": "auto_safe_known",
                "label": "Full name",
                "reason": "profile_full_name_available",
                "source": {
                    "collection": "page_elements",
                    "id": "full-name-field",
                    "role": "input",
                    "bbox": {"x": 100, "y": 300, "w": 420, "h": 48},
                },
                "answer_source": "candidate_profile_v1",
                "value_preview": "Alex Chen",
            }
        ],
    }

    def fake_post(base_url, endpoint, payload, timeout):
        calls.append((endpoint, payload))
        if endpoint == "/session/resize_bound_window":
            return _resize_response(payload)
        if endpoint == "/action/execute_recognition_plan" and payload.get("dry_run") is True:
            response = _dry_response(final_submit_guard_enabled=bool((payload.get("metadata") or {}).get("forbid_final_submit")))
            response["data"]["result"]["agent_step_result"]["selected_click_point"] = {"x": 310, "y": 324}
            return response
        if endpoint == "/action/execute_recognition_plan" and payload.get("dry_run") is False:
            return _execute_response(final_submit_guard_enabled=bool((payload.get("metadata") or {}).get("forbid_final_submit")))
        if endpoint == "/action/type_text":
            return _response(
                {
                    "contract_version": "type_text_result_v1",
                    "dry_run": False,
                    "text_length": len(payload["text"]),
                    "click_before_typing": payload["click_before_typing"],
                    "submit": payload["submit"],
                    "trace_path": "logs/traces/actions/type-text.json",
                }
            )
        if endpoint == "/vision/observe_screen":
            return _response(
                {
                    "trace_path": "logs/traces/vision/post-fill.json",
                    "screen_inventory": {
                        "contract_version": "screen_inventory_v1",
                        "page_elements": [
                            {
                                "id": "full-name-field",
                                "text": "Full name",
                                "role": "input",
                                "value": "Alex Chen",
                                "bbox": {"x": 100, "y": 300, "w": 420, "h": 48},
                            }
                        ],
                        "available_actions": [{"label": "Save draft"}],
                        "cards": [],
                    },
                }
            )
        raise AssertionError(f"unexpected endpoint {endpoint}")

    monkeypatch.setattr(runner, "_post_json", fake_post)

    attempt = runner._safe_form_fill_attempt(
        "http://runtime",
        app_name="edge",
        answer_plan=answer_plan,
        candidate_profile={"candidate_name": "Alex Chen"},
        execute_fill=True,
        timeout=10,
    )

    assert _non_resize_endpoints(calls) == [
        "/action/execute_recognition_plan",
        "/action/execute_recognition_plan",
        "/action/type_text",
        "/vision/observe_screen",
    ]
    dry_payload = calls[0][1]
    execute_payload = calls[1][1]
    type_payload = calls[2][1]
    assert dry_payload["metadata"]["forbid_final_submit"] is True
    assert "Do not click Continue" in dry_payload["goal"]
    assert execute_payload["approved_plan_id"]
    assert "app_name" not in type_payload
    assert type_payload["click_before_typing"] is True
    assert type_payload["x"] == 310
    assert type_payload["y"] == 324
    assert type_payload["submit"] is False
    assert type_payload["clear_existing"] is True
    field_result = attempt["field_results"][0]
    trace = field_result["safe_form_fill_trace"]
    assert trace["contract_version"] == "safe_form_fill_trace_v1"
    assert trace["field_label"] == "Full name"
    assert trace["field_category"] == "auto_safe_known"
    assert trace["value_source"] == "candidate_profile_v1"
    assert trace["value_preview"] == "<redacted:profile_value:len=9>"
    assert trace["value_length"] == len("Alex Chen")
    assert len(trace["value_hash"]) == 64
    assert trace["pre_focus_dry_run"]["allowed"] is True
    assert trace["pre_focus_dry_run"]["point_inside_field_bbox"] is True
    assert trace["approved_focus_reuse"]["allowed"] is True
    assert trace["type_text_request"]["click_before_typing"] is True
    assert trace["type_text_request"]["point"] == {"x": 310, "y": 324}
    assert trace["type_text_request"]["submit"] is False
    assert trace["post_fill_verification"]["no_submit"] is True
    assert trace["post_fill_verification"]["contract_version"] == "post_fill_verification_v1"
    assert trace["post_fill_verification"]["decision"] == "verified"
    assert trace["post_fill_verification"]["field_contains_expected_value"] is True
    assert trace["post_fill_verification"]["expected_value_preview"] == "<redacted:profile_value:len=9>"
    assert trace["safety"]["continue_clicks"] == 0
    assert trace["safety"]["submit_clicks"] == 0
    assert trace["safety"]["final_submissions"] == 0
    assert attempt["status"] == "filled_until_review"
    assert attempt["fields_filled"] == 1
    assert attempt["continue_clicks"] == 0
    assert attempt["submit_clicks"] == 0
    assert attempt["final_submissions"] == 0


def test_safe_form_fill_attempt_stops_before_focus_execute_when_dry_point_outside_field(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []
    answer_plan = {
        "contract_version": "application_answer_plan_v1",
        "status": "planned_only_not_filled",
        "planned_answers": [
            {
                "category": "auto_safe_known",
                "label": "Full name",
                "reason": "profile_full_name_available",
                "source": {
                    "collection": "page_elements",
                    "id": "full-name-field",
                    "role": "input",
                    "bbox": {"x": 100, "y": 300, "w": 420, "h": 48},
                },
                "answer_source": "candidate_profile_v1",
                "value_preview": "Alex Chen",
            }
        ],
    }

    def fake_post(base_url, endpoint, payload, timeout):
        calls.append((endpoint, payload))
        if endpoint == "/action/execute_recognition_plan" and payload.get("dry_run") is True:
            return _dry_response(final_submit_guard_enabled=True)
        raise AssertionError(f"unexpected endpoint {endpoint}")

    monkeypatch.setattr(runner, "_post_json", fake_post)

    attempt = runner._safe_form_fill_attempt(
        "http://runtime",
        app_name="edge",
        answer_plan=answer_plan,
        candidate_profile={"candidate_name": "Alex Chen"},
        execute_fill=True,
        timeout=10,
    )

    assert _non_resize_endpoints(calls) == ["/action/execute_recognition_plan"]
    field_result = attempt["field_results"][0]
    trace = field_result["safe_form_fill_trace"]
    assert field_result["stop_reason"] == "safe_field_focus_point_outside_field_bbox"
    assert trace["pre_focus_dry_run"]["allowed"] is True
    assert trace["pre_focus_dry_run"]["selected_click_point"] == {"x": 220, "y": 510}
    assert trace["pre_focus_dry_run"]["point_inside_field_bbox"] is False
    assert trace["approved_focus_reuse"] is None
    assert trace["type_text_request"]["click_before_typing"] is False
    assert attempt["fields_attempted"] == 1
    assert attempt["fields_filled"] == 0
    assert attempt["status"] == "blocked_need_user_or_gpt_decision"


def test_safe_form_fill_attempt_preview_includes_trace_without_typing() -> None:
    answer_plan = {
        "contract_version": "application_answer_plan_v1",
        "status": "planned_only_not_filled",
        "planned_answers": [
            {
                "category": "auto_safe_known",
                "label": "Email",
                "reason": "profile_email_available",
                "source": {
                    "collection": "page_elements",
                    "id": "email-field",
                    "role": "input",
                    "bbox": {"x": 100, "y": 300, "w": 420, "h": 48},
                },
                "answer_source": "candidate_profile_v1.email",
                "value_preview": "alex@example.com",
            }
        ],
    }

    attempt = runner._safe_form_fill_attempt(
        "http://runtime",
        app_name="edge",
        answer_plan=answer_plan,
        candidate_profile={"email": "alex@example.com"},
        execute_fill=False,
        timeout=10,
    )

    assert attempt["status"] == "dry_run_ready"
    assert attempt["fields_attempted"] == 0
    trace = attempt["field_results"][0]["safe_form_fill_trace"]
    assert trace["contract_version"] == "safe_form_fill_trace_v1"
    assert trace["enabled"] is False
    assert trace["field_id"] == "email-field"
    assert trace["field_bbox"] == {"x": 100, "y": 300, "w": 420, "h": 48}
    assert trace["value_preview"] == "<redacted:email:len=16>"
    assert trace["type_text_request"]["submit"] is False
    assert trace["post_fill_verification"]["status"] == "not_run_preview"
    assert trace["safety"]["final_submissions"] == 0


def test_safe_form_fill_attempt_output_does_not_echo_raw_email_or_phone() -> None:
    answer_plan = {
        "contract_version": "application_answer_plan_v1",
        "status": "planned_only_not_filled",
        "planned_answers": [
            {
                "category": "auto_safe_known",
                "label": "Email",
                "reason": "profile_email_available",
                "source": {"collection": "page_elements", "id": "email-field", "role": "email_input"},
                "answer_source": "candidate_profile_v1.email",
                "value_preview": "alex@example.com",
            },
            {
                "category": "auto_safe_known",
                "label": "Mobile phone",
                "reason": "profile_phone_available",
                "source": {"collection": "page_elements", "id": "phone-field", "role": "tel"},
                "answer_source": "candidate_profile_v1.phone",
                "value_preview": "+64 21 555 0123",
            },
        ],
    }

    attempt = runner._safe_form_fill_attempt(
        "http://runtime",
        app_name="edge",
        answer_plan=answer_plan,
        candidate_profile={"email": "alex@example.com", "phone": "+64 21 555 0123"},
        execute_fill=False,
        max_safe_fields_to_fill=2,
        timeout=10,
    )

    payload_text = json.dumps(attempt, ensure_ascii=False)
    assert "alex@example.com" not in payload_text
    assert "+64 21 555 0123" not in payload_text
    assert "<redacted:email:len=16>" in payload_text
    assert "<redacted:phone:len=15>" in payload_text
    assert attempt["field_results"][0]["safe_form_fill_trace"]["value_hash"]
    assert attempt["field_results"][1]["safe_form_fill_trace"]["value_hash"]


def test_safe_form_fill_attempt_limits_to_one_field_and_blocks_cover_letter_by_default() -> None:
    answer_plan = {
        "contract_version": "application_answer_plan_v1",
        "status": "planned_only_not_filled",
        "planned_answers": [
            {
                "category": "auto_safe_known",
                "label": "Email",
                "reason": "profile_email_available",
                "source": {"id": "email-field", "role": "email_input"},
                "answer_source": "candidate_profile_v1.email",
                "value_preview": "alex@example.com",
            },
            {
                "category": "auto_safe_known",
                "label": "First name",
                "reason": "profile_first_name_available",
                "source": {"id": "first-field", "role": "text_input"},
                "answer_source": "candidate_profile_v1.first_name",
                "value_preview": "Alex",
            },
            {
                "category": "auto_safe_known",
                "label": "Cover letter",
                "reason": "cover_letter_draft_available_but_not_pasted",
                "source": {"id": "cover-letter", "role": "textarea"},
                "answer_source": "cover_letter_draft_v1.draft",
                "value_preview": "Dear Hiring Team...",
            },
        ],
    }

    attempt = runner._safe_form_fill_attempt(
        "http://runtime",
        app_name="edge",
        answer_plan=answer_plan,
        candidate_profile={"email": "alex@example.com", "first_name": "Alex"},
        cover_letter_draft={"draft": "Dear Hiring Team..."},
        execute_fill=False,
        timeout=10,
    )

    assert attempt["status"] == "dry_run_ready"
    assert attempt["max_safe_fields_to_fill"] == 1
    assert attempt["candidate_count"] == 2
    assert attempt["selected_count"] == 1
    assert [item["label"] for item in attempt["field_results"]] == ["Email", "First name"]
    assert attempt["field_results"][0]["selected_for_fill"] is True
    assert attempt["field_results"][1]["selected_for_fill"] is False
    assert attempt["skipped_candidates"] == [
        {
            "label": "Cover letter",
            "category": "auto_safe_known",
            "answer_source": "cover_letter_draft_v1.draft",
            "reason": "cover_letter_fill_requires_explicit_flag",
        }
    ]


def test_safe_form_fill_attempt_can_preview_cover_letter_only_with_explicit_flag() -> None:
    answer_plan = {
        "contract_version": "application_answer_plan_v1",
        "status": "planned_only_not_filled",
        "planned_answers": [
            {
                "category": "auto_safe_known",
                "label": "Cover letter",
                "reason": "cover_letter_draft_available_but_not_pasted",
                "source": {"id": "cover-letter", "role": "textarea"},
                "answer_source": "cover_letter_draft_v1.draft",
                "value_preview": "Dear Hiring Team...",
            }
        ],
    }

    attempt = runner._safe_form_fill_attempt(
        "http://runtime",
        app_name="edge",
        answer_plan=answer_plan,
        cover_letter_draft={"draft": "Dear Hiring Team..."},
        execute_fill=False,
        allow_cover_letter_fill=True,
        timeout=10,
    )

    assert attempt["candidate_count"] == 1
    assert attempt["selected_count"] == 1
    assert attempt["skipped_candidates"] == []
    assert attempt["field_results"][0]["label"] == "Cover letter"


def test_safe_focus_label_uses_visible_cover_letter_textbox_anchor() -> None:
    label = runner._safe_focus_label(
        {
            "label": "Cover letter body",
            "reason": "cover_letter_draft_available_but_not_pasted",
            "answer_source": "cover_letter_draft_v1.draft",
            "source": {"source_text": "Dear Alicia,"},
        }
    )

    assert label == "existing cover letter text box containing Dear Alicia"


def test_cover_letter_post_fill_verification_can_use_ocr_after_label_changes() -> None:
    value = "Dear Hiring Team, I am interested in this Software Engineers role."
    verification = runner._verify_expected_value_from_structured_inventory(
        {
            "screen_inventory": {
                "contract_version": "screen_inventory_v1",
                "page_elements": [
                    {
                        "id": "page_text_cover_letter_body",
                        "text": value,
                        "role": "text",
                        "bbox": {"x": 838, "y": 1201, "w": 625, "h": 172},
                    }
                ],
                "available_actions": [],
                "cards": [],
            }
        },
        item={
            "label": "Dear Alicia, old cover letter content",
            "category": "auto_safe_known",
            "source": {"id": "old-cover-letter-field", "role": "input", "bbox": {"x": 838, "y": 1201, "w": 625, "h": 172}},
            "answer_source": "cover_letter_draft_v1.draft",
        },
        value=value,
    )

    assert verification["field_contains_expected_value"] is True
    assert verification["verification_methods"]["ocr_near_field"]["used_as_primary"] is True
    assert verification["field_relocation"]["status"] == "matched"


def test_cover_letter_post_fill_verification_uses_degraded_observation_ocr_lines() -> None:
    value = (
        "Dear Hiring Team,\n\n"
        "I am interested in the Software Engineer (Business Systems) role at "
        "Sourced | IT Recruitment Specialists. The role stood out to me because it matches my "
        "frontend and database project experience.\n\n"
        "Kind regards,\n"
        "Wenqing Ji"
    )

    verification = runner._verify_expected_value_from_structured_inventory(
        {
            "contract_version": "screen_observation_v1",
            "status": "degraded",
            "texts": [
                {"id": "ocr_1", "text": "Upload a cover letter", "bbox": {"x": 834, "y": 664, "w": 174, "h": 22}},
                {"id": "ocr_2", "text": "Dear Hiring Team,", "bbox": {"x": 850, "y": 802, "w": 151, "h": 25}},
                {
                    "id": "ocr_3",
                    "text": "I am interested in the Software Engineer(Business Systems) role at",
                    "bbox": {"x": 852, "y": 852, "w": 535, "h": 24},
                },
                {
                    "id": "ocr_4",
                    "text": "Sourced | IT Recruitment Specialists. The role stood out to me because it",
                    "bbox": {"x": 852, "y": 876, "w": 584, "h": 25},
                },
                {"id": "ocr_5", "text": "Kind regards,", "bbox": {"x": 850, "y": 1340, "w": 113, "h": 29}},
                {"id": "ocr_6", "text": "Wenqing Ji", "bbox": {"x": 848, "y": 1363, "w": 106, "h": 33}},
            ],
            "screen_reading": {"contract_version": "screen_reading_v1", "texts": []},
        },
        item={
            "label": "Dear Alicia, old cover letter content",
            "category": "auto_safe_known",
            "source": {"id": "old-cover-letter-field", "role": "input", "bbox": {"x": 810, "y": 1193, "w": 760, "h": 360}},
            "answer_source": "cover_letter_draft_v1.draft",
        },
        value=value,
    )

    assert verification["field_contains_expected_value"] is True
    assert verification["verification_methods"]["ocr_near_field"]["matched"] is True
    assert verification["verification_methods"]["ocr_near_field"]["match_type"] == "compact_anchor_contains"
    assert verification["field_relocation"]["status"] == "matched"
    assert "ocr_text_anchor_primary" in verification["field_relocation"]["matched_by"]


def test_cover_letter_post_fill_verification_rejects_unrelated_degraded_ocr() -> None:
    value = (
        "Dear Hiring Team,\n\n"
        "I am interested in the Software Engineer (Business Systems) role.\n\n"
        "Kind regards,\n"
        "Wenqing Ji"
    )

    verification = runner._verify_expected_value_from_structured_inventory(
        {
            "contract_version": "screen_observation_v1",
            "status": "degraded",
            "texts": [
                {"id": "ocr_1", "text": "Upload a cover letter", "bbox": {"x": 834, "y": 664, "w": 174, "h": 22}},
                {"id": "ocr_2", "text": "This is unrelated text", "bbox": {"x": 850, "y": 802, "w": 180, "h": 25}},
                {"id": "ocr_3", "text": "Save and continue", "bbox": {"x": 1180, "y": 1420, "w": 170, "h": 40}},
            ],
            "screen_reading": {"contract_version": "screen_reading_v1", "texts": []},
        },
        item={
            "label": "Dear Alicia, old cover letter content",
            "category": "auto_safe_known",
            "source": {"id": "old-cover-letter-field", "role": "input", "bbox": {"x": 810, "y": 1193, "w": 760, "h": 360}},
            "answer_source": "cover_letter_draft_v1.draft",
        },
        value=value,
    )

    assert verification["field_contains_expected_value"] is False
    assert verification["verification_methods"]["ocr_near_field"]["matched"] is False
    assert verification["field_relocation"]["status"] == "matched"
    assert verification["failure_reason"] == "expected_value_not_observable_without_dom_or_uia"


def test_safe_form_fill_attempt_stops_when_post_fill_verification_unverified(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []
    answer_plan = {
        "contract_version": "application_answer_plan_v1",
        "status": "planned_only_not_filled",
        "planned_answers": [
                {
                    "category": "auto_safe_known",
                    "label": "Full name",
                    "reason": "profile_full_name_available",
                    "source": {
                        "collection": "available_actions",
                        "id": "full-name-field",
                        "role": "input",
                        "bbox": {"x": 100, "y": 300, "w": 420, "h": 48},
                    },
                    "answer_source": "candidate_profile_v1",
                    "value_preview": "Alex Chen",
                },
            {
                "category": "auto_safe_known",
                "label": "Email",
                "reason": "profile_email_available",
                "source": {"id": "email-field", "role": "input"},
                "answer_source": "candidate_profile_v1.email",
                "value_preview": "alex@example.com",
            },
        ],
    }

    def fake_post(base_url, endpoint, payload, timeout):
        calls.append((endpoint, payload))
        if endpoint == "/session/resize_bound_window":
            return _resize_response(payload)
        if endpoint == "/action/execute_recognition_plan" and payload.get("dry_run") is True:
            response = _dry_response(final_submit_guard_enabled=True)
            response["data"]["result"]["agent_step_result"]["selected_click_point"] = {"x": 310, "y": 324}
            return response
        if endpoint == "/action/execute_recognition_plan" and payload.get("dry_run") is False:
            return _execute_response(final_submit_guard_enabled=True)
        if endpoint == "/action/type_text":
            return _response(
                {
                    "contract_version": "type_text_result_v1",
                    "dry_run": False,
                    "text_length": len(payload["text"]),
                    "click_before_typing": payload["click_before_typing"],
                    "submit": payload["submit"],
                    "trace_path": "logs/traces/actions/type-text.json",
                }
            )
        if endpoint == "/vision/observe_screen":
            return _response(
                {
                    "trace_path": "logs/traces/vision/post-fill.json",
                    "screen_inventory": {
                        "contract_version": "screen_inventory_v1",
                        "page_elements": [
                            {
                                "id": "full-name-field",
                                "text": "Full name",
                                "role": "input",
                                "bbox": {"x": 100, "y": 300, "w": 420, "h": 48},
                            }
                        ],
                        "available_actions": [{"label": "Save draft"}],
                        "cards": [],
                    },
                }
            )
        raise AssertionError(f"unexpected endpoint {endpoint}")

    monkeypatch.setattr(runner, "_post_json", fake_post)

    attempt = runner._safe_form_fill_attempt(
        "http://runtime",
        app_name="edge",
        answer_plan=answer_plan,
        candidate_profile={"candidate_name": "Alex Chen", "email": "alex@example.com"},
        execute_fill=True,
        timeout=10,
    )

    assert attempt["status"] == "blocked_need_user_or_gpt_decision"
    assert attempt["fields_attempted"] == 1
    assert attempt["fields_filled"] == 0
    assert _non_resize_endpoints(calls).count("/action/type_text") == 1
    verification = attempt["field_results"][0]["post_fill_verification"]
    assert verification["decision"] == "unverified"
    assert verification["failure_reason"] == "expected_value_not_observable_without_dom_or_uia"
    assert attempt["final_submissions"] == 0


def test_safe_form_fill_attempt_stops_when_final_submit_visible_after_fill(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []
    answer_plan = {
        "contract_version": "application_answer_plan_v1",
        "status": "planned_only_not_filled",
        "planned_answers": [
            {
                "category": "auto_safe_known",
                "label": "Full name",
                "reason": "profile_full_name_available",
                "source": {"id": "full-name-field", "role": "input", "bbox": {"x": 100, "y": 300, "w": 420, "h": 48}},
                "answer_source": "candidate_profile_v1",
                "value_preview": "Alex Chen",
            }
        ],
    }

    def fake_post(base_url, endpoint, payload, timeout):
        calls.append((endpoint, payload))
        if endpoint == "/session/resize_bound_window":
            return _resize_response(payload)
        if endpoint == "/action/execute_recognition_plan" and payload.get("dry_run") is True:
            response = _dry_response(final_submit_guard_enabled=True)
            response["data"]["result"]["agent_step_result"]["selected_click_point"] = {"x": 310, "y": 324}
            return response
        if endpoint == "/action/execute_recognition_plan" and payload.get("dry_run") is False:
            return _execute_response(final_submit_guard_enabled=True)
        if endpoint == "/action/type_text":
            return _response(
                {
                    "contract_version": "type_text_result_v1",
                    "dry_run": False,
                    "text_length": len(payload["text"]),
                    "click_before_typing": payload["click_before_typing"],
                    "submit": payload["submit"],
                    "trace_path": "logs/traces/actions/type-text.json",
                }
            )
        if endpoint == "/vision/observe_screen":
            return _response(
                {
                    "trace_path": "logs/traces/vision/post-fill.json",
                    "screen_inventory": {
                        "contract_version": "screen_inventory_v1",
                        "page_elements": [
                            {
                                "id": "full-name-field",
                                "text": "Full name",
                                "role": "input",
                                "value": "Alex Chen",
                            }
                        ],
                        "available_actions": [{"label": "Submit application"}],
                        "cards": [],
                    },
                }
            )
        raise AssertionError(f"unexpected endpoint {endpoint}")

    monkeypatch.setattr(runner, "_post_json", fake_post)

    attempt = runner._safe_form_fill_attempt(
        "http://runtime",
        app_name="edge",
        answer_plan=answer_plan,
        candidate_profile={"candidate_name": "Alex Chen"},
        execute_fill=True,
        timeout=10,
    )

    verification = attempt["field_results"][0]["post_fill_verification"]
    assert verification["decision"] == "stop_required"
    assert verification["failure_reason"] == "final_submit_visible_after_fill"
    assert verification["final_submit_visible_blocker"]["ran"] is True
    assert verification["final_submit_visible_blocker"]["blocked"] is True
    assert attempt["fields_filled"] == 0
    assert attempt["final_submissions"] == 0
    assert _non_resize_endpoints(calls).count("/action/type_text") == 1


def test_runner_detects_post_click_layout_drift_and_restores_search(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []
    observations = [_cards_observation(), _company_page_observation(), _cards_observation()]

    def fake_post(base_url, endpoint, payload, timeout):
        calls.append((endpoint, payload))
        if endpoint == "/session/resize_bound_window":
            return _resize_response(payload)
        if endpoint == "/apps/open":
            return {"success": True, "message": "opened", "data": {"bound": True}, "error": None}
        if endpoint == "/vision/observe_screen":
            return _response(observations.pop(0))
        if endpoint == "/action/execute_recognition_plan" and payload.get("dry_run") is True:
            return _dry_response()
        if endpoint == "/action/execute_recognition_plan" and payload.get("dry_run") is False:
            return _execute_response()
        raise AssertionError(f"unexpected endpoint {endpoint}")

    monkeypatch.setattr(runner, "_post_json", fake_post)

    report = runner.run_traversal(
        base_url="http://runtime",
        app_name="edge",
        url="https://www.seek.co.nz/software-engineer-jobs/in-All-Auckland",
        max_jobs=1,
        max_detail_scrolls=1,
        max_results_scrolls=0,
        execute_clicks=True,
        timeout=10,
    )

    assert _non_resize_endpoints(calls) == [
        "/apps/open",
        "/vision/observe_screen",
        "/action/execute_recognition_plan",
        "/action/execute_recognition_plan",
        "/vision/observe_screen",
        "/apps/open",
        "/vision/observe_screen",
    ]
    assert report["jobs_seen"] == 1
    assert report["jobs_opened"] == 0
    step = report["traversal_steps"][0]
    assert step["card_click"]["failure_reason"] == "post_click_layout_drift"
    assert step["card_click"]["post_click_layout"]["ok"] is False
    assert step["search_restore"]["success"] is True
    assert report["final_submissions"] == 0


def test_runner_keeps_report_jobs_aligned_after_layout_drift_then_success(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []
    observations = [
        _cards_observation(),
        _company_page_observation(),
        _second_cards_observation(),
        _second_detail_observation(),
        _second_detail_observation(),
    ]

    def fake_post(base_url, endpoint, payload, timeout):
        calls.append((endpoint, payload))
        if endpoint == "/session/resize_bound_window":
            return _resize_response(payload)
        if endpoint == "/apps/open":
            return {"success": True, "message": "opened", "data": {"bound": True}, "error": None}
        if endpoint == "/vision/observe_screen":
            return _response(observations.pop(0))
        if endpoint == "/action/execute_recognition_plan" and payload.get("dry_run") is True:
            return _dry_response()
        if endpoint == "/action/execute_recognition_plan" and payload.get("dry_run") is False:
            return _execute_response()
        raise AssertionError(f"unexpected endpoint {endpoint}")

    monkeypatch.setattr(runner, "_post_json", fake_post)

    report = runner.run_traversal(
        base_url="http://runtime",
        app_name="edge",
        url="https://www.seek.co.nz/software-engineer-jobs/in-All-Auckland",
        max_jobs=1,
        max_detail_scrolls=1,
        max_results_scrolls=0,
        execute_clicks=True,
        timeout=10,
    )

    assert report["jobs_seen"] == 2
    assert report["jobs_opened"] == 1
    assert report["jobs_fully_read"] == 1
    assert report["accuracy_summary"]["post_click_layout_drift_count"] == 1
    assert len(report["jobs"]) == 2
    assert report["jobs"][0]["card"]["title"] == "Software Engineer (Test Systems)"
    assert report["jobs"][0]["detail"] is None
    assert report["jobs"][0]["match_decision"] is None
    assert report["jobs"][1]["card"]["title"] == "Senior Backend Developer"
    assert report["jobs"][1]["detail"]["title"] == "Senior Backend Developer"
    assert report["jobs"][1]["match_decision"]["job_id"] == report["jobs"][1]["card"]["job_id"]


def test_title_match_rejects_short_ocr_noise() -> None:
    assert runner._titles_match("Applications Software Engineer", "ApplicationsSoftware Engineer") is True
    assert runner._titles_match("Software Engineer", "A") is False
    assert runner._titles_match("Staff Software Engineer", "tA") is False
    assert runner._titles_match("Full-Stack Developers", "The agency is made up of a team") is False


def test_detail_title_evidence_marks_body_fragment() -> None:
    title = "programand islookingforaGradSoftwareMigrationEngineertohelpmodernise and"
    detail = {
        "title": title,
        "evidence": {
            "texts": [
                "All Auckland",
                "SEEK",
                "Classification",
                "Listing time",
                "Quick apply",
                "Save",
                "Posted 12h ago",
                "Full time",
                "Engineering",
                title,
            ]
        },
    }

    assert runner._detail_title_evidence_quality(detail) == "body_fragment_candidate"


def test_job_seen_key_normalizes_location_punctuation() -> None:
    first = {
        "title": "Senior Software Engineer",
        "company": "Absolute IT Limited",
        "location": "Auckland CBD,Auckland",
    }
    second = {
        "title": "Senior Software Engineer",
        "company": "Absolute IT Limited",
        "location": "Auckland CBD, Auckland",
    }

    assert runner._job_seen_key(first) == runner._job_seen_key(second)


def test_job_seen_key_normalizes_stuck_title_words() -> None:
    first = {
        "title": "SeniorSoftware Engineer",
        "company": "Absolute IT Limited",
        "location": "Auckland CBD, Auckland",
    }
    second = {
        "title": "Senior Software Engineer",
        "company": "Absolute IT Limited",
        "location": "Auckland CBD, Auckland",
    }

    assert runner._job_seen_key(first) == runner._job_seen_key(second)


def test_append_new_jobs_defers_bottom_edge_cards_without_marking_seen() -> None:
    queue: list[dict] = []
    seen: set[str] = set()
    payload = {
        "image_size": {"width": 1200, "height": 1000},
        "jobs": [
            {
                "title": "Staff Software Engineer",
                "company": "Kami",
                "location": "Auckland",
                "click_point": {"x": 120, "y": 950},
            }
        ],
    }

    assert runner._append_new_jobs(queue, seen, payload) == 0
    assert queue == []
    assert seen == set()

    payload["jobs"][0]["click_point"]["y"] = 620
    assert runner._append_new_jobs(queue, seen, payload) == 1
    assert queue[0]["title"] == "Staff Software Engineer"
    assert seen
