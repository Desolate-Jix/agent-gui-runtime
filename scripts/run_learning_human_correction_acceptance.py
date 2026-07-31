from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from app.main import app


def bounded_bbox_adjustment(bbox: dict[str, Any], *, image_size: dict[str, int]) -> dict[str, int]:
    """生成一个可审计且不越界的最小人工几何修正。"""
    width = max(1, int(image_size.get("width") or 0))
    height = max(1, int(image_size.get("height") or 0))
    x = max(0, int(bbox.get("x") or 0))
    y = max(0, int(bbox.get("y") or 0))
    w = max(1, int(bbox.get("w") or 0))
    h = max(1, int(bbox.get("h") or 0))
    if w > 4 and h > 4:
        adjusted = {"x": x + 1, "y": y + 1, "w": w - 2, "h": h - 2}
    elif w > 1:
        adjusted = {"x": x, "y": y, "w": w - 1, "h": h}
    elif h > 1:
        adjusted = {"x": x, "y": y, "w": w, "h": h - 1}
    else:
        raise ValueError("selected region is too small for a bounded acceptance edit")
    adjusted["x"] = min(adjusted["x"], width - 1)
    adjusted["y"] = min(adjusted["y"], height - 1)
    adjusted["w"] = min(adjusted["w"], width - adjusted["x"])
    adjusted["h"] = min(adjusted["h"], height - adjusted["y"])
    if adjusted["w"] <= 0 or adjusted["h"] <= 0:
        raise ValueError("bounded acceptance edit produced an empty bbox")
    return adjusted


def audit_human_correction_acceptance(
    *,
    source_image_path: Path,
    reviewed_overlay_path: Path,
    target_region_id: str,
    expected_bbox: dict[str, int],
    save_result: dict[str, Any],
    reloaded_review: dict[str, Any],
) -> dict[str, Any]:
    regions = (reloaded_review.get("draft") or {}).get("regions") or []
    reloaded_region = next(
        (
            item
            for item in regions
            if isinstance(item, dict) and str(item.get("region_id") or "") == target_region_id
        ),
        {},
    )
    actual_bbox = reloaded_region.get("bbox") if isinstance(reloaded_region.get("bbox"), dict) else {}
    source_size = _image_size(source_image_path)
    overlay_size = _image_size(reviewed_overlay_path)
    correction_memory = (
        save_result.get("correction_memory") if isinstance(save_result.get("correction_memory"), dict) else {}
    )
    checks = {
        "reloaded_bbox_matches": actual_bbox == expected_bbox,
        "overlay_same_size_as_source": source_size == overlay_size,
        "reviewed_overlay_exists": reviewed_overlay_path.exists(),
        "reviewed_candidate_written": bool(save_result.get("reviewed_template_candidate_path")),
        "readonly_pathgraph_candidate_written": bool(save_result.get("pathgraph_candidate_path")),
        "human_patch_versioned": int(save_result.get("human_review_patch_revision") or 0) >= 1,
        "correction_memory_candidate_only": (
            correction_memory.get("status") == "candidate"
            and correction_memory.get("production_eligible") is False
        ),
        "read_only_safety_preserved": (
            save_result.get("execute_binding_enabled") is False
            and save_result.get("artifact_is_authorization") is False
            and reloaded_review.get("execute_binding_enabled") is False
            and reloaded_review.get("artifact_is_authorization") is False
            and reloaded_review.get("final_submit_forbidden") is True
        ),
        "pathgraph_review_reloadable": isinstance(reloaded_review.get("pathgraph_candidate_review"), dict),
    }
    failure_names = {
        "reloaded_bbox_matches": "reloaded_bbox_mismatch",
        "overlay_same_size_as_source": "overlay_size_mismatch",
        "reviewed_overlay_exists": "reviewed_overlay_missing",
        "reviewed_candidate_written": "reviewed_candidate_missing",
        "readonly_pathgraph_candidate_written": "pathgraph_candidate_missing",
        "human_patch_versioned": "human_patch_revision_missing",
        "correction_memory_candidate_only": "correction_memory_not_candidate_only",
        "read_only_safety_preserved": "read_only_safety_failed",
        "pathgraph_review_reloadable": "pathgraph_review_reload_failed",
    }
    failures = [failure_names[name] for name, passed in checks.items() if not passed]
    return {
        "contract_version": "learning_human_correction_acceptance_audit_v1",
        "status": "passed" if not failures else "failed",
        "target_region_id": target_region_id,
        "expected_bbox": expected_bbox,
        "actual_bbox": actual_bbox,
        "source_image_size": source_size,
        "reviewed_overlay_size": overlay_size,
        "checks": checks,
        "failure_categories": failures,
        "interpretation": "Human-correction replay and read-only artifact audit; not recognition accuracy.",
    }


def run_human_correction_acceptance(
    *,
    source_path: str,
    out_dir: Path,
    target_region_id: str = "",
    client: TestClient | None = None,
) -> dict[str, Any]:
    client = client or TestClient(app)
    before_response = _post(client, "/panel/load_learning_draft_review", {"source_path": source_path})
    before = before_response["data"]
    draft = before.get("draft") if isinstance(before.get("draft"), dict) else {}
    screen = (draft.get("page_details") or {}).get("screen") or {}
    source_image_value = str(screen.get("source_image_path") or screen.get("image_path") or "").strip()
    source_image = _resolve_path(source_image_value)
    source_sha256 = str(screen.get("source_image_sha256") or "").strip().lower()
    actual_sha256 = hashlib.sha256(source_image.read_bytes()).hexdigest()
    if not source_sha256 or source_sha256 != actual_sha256:
        raise ValueError("learning draft source screenshot checksum is missing or stale")

    regions = [item for item in draft.get("regions") or [] if isinstance(item, dict)]
    selected = next(
        (item for item in regions if str(item.get("region_id") or "") == target_region_id),
        None,
    )
    if selected is None:
        selected = next((item for item in regions if isinstance(item.get("bbox"), dict)), None)
    if selected is None:
        raise ValueError("learning draft has no editable bbox region")
    region_id = str(selected.get("region_id") or "").strip()
    before_bbox = {key: int((selected.get("bbox") or {}).get(key) or 0) for key in ("x", "y", "w", "h")}
    image_size = _image_size(source_image)
    after_bbox = bounded_bbox_adjustment(before_bbox, image_size=image_size)
    patch = {
        "contract_version": "human_review_patch_v1",
        "screenshot_path": _relative_path(source_image),
        "screenshot_sha256": actual_sha256,
        "reason": "Task 7 acceptance replay: bounded human bbox correction",
        "source": "human_panel_editor_v1",
        "operations": [
            {
                "op": "update_bbox",
                "target_kind": "region",
                "target_id": region_id,
                "before_bbox": before_bbox,
                "after_bbox": after_bbox,
            }
        ],
    }
    save_response = _post(
        client,
        "/panel/save_learning_draft_review",
        {"source_path": source_path, "review_patch": patch},
    )
    save_result = save_response["data"]
    reload_path = str(
        save_result.get("pathgraph_candidate_path")
        or save_result.get("reviewed_template_candidate_path")
        or ""
    ).strip()
    if not reload_path:
        raise ValueError("panel save did not return a reloadable candidate path")
    reloaded_response = _post(client, "/panel/load_learning_draft_review", {"source_path": reload_path})
    reloaded = reloaded_response["data"]
    overlay = _resolve_path(str(save_result.get("reviewed_overlay_path") or ""))
    audit = audit_human_correction_acceptance(
        source_image_path=source_image,
        reviewed_overlay_path=overlay,
        target_region_id=region_id,
        expected_bbox=after_bbox,
        save_result=save_result,
        reloaded_review=reloaded,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "learning_human_correction_acceptance_report.json"
    report = {
        "contract_version": "learning_human_correction_acceptance_report_v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "status": audit["status"],
        "source_path": source_path,
        "source_image_path": _relative_path(source_image),
        "source_image_sha256": actual_sha256,
        "target_region_id": region_id,
        "before_bbox": before_bbox,
        "after_bbox": after_bbox,
        "human_review_patch_path": save_result.get("human_review_patch_path"),
        "reviewed_overlay_path": save_result.get("reviewed_overlay_path"),
        "reviewed_template_candidate_path": save_result.get("reviewed_template_candidate_path"),
        "pathgraph_candidate_path": save_result.get("pathgraph_candidate_path"),
        "correction_memory": save_result.get("correction_memory"),
        "load_trace_path": before.get("trace_path"),
        "save_trace_path": save_result.get("trace_path"),
        "reload_trace_path": reloaded.get("trace_path"),
        "audit": audit,
        "safety": {
            "live_clicks": 0,
            "live_fills": 0,
            "live_submits": 0,
            "execute_binding_enabled": False,
            "runtime_pathgraph_promotion": False,
        },
        "interpretation": "Panel API human-correction replay only; no model call and no GUI action authorization.",
    }
    report["report_path"] = str(report_path)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _post(client: TestClient, route: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = client.post(route, json=payload).json()
    if response.get("success") is not True or not isinstance(response.get("data"), dict):
        error = response.get("error") if isinstance(response.get("error"), dict) else {}
        raise RuntimeError(f"{route} failed: {error.get('details') or response.get('message')}")
    return response


def _resolve_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(str(path))
    return path


def _relative_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _image_size(path: Path) -> dict[str, int]:
    with Image.open(path) as image:
        return {"width": int(image.width), "height": int(image.height)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one read-only panel human-correction acceptance replay.")
    parser.add_argument(
        "--source",
        default="logs/benchmarks/learn_three_interface_scaffold_20260711/applemusic/learn_mode_demo_scaffold.json",
    )
    parser.add_argument("--region-id", default="")
    parser.add_argument("--out", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = run_human_correction_acceptance(
        source_path=str(args.source),
        out_dir=Path(args.out),
        target_region_id=str(args.region_id or ""),
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"status={report['status']}")
        print(f"report_path={report['report_path']}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
