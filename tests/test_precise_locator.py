from __future__ import annotations

from app.operation.recognition.precise_locator import build_precise_locator_evidence


def _request(**overrides):
    payload = {
        "capture_id": "capture-1",
        "image_size": {"width": 400, "height": 240},
        "goal": "Locate Search",
        "target": {
            "target_id": "search",
            "label": "Search",
            "role": "nav_item",
            "parent_region_id": "left_nav",
            "parent_region_bbox": {"x": 0, "y": 0, "w": 180, "h": 240},
        },
        "source_candidate": {
            "candidate_id": "source-search",
            "label": "Search",
            "role": "nav_item",
            "bbox": {"x": 8, "y": 20, "w": 64, "h": 36},
            "confidence": 0.7,
            "source": "stage2_visual",
            "freshness": "current_capture",
        },
        "evidence_candidates": [],
        "vista_point": {"x": 36, "y": 38},
        "mode": "learn",
    }
    payload.update(overrides)
    return payload


def test_precise_locator_emits_no_click_review_contract() -> None:
    result = build_precise_locator_evidence(**_request())

    assert result["contract_version"] == "precise_locator_evidence_v1"
    assert result["source_bbox_quality"]["classification"] == "candidate_bbox_ok"
    assert result["dry_run_gate"]["status"] == "locate_review_pass"
    assert result["execute_binding_enabled"] is False
    assert result["click_performed"] is False


def test_precise_locator_can_replace_a_misaligned_source_with_ocr_evidence() -> None:
    result = build_precise_locator_evidence(
        **_request(
            source_candidate={
                "candidate_id": "source-search",
                "label": "Search",
                "role": "nav_item",
                "bbox": {"x": 8, "y": 20, "w": 64, "h": 36},
                "confidence": 0.7,
                "source": "stage2_visual",
                "freshness": "current_capture",
            },
            evidence_candidates=[
                {
                    "candidate_id": "ocr-search",
                    "label": "Search",
                    "role": "nav_item",
                    "bbox": {"x": 96, "y": 112, "w": 72, "h": 34},
                    "confidence": 0.96,
                    "source": "ocr_anchor",
                    "freshness": "current_capture",
                }
            ],
            vista_point={"x": 124, "y": 129},
        )
    )

    assert result["selected_candidate"]["candidate_id"] == "ocr-search"
    assert result["selected_candidate"]["bbox"] == {"x": 96, "y": 112, "w": 72, "h": 34}
    assert result["source_bbox_quality"]["classification"] == "candidate_bbox_misaligned"
    assert result["dry_run_gate"]["status"] == "locate_review_pass"


def test_precise_locator_rejects_stale_or_out_of_parent_source() -> None:
    result = build_precise_locator_evidence(
        **_request(
            source_candidate={
                "candidate_id": "stale",
                "label": "Search",
                "role": "nav_item",
                "bbox": {"x": 300, "y": 20, "w": 64, "h": 36},
                "confidence": 0.9,
                "source": "old_trace",
                "freshness": "stale_capture",
            },
            vista_point={"x": 330, "y": 38},
        )
    )

    assert result["source_bbox_quality"]["classification"] == "candidate_bbox_stale"
    assert result["dry_run_gate"]["status"] == "locate_review_failed"
    assert "no_valid_candidate_inside_parent" in result["dry_run_gate"]["reasons"]


def test_precise_locator_marks_vista_disagreement_for_review() -> None:
    result = build_precise_locator_evidence(
        **_request(vista_point={"x": 170, "y": 210})
    )

    assert result["selected_candidate"]["candidate_id"] == "source-search"
    assert result["dry_run_gate"]["status"] == "needs_human_review"
    assert "vista_point_outside_selected_bbox" in result["dry_run_gate"]["reasons"]


def test_precise_locator_merges_matching_geometry_without_hidden_source_bonus() -> None:
    result = build_precise_locator_evidence(
        **_request(
            evidence_candidates=[
                {
                    "candidate_id": "ocr-search",
                    "label": "Search",
                    "role": "nav_item",
                    "bbox": {"x": 10, "y": 21, "w": 62, "h": 35},
                    "confidence": 0.95,
                    "source": "ocr_anchor",
                    "freshness": "current_capture",
                }
            ]
        )
    )

    selected = result["selected_candidate"]
    assert selected["sources"] == ["ocr_anchor", "stage2_visual"]
    assert result["candidate_source_counts"] == {"ocr_anchor": 1, "stage2_visual": 1}
    assert selected["score_breakdown"]["source_origin_bonus"] == 0.0


def test_precise_locator_does_not_use_generated_control_numbers_to_accept_a_sibling() -> None:
    result = build_precise_locator_evidence(
        **_request(
            target={
                "target_id": "control-7",
                "label": "control 7",
                "role": "control",
                "parent_region_id": "top_bar",
                "parent_region_bbox": {"x": 0, "y": 0, "w": 400, "h": 80},
            },
            source_candidate={
                "candidate_id": "control-7",
                "label": "control 7",
                "role": "control",
                "bbox": {"x": 120, "y": 8, "w": 48, "h": 52},
                "confidence": 0.7,
                "source": "stage2_visual",
                "freshness": "current_capture",
            },
            evidence_candidates=[
                {
                    "candidate_id": "control-9",
                    "label": "control 9",
                    "role": "control",
                    "bbox": {"x": 260, "y": 8, "w": 48, "h": 52},
                    "confidence": 0.7,
                    "source": "same_region_visual_candidate",
                    "freshness": "current_capture",
                }
            ],
            vista_point={"x": 284, "y": 34},
        )
    )

    assert result["selected_candidate"]["candidate_id"] == "control-9"
    assert result["dry_run_gate"]["status"] == "needs_human_review"
    assert "generated_label_cannot_disambiguate_sibling" in result["dry_run_gate"]["reasons"]


def test_precise_locator_keeps_geometry_only_generic_control_as_review_only() -> None:
    result = build_precise_locator_evidence(
        **_request(
            target={
                "target_id": "control-3",
                "label": "control 3",
                "role": "control",
                "parent_region_id": "top_bar",
                "parent_region_bbox": {"x": 0, "y": 0, "w": 400, "h": 80},
            },
            source_candidate={
                "candidate_id": "control-3",
                "label": "control 3",
                "role": "control",
                "bbox": {"x": 120, "y": 8, "w": 48, "h": 52},
                "confidence": 0.9,
                "source": "stage2_visual",
                "freshness": "current_capture",
            },
            vista_point={"x": 144, "y": 34},
        )
    )

    assert result["selected_candidate"]["candidate_id"] == "control-3"
    assert result["dry_run_gate"]["status"] == "needs_human_review"
    assert "target_label_too_generic_for_precise_location" in result["dry_run_gate"]["reasons"]
