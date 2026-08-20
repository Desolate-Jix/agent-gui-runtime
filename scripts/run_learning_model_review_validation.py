from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Callable

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_learning_overlay_model_review_probe import run_probe
from scripts.run_learning_review_repair_closure import run_closure
from app.learn.recognition.review_finalization import finalize_reviewed_stage2_for_calibration
from app.learn.recognition.review_adjudication import (
    empty_review_quality_metrics,
    finalize_review_quality_metrics,
    merge_review_quality_metrics,
    score_review_adjudication,
)


ProbeRunner = Callable[..., dict[str, Any]]
ClosureRunner = Callable[..., dict[str, Any]]


def run_validation(
    *,
    manifest_path: Path,
    out_dir: Path,
    probe_runner: ProbeRunner = run_probe,
    closure_runner: ClosureRunner | None = run_closure,
    endpoint: str = "http://127.0.0.1:13240/v1/chat/completions",
    model_name: str = "Qwen3VL-8B-Instruct-Q4_K_M.gguf",
    timeout_seconds: float = 240.0,
) -> dict[str, Any]:
    manifest = _read_json(manifest_path)
    if manifest.get("contract_version") != "learning_model_review_validation_manifest_v1":
        raise ValueError("unsupported validation manifest contract")
    out_dir.mkdir(parents=True, exist_ok=True)
    cases: list[dict[str, Any]] = []
    invalid_cases: list[dict[str, Any]] = []
    summary = {"attempted": 0, "passed": 0, "failed": 0, "invalid": 0, "safe_stop": 0}
    review_quality_metrics = empty_review_quality_metrics()

    for case in manifest.get("cases", []):
        if not isinstance(case, dict):
            continue
        case_id = str(case.get("case_id") or "").strip()
        validity = _validate_case_fixture(case, manifest_path=manifest_path)
        if validity is not None:
            invalid = {"case_id": case_id, **validity}
            invalid_cases.append(invalid)
            cases.append({**invalid, "case_outcome": "invalid"})
            summary["invalid"] += 1
            continue

        summary["attempted"] += 1
        stage2_path = _resolve_path(case["stage2_json_path"], manifest_path)
        screenshot_path = _resolve_path(case["screenshot_path"], manifest_path)
        root_partition_path = _resolve_path(case["root_partition_overlay_path"], manifest_path)
        overlay_path = _resolve_path(case["composite_overlay_path"], manifest_path)
        case_dir = out_dir / case_id
        try:
            probe = probe_runner(
                stage2_json_path=stage2_path,
                out_dir=case_dir / "model_review",
                overlay_path=overlay_path,
                screenshot_path=screenshot_path,
                endpoint=endpoint,
                model_name=model_name,
                timeout_seconds=timeout_seconds,
            )
            if probe.get("actual_model_call") is not True or probe.get("source_type") != "actual_model_call":
                raise _CaseFailure("actual_model_call_missing")
            validated_patch_path = Path(str(probe.get("validated_review_patch_path") or ""))
            if not validated_patch_path.exists():
                raise _CaseFailure("validated_patch_missing")
            validated_patch = _read_json(validated_patch_path)
            if closure_runner is None:
                raise _CaseFailure("closure_runner_missing")
            closure = closure_runner(
                stage2_source_path=stage2_path,
                validated_patch_path=validated_patch_path,
                screenshot_path=str(screenshot_path),
                out_path=case_dir / "repair_closure" / "learning_review_repair_closure_report.json",
            )
            final_path = Path(str(closure.get("final_repaired_overlay_path") or ""))
            before_path = Path(str(probe.get("before_review_overlay_path") or overlay_path))
            required_model_paths = [
                Path(str(probe.get("raw_model_output_path") or "")),
                Path(str(probe.get("prompt_path") or "")),
            ]
            if not final_path.exists() or not before_path.exists() or any(not path.exists() for path in required_model_paths):
                raise _CaseFailure("required_evidence_missing")
            if int(closure.get("deterministic_repair_failed") or 0) > 0:
                raise _CaseFailure("deterministic_repair_failed")

            contact_sheet_path = _build_three_image_contact_sheet(
                original_path=screenshot_path,
                root_partition_path=root_partition_path,
                final_path=final_path,
                out_path=case_dir / "audit_three_image_contact_sheet.png",
            )

            source_report = _read_json(stage2_path)
            source_stage2 = _extract_stage2(source_report)
            final_workflow = closure.get("final_workflow") if isinstance(closure.get("final_workflow"), dict) else {}
            recomposed_stage2 = (
                final_workflow.get("recomposed_stage2")
                if isinstance(final_workflow.get("recomposed_stage2"), dict)
                else {}
            )
            replacement_gate = (
                final_workflow.get("replacement_integrity_gate")
                if isinstance(final_workflow.get("replacement_integrity_gate"), dict)
                else {"passed": False, "failure_categories": ["replacement_integrity_gate_missing"]}
            )
            finalization = finalize_reviewed_stage2_for_calibration(
                source_stage2=source_stage2,
                recomposed_stage2=recomposed_stage2,
                screenshot_path=screenshot_path,
                expected_capture_sha256=str(probe.get("input_capture_sha256") or _sha256(screenshot_path)),
                workflow_state=str(final_workflow.get("workflow_state") or closure.get("workflow_state") or ""),
                replacement_integrity_gate=replacement_gate,
                repair_pending_count=int(final_workflow.get("repair_pending_count") or 0),
            )
            human_adjudication = None
            if case.get("human_adjudication_path"):
                adjudication_path = _resolve_path(case["human_adjudication_path"], manifest_path)
                adjudication = _read_json(adjudication_path)
                human_adjudication = score_review_adjudication(
                    adjudication=adjudication,
                    validated_patch=validated_patch,
                    final_stage2=finalization["finalized_stage2"],
                    integrity_gate=finalization["integrity_gate"],
                )
                human_adjudication["adjudication_path"] = str(adjudication_path.resolve())
                merge_review_quality_metrics(review_quality_metrics, human_adjudication["metrics"])
            final_stage2_report_path = case_dir / "final_stage2_for_calibration.json"
            _write_json(
                final_stage2_report_path,
                {
                    **source_report,
                    "contract_version": "learning_model_review_validation_final_stage2_v1",
                    "stage2_numbering": finalization["finalized_stage2"],
                    "model_review_repair": {
                        "integrity_gate": finalization["integrity_gate"],
                        "calibration_permission": finalization["calibration_permission"],
                        "final_numbering_revision": finalization["final_numbering_revision"],
                    },
                    "display_only": True,
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                },
            )

            completed = (
                closure.get("completed_review_only") is True
                and finalization["calibration_permission"] is True
                and (
                    human_adjudication is None
                    or human_adjudication["quality_gate_passed"] is True
                )
            )
            safe_stop = not completed
            outcome = "passed" if completed else "safe_stop"
            summary["passed" if completed else "safe_stop"] += 1
            case_report = {
                "case_id": case_id,
                "surface_family": case.get("surface_family"),
                "case_outcome": outcome,
                "actual_model_call": True,
                "workflow_state": closure.get("workflow_state"),
                "three_image_evidence": {
                    "original": str(screenshot_path.resolve()),
                    "root_partition": str(root_partition_path.resolve()),
                    "before_review_fusion": str(before_path.resolve()),
                    "final_repaired_fusion": str(final_path.resolve()),
                    "audit_contact_sheet_path": str(contact_sheet_path.resolve()),
                    "complete": True,
                },
                "provenance": {
                    "screenshot_sha256": _sha256(screenshot_path),
                    "stage2_sha256": _sha256(stage2_path),
                    "composite_overlay_sha256": _sha256(overlay_path),
                    "prompt_version": probe.get("prompt_version"),
                    "schema_version": probe.get("schema_version"),
                    "parser_version": probe.get("parser_version"),
                    "model_name": probe.get("model_name") or model_name,
                    "inference_parameters": probe.get("inference_parameters") or {},
                    "source_graph_revision": closure.get("source_graph_revision"),
                    "final_graph_revision": closure.get("final_graph_revision"),
                },
                "model_review_report_path": probe.get("report_path"),
                "repair_closure_report_path": closure.get("report_path"),
                "finalization": {
                    "calibration_permission": finalization["calibration_permission"],
                    "integrity_gate": finalization["integrity_gate"],
                    "final_numbering_revision": finalization["final_numbering_revision"],
                    "final_stage2_report_path": str(final_stage2_report_path.resolve()),
                },
                "safe_stop": safe_stop,
            }
            if human_adjudication is not None:
                case_report["human_adjudication"] = human_adjudication
        except _CaseFailure as exc:
            summary["failed"] += 1
            case_report = {
                "case_id": case_id,
                "surface_family": case.get("surface_family"),
                "case_outcome": "failed",
                "failure_category": exc.category,
                "actual_model_call": False if exc.category == "actual_model_call_missing" else None,
            }
        except (OSError, TimeoutError, ValueError) as exc:
            summary["failed"] += 1
            case_report = {
                "case_id": case_id,
                "surface_family": case.get("surface_family"),
                "case_outcome": "failed",
                "failure_category": "model_review_protocol_failure",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        cases.append(case_report)

    attempted = summary["attempted"]
    model_passed = sum(item.get("actual_model_call") is True for item in cases)
    finalize_review_quality_metrics(review_quality_metrics)
    report = {
        "contract_version": "learning_model_review_development_validation_report_v1",
        "manifest_path": str(manifest_path.resolve()),
        "suite_id": manifest.get("suite_id"),
        "suite_type": manifest.get("suite_type"),
        "used_for_tuning": manifest.get("used_for_tuning") is True,
        "summary": summary,
        "model_review_coverage": {
            "passed": model_passed,
            "attempted": attempted,
            "rate": round(model_passed / attempted, 4) if attempted else "not_covered",
        },
        "review_quality_metrics": review_quality_metrics,
        "cases": cases,
        "invalid_cases": invalid_cases,
        "safety": {"real_clicks": 0, "live_fills": 0, "live_submits": 0},
        "interpretation": (
            "Actual-model development validation of review and deterministic repair; "
            "not recognition accuracy, Execute authorization, or runtime PathGraph readiness."
        ),
    }
    report_path = out_dir / "learning_model_review_validation_report.json"
    report["report_path"] = str(report_path.resolve())
    _write_json(report_path, report)
    return report


class _CaseFailure(RuntimeError):
    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


def _validate_case_fixture(case: dict[str, Any], *, manifest_path: Path) -> dict[str, Any] | None:
    checks = [
        ("stage2", "stage2_json_path", "stage2_sha256"),
        ("screenshot", "screenshot_path", "screenshot_sha256"),
        ("root_partition_overlay", "root_partition_overlay_path", "root_partition_overlay_sha256"),
        ("composite_overlay", "composite_overlay_path", "composite_overlay_sha256"),
    ]
    if case.get("human_adjudication_path"):
        checks.append(
            (
                "human_adjudication",
                "human_adjudication_path",
                "human_adjudication_sha256",
            )
        )
    for fixture_type, path_key, checksum_key in checks:
        path = _resolve_path(case.get(path_key), manifest_path)
        if not path.exists():
            return {
                "failure_category": "fixture_missing",
                "fixture_type": fixture_type,
                "fixture_path": str(path),
            }
        expected = str(case.get(checksum_key) or "").lower()
        actual = _sha256(path)
        if expected != actual:
            return {
                "failure_category": "stale_fixture",
                "fixture_type": fixture_type,
                "fixture_path": str(path),
                "expected_checksum": expected,
                "actual_checksum": actual,
            }
    return None


def _resolve_path(value: Any, manifest_path: Path) -> Path:
    path = Path(str(value or ""))
    if path.is_absolute():
        return path.resolve()
    root_candidate = (ROOT / path).resolve()
    if root_candidate.exists():
        return root_candidate
    return (manifest_path.parent / path).resolve()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build_three_image_contact_sheet(
    *,
    original_path: Path,
    root_partition_path: Path,
    final_path: Path,
    out_path: Path,
) -> Path:
    entries = (
        ("ORIGINAL", original_path),
        ("STAGE1 ROOT PARTITION", root_partition_path),
        ("AFTER REVIEW + REPAIR", final_path),
    )
    images: list[tuple[str, Image.Image]] = []
    for label, path in entries:
        with Image.open(path) as source:
            images.append((label, source.convert("RGB")))

    header_height = 42
    gap = 12
    width = sum(image.width for _, image in images) + gap * (len(images) - 1)
    height = header_height + max(image.height for _, image in images)
    sheet = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(sheet)
    x = 0
    for label, image in images:
        draw.text((x + 8, 12), label, fill="black")
        sheet.paste(image, (x, header_height))
        x += image.width + gap

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    return out_path


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _extract_stage2(source: dict[str, Any]) -> dict[str, Any]:
    two_stage = source.get("two_stage_understanding")
    if isinstance(two_stage, dict) and isinstance(two_stage.get("stage2_numbering"), dict):
        return two_stage["stage2_numbering"]
    if isinstance(source.get("stage2_numbering"), dict):
        return source["stage2_numbering"]
    if isinstance(source.get("regions"), list):
        return source
    raise ValueError("validation case does not contain stage2_numbering")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run actual-model Learning overlay review validation.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--endpoint", default="http://127.0.0.1:13240/v1/chat/completions")
    parser.add_argument("--model-name", default="Qwen3VL-8B-Instruct-Q4_K_M.gguf")
    parser.add_argument("--timeout-seconds", type=float, default=240.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = run_validation(
        manifest_path=args.manifest,
        out_dir=args.out,
        endpoint=args.endpoint,
        model_name=args.model_name,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else report["report_path"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
