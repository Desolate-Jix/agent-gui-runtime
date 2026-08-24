from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.benchmark_vista_scaling import evaluate_point


APP_IDS = ("calculator", "notepad", "paint", "character_map", "control_panel")


class BenchmarkInputError(RuntimeError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BenchmarkInputError(f"invalid benchmark JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BenchmarkInputError(f"benchmark JSON must be an object: {path}")
    return value


def _canonical_text(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    normalized = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", normalized)
    return " ".join(normalized.split())


def _goal_target(goal: str) -> str:
    return _canonical_text(str(goal).split(":", 1)[-1])


def _general_text_similarity(goal: str, content: Any) -> float:
    target = _goal_target(goal)
    candidate = _canonical_text(content)
    if not target or not candidate:
        return 0.0
    if target == candidate:
        return 1.0
    target_tokens = set(target.split())
    candidate_tokens = set(candidate.split())
    overlap = target_tokens & candidate_tokens
    if not overlap:
        if min(len(target), len(candidate)) < 3:
            return 0.0
        sequence_score = SequenceMatcher(None, target, candidate).ratio()
        return round(sequence_score, 6) if sequence_score >= 0.35 else 0.0
    token_f1 = 2 * len(overlap) / (len(target_tokens) + len(candidate_tokens))
    return round(max(token_f1, SequenceMatcher(None, target, candidate).ratio()), 6)


def forced_similarity(goal: str, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not candidates:
        return None
    scored = [(_general_text_similarity(goal, item.get("content")), index) for index, item in enumerate(candidates)]
    _, selected_index = max(scored, key=lambda item: (item[0], -item[1]))
    return candidates[selected_index]


def exact_unique_fail_closed(goal: str, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    target = _goal_target(goal)
    matches = [item for item in candidates if target and _canonical_text(item.get("content")) == target]
    return matches[0] if len(matches) == 1 else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _png_size(path: Path) -> tuple[int, int]:
    try:
        header = path.read_bytes()[:24]
    except FileNotFoundError as exc:
        raise BenchmarkInputError(f"required screenshot is missing: {path}") from exc
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise BenchmarkInputError(f"required screenshot is not a valid PNG: {path}")
    return struct.unpack(">II", header[16:24])


def _interactive_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    size = payload.get("image_size")
    elements = payload.get("elements")
    if not isinstance(size, dict) or not isinstance(elements, list):
        raise BenchmarkInputError("Omni artifact must contain image_size and elements")
    width, height = int(size.get("width") or 0), int(size.get("height") or 0)
    if width <= 0 or height <= 0 or "normalized" not in str(payload.get("coordinate_space") or "").casefold():
        raise BenchmarkInputError("Omni artifact must use a positive normalized image coordinate space")
    candidates: list[dict[str, Any]] = []
    for element in elements:
        if not isinstance(element, dict) or element.get("interactivity") is not True:
            continue
        box = element.get("bbox")
        if not isinstance(box, list) or len(box) != 4:
            raise BenchmarkInputError("interactive Omni candidate has an invalid bbox")
        x1, y1, x2, y2 = (float(value) for value in box)
        candidate = dict(element)
        candidate["pixel_bbox"] = {
            "x": x1 * width,
            "y": y1 * height,
            "w": (x2 - x1) * width,
            "h": (y2 - y1) * height,
        }
        candidates.append(candidate)
    return candidates


def _validate_omni_artifact_attribution(app_id: str, payload: dict[str, Any]) -> None:
    exact_values = {
        "contract_version": "screen_parser_result_v1",
        "provider": "omniparser",
        "status": "success",
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "review_only": True,
        "grounding_eligible": False,
    }
    invalid_fields = []
    for field, expected in exact_values.items():
        actual = payload.get(field)
        if (isinstance(expected, bool) and actual is not expected) or (
            not isinstance(expected, bool) and actual != expected
        ):
            invalid_fields.append(field)
    for field in ("profile_id", "model_revision", "capture_id", "source_run_id"):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            invalid_fields.append(field)
    if not isinstance(payload.get("provenance"), dict):
        invalid_fields.append("provenance")
    if invalid_fields:
        raise BenchmarkInputError(
            f"Omni artifact attribution invalid: {app_id}: {','.join(sorted(set(invalid_fields)))}"
        )


def _validate_lineage(
    benchmark_dir: Path,
    cases: list[dict[str, Any]],
    omni_payloads: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    manifest = _load_json(benchmark_dir / "capture_manifest.json")
    screens = manifest.get("screens")
    if manifest.get("screen_count") != 5 or not isinstance(screens, list) or len(screens) != 5:
        raise BenchmarkInputError("capture manifest must contain exactly five screens")
    by_app = {str(item.get("app_id")): item for item in screens if isinstance(item, dict)}
    if set(by_app) != set(APP_IDS):
        raise BenchmarkInputError("capture manifest application set is not frozen five-screen set")

    for app_id in APP_IDS:
        screen = by_app[app_id]
        expected_sha = str(screen.get("image_sha256") or "")
        source_image = Path(str(screen.get("image_path") or "")).resolve()
        artifact_image = (benchmark_dir / f"{app_id}.png").resolve()
        payload = omni_payloads[app_id]
        size = payload.get("image_size") or {}
        expected_size = (int(size.get("width") or 0), int(size.get("height") or 0))
        if not expected_sha or payload.get("screenshot_sha256") != expected_sha:
            raise BenchmarkInputError(f"Omni screenshot SHA lineage mismatch: {app_id}")
        for image in (source_image, artifact_image):
            if _sha256(image) != expected_sha:
                raise BenchmarkInputError(f"screenshot SHA mismatch: {app_id}: {image}")
            if _png_size(image) != expected_size:
                raise BenchmarkInputError(f"screenshot size mismatch: {app_id}: {image}")

    if len(cases) != 40:
        raise BenchmarkInputError("frozen benchmark must contain exactly 40 cases")
    binding_count = 0
    counts: Counter[str] = Counter()
    for case in cases:
        app_id = str(case.get("app_name") or "")
        if app_id not in by_app:
            raise BenchmarkInputError(f"case has unknown app binding: {app_id}")
        case_image = Path(str(case.get("image_path") or "")).resolve()
        manifest_image = Path(str(by_app[app_id].get("image_path") or "")).resolve()
        if case_image != manifest_image:
            raise BenchmarkInputError(f"case-to-image binding mismatch: {case.get('case_id')}")
        counts[app_id] += 1
        binding_count += 1
    if any(counts[app_id] != 8 for app_id in APP_IDS):
        raise BenchmarkInputError("each frozen screenshot must bind exactly eight cases")
    return {
        "status": "valid",
        "screen_count": 5,
        "case_count": 40,
        "case_to_image_binding_count": binding_count,
    }


def _candidate_center(candidate: dict[str, Any]) -> dict[str, int]:
    box = candidate["pixel_bbox"]
    return {
        "x": round(float(box["x"]) + float(box["w"]) / 2),
        "y": round(float(box["y"]) + float(box["h"]) / 2),
    }


def _evaluate_mode(
    cases: list[dict[str, Any]],
    candidates_by_app: dict[str, list[dict[str, Any]]],
    selector: Callable[[str, list[dict[str, Any]]], dict[str, Any] | None],
) -> dict[str, Any]:
    details: list[dict[str, Any]] = []
    per_screen = {
        app_id: {"case_count": 0, "selected_count": 0, "abstained_count": 0, "inside_count": 0, "pass_count": 0, "risky_count": 0, "fail_count": 0}
        for app_id in APP_IDS
    }
    for case in cases:
        app_id = str(case["app_name"])
        selected = selector(str(case["goal"]), candidates_by_app[app_id])
        evaluation = evaluate_point(
            point=_candidate_center(selected) if selected is not None else None,
            expected_bbox=case["expected_bbox"],
            expected_click_point=case["expected_click_point"],
            allowed_distance_px=float(case["allowed_distance_px"]),
            neighbor_bboxes=case.get("neighbor_bboxes") or [],
        )
        screen = per_screen[app_id]
        screen["case_count"] += 1
        screen["selected_count" if selected is not None else "abstained_count"] += 1
        screen["inside_count"] += int(evaluation["inside_expected_bbox"])
        screen[f"{evaluation['status']}_count"] += 1
        details.append(
            {
                "case_id": case.get("case_id"),
                "app_id": app_id,
                "selected": selected is not None,
                "selected_element_id": selected.get("element_id") if selected else None,
                "selected_content": selected.get("content") if selected else None,
                **evaluation,
            }
        )
    selected_count = sum(item["selected"] for item in details)
    inside_count = sum(item["inside_expected_bbox"] for item in details)
    statuses = Counter(str(item["status"]) for item in details)
    return {
        "selection_input_contract": ["goal", "current_omni_candidates"],
        "selected_count": selected_count,
        "abstained_count": len(details) - selected_count,
        "inside_count": inside_count,
        "inside_rate": round(inside_count / len(details), 6),
        "selection_precision": round(inside_count / selected_count, 6) if selected_count else 0.0,
        "pass_count": statuses["pass"],
        "risky_count": statuses["risky"],
        "fail_count": statuses["fail"],
        "per_screen": per_screen,
        "details": details,
    }


def _posthoc_safe_center_point_ceiling(
    cases: list[dict[str, Any]], candidates_by_app: dict[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    inside_count = 0
    for case in cases:
        box = case["expected_bbox"]
        for candidate in candidates_by_app[str(case["app_name"])]:
            point = _candidate_center(candidate)
            if box["x"] <= point["x"] <= box["x"] + box["w"] and box["y"] <= point["y"] <= box["y"] + box["h"]:
                inside_count += 1
                break
    return {
        "evaluation_only": True,
        "used_for_selection": False,
        "definition": (
            "Any current Omni candidate bbox center point lies within the target expected bbox; "
            "this is not IoU/bbox recall and does not establish execute safety."
        ),
        "inside_count": inside_count,
        "case_count": len(cases),
        "inside_rate": round(inside_count / len(cases), 6),
    }


def _validate_vista_reference_bindings(cases: list[dict[str, Any]], results: list[dict[str, Any]]) -> None:
    expected_ids = [str(case.get("case_id") or "") for case in cases]
    actual_ids = [str(result.get("case_id") or "") for result in results]
    if len(set(expected_ids)) != len(expected_ids) or len(set(actual_ids)) != len(actual_ids):
        raise BenchmarkInputError("frozen VISTA reference contains duplicate case IDs")
    if actual_ids != expected_ids:
        raise BenchmarkInputError("frozen VISTA reference ordered case IDs do not exactly match vista_cases")
    for case, result in zip(cases, results, strict=True):
        expected_bbox = case.get("expected_bbox")
        reference_bbox = result.get("expected_bbox")
        if reference_bbox is not None and reference_bbox != expected_bbox:
            raise BenchmarkInputError(f"frozen VISTA reference bbox mismatch: {case.get('case_id')}")


def _vista_reference(benchmark_dir: Path, cases: list[dict[str, Any]]) -> dict[str, Any]:
    payload = _load_json(benchmark_dir / "vista.json")
    results = payload.get("results")
    if not isinstance(results, list) or len(results) != 40:
        raise BenchmarkInputError("frozen VISTA reference must contain 40 results")
    if not all(isinstance(item, dict) for item in results):
        raise BenchmarkInputError("frozen VISTA reference results must be objects")
    _validate_vista_reference_bindings(cases, results)
    statuses = Counter(str(item.get("status")) for item in results if isinstance(item, dict))
    return {
        "source": "frozen_vista_json_no_model_execution",
        "case_count": len(results),
        "inside_count": sum(bool(item.get("inside_expected_bbox")) for item in results),
        "pass_count": statuses["pass"],
        "risky_count": statuses["risky"],
        "fail_count": statuses["fail"],
        "gate_allowed_count": sum(bool(item.get("gate_allowed")) for item in results),
    }


def run_benchmark(benchmark_dir: Path) -> dict[str, Any]:
    benchmark_dir = Path(benchmark_dir).resolve()
    cases_payload = _load_json(benchmark_dir / "vista_cases.json")
    cases = cases_payload.get("cases")
    if cases_payload.get("case_count") != 40 or not isinstance(cases, list):
        raise BenchmarkInputError("frozen VISTA cases contract is invalid")
    omni_payloads = {app_id: _load_json(benchmark_dir / f"omni_{app_id}.json") for app_id in APP_IDS}
    for app_id, payload in omni_payloads.items():
        _validate_omni_artifact_attribution(app_id, payload)
    lineage = _validate_lineage(benchmark_dir, cases, omni_payloads)
    candidates_by_app = {app_id: _interactive_candidates(payload) for app_id, payload in omni_payloads.items()}
    forced_report = _evaluate_mode(cases, candidates_by_app, forced_similarity)
    forced_report["interpretation"] = (
        f"{forced_report['inside_count']}/{len(cases)} is end-to-end goal-selector safe-center accuracy; "
        "not detection recall, bbox IoU, execute safety, or authorization."
    )
    return {
        "contract_version": "omniparser_vista_goal_selection_benchmark_v2",
        "scope": "frozen artifact review benchmark only; no model, GUI, click, or authorization",
        "review_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "lineage_validation": lineage,
        "metric_definitions": {
            "selection_precision": (
                "Selected cases whose candidate bbox center point lies within the target expected bbox, divided by selected cases."
            ),
            "forced_similarity_safe_center_accuracy": (
                "End-to-end goal-selector safe-center accuracy over all frozen cases; this is not detection recall, "
                "bbox IoU, execute safety, or authorization."
            ),
            "posthoc_safe_center_point_ceiling": (
                "Evaluation-only upper bound where any current Omni candidate bbox center point lies within the target; "
                "not IoU/bbox recall and never used for selection."
            ),
        },
        "modes": {
            "forced_similarity": forced_report,
            "exact_unique_fail_closed": _evaluate_mode(cases, candidates_by_app, exact_unique_fail_closed),
        },
        "posthoc_safe_center_point_ceiling": _posthoc_safe_center_point_ceiling(cases, candidates_by_app),
        "vista_frozen_reference": _vista_reference(benchmark_dir, cases),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark goal-only OmniParser selection on frozen VISTA cases.")
    parser.add_argument("--benchmark-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = run_benchmark(args.benchmark_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for mode, summary in report["modes"].items():
            print(
                f"{mode}: selected={summary['selected_count']} abstained={summary['abstained_count']} "
                f"inside={summary['inside_count']} pass={summary['pass_count']} "
                f"risky={summary['risky_count']} fail={summary['fail_count']}"
            )
        print(f"report_path={args.out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
