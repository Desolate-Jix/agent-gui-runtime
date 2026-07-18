from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from scripts import run_deterministic_first_recognition_benchmark as first_runner
from scripts.run_deterministic_first_recognition_benchmark import (
    resolve_fixture_path,
    summarize_first_recognition,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tests/fixtures/deterministic_first_recognition_manifest_v1.json"


def test_first_recognition_manifest_has_multiple_distinct_interfaces() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    families = {case["app_family"] for case in manifest["cases"]}
    assert len(manifest["cases"]) == 9
    assert len(families) == 9
    assert {"windows_settings", "file_explorer", "wechat"}.issubset(families)
    excluded = manifest["excluded_cases"]
    assert excluded == [
        {
            **excluded[0],
            "case_id": "nvidia_overlay_stage1_blocker",
            "reason": "wrong_surface_fixture",
            "counts_toward_positive_recognition": False,
        }
    ]


def test_first_recognition_manifest_replays_all_nine_cases(tmp_path: Path) -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    source_root = Path(str(manifest.get("source_root") or ROOT))
    missing: list[str] = []
    for case in manifest["cases"]:
        for key in ("trace_path", "screenshot_path"):
            try:
                resolve_fixture_path(case[key], source_root=source_root)
            except FileNotFoundError:
                missing.append(case[key])
    if missing:
        pytest.skip(f"not_available: local privacy-sensitive evidence is not provisioned ({len(missing)} files)")

    report = first_runner.run_manifest(MANIFEST, tmp_path / "first-recognition")

    assert report["invalid_cases"] == []
    assert report["aggregate"] == {
        **report["aggregate"],
        "attempted": 9,
        "invalid": 0,
        "canonical_root_confirmed": 9,
        "root_validator_valid": 9,
        "stage1_gate_passed": 9,
        "stage2_completed": 9,
        "three_image_complete": 9,
        "root_zone_expectation_passed": 9,
    }
    assert all(
        all(Path(path).exists() for path in case["summary"]["three_image_artifacts"].values())
        for case in report["cases"]
    )


def test_hermetic_runner_covers_nine_case_aggregation_and_production_provenance(tmp_path: Path) -> None:
    screenshot = tmp_path / "fixture.png"
    Image.new("RGB", (240, 160), "white").save(screenshot)
    trace = tmp_path / "trace.json"
    trace.write_text(
        json.dumps(
            {
                "result": {
                    "app_name": "hermetic_fixture",
                    "image_size": {"width": 240, "height": 160},
                    "screen_inventory": {
                        "page_elements": [
                            {
                                "id": "content",
                                "label": "Content",
                                "role": "document",
                                "bbox": {"x": 20, "y": 20, "w": 200, "h": 120},
                            }
                        ]
                    },
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    screenshot_sha = hashlib.sha256(screenshot.read_bytes()).hexdigest()
    trace_sha = hashlib.sha256(trace.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "source_root": str(tmp_path),
                "require_stage1_gate": True,
                "cases": [
                    {
                        "case_id": f"hermetic_{index}",
                        "app_family": f"fixture_family_{index}",
                        "trace_path": trace.name,
                        "trace_sha256": trace_sha,
                        "screenshot_path": screenshot.name,
                        "screenshot_sha256": screenshot_sha,
                        "expected_root_zones": ["main_content"],
                    }
                    for index in range(1, 10)
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = first_runner.run_manifest(manifest, tmp_path / "out")

    assert report["aggregate"] == {
        **report["aggregate"],
        "attempted": 9,
        "invalid": 0,
        "canonical_root_confirmed": 9,
        "root_validator_valid": 9,
        "stage1_gate_passed": 9,
        "stage2_completed": 9,
        "three_image_complete": 9,
        "root_zone_expectation_passed": 9,
    }
    for case in report["cases"]:
        full_report = json.loads(Path(case["full_report_path"]).read_text(encoding="utf-8"))
        stage1 = full_report["stage1_structure"]
        assert stage1["partition_contract"] == "deterministic_root_partition_v1"
        assert stage1["root_validator"]["valid"] is True


def test_hermetic_runner_rejects_stale_checksum(tmp_path: Path) -> None:
    screenshot = tmp_path / "fixture.png"
    Image.new("RGB", (40, 40), "white").save(screenshot)
    trace = tmp_path / "trace.json"
    trace.write_text("{}", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "source_root": str(tmp_path),
                "cases": [
                    {
                        "case_id": "stale_fixture",
                        "trace_path": trace.name,
                        "trace_sha256": "0" * 64,
                        "screenshot_path": screenshot.name,
                        "screenshot_sha256": hashlib.sha256(screenshot.read_bytes()).hexdigest(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report = first_runner.run_manifest(manifest, tmp_path / "out")

    assert report["aggregate"]["attempted"] == 0
    assert report["aggregate"]["invalid"] == 1
    assert report["invalid_cases"] == [
        {
            **report["invalid_cases"][0],
            "case_id": "stale_fixture",
            "failure_category": "invalid_fixture",
        }
    ]
    assert "stale trace" in report["invalid_cases"][0]["error"]


def test_resolve_fixture_path_can_use_external_source_root(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    fixture = source_root / "trace.json"
    fixture.write_text("{}", encoding="utf-8")
    assert resolve_fixture_path("trace.json", source_root=source_root, project_root=tmp_path / "worktree") == fixture


def test_summary_reports_canonical_root_gate_and_render_artifacts() -> None:
    summary = summarize_first_recognition(
        {
            "stage1_source": "deterministic_root_partition_v1",
            "stage1_structure": {
                "region_count": 3,
                "source": "deterministic_root_partition_v1",
                "root_validator": {"valid": True},
            },
            "stage1_gate": {"status": "passed", "failure_categories": []},
            "stage2_numbering": {
                "region_count": 3,
                "numbered_item_count": 24,
                "calibration_candidate_count": 11,
                "skipped": False,
            },
            "fusion": {"fused_review_boxes": [{}, {}]},
            "page_details": {"sections": [{}, {}, {}]},
            "learning_draft": {"regions": [{}, {}]},
        },
        original_path="01.png",
        root_overlay_path="02.png",
        final_overlay_path="03.png",
    )
    assert summary["stage1_source"] == "deterministic_root_partition_v1"
    assert summary["stage1_gate_status"] == "passed"
    assert summary["stage2_numbering_skipped"] is False
    assert summary["stage2_calibration_candidate_count"] == 11
    assert summary["three_image_artifacts"] == {
        "original": "01.png",
        "root_partition": "02.png",
        "final_fusion": "03.png",
    }
    assert summary["fused_review_box_count"] == 2


def test_root_zone_expectation_compares_ordered_stage1_topology() -> None:
    evaluator = getattr(first_runner, "evaluate_root_zone_expectation", None)
    assert evaluator is not None
    report = {
        "stage1_structure": {
            "structure_regions": [
                {"zone_id": "left_nav"},
                {"zone_id": "main_content"},
            ]
        }
    }
    assert evaluator(report, ["left_nav", "main_content"]) == {
        "passed": True,
        "expected": ["left_nav", "main_content"],
        "actual": ["left_nav", "main_content"],
    }
    assert evaluator(report, ["top_bar", "main_content"])["passed"] is False


def test_runner_does_not_read_retired_shadow_validator() -> None:
    source = Path("scripts/run_deterministic_first_recognition_benchmark.py").read_text(encoding="utf-8")
    assert "shadow_validator" not in source
