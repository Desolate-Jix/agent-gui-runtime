import hashlib
import json
from pathlib import Path

from PIL import Image

from scripts.run_learning_structure_triad_benchmark import run_benchmark


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_case(tmp_path: Path, *, actual_bbox: dict[str, int]) -> tuple[Path, dict]:
    source = tmp_path / "source.png"
    stage1 = tmp_path / "stage1.png"
    final = tmp_path / "final.png"
    for path in (source, stage1, final):
        Image.new("RGB", (1000, 800), "white").save(path)
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "source_image_path": str(source),
                "stage1_region_localization": {
                    "overlay_path": str(stage1),
                    "regions": [
                        {
                            "region_id": "structure_region_main_content",
                            "bbox": actual_bbox,
                        }
                    ],
                },
                "fusion": {"compiled_overlay_path": str(final)},
            }
        ),
        encoding="utf-8",
    )
    case = {
        "case_id": "generic_surface",
        "source_image_path": str(source),
        "screenshot_sha256": _sha256(source),
        "report_path": str(report),
        "expected_regions": [
            {
                "family": "main_content",
                "bbox": {"x": 0, "y": 100, "w": 1000, "h": 700},
            }
        ],
    }
    return source, case


def test_triad_benchmark_scores_matching_regions_and_writes_contact_sheet(tmp_path: Path) -> None:
    _, case = _write_case(
        tmp_path,
        actual_bbox={"x": 0, "y": 104, "w": 1000, "h": 696},
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"cases": [case]}), encoding="utf-8")

    report = run_benchmark(manifest, tmp_path / "out")

    result = report["cases"][0]
    assert result["status"] == "passed"
    assert result["structure_region_match_rate"] == {
        "passed": 1,
        "attempted": 1,
        "rate": 1.0,
    }
    assert result["max_normalized_boundary_error"] <= 0.10
    assert Path(result["triad_contact_sheet_path"]).exists()


def test_triad_benchmark_normalizes_boundary_error_against_expected_region_size(tmp_path: Path) -> None:
    _, case = _write_case(
        tmp_path,
        actual_bbox={"x": 0, "y": 100, "w": 1000, "h": 300},
    )
    case["expected_regions"] = [
        {"family": "main_content", "bbox": {"x": 0, "y": 100, "w": 1000, "h": 200}}
    ]
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"cases": [case]}), encoding="utf-8")

    report = run_benchmark(manifest, tmp_path / "out")

    result = report["cases"][0]
    assert result["status"] == "failed"
    assert result["max_normalized_boundary_error"] == 0.5
    assert result["structure_region_match_rate"] == {"passed": 0, "attempted": 1, "rate": 0.0}


def test_triad_benchmark_marks_checksum_mismatch_invalid_and_excludes_denominator(tmp_path: Path) -> None:
    source, case = _write_case(
        tmp_path,
        actual_bbox={"x": 0, "y": 100, "w": 1000, "h": 700},
    )
    case["screenshot_sha256"] = "0" * 64
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"cases": [case]}), encoding="utf-8")

    report = run_benchmark(manifest, tmp_path / "out")

    result = report["cases"][0]
    assert result["status"] == "invalid"
    assert result["failure_category"] == "stale_fixture"
    assert result["actual_checksum"] == _sha256(source)
    assert report["summary"]["attempted"] == 0
    assert report["summary"]["invalid"] == 1


def test_triad_benchmark_marks_missing_stage1_overlay_invalid(tmp_path: Path) -> None:
    _, case = _write_case(
        tmp_path,
        actual_bbox={"x": 0, "y": 100, "w": 1000, "h": 700},
    )
    report_path = Path(case["report_path"])
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["stage1_region_localization"]["overlay_path"] = ""
    report_path.write_text(json.dumps(payload), encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"cases": [case]}), encoding="utf-8")

    report = run_benchmark(manifest, tmp_path / "out")

    assert report["cases"][0]["status"] == "invalid"
    assert report["cases"][0]["failure_category"] == "triad_evidence_missing"


def test_triad_benchmark_requires_final_item_coverage_when_manifest_requests_it(tmp_path: Path) -> None:
    _, case = _write_case(
        tmp_path,
        actual_bbox={"x": 0, "y": 100, "w": 1000, "h": 700},
    )
    case["min_final_content_vertical_coverage"] = 0.55
    report_path = Path(case["report_path"])
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["fusion"]["fused_review_boxes"] = [
        {"bbox": {"x": 0, "y": 100, "w": 1000, "h": 700}},
        {"bbox": {"x": 100, "y": 120, "w": 200, "h": 80}},
    ]
    report_path.write_text(json.dumps(payload), encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"cases": [case]}), encoding="utf-8")

    report = run_benchmark(manifest, tmp_path / "out")

    result = report["cases"][0]
    assert result["status"] == "failed"
    assert result["final_content_vertical_coverage"] == 0.25
    assert "final_content_coverage_below_threshold" in result["failure_categories"]


def test_triad_benchmark_scores_golden_element_localization_with_center_and_iou_gate(tmp_path: Path) -> None:
    _, case = _write_case(
        tmp_path,
        actual_bbox={"x": 0, "y": 100, "w": 1000, "h": 700},
    )
    case["expected_elements"] = [
        {"element_id": "tile_a", "bbox": {"x": 100, "y": 180, "w": 180, "h": 120}},
        {"element_id": "tile_b", "bbox": {"x": 320, "y": 180, "w": 180, "h": 120}},
    ]
    report_path = Path(case["report_path"])
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["fusion"]["fused_review_boxes"] = [
        {"role": "tile", "bbox": {"x": 104, "y": 182, "w": 176, "h": 118}},
        {"role": "tile", "bbox": {"x": 316, "y": 178, "w": 184, "h": 122}},
    ]
    report_path.write_text(json.dumps(payload), encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"cases": [case]}), encoding="utf-8")

    report = run_benchmark(manifest, tmp_path / "out")

    metric = report["cases"][0]["golden_element_localization"]
    assert metric["passed"] == 2
    assert metric["attempted"] == 2
    assert metric["rate"] == 1.0
    assert metric["max_center_offset_ratio"] <= 0.10
    assert metric["minimum_iou"] >= 0.65
    assert report["summary"]["golden_element_localization"] == {
        "passed": 2,
        "attempted": 2,
        "rate": 1.0,
        "max_center_offset_ratio": 0.0111,
    }
    workflow = report["recognition_regression_workflow"]
    assert workflow["stages"] == [
        "validate_same_source_triad",
        "score_structure_regions",
        "score_golden_elements",
        "require_manual_three_image_review",
    ]
    assert workflow["automated_gate_status"] == "passed"
    assert workflow["manual_visual_review_required"] is True
    assert workflow["interpretation"] == "fixture regression workflow; not general model accuracy"
