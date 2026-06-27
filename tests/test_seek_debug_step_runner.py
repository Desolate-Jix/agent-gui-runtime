from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

from PIL import Image, ImageDraw


RUNNER_PATH = Path(__file__).resolve().parents[1] / "scripts" / "seek_debug_step_runner.py"
spec = importlib.util.spec_from_file_location("seek_debug_step_runner", RUNNER_PATH)
assert spec is not None and spec.loader is not None
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_top_level_observe_texts_feed_employer_question_inventory() -> None:
    observation = {
        "contract_version": "screen_observation_v1",
        "texts": [
            {
                "id": "text_q2",
                "text": "Do you have at least 1-2 years of experience in web application development?",
                "bbox": {"x": 737, "y": 570, "w": 629, "h": 25},
            },
            {
                "id": "text_q3",
                "text": "Are you comfortable reading, altering and designing solutions with some of the following: Java, AngularJS, React, Vue, MySQL?",
                "bbox": {"x": 737, "y": 710, "w": 640, "h": 46},
            },
            {
                "id": "text_q4",
                "text": "Can you start immediately or within 1-2 weeks?",
                "bbox": {"x": 737, "y": 874, "w": 383, "h": 26},
            },
        ],
    }

    screen_reading = runner._screen_reading_from_observation(observation)
    inventory = runner.build_employer_question_inventory(
        {
            "contract_version": "seek_application_flow_state_v1",
            "current_step": "answer_employer_questions",
            "application_form_inventory": {
                "contract_version": "application_form_inventory_v1",
                "fields": [],
                "actions": [
                    {"id": "q2_yes", "text": "Yes", "role": "radio", "bbox": {"x": 738, "y": 616, "w": 38, "h": 38}},
                    {"id": "q2_no", "text": "No", "role": "radio", "bbox": {"x": 738, "y": 660, "w": 38, "h": 38}},
                    {"id": "q3_yes", "text": "Yes", "role": "radio", "bbox": {"x": 738, "y": 770, "w": 38, "h": 38}},
                    {"id": "q3_no", "text": "No", "role": "radio", "bbox": {"x": 738, "y": 814, "w": 38, "h": 38}},
                    {"id": "q4_input", "text": "", "role": "textbox", "bbox": {"x": 738, "y": 909, "w": 661, "h": 98}},
                ],
            },
        },
        screen_reading=screen_reading,
    )

    assert screen_reading is observation
    assert inventory["question_count"] == 3
    assert [item["answer_type"] for item in inventory["questions"]] == [
        "radio_yes_no",
        "radio_yes_no",
        "text_input",
    ]


def _args(tmp_path: Path, step: str) -> argparse.Namespace:
    return argparse.Namespace(
        base_url="http://runtime.test",
        run_dir=str(tmp_path / "seek_debug"),
        step=step,
        url="https://nz.seek.com/software-engineer-jobs/in-All-Auckland",
        app_name="edge",
        job_index=0,
        timeout=5.0,
        window_width=2560,
        window_height=1400,
        wheel_clicks=4,
        search_query="graduate",
        search_x=840,
        search_y=207,
        search_wait_seconds=0.1,
        capture_after_search=False,
        batch_max_captures=4,
        batch_stop_after_no_new_content=1,
        candidate_profile=None,
        learned_artifact=None,
        application_flow_replay=None,
        application_fill_record=None,
        allow_close_windows=False,
        fast_open_detail=False,
        allow_maybe_apply=False,
        post_apply_capture_wait_seconds=0.0,
        fill_safe_fields=False,
        max_safe_fields_to_fill=1,
        allow_cover_letter_fill=False,
    )


def test_search_keyword_submit_uses_type_text_submit_not_button_locate(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[str, dict]] = []

    monkeypatch.setattr(runner, "_read_json", lambda _path: None)

    def fake_runtime_state(_base_url, _timeout):
        return {
            "response": {"success": True},
            "payload": {
                "bound": True,
                "window_title": "Graduate Jobs in All New Zealand - SEEK",
                "process_name": "msedge.exe",
            },
        }

    def fake_post_json(_base_url, endpoint, payload, _timeout):
        calls.append((endpoint, payload))
        assert endpoint == "/action/type_text"
        return {
            "success": True,
            "message": "Text input dispatched",
            "data": {
                "result": {
                    "contract_version": "type_text_result_v1",
                    "trace_path": "logs/traces/actions/type-text.json",
                    "submit": payload["submit"],
                }
            },
            "error": None,
        }

    monkeypatch.setattr(runner, "_runtime_state", fake_runtime_state)
    monkeypatch.setattr(runner, "_post_json", fake_post_json)

    payload = runner.run_step(_args(tmp_path, "search_keyword_submit"))

    assert payload["status"] == "ok"
    assert calls == [
        (
            "/action/type_text",
            {
                "text": "graduate",
                "x": 840,
                "y": 207,
                "click_before_typing": True,
                "clear_existing": True,
                "submit": True,
                "restore_clipboard": True,
                "dry_run": False,
                "metadata": {
                    "contract_version": "seek_search_submit_request_v1",
                    "action_taxonomy": "type_public_search_query",
                    "input_category": "public_search_query",
                    "submit_method": "enter_key",
                    "target_latency_ms": 20000,
                },
            },
        )
    ]
    assert payload["search_submit"]["submit_method"] == "type_text_submit_enter"
    assert payload["search_submit"]["within_target_latency"] is True
    state = json.loads((tmp_path / "seek_debug" / "state.json").read_text(encoding="utf-8"))
    assert state["next_allowed_steps"] == ["extract_cards", "capture"]


def _detail(title: str, requirement: str, *, y: int = 210) -> dict:
    return {
        "contract_version": "seek_job_detail_v1",
        "title": title,
        "company": "Example Ltd",
        "location": "Auckland",
        "requirements": [requirement],
        "detail_container": {"bbox": {"x": 484, "y": y, "w": 900, "h": 820}},
    }


def _cards_observation() -> dict:
    return {
        "contract_version": "screen_observation_v1",
        "image_size": {"width": 2560, "height": 1400},
        "screen_inventory": {
            "contract_version": "screen_inventory_v1",
            "available_actions": [
                {
                    "id": "action_job_1",
                    "label": "Senior Android Developer",
                    "bbox": {"x": 632, "y": 529, "w": 475, "h": 239},
                    "click_point": {"x": 869, "y": 648},
                }
            ],
            "page_elements": [
                {"id": "title", "text": "Senior Android Developer", "bbox": {"x": 652, "y": 555, "w": 231, "h": 24}},
                {"id": "company", "text": "Fiserv New Zealand Limited", "bbox": {"x": 652, "y": 590, "w": 240, "h": 24}},
                {"id": "location", "text": "Auckland CBD, Auckland", "bbox": {"x": 652, "y": 625, "w": 240, "h": 24}},
            ],
            "cards": [
                {
                    "id": "card_job_1",
                    "label": "Hyperlink",
                    "bbox": {"x": 632, "y": 529, "w": 475, "h": 239},
                    "primary_action_id": "action_job_1",
                    "child_action_ids": ["action_job_1"],
                    "child_page_element_ids": ["title", "company", "location"],
                }
            ],
        },
    }


def test_read_detail_scroll_is_single_step_and_targets_right_detail(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[str, dict]] = []
    details = [
        _detail("Software Engineer", "Python"),
        _detail("Software Engineer", "Python and C#"),
    ]

    monkeypatch.setattr(runner, "_read_json", lambda _path: None)
    monkeypatch.setattr(runner, "_capture", lambda _base_url, _timeout: {"image_path": "capture.png", "payload": {}})

    def fake_observe_detail(_base_url, _app_name, _timeout):
        detail = details.pop(0)
        observation = _cards_observation()
        observation["trace_path"] = f"trace-{len(details)}.json"
        observation["image_path"] = f"observe-{len(details)}.png"
        return observation, detail

    def fake_post_json(_base_url, endpoint, payload, _timeout):
        calls.append((endpoint, payload))
        assert endpoint == "/action/scroll"
        return {
            "success": True,
            "message": "ok",
            "data": {
                "result": {
                    "contract_version": "scroll_action_v2",
                    "target_container_id": "seek:job_detail",
                    "target_pane": "job_detail",
                    "trace_path": "logs/traces/actions/scroll.json",
                    "huge_debug_payload": "x" * 1000,
                    "scroll_effect_validation": {
                        "status": "content_changed",
                        "non_target_panes_stable": True,
                    },
                }
            },
            "error": None,
        }

    monkeypatch.setattr(runner, "_observe_detail", fake_observe_detail)
    monkeypatch.setattr(runner, "_post_json", fake_post_json)

    payload = runner.run_step(_args(tmp_path, "read_detail_scroll"))

    assert len(calls) == 1
    endpoint, request = calls[0]
    assert endpoint == "/action/scroll"
    assert request["scroll_scope"] == "container"
    assert request["target_container_id"] == "seek:job_detail"
    assert request["container_bbox"] == {"x": 484, "y": 210, "width": 900, "height": 820}
    assert payload["right_detail_scroll_validation"]["contract_version"] == "right_detail_scroll_validation_v1"
    assert payload["right_detail_scroll_validation"]["right_detail_changed"] is True
    assert payload["right_detail_scroll_validation"]["left_results_stable"] is True
    assert payload["right_detail_scroll_validation"]["wrong_scope"] is False
    assert payload["right_detail_scroll_validation"]["new_unique_line_count"] >= 1
    assert payload["right_detail_scroll_validation"]["no_progress_count"] == 0
    assert payload["right_detail_scroll_validation"]["next_recommendation"] == "continue_detail_scroll"
    assert payload["scroll_response"]["trace_path"] == "logs/traces/actions/scroll.json"
    assert "huge_debug_payload" not in payload["scroll_response"]
    assert payload["job_archive_path"]
    archive = json.loads(Path(payload["job_archive_path"]).read_text(encoding="utf-8"))
    assert archive["contract_version"] == "seek_job_archive_v1"
    assert archive["source"] == "seek_debug_step_runner"
    assert archive["title"] == "Software Engineer"
    assert archive["detail_read"]["detail"]["requirements"] == ["Python", "Python and C#"]
    assert archive["detail_read"]["scrolls"][0]["scroll_request"]["target_container_id"] == "seek:job_detail"
    assert archive["debug_steps"][0]["step_name"] == "read_detail_scroll"
    assert archive["debug_steps"][0]["before_image"] == "capture.png"
    assert archive["debug_steps"][0]["after_image"] == "capture.png"

    state = json.loads((tmp_path / "seek_debug" / "state.json").read_text(encoding="utf-8"))
    assert state["phase"] == "read_detail_scroll"
    assert state["next_allowed_steps"] == ["read_detail_scroll", "match"]
    assert len(state["detail_scrolls"]) == 1
    assert state["current_job_archive_path"] == payload["job_archive_path"]
    assert state["job_archives"][0]["path"] == payload["job_archive_path"]


def test_read_detail_scroll_records_no_progress_stop_reason(monkeypatch, tmp_path: Path) -> None:
    same_detail = _detail("Software Engineer", "Python")
    monkeypatch.setattr(runner, "_read_json", lambda _path: None)
    monkeypatch.setattr(runner, "_capture", lambda _base_url, _timeout: {"image_path": "capture.png", "payload": {}})
    monkeypatch.setattr(
        runner,
        "_observe_detail",
        lambda _base_url, _app_name, _timeout: ({"trace_path": "trace.json"}, dict(same_detail)),
    )
    monkeypatch.setattr(
        runner,
        "_post_json",
        lambda _base_url, _endpoint, _payload, _timeout: {
            "success": True,
            "message": "ok",
            "data": {
                "result": {
                    "target_container_id": "seek:job_detail",
                    "target_pane": "job_detail",
                    "scroll_effect_validation": {"status": "no_effect", "non_target_panes_stable": True},
                }
            },
            "error": None,
        },
    )

    payload = runner.run_step(_args(tmp_path, "read_detail_scroll"))

    validation = payload["right_detail_scroll_validation"]
    assert validation["right_detail_changed"] is False
    assert validation["new_unique_line_count"] == 0
    assert validation["no_progress_count"] == 1
    assert validation["adaptive_stop_reason"] == "right_detail_bottom_or_boundary_reached"


def test_read_detail_scroll_blocks_next_steps_when_left_results_changes(monkeypatch, tmp_path: Path) -> None:
    details = [
        _detail("Software Engineer", "Python"),
        _detail("Software Engineer", "Python and C#"),
    ]
    monkeypatch.setattr(runner, "_read_json", lambda _path: None)
    monkeypatch.setattr(runner, "_capture", lambda _base_url, _timeout: {"image_path": "capture.png", "payload": {}})

    def fake_observe_detail(_base_url, _app_name, _timeout):
        return {"trace_path": "trace.json", "image_path": "observe.png"}, details.pop(0)

    monkeypatch.setattr(runner, "_observe_detail", fake_observe_detail)
    monkeypatch.setattr(
        runner,
        "_visible_cards_fingerprint",
        lambda observation, **_kwargs: {"jobs_seen": 1, "fingerprint": "same", "job_keys": ["same"]},
    )
    monkeypatch.setattr(
        runner,
        "_left_results_visual_stability",
        lambda *_args, **_kwargs: {"contract_version": "visual_pane_stability_v1", "stable": False},
    )
    monkeypatch.setattr(
        runner,
        "_post_json",
        lambda _base_url, _endpoint, _payload, _timeout: {
            "success": True,
            "message": "ok",
            "data": {
                "result": {
                    "target_container_id": "seek:job_detail",
                    "target_pane": "job_detail",
                    "scroll_effect_validation": {"status": "content_changed", "non_target_panes_stable": False},
                }
            },
            "error": None,
        },
    )

    payload = runner.run_step(_args(tmp_path, "read_detail_scroll"))

    validation = payload["right_detail_scroll_validation"]
    assert validation["left_results_stable"] is False
    assert validation["adaptive_stop_reason"] == "wrong_scope_scroll_results_list_changed"
    assert validation["next_allowed_steps"] == ["capture", "abort"]

    state = json.loads((tmp_path / "seek_debug" / "state.json").read_text(encoding="utf-8"))
    assert state["next_allowed_steps"] == ["capture", "abort"]


def test_visible_cards_fingerprint_excludes_right_detail_pseudo_cards(monkeypatch) -> None:
    monkeypatch.setattr(
        runner,
        "extract_seek_job_cards",
        lambda _observation, goal=None: {
            "jobs": [
                {
                    "title": "Cloud Engineer",
                    "company": "Datacom",
                    "location": "Auckland CBD",
                    "card_bbox": {"x": 520, "y": 600, "w": 420, "h": 260},
                },
                {
                    "title": "Company profile section",
                    "company": None,
                    "location": None,
                    "card_bbox": {"x": 1180, "y": 980, "w": 560, "h": 300},
                },
            ]
        },
    )

    fingerprint = runner._visible_cards_fingerprint({}, exclude_detail_bbox={"x": 1134, "y": 280, "width": 896, "height": 1104})

    assert fingerprint["jobs_seen"] == 1
    assert fingerprint["job_keys"] == ["cloudengineer@y12"]
    assert fingerprint["display_job_keys"] == ["cloud engineer|datacom|auckland cbd"]


def test_visible_cards_fingerprint_tolerates_ocr_spacing_and_bad_company(monkeypatch) -> None:
    monkeypatch.setattr(
        runner,
        "extract_seek_job_cards",
        lambda _observation, goal=None: {
            "jobs": [
                {
                    "title": "Senior Android Developer",
                    "company": "at",
                    "location": "Auckland CBD",
                    "card_bbox": {"x": 520, "y": 430, "w": 420, "h": 200},
                },
                {
                    "title": "SeniorAndroid Developer",
                    "company": "Fiserv New Zealand Limited",
                    "location": "Auckland CBD",
                    "card_bbox": {"x": 520, "y": 440, "w": 420, "h": 200},
                },
            ]
        },
    )

    fingerprint = runner._visible_cards_fingerprint({}, exclude_detail_bbox={"x": 1134, "y": 280, "width": 896, "height": 1104})

    assert fingerprint["jobs_seen"] == 1
    assert fingerprint["job_keys"] == ["seniorandroiddeveloper@y8"]


def test_merge_scrolled_detail_preserves_header_fields_from_previous_detail() -> None:
    previous = {
        "title": "Cloud Engineer",
        "company": "Datacom",
        "location": "Auckland CBD, Auckland (Hybrid)",
        "work_type": "Fulltime",
        "classification": "Engineering - Software (Information & Communication Technology)",
        "requirements": ["AWS"],
        "description_sections": [{"index": 0, "role": "body", "text": "Header text"}],
        "trace_paths": ["trace-before.json"],
    }
    after = {
        "title": "Cloud Engineer",
        "company": "Datacom",
        "location": None,
        "work_type": None,
        "classification": "We are a pretty agile company, and are keen to respond to customer, technology and",
        "requirements": ["Kubernetes"],
        "description_sections": [{"index": 0, "role": "body", "text": "Scrolled body"}],
        "trace_paths": ["trace-after.json"],
    }

    merged = runner._merge_scrolled_detail(
        previous_detail=previous,
        before_detail=previous,
        after_detail=after,
        current_job={"location": "Card location"},
    )

    assert merged["company"] == "Datacom"
    assert merged["location"] == "Auckland CBD, Auckland (Hybrid)"
    assert merged["work_type"] == "Fulltime"
    assert merged["classification"] == "Engineering - Software (Information & Communication Technology)"
    assert merged["requirements"] == ["AWS", "Kubernetes"]
    assert [item["text"] for item in merged["description_sections"]] == ["Header text", "Scrolled body"]
    assert merged["trace_paths"] == ["trace-before.json", "trace-after.json"]


def test_merge_scrolled_detail_trims_trailing_recommended_jobs() -> None:
    previous = {
        "title": "Intermediate Developer",
        "company": "Enlighten Designs Ltd",
        "description_sections": [
            {"index": 0, "role": "body", "text": "How we're delivering value with AI"},
            {"index": 1, "role": "body", "text": "Employer questions"},
            {"index": 2, "role": "body", "text": "Do you have a legal right to work in New Zealand?"},
        ],
    }
    after = {
        "title": "Intermediate Developer",
        "company": "Enlighten Designs Ltd",
        "description_sections": [
            {"index": 0, "role": "body", "text": "Be careful"},
            {"index": 1, "role": "body", "text": "Featured jobs"},
            {"index": 2, "role": "body", "text": "Intermediate PHP Developer"},
            {"index": 3, "role": "body", "text": "Rockit Recruitment"},
        ],
    }

    merged = runner._merge_scrolled_detail(
        previous_detail=previous,
        before_detail=previous,
        after_detail=after,
        current_job={"title": "Intermediate Developer", "company": "Enlighten Designs Ltd"},
    )

    texts = [item["text"] for item in merged["description_sections"]]
    assert "Employer questions" in texts
    assert "Do you have a legal right to work in New Zealand?" in texts
    assert "Be careful" in texts
    assert "Featured jobs" not in texts
    assert "Intermediate PHP Developer" not in texts
    assert "Rockit Recruitment" not in texts


def test_merge_scrolled_detail_rejects_salary_widget_as_header() -> None:
    previous = {
        "job_id": "seek_job_salary_widget_previous",
        "title": "Cloud Engineer",
        "company": "Datacom",
        "location": "Auckland CBD, Auckland (Hybrid)",
        "classification": "Information Technology Services",
    }
    after = {
        "job_id": "seek_job_salary_widget",
        "title": "What can I earn as a Cloud Engineer",
        "company": "Seemore detailed salary information→",
        "location": None,
        "classification": "Information Technology Services",
        "description_sections": [{"index": 0, "role": "body", "text": "What can I earn as a Cloud Engineer"}],
    }

    merged = runner._merge_scrolled_detail(
        previous_detail=previous,
        before_detail=previous,
        after_detail=after,
        current_job={"title": "Cloud Engineer", "company": "Datacom", "job_id": "seek_job_cloud_datacom"},
    )

    assert merged["job_id"] == "seek_job_cloud_datacom"
    assert merged["title"] == "Cloud Engineer"
    assert merged["company"] == "Datacom"
    assert merged["location"] == "Auckland CBD, Auckland (Hybrid)"


def test_merge_scrolled_detail_rejects_featured_job_fragments_as_header() -> None:
    previous = {
        "job_id": "seek_job_intermediate_developer",
        "title": "Intermediate Developer",
        "company": "Enlighten Designs Ltd",
        "location": "Hamilton Central, Waikato (Hybrid)",
    }
    after = {
        "job_id": "seek_job_polluted_featured",
        "title": "Intermediate Developer",
        "company": "X",
        "location": "SAFE NZ //",
        "description_sections": [{"index": 0, "role": "body", "text": "Featured jobs"}],
    }

    merged = runner._merge_scrolled_detail(
        previous_detail=previous,
        before_detail=previous,
        after_detail=after,
        current_job={
            "title": "Intermediate Developer",
            "company": "Enlighten Designs Ltd",
            "location": "Hamilton Central, Waikato (Hybrid)",
            "job_id": "seek_job_card",
        },
    )

    assert merged["title"] == "Intermediate Developer"
    assert merged["company"] == "Enlighten Designs Ltd"
    assert merged["location"] == "Hamilton Central, Waikato (Hybrid)"


def test_merge_scrolled_detail_rejects_company_profile_brand_as_location() -> None:
    previous = {
        "job_id": "seek_job_application_support_engineer",
        "title": "Application Support Engineer",
        "company": "Westpac New Zealand Limited",
        "location": "Auckland CBD, Auckland (Hybrid)",
    }
    after = {
        "job_id": "seek_job_company_profile",
        "title": "Application Support Engineer",
        "company": "Westpac New Zealand Limited",
        "location": "WestpacNZ",
        "description_sections": [{"index": 0, "role": "body", "text": "Company profile"}],
    }

    merged = runner._merge_scrolled_detail(
        previous_detail=previous,
        before_detail=previous,
        after_detail=after,
        current_job={
            "title": "Application Support Engineer",
            "company": "Westpac New Zealand Limited",
            "location": "Auckland CBD, Auckland (Hybrid)",
        },
    )

    assert merged["location"] == "Auckland CBD, Auckland (Hybrid)"


def test_merge_scrolled_detail_prefers_card_identity_over_body_title() -> None:
    previous = {
        "job_id": "seek_job_ai_automation",
        "title": "Intermediate Engineer - AI Automation & Integration",
        "company": "Inde Technology",
        "location": "Auckland CBD, Auckland (Hybrid)",
    }
    after = {
        "job_id": "seek_job_body_line",
        "title": "Join Inde's AI, Automation, & Integration team and collaborate with specialists",
        "company": "X",
        "location": "Auckland CBD, Auckland (Hybrid)",
        "description_sections": [{"index": 0, "role": "body", "text": "Join Inde's AI team"}],
    }

    merged = runner._merge_scrolled_detail(
        previous_detail=previous,
        before_detail=previous,
        after_detail=after,
        current_job={
            "title": "Intermediate Engineer - AI Automation & Integration",
            "company": "Inde Technology",
            "location": "Auckland CBD, Auckland (Hybrid)",
            "job_id": "seek_job_card",
        },
    )

    assert merged["title"] == "Intermediate Engineer - AI Automation & Integration"
    assert merged["company"] == "Inde Technology"


def test_verify_detail_preserves_header_fields_when_current_view_lacks_them(monkeypatch, tmp_path: Path) -> None:
    args = _args(tmp_path, "verify_detail")
    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True)
    state = {
        "contract_version": runner.STATE_CONTRACT,
        "run_id": "seek_debug",
        "run_dir": str(run_dir),
        "phase": "read_detail_scroll",
        "step_index": 4,
        "current_job": {
            "title": "Cloud Engineer",
            "company": "Datacom",
            "location": "Auckland CBD, Auckland (Hybrid)",
        },
        "detail": {
            "title": "Cloud Engineer",
            "company": "Datacom",
            "location": "Auckland CBD, Auckland (Hybrid)",
            "requirements": ["AWS"],
        },
        "steps": [],
        "safety": runner._default_safety(),
    }
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    raw_detail = {
        "title": "Cloud Engineer",
        "company": "Datacom",
        "location": None,
        "requirements": ["Kubernetes"],
        "description_sections": [{"index": 0, "role": "body", "text": "Scrolled requirement text"}],
    }

    monkeypatch.setattr(runner, "_read_json", lambda _path: None)
    monkeypatch.setattr(runner, "_capture", lambda _base_url, _timeout: {"image_path": "capture.png", "payload": {}})
    monkeypatch.setattr(
        runner,
        "_observe_detail",
        lambda _base_url, _app_name, _timeout: ({"trace_path": "trace.json", "image_path": "observe.png"}, raw_detail),
    )

    payload = runner.run_step(args)

    assert payload["raw_detail"]["location"] is None
    assert payload["detail"]["location"] == "Auckland CBD, Auckland (Hybrid)"
    assert payload["detail"]["requirements"] == ["AWS", "Kubernetes"]
    state_after = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state_after["next_allowed_steps"] == ["read_detail_batch", "match"]


def test_verify_detail_precise_drawer_does_not_merge_stale_body(monkeypatch, tmp_path: Path) -> None:
    args = _args(tmp_path, "verify_detail")
    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True)
    state = {
        "contract_version": runner.STATE_CONTRACT,
        "run_id": "seek_debug",
        "run_dir": str(run_dir),
        "phase": "verify_detail",
        "step_index": 4,
        "current_job": {"title": "Intermediate Developer", "company": "Enlighten Designs Ltd"},
        "detail": {
            "title": "Intermediate Developer",
            "company": "Enlighten Designs Ltd",
            "requirements": ["Saved searches"],
            "description_sections": [{"index": 0, "role": "body", "text": "Saved jobs"}],
        },
        "steps": [],
        "safety": runner._default_safety(),
    }
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    raw_detail = {
        "title": "Intermediate Developer",
        "company": "Enlighten Designs Ltd",
        "requirements": ["C# Programming"],
        "description_sections": [{"index": 0, "role": "body", "text": "The step up that actually matters"}],
        "detail_container": {
            "bbox": {"x": 1596, "y": 427, "w": 948, "h": 957},
            "sources": ["seek_detail_drawer_anchor_bbox"],
        },
    }

    monkeypatch.setattr(runner, "_read_json", lambda _path: None)
    monkeypatch.setattr(runner, "_capture", lambda _base_url, _timeout: {"image_path": "capture.png", "payload": {}})
    monkeypatch.setattr(
        runner,
        "_observe_detail",
        lambda _base_url, _app_name, _timeout: ({"trace_path": "trace.json", "image_path": "observe.png"}, raw_detail),
    )

    payload = runner.run_step(args)

    assert payload["detail"]["requirements"] == ["C# Programming"]
    assert payload["detail"]["description_sections"] == [{"index": 0, "role": "body", "text": "The step up that actually matters"}]


def test_read_detail_batch_updates_state_detail_for_match(monkeypatch, tmp_path: Path) -> None:
    args = _args(tmp_path, "read_detail_batch")
    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True)
    state = {
        "contract_version": runner.STATE_CONTRACT,
        "run_id": "seek_debug",
        "run_dir": str(run_dir),
        "phase": "verify_detail",
        "step_index": 4,
        "current_job": {"title": "Software Engineer", "company": "Example Ltd"},
        "detail": {
            "title": "Software Engineer",
            "company": "Example Ltd",
            "description_sections": [{"index": 0, "role": "body", "text": "Header text"}],
            "detail_container": {"bbox": {"x": 100, "y": 100, "w": 800, "h": 900}},
        },
        "steps": [],
        "safety": runner._default_safety(),
    }
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    batch = {
        "status": "ok",
        "target_container_id": "seek:job_detail",
        "target_bbox": {"x": 100, "y": 100, "w": 800, "h": 900},
        "capture_count": 2,
        "unique_line_count": 2,
        "stop_reason": "no_new_content",
        "merged_text_lines": [
            "Apply",
            "Header text",
            "You bring strong experience in integration or C# .NET development.",
        ],
        "captures": [{"trace_path": "ocr_trace.json"}],
    }

    monkeypatch.setattr(runner, "_read_json", lambda _path: None)
    monkeypatch.setattr(runner, "_read_detail_batch", lambda *_args, **_kwargs: batch)

    payload = runner.run_step(args)

    state_after = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    texts = [item["text"] for item in state_after["detail"]["description_sections"]]
    assert payload["merged_description_section_count"] == 3
    assert "You bring strong experience in integration or C# .NET development." in texts
    assert state_after["detail"]["detail_bottom_reached"] is True
    assert state_after["detail"]["trace_paths"] == ["ocr_trace.json"]
    assert state_after["detail"]["apply_button_state"]["label"] == "Apply"
    assert state_after["detail"]["apply_button_state"]["source"] == "read_detail_batch_ocr"


def test_execute_card_resets_stale_detail_snapshot(monkeypatch, tmp_path: Path) -> None:
    args = _args(tmp_path, "execute_card")
    args.fast_open_detail = True
    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True)
    state = {
        "contract_version": runner.STATE_CONTRACT,
        "run_id": "seek_debug",
        "run_dir": str(run_dir),
        "phase": "extract_cards",
        "step_index": 3,
        "cards_payload": {
            "jobs": [
                {
                    "job_id": "new_job",
                    "title": "Graduate Software Engineer",
                    "company": "Local Co",
                    "location": "Auckland",
                    "card_bbox": {"x": 100, "y": 200, "w": 300, "h": 140},
                }
            ]
        },
        "detail": {
            "job_id": "old_job",
            "title": "Software Engineer Specialist - Integration",
            "company": "AIA New Zealand",
            "description_sections": [{"index": 0, "role": "batch_ocr", "text": "Old detail"}],
        },
        "steps": [],
        "safety": runner._default_safety(),
    }
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")

    monkeypatch.setattr(runner, "_read_json", lambda _path: None)
    monkeypatch.setattr(
        runner,
        "_capture",
        lambda *_args, **_kwargs: {"image_path": "capture.png", "payload": {"image_width": 2560, "image_height": 1400}},
    )
    monkeypatch.setattr(
        runner,
        "_execute_job_card",
        lambda *_args, **_kwargs: {"opened": True, "execute_response": {"success": True}},
    )
    monkeypatch.setattr(runner, "_execute_debug_artifacts", lambda **_kwargs: {"ui_diff_verification": {"status": "skipped"}})

    payload = runner.run_step(args)

    state_after = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert payload["status"] == "ok"
    assert state_after["current_job"]["job_id"] == "new_job"
    assert state_after["detail"]["job_id"] == "new_job"
    assert state_after["detail"]["title"] == "Graduate Software Engineer"
    assert state_after["detail"]["runtime_detail_snapshot"]["source"] == "open_detail_seed"


def test_execute_apply_entry_skipped_does_not_wait_for_application_flow(monkeypatch, tmp_path: Path) -> None:
    args = _args(tmp_path, "execute_apply_entry")
    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True)
    state = {
        "contract_version": runner.STATE_CONTRACT,
        "run_id": "seek_debug",
        "run_dir": str(run_dir),
        "phase": "match",
        "step_index": 8,
        "current_job": {"job_id": "job1", "title": "Engineering Manager", "company": "Halter"},
        "detail": {
            "job_id": "job1",
            "title": "Engineering Manager",
            "company": "Halter",
            "apply_button_state": {"visible": True, "label": "Apply", "source": "read_detail_batch_ocr"},
        },
        "match_decision": {"decision": "strong_apply", "job_id": "job1"},
        "steps": [],
        "safety": runner._default_safety(),
    }
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")

    monkeypatch.setattr(runner, "_read_json", lambda _path: None)
    monkeypatch.setattr(runner, "load_candidate_profile", lambda _path: None)
    monkeypatch.setattr(
        runner,
        "_capture",
        lambda *_args, **_kwargs: {"image_path": "capture.png", "payload": {"image_width": 2560, "image_height": 1400}},
    )
    monkeypatch.setattr(
        runner,
        "_execute_apply_entry",
        lambda *_args, **_kwargs: {
            "status": "skipped",
            "eligible": False,
            "executed": False,
            "application_flow_started": False,
            "stop_reason": "seek_standard_apply_is_external_use_quick_apply_only",
        },
    )

    def fail_wait(*_args, **_kwargs):
        raise AssertionError("skipped Apply Entry must not wait for application flow")

    monkeypatch.setattr(runner, "_wait_for_application_flow_after_apply", fail_wait)

    payload = runner.run_step(args)

    assert payload["status"] == "skipped"
    assert payload["post_apply_wait"]["status"] == "not_requested"
    assert payload["apply_entry"]["stop_reason"] == "seek_standard_apply_is_external_use_quick_apply_only"


def test_read_detail_batch_can_start_from_learned_region_without_verify(monkeypatch, tmp_path: Path) -> None:
    args = _args(tmp_path, "read_detail_batch")
    args.batch_max_captures = 1
    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True)
    state = {
        "contract_version": runner.STATE_CONTRACT,
        "run_id": "seek_debug",
        "run_dir": str(run_dir),
        "phase": "execute_card",
        "step_index": 3,
        "current_job": {
            "title": "Graduate Software Engineer",
            "company": "Example Ltd",
            "location": "Auckland",
        },
        "steps": [],
        "safety": runner._default_safety(),
    }
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    ocr_calls: list[dict] = []

    monkeypatch.setattr(runner, "_read_json", lambda _path: None)
    monkeypatch.setattr(
        runner,
        "_runtime_state",
        lambda _base_url, _timeout: {
            "payload": {"rect": {"left": 0, "top": 0, "right": 2560, "bottom": 1400}},
            "response": {"success": True},
        },
    )

    def fake_ocr(_base_url, *, roi, _timeout=None, timeout=None):
        ocr_calls.append(roi)
        return {
            "image_path": f"roi-{len(ocr_calls)}.png",
            "trace_path": f"ocr-{len(ocr_calls)}.json",
            "ocr_result": {"items": [{"text": "Graduate Software Engineer"}, {"text": "C# and API integration"}]},
        }

    monkeypatch.setattr(runner, "_ocr_region", fake_ocr)

    payload = runner.run_step(args)

    assert payload["status"] == "ok"
    assert payload["target_container_id"] == "seek:job_detail"
    assert payload["target_bbox"]["w"] > 500
    assert ocr_calls[0]["width"] == payload["target_bbox"]["w"]
    state_after = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state_after["detail"]["title"] == "Graduate Software Engineer"
    assert any("C# and API integration" in item["text"] for item in state_after["detail"]["description_sections"])
    assert state_after["next_allowed_steps"] == ["match", "read_detail_batch"]


def test_read_detail_batch_confirms_no_effect_before_bottom(monkeypatch) -> None:
    ocr_index = 0
    scroll_calls: list[dict] = []

    def fake_ocr(_base_url, *, roi, timeout):
        nonlocal ocr_index
        ocr_index += 1
        return {
            "image_path": f"roi-{ocr_index}.png",
            "trace_path": f"ocr-{ocr_index}.json",
            "ocr_result": {"items": [{"text": "Same visible line"}]},
        }

    def fake_post(_base_url, endpoint, payload, _timeout):
        scroll_calls.append(payload)
        assert endpoint == "/action/scroll"
        return {
            "success": True,
            "data": {
                "result": {
                    "trace_path": f"scroll-{len(scroll_calls)}.json",
                    "target_container_id": "seek:job_detail",
                    "scroll_effect_validation": {"status": "no_effect", "non_target_panes_stable": True},
                }
            },
        }

    monkeypatch.setattr(runner, "_ocr_region", fake_ocr)
    monkeypatch.setattr(runner, "_post_json", fake_post)

    batch = runner._read_detail_batch(
        "http://runtime.test",
        timeout=5.0,
        detail={"detail_container": {"bbox": {"x": 10, "y": 20, "w": 300, "h": 500}}},
        learned_artifact=None,
        wheel_clicks=9,
        max_captures=3,
        stop_after_no_new_content=2,
    )

    assert batch["stop_reason"] == "no_new_content"
    assert batch["capture_count"] == 3
    assert len(scroll_calls) == 2
    assert scroll_calls[0]["wheel_clicks"] == 9
    assert scroll_calls[1]["wheel_clicks"] > scroll_calls[0]["wheel_clicks"]


def test_close_old_seek_windows_detect_only_does_not_close(monkeypatch, tmp_path: Path) -> None:
    args = _args(tmp_path, "close_old_seek_windows")
    args.allow_close_windows = False
    monkeypatch.setattr(
        runner,
        "_apps_snapshot",
        lambda _base_url, _timeout: {
            "success": True,
            "data": {
                "windows": [
                    {"handle": 10, "title": "Software Engineer Jobs in All Auckland - Microsoft Edge", "process_name": "msedge.exe"},
                    {"handle": 11, "title": "ChatGPT", "process_name": "msedge.exe"},
                ]
            },
        },
    )
    monkeypatch.setattr(runner, "_close_top_level_windows", lambda _windows: (_ for _ in ()).throw(AssertionError("must not close")))

    payload = runner.run_step(args)

    assert payload["old_seek_windows_detected"] == [
        {"handle": 10, "title": "Software Engineer Jobs in All Auckland - Microsoft Edge", "process_name": "msedge.exe"}
    ]
    assert payload["closed_windows"] == []
    assert payload["close_policy"] == "detect_only"


def test_close_old_seek_windows_skips_multi_tab_browser_window(monkeypatch) -> None:
    monkeypatch.setattr(runner.sys, "platform", "win32")
    closed = runner._close_top_level_windows(
        [
            {
                "handle": 10,
                "title": "Software Engineer Jobs in All Auckland, Job Vacancies - Jun 2026 | SEEK 和另外 3 个页面 - Microsoft Edge",
                "process_name": "msedge.exe",
            }
        ]
    )

    assert closed == [
        {
            "handle": 10,
            "title": "Software Engineer Jobs in All Auckland, Job Vacancies - Jun 2026 | SEEK 和另外 3 个页面 - Microsoft Edge",
            "post_message_sent": False,
            "skipped": True,
            "skip_reason": "multi_tab_browser_window",
        }
    ]


def test_open_seek_debug_requests_new_browser_window(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    def fake_post_json(base_url, endpoint, payload, timeout):
        calls.append((endpoint, payload))
        return {"success": True, "data": {"result": {"bound_window": {"title": "SEEK"}}}}

    monkeypatch.setattr(runner, "_post_json", fake_post_json)

    response = runner._open_seek_debug(
        "http://runtime.test",
        url="https://nz.seek.com/software-engineer-jobs/in-All-Auckland",
        app_name="edge",
        timeout=5.0,
    )

    assert response["success"] is True
    assert calls[0][0] == "/apps/open"
    assert calls[0][1]["command"] == ["msedge.exe", "--new-window"]
    assert calls[0][1]["url"].startswith("https://nz.seek.com/")
    assert calls[0][1]["bind_after_open"] is True


def test_bind_and_resize_verify_records_coordinate_space(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[str, dict]] = []
    args = _args(tmp_path, "bind_and_resize_verify")
    args.window_width = 1400
    args.window_height = 950

    states = [
        {
            "bound": True,
            "window_title": "Software Engineer Jobs in All Auckland - Microsoft Edge",
            "process_name": "msedge.exe",
            "is_active": True,
            "rect": {"left": 0, "top": 0, "right": 1200, "bottom": 900},
        },
        {
            "bound": True,
            "window_title": "Software Engineer Jobs in All Auckland - Microsoft Edge",
            "process_name": "msedge.exe",
            "is_active": True,
            "rect": {"left": 0, "top": 0, "right": 1400, "bottom": 950},
        },
    ]

    def fake_runtime_state(_base_url, _timeout):
        return {"response": {"success": True}, "payload": states.pop(0)}

    def fake_resize(_base_url, *, width, height, timeout):
        calls.append(("/session/resize_bound_window", {"width": width, "height": height, "timeout": timeout}))
        return {"success": True, "data": {"result": {"trace_path": "resize.json"}}}

    def fake_bind(_base_url, *, app_name, timeout):
        calls.append(("/session/bind_window", {"app_name": app_name, "timeout": timeout}))
        return {"success": True, "data": {"result": {"trace_path": "bind.json"}}}

    monkeypatch.setattr(runner, "_read_json", lambda _path: None)
    monkeypatch.setattr(runner, "_bind_seek_debug_window", fake_bind)
    monkeypatch.setattr(runner, "_runtime_state", fake_runtime_state)
    monkeypatch.setattr(runner, "_resize_bound_window", fake_resize)
    monkeypatch.setattr(runner, "_capture", lambda _base_url, _timeout: {"image_path": "after.png", "payload": {}})

    payload = runner.run_step(args)

    assert calls == [
        ("/session/bind_window", {"app_name": "edge", "timeout": 5.0}),
        ("/session/resize_bound_window", {"width": 1400, "height": 950, "timeout": 5.0}),
    ]
    assert payload["status"] == "ok"
    verification = payload["bound_window_verification"]
    assert verification["process_is_external_browser"] is True
    assert verification["title_contains_seek"] is True
    assert verification["coordinate_window_size"] == {"width": 1400, "height": 950}
    state = json.loads((tmp_path / "seek_debug" / "state.json").read_text(encoding="utf-8"))
    assert state["coordinate_window_size"] == {"width": 1400, "height": 950}
    assert state["next_allowed_steps"] == ["capture", "extract_cards"]


def test_apply_entry_step_requires_completed_match_context(tmp_path: Path) -> None:
    args = _args(tmp_path, "dry_run_apply_entry")

    try:
        runner.run_step(args)
    except runner.SeekTraversalError as exc:
        assert "apply entry requires completed match context" in str(exc)
    else:
        raise AssertionError("expected missing context error")


def test_continue_application_flow_recovers_context_from_learned_artifact(monkeypatch, tmp_path: Path) -> None:
    args = _args(tmp_path, "continue_application_flow")
    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True)
    profile_path = run_dir / "candidate_profile.json"
    profile_path.write_text(json.dumps({"contract_version": "candidate_profile_v1"}), encoding="utf-8")
    source_record_path = run_dir / "application_fill_record.json"
    source_record_path.write_text(
        json.dumps(
            {
                "contract_version": "seek_application_fill_record_v1",
                "apply_url": "https://nz.seek.com/job/92822270/apply?sol=abc",
                "job": {"company": "Sourced | IT Recruitment Specialists", "location": "Christchurch Central, Canterbury"},
                "filled_content": {
                    "cover_letter": "Create customer-centric solutions with React, SQL, API, and frontend evidence."
                },
            }
        ),
        encoding="utf-8",
    )
    artifact_path = run_dir / "application_artifact.json"
    artifact_path.write_text(
        json.dumps(
            {
                "contract_version": "seek_application_flow_artifact_v1",
                "source": {"application_fill_record_path": str(source_record_path)},
                "job": {
                    "job_id": "seek_job_92822270",
                    "title": "Software Engineer (Business Systems)",
                    "company": "Sourced | IT Recruitment Specialists",
                    "apply_url": "https://nz.seek.com/job/92822270/apply?sol=abc",
                },
            }
        ),
        encoding="utf-8",
    )
    replay_path = run_dir / "application_replay.json"
    replay_path.write_text(
        json.dumps(
            {
                "contract_version": "seek_application_flow_replay_report_v1",
                "status": "pass",
                "summary": {"can_run_live_strict_replay": True, "final_submit_forbidden": True},
                "timeline": [
                    {
                        "transition_id": "seek_apply:block_final_submit",
                        "from_state": "seek_apply:review_and_submit",
                        "to_state": "seek_apply:final_submit_blocked",
                        "action": "stop_before_final_submit",
                        "low_level_action_type": "guard",
                        "allows_final_submit": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    args.candidate_profile = str(profile_path)
    args.learned_artifact = str(artifact_path)
    args.application_flow_replay = str(replay_path)
    flow_state = {
        "contract_version": "seek_application_flow_state_v1",
        "status": "ok",
        "current_step": "review_and_submit",
        "state_type": "final_submit_visible",
        "application_form_inventory": {"contract_version": "application_form_inventory_v1", "fields": [], "actions": []},
    }

    monkeypatch.setattr(runner, "_capture", lambda _base_url, _timeout: {"image_path": "capture.png", "payload": {}})
    monkeypatch.setattr(runner, "_observe", lambda *_args, **_kwargs: {"trace_path": "observe.json"})
    monkeypatch.setattr(runner, "assess_seek_application_flow_state", lambda *_args, **_kwargs: flow_state)
    monkeypatch.setattr(runner, "build_seek_apply_flow_decision", lambda _flow_state: {"decision": "stop", "reason": "review_boundary"})

    payload = runner.run_step(args)

    assert payload["application_context"] == {
        "source": "learned_application_artifact",
        "recovered": True,
        "final_submit_authorized": False,
    }
    assert payload["status"] == "blocked_need_user_or_gpt_decision"
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["current_job"]["job_id"] == "seek_job_92822270"
    assert state["detail"]["requirements"] == ["Create customer-centric solutions with React, SQL, API, and frontend evidence"]
    assert state["match_decision"]["artifact_context_only"] is True
    assert state["match_decision"]["final_submit_authorized"] is False
    assert state["match_decision"]["positive_evidence"] == [
        "Create customer-centric solutions with React, SQL, API, and frontend evidence."
    ]


def test_extract_final_review_writes_reconciliation_without_clicks(monkeypatch, tmp_path: Path) -> None:
    args = _args(tmp_path, "extract_final_review")
    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True)
    record_path = run_dir / "application_fill_record.json"
    record_path.write_text(
        json.dumps(
            {
                "contract_version": "seek_application_fill_record_v1",
                "stage": "review_before_submit",
                "submit_clicks": 0,
                "final_submissions": 0,
                "filled_content": {
                    "resume": "WENQING JI.pdf (SEEK default/selected resume)",
                    "cover_letter": (
                        "Dear Hiring Team,\n\n"
                        "I am interested because the role aligns with React, SQL, and careful testing.\n\n"
                        "Kind regards,\nWenqing Ji"
                    ),
                    "employer_questions": [
                        {"question": "Can you start immediately or within 1-2 weeks?", "answer": "Yes"},
                    ],
                    "seek_profile_mutation": "none",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    args.application_fill_record = str(record_path)

    monkeypatch.setattr(runner, "_capture", lambda _base_url, _timeout: {"image_path": "review.png", "payload": {}})
    monkeypatch.setattr(
        runner,
        "_observe",
        lambda *_args, **_kwargs: {
            "contract_version": "screen_observation_v1",
            "trace_path": "review-observe.json",
            "screen_inventory": {
                "available_actions": [{"label": "Submit application"}],
                "page_elements": [
                    {"text": "Review and submit"},
                    {"text": "WENQING JI.pdf"},
                    {"text": "I am interested because the role aligns with React, SQL, and careful testing."},
                    {"text": "Can you start immediately or within 1-2 weeks?"},
                    {"text": "Yes"},
                    {"text": "Submit application"},
                ],
            },
        },
    )

    payload = runner.run_step(args)

    assert payload["status"] == "pass"
    assert payload["submit_clicks"] == 0
    assert payload["final_submissions"] == 0
    assert payload["review_reconciliation"]["status"] == "pass"
    extraction_path = run_dir / "final_review_extraction.json"
    assert extraction_path.exists()
    extraction = json.loads(extraction_path.read_text(encoding="utf-8"))
    assert extraction["contract_version"] == "seek_final_review_extraction_v1"
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["final_review_extraction_path"] == str(extraction_path)
    assert state["next_allowed_steps"] == ["capture"]


def test_application_flow_context_refreshes_stale_artifact_context(tmp_path: Path) -> None:
    source_record_path = tmp_path / "application_fill_record.json"
    source_record_path.write_text(
        json.dumps(
            {
                "contract_version": "seek_application_fill_record_v1",
                "job": {"company": "Sourced", "location": "Auckland"},
                "filled_content": {"cover_letter": "Write clear modular code with React and SQL evidence."},
            }
        ),
        encoding="utf-8",
    )
    artifact = {
        "contract_version": "seek_application_flow_artifact_v1",
        "source": {"application_fill_record_path": str(source_record_path)},
        "job": {"job_id": "seek_job_1", "title": "Software Engineer", "company": "Sourced"},
    }
    state = {
        "current_job": {"job_id": "seek_job_1", "title": "Software Engineer", "source": "seek_application_flow_artifact_v1"},
        "detail": {"job_id": "seek_job_1", "title": "Software Engineer", "source": "seek_application_flow_artifact_v1"},
        "match_decision": {"decision": "strong_apply", "artifact_context_only": True},
    }

    _job, detail, decision, context = runner._require_application_flow_context(state, learned_artifact=artifact)

    assert context["refreshed_stale_state_context"] is True
    assert detail["requirements"] == ["Write clear modular code with React and SQL evidence"]
    assert decision["positive_evidence"] == ["Write clear modular code with React and SQL evidence."]
    assert state["detail"]["requirements"] == ["Write clear modular code with React and SQL evidence"]


def test_dry_run_apply_entry_requires_allow_maybe_for_maybe_decision(monkeypatch, tmp_path: Path) -> None:
    args = _args(tmp_path, "dry_run_apply_entry")
    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True)
    state = {
        "contract_version": runner.STATE_CONTRACT,
        "run_id": "seek_debug",
        "run_dir": str(run_dir),
        "created_at": "now",
        "updated_at": "now",
        "phase": "match",
        "step_index": 3,
        "current_job": _cards_observation()["screen_inventory"]["available_actions"][0] | {
            "title": "Senior Android Developer",
            "company": "Fiserv",
            "location": "Auckland",
        },
        "detail": {
            "title": "Senior Android Developer",
            "company": "Fiserv",
            "location": "Auckland",
            "apply_button_state": {"visible": True, "label": "Apply", "click_point": {"x": 800, "y": 500}},
        },
        "match_decision": {"decision": "maybe_apply", "job_id": "job1"},
        "steps": [],
        "safety": {},
    }
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    calls: list[dict] = []

    def fake_execute_apply_entry(*_args, **kwargs):
        calls.append(kwargs)
        return {
            "contract_version": "seek_apply_entry_attempt_v1",
            "status": "skipped",
            "eligible": False,
            "executed": False,
            "stop_reason": "decision_not_eligible_for_apply_entry",
        }

    monkeypatch.setattr(runner, "_read_json", lambda _path: None)
    monkeypatch.setattr(
        runner,
        "load_candidate_profile",
        lambda _path: {
            "contract_version": "candidate_profile_v1",
            "experience_summary": "Built web applications and REST APIs.",
            "skills": ["React", "SQL", "Frontend"],
            "work_rights_summary": "Post-study Open Work Visa valid 2026-04-25 to 2029-04-25.",
        },
    )
    monkeypatch.setattr(runner, "_capture", lambda _base_url, _timeout: {"image_path": "before.png", "payload": {}})
    monkeypatch.setattr(runner, "_execute_apply_entry", fake_execute_apply_entry)

    payload = runner.run_step(args)

    assert calls[0]["execute_clicks"] is False
    assert calls[0]["allow_maybe_apply"] is False
    assert payload["apply_entry"]["status"] == "skipped"
    assert payload["apply_entry"]["stop_reason"] == "decision_not_eligible_for_apply_entry"
    saved_state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert saved_state["next_allowed_steps"] == ["match", "extract_cards"]


def test_dry_run_apply_entry_allows_maybe_with_explicit_approval(monkeypatch, tmp_path: Path) -> None:
    args = _args(tmp_path, "dry_run_apply_entry")
    args.allow_maybe_apply = True
    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True)
    state = {
        "contract_version": runner.STATE_CONTRACT,
        "run_id": "seek_debug",
        "run_dir": str(run_dir),
        "created_at": "now",
        "updated_at": "now",
        "phase": "match",
        "step_index": 3,
        "current_job": {"title": "Senior Android Developer", "company": "Fiserv", "location": "Auckland"},
        "detail": {
            "title": "Senior Android Developer",
            "company": "Fiserv",
            "location": "Auckland",
            "apply_button_state": {"visible": True, "label": "Apply", "click_point": {"x": 800, "y": 500}},
        },
        "match_decision": {"decision": "maybe_apply", "job_id": "job1"},
        "steps": [],
        "safety": {},
    }
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    calls: list[dict] = []

    def fake_execute_apply_entry(*_args, **kwargs):
        calls.append(kwargs)
        return {
            "contract_version": "seek_apply_entry_attempt_v1",
            "status": "dry_run_ready",
            "eligible": True,
            "executed": False,
            "approved_plan_id": "plan-1",
            "dry_run_response": {"trace_path": "dry.json", "final_submit_guard": {"enabled": True}},
        }

    monkeypatch.setattr(runner, "_read_json", lambda _path: None)
    monkeypatch.setattr(
        runner,
        "load_candidate_profile",
        lambda _path: {
            "contract_version": "candidate_profile_v1",
            "experience_summary": "Built web applications and REST APIs.",
            "skills": ["React", "SQL", "Frontend"],
            "work_rights_summary": "Post-study Open Work Visa valid 2026-04-25 to 2029-04-25.",
        },
    )
    monkeypatch.setattr(runner, "_capture", lambda _base_url, _timeout: {"image_path": "before.png", "payload": {}})
    monkeypatch.setattr(runner, "_execute_apply_entry", fake_execute_apply_entry)

    payload = runner.run_step(args)

    assert calls[0]["execute_clicks"] is False
    assert calls[0]["allow_maybe_apply"] is True
    assert payload["apply_entry"]["status"] == "dry_run_ready"
    saved_state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert saved_state["next_allowed_steps"] == ["execute_apply_entry", "match"]


def test_execute_apply_entry_requires_allow_maybe_for_maybe_decision(monkeypatch, tmp_path: Path) -> None:
    args = _args(tmp_path, "execute_apply_entry")
    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True)
    state = {
        "contract_version": runner.STATE_CONTRACT,
        "run_id": "seek_debug",
        "run_dir": str(run_dir),
        "created_at": "now",
        "updated_at": "now",
        "phase": "match",
        "step_index": 3,
        "current_job": {"title": "Senior Android Developer", "company": "Fiserv", "location": "Auckland"},
        "detail": {
            "title": "Senior Android Developer",
            "company": "Fiserv",
            "location": "Auckland",
            "apply_button_state": {"visible": True, "label": "Apply", "click_point": {"x": 800, "y": 500}},
        },
        "match_decision": {"decision": "maybe_apply", "job_id": "job1"},
        "steps": [],
        "safety": {},
    }
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    calls: list[dict] = []

    def fake_execute_apply_entry(*_args, **kwargs):
        calls.append(kwargs)
        return {
            "contract_version": "seek_apply_entry_attempt_v1",
            "status": "skipped",
            "eligible": False,
            "executed": False,
            "stop_reason": "decision_not_eligible_for_apply_entry",
        }

    monkeypatch.setattr(
        runner,
        "load_candidate_profile",
        lambda _path: {
            "contract_version": "candidate_profile_v1",
            "experience_summary": "Built web applications and REST APIs.",
            "skills": ["React", "SQL", "Frontend"],
            "work_rights_summary": "Post-study Open Work Visa valid 2026-04-25 to 2029-04-25.",
        },
    )
    monkeypatch.setattr(runner, "_capture", lambda _base_url, _timeout: {"image_path": "shot.png", "payload": {}})
    monkeypatch.setattr(runner, "_execute_apply_entry", fake_execute_apply_entry)

    payload = runner.run_step(args)

    assert calls[0]["execute_clicks"] is True
    assert calls[0]["allow_maybe_apply"] is False
    assert payload["apply_entry"]["stop_reason"] == "decision_not_eligible_for_apply_entry"


def test_execute_apply_entry_reuses_apply_flow_state_without_fixed_sleep(monkeypatch, tmp_path: Path) -> None:
    args = _args(tmp_path, "execute_apply_entry")
    args.allow_maybe_apply = True
    args.post_apply_capture_wait_seconds = 2.5
    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True)
    state = {
        "contract_version": runner.STATE_CONTRACT,
        "run_id": "seek_debug",
        "run_dir": str(run_dir),
        "phase": "match",
        "step_index": 0,
        "current_job": {"job_id": "job1", "title": "Senior Android Developer", "company": "Fiserv"},
        "detail": {"job_id": "job1", "title": "Senior Android Developer", "company": "Fiserv"},
        "match_decision": {"decision": "maybe_apply", "job_id": "job1"},
        "steps": [],
        "safety": runner._default_safety(),
        "next_allowed_steps": ["execute_apply_entry"],
    }
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    sleeps: list[float] = []
    captures: list[str] = []

    def fake_capture(_base_url, _timeout):
        image = "before.png" if not captures else "after.png"
        captures.append(image)
        return {"image_path": image, "payload": {}}

    monkeypatch.setattr(
        runner,
        "load_candidate_profile",
        lambda _path: {
            "contract_version": "candidate_profile_v1",
            "experience_summary": "Built web applications and REST APIs.",
            "skills": ["React", "SQL", "Frontend"],
            "work_rights_summary": "Post-study Open Work Visa valid 2026-04-25 to 2029-04-25.",
        },
    )
    monkeypatch.setattr(runner, "_capture", fake_capture)
    monkeypatch.setattr(runner.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(
        runner,
        "_execute_apply_entry",
        lambda *_args, **_kwargs: {
            "contract_version": "seek_apply_entry_attempt_v1",
            "status": "blocked_need_user_or_gpt_decision",
            "eligible": True,
            "executed": True,
            "application_flow_started": True,
            "application_flow_state": {
                "contract_version": "seek_application_flow_state_v1",
                "state_type": "cover_letter_field_detected",
                "current_step": "choose_documents",
            },
        },
    )

    payload = runner.run_step(args)

    assert sleeps == []
    assert captures == ["before.png", "after.png"]
    assert payload["after_image"] == "after.png"
    assert payload["post_apply_capture_wait_seconds"] == 2.5
    assert payload["post_apply_wait"]["status"] == "ready_from_apply_entry"
    assert payload["post_apply_wait"]["poll_count"] == 0
    saved_state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert saved_state["next_allowed_steps"] == ["continue_application_flow", "capture"]


def test_execute_apply_entry_recomputes_decision_from_post_wait_state(monkeypatch, tmp_path: Path) -> None:
    args = _args(tmp_path, "execute_apply_entry")
    args.allow_maybe_apply = True
    args.post_apply_capture_wait_seconds = 2.5
    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True)
    state = {
        "contract_version": runner.STATE_CONTRACT,
        "run_id": "seek_debug",
        "run_dir": str(run_dir),
        "phase": "match",
        "step_index": 0,
        "current_job": {"job_id": "job1", "title": "Software Engineer", "company": "AIA New Zealand"},
        "detail": {"job_id": "job1", "title": "Software Engineer", "company": "AIA New Zealand"},
        "match_decision": {"decision": "strong_apply", "job_id": "job1"},
        "steps": [],
        "safety": runner._default_safety(),
        "next_allowed_steps": ["execute_apply_entry"],
    }
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    captures: list[str] = []

    def fake_capture(_base_url, _timeout):
        image = "before.png" if not captures else "after.png"
        captures.append(image)
        return {"image_path": image, "payload": {}}

    monkeypatch.setattr(runner, "load_candidate_profile", lambda _path: {"contract_version": "candidate_profile_v1"})
    monkeypatch.setattr(runner, "_capture", fake_capture)
    monkeypatch.setattr(
        runner,
        "_execute_apply_entry",
        lambda *_args, **_kwargs: {
            "contract_version": "seek_apply_entry_attempt_v1",
            "status": "blocked_need_user_or_gpt_decision",
            "eligible": True,
            "executed": True,
            "application_flow_started": True,
            "stop_reason": "unknown_after_apply_blocked",
            "application_flow_state": {
                "contract_version": "seek_application_flow_state_v1",
                "state_type": "unknown_after_apply",
                "current_step": "unknown",
                "application_flow_started": True,
            },
            "apply_flow_decision": {
                "contract_version": "seek_apply_flow_decision_v1",
                "source_state_type": "unknown_after_apply",
                "reason": "unknown_application_state_blocked",
            },
        },
    )

    post_wait_state = {
        "contract_version": "seek_application_flow_state_v1",
        "state_type": "third_party_ats",
        "current_step": None,
        "application_flow_started": True,
        "final_submit_visible_blocker": {"contract_version": "final_submit_visible_blocker_v1", "blocked": False},
    }
    monkeypatch.setattr(
        runner,
        "_wait_for_application_flow_after_apply",
        lambda *_args, **_kwargs: {
            "contract_version": "seek_application_flow_wait_v1",
            "status": "ready_from_poll",
            "poll_count": 1,
            "application_flow_state": post_wait_state,
        },
    )

    payload = runner.run_step(args)

    assert payload["apply_entry"]["application_flow_state"]["state_type"] == "third_party_ats"
    assert payload["apply_entry"]["apply_flow_decision"]["source_state_type"] == "third_party_ats"
    assert payload["apply_entry"]["apply_flow_decision"]["reason"] == "third_party_ats_deferred"
    assert payload["apply_entry"]["stop_reason"] == "third_party_ats_deferred"
    saved_state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert saved_state["next_allowed_steps"] == ["execute_apply_entry", "match"]


def test_wait_for_application_flow_after_apply_polls_until_ready(monkeypatch) -> None:
    sleeps: list[float] = []
    observations = [
        {"trace_path": "trace-1.json", "image_path": "shot-1.png"},
        {"trace_path": "trace-2.json", "image_path": "shot-2.png"},
    ]
    flow_states = [
        {
            "contract_version": "seek_application_flow_state_v1",
            "state_type": "unknown_after_apply",
            "current_step": "unknown",
            "application_flow_started": False,
        },
        {
            "contract_version": "seek_application_flow_state_v1",
            "state_type": "application_form_detected",
            "current_step": "choose_documents",
            "application_flow_started": True,
        },
    ]

    def fake_observe(*_args, **_kwargs):
        return observations.pop(0)

    def fake_assess(_observation, *, source_job=None):
        assert source_job == {"title": "Engineer"}
        return flow_states.pop(0)

    monkeypatch.setattr(runner, "_observe", fake_observe)
    monkeypatch.setattr(runner, "assess_seek_application_flow_state", fake_assess)
    monkeypatch.setattr(runner.time, "sleep", lambda seconds: sleeps.append(seconds))

    result = runner._wait_for_application_flow_after_apply(
        "http://runtime.test",
        app_name="edge",
        source_job={"title": "Engineer"},
        initial_flow_state=None,
        timeout=5.0,
        max_wait_seconds=3.0,
        poll_interval_seconds=0.5,
    )

    assert result["status"] == "ready_from_poll"
    assert result["poll_count"] == 2
    assert result["trace_path"] == "trace-2.json"
    assert result["image_path"] == "shot-2.png"
    assert sleeps == [0.5]


def test_continue_application_flow_generates_plan_without_reclicking_apply(monkeypatch, tmp_path: Path) -> None:
    args = _args(tmp_path, "continue_application_flow")
    replay_path = tmp_path / "replay.json"
    replay_path.write_text(
        json.dumps(
            {
                "contract_version": "seek_application_flow_replay_report_v1",
                "status": "pass",
                "summary": {"can_run_live_strict_replay": True},
                "timeline": [
                        {
                            "transition_id": "seek_apply:fill_cover_letter",
                            "low_level_action_type": "type_text_and_gated_continue",
                            "requires_screenshot_before": True,
                        "requires_screenshot_after": True,
                        "requires_safe_fill_focus": True,
                        "requires_post_fill_verification": True,
                        "allows_profile_mutation": False,
                        "allows_final_submit": False,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    args.application_flow_replay = str(replay_path)
    args.fill_safe_fields = True
    args.allow_cover_letter_fill = True
    args.max_safe_fields_to_fill = 1
    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True)
    state = {
        "contract_version": runner.STATE_CONTRACT,
        "run_id": "seek_debug",
        "run_dir": str(run_dir),
        "phase": "application_flow",
        "step_index": 0,
        "current_job": {"job_id": "job1", "title": "AI Automation Engineer", "company": "Inde Technology"},
        "detail": {"job_id": "job1", "title": "AI Automation Engineer", "company": "Inde Technology"},
        "match_decision": {"decision": "strong_apply", "job_id": "job1"},
        "steps": [],
        "safety": runner._default_safety(),
        "next_allowed_steps": ["continue_application_flow"],
    }
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    calls: list[str] = []

    profile = {
        "contract_version": "candidate_profile_v1",
        "experience_summary": "Built web applications and REST APIs.",
        "skills": ["React", "SQL", "Frontend"],
        "work_rights_summary": "Post-study Open Work Visa valid 2026-04-25 to 2029-04-25.",
    }
    monkeypatch.setattr(runner, "load_candidate_profile", lambda _path: profile)
    monkeypatch.setattr(runner, "_capture", lambda *_args, **_kwargs: {"image_path": "shot.png", "payload": {}})
    monkeypatch.setattr(runner, "_observe", lambda *_args, **_kwargs: {"trace_path": "observe.json", "screen_inventory": {"page_elements": [{"text": "Cover letter"}], "available_actions": []}})
    monkeypatch.setattr(runner, "build_cover_letter_draft", lambda **_kwargs: {"status": "draft_only_not_pasted", "draft": "Dear hiring team..."})
    monkeypatch.setattr(runner, "build_application_answer_plan", lambda **_kwargs: {"status": "planned_only_not_filled", "answers": []})

    def fake_fill(*_args, **kwargs):
        calls.append("safe_fill")
        assert kwargs["execute_fill"] is True
        assert kwargs["allow_cover_letter_fill"] is True
        return {"contract_version": "safe_form_fill_attempt_v1", "status": "filled_until_review", "fields_filled": 1, "final_submissions": 0}

    monkeypatch.setattr(runner, "_safe_form_fill_attempt", fake_fill)
    monkeypatch.setattr(
        runner,
        "_safe_continue_after_fill",
        lambda *_args, **_kwargs: {
            "contract_version": "seek_safe_continue_after_fill_v1",
            "attempted": True,
            "executed": True,
            "continue_clicks": 1,
            "submit_clicks": 0,
            "final_submissions": 0,
            "status": "continued_to_next_step",
            "post_continue_application_flow_state": {
                "contract_version": "seek_application_flow_state_v1",
                "state_type": "screening_questions_detected",
                "final_submit_visible_blocker": {"blocked": False},
            },
        },
    )

    payload = runner.run_step(args)

    assert calls == ["safe_fill"]
    assert payload["step_name"] == "continue_application_flow"
    assert payload["cover_letter_draft"]["status"] == "draft_only_not_pasted"
    assert payload["application_answer_plan"]["status"] == "planned_only_not_filled"
    assert payload["safe_form_fill_attempt"]["fields_filled"] == 1
    assert payload["continue_after_fill"]["continue_clicks"] == 1
    assert payload["application_flow_state"]["state_type"] == "screening_questions_detected"
    assert payload["final_submission_performed"] is False
    assert payload["live_strict_replay_ready"] is True
    assert payload["selected_transition_id"] == "seek_apply:fill_cover_letter"
    assert payload["requires_safe_fill_focus"] is True
    assert payload["requires_post_fill_verification"] is True
    assert payload["next_allowed_steps"] == ["continue_application_flow", "capture"]


def test_continue_application_flow_records_employer_question_inventory(monkeypatch, tmp_path: Path) -> None:
    args = _args(tmp_path, "continue_application_flow")
    replay_path = tmp_path / "replay.json"
    replay_path.write_text(
        json.dumps(
            {
                "contract_version": "seek_application_flow_replay_report_v1",
                "status": "pass",
                "summary": {"can_run_live_strict_replay": True},
                "timeline": [
                    {
                        "transition_id": "seek_apply:answer_questions",
                        "low_level_action_type": "answer_employer_questions_and_continue",
                        "requires_screenshot_before": True,
                        "requires_screenshot_after": True,
                        "allows_profile_mutation": False,
                        "allows_final_submit": False,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    args.application_flow_replay = str(replay_path)
    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True)
    state = {
        "contract_version": runner.STATE_CONTRACT,
        "run_id": "seek_debug",
        "run_dir": str(run_dir),
        "phase": "application_flow",
        "step_index": 0,
        "current_job": {"job_id": "job1", "title": "Software Engineer", "company": "Sourced"},
        "detail": {"job_id": "job1", "title": "Software Engineer", "company": "Sourced"},
        "match_decision": {"decision": "strong_apply", "job_id": "job1"},
        "steps": [],
        "safety": runner._default_safety(),
        "next_allowed_steps": ["continue_application_flow"],
    }
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")

    observation = {
        "trace_path": "observe.json",
        "screen_reading": {
            "contract_version": "screen_reading_v1",
            "source_layers": {
                "windows_uia": {
                    "controls": [
                        {
                            "control_id": "uia_q1",
                            "name": "Do you have at least 1-2 years of experience in web application development?",
                            "control_type": "Text",
                            "bbox": {"x": 802, "y": 570, "w": 626, "h": 22},
                        },
                        {
                            "control_id": "uia_q1_yes",
                            "name": "Yes",
                            "control_type": "RadioButton",
                            "bbox": {"x": 792, "y": 594, "w": 45, "h": 45},
                        },
                        {
                            "control_id": "uia_q1_no",
                            "name": "No",
                            "control_type": "RadioButton",
                            "bbox": {"x": 792, "y": 646, "w": 45, "h": 45},
                        },
                        {
                            "control_id": "uia_q2",
                            "name": "Can you start immediately or within 1-2 weeks?",
                            "control_type": "Text",
                            "bbox": {"x": 802, "y": 724, "w": 626, "h": 22},
                        },
                        {
                            "control_id": "uia_q2_text",
                            "name": "",
                            "control_type": "Edit",
                            "bbox": {"x": 802, "y": 760, "w": 650, "h": 110},
                        },
                    ]
                }
            },
        },
    }

    profile = {
        "contract_version": "candidate_profile_v1",
        "experience_summary": "Built web applications and REST APIs.",
        "skills": ["React", "SQL", "Frontend"],
        "work_rights_summary": "Post-study Open Work Visa valid 2026-04-25 to 2029-04-25.",
    }
    monkeypatch.setattr(runner, "load_candidate_profile", lambda _path: profile)
    monkeypatch.setattr(runner, "_capture", lambda *_args, **_kwargs: {"image_path": "shot.png", "payload": {}})
    monkeypatch.setattr(runner, "_observe", lambda *_args, **_kwargs: observation)
    monkeypatch.setattr(
        runner,
        "assess_seek_application_flow_state",
        lambda *_args, **_kwargs: {
            "contract_version": "seek_application_flow_state_v1",
            "current_step": "answer_employer_questions",
            "state_type": "screening_questions_detected",
            "application_form_inventory": {
                "contract_version": "application_form_inventory_v1",
                "fields": [],
                "actions": [],
            },
            "final_submit_visible_blocker": {"blocked": False},
        },
    )
    monkeypatch.setattr(runner, "build_cover_letter_draft", lambda **_kwargs: {"status": "not_generated"})
    monkeypatch.setattr(runner, "build_application_answer_plan", lambda **_kwargs: {"status": "planned_only_not_filled"})
    monkeypatch.setattr(
        runner,
        "_safe_form_fill_attempt",
        lambda *_args, **_kwargs: {"contract_version": "safe_form_fill_attempt_v1", "status": "no_safe_known_fields", "fields_filled": 0, "final_submissions": 0},
    )

    payload = runner.run_step(args)

    inventory = payload["employer_question_inventory"]
    assert inventory["contract_version"] == "employer_question_inventory_v1"
    assert inventory["question_count"] == 2
    assert inventory["questions"][0]["answer_type"] == "radio_yes_no"
    assert [item["id"] for item in inventory["questions"][0]["control_candidates"]] == ["uia_q1_yes", "uia_q1_no"]
    assert inventory["questions"][1]["answer_type"] == "text_input"
    answer_plan = payload["employer_question_answer_plan"]
    assert answer_plan["contract_version"] == "employer_question_answer_plan_v1"
    assert answer_plan["answers"][0]["planned_answer"] == "Yes"
    assert answer_plan["answers"][0]["selection"]["selected_candidate"]["id"] == "uia_q1_yes"
    assert answer_plan["answers"][1]["planned_answer"] == "Yes, I can start immediately or within 1-2 weeks."
    preview = payload["employer_question_answer_preview"]
    assert preview["contract_version"] == "employer_question_answer_preview_v1"
    assert preview["status"] == "ready"
    assert preview["previews"][0]["target"]["action_type"] == "click"
    assert preview["previews"][0]["target"]["candidate"]["id"] == "uia_q1_yes"
    assert preview["previews"][1]["target"]["action_type"] == "type_text"


def test_safe_employer_question_fill_answers_mapped_questions_without_submit(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []
    preview = {
        "contract_version": "employer_question_answer_preview_v1",
        "status": "ready",
        "previews": [
            {
                "question_id": "q1",
                "question_text": "Which statement describes your right to work?",
                "planned_answer": "I have a graduate temporary work visa",
                "runner_decision": "allow",
                "target": {"action_type": "already_selected", "selected_value_evidence": {"candidate": {"id": "q1_value"}}},
            },
            {
                "question_id": "q2",
                "question_text": "Do you have at least 1-2 years of experience in web application development?",
                "planned_answer": "Yes",
                "runner_decision": "allow",
                "target": {
                    "action_type": "click",
                    "candidate": {"id": "q2_yes", "bbox": {"x": 100, "y": 200, "w": 40, "h": 40}},
                    "bbox": {"x": 100, "y": 200, "w": 40, "h": 40},
                },
            },
            {
                "question_id": "q3",
                "question_text": "Can you start immediately or within 1-2 weeks?",
                "planned_answer": "Yes, I can start immediately or within 1-2 weeks.",
                "runner_decision": "allow",
                "target": {
                    "action_type": "type_text",
                    "candidate": {"id": "q3_text", "bbox": {"x": 300, "y": 400, "w": 500, "h": 120}},
                    "bbox": {"x": 300, "y": 400, "w": 500, "h": 120},
                },
            },
        ],
    }

    def fake_post_json(_base_url, endpoint, payload, _timeout):
        calls.append((endpoint, payload))
        if endpoint == "/action/type_text":
            assert payload["submit"] is False
            assert payload["clear_existing"] is True
            return {
                "success": True,
                "message": "typed",
                "data": {
                    "result": {
                        "trace_path": "type.json",
                        "dry_run": False,
                        "text_length": len(payload["text"]),
                        "click_before_typing": payload["click_before_typing"],
                        "submit": payload["submit"],
                    }
                },
                "error": None,
            }
        assert endpoint == "/action/execute_confirmed_point"
        return {
            "success": True,
            "message": "ok",
            "data": {
                "result": {
                    "trace_path": "confirmed.json",
                    "confirmed_point": {"x": payload["x"], "y": payload["y"]},
                    "candidate_bbox": payload["bbox"],
                    "execution_path": {"dry_run": payload["dry_run"], "action_executed": not payload["dry_run"]},
                }
            },
            "error": None,
        }

    monkeypatch.setattr(runner, "_post_json", fake_post_json)

    result = runner._safe_employer_question_fill_attempt(
        "http://runtime.test",
        app_name="edge",
        answer_preview=preview,
        execute_fill=True,
        timeout=5.0,
    )

    assert result["status"] == "filled_until_review"
    assert result["answered_count"] == 3
    assert result["already_selected_count"] == 1
    assert result["clicks"] == 1
    assert result["typed_fields"] == 1
    assert result["submit_clicks"] == 0
    assert result["final_submissions"] == 0
    assert [endpoint for endpoint, _payload in calls] == [
        "/action/execute_confirmed_point",
        "/action/execute_confirmed_point",
        "/action/execute_confirmed_point",
        "/action/execute_confirmed_point",
        "/action/type_text",
    ]
    assert all(
        payload.get("dry_run") in {True, False}
        for endpoint, payload in calls
        if endpoint == "/action/execute_confirmed_point"
    )


def test_safe_employer_question_fill_partial_ready_questions_without_submit(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []
    preview = {
        "contract_version": "employer_question_answer_preview_v1",
        "status": "needs_user_review",
        "previews": [
            {
                "question_id": "q1",
                "question_text": "Which programming languages are you experienced in?",
                "planned_answer": ["JavaScript", "Python"],
                "runner_decision": "allow",
                "target": {
                    "action_type": "multi_click",
                    "targets": [
                        {
                            "candidate": {"id": "q1_js", "label": "JavaScript", "bbox": {"x": 100, "y": 200, "w": 160, "h": 36}},
                            "bbox": {"x": 100, "y": 200, "w": 160, "h": 36},
                        },
                        {
                            "candidate": {"id": "q1_py", "label": "Python", "bbox": {"x": 100, "y": 244, "w": 150, "h": 36}},
                            "bbox": {"x": 100, "y": 244, "w": 150, "h": 36},
                        },
                    ],
                },
            },
            {
                "question_id": "q2",
                "question_text": "What salary are you targeting?",
                "planned_answer": None,
                "runner_decision": "needs_user_review",
                "reject_reason": "blocked_sensitive",
                "target": None,
            },
        ],
    }

    def fake_post_json(_base_url, endpoint, payload, _timeout):
        calls.append((endpoint, payload))
        assert endpoint == "/action/execute_confirmed_point"
        return {
            "success": True,
            "message": "ok",
            "data": {
                "result": {
                    "trace_path": "confirmed.json",
                    "confirmed_point": {"x": payload["x"], "y": payload["y"]},
                    "candidate_bbox": payload["bbox"],
                    "execution_path": {"dry_run": payload["dry_run"], "action_executed": not payload["dry_run"]},
                }
            },
            "error": None,
        }

    monkeypatch.setattr(runner, "_post_json", fake_post_json)

    result = runner._safe_employer_question_fill_attempt(
        "http://runtime.test",
        app_name="edge",
        answer_preview=preview,
        execute_fill=True,
        timeout=5.0,
    )

    assert result["status"] == "partial_until_review"
    assert result["stop_reason"] == "some_employer_questions_need_review"
    assert result["answered_count"] == 1
    assert result["clicks"] == 2
    assert result["typed_fields"] == 0
    assert result["submit_clicks"] == 0
    assert result["final_submissions"] == 0
    assert result["blocked_questions"][0]["question_id"] == "q2"
    assert [endpoint for endpoint, _payload in calls] == [
        "/action/execute_confirmed_point",
        "/action/execute_confirmed_point",
        "/action/execute_confirmed_point",
        "/action/execute_confirmed_point",
    ]


def test_safe_continue_rejects_right_edge_floating_widget(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    monkeypatch.setattr(runner, "_runtime_state", lambda *_args, **_kwargs: {"payload": {"rect": {"left": 0, "top": 0, "right": 2560, "bottom": 1400}}})
    monkeypatch.setattr(runner.time, "sleep", lambda *_args, **_kwargs: None)

    def fake_post_json(_base_url, endpoint, payload, _timeout):
        calls.append((endpoint, payload))
        if endpoint == "/action/scroll":
            return {"success": True, "data": {"result": {"trace_path": "scroll.json"}}}
        assert endpoint == "/action/execute_recognition_plan"
        assert payload["dry_run"] is True
        return {
            "success": True,
            "data": {
                "result": {
                    "approved_plan_id": "plan-right-edge",
                    "selected_click_point": {"x": 2513, "y": 1081},
                    "trace_path": "dry.json",
                }
            },
        }

    monkeypatch.setattr(runner, "_post_json", fake_post_json)

    result = runner._safe_continue_after_fill("http://runtime.test", app_name="edge", timeout=5.0, from_step="update_seek_profile")

    assert result["status"] == "continue_target_rejected"
    assert result["stop_reason"] == "continue_target_outside_form_region"
    assert result["target_validation"]["reason"] == "right_floating_control_region"
    assert [endpoint for endpoint, _payload in calls].count("/action/execute_recognition_plan") == 4
    assert all(payload.get("dry_run") is True for endpoint, payload in calls if endpoint == "/action/execute_recognition_plan")


def test_safe_continue_rejects_prompt_candidate_over_profile_mutation_button(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    monkeypatch.setattr(runner, "_runtime_state", lambda *_args, **_kwargs: {"payload": {"rect": {"left": 0, "top": 0, "right": 1920, "bottom": 1080}}})
    monkeypatch.setattr(runner.time, "sleep", lambda *_args, **_kwargs: None)

    def fake_post_json(_base_url, endpoint, payload, _timeout):
        calls.append((endpoint, payload))
        if endpoint == "/action/scroll":
            return {"success": True, "data": {"result": {"trace_path": "scroll.json"}}}
        assert endpoint == "/action/execute_recognition_plan"
        assert payload["dry_run"] is True
        return {
            "success": True,
            "data": {
                "result": {
                    "approved_plan_id": "plan-profile-mutation",
                    "selected_click_point": {"x": 542, "y": 129},
                    "trace_path": "dry.json",
                    "pre_click_decision": {
                        "selected_candidate_id": "vista_direct_prompt",
                        "candidate_decisions": [
                            {
                                "candidate_id": "vista_direct_prompt",
                                "allowed": True,
                                "resolved_click_point": {
                                    "target_text": "Click only the visible SEEK application form Continue or Save and continue button",
                                    "target_role": "button",
                                    "bbox": {"x": 518, "y": 105, "w": 48, "h": 48},
                                },
                            },
                            {
                                "candidate_id": "candidate_add_role",
                                "allowed": False,
                                "resolved_click_point": {
                                    "target_text": "Add role",
                                    "target_role": "button",
                                    "bbox": {"x": 482, "y": 104, "w": 118, "h": 49},
                                },
                            },
                        ],
                    },
                }
            },
        }

    monkeypatch.setattr(runner, "_post_json", fake_post_json)

    result = runner._safe_continue_after_fill("http://runtime.test", app_name="edge", timeout=5.0, from_step="update_seek_profile")

    assert result["status"] == "continue_target_rejected"
    assert result["target_validation"]["reason"] == "profile_mutation_candidate_at_click_point"
    assert result["target_validation"]["selected_candidate_label"].startswith("click only the visible seek")
    assert all(payload.get("dry_run") is True for endpoint, payload in calls if endpoint == "/action/execute_recognition_plan")


def test_safe_continue_allows_prompt_candidate_when_visible_continue_overlaps(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    monkeypatch.setattr(runner, "_runtime_state", lambda *_args, **_kwargs: {"payload": {"rect": {"left": 0, "top": 0, "right": 1920, "bottom": 1080}}})
    monkeypatch.setattr(runner.time, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        runner,
        "_observe",
        lambda *_args, **_kwargs: {
            "trace_path": "observe.json",
            "screen_inventory": {"page_elements": [{"text": "Review and submit"}], "available_actions": []},
        },
    )
    monkeypatch.setattr(
        runner,
        "assess_seek_application_flow_state",
        lambda _observation: {
            "contract_version": "seek_application_flow_state_v1",
            "current_step": "review_and_submit",
            "state_type": "final_submit_visible",
            "final_submit_visible_blocker": {"blocked": True},
            "stop_reason": "final_submit_visible_stop_before_submission",
        },
    )

    def fake_post_json(_base_url, endpoint, payload, _timeout):
        calls.append((endpoint, payload))
        if endpoint == "/action/scroll":
            return {"success": True, "data": {"result": {"trace_path": "scroll.json"}}}
        assert endpoint == "/action/execute_recognition_plan"
        if payload["dry_run"] is True:
            return {
                "success": True,
                "data": {
                    "result": {
                        "approved_plan_id": "plan-continue",
                        "selected_click_point": {"x": 1072, "y": 900},
                        "trace_path": "dry.json",
                        "pre_click_decision": {
                            "selected_candidate_id": "vista_direct_prompt",
                            "candidate_decisions": [
                                {
                                    "candidate_id": "vista_direct_prompt",
                                    "allowed": True,
                                    "resolved_click_point": {
                                        "target_text": "Click only the visible SEEK application form Continue or Save and continue button",
                                        "target_role": "button",
                                        "bbox": {"x": 1048, "y": 876, "w": 48, "h": 48},
                                    },
                                },
                                {
                                    "candidate_id": "candidate_continue",
                                    "allowed": False,
                                    "resolved_click_point": {
                                        "target_text": "Continue",
                                        "target_role": "button",
                                        "bbox": {"x": 1000, "y": 876, "w": 144, "h": 48},
                                    },
                                },
                            ],
                        },
                    }
                },
            }
        return {
            "success": True,
            "data": {
                "result": {
                    "approved_plan_id": payload["approved_plan_id"],
                    "selected_click_point": {"x": 1072, "y": 900},
                    "trace_path": "execute.json",
                }
            },
        }

    monkeypatch.setattr(runner, "_post_json", fake_post_json)

    result = runner._safe_continue_after_fill("http://runtime.test", app_name="edge", timeout=5.0, from_step="update_seek_profile")

    assert result["status"] == "stopped_at_final_submit_visible"
    assert result["target_validation"]["reason"] == "visible_continue_candidate_at_click_point"
    assert result["continue_clicks"] == 1
    assert any(payload.get("dry_run") is False for endpoint, payload in calls if endpoint == "/action/execute_recognition_plan")


def test_safe_continue_reports_no_navigation_when_step_does_not_change(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    monkeypatch.setattr(runner, "_runtime_state", lambda *_args, **_kwargs: {"payload": {"rect": {"left": 0, "top": 0, "right": 2560, "bottom": 1400}}})
    monkeypatch.setattr(runner.time, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        runner,
        "_observe",
        lambda *_args, **_kwargs: {
            "trace_path": "observe.json",
            "screen_inventory": {"page_elements": [{"text": "Update SEEK Profile"}], "available_actions": []},
        },
    )
    monkeypatch.setattr(
        runner,
        "assess_seek_application_flow_state",
        lambda _observation: {
            "contract_version": "seek_application_flow_state_v1",
            "current_step": "update_seek_profile",
            "state_type": "application_form_detected",
            "final_submit_visible_blocker": {"blocked": False},
            "stop_reason": "application_form_detected_stop_before_form_fill",
        },
    )

    def fake_post_json(_base_url, endpoint, payload, _timeout):
        calls.append((endpoint, payload))
        if endpoint == "/action/scroll":
            return {"success": True, "data": {"result": {"trace_path": "scroll.json"}}}
        assert endpoint == "/action/execute_recognition_plan"
        if payload["dry_run"] is True:
            return {
                "success": True,
                "data": {
                    "result": {
                        "approved_plan_id": "plan-form-continue",
                        "selected_click_point": {"x": 1300, "y": 1160},
                        "trace_path": "dry.json",
                        "pre_click_decision": {
                            "selected_candidate_id": "continue_button",
                            "candidate_decisions": [
                                {
                                    "candidate_id": "continue_button",
                                    "allowed": True,
                                    "resolved_click_point": {
                                        "target_text": "Continue",
                                        "target_role": "button",
                                        "bbox": {"x": 1240, "y": 1130, "w": 120, "h": 60},
                                    },
                                }
                            ],
                        },
                    }
                },
            }
        return {
            "success": True,
            "data": {
                "result": {
                    "approved_plan_id": payload["approved_plan_id"],
                    "selected_click_point": {"x": 1300, "y": 1160},
                    "trace_path": "execute.json",
                }
            },
        }

    monkeypatch.setattr(runner, "_post_json", fake_post_json)

    result = runner._safe_continue_after_fill("http://runtime.test", app_name="edge", timeout=5.0, from_step="update_seek_profile")

    assert result["status"] == "continue_no_navigation"
    assert result["stop_reason"] == "continue_click_did_not_change_application_step"
    assert result["continue_clicks"] == 1
    assert any(payload.get("dry_run") is False for endpoint, payload in calls if endpoint == "/action/execute_recognition_plan")


def test_continue_application_flow_maps_review_to_final_submit_block(monkeypatch, tmp_path: Path) -> None:
    args = _args(tmp_path, "continue_application_flow")
    replay_path = tmp_path / "replay.json"
    replay_path.write_text(
        json.dumps(
            {
                "contract_version": "seek_application_flow_replay_report_v1",
                "status": "pass",
                "summary": {"can_run_live_strict_replay": True},
                "timeline": [
                    {
                        "transition_id": "seek_apply:block_final_submit",
                        "requires_screenshot_before": True,
                        "requires_screenshot_after": True,
                        "requires_safe_fill_focus": False,
                        "requires_post_fill_verification": False,
                        "allows_profile_mutation": False,
                        "allows_final_submit": False,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    args.application_flow_replay = str(replay_path)
    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True)
    state = {
        "contract_version": runner.STATE_CONTRACT,
        "run_id": "seek_debug",
        "run_dir": str(run_dir),
        "phase": "application_flow",
        "step_index": 0,
        "current_job": {"job_id": "job1", "title": "AI Automation Engineer", "company": "Inde Technology"},
        "detail": {"job_id": "job1", "title": "AI Automation Engineer", "company": "Inde Technology"},
        "match_decision": {"decision": "strong_apply", "job_id": "job1"},
        "steps": [],
        "safety": runner._default_safety(),
        "next_allowed_steps": ["continue_application_flow"],
    }
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    fill_calls: list[str] = []

    monkeypatch.setattr(runner, "load_candidate_profile", lambda _path: {"contract_version": "candidate_profile_v1"})
    monkeypatch.setattr(runner, "_capture", lambda *_args, **_kwargs: {"image_path": "shot.png", "payload": {}})
    monkeypatch.setattr(
        runner,
        "_observe",
        lambda *_args, **_kwargs: {
            "trace_path": "observe.json",
            "screen_inventory": {
                "page_elements": [
                    {"text": "Review your application | SEEK"},
                    {"text": "Review and submit"},
                    {"text": "Submit application"},
                ],
                "available_actions": [],
            },
        },
    )
    monkeypatch.setattr(runner, "_safe_form_fill_attempt", lambda *_args, **_kwargs: fill_calls.append("unsafe") or {})

    payload = runner.run_step(args)

    assert fill_calls == []
    assert payload["selected_transition_id"] == "seek_apply:block_final_submit"
    assert payload["application_replay_context"]["allows_final_submit"] is False
    assert payload["requires_safe_fill_focus"] is False
    assert payload["final_submission_performed"] is False
    assert payload["next_allowed_steps"] == ["capture"]
    saved_state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert saved_state["next_allowed_steps"] == ["capture"]


def test_left_results_visual_stability_uses_left_crop_not_detail_change(tmp_path: Path) -> None:
    before = tmp_path / "before.png"
    after = tmp_path / "after.png"
    left_cards = [(80, 120, 420, 230), (80, 260, 420, 370)]
    for path, detail_offset in [(before, 0), (after, 120)]:
        image = Image.new("RGB", (900, 700), "white")
        draw = ImageDraw.Draw(image)
        for box in left_cards:
            draw.rounded_rectangle(box, radius=8, outline=(20, 60, 180), width=3)
            draw.text((box[0] + 20, box[1] + 20), "Senior Android Developer", fill=(20, 20, 20))
        draw.rectangle((500, 80, 860, 650), outline=(180, 180, 180), width=2)
        draw.text((530, 150 - detail_offset), "detail paragraph A", fill=(20, 20, 20))
        draw.text((530, 300 - detail_offset), "detail paragraph B", fill=(20, 20, 20))
        image.save(path)
    detail = {"detail_container": {"bbox": {"x": 500, "y": 100, "w": 360, "h": 540}}}

    stability = runner._left_results_visual_stability(str(before), str(after), detail)

    assert stability["stable"] is True
    assert stability["crop_bbox"]["x"] == 0
    assert stability["crop_bbox"]["width"] == 480


def test_left_results_visual_stability_detects_left_results_scroll(tmp_path: Path) -> None:
    before = tmp_path / "before.png"
    after = tmp_path / "after.png"
    for path, left_offset in [(before, 0), (after, -180)]:
        image = Image.new("RGB", (900, 700), "white")
        draw = ImageDraw.Draw(image)
        for top in [120 + left_offset, 260 + left_offset, 400 + left_offset]:
            draw.rounded_rectangle((80, top, 420, top + 110), radius=8, outline=(20, 60, 180), width=3)
            draw.text((100, top + 20), "Visible job card", fill=(20, 20, 20))
        draw.rectangle((500, 80, 860, 650), outline=(180, 180, 180), width=2)
        draw.text((530, 150), "same detail", fill=(20, 20, 20))
        image.save(path)
    detail = {"detail_container": {"bbox": {"x": 500, "y": 100, "w": 360, "h": 540}}}

    stability = runner._left_results_visual_stability(str(before), str(after), detail)

    assert stability["stable"] is False
    assert stability["changed_pixel_ratio"] > stability["thresholds"]["changed_pixel_ratio_max"]


def test_application_flow_ready_rejects_generic_search_page_form_detection() -> None:
    assert (
        runner._application_flow_ready(
            {
                "application_flow_started": True,
                "state_type": "application_form_detected",
                "current_step": None,
            }
        )
        is False
    )


def test_application_flow_ready_accepts_explicit_seek_application_step() -> None:
    assert (
        runner._application_flow_ready(
            {
                "application_flow_started": True,
                "state_type": "application_form_detected",
                "current_step": "update_seek_profile",
            }
        )
        is True
    )
