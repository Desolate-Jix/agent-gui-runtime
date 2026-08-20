from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.agent.navigation_reading_replay import run_navigation_reading_replay
from app.learn.interface_assets import build_single_interface_asset
from scripts.run_navigation_reading_replay import main


APPLICATION = {
    "kind": "web",
    "name": "Example News",
    "url": "https://news.example.test/",
    "process": "msedge.exe",
}


def _write_json(path: Path, payload: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode("utf-8")
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def _canonical_sha256(value: dict) -> str:
    content = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _approve_asset(asset: dict) -> dict:
    revision = {
        "interface_id": asset["interface_id"],
        "audit_evidence_sha256": _canonical_sha256(asset["evidence"]),
    }
    revision_hash = _canonical_sha256(revision)
    asset["review"].update(
        {
            "reviewed_by_human": True,
            "reviewed_revision_hash": revision_hash,
            "current_revision_hash": revision_hash,
        }
    )
    return {"revision": revision, "revision_hash": revision_hash}


def _asset(
    *,
    interface_id: str,
    surface_type: str,
    content_behavior: str,
    read_strategy: str,
    action: dict | None = None,
) -> dict:
    controls = []
    action_candidates = []
    if action:
        controls.append(
            {
                "control_id": action["source_control_id"],
                "label": action["display_name"],
                "role": "button",
                "agent_description": action["agent_description"],
                "review_status": "human_approved",
            }
        )
        action_candidates.append(
            {
                "action_template_id": action["action_id"],
                "semantic_action": action["action_type"],
                "target_control_id": action["source_control_id"],
                "display_name": action["display_name"],
                "agent_description": action["agent_description"],
                "risk_level": "low",
                "review_status": "human_approved",
                "verification_rule_ids": ["destination_visible"],
            }
        )
    return build_single_interface_asset(
        {
            "node_id": interface_id,
            "display_name": interface_id.replace(":", " ").title(),
            "surface_type": surface_type,
            "state_signature": f"{interface_id}:reviewed",
            "evidence": {
                "source_screenshot_path": f"artifacts/screenshots/{interface_id}.png",
                "fused_overlay_path": f"artifacts/review-overlays/{interface_id}.png",
            },
            "states": [{"state_id": interface_id, "label": "Reviewed state"}],
            "regions": [],
            "controls": controls,
            "content_descriptors": [
                {
                    "content_id": f"{interface_id}:identity",
                    "label": "Reviewed interface identity",
                    "source_kind": "state",
                    "source_id": interface_id,
                    "content_behavior": "fixed_label",
                    "agent_usage": "identity_anchor",
                    "read_policy": "on_interface_match",
                    "agent_description": "确认当前审核界面身份。",
                },
                {
                    "content_id": f"{interface_id}:content",
                    "label": "Current readable content",
                    "source_kind": "region",
                    "source_id": f"{interface_id}:content",
                    "content_behavior": content_behavior,
                    "agent_usage": "decision_signal",
                    "read_policy": "on_demand",
                    "read_strategy": read_strategy,
                    "completion_policy": (
                        "budget_or_no_new_content"
                        if read_strategy == "infinite_collection"
                        else "reached_bottom_required"
                    ),
                    "agent_description": "按需读取当前内容，不复用历史文本。",
                },
            ],
            "action_candidates": action_candidates,
            "verification_rules": [
                {
                    "rule_id": "destination_visible",
                    "description": "目标审核界面的身份锚点可见。",
                }
            ],
            "review_status": "human_approved",
            "manual_revision": {
                "semantic_description": f"读取并操作 {interface_id} 审核界面。"
            },
        },
        application_identity=APPLICATION,
    )


def _observation(interface_id: str, capture_id: str) -> dict:
    return {
        "contract_version": "current_interface_observation_v1",
        "interface_id": interface_id,
        "capture_id": capture_id,
        "screenshot_sha256": hashlib.sha256(capture_id.encode("utf-8")).hexdigest(),
        "trace_path": f"logs/traces/{capture_id}.json",
    }


def _metric(passed: int, attempted: int) -> dict:
    return {
        "passed": passed,
        "attempted": attempted,
        "rate": round(passed / attempted, 4) if attempted else "not_covered",
    }


def _build_manifest(tmp_path: Path) -> Path:
    list_action = {
        "action_id": "open_selected_article",
        "action_type": "open_detail",
        "source_control_id": "article_card",
        "display_name": "Open selected article",
        "agent_description": "打开 Agent 选择的新闻卡片。",
    }
    list_asset = _asset(
        interface_id="news_list",
        surface_type="content_collection",
        content_behavior="dynamic_collection",
        read_strategy="infinite_collection",
        action=list_action,
    )
    detail_asset = _asset(
        interface_id="news_detail",
        surface_type="finite_detail",
        content_behavior="dynamic_value",
        read_strategy="finite_detail",
    )
    list_revision = _approve_asset(list_asset)
    detail_revision = _approve_asset(detail_asset)
    list_path = tmp_path / "assets" / "news-list.json"
    detail_path = tmp_path / "assets" / "news-detail.json"
    list_sha = _write_json(list_path, list_asset)
    detail_sha = _write_json(detail_path, detail_asset)
    list_revision["source_asset_sha256"] = list_sha
    detail_revision["source_asset_sha256"] = detail_sha

    manifest = {
        "contract_version": "navigation_reading_replay_manifest_v1",
        "suite_id": "reviewed-news-navigation",
        "decision_source": "recorded_agent_output",
        "interface_assets": [
            {
                "interface_id": "news_list",
                "path": str(list_path),
                "sha256": list_sha,
                "persisted_review_revision": list_revision,
            },
            {
                "interface_id": "news_detail",
                "path": str(detail_path),
                "sha256": detail_sha,
                "persisted_review_revision": detail_revision,
            },
        ],
        "transitions": [
            {
                "transition_id": "news-list-to-detail",
                "source_interface_id": "news_list",
                "target_interface_id": "news_detail",
                "source_control_id": "article_card",
                "action_type": "open_detail",
                "display_name": "Open selected article",
                "agent_description": "打开选中的新闻并验证详情界面。",
                "risk_level": "low",
                "review_status": "human_confirmed",
                "success_conditions": ["news_detail identity anchor visible"],
            }
        ],
        "cases": [
            {
                "case_id": "list_scroll_detail_read",
                "goal": "浏览新闻列表，选择一篇新闻并完整读取详情。",
                "workflow_id": "news-reading",
                "initial_observation": _observation("news_list", "capture-list-1"),
                "steps": [
                    {
                        "step_id": "read-list",
                        "decision": {
                            "choice_id": "read:news_list_content",
                            "reason": "先读取当前新闻卡片。",
                        },
                        "read_result": {
                            "action_type": "read",
                            "gate_result": {"allowed": True, "reason": "read_only"},
                            "action_dispatched": True,
                            "effect_verified": True,
                            "report": {
                                "contract_version": "read_region_batch_v1",
                                "stop_reason": "captures_exhausted",
                                "completion_status": "incomplete",
                                "reached_bottom": False,
                                "unique_line_count": 8,
                            },
                            "evidence": _observation("news_list", "capture-list-1"),
                        },
                    },
                    {
                        "step_id": "scroll-list",
                        "read_progress": {
                            "strategy": "infinite_collection",
                            "status": "reading",
                            "scrolls_used": 0,
                            "max_scrolls": 2,
                            "items_read": 8,
                            "max_items": 20,
                        },
                        "decision": {
                            "choice_id": "scroll:current_read_region",
                            "reason": "当前条目不足，继续滚动一次。",
                        },
                        "read_result": {
                            "action_type": "scroll",
                            "gate_result": {"allowed": True, "reason": "correct_scope"},
                            "action_dispatched": True,
                            "effect_verified": True,
                            "report": {
                                "contract_version": "read_region_batch_v1",
                                "stop_reason": "captures_exhausted",
                                "completion_status": "incomplete",
                                "reached_bottom": False,
                                "unique_line_count": 15,
                            },
                            "evidence": _observation("news_list", "capture-list-2"),
                        },
                        "post_observation": _observation("news_list", "capture-list-2"),
                    },
                    {
                        "step_id": "open-detail",
                        "decision": {
                            "choice_id": "transition:open_selected_article",
                            "reason": "选择的新闻符合目标。",
                        },
                        "operation_result": {
                            "action_type": "open_detail",
                            "gate_result": {"allowed": True, "reason": "low_risk"},
                            "action_executed": True,
                            "post_action_verified": True,
                            "evidence": _observation(
                                "news_detail",
                                "capture-detail-transition",
                            ),
                        },
                        "post_observation": _observation(
                            "news_detail",
                            "capture-detail-1",
                        ),
                    },
                    {
                        "step_id": "read-detail",
                        "decision": {
                            "choice_id": "read:news_detail_content",
                            "reason": "读取完整新闻详情。",
                        },
                        "read_result": {
                            "action_type": "read",
                            "gate_result": {"allowed": True, "reason": "read_only"},
                            "action_dispatched": True,
                            "effect_verified": True,
                            "report": {
                                "contract_version": "read_region_batch_v1",
                                "stop_reason": "reached_bottom",
                                "completion_status": "complete",
                                "reached_bottom": True,
                                "unique_line_count": 32,
                            },
                            "evidence": _observation(
                                "news_detail",
                                "capture-detail-bottom",
                            ),
                        },
                    },
                ],
                "expected_outcome": "goal_satisfied",
            },
            {
                "case_id": "wrong_scope_safe_stop",
                "goal": "滚动新闻列表并读取更多条目。",
                "workflow_id": "news-reading",
                "initial_observation": _observation("news_list", "capture-wrong-1"),
                "steps": [
                    {
                        "step_id": "wrong-scroll",
                        "read_progress": {
                            "strategy": "infinite_collection",
                            "status": "reading",
                            "scrolls_used": 0,
                            "max_scrolls": 2,
                        },
                        "decision": {
                            "choice_id": "scroll:current_read_region",
                            "reason": "需要读取更多条目。",
                        },
                        "read_result": {
                            "action_type": "scroll",
                            "gate_result": {"allowed": True, "reason": "scope_expected"},
                            "action_dispatched": True,
                            "effect_verified": False,
                            "report": {
                                "contract_version": "read_region_batch_v1",
                                "stop_reason": "wrong_scope_detected",
                                "completion_status": "blocked",
                                "wrong_scope_detected": True,
                            },
                            "evidence": _observation(
                                "news_list",
                                "capture-wrong-2",
                            ),
                        },
                    }
                ],
                "expected_outcome": "safe_stop",
                "expected_stop_reason": "wrong_scope_detected",
            },
        ],
    }
    path = tmp_path / "manifest.json"
    _write_json(path, manifest)
    return path


def test_replay_runs_reviewed_multi_interface_navigation_read_and_scroll(
    tmp_path: Path,
) -> None:
    manifest_path = _build_manifest(tmp_path)

    report = run_navigation_reading_replay(
        manifest_path=manifest_path,
        out_dir=tmp_path / "report",
    )

    assert report["contract_version"] == "navigation_reading_replay_report_v1"
    assert report["decision_source"] == "recorded_agent_output"
    assert report["model_decision_quality"] == "not_evaluated"
    assert report["summary"] == {
        "attempted": 2,
        "passed": 2,
        "failed": 0,
        "invalid": 0,
        "safe_stop": 1,
    }
    assert report["metrics"]["reviewed_asset_validity"] == _metric(2, 2)
    assert report["metrics"]["agent_context_build"] == _metric(5, 5)
    assert report["metrics"]["agent_decision_validation"] == _metric(5, 5)
    assert report["metrics"]["gate_safety"] == _metric(5, 5)
    assert report["metrics"]["operation_dispatch"] == _metric(5, 5)
    assert report["metrics"]["effect_verification"] == _metric(4, 5)
    assert report["metrics"]["destination_observation"] == _metric(2, 2)
    assert report["metrics"]["finite_read_completion"] == _metric(1, 1)
    assert report["metrics"]["wrong_scope_safe_stop"] == _metric(1, 1)
    first = report["cases"][0]
    assert first["case_outcome"] == "passed"
    assert first["visited_interfaces"] == ["news_list", "news_detail"]
    assert first["final_read_state"]["reached_bottom"] is True
    assert [step["decision_type"] for step in first["steps"]] == [
        "read_region",
        "scroll_for_more",
        "follow_transition",
        "read_region",
    ]
    assert report["cases"][1]["case_outcome"] == "safe_stop"
    assert report["cases"][1]["stop_reason"] == "wrong_scope_detected"
    assert Path(report["report_path"]).is_file()


def test_stale_reviewed_asset_is_invalid_and_excluded_from_attempted(
    tmp_path: Path,
) -> None:
    manifest_path = _build_manifest(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["interface_assets"][0]["sha256"] = "0" * 64
    _write_json(manifest_path, manifest)

    report = run_navigation_reading_replay(
        manifest_path=manifest_path,
        out_dir=tmp_path / "report",
    )

    assert report["summary"] == {
        "attempted": 0,
        "passed": 0,
        "failed": 0,
        "invalid": 2,
        "safe_stop": 0,
    }
    assert report["metrics"]["reviewed_asset_validity"] == _metric(0, 0)
    assert {item["failure_category"] for item in report["invalid_cases"]} == {
        "stale_reviewed_asset"
    }
    assert all(
        item["asset_path"].endswith("news-list.json")
        for item in report["invalid_cases"]
    )


def test_missing_persisted_review_revision_invalidates_replay_cases(
    tmp_path: Path,
) -> None:
    manifest_path = _build_manifest(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["interface_assets"][0].pop("persisted_review_revision")
    _write_json(manifest_path, manifest)

    report = run_navigation_reading_replay(
        manifest_path=manifest_path,
        out_dir=tmp_path / "report",
    )

    assert report["summary"] == {
        "attempted": 0,
        "passed": 0,
        "failed": 0,
        "invalid": 2,
        "safe_stop": 0,
    }
    assert {item["failure_category"] for item in report["invalid_cases"]} == {
        "missing_persisted_review_revision"
    }


def test_stale_persisted_review_revision_invalidates_replay_cases(
    tmp_path: Path,
) -> None:
    manifest_path = _build_manifest(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["interface_assets"][0]["persisted_review_revision"][
        "source_asset_sha256"
    ] = "0" * 64
    _write_json(manifest_path, manifest)

    report = run_navigation_reading_replay(
        manifest_path=manifest_path,
        out_dir=tmp_path / "report",
    )

    assert report["summary"] == {
        "attempted": 0,
        "passed": 0,
        "failed": 0,
        "invalid": 2,
        "safe_stop": 0,
    }
    assert {item["failure_category"] for item in report["invalid_cases"]} == {
        "stale_persisted_review_revision"
    }


def test_stale_revision_audit_evidence_invalidates_replay_cases(
    tmp_path: Path,
) -> None:
    manifest_path = _build_manifest(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    revision = manifest["interface_assets"][0]["persisted_review_revision"]["revision"]
    revision["audit_evidence_sha256"] = "0" * 64
    manifest["interface_assets"][0]["persisted_review_revision"][
        "revision_hash"
    ] = _canonical_sha256(revision)
    _write_json(manifest_path, manifest)

    report = run_navigation_reading_replay(
        manifest_path=manifest_path,
        out_dir=tmp_path / "report",
    )

    assert report["summary"] == {
        "attempted": 0,
        "passed": 0,
        "failed": 0,
        "invalid": 2,
        "safe_stop": 0,
    }
    assert {item["failure_category"] for item in report["invalid_cases"]} == {
        "stale_persisted_review_revision"
    }


def test_gate_rejection_prevents_operation_and_is_a_safe_intercept(
    tmp_path: Path,
) -> None:
    manifest_path = _build_manifest(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    case = manifest["cases"][0]
    case["steps"] = [case["steps"][2]]
    case["steps"][0]["operation_result"]["gate_result"] = {
        "allowed": False,
        "reason": "target_ambiguous",
    }
    case["steps"][0]["operation_result"]["action_executed"] = False
    case["steps"][0]["operation_result"]["post_action_verified"] = False
    case["steps"][0].pop("post_observation")
    case["expected_outcome"] = "safe_stop"
    case["expected_stop_reason"] = "gate_rejected"
    manifest["cases"] = [case]
    _write_json(manifest_path, manifest)

    report = run_navigation_reading_replay(
        manifest_path=manifest_path,
        out_dir=tmp_path / "report",
    )

    assert report["summary"] == {
        "attempted": 1,
        "passed": 1,
        "failed": 0,
        "invalid": 0,
        "safe_stop": 1,
    }
    assert report["metrics"]["gate_safety"] == _metric(1, 1)
    assert report["metrics"]["operation_dispatch"] == _metric(0, 0)
    step = report["cases"][0]["steps"][0]
    assert step["case_outcome"] == "safe_intercept"
    assert step["gate_safety"] == "passed_rejected"
    assert step["action_executed"] is False


def test_dispatched_action_without_verified_effect_fails_the_case(
    tmp_path: Path,
) -> None:
    manifest_path = _build_manifest(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    case = manifest["cases"][0]
    case["steps"] = [case["steps"][1]]
    case["steps"][0]["read_result"]["effect_verified"] = False
    case["steps"][0]["read_result"]["report"] = {
        "contract_version": "read_region_batch_v1",
        "stop_reason": "no_new_content",
        "completion_status": "incomplete",
        "reached_bottom": False,
        "unique_line_count": 8,
    }
    case["steps"][0].pop("post_observation")
    manifest["cases"] = [case]
    _write_json(manifest_path, manifest)

    report = run_navigation_reading_replay(
        manifest_path=manifest_path,
        out_dir=tmp_path / "report",
    )

    assert report["summary"] == {
        "attempted": 1,
        "passed": 0,
        "failed": 1,
        "invalid": 0,
        "safe_stop": 0,
    }
    assert report["metrics"]["operation_dispatch"] == _metric(1, 1)
    assert report["metrics"]["effect_verification"] == _metric(0, 1)
    assert report["cases"][0]["case_outcome"] == "failed"
    assert report["cases"][0]["steps"][0]["case_outcome"] == "failed"


def test_cli_writes_replay_report(tmp_path: Path, capsys) -> None:
    manifest_path = _build_manifest(tmp_path)
    out_dir = tmp_path / "cli-report"

    exit_code = main(
        [
            "--manifest",
            str(manifest_path),
            "--out",
            str(out_dir),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["summary"]["failed"] == 0
    assert (out_dir / "navigation_reading_replay_report.json").is_file()
