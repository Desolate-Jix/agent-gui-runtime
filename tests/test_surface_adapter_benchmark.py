from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

from app.learn.recognition.trace_input import (
    observe_bundle_from_trace_result,
    stage1_inventory_from_trace_result,
)
from scripts.run_surface_adapter_benchmark import run_surface_adapter_benchmark


ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_surface_adapter_benchmark_separates_valid_and_stale_fixtures(tmp_path: Path) -> None:
    image_path = tmp_path / "screen.png"
    Image.new("RGB", (640, 480), "white").save(image_path)
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(
        json.dumps(
            {
                "result": {
                    "app_name": "chat-demo",
                    "image_path": str(image_path),
                    "image_size": {"width": 640, "height": 480},
                        "interface_classification": {
                            "category": "conversation_workspace",
                            "confidence": 0.91,
                            "structure_signals": {
                                "people_or_conversation_rows": True,
                                "message_thread": True,
                                "message_composer": True,
                            },
                        },
                        "screen_inventory": [
                        {
                            "item_id": "conversation_row_1",
                            "label": "Conversation",
                            "role": "conversation_row",
                                "bbox": {"x": 0, "y": 80, "w": 180, "h": 48},
                            },
                            {
                                "item_id": "thread",
                                "role": "message_thread",
                                "bbox": {"x": 180, "y": 80, "w": 460, "h": 320},
                            },
                            {
                                "item_id": "composer",
                                "role": "composer",
                                "bbox": {"x": 180, "y": 400, "w": 460, "h": 80},
                            },
                        ],
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "contract_version": "learning_surface_adapter_holdout_manifest_v1",
                "used_for_rule_tuning": False,
                "cases": [
                    {
                        "case_id": "valid_chat",
                        "trace_path": str(trace_path),
                        "trace_sha256": _sha256(trace_path),
                        "screenshot_path": str(image_path),
                        "screenshot_sha256": _sha256(image_path),
                        "expected_adapter_id": "chat",
                        "expected_host_adapter_id": "generic",
                        "expected_content_adapter_id": "chat",
                        "expected_content_adapter_status": "selected_from_correlated_model_and_inventory",
                    },
                    {
                        "case_id": "stale_chat",
                        "trace_path": str(trace_path),
                        "trace_sha256": "0" * 64,
                        "screenshot_path": str(image_path),
                        "screenshot_sha256": _sha256(image_path),
                        "expected_adapter_id": "chat",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = run_surface_adapter_benchmark(manifest_path=manifest_path, out_dir=tmp_path / "out")

    assert report["adapter_selection"] == {
        "passed": 1,
        "attempted": 1,
        "rate": 1.0,
        "denominator": "checksum-valid fixed holdout adapter decisions",
        "interpretation": "fixed holdout decision checks only; not recognition accuracy or general GUI reliability",
    }
    assert report["holdout_used_for_rule_tuning"] is False
    assert report["host_adapter_selection"]["passed"] == 1
    assert report["host_adapter_selection"]["attempted"] == 1
    assert report["content_adapter_selection"]["passed"] == 1
    assert report["content_adapter_selection"]["attempted"] == 1
    assert report["content_adapter_status"]["passed"] == 1
    assert report["content_adapter_status"]["attempted"] == 1
    assert report["source_breakdown"] == {"fixed_recorded_trace": 1}
    assert report["invalid_cases"][0]["failure_category"] == "stale_trace_fixture"
    assert report["safety"]["model_calls"] == 0
    assert report["safety"]["live_clicks"] == 0


def test_trace_input_reads_completed_learning_trial_artifacts(tmp_path: Path) -> None:
    trace_path = tmp_path / "trial_result.json"
    result = {
        "two_stage_understanding": {
            "observe_bundle": {
                "app_name": "Desktop chat",
                "image_path": "screen.png",
                "image_size": {"width": 800, "height": 600},
                "screen_reading": {
                    "interface_classification": {
                        "category": "conversation_workspace",
                        "confidence": 0.95,
                        "structure_signals": {
                            "people_or_conversation_rows": True,
                            "message_thread": True,
                            "message_composer": True,
                        },
                    }
                },
            }
        },
        "learning_draft": {
            "regions": [
                {
                    "region_id": "conversation_list_row_1",
                    "label": "Conversation",
                    "role": "conversation_row",
                    "bbox": {"x": 0, "y": 80, "w": 240, "h": 48},
                },
                {
                    "region_id": "message_thread_1",
                    "label": "Thread",
                    "role": "message_thread",
                    "bbox": {"x": 240, "y": 80, "w": 560, "h": 440},
                },
                {
                    "region_id": "bottom_composer_1",
                    "label": "Composer",
                    "role": "control",
                    "bbox": {"x": 240, "y": 520, "w": 560, "h": 80},
                },
            ]
        },
    }

    bundle = observe_bundle_from_trace_result(result, trace_path=trace_path)
    inventory = stage1_inventory_from_trace_result(result)

    assert bundle["app_name"] == "Desktop chat"
    assert bundle["screen_reading"]["interface_classification"]["category"] == "conversation_workspace"
    assert [item["item_id"] for item in inventory] == [
        "conversation_list_row_1",
        "message_thread_1",
        "bottom_composer_1",
    ]


def test_surface_adapter_protocol_manifest_uses_all_explicit_layer_checks(tmp_path: Path) -> None:
    image_path = tmp_path / "screen.ppm"
    image_path.write_text("P3\n1 1\n255\n255 255 255\n", encoding="ascii")
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(
        json.dumps(
            {
                "result": {
                    "app_name": "browser-chat-fixture",
                    "image_path": str(image_path),
                    "image_size": {"width": 640, "height": 480},
                    "interface_classification": {
                        "category": "conversation_workspace",
                        "confidence": 0.95,
                        "structure_signals": {
                            "people_or_conversation_rows": True,
                            "message_thread": True,
                            "message_composer": True,
                        },
                    },
                    "screen_inventory": [
                        {
                            "item_id": "browser_address",
                            "role": "address_bar",
                            "label": "https://example.test/chat",
                            "bbox": {"x": 0, "y": 0, "w": 640, "h": 40},
                        },
                        {
                            "item_id": "conversation_row_1",
                            "role": "conversation_row",
                            "bbox": {"x": 0, "y": 40, "w": 180, "h": 48},
                        },
                        {
                            "item_id": "thread",
                            "role": "message_thread",
                            "bbox": {"x": 180, "y": 40, "w": 460, "h": 360},
                        },
                        {
                            "item_id": "composer",
                            "role": "composer",
                            "bbox": {"x": 180, "y": 400, "w": 460, "h": 80},
                        },
                    ],
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "contract_version": "learning_surface_adapter_protocol_manifest_v1",
                "split": "dev",
                "used_for_rule_tuning": True,
                "cases": [
                    {
                        "case_id": "browser_chat_wrong_content_expectation",
                        "source_type": "fixture_only",
                        "trace_path": str(trace_path),
                        "trace_sha256": _sha256(trace_path),
                        "screenshot_path": str(image_path),
                        "screenshot_sha256": _sha256(image_path),
                        "expected_adapter_id": "browser",
                        "expected_host_adapter_id": "browser",
                        "expected_host_adapter_status": "selected_from_visible_evidence",
                        "expected_content_adapter_id": "mail_workspace",
                        "expected_content_adapter_status": "selected_from_correlated_model_and_inventory",
                        "expected_decision_status": "selected_from_visible_evidence",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = run_surface_adapter_benchmark(manifest_path=manifest_path, out_dir=tmp_path / "out")

    assert report["manifest_split"] == "dev"
    assert report["used_for_rule_tuning"] is True
    assert report["cases"][0]["checks"]["adapter_selection"] is True
    assert report["cases"][0]["checks"]["host_adapter_selection"] is True
    assert report["cases"][0]["checks"]["content_adapter_selection"] is False
    assert report["cases"][0]["passed"] is False
    assert report["source_breakdown"] == {"fixture_only": 1}
    assert report["model_ability_denominator"] == {
        "attempted": 0,
        "rate": "not_covered",
        "interpretation": "surface-routing fixtures do not measure model ability",
    }


def test_surface_adapter_protocol_holdout_cannot_be_used_for_tuning(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "contract_version": "learning_surface_adapter_protocol_manifest_v1",
                "split": "holdout",
                "used_for_rule_tuning": True,
                "cases": [],
            }
        ),
        encoding="utf-8",
    )

    try:
        run_surface_adapter_benchmark(manifest_path=manifest_path, out_dir=tmp_path / "out")
    except ValueError as exc:
        assert "holdout manifest cannot be used for rule tuning" in str(exc)
    else:
        raise AssertionError("holdout manifest must reject used_for_rule_tuning=true")


def test_surface_adapter_protocol_dev_and_holdout_manifests_are_rerunnable(tmp_path: Path) -> None:
    dev = run_surface_adapter_benchmark(
        manifest_path=ROOT / "tests/fixtures/learning_surface_adapter_protocol_dev_manifest_v1.json",
        out_dir=tmp_path / "dev",
    )
    holdout = run_surface_adapter_benchmark(
        manifest_path=ROOT / "tests/fixtures/learning_surface_adapter_protocol_holdout_manifest_v1.json",
        out_dir=tmp_path / "holdout",
    )

    assert dev["adapter_selection"]["passed"] == 5
    assert dev["adapter_selection"]["attempted"] == 5
    assert dev["source_breakdown"] == {"fixture_only": 5}
    assert dev["used_for_rule_tuning"] is True
    assert holdout["adapter_selection"]["passed"] == 4
    assert holdout["adapter_selection"]["attempted"] == 4
    assert holdout["source_breakdown"] == {"fixture_only": 4}
    assert holdout["used_for_rule_tuning"] is False
    assert holdout["holdout_used_for_rule_tuning"] is False
    assert dev["model_ability_denominator"]["attempted"] == 0
    assert holdout["model_ability_denominator"]["attempted"] == 0
