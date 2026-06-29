from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.operation.screen_inventory import build_screen_inventory


def _load_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_cases = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(raw_cases, list):
        raise ValueError(f"Benchmark cases must be a list or contain cases: {path}")
    cases: list[dict[str, Any]] = []
    for item in raw_cases:
        if not isinstance(item, dict):
            continue
        source_path = ROOT_DIR / str(item.get("screen_reading_path") or item.get("trace_path") or "")
        if not source_path.exists():
            raise FileNotFoundError(f"Inventory benchmark source not found: {source_path}")
        cases.append({**item, "source_path": source_path})
    if not cases:
        raise ValueError(f"No inventory benchmark cases found in {path}")
    return cases


def _load_screen_reading(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if payload.get("contract_version") == "screen_reading_v1":
        return payload
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    if result.get("contract_version") == "screen_reading_v1":
        return result
    screen = result.get("screen_reading") if isinstance(result.get("screen_reading"), dict) else {}
    if screen.get("contract_version") == "screen_reading_v1":
        return screen
    parse_result = result.get("parse_result") if isinstance(result.get("parse_result"), dict) else {}
    screen = parse_result.get("screen_reading") if isinstance(parse_result.get("screen_reading"), dict) else {}
    if screen.get("contract_version") == "screen_reading_v1":
        return screen
    raise ValueError(f"Could not find screen_reading_v1 in {path}")


def _score_case(case: dict[str, Any], inventory: dict[str, Any], elapsed_ms: float) -> dict[str, Any]:
    typed_gt = _typed_ground_truth(case)
    expected_actions = [str(item) for item in case.get("expected_actions") or []] + _gt_labels(
        typed_gt,
        bucket="actions",
    )
    expected_page_elements = [str(item) for item in case.get("expected_page_elements") or []] + _gt_labels(
        typed_gt,
        bucket="page_elements",
    )
    expected_metadata = [str(item) for item in case.get("expected_metadata") or []] + _gt_labels(
        typed_gt,
        bucket="metadata",
    )
    expected_cards = [str(item) for item in case.get("expected_cards") or []] + _gt_labels(
        typed_gt,
        bucket="cards",
    )
    action_labels = [str(item.get("label") or "") for item in inventory.get("available_actions") or [] if isinstance(item, dict)]
    page_labels = [str(item.get("text") or item.get("label") or "") for item in inventory.get("page_elements") or [] if isinstance(item, dict)]
    metadata_labels = page_labels
    card_labels = [str(item.get("label") or "") for item in inventory.get("cards") or [] if isinstance(item, dict)]
    action_score = _score_terms(action_labels, expected_actions)
    page_score = _score_terms(page_labels, expected_page_elements)
    metadata_score = _score_terms(metadata_labels, expected_metadata)
    card_score = _score_terms(card_labels, expected_cards)
    false_positive_actions = [
        label
        for label in action_labels
        if label and not _matches_any(label, expected_actions) and not _allow_extra_action(label, case)
    ]
    return {
        "case_id": case.get("case_id") or case["source_path"].stem,
        "source_path": str(case["source_path"]),
        "elapsed_ms": round(elapsed_ms, 3),
        "action_recall": action_score["recall"],
        "page_element_recall": page_score["recall"],
        "metadata_recall": metadata_score["recall"],
        "card_recall": card_score["recall"],
        "action_precision": round(
            (len(action_labels) - len(false_positive_actions)) / len(action_labels),
            4,
        )
        if action_labels
        else None,
        "action_precision_proxy": round(
            (len(action_labels) - len(false_positive_actions)) / len(action_labels),
            4,
        )
        if action_labels
        else None,
        "clickable_false_positive_count": len(false_positive_actions),
        "clickable_false_positive_rate": round(len(false_positive_actions) / len(action_labels), 4) if action_labels else None,
        "clickable_false_positive_labels": false_positive_actions[:20],
        "duplicate_rate": (inventory.get("quality") or {}).get("duplicate_rate"),
        "coordinate_coverage": (inventory.get("quality") or {}).get("coordinate_coverage"),
        "candidate_count": len(action_labels),
        "typed_ground_truth": {
            "item_count": len(typed_gt),
            "action_count": len(_gt_labels(typed_gt, bucket="actions")),
            "page_element_count": len(_gt_labels(typed_gt, bucket="page_elements")),
            "metadata_count": len(_gt_labels(typed_gt, bucket="metadata")),
            "card_count": len(_gt_labels(typed_gt, bucket="cards")),
        },
        "matched": {
            "actions": action_score,
            "page_elements": page_score,
            "metadata": metadata_score,
            "cards": card_score,
        },
        "summary": inventory.get("summary"),
    }


def _typed_ground_truth(case: dict[str, Any]) -> list[dict[str, Any]]:
    raw = case.get("gt") or case.get("ground_truth") or []
    return [item for item in raw if isinstance(item, dict)]


def _gt_labels(items: list[dict[str, Any]], *, bucket: str) -> list[str]:
    labels = []
    for item in items:
        label = str(item.get("label") or item.get("text") or "").strip()
        if not label or not _gt_in_bucket(item, bucket=bucket):
            continue
        labels.append(label)
    return labels


def _gt_in_bucket(item: dict[str, Any], *, bucket: str) -> bool:
    kind = _normalize_text(item.get("kind"))
    clickable = item.get("clickable")
    if bucket == "actions":
        return clickable is True or kind.startswith("action")
    if bucket == "cards":
        return kind in {"card container", "card", "job card", "news card", "result card"}
    if bucket == "metadata":
        return "metadata" in kind or kind in {"filter group label", "salary", "location", "company", "posted", "date"}
    if bucket == "page_elements":
        return not _gt_in_bucket(item, bucket="actions") and not _gt_in_bucket(item, bucket="cards")
    return False


def _score_terms(labels: list[str], expected: list[str]) -> dict[str, Any]:
    matched = []
    missing = []
    for term in expected:
        match = next((label for label in labels if _term_match(label, term)), None)
        if match is None:
            missing.append(term)
        else:
            matched.append({"expected": term, "actual": match})
    return {
        "expected_count": len(expected),
        "matched_count": len(matched),
        "missing": missing,
        "matched": matched,
        "recall": round(len(matched) / len(expected), 4) if expected else None,
    }


def _matches_any(label: str, expected: list[str]) -> bool:
    return any(_term_match(label, term) for term in expected)


def _term_match(label: str, term: str) -> bool:
    left = _normalize_text(label)
    right = _normalize_text(term)
    return bool(left and right and (left == right or left in right or right in left))


def _allow_extra_action(label: str, case: dict[str, Any]) -> bool:
    allowed = [str(item) for item in case.get("allowed_extra_actions") or []]
    return _matches_any(label, allowed)


def _normalize_text(value: Any) -> str:
    text = str(value or "").casefold()
    text = re.sub(r"[^0-9a-z\u4e00-\u9fff$]+", " ", text)
    return " ".join(text.split())


def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    cases = _load_cases(ROOT_DIR / args.cases)
    results = []
    for case in cases:
        screen_reading = _load_screen_reading(case["source_path"])
        started = time.perf_counter()
        inventory = build_screen_inventory(screen_reading, goal=str(case.get("goal") or ""))
        elapsed_ms = (time.perf_counter() - started) * 1000
        case_result = _score_case(case, inventory, elapsed_ms)
        if args.include_inventory:
            case_result["screen_inventory"] = inventory
        results.append(case_result)
    action_recalls = [item["action_recall"] for item in results if item.get("action_recall") is not None]
    page_recalls = [item["page_element_recall"] for item in results if item.get("page_element_recall") is not None]
    card_recalls = [item["card_recall"] for item in results if item.get("card_recall") is not None]
    metadata_recalls = [item["metadata_recall"] for item in results if item.get("metadata_recall") is not None]
    precision_values = [item["action_precision"] for item in results if item.get("action_precision") is not None]
    return {
        "contract_version": "screen_inventory_benchmark_v1",
        "cases_path": args.cases,
        "summary": {
            "case_count": len(results),
            "avg_elapsed_ms": _average([float(item["elapsed_ms"]) for item in results]),
            "p95_elapsed_ms": _p95([float(item["elapsed_ms"]) for item in results]),
            "avg_action_recall": _average(action_recalls),
            "avg_page_element_recall": _average(page_recalls),
            "avg_metadata_recall": _average(metadata_recalls),
            "avg_card_recall": _average(card_recalls),
            "avg_action_precision": _average(precision_values),
            "avg_action_precision_proxy": _average(precision_values),
            "avg_clickable_false_positive_rate": _average([float(item["clickable_false_positive_rate"]) for item in results if item.get("clickable_false_positive_rate") is not None]),
            "avg_duplicate_rate": _average([float(item["duplicate_rate"]) for item in results if item.get("duplicate_rate") is not None]),
            "avg_coordinate_coverage": _average([float(item["coordinate_coverage"]) for item in results if item.get("coordinate_coverage") is not None]),
            "avg_candidate_count": _average([float(item["candidate_count"]) for item in results]),
        },
        "results": results,
    }


def _average(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((len(ordered) - 1) * 0.95)))
    return round(ordered[index], 4)


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark screen_inventory_v1 recall and latency.")
    parser.add_argument("--cases", default="configs/screen_inventory_benchmark_cases.json")
    parser.add_argument("--output", default="artifacts/accuracy-checks/screen_inventory_benchmark_report.json")
    parser.add_argument("--include-inventory", action=argparse.BooleanOptionalAction, default=False)
    args = parser.parse_args()
    report = run_benchmark(args)
    output_path = ROOT_DIR / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output_path), "summary": report["summary"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
