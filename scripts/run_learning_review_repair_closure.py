from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.learn.recognition.repair_executor import execute_deterministic_repairs
from app.learn.recognition.model_review import render_review_overlays
from app.learn.recognition.review_workflow import run_review_repair_workflow


def run_closure(
    *,
    stage2_source_path: Path,
    validated_patch_path: Path,
    screenshot_path: str,
    out_path: Path,
) -> dict[str, Any]:
    source = _read_json(stage2_source_path)
    stage2 = _extract_stage2(source)
    patch = _read_json(validated_patch_path)
    pending = run_review_repair_workflow(
        stage2=stage2,
        validated_patch=patch,
        screenshot_path=screenshot_path,
    )
    repair_results = execute_deterministic_repairs(stage2, pending["generic_repair_requests"])
    final = run_review_repair_workflow(
        stage2=stage2,
        validated_patch=patch,
        screenshot_path=screenshot_path,
        repair_results=repair_results,
    )
    final_overlay_dir = out_path.parent / "final_repaired_overlay"
    final_overlay_outputs = render_review_overlays(
        screenshot_path=screenshot_path,
        before_stage2=stage2,
        after_stage2=final["recomposed_stage2"],
        validated_patch={"remove": [], "relabel": [], "missing": []},
        out_dir=final_overlay_dir,
    )
    source_graph_revision = _graph_revision(stage2)
    final_graph_revision = _graph_revision(final["recomposed_stage2"])
    report = {
        "contract_version": "learning_review_repair_closure_report_v1",
        "stage2_source_path": str(stage2_source_path),
        "validated_patch_path": str(validated_patch_path),
        "screenshot_path": screenshot_path,
        "workflow_state": final["workflow_state"],
        "completed_review_only": final["completed_review_only"],
        "generic_repair_request_count": pending["generic_repair_requests"]["request_count"],
        "deterministic_repair_passed": sum(
            item.get("status") == "passed" for item in repair_results["results"]
        ),
        "deterministic_repair_failed": sum(
            item.get("status") != "passed" for item in repair_results["results"]
        ),
        "generic_repair_requests": pending["generic_repair_requests"],
        "repair_results": repair_results,
        "final_workflow": final,
        "source_graph_revision": source_graph_revision,
        "final_graph_revision": final_graph_revision,
        "final_repaired_overlay_path": final_overlay_outputs["reviewed_overlay_path"],
        "three_image_evidence": {
            "original": str(Path(screenshot_path).resolve()),
            "final_repaired_fusion": final_overlay_outputs["reviewed_overlay_path"],
        },
        "safety": {
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "real_clicks": 0,
            "live_fills": 0,
            "live_submits": 0,
        },
        "interpretation": (
            "Deterministic repair closure over a validated review patch; "
            "not model-review quality, recognition accuracy, or runtime authorization."
        ),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["report_path"] = str(out_path)
    return report


def _graph_revision(stage2: dict[str, Any]) -> str:
    canonical = json.dumps(stage2, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _extract_stage2(source: dict[str, Any]) -> dict[str, Any]:
    candidates = [
        source,
        source.get("stage2_numbering"),
        (source.get("two_stage_understanding") or {}).get("stage2_numbering")
        if isinstance(source.get("two_stage_understanding"), dict)
        else None,
    ]
    for candidate in candidates:
        if isinstance(candidate, dict) and isinstance(candidate.get("regions"), list):
            return candidate
    raise ValueError("stage2 source does not contain a stage2_numbering object")


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _configure_stdout_utf8(stream: Any) -> None:
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")


def main() -> int:
    _configure_stdout_utf8(sys.stdout)
    parser = argparse.ArgumentParser(description="Close a validated learning review patch with deterministic evidence.")
    parser.add_argument("--stage2-source", required=True)
    parser.add_argument("--validated-patch", required=True)
    parser.add_argument("--screenshot", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = run_closure(
        stage2_source_path=Path(args.stage2_source),
        validated_patch_path=Path(args.validated_patch),
        screenshot_path=args.screenshot,
        out_path=Path(args.out),
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        print(f"report_path={report['report_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
