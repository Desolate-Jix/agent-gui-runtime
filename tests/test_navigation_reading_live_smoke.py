from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.agent.navigation_reading_live_smoke import (
    capture_navigation_runtime_record,
    load_reviewed_navigation_suite,
    run_navigation_reading_live_smoke,
)
import app.agent.navigation_reading_live_smoke as live_smoke_module


def _write_json(path: Path, value: dict) -> str:
    content = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def _asset() -> dict:
    return {
        "contract_version": "single_interface_asset_v1",
        "interface_id": "lab_detail",
        "application_identity_key": "web:navigation-reading.test",
        "display_name": "Lab detail",
        "surface_type": "finite_detail",
        "state_signature": "lab_detail:reviewed",
        "artifact_is_authorization": False,
        "fixed_anchors": [
            {
                "content_id": "detail_identity",
                "label": "Lab Detail Interface",
                "source_kind": "state",
                "source_id": "lab_detail",
                "content_behavior": "fixed_label",
                "agent_usage": "identity_anchor",
                "read_policy": "on_interface_match",
                "agent_description": "Confirm the reviewed detail interface.",
            }
        ],
        "dynamic_slots": [
            {
                "content_id": "detail_body",
                "label": "Current detail body",
                "source_kind": "region",
                "source_id": "detail_body",
                "content_behavior": "dynamic_value",
                "agent_usage": "decision_signal",
                "read_policy": "on_demand",
                "read_strategy": "finite_detail",
                "completion_policy": "reached_bottom_required",
                "agent_description": "Read the current detail to its explicit end marker.",
            }
        ],
        "controls": [
            {
                "control_id": "open_next",
                "label": "Open next interface",
                "role": "button",
                "agent_description": "Open the next reviewed interface.",
                "review_status": "human_reviewed",
            }
        ],
        "action_candidates": [],
        "verification_rules": [
            {
                "rule_id": "next_visible",
                "description": "The next interface identity marker is visible.",
            }
        ],
        "blockers": [],
        "review": {
            "status": "human_reviewed",
            "manual_revision": {
                "semantic_description": "Read the finite detail, then continue."
            },
        },
        "evidence": {},
        "execute_binding_enabled": False,
    }


def test_reviewed_suite_compiles_agent_evidence_with_hash_and_read_prerequisite(
    tmp_path: Path,
) -> None:
    asset_path = tmp_path / "assets" / "detail.json"
    asset_sha = _write_json(asset_path, _asset())
    manifest_path = tmp_path / "suite.json"
    _write_json(
        manifest_path,
        {
            "contract_version": "navigation_reading_live_suite_v1",
            "suite_id": "lab",
            "goal": "Read the detail and continue.",
            "app_name": "Navigation Reading Lab",
            "initial_interface_id": "lab_detail",
            "interface_specs": [
                {
                    "interface_id": "lab_detail",
                    "surface_type": "finite_detail",
                    "identity_markers": ["Lab Detail Interface"],
                    "read_target": {
                        "content_id": "detail_body",
                        "bottom_markers": ["DETAIL END"],
                    },
                }
            ],
            "interface_assets": [
                {
                    "interface_id": "lab_detail",
                    "path": "assets/detail.json",
                    "sha256": asset_sha,
                }
            ],
            "transitions": [
                {
                    "transition_id": "detail_to_next",
                    "source_interface_id": "lab_detail",
                    "target_interface_id": "lab_next",
                    "source_control_id": "open_next",
                    "action_type": "continue_next_step",
                    "display_name": "Open next interface",
                    "agent_description": "Open the next reviewed interface.",
                    "operation_goal": "Click the button labeled Open next interface",
                    "requires_completed_read": "detail_body",
                    "risk_level": "low",
                    "review_status": "human_reviewed",
                    "success_conditions": ["Lab Next Interface is visible"],
                }
            ],
        },
    )

    suite = load_reviewed_navigation_suite(manifest_path)

    assert suite["initial_interface_id"] == "lab_detail"
    evidence = suite["evidence_by_interface"]["lab_detail"]
    assert evidence["source_asset_sha256"] == asset_sha
    assert evidence["readiness"]["status"] == "agent_usable"
    assert evidence["available_actions"][0]["operation_goal"] == (
        "Click the button labeled Open next interface"
    )
    assert evidence["available_actions"][0]["requires_completed_read"] == "detail_body"


def test_capture_runtime_record_uses_current_capture_and_screen_reading(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "current.png"
    image_path.write_bytes(b"current-screen")
    calls: list[tuple[str, dict]] = []

    def post_json(path: str, body: dict) -> dict:
        calls.append((path, body))
        if path == "/state/capture_window":
            return {
                "success": True,
                "data": {
                    "image_path": str(image_path),
                    "image_width": 900,
                    "image_height": 700,
                },
            }
        if path == "/vision/screen_reading":
            return {
                "success": True,
                "data": {
                    "result": {
                        "contract_version": "screen_reading_v1",
                        "trace_path": "logs/traces/current-screen.json",
                        "texts": [
                            {
                                "text": "Lab Detail Interface",
                                "bbox": {"x": 30, "y": 50, "w": 220, "h": 30},
                                "confidence": 0.99,
                            }
                        ],
                        "screen_inventory": {
                            "cards": [
                                {
                                    "role": "document",
                                    "bbox": {"x": 0, "y": 0, "w": 900, "h": 700},
                                }
                            ]
                        },
                    }
                },
            }
        raise AssertionError(path)

    record = capture_navigation_runtime_record(
        post_json=post_json,
        app_name="Navigation Reading Lab",
        interface_specs=[
            {
                "interface_id": "lab_detail",
                "surface_type": "finite_detail",
                "identity_markers": ["Lab Detail Interface"],
                "read_target": {
                    "content_id": "detail_body",
                    "bottom_markers": ["DETAIL END"],
                },
            }
        ],
    )

    assert record["observation"]["interface_id"] == "lab_detail"
    assert record["image_path"] == str(image_path.resolve())
    assert record["resolved_read_targets"]["detail_body"]["bbox"] == {
        "x": 0,
        "y": 0,
        "w": 900,
        "h": 700,
    }
    assert calls == [
        ("/state/capture_window", {"save_image": True}),
        (
            "/vision/screen_reading",
            {
                "image_path": str(image_path),
                "task": "screen_reading",
                "app_name": "Navigation Reading Lab",
                "goal": (
                    "Identify the current reviewed interface and read the visible "
                    "content using only the current screenshot."
                ),
                "provider_mode": "local_understanding",
                "metadata": {
                    "source": "navigation_reading_live_smoke",
                    "trace": True,
                },
            },
        ),
    ]


def test_branching_live_suite_covers_back_modal_and_bounded_collection() -> None:
    suite = load_reviewed_navigation_suite(
        Path("configs/demos/navigation_reading_live_v2/suite.json")
    )

    assert set(suite["evidence_by_interface"]) == {
        "branch_hub",
        "branch_incident",
        "branch_policy_modal",
        "branch_updates",
        "branch_summary",
    }
    transition_types = {
        item["action_type"]
        for item in suite["transitions"]
    }
    assert {"open_detail", "back", "open_modal", "close_modal"} <= (
        transition_types
    )
    updates = suite["evidence_by_interface"]["branch_updates"]
    assert updates["deferred_reads"][0]["read_strategy"] == "infinite_collection"
    assert updates["deferred_reads"][0]["max_scrolls"] == 2
    summary = suite["evidence_by_interface"]["branch_summary"]
    assert summary["deferred_reads"][0]["content_id"] == "summary_body"


def test_live_smoke_rejects_stale_initial_interface_before_agent_or_operation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    asset_path = tmp_path / "assets" / "detail.json"
    asset_sha = _write_json(asset_path, _asset())
    manifest_path = tmp_path / "suite.json"
    _write_json(
        manifest_path,
        {
            "contract_version": "navigation_reading_live_suite_v1",
            "suite_id": "initial-state-check",
            "goal": "Read the reviewed detail.",
            "app_name": "Navigation Reading Lab",
            "initial_interface_id": "lab_detail",
            "interface_specs": [
                {
                    "interface_id": "lab_detail",
                    "surface_type": "finite_detail",
                    "identity_markers": ["Lab Detail Interface"],
                }
            ],
            "interface_assets": [
                {
                    "interface_id": "lab_detail",
                    "path": "assets/detail.json",
                    "sha256": asset_sha,
                }
            ],
            "transitions": [],
        },
    )
    capture_calls = 0

    def capture_record(**_kwargs) -> dict:
        nonlocal capture_calls
        capture_calls += 1
        return {
            "contract_version": "navigation_runtime_observation_record_v1",
            "observation": {
                "contract_version": "current_interface_observation_v1",
                "interface_id": "stale_summary",
                "surface_type": "read_only_summary",
                "capture_id": "capture-stale",
                "screenshot_sha256": "a" * 64,
                "trace_path": "logs/traces/stale-summary.json",
            },
            "image_path": str(tmp_path / "stale-summary.png"),
            "window_size": {"width": 900, "height": 700},
            "resolved_read_targets": {},
        }

    def fail_if_model_is_created(*_args, **_kwargs):
        raise AssertionError("Agent model must not run for a stale initial interface")

    monkeypatch.setattr(
        live_smoke_module,
        "capture_navigation_runtime_record",
        capture_record,
    )
    monkeypatch.setattr(
        live_smoke_module,
        "_http_post_json",
        lambda *_args, **_kwargs: lambda _path, _body: {},
    )
    monkeypatch.setattr(
        live_smoke_module,
        "OpenAICompatibleNavigationDecisionProvider",
        fail_if_model_is_created,
    )

    report = run_navigation_reading_live_smoke(
        suite_path=manifest_path,
        out_dir=tmp_path / "report",
        runtime_endpoint="http://runtime.invalid",
        decision_endpoint="http://model.invalid",
        decision_model="unused",
    )

    assert capture_calls == 1
    assert report["initial_state_check"] == {
        "status": "mismatch",
        "expected_interface_id": "lab_detail",
        "actual_interface_id": "stale_summary",
        "capture_id": "capture-stale",
        "screenshot_sha256": "a" * 64,
        "trace_path": "logs/traces/stale-summary.json",
    }
    assert report["controller"]["final_status"] == "needs_human_review"
    assert report["controller"]["stop_reason"] == "initial_interface_mismatch"
    assert report["controller"]["actual_model_call_count"] == 0
    assert report["controller"]["steps"] == []


def test_live_smoke_reuses_matching_initial_capture_for_first_agent_decision(
    tmp_path: Path,
    monkeypatch,
) -> None:
    asset_path = tmp_path / "assets" / "detail.json"
    asset_sha = _write_json(asset_path, _asset())
    manifest_path = tmp_path / "suite.json"
    _write_json(
        manifest_path,
        {
            "contract_version": "navigation_reading_live_suite_v1",
            "suite_id": "matching-initial-state",
            "goal": "Stop safely after recognizing the reviewed detail.",
            "app_name": "Navigation Reading Lab",
            "initial_interface_id": "lab_detail",
            "interface_specs": [
                {
                    "interface_id": "lab_detail",
                    "surface_type": "finite_detail",
                    "identity_markers": ["Lab Detail Interface"],
                }
            ],
            "interface_assets": [
                {
                    "interface_id": "lab_detail",
                    "path": "assets/detail.json",
                    "sha256": asset_sha,
                }
            ],
            "transitions": [],
        },
    )
    capture_calls = 0

    def capture_record(**_kwargs) -> dict:
        nonlocal capture_calls
        capture_calls += 1
        return {
            "contract_version": "navigation_runtime_observation_record_v1",
            "observation": {
                "contract_version": "current_interface_observation_v1",
                "interface_id": "lab_detail",
                "surface_type": "finite_detail",
                "capture_id": "capture-current",
                "screenshot_sha256": "b" * 64,
                "trace_path": "logs/traces/current-detail.json",
            },
            "image_path": str(tmp_path / "current-detail.png"),
            "window_size": {"width": 900, "height": 700},
            "resolved_read_targets": {},
        }

    class SafeStopProvider:
        def __init__(self, **_kwargs) -> None:
            self.calls = 0

        def decide(self, context: dict) -> dict:
            self.calls += 1
            choice = next(
                item
                for item in context["choices"]
                if item["semantic_action"] == "safe_stop"
            )
            return {
                "choice_id": choice["choice_id"],
                "reason": "The controlled test requests a safe stop.",
                "decision_source": "actual_model_call",
            }

    monkeypatch.setattr(
        live_smoke_module,
        "capture_navigation_runtime_record",
        capture_record,
    )
    monkeypatch.setattr(
        live_smoke_module,
        "_http_post_json",
        lambda *_args, **_kwargs: lambda _path, _body: {},
    )
    monkeypatch.setattr(
        live_smoke_module,
        "OpenAICompatibleNavigationDecisionProvider",
        SafeStopProvider,
    )

    report = run_navigation_reading_live_smoke(
        suite_path=manifest_path,
        out_dir=tmp_path / "report",
        runtime_endpoint="http://runtime.invalid",
        decision_endpoint="http://model.invalid",
        decision_model="controlled",
    )

    assert capture_calls == 1
    assert report["initial_state_check"]["status"] == "matched"
    assert report["controller"]["visited_interfaces"] == ["lab_detail"]
    assert report["controller"]["actual_model_call_count"] == 1
    assert report["controller"]["steps"][0]["capture_id"] == "capture-current"
    assert report["controller"]["final_status"] == "safe_stop"
    assert report["controller"]["steps"][0]["case_outcome"] == "safe_stop"
