from __future__ import annotations

import argparse

from scripts import benchmark_screen_inventory


def test_screen_inventory_benchmark_scores_typed_ground_truth() -> None:
    args = argparse.Namespace(
        cases="configs/screen_inventory_benchmark_cases.json",
        include_inventory=False,
    )

    report = benchmark_screen_inventory.run_benchmark(args)

    assert report["contract_version"] == "screen_inventory_benchmark_v1"
    assert report["summary"]["case_count"] == 1
    assert report["summary"]["avg_action_recall"] == 1.0
    assert report["summary"]["avg_page_element_recall"] == 1.0
    assert report["summary"]["avg_metadata_recall"] == 1.0
    assert report["summary"]["avg_card_recall"] == 1.0
    assert report["summary"]["avg_action_precision"] == 1.0
    assert report["summary"]["avg_clickable_false_positive_rate"] == 0.0

    result = report["results"][0]
    assert result["typed_ground_truth"] == {
        "item_count": 9,
        "action_count": 6,
        "page_element_count": 3,
        "metadata_count": 3,
        "card_count": 1,
    }
    assert result["matched"]["metadata"]["matched_count"] == 3
    assert result["clickable_false_positive_labels"] == []

