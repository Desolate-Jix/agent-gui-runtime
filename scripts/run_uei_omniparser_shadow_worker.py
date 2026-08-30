"""Fixed offline worker for the UEI OmniParser Shadow adapter."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import statistics


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-json", required=True, type=Path)
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--benchmark", action="store_true")
    return parser.parse_args()


def _input(path: Path) -> tuple[Path, dict[str, int]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("input_invalid") from error
    if not isinstance(value, dict) or set(value) != {"input_path", "image_size"}:
        raise ValueError("input_invalid")
    image_path, image_size = value.get("input_path"), value.get("image_size")
    if (not isinstance(image_path, str) or not isinstance(image_size, dict)
            or not all(isinstance(image_size.get(field), int) and image_size[field] > 0 for field in ("width", "height"))):
        raise ValueError("input_invalid")
    return Path(image_path), {"width": image_size["width"], "height": image_size["height"]}


def _hub_cache_path(profile: dict[str, object]) -> Path:
    explicit = os.environ.get("HF_HUB_CACHE")
    if explicit is not None:
        cache_path = Path(explicit)
        if not explicit.strip() or not cache_path.is_absolute():
            raise ValueError("huggingface_cache_invalid")
        return cache_path
    expected_paths = profile["expected_paths"]
    if not isinstance(expected_paths, dict):
        raise ValueError("huggingface_cache_invalid")
    return Path(str(expected_paths["huggingface_cache_path"])).expanduser()


def _run(input_path: Path, image_size: dict[str, int], *, benchmark: bool = False) -> dict[str, object]:
    from app.learn.recognition.omniparser_quality import filter_omniparser_candidates
    from scripts import run_omniparser_learn_smoke as runner

    profile = runner._load_profile()
    code_path = ROOT / profile["expected_paths"]["code_path"]
    weights_path = ROOT / profile["expected_paths"]["weights_path"]
    cache_path = _hub_cache_path(profile)
    preflight = runner._preflight(code_path=code_path, weights_path=weights_path, hub_cache=cache_path)
    detector, caption, check_ocr_box, get_som_labeled_img = runner._load_official_models(code_path, weights_path, cache_path)
    items, duration_ms = runner._run_once(
        input_path=input_path, detector=detector, caption=caption,
        check_ocr_box=check_ocr_box, get_som_labeled_img=get_som_labeled_img,
    )
    try:
        items, _quality_summary = filter_omniparser_candidates(items, image_size=image_size)
    except ValueError as error:
        raise ValueError("worker_output_invalid") from error
    normalized: list[dict[str, object]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError("worker_output_invalid")
        bbox = item.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            raise ValueError("worker_output_invalid")
        pixel_bbox = [round(float(bbox[0]) * image_size["width"]), round(float(bbox[1]) * image_size["height"]),
                      round(float(bbox[2]) * image_size["width"]), round(float(bbox[3]) * image_size["height"])]
        kind = str(item.get("type") or "element").strip().casefold()
        normalized.append({
            "source_item_id": f"omniparser/{index + 1}", "kind": kind,
            "safe_text": str(item.get("content") or ""), "source_bbox": pixel_bbox,
            "safe_role": kind if kind in {"element", "text", "icon", "structure"} else None,
            "safe_states": ["interactable"] if item.get("interactivity") is True else [],
            # 输入图片就是受限 capture 本体；按原尺寸反投影后的像素框属于 capture 坐标系。
            "source_coordinate_space": "capture_pixel_xyxy", "provider_confidence": None,
        })
    result = {"items": normalized, "duration_ms": int(round(duration_ms)), "resource_units": _peak_resource_units()}
    if benchmark:
        warm = []
        counts = [len(items)]
        invalid_counts = [_invalid_item_count(items)]
        for _ in range(3):
            warm_items, warm_duration = runner._run_once(input_path=input_path, detector=detector, caption=caption,
                                                          check_ocr_box=check_ocr_box, get_som_labeled_img=get_som_labeled_img)
            warm.append(int(round(warm_duration))); counts.append(len(warm_items)); invalid_counts.append(_invalid_item_count(warm_items))
        result["benchmark"] = {"cold_ms": int(round(duration_ms)), "warm_ms": warm,
                               "warm_p50_ms": statistics.median(warm), "warm_p95_ms": max(warm),
                               "item_counts": counts, "invalid_item_counts": invalid_counts,
                               "peak_mib": _peak_resource_units()}
    return result


def _peak_resource_units() -> int:
    """返回 worker 实测 CUDA 峰值 MiB；无 CUDA 时为已测得的零。"""
    try:
        import torch

        if torch.cuda.is_available():
            return max(0, int(torch.cuda.max_memory_allocated() // (1024 * 1024)))
    except (ImportError, RuntimeError):
        pass
    return 0


def _invalid_item_count(items: object) -> int:
    """按闭合归一化 bbox 规则统计 worker 原始无效项目。"""
    if not isinstance(items, list):
        return 1
    invalid = 0
    for item in items:
        bbox = item.get("bbox") if isinstance(item, dict) else None
        if (not isinstance(bbox, list) or len(bbox) != 4 or not all(isinstance(value, (int, float)) for value in bbox)
                or not (0 <= bbox[0] < bbox[2] <= 1 and 0 <= bbox[1] < bbox[3] <= 1)):
            invalid += 1
    return invalid


def main() -> int:
    args = _arguments()
    try:
        input_path, image_size = _input(args.input_json)
        output = _run(input_path, image_size, benchmark=args.benchmark)
        args.output_json.write_text(json.dumps(output, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        return 0
    except (OSError, ValueError, RuntimeError, ImportError):
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
