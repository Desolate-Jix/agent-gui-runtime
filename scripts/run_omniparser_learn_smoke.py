from __future__ import annotations

import argparse
import gc
import json
import math
import os
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
FLORENCE_PROCESSOR_REPOSITORY = "microsoft/Florence-2-base"
FLORENCE_PROCESSOR_REVISION = "5ca5edf5bd017b9919c05d08aebef5e4c7ac3bac"
FLORENCE_MODEL_REPOSITORY = "microsoft/Florence-2-base-ft"
FLORENCE_MODEL_REVISION = "f6c1a25888ffc1d945ee8a1a77ac833c7303d46e"
EXPECTED_WEIGHT_HASHES = {
    "icon_detect/train_args.yaml": "6acc8dcdc8a38ccfafc47ccfdb0087b8545eab6f9d9a373c0504bbb5a45a0277",
    "icon_detect/model.pt": "dab3d4351ad00b035db829909a4db98354d5a90f6990e4ac00222a9a95d4bf57",
    "icon_detect/model.yaml": "0edced8dfb9c619ca187cf0f84139d63b4cff9011890a9bc1e9bd6bb08f43b8a",
    "icon_caption_florence/config.json": "1c3c63bb16910b8fa7f3b74fb7ae4c8ffefbe7b008847e2e0b21be6aa807593b",
    "icon_caption_florence/generation_config.json": "a2ef03e814a7ecbf6fcfe7479afd3e7385c6800202fcede1dc1bc01849375464",
    "icon_caption_florence/model.safetensors": "01b934b0fe2d07b181e2d07752f16ae27c9d0ea88ddffe13a9a003aa9680f233",
}
_AUTO = object()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run official OmniParser v2.0.1 learn-only static-image smoke inference.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--warm-repetitions", type=int, default=3)
    return parser.parse_args()


def _load_profile() -> dict[str, Any]:
    try:
        return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OmniparserProviderError("provider_unavailable", f"Model profile could not be read: {exc}") from exc


def _gpu_snapshot() -> dict[str, Any]:
    try:
        completed = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.free,memory.used", "--format=csv,noheader,nounits"],
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


def _resident_compute_models(*, psutil_module: Any = _AUTO, current_pid: int | None = None) -> list[dict[str, Any]]:
    if psutil_module is _AUTO:
        try:
            import psutil as psutil_module
        except ImportError as exc:
            raise OmniparserProviderError("dependency_missing", "psutil is required for compute-model residency preflight") from exc
    if psutil_module is None:
        raise OmniparserProviderError("dependency_missing", "psutil is required for compute-model residency preflight")
    own_pid = os.getpid() if current_pid is None else current_pid
    blocked: list[dict[str, Any]] = []
    needles = ("qwen", "vista", "llama-server", "llama_server", "vllm", "ollama")
    try:
        processes = psutil_module.process_iter(["pid", "name", "cmdline"])
        for process in processes:
            info = process.info
            if info.get("pid") == own_pid:
                continue
            command_line = " ".join(str(value) for value in (info.get("cmdline") or []))
            haystack = f"{info.get('name') or ''} {command_line}".casefold()
            if any(needle in haystack for needle in needles):
                blocked.append({"pid": info.get("pid"), "name": info.get("name"), "command_line": command_line})
    except (OSError, RuntimeError, AttributeError, getattr(psutil_module, "Error", OSError)) as exc:
        raise OmniparserProviderError("runtime_preflight", f"Process residency inspection failed: {exc}") from exc
    return blocked


def _verify_weight_manifest(weights_path: Path, manifest: dict[str, str] = EXPECTED_WEIGHT_HASHES) -> dict[str, str]:
    missing = [str(weights_path / relative_path) for relative_path in manifest if not (weights_path / relative_path).is_file()]
    if missing:
        raise OmniparserProviderError("weights_missing", "Missing official required weight files: " + ", ".join(missing))
    actual = {relative_path: sha256_file(weights_path / relative_path) for relative_path in manifest}
    mismatches = [relative_path for relative_path, expected in manifest.items() if actual[relative_path] != expected]
    if mismatches:
        raise OmniparserProviderError("weights_hash_mismatch", "Official weight hash mismatch: " + ", ".join(mismatches))
    return actual


def _snapshot_path(hub_cache: Path, repository: str, revision: str) -> Path:
    return hub_cache / ("models--" + repository.replace("/", "--")) / "snapshots" / revision


def _require_florence_offline_assets(hub_cache: Path) -> dict[str, Any]:
    requirements = {
        FLORENCE_PROCESSOR_REPOSITORY: (FLORENCE_PROCESSOR_REVISION, ("config.json", "preprocessor_config.json", "tokenizer.json", "configuration_florence2.py", "processing_florence2.py")),
        FLORENCE_MODEL_REPOSITORY: (FLORENCE_MODEL_REVISION, ("configuration_florence2.py", "modeling_florence2.py")),
    }
    resolved: dict[str, Any] = {}
    missing: list[str] = []
    for repository, (revision, files) in requirements.items():
        snapshot = _snapshot_path(hub_cache, repository, revision)
        absent = [name for name in files if not (snapshot / name).is_file()]
        if absent:
            missing.append(f"{repository}@{revision}: {', '.join(absent)}")
        else:
            resolved[repository] = {"revision": revision, "snapshot_path": str(snapshot), "files": list(files)}
    if missing:
        raise OmniparserProviderError("dependency_missing", "Pinned Florence offline assets are missing: " + "; ".join(missing))
    return resolved


def _git_revision(code_path: Path) -> str:
    try:
        completed = subprocess.run(["git", "-C", str(code_path), "rev-parse", "HEAD"], check=True, capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise OmniparserProviderError("provider_unavailable", f"Official code revision probe failed: {exc}") from exc
    revision = completed.stdout.strip()
    if not revision:
        raise OmniparserProviderError("provider_unavailable", "Official code revision probe returned no commit")
    return revision


def _image_size(image_path: Path) -> dict[str, int]:
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError as exc:
        raise OmniparserProviderError("dependency_missing", "Pillow is required to read the static input image") from exc
    try:
        with Image.open(image_path) as image:
            image.verify()
        with Image.open(image_path) as image:
            return {"width": int(image.width), "height": int(image.height)}
    except (FileNotFoundError, UnidentifiedImageError, OSError) as exc:
        raise OmniparserProviderError("image_read_failed", f"Static input image could not be read: {exc}") from exc


def _license_provenance(code_path: Path, weights_path: Path) -> dict[str, Any]:
    files = {
        "repository_root_license": code_path / "LICENSE",
        "icon_detect_license": weights_path / "icon_detect" / "LICENSE",
        "icon_caption_florence_license": weights_path / "icon_caption_florence" / "LICENSE",
    }
    missing = [str(path) for path in files.values() if not path.is_file()]
    if missing:
        raise OmniparserProviderError("weights_missing", "Pinned license source files are missing: " + ", ".join(missing))
    return {
        "official_code": {
            "status": "ambiguous",
            "root_license": "CC-BY-4.0",
            "details": "Pinned repository root LICENSE states CC-BY-4.0 while the README badge says MIT; the conflicting README badge is not treated as an equivalent assertion.",
            "source_path": str(files["repository_root_license"]),
            "sha256": sha256_file(files["repository_root_license"]),
        },
        "icon_detect": {"license": "AGPL-3.0", "source_path": str(files["icon_detect_license"]), "sha256": sha256_file(files["icon_detect_license"])},
        "icon_caption_florence": {"license": "MIT", "source_path": str(files["icon_caption_florence_license"]), "sha256": sha256_file(files["icon_caption_florence_license"])},
    }


def _preflight(*, code_path: Path, weights_path: Path, hub_cache: Path) -> dict[str, Any]:
    try:
        disk = shutil.disk_usage(ROOT)
    except OSError as exc:
        raise OmniparserProviderError("runtime_preflight", f"Disk preflight failed: {exc}") from exc
    gpu = _gpu_snapshot()
    if not code_path.is_dir():
        raise OmniparserProviderError("provider_unavailable", f"Official code directory is missing: {code_path}")
    revision = _git_revision(code_path)
    if revision != "b0d5c9f5701f7e2be4771872e6e928da77759df3":
        raise OmniparserProviderError("provider_unavailable", f"Official code revision is not v.2.0.1: {revision}")
    if not gpu.get("available"):
        raise OmniparserProviderError("runtime_preflight", f"GPU probe failed: {gpu.get('reason')}")
    if int(gpu["free_bytes"]) < MINIMUM_FREE_GPU_BYTES:
        raise OmniparserProviderError("runtime_preflight", "GPU free memory is below the required 8 GiB")
    resident = _resident_compute_models()
    if resident:
        raise OmniparserProviderError("runtime_preflight", "Another compute model is resident: " + json.dumps(resident, ensure_ascii=True))
    return {
        "disk_free_bytes": int(disk.free),
        "gpu_before": gpu,
        "resident_compute_models": resident,
        "code_revision": revision,
        "weight_hashes": _verify_weight_manifest(weights_path),
        "florence_offline_assets": _require_florence_offline_assets(hub_cache),
        "license_provenance": _license_provenance(code_path, weights_path),
    }


def _enable_offline_inference(hub_cache: Path) -> None:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_CACHE"] = str(hub_cache)


def _pinned_caption_config_source(weights_path: Path) -> Path:
    return weights_path / "icon_caption_florence"


def _load_pinned_caption_model(weights_path: Path, hub_cache: Path) -> dict[str, Any]:
    _enable_offline_inference(hub_cache)
    try:
        import torch
        from transformers import AutoConfig, AutoModelForCausalLM, AutoProcessor
    except ImportError as exc:
        raise OmniparserProviderError("torch_import_failed", f"Pinned caption runtime dependencies could not be imported: {exc}") from exc
    if not torch.cuda.is_available():
        raise OmniparserProviderError("runtime_preflight", "CUDA is unavailable for pinned caption model loading")
    try:
        processor = AutoProcessor.from_pretrained(
            FLORENCE_PROCESSOR_REPOSITORY,
            revision=FLORENCE_PROCESSOR_REVISION,
            trust_remote_code=True,
            local_files_only=True,
        )
        config = AutoConfig.from_pretrained(
            str(_pinned_caption_config_source(weights_path)),
            revision=FLORENCE_MODEL_REVISION,
            trust_remote_code=True,
            local_files_only=True,
        )
        model = AutoModelForCausalLM.from_pretrained(
            str(_pinned_caption_config_source(weights_path)),
            config=config,
            trust_remote_code=True,
            local_files_only=True,
            torch_dtype=torch.float16,
        ).to("cuda")
    except (OSError, ValueError, RuntimeError) as exc:
        raise OmniparserProviderError("dependency_missing", f"Pinned offline Florence load failed: {exc}") from exc
    return {"model": model, "processor": processor}


def _load_official_models(code_path: Path, weights_path: Path, hub_cache: Path) -> tuple[Any, Any, Any, Any]:
    _enable_offline_inference(hub_cache)
    if str(code_path) not in sys.path:
        sys.path.insert(0, str(code_path))
    try:
        from util.utils import check_ocr_box, get_som_labeled_img, get_yolo_model
    except ImportError as exc:
        raise OmniparserProviderError("dependency_missing", f"Official OmniParser dependencies could not be imported: {exc}") from exc
    try:
        detector = get_yolo_model(str(weights_path / "icon_detect" / "model.pt"))
    except (OSError, RuntimeError, ValueError) as exc:
        raise OmniparserProviderError("inference_failed", f"Official icon detector load failed: {exc}") from exc
    return detector, _load_pinned_caption_model(weights_path, hub_cache), check_ocr_box, get_som_labeled_img


def _run_once(*, input_path: Path, detector: Any, caption: Any, check_ocr_box: Any, get_som_labeled_img: Any) -> tuple[list[dict[str, Any]], float]:
    started = time.perf_counter()
    (texts, ocr_boxes), _ = check_ocr_box(
        str(input_path), display_img=False, output_bb_format="xyxy", goal_filtering=None,
        easyocr_args={"paragraph": False, "text_threshold": 0.9}, use_paddleocr=False,
    )
    _, _, parsed_content_list = get_som_labeled_img(
        str(input_path), detector, BOX_TRESHOLD=0.01, output_coord_in_ratio=True,
        ocr_bbox=ocr_boxes, caption_model_processor=caption, ocr_text=texts,
        iou_threshold=0.9, imgsz=None, batch_size=32,
    )
    if not isinstance(parsed_content_list, list):
        raise OmniparserProviderError("protocol_invalid", "Official parsed_content_list must be a list")
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
        if not all(math.isfinite(value) for value in (x1, y1, x2, y2)) or not (0.0 <= x1 < x2 <= 1.0 and 0.0 <= y1 < y2 <= 1.0):
            invalid += 1
    return invalid


def _element_metrics(parsed_content_list: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "element_count": len(parsed_content_list),
        "interactive_count": sum(1 for item in parsed_content_list if isinstance(item, dict) and bool(item.get("interactivity"))),
        "invalid_bbox_count": _invalid_bbox_count(parsed_content_list),
    }


def _validate_warm_repetitions(value: int) -> int:
    if value < 3:
        raise OmniparserProviderError("protocol_invalid", "Benchmark mode requires warm_repetitions >= 3")
    return value


def _resource_usage(*, before: dict[str, Any], peak_bytes: int | None = None) -> dict[str, Any]:
    return {"gpu_available": bool(before.get("available")), "gpu_before": before, "gpu_peak_allocated_bytes": peak_bytes, "gpu_after": _gpu_snapshot()}


def _artifact_output_path(input_path: Path, supplied: Path | None) -> Path:
    if supplied is not None:
        return supplied
    return ROOT / "artifacts" / "omniparser-smoke" / f"{input_path.stem}-{time.strftime('%Y%m%d-%H%M%S')}.json"


def _write_artifact(path: Path, artifact: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _bootstrap_context(input_path: Path, profile: dict[str, Any] | None) -> dict[str, Any]:
    profile_id = str((profile or {}).get("profile_id") or "learn_mode_omniparser_v2")
    model_revision = "v.2.0.1@b0d5c9f5701f7e2be4771872e6e928da77759df3"
    try:
        image_size = _image_size(input_path)
        screenshot_sha = sha256_file(input_path)
    except OmniparserProviderError:
        image_size = {"width": 1, "height": 1}
        screenshot_sha = "0" * 64
    return {
        "profile_id": profile_id,
        "model_revision": model_revision,
        "capture_id": f"static-contact-sheet-{screenshot_sha[:16]}",
        "source_run_id": f"omniparser-smoke-{uuid4()}",
        "screenshot_sha256": screenshot_sha,
        "image_size": image_size,
        "coordinate_space": "image_normalized_xyxy",
    }


def _failed_artifact(*, error: OmniparserProviderError, stage: str, common: dict[str, Any], input_path: Path) -> dict[str, Any]:
    return build_failed_screen_parser_result(
        error_code=error.code,
        error_details=error.details,
        stage=stage,
        timing={},
        resource_usage={"gpu_after": _gpu_snapshot()},
        provenance={"input_path": str(input_path), "static_contact_sheet_only": True},
        **common,
    )


def main() -> int:
    args = _parse_args()
    input_path = args.input.resolve()
    output_path = _artifact_output_path(input_path, args.output)
    profile: dict[str, Any] | None = None
    detector = caption = None
    common = _bootstrap_context(input_path, profile)
    try:
        profile = _load_profile()
        common = _bootstrap_context(input_path, profile)
        if common["screenshot_sha256"] == "0" * 64:
            raise OmniparserProviderError("image_read_failed", "Static input image could not be read before preflight")
        warm_repetitions = _validate_warm_repetitions(args.warm_repetitions)
        code_path = ROOT / profile["expected_paths"]["code_path"]
        weights_path = ROOT / profile["expected_paths"]["weights_path"]
        hub_cache = Path(os.environ.get("HF_HUB_CACHE") or Path.home() / ".cache" / "huggingface" / "hub")
        preflight = _preflight(code_path=code_path, weights_path=weights_path, hub_cache=hub_cache)
        detector, caption, check_ocr_box, get_som_labeled_img = _load_official_models(code_path, weights_path, hub_cache)
        try:
            import torch
        except ImportError as exc:
            raise OmniparserProviderError("torch_import_failed", f"torch is required for GPU measurement: {exc}") from exc
        torch.cuda.reset_peak_memory_stats()
        cold_items, cold_ms = _run_once(input_path=input_path, detector=detector, caption=caption, check_ocr_box=check_ocr_box, get_som_labeled_img=get_som_labeled_img)
        cold_metrics = _element_metrics(cold_items)
        if cold_metrics["invalid_bbox_count"]:
            raise OmniparserProviderError("invalid_bbox", f"Cold official output contained {cold_metrics['invalid_bbox_count']} invalid bbox(es)")
        warm_runs: list[dict[str, Any]] = []
        for run_index in range(warm_repetitions):
            warm_items, elapsed_ms = _run_once(input_path=input_path, detector=detector, caption=caption, check_ocr_box=check_ocr_box, get_som_labeled_img=get_som_labeled_img)
            metrics = _element_metrics(warm_items)
            if metrics["invalid_bbox_count"]:
                raise OmniparserProviderError("invalid_bbox", f"Warm run {run_index + 1} contained {metrics['invalid_bbox_count']} invalid bbox(es)")
            warm_runs.append({"run_index": run_index + 1, "inference_ms": elapsed_ms, **metrics})
        warm_ms = [run["inference_ms"] for run in warm_runs]
        artifact = normalize_omniparser_result(
            parsed_content_list=cold_items,
            timing={"cold_inference_ms": cold_ms, "warm_inference_ms": warm_ms, "warm_p50_ms": statistics.median(warm_ms), "warm_p95_ms": _p95(warm_ms)},
            resource_usage=_resource_usage(before=preflight["gpu_before"], peak_bytes=int(torch.cuda.max_memory_allocated()) if torch.cuda.is_available() else None),
            provenance={
                "official_repo": "microsoft/OmniParser",
                "code_tag": profile["official_code"]["tag"],
                "code_revision": preflight["code_revision"],
                "model_hub_repo": "microsoft/OmniParser-v2.0",
                "model_hub_revision": MODEL_HUB_REVISION,
                "weight_manifest": {"model_hub_revision": MODEL_HUB_REVISION, "hashes": preflight["weight_hashes"]},
                "florence_offline_revisions": preflight["florence_offline_assets"],
                "license_provenance": preflight["license_provenance"],
                "input_path": str(input_path),
                "static_contact_sheet_only": True,
                "offline_inference_enforced": True,
            },
            **common,
        )
        from app.learn.recognition.parsers import parse_existing_evidence_to_inventory
        inventory = parse_existing_evidence_to_inventory({"capture_id": artifact["capture_id"], "screenshot_sha256": artifact["screenshot_sha256"], "image_size": artifact["image_size"], "sources": {"omniparser": artifact}})
        artifact["smoke_metrics"] = {
            **cold_metrics,
            "cold_run": {"inference_ms": cold_ms, **cold_metrics},
            "warm_runs": warm_runs,
            "inventory_count": len(inventory),
            "inventory_non_authorizing": all(item["click_candidate"] is False for item in inventory),
            "input_is_static_contact_sheet": True,
        }
    except OmniparserProviderError as exc:
        artifact = _failed_artifact(error=exc, stage="smoke_runner", common=common, input_path=input_path)
    except (FileNotFoundError, OSError) as exc:
        artifact = _failed_artifact(error=OmniparserProviderError("image_read_failed", str(exc)), stage="bootstrap", common=common, input_path=input_path)
    except (RuntimeError, ValueError) as exc:
        code = "cuda_oom" if "out of memory" in str(exc).casefold() else "inference_failed"
        artifact = _failed_artifact(error=OmniparserProviderError(code, str(exc)), stage="official_inference", common=common, input_path=input_path)
    finally:
        if detector is not None:
            del detector
        if caption is not None:
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
    print(json.dumps({"status": artifact["status"], "output": str(output_path), "source_run_id": common["source_run_id"]}, ensure_ascii=True))
    return 0 if artifact["status"] == "success" else 2


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1)))))]


if __name__ == "__main__":
    raise SystemExit(main())
