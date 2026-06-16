from __future__ import annotations

import argparse
import json
import math
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_MAX_EDGES = [448, 512, 640, 768, 896, 960]


def _load_cases(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8-sig").strip()
    if not text:
        return []
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    payload = json.loads(text)
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("cases"), list):
        return [item for item in payload["cases"] if isinstance(item, dict)]
    raise ValueError("Benchmark cases must be a JSON list, JSON object with cases[], or JSONL")


def _bbox_dict(raw: Any) -> dict[str, int]:
    if isinstance(raw, dict):
        if {"x", "y", "w", "h"}.issubset(raw):
            return {"x": int(raw["x"]), "y": int(raw["y"]), "w": int(raw["w"]), "h": int(raw["h"])}
        if {"x1", "y1", "x2", "y2"}.issubset(raw):
            return {
                "x": int(raw["x1"]),
                "y": int(raw["y1"]),
                "w": int(raw["x2"]) - int(raw["x1"]),
                "h": int(raw["y2"]) - int(raw["y1"]),
            }
    if isinstance(raw, list) and len(raw) >= 4:
        x1, y1, x2, y2 = [int(value) for value in raw[:4]]
        return {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1}
    raise ValueError(f"Unsupported bbox: {raw!r}")


def _point_dict(raw: Any) -> dict[str, int]:
    if isinstance(raw, dict):
        return {"x": int(raw["x"]), "y": int(raw["y"])}
    if isinstance(raw, list) and len(raw) >= 2:
        return {"x": int(raw[0]), "y": int(raw[1])}
    raise ValueError(f"Unsupported point: {raw!r}")


def _distance(a: dict[str, int], b: dict[str, int]) -> float:
    return math.hypot(float(a["x"]) - float(b["x"]), float(a["y"]) - float(b["y"]))


def evaluate_point(
    *,
    point: dict[str, int] | None,
    expected_bbox: dict[str, int],
    expected_click_point: dict[str, int],
    allowed_distance_px: float,
    neighbor_bboxes: list[dict[str, int]] | None = None,
) -> dict[str, Any]:
    if point is None:
        return {
            "status": "fail",
            "inside_expected_bbox": False,
            "distance_to_expected_click": None,
            "edge_margin_px": None,
            "nearest_neighbor_mistake": False,
            "reasons": ["missing_point"],
        }
    x = int(point["x"])
    y = int(point["y"])
    left = int(expected_bbox["x"])
    top = int(expected_bbox["y"])
    right = left + int(expected_bbox["w"])
    bottom = top + int(expected_bbox["h"])
    inside = left <= x <= right and top <= y <= bottom
    edge_margin = min(x - left, right - x, y - top, bottom - y) if inside else None
    distance = _distance(point, expected_click_point)
    neighbor_hit = False
    neighbor_distance = None
    for neighbor in neighbor_bboxes or []:
        nx1 = int(neighbor["x"])
        ny1 = int(neighbor["y"])
        nx2 = nx1 + int(neighbor["w"])
        ny2 = ny1 + int(neighbor["h"])
        if nx1 <= x <= nx2 and ny1 <= y <= ny2:
            neighbor_hit = True
        center = {"x": round((nx1 + nx2) / 2), "y": round((ny1 + ny2) / 2)}
        value = _distance(point, center)
        neighbor_distance = value if neighbor_distance is None else min(neighbor_distance, value)

    reasons: list[str] = []
    if neighbor_hit:
        reasons.append("nearest_neighbor_mistake")
    if not inside:
        reasons.append("point_outside_expected_bbox")
    if distance > allowed_distance_px:
        reasons.append("distance_above_allowed")
    if inside and edge_margin is not None and edge_margin < 6:
        reasons.append("edge_margin_below_6px")
    if neighbor_distance is not None and neighbor_distance < 20:
        reasons.append("near_neighbor_within_20px")

    if neighbor_hit or not inside or distance > allowed_distance_px * 1.5:
        status = "fail"
    elif reasons:
        status = "risky"
    else:
        status = "pass"
    return {
        "status": status,
        "inside_expected_bbox": inside,
        "distance_to_expected_click": round(distance, 3),
        "edge_margin_px": edge_margin,
        "nearest_neighbor_mistake": neighbor_hit,
        "nearest_neighbor_distance": round(neighbor_distance, 3) if neighbor_distance is not None else None,
        "reasons": reasons,
    }


def _post_json(url: str, payload: dict[str, Any], *, timeout_seconds: float) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc


def run_case(
    *,
    base_url: str,
    case: dict[str, Any],
    max_edge: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    expected_bbox = _bbox_dict(case["expected_bbox"])
    expected_click_point = _point_dict(case["expected_click_point"])
    neighbors = [_bbox_dict(item) for item in case.get("neighbor_bboxes", []) if item is not None]
    allowed_distance_px = float(case.get("allowed_distance_px") or 24)
    request_payload = {
        "image_path": str(Path(case["image_path"])),
        "provider_mode": case.get("provider_mode") or "local_grounding",
        "task": case.get("task") or "click_target",
        "goal": case["goal"],
        "app_name": case.get("app_name") or "benchmark",
        "agent_mode": "execute",
        "metadata": {
            "vista_direct_grounding": {
                "enabled": True,
                "timeout_seconds": timeout_seconds,
                "max_edge": int(max_edge),
                "refine": False,
            }
        },
        "top_k": int(case.get("top_k") or 3),
        "write_policy": {"path_graph": False, "element_memory": False, "trace": True},
    }
    started = time.perf_counter()
    response = _post_json(f"{base_url.rstrip('/')}/vision/recognition_plan", request_payload, timeout_seconds=timeout_seconds + 15)
    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
    result = ((response.get("data") or {}).get("result") or {}) if isinstance(response, dict) else {}
    vista = (((result.get("parse_result") or {}).get("vista_point_grounding")) or {}) if isinstance(result, dict) else {}
    point = vista.get("point") if isinstance(vista.get("point"), dict) else None
    evaluation = evaluate_point(
        point=point,
        expected_bbox=expected_bbox,
        expected_click_point=expected_click_point,
        allowed_distance_px=allowed_distance_px,
        neighbor_bboxes=neighbors,
    )
    return {
        "case_id": case.get("case_id") or Path(case["image_path"]).stem,
        "category": case.get("category") or "unknown",
        "goal": case["goal"],
        "max_edge": int(max_edge),
        "success": bool(response.get("success")) if isinstance(response, dict) else False,
        "latency_ms": elapsed_ms,
        "processed_size": vista.get("inference_image_size"),
        "processed_point": vista.get("processed_point"),
        "mapped_point_original": point,
        "expected_bbox": expected_bbox,
        "expected_click_point": expected_click_point,
        "gate_allowed": bool(((result.get("pre_click_decision") or {}).get("allowed"))) if isinstance(result, dict) else False,
        "trace_path": result.get("trace_path") if isinstance(result, dict) else None,
        **evaluation,
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_edge: dict[str, list[dict[str, Any]]] = {}
    for item in results:
        by_edge.setdefault(str(item["max_edge"]), []).append(item)
    summary: dict[str, Any] = {"contract_version": "vista_scaling_benchmark_summary_v1", "max_edges": {}}
    for edge, items in by_edge.items():
        latencies = sorted(float(item["latency_ms"]) for item in items)
        pass_count = sum(1 for item in items if item["status"] == "pass")
        risky_count = sum(1 for item in items if item["status"] == "risky")
        fail_count = sum(1 for item in items if item["status"] == "fail")
        summary["max_edges"][edge] = {
            "case_count": len(items),
            "pass_count": pass_count,
            "risky_count": risky_count,
            "fail_count": fail_count,
            "pass_rate": round(pass_count / max(1, len(items)), 4),
            "median_latency_ms": latencies[len(latencies) // 2] if latencies else None,
            "max_latency_ms": latencies[-1] if latencies else None,
        }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark VISTA direct grounding at multiple max_edge settings.")
    parser.add_argument("--cases", required=True, help="JSON/JSONL benchmark cases")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--max-edges", default=",".join(str(item) for item in DEFAULT_MAX_EDGES))
    parser.add_argument("--timeout-seconds", type=float, default=45.0)
    parser.add_argument("--output", help="Optional output JSON path")
    args = parser.parse_args()

    cases = _load_cases(Path(args.cases))
    max_edges = [int(item.strip()) for item in str(args.max_edges).split(",") if item.strip()]
    results: list[dict[str, Any]] = []
    for case in cases:
        for max_edge in max_edges:
            item = run_case(base_url=args.base_url, case=case, max_edge=max_edge, timeout_seconds=args.timeout_seconds)
            results.append(item)
            print(json.dumps(item, ensure_ascii=False))
    payload = {
        "contract_version": "vista_scaling_benchmark_v1",
        "case_count": len(cases),
        "result_count": len(results),
        "results": results,
        "summary": summarize(results),
    }
    if args.output:
        Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
