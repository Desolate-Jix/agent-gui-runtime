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
from app.learn.recognition.bbox_alignment import bbox_overlap, cross_evidence_overlap_is_acceptable


APP_IDS = ("calculator", "notepad", "paint", "character_map", "control_panel")
_SUPPORT_ROLES = {"button", "link", "input", "checkbox", "menu_item", "tab"}
_UIA_CONTRACT_VERSION = "five_interface_uia_gold_source_v1"
_QWEN_PROFILE_ID = "learn_mode_qwen3_vl_8b"
_QWEN_MODEL_NAME = "Qwen3VL-8B-Instruct-Q4_K_M.gguf"
_QWEN_INVENTORY_GOAL = "inventory the visible interface and identify interactive controls with labels and bounding boxes"


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


def _selection_texts(candidate: dict[str, Any]) -> list[str]:
    texts = [str(candidate.get("content") or "")]
    support_texts = candidate.get("support_texts")
    if isinstance(support_texts, list):
        texts.extend(str(value or "") for value in support_texts)
    return [text for text in texts if _canonical_text(text)]


def forced_similarity(goal: str, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not candidates:
        return None
    scored = [
        (max((_general_text_similarity(goal, text) for text in _selection_texts(item)), default=0.0), index)
        for index, item in enumerate(candidates)
    ]
    _, selected_index = max(scored, key=lambda item: (item[0], -item[1]))
    return candidates[selected_index]


def exact_unique_fail_closed(goal: str, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    target = _goal_target(goal)
    matches = [
        item
        for item in candidates
        if target and any(_canonical_text(text) == target for text in _selection_texts(item))
    ]
    return matches[0] if len(matches) == 1 else None


def _enrich_candidates_with_support(
    candidates: list[dict[str, Any]], support_items: list[dict[str, Any]], source: str
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    enriched: list[dict[str, Any]] = []
    coverage = {"unique_count": 0, "ambiguous_count": 0, "unmatched_count": 0}
    for candidate in candidates:
        copy = dict(candidate)
        matches = [
            item
            for item in support_items
            if isinstance(item, dict)
            and isinstance(item.get("bbox"), dict)
            and _canonical_support_role(item.get("role")) in _SUPPORT_ROLES
            and cross_evidence_overlap_is_acceptable(bbox_overlap(candidate["pixel_bbox"], item["bbox"]))
        ]
        if len(matches) == 1:
            texts = matches[0].get("texts")
            if not isinstance(texts, list):
                texts = [matches[0].get("text")]
            current_texts = copy.get("support_texts")
            copy["support_texts"] = [
                *(current_texts if isinstance(current_texts, list) else []),
                *(str(text or "").strip() for text in texts if str(text or "").strip()),
            ]
            if not copy["support_texts"]:
                copy.pop("support_texts")
            copy["support_evidence"] = [
                *copy.get("support_evidence", []),
                {"source": source, "support_id": str(matches[0].get("support_id") or "")},
            ]
            coverage["unique_count"] += 1
        elif len(matches) > 1:
            coverage["ambiguous_count"] += 1
        else:
            coverage["unmatched_count"] += 1
        enriched.append(copy)
    return enriched, coverage


def _canonical_support_role(value: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").casefold()).strip("_")
    aliases = {
        "menuitem": "menu_item",
        "menu_item": "menu_item",
        "edit": "input",
        "textbox": "input",
        "text_box": "input",
        "hyperlink": "link",
    }
    return aliases.get(normalized, normalized)


def _pixel_bbox(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    try:
        bbox = {axis: int(value[axis]) for axis in ("x", "y", "w", "h")}
    except (KeyError, TypeError, ValueError):
        return None
    return bbox if bbox["w"] > 0 and bbox["h"] > 0 else None


def _support_text_values(*values: Any) -> list[str]:
    texts: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in texts:
            texts.append(text)
    return texts


def _uia_support_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    snapshot = payload.get("uia_snapshot")
    controls = snapshot.get("controls") if isinstance(snapshot, dict) else None
    if not isinstance(controls, list):
        raise BenchmarkInputError("UIA artifact must contain uia_snapshot.controls")
    items: list[dict[str, Any]] = []
    for control in controls:
        if not isinstance(control, dict):
            continue
        role = _canonical_support_role(control.get("control_type"))
        bbox = _pixel_bbox(control.get("bbox"))
        texts = _support_text_values(control.get("name"), control.get("automation_id"), role)
        support_id = str(control.get("control_id") or "").strip()
        if (
            control.get("enabled") is True
            and control.get("visible") is True
            and role in _SUPPORT_ROLES
            and bbox is not None
            and support_id
            and texts
        ):
            items.append({"support_id": support_id, "bbox": bbox, "role": role, "texts": texts})
    return items


def _qwen_support_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    bundle = payload.get("observe_bundle")
    sources = bundle.get("sources") if isinstance(bundle, dict) else None
    vision = sources.get("vision") if isinstance(sources, dict) else None
    regions = vision.get("regions") if isinstance(vision, dict) else None
    if not isinstance(regions, list):
        raise BenchmarkInputError("Qwen artifact must contain observe_bundle.sources.vision.regions")
    items: list[dict[str, Any]] = []
    for region in regions:
        if not isinstance(region, dict):
            continue
        role = _canonical_support_role(region.get("role"))
        bbox = _pixel_bbox(region.get("bbox"))
        texts = _support_text_values(region.get("label"), region.get("ocr_text"), region.get("description"), role)
        support_id = str(region.get("region_id") or "").strip()
        if role in _SUPPORT_ROLES and bbox is not None and support_id and texts:
            items.append({"support_id": support_id, "bbox": bbox, "role": role, "texts": texts})
    return items


def _validate_support_lineage(
    app_id: str, source: str, payload: dict[str, Any], expected_sha: str, expected_size: tuple[int, int]
) -> None:
    label = "UIA" if source == "uia" else "Qwen"
    if source == "uia":
        sha_values = [payload.get("image_sha256")]
        size_values = [payload.get("image_size")]
    elif source == "qwen":
        bundle = payload.get("observe_bundle")
        if not isinstance(bundle, dict):
            raise BenchmarkInputError(f"Qwen observe bundle missing: {app_id}")
        sha_values = [payload.get("screenshot_sha256"), bundle.get("screenshot_sha256")]
        size_values = [bundle.get("image_size")]
    else:
        raise BenchmarkInputError(f"unknown support source: {source}")
    if any(value != expected_sha for value in sha_values):
        raise BenchmarkInputError(f"{label} screenshot SHA lineage mismatch: {app_id}")
    sizes = []
    for value in size_values:
        if not isinstance(value, dict):
            raise BenchmarkInputError(f"{label} screenshot size lineage mismatch: {app_id}")
        try:
            sizes.append((int(value.get("width") or 0), int(value.get("height") or 0)))
        except (TypeError, ValueError):
            raise BenchmarkInputError(f"{label} screenshot size lineage mismatch: {app_id}") from None
    if any(size != expected_size for size in sizes):
        raise BenchmarkInputError(f"{label} screenshot size lineage mismatch: {app_id}")


def _validate_support_attribution(app_id: str, source: str, payload: dict[str, Any]) -> None:
    if source == "uia":
        snapshot = payload.get("uia_snapshot")
        valid = (
            payload.get("contract_version") == _UIA_CONTRACT_VERSION
            and payload.get("app_id") == app_id
            and isinstance(snapshot, dict)
            and snapshot.get("provider") == "windows_uia"
            and snapshot.get("provider_version") == "windows_uia_provider_v1"
            and snapshot.get("status") == "ok"
        )
        if not valid:
            raise BenchmarkInputError(f"UIA support attribution invalid: {app_id}")
        return
    if source != "qwen":
        raise BenchmarkInputError(f"unknown support source: {source}")
    profile = payload.get("model_profile")
    config = payload.get("model_config")
    config_profile = config.get("model_profile") if isinstance(config, dict) else None
    bundle = payload.get("observe_bundle")
    sources = bundle.get("sources") if isinstance(bundle, dict) else None
    vision = sources.get("vision") if isinstance(sources, dict) else None
    expected_profile = lambda value: (
        isinstance(value, dict)
        and value.get("profile_id") == _QWEN_PROFILE_ID
        and value.get("model_name") == _QWEN_MODEL_NAME
        and value.get("model_family") == "Qwen3-VL"
        and value.get("provider_mode") == "local_understanding"
        and value.get("mode_scope") == "learn_only"
        and value.get("artifact_is_authorization") is False
        and value.get("execute_binding_enabled") is False
    )
    valid = (
        payload.get("contract_version") == "actual_parser_output_v1"
        and payload.get("source_type") == "actual_parser_call"
        and payload.get("actual_model_call_in_this_run") is True
        and isinstance(config, dict)
        and config.get("model_profile_id") == _QWEN_PROFILE_ID
        and config.get("model_name") == _QWEN_MODEL_NAME
        and config.get("app_name") == app_id
        and config.get("goal") == _QWEN_INVENTORY_GOAL
        and expected_profile(profile)
        and expected_profile(config_profile)
        and isinstance(vision, dict)
        and vision.get("contract_version") == "vision_regions_v1"
        and vision.get("provider") == _QWEN_MODEL_NAME
    )
    if not valid:
        raise BenchmarkInputError(f"Qwen support attribution invalid: {app_id}")


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
    *,
    selection_input_contract: list[str] | None = None,
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
                "selected_support_evidence": selected.get("support_evidence") if selected else None,
                **evaluation,
            }
        )
    selected_count = sum(item["selected"] for item in details)
    inside_count = sum(item["inside_expected_bbox"] for item in details)
    statuses = Counter(str(item["status"]) for item in details)
    return {
        "case_count": len(details),
        "selection_input_contract": selection_input_contract or ["goal", "current_omni_candidates"],
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


def _empty_support_coverage() -> dict[str, int]:
    return {"unique_count": 0, "ambiguous_count": 0, "unmatched_count": 0}


def _attach_support_coverage(report: dict[str, Any], coverage: dict[str, dict[str, int]]) -> dict[str, Any]:
    report["support_coverage"] = coverage
    return report


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
    uia_payloads = {app_id: _load_json(benchmark_dir / f"{app_id}_uia.json") for app_id in APP_IDS}
    qwen_payloads = {
        app_id: _load_json(benchmark_dir / f"qwen_{app_id}.json" / "actual_parser_output_v1.json")
        for app_id in APP_IDS
    }
    uia_candidates_by_app: dict[str, list[dict[str, Any]]] = {}
    uia_qwen_candidates_by_app: dict[str, list[dict[str, Any]]] = {}
    uia_coverage = _empty_support_coverage()
    qwen_coverage = _empty_support_coverage()
    for app_id in APP_IDS:
        omni_payload = omni_payloads[app_id]
        image_size = omni_payload["image_size"]
        expected_size = (int(image_size["width"]), int(image_size["height"]))
        expected_sha = str(omni_payload["screenshot_sha256"])
        _validate_support_attribution(app_id, "uia", uia_payloads[app_id])
        _validate_support_attribution(app_id, "qwen", qwen_payloads[app_id])
        _validate_support_lineage(app_id, "uia", uia_payloads[app_id], expected_sha, expected_size)
        _validate_support_lineage(app_id, "qwen", qwen_payloads[app_id], expected_sha, expected_size)
        uia_candidates, coverage = _enrich_candidates_with_support(
            candidates_by_app[app_id], _uia_support_items(uia_payloads[app_id]), "uia"
        )
        uia_candidates_by_app[app_id] = uia_candidates
        qwen_candidates, coverage_qwen = _enrich_candidates_with_support(
            uia_candidates, _qwen_support_items(qwen_payloads[app_id]), "qwen"
        )
        uia_qwen_candidates_by_app[app_id] = qwen_candidates
        for key in uia_coverage:
            uia_coverage[key] += coverage[key]
            qwen_coverage[key] += coverage_qwen[key]
    forced_report = _evaluate_mode(cases, candidates_by_app, forced_similarity)
    forced_report["interpretation"] = (
        f"{forced_report['inside_count']}/{len(cases)} is end-to-end goal-selector safe-center accuracy; "
        "not detection recall, bbox IoU, execute safety, or authorization."
    )
    uia_contract = ["goal", "current_omni_candidates", "same_screenshot_uia_semantic_support"]
    uia_qwen_contract = [
        "goal",
        "current_omni_candidates",
        "same_screenshot_uia_semantic_support",
        "same_screenshot_qwen_semantic_support",
    ]
    support_coverage = {"uia": uia_coverage, "qwen": qwen_coverage}
    return {
        "contract_version": "omniparser_vista_goal_selection_benchmark_v3",
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
            "semantic_support": (
                "Same-screenshot UIA and Qwen text/role evidence may enrich Omni candidate selection text only after a unique "
                "accepted overlap; it is non-authorizing and never supplies geometry or a click target."
            ),
        },
        "modes": {
            "forced_similarity": forced_report,
            "exact_unique_fail_closed": _evaluate_mode(cases, candidates_by_app, exact_unique_fail_closed),
            "omni_uia_forced_similarity": _attach_support_coverage(
                _evaluate_mode(
                    cases,
                    uia_candidates_by_app,
                    forced_similarity,
                    selection_input_contract=uia_contract,
                ),
                {"uia": uia_coverage},
            ),
            "omni_uia_exact_unique_fail_closed": _attach_support_coverage(
                _evaluate_mode(
                    cases,
                    uia_candidates_by_app,
                    exact_unique_fail_closed,
                    selection_input_contract=uia_contract,
                ),
                {"uia": uia_coverage},
            ),
            "omni_uia_qwen_forced_similarity": _attach_support_coverage(
                _evaluate_mode(
                    cases,
                    uia_qwen_candidates_by_app,
                    forced_similarity,
                    selection_input_contract=uia_qwen_contract,
                ),
                support_coverage,
            ),
            "omni_uia_qwen_exact_unique_fail_closed": _attach_support_coverage(
                _evaluate_mode(
                    cases,
                    uia_qwen_candidates_by_app,
                    exact_unique_fail_closed,
                    selection_input_contract=uia_qwen_contract,
                ),
                support_coverage,
            ),
        },
        "support_coverage": support_coverage,
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
