from __future__ import annotations

import argparse
import gc
from hashlib import sha256
import json
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import time
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.learn.recognition.omniparser_provider import (
    OmniparserProviderError,
    build_failed_screen_parser_result,
    normalize_omniparser_result,
    sha256_file,
)

PROFILE_PATH = ROOT / "configs" / "model_profiles" / "learn_mode_omniparser_v2.json"
MINIMUM_FREE_GPU_BYTES = 8 * 1024**3
MODEL_HUB_REVISION = "6600256cb0f1b07651e3bc86166196307bad7e2d"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the official OmniParser v2.0.1 learn-only smoke on a static image.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--warm-repetitions", type=int, default=3)
    return parser.parse_args()


def _load_profile() -> dict[str, Any]:
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


def _gpu_snapshot() -> dict[str, Any]:
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.free,memory.used",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        return {"available": False, "reason": "nvidia_smi_unavailable"}
    except subprocess.CalledProcessError as exc:
        return {"available": False, "reason": "nvidia_smi_failed", "details": exc.stderr.strip()}
    except subprocess.TimeoutExpired:
        return {"available": False, "reason": "nvidia_smi_timeout"}
    first_line = next((line.strip() for line in completed.stdout.splitlines() if line.strip()), "")
    parts = [part.strip() for part in first_line.split(",")]
    if len(parts) != 4:
        return {"available": False, "reason": "nvidia_smi_unparseable", "details": first_line}
    try:
        total_mib, free_mib, used_mib = (int(parts[index]) for index in (1, 2, 3))
    except ValueError:
        return {"available": False, "reason": "nvidia_smi_unparseable", "details": first_line}
    return {
        "available": True,
        "name": parts[0],
        "total_bytes": total_mib * 1024**2,
        "free_bytes": free_mib * 1024**2,
        "used_bytes": used_mib * 1024**2,
    }


def _resident_compute_models() -> list[dict[str, Any]]:
    try:
        import psutil
    except ImportError:
        return []
    current_pid = __import__("os").getpid()
    blocked: list[dict[str, Any]] = []
    needles = ("qwen", "vista", "llama-server", "llama_server", "vllm", "ollama")
    for process in psutil.process_iter(["pid", "name", "cmdline"]):
        info = process.info
        if info.get("pid") == current_pid:
            continue
        command_line = " ".join(str(value) for value in (info.get("cmdline") or []))
        haystack = f"{info.get('name') or ''} {command_line}".casefold()
        if any(needle in haystack for needle in needles):
            blocked.append({"pid": info.get("pid"), "name": info.get("name"), "command_line": command_line})
    return blocked


def _file_hashes(weights_path: Path) -> dict[str, str]:
    required = (
        weights_path / "icon_detect" / "train_args.yaml",
        weights_path / "icon_detect" / "model.pt",
        weights_path / "icon_detect" / "model.yaml",
        weights_path / "icon_caption_florence" / "config.json",
        weights_path / "icon_caption_florence" / "generation_config.json",
        weights_path / "icon_caption_florence" / "model.safetensors",
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise OmniparserProviderError("weights_missing", "Missing official required weight files: " + ", ".join(missing))
    return {str(path.relative_to(weights_path)).replace("\\", "/"): sha256_file(path) for path in required}


def _git_revision(code_path: Path) -> str:
    completed = subprocess.run(["git", "-C", str(code_path), "rev-parse", "HEAD"], check=True, capture_output=True, text=True, timeout=10)
    return completed.stdout.strip()


def _image_size(image_path: Path) -> dict[str, int]:
    from PIL import Image

    with Image.open(image_path) as image:
        return {"width": int(image.width), "height": int(image.height)}


def _preflight(*, code_path: Path, weights_path: Path) -> dict[str, Any]:
    disk = shutil.disk_usage(ROOT)
    gpu = _gpu_snapshot()
    resident = _resident_compute_models()
    if not code_path.is_dir():
        raise OmniparserProviderError("provider_unavailable", f"Official code directory is missing: {code_path}")
    revision = _git_revision(code_path)
    if revision != "b0d5c9f5701f7e2be4771872e6e928da77759df3":
        raise OmniparserProviderError("provider_unavailable", f"Official code revision is not v.2.0.1: {revision}")
    if not gpu.get("available"):
        raise OmniparserProviderError("runtime_preflight", f"GPU probe failed: {gpu.get('reason')}")
    if int(gpu["free_bytes"]) < MINIMUM_FREE_GPU_BYTES:
        raise OmniparserProviderError("runtime_preflight", "GPU free memory is below the required 8 GiB")
    if resident:
        raise OmniparserProviderError("runtime_preflight", "Another compute model is resident: " + json.dumps(resident, ensure_ascii=True))
    return {
        "disk_free_bytes": int(disk.free),
        "gpu_before": gpu,
        "resident_compute_models": resident,
        "code_revision": revision,
        "weight_hashes": _file_hashes(weights_path),
    }


def _load_official_models(code_path: Path, weights_path: Path) -> tuple[Any, Any, Any, Any]:
    if str(code_path) not in sys.path:
        sys.path.insert(0, str(code_path))
    try:
        from util.utils import check_ocr_box, get_caption_model_processor, get_som_labeled_img, get_yolo_model
    except ImportError as exc:
        raise OmniparserProviderError("dependency_missing", f"Official OmniParser dependencies could not be imported: {exc}") from exc
    detector = get_yolo_model(str(weights_path / "icon_detect" / "model.pt"))
    caption = get_caption_model_processor("florence2", model_name_or_path=str(weights_path / "icon_caption_florence"))
    return detector, caption, check_ocr_box, get_som_labeled_img


def _run_once(*, input_path: Path, detector: Any, caption: Any, check_ocr_box: Any, get_som_labeled_img: Any) -> tuple[list[dict[str, Any]], float]:
    started = time.perf_counter()
    (texts, ocr_boxes), _ = check_ocr_box(
        str(input_path),
        display_img=False,
        output_bb_format="xyxy",
        goal_filtering=None,
        easyocr_args={"paragraph": False, "text_threshold": 0.9},
        use_paddleocr=False,
    )
    _, _, parsed_content_list = get_som_labeled_img(
        str(input_path),
        detector,
        BOX_TRESHOLD=0.01,
        output_coord_in_ratio=True,
        ocr_bbox=ocr_boxes,
        caption_model_processor=caption,
        ocr_text=texts,
        iou_threshold=0.9,
        imgsz=None,
        batch_size=32,
    )
    return parsed_content_list, (time.perf_counter() - started) * 1000


def _invalid_bbox_count(parsed_content_list: list[dict[str, Any]]) -> int:
    invalid = 0
    for item in parsed_content_list:
        bbox = item.get("bbox") if isinstance(item, dict) else None
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            invalid += 1
            continue
        try:
            x1, y1, x2, y2 = (float(value) for value in bbox)
        except (TypeError, ValueError):
            invalid += 1
            continue
        if not (0.0 <= x1 < x2 <= 1.0 and 0.0 <= y1 < y2 <= 1.0):
            invalid += 1
    return invalid


def _resource_usage(*, before: dict[str, Any], peak_bytes: int | None = None) -> dict[str, Any]:
    after = _gpu_snapshot()
    return {
        "gpu_available": bool(before.get("available")),
        "gpu_before": before,
        "gpu_peak_allocated_bytes": peak_bytes,
        "gpu_after": after,
    }


def _artifact_output_path(input_path: Path, supplied: Path | None) -> Path:
    if supplied is not None:
        return supplied
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return ROOT / "artifacts" / "omniparser-smoke" / f"{input_path.stem}-{stamp}.json"


def _write_artifact(path: Path, artifact: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = _parse_args()
    input_path = args.input.resolve()
    output_path = _artifact_output_path(input_path, args.output)
    profile = _load_profile()
    code_path = ROOT / profile["expected_paths"]["code_path"]
    weights_path = ROOT / profile["expected_paths"]["weights_path"]
    source_run_id = f"omniparser-smoke-{uuid4()}"
    image_size = _image_size(input_path)
    screenshot_sha = sha256_file(input_path)
    common = {
        "profile_id": profile["profile_id"],
        "model_revision": f"{profile['official_code']['tag']}@{profile['official_code']['commit']}",
        "capture_id": f"static-contact-sheet-{screenshot_sha[:16]}",
        "source_run_id": source_run_id,
        "screenshot_sha256": screenshot_sha,
        "image_size": image_size,
        "coordinate_space": "image_normalized_xyxy",
    }
    try:
        preflight = _preflight(code_path=code_path, weights_path=weights_path)
        detector, caption, check_ocr_box, get_som_labeled_img = _load_official_models(code_path, weights_path)
        import torch

        torch.cuda.reset_peak_memory_stats()
        cold_items, cold_ms = _run_once(
            input_path=input_path,
            detector=detector,
            caption=caption,
            check_ocr_box=check_ocr_box,
            get_som_labeled_img=get_som_labeled_img,
        )
        invalid_bbox_count = _invalid_bbox_count(cold_items)
        if invalid_bbox_count:
            raise OmniparserProviderError("invalid_bbox", f"Official output contained {invalid_bbox_count} invalid bbox(es)")
        warm_ms: list[float] = []
        for _ in range(max(0, args.warm_repetitions)):
            _, elapsed_ms = _run_once(
                input_path=input_path,
                detector=detector,
                caption=caption,
                check_ocr_box=check_ocr_box,
                get_som_labeled_img=get_som_labeled_img,
            )
            warm_ms.append(elapsed_ms)
        peak_bytes = int(torch.cuda.max_memory_allocated()) if torch.cuda.is_available() else None
        resource_usage = _resource_usage(before=preflight["gpu_before"], peak_bytes=peak_bytes)
        timing = {
            "cold_inference_ms": cold_ms,
            "warm_inference_ms": warm_ms,
            "warm_p50_ms": statistics.median(warm_ms) if warm_ms else None,
            "warm_p95_ms": _p95(warm_ms),
        }
        artifact = normalize_omniparser_result(
            parsed_content_list=cold_items,
            timing=timing,
            resource_usage=resource_usage,
            provenance={
                "official_repo": "microsoft/OmniParser",
                "code_tag": profile["official_code"]["tag"],
                "code_revision": preflight["code_revision"],
                "model_hub_repo": "microsoft/OmniParser-v2.0",
                "model_hub_revision": MODEL_HUB_REVISION,
                "weight_hashes": preflight["weight_hashes"],
                "input_path": str(input_path),
                "static_contact_sheet_only": True,
                "licenses": {"official_code": "MIT", "icon_detect": "AGPL-3.0", "icon_caption_florence": "MIT"},
            },
            **common,
        )
        from app.learn.recognition.parsers import parse_existing_evidence_to_inventory

        inventory = parse_existing_evidence_to_inventory(
            {
                "capture_id": artifact["capture_id"],
                "screenshot_sha256": artifact["screenshot_sha256"],
                "image_size": artifact["image_size"],
                "sources": {"omniparser": artifact},
            }
        )
        artifact["smoke_metrics"] = {
            "element_count": len(artifact["elements"]),
            "interactive_count": sum(1 for element in artifact["elements"] if element["interactivity"]),
            "invalid_bbox_count": invalid_bbox_count,
            "inventory_count": len(inventory),
            "inventory_non_authorizing": all(item["click_candidate"] is False for item in inventory),
            "input_is_static_contact_sheet": True,
        }
    except OmniparserProviderError as exc:
        artifact = build_failed_screen_parser_result(
            error_code=exc.code,
            error_details=exc.details,
            stage="smoke_runner",
            timing={},
            resource_usage={"gpu_after": _gpu_snapshot()},
            provenance={"input_path": str(input_path), "static_contact_sheet_only": True},
            **common,
        )
    except FileNotFoundError as exc:
        artifact = build_failed_screen_parser_result(
            error_code="dependency_missing",
            error_details=str(exc),
            stage="smoke_runner",
            timing={},
            resource_usage={"gpu_after": _gpu_snapshot()},
            provenance={"input_path": str(input_path), "static_contact_sheet_only": True},
            **common,
        )
    except (RuntimeError, ValueError) as exc:
        code = "cuda_oom" if "out of memory" in str(exc).casefold() else "inference_failed"
        artifact = build_failed_screen_parser_result(
            error_code=code,
            error_details=str(exc),
            stage="official_inference",
            timing={},
            resource_usage={"gpu_after": _gpu_snapshot()},
            provenance={"input_path": str(input_path), "static_contact_sheet_only": True},
            **common,
        )
    finally:
        if "detector" in locals():
            del detector
        if "caption" in locals():
            del caption
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
    artifact["resource_usage"]["gpu_post_cleanup"] = _gpu_snapshot()
    _write_artifact(output_path, artifact)
    print(json.dumps({"status": artifact["status"], "output": str(output_path), "source_run_id": source_run_id}, ensure_ascii=True))
    return 0 if artifact["status"] == "success" else 2


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1)))))
    return ordered[index]


if __name__ == "__main__":
    raise SystemExit(main())
