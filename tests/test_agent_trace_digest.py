from __future__ import annotations

import json
from pathlib import Path

from scripts.agent_trace_digest import build_digest, format_text


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_agent_trace_digest_extracts_gate_candidates_and_images(tmp_path: Path) -> None:
    trace_path = _write_json(
        tmp_path / "execute-mode-recognition-plan__seek.json",
        {
            "success": True,
            "message": "Recognition plan created",
            "request": {
                "goal": "open first job card",
                "app_name": "seek",
                "state_hint": "search results",
                "dry_run": True,
                "capture_live": True,
            },
            "result": {
                "contract_version": "target_location_v1",
                "image_path": "D:/agent-gui-runtime/artifacts/screenshots/seek.png",
                "screen_map": {
                    "summary": {"screen_summary": "SEEK search result page", "state_guess": "results list", "candidate_count": 2},
                    "sections": [{"section_id": "results_list", "label": "Results list", "role": "list"}],
                    "candidates": [
                        {
                            "id": "element_job_listing_1",
                            "label": "AI Engineer",
                            "role": "job_listing",
                            "risk_class": "safe_click_allowed",
                            "bbox": {"x": 20, "y": 300, "w": 410, "h": 180},
                            "click_point": {"x": 225, "y": 390},
                        }
                    ],
                },
                "candidate_result": {
                    "recommended_candidate_id": "element_job_listing_1",
                    "margin_to_second": 0.31,
                    "candidates": [
                        {
                            "candidate_id": "element_job_listing_1",
                            "label": "AI Engineer",
                            "role": "job_listing",
                            "score": 0.91,
                            "risk_class": "safe_click_allowed",
                            "click_point": {"x": 225, "y": 390},
                        }
                    ],
                },
                "pre_click_decision": {
                    "allowed": True,
                    "selected_candidate_id": "element_job_listing_1",
                    "selected_click_point": {"x": 225, "y": 390},
                    "reasons": ["safe_or_reviewable_path_graph_action"],
                    "candidate_decisions": [
                        {
                            "candidate_id": "element_job_listing_1",
                            "allowed": True,
                            "risk_class": "safe_click_allowed",
                            "reason": "low risk navigation",
                        }
                    ],
                },
                "parse_result": {
                    "vista_point_grounding": {
                        "status": "ready",
                        "vista_stage": "pathgraph_candidate_roi_refine",
                        "raw_text": "[500, 500]",
                        "point": {"x": 225, "y": 390},
                        "processed_point": {"x": 128, "y": 128},
                        "image_preprocess": {
                            "roi_policy": "compact_seed_candidate_roi_primary",
                            "roi_source": "seeded_candidate_v1",
                            "fallback_tier": "primary",
                            "processed_size": {"width": 320, "height": 220},
                            "crop_bounds_original": {"x": 20, "y": 300, "w": 410, "h": 180},
                            "processed_image_path": "D:/agent-gui-runtime/artifacts/vista-direct/roi.png",
                        },
                    }
                },
                "model_io": {
                    "status": "ok",
                    "provider": "local_understanding",
                    "model_name": "Qwen3-VL 4B",
                    "raw_text": '{"screen_summary":"SEEK search result page"}',
                },
                "coordinate_overlay_path": "D:/agent-gui-runtime/artifacts/review-overlays/overlay.png",
            },
        },
    )

    digest = build_digest(trace_path)

    assert digest["contract_version"] == "agent_trace_digest_v1"
    assert digest["status"] == "ok"
    assert digest["request"]["goal"] == "open first job card"
    assert digest["screen"]["summary"] == "SEEK search result page"
    assert digest["candidates"]["recommended_candidate_id"] == "element_job_listing_1"
    assert digest["vista_grounding"]["roi_policy"] == "compact_seed_candidate_roi_primary"
    assert digest["vista_grounding"]["fallback_tier"] == "primary"
    assert digest["gate"]["allowed"] is True
    assert digest["summary"]["gate_allowed"] is True
    assert any(image["path"].endswith("overlay.png") for image in digest["images"])
    text = format_text(digest)
    assert "element_job_listing_1" in text
    assert "compact_seed_candidate_roi_primary" in text
    assert "gate: allowed=True" in text


def test_agent_trace_digest_skips_large_trace_without_allow_large(tmp_path: Path) -> None:
    trace_path = tmp_path / "large-trace.json"
    trace_path.write_text('{"success":true,"result":{"contract_version":"x"}}', encoding="utf-8")

    digest = build_digest(trace_path, max_file_mb=0.000001)

    assert digest["status"] == "skipped_large_trace"
    assert "advice" in digest
