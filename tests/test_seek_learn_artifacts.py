from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from PIL import Image, ImageDraw

from app.execute.available_actions import build_available_actions
from app.learn.path_graph_artifacts import build_seek_runtime_path_graph_export
from app.learn.visual_asset_crops import build_visual_asset_crop_export
from app.seek.learn_artifacts import build_seek_learn_artifacts


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "seek_export_learn_artifacts.py"
spec = importlib.util.spec_from_file_location("seek_export_learn_artifacts", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


def _event(index: int) -> dict:
    return {
        "index": index,
        "job_id": f"job-{index}",
        "card": {
            "title": f"Software Engineer {index}",
            "company": "Example",
            "location": "Auckland",
            "card_bbox": {"x": 24, "y": 400 + index * 10, "w": 410, "h": 220},
            "click_point": {"x": 220, "y": 510 + index * 10},
        },
        "card_click": {"opened": True, "failure_reason": None},
        "detail_read": {
            "title": f"Software Engineer {index}",
            "company": "Example",
            "complete": True,
            "scrolls": [{"target_container_id": "seek:job_detail", "target_pane": "job_detail"}],
        },
        "match_decision": {"decision": "strong_apply" if index == 0 else "maybe_apply", "score": 0.8},
    }


def _report_and_trace(jobs: int = 5) -> tuple[dict, dict]:
    accuracy = {
        "contract_version": "seek_mvp_accuracy_summary_v1",
        "jobs_seen": jobs,
        "jobs_opened": jobs,
        "jobs_fully_read": jobs,
        "post_click_layout_drift_count": 0,
        "wrong_scope_scroll_count": 0,
        "status": "pass",
    }
    report = {
        "contract_version": "seek_mvp_run_report_v1",
        "mode": "no_apply_traversal",
        "source_url": "https://www.seek.co.nz/software-engineer-jobs/in-All-Auckland",
        "jobs_seen": jobs,
        "jobs_opened": jobs,
        "jobs_fully_read": jobs,
        "submit_clicks": 0,
        "final_submissions": 0,
        "accuracy_summary": accuracy,
        "traversal_steps": [_event(index) for index in range(jobs)],
        "results_list_scrolls": [{"target_container_id": "seek:results_list", "target_pane": "results_list"}],
    }
    trace = {
        "contract_version": "seek_mvp_traversal_trace_v1",
        "source_report_contract": "seek_mvp_run_report_v1",
        "mode": "no_apply_traversal",
        "source_url": report["source_url"],
        "traversal_events": [_event(index) for index in range(jobs)],
        "scroll_events": [{"target_container_id": "seek:results_list", "target_pane": "results_list"}],
        "accuracy_summary": accuracy,
        "safety": {"submit_clicks": 0, "final_submissions": 0},
    }
    return report, trace


def _template(profile: dict, action_id: str) -> dict:
    return next(item for item in profile["action_templates"] if item["action_id"] == action_id)


def test_export_builds_learned_app_profile_and_path_graph_seed() -> None:
    report, trace = _report_and_trace()

    artifact = build_seek_learn_artifacts(report, trace=trace, report_path="report.json", trace_path="trace.json")

    assert artifact["contract_version"] == "seek_learn_artifact_export_v1"
    assert artifact["baseline"]["jobs_opened"] == 5
    assert artifact["baseline"]["jobs_fully_read"] == 5
    assert artifact["baseline"]["post_click_layout_drift_count"] == 0
    assert artifact["baseline"]["wrong_scope_scroll_count"] == 0
    assert artifact["baseline"]["final_submissions"] == 0

    profile = artifact["learned_app_profile"]
    assert profile["contract_version"] == "learned_app_profile_v1"
    assert profile["page_type"] == "seek_search_results_with_detail"
    open_card = _template(profile, "open_job_card")
    assert open_card["scroll_target"]["target_container_id"] == "seek:results_list"
    assert open_card["candidate_constraints"]["required_container_id"] == "seek:results_list"
    assert open_card["candidate_constraints"]["use_seeded_candidate"] is True
    read_detail = _template(profile, "read_detail")
    assert read_detail["scroll_target"]["target_container_id"] == "seek:job_detail"
    load_more = _template(profile, "load_more_results")
    assert load_more["scroll_target"]["target_container_id"] == "seek:results_list"
    assert profile["safety_policy"]["final_submit"] == "forbidden"

    seed = artifact["path_graph_seed"]
    assert seed["contract_version"] == "path_graph_seed_v1"
    assert [section["section_id"] for section in seed["sections"]] == [
        "top_search_area",
        "results_list",
        "job_detail",
        "job_card",
        "detail_header",
        "detail_body",
    ]
    assert seed["action_bindings"]["open_job_card"]["required_container_id"] == "seek:results_list"


def test_seek_artifact_converts_to_runtime_path_graph_skills_and_visual_assets() -> None:
    report, trace = _report_and_trace()
    seek_artifact = build_seek_learn_artifacts(report, trace=trace, report_path="report.json", trace_path="trace.json")

    runtime_export = build_seek_runtime_path_graph_export(seek_artifact)

    assert runtime_export["contract_version"] == "runtime_path_graph_export_v1"
    graph = runtime_export["runtime_path_graph"]
    assert graph["contract_version"] == "runtime_path_graph_v1"
    assert graph["coordinate_policy"]["bbox_is_guidance_not_authorization"] is True
    assert graph["coordinate_policy"]["click_point_requires_current_validation"] is True
    assert {state["state_id"] for state in graph["states"]} >= {
        "seek_search_results_empty_detail",
        "seek_search_results_with_selected_job",
        "seek_detail_scrolled",
        "seek_results_list_scrolled",
    }
    assert {transition["action_template_id"] for transition in graph["transitions"]} >= {
        "open_job_card",
        "read_detail",
        "load_more_results",
    }
    assert graph["entities"][0]["coordinate_evidence"]["requires_current_reobserve"] is True
    assert graph["entities"][0]["coordinate_evidence"]["requires_vista_or_equivalent_validation"] is True
    patterns = graph["path_patterns"]
    assert [pattern["contract_version"] for pattern in patterns] == ["list_detail_path_pattern_v1"]
    list_detail = patterns[0]
    assert list_detail["pattern_type"] == "split_list_detail"
    assert list_detail["list_container_id"] == "seek:results_list"
    assert list_detail["detail_container_id"] == "seek:job_detail"
    assert list_detail["open_action_template_id"] == "open_job_card"
    assert list_detail["read_detail_action_template_id"] == "read_detail"
    assert list_detail["load_more_action_template_id"] == "load_more_results"

    identity_mapping = list_detail["identity_mapping"]
    assert identity_mapping["primary_key_fields"][0] == {
        "list_field": "title",
        "detail_field": "title",
        "match_type": "text_similarity",
        "min_similarity": 0.82,
        "required": True,
    }
    assert "detail_body" in identity_mapping["reject_if_detail_title_source"]

    detail_policy = list_detail["detail_read_policy"]
    assert detail_policy["scroll_scope"] == "container"
    assert detail_policy["detail_container_id"] == "seek:job_detail"
    assert detail_policy["non_target_stability"]["stable_container_id"] == "seek:results_list"
    assert detail_policy["adaptive_scroll"]["stop_after_no_progress_count"] >= 2
    assert "wrong_scope_scroll_detected" in detail_policy["stop_reasons"]

    cleanup = list_detail["pre_action_cleanup"][0]
    assert cleanup["for_action_template_id"] == "open_job_card"
    assert "read_detail" in cleanup["when_previous_action_in"]
    assert cleanup["cleanup_action"] == "reset_detail_container_to_header"
    assert cleanup["target_container_id"] == "seek:job_detail"
    assert cleanup["verify_after_cleanup"]["detail_header_visible"] is True
    assert cleanup["verify_after_cleanup"]["wrong_scope_detected"] is False

    skills = runtime_export["learned_skills"]
    assert skills["contract_version"] == "learned_skill_v1"
    assert {skill["skill_id"] for skill in skills["skills"]} >= {
        "skill.open_card_from_list",
        "skill.scroll_container_until_new_content",
        "skill.read_detail_pane_until_bounded",
        "skill.block_final_submit",
        "skill.open_record_from_list_or_card",
        "skill.read_fixed_detail_pane_until_complete",
        "skill.scroll_target_container_until_progress_or_boundary",
        "skill.reset_detail_container_to_header",
        "skill.block_final_submit_or_write_action",
    }

    visual_assets = runtime_export["visual_assets"]
    assert visual_assets["contract_version"] == "visual_asset_v1"
    assert {asset["asset_id"] for asset in visual_assets["assets"]} >= {
        "seek:visual:apply_button",
        "seek:visual:save_icon",
        "seek:visual:job_card_shape",
        "seek:visual:detail_scrollbar",
    }
    assert visual_assets["matching_policy"]["asset_match_is_evidence_only"] is True


def test_runtime_path_graph_available_actions_hide_guarded_apply_by_default() -> None:
    report, trace = _report_and_trace()
    seek_artifact = build_seek_learn_artifacts(report, trace=trace)
    graph = build_seek_runtime_path_graph_export(seek_artifact)["runtime_path_graph"]

    available = build_available_actions(graph, current_state_id="seek_search_results_with_selected_job")

    assert available["contract_version"] == "available_actions_v1"
    assert available["artifact_assisted"] is True
    assert available["artifact_is_authorization"] is False
    action_ids = {action["action_template_id"] for action in available["actions"]}
    assert "read_detail" in action_ids
    assert "load_more_results" in action_ids
    assert "apply_entry" not in action_ids
    assert all(action["safety"]["final_submit_allowed"] is False for action in available["actions"])


def test_visual_asset_crop_export_hashes_representative_job_card(tmp_path) -> None:
    report, trace = _report_and_trace()
    seek_artifact = build_seek_learn_artifacts(report, trace=trace)
    runtime_export = build_seek_runtime_path_graph_export(seek_artifact)
    source_image_path = tmp_path / "seek-screen.png"
    image = Image.new("RGB", (900, 900), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((24, 400, 434, 620), fill=(240, 245, 255), outline=(35, 74, 180), width=4)
    image.save(source_image_path)

    crop_export = build_visual_asset_crop_export(
        runtime_export["runtime_path_graph"],
        runtime_export["visual_assets"],
        source_image_path=source_image_path,
        output_dir=tmp_path / "crops",
    )
    assets = {asset["asset_id"]: asset for asset in crop_export["visual_assets"]["assets"]}
    card_asset = assets["seek:visual:job_card_shape"]

    assert crop_export["contract_version"] == "visual_asset_crop_export_v1"
    assert crop_export["summary"]["crop_count"] == 1
    assert crop_export["summary"]["artifact_is_authorization"] is False
    assert Path(card_asset["source"]["crop_path"]).exists()
    assert card_asset["source"]["crop_status"] == "ok"
    assert len(card_asset["source"]["perceptual_hash"]) == 64
    assert card_asset["can_authorize_click"] is False
    assert assets["seek:visual:apply_button"]["source"]["crop_status"] == "pending_no_learned_bbox"
    assert crop_export["visual_assets"]["matching_policy"]["asset_can_authorize_click"] is False


def test_export_cli_writes_bundle_profile_and_path_graph(tmp_path, capsys) -> None:
    report, trace = _report_and_trace()
    report_path = tmp_path / "report.json"
    trace_path = tmp_path / "trace.json"
    out_path = tmp_path / "learned.json"
    profile_path = tmp_path / "profile.json"
    graph_path = tmp_path / "path-graph.json"
    runtime_graph_path = tmp_path / "runtime-graph.json"
    skills_path = tmp_path / "skills.json"
    visual_assets_path = tmp_path / "visual-assets.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    trace_path.write_text(json.dumps(trace, ensure_ascii=False), encoding="utf-8")

    exit_code = cli.main(
        [
            "--report",
            str(report_path),
            "--trace",
            str(trace_path),
            "--out",
            str(out_path),
            "--profile-out",
            str(profile_path),
            "--path-graph-out",
            str(graph_path),
            "--runtime-graph-out",
            str(runtime_graph_path),
            "--learned-skills-out",
            str(skills_path),
            "--visual-assets-out",
            str(visual_assets_path),
        ]
    )
    printed = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert printed["success"] is True
    assert printed["baseline"]["jobs_opened"] == 5
    assert json.loads(out_path.read_text(encoding="utf-8"))["contract_version"] == "seek_learn_artifact_export_v1"
    assert json.loads(profile_path.read_text(encoding="utf-8"))["contract_version"] == "learned_app_profile_v1"
    assert json.loads(graph_path.read_text(encoding="utf-8"))["contract_version"] == "path_graph_seed_v1"
    assert json.loads(runtime_graph_path.read_text(encoding="utf-8"))["contract_version"] == "runtime_path_graph_v1"
    assert json.loads(skills_path.read_text(encoding="utf-8"))["contract_version"] == "learned_skill_v1"
    assert json.loads(visual_assets_path.read_text(encoding="utf-8"))["contract_version"] == "visual_asset_v1"
    assert printed["runtime_path_graph_contract"] == "runtime_path_graph_v1"
