"""时序播放只接受固定证据结构；原 after 与只读采样链分别绑定。"""
import base64
import json
import math
from pathlib import Path
import re


_FRAME_FIELDS = {"capture_id", "sha256", "image_path", "window_identity", "role"}
ANALYSIS_POLICY = "video_playback_local.v1"
_METRICS = {"frame_count", "span_ms", "image_size", "valid_content_pixels", "masked_fraction",
    "usable_frame_count", "usable_span_ms", "positive_progress_intervals", "progress_seconds",
    "progress_rate", "motion_pairs", "semantic_review_suggested"}


def _number(value, low, high):
    try:
        return type(value) in (int, float) and low <= value <= high and math.isfinite(value)
    except OverflowError:
        return False


def _rectangle(value):
    return (type(value) is list and len(value) == 4 and all(type(v) is int for v in value)
        and value[0] >= 0 and value[1] >= 0 and value[2] > 0 and value[3] > 0)


def _contains(outer, inner):
    return (outer[0] <= inner[0] and outer[1] <= inner[1]
        and inner[0] + inner[2] <= outer[0] + outer[2] and inner[1] + inner[3] <= outer[1] + outer[3])


def _frame(value, role):
    if (type(value) is not dict or set(value) != _FRAME_FIELDS or value.get("role") != role
            or type(value.get("capture_id")) is not str or not 0 < len(value["capture_id"]) <= 200
            or not value["capture_id"].strip() or type(value.get("sha256")) is not str
            or not re.fullmatch(r"[0-9a-f]{64}", value["sha256"])
            or type(value.get("image_path")) is not str or not 0 < len(value["image_path"]) <= 32768
            or "://" in value["image_path"]):
        raise ValueError("decision_temporal_frame_invalid")
    identity = value["window_identity"]
    if (type(identity) is not dict or set(identity) != {"handle", "process_id", "process_create_time"}
            or any(type(identity.get(k)) is not int or identity[k] <= 0 for k in ("handle", "process_id"))
            or not _number(identity.get("process_create_time"), 0, 1e15) or identity["process_create_time"] == 0):
        raise ValueError("decision_temporal_window_invalid")


def _normalize_picture_change_context(value):
    fields = {"schema", "original_after", "samples", "selected_capture_ids", "timeout_seconds"}
    if value["schema"] == "temporal_visual_change.v1":
        fields.add("target_description")
    if set(value) != fields:
        raise ValueError("decision_temporal_fields_invalid")
    if value["schema"] == "temporal_visual_change.v1" and (
            type(value["target_description"]) is not str or not value["target_description"].strip()
            or len(value["target_description"]) > 1000):
        raise ValueError("decision_temporal_target_description_invalid")
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError):
        raise ValueError("decision_temporal_json_invalid") from None
    if len(encoded.encode("utf-8")) > 64 * 1024:
        raise ValueError("decision_temporal_context_too_large")
    value = json.loads(encoded)
    _frame(value["original_after"], "after")
    samples = value["samples"]
    if type(samples) is not list or len(samples) != 3:
        raise ValueError("decision_temporal_samples_invalid")
    for sample in samples:
        if (type(sample) is not dict or set(sample) != {"frame", "elapsed_ms"}
                or not _number(sample["elapsed_ms"], 1000, 8000) or sample["elapsed_ms"] >= 8000):
            raise ValueError("decision_temporal_sample_invalid")
        _frame(sample["frame"], "observation")
    times = [sample["elapsed_ms"] for sample in samples]
    if any(b - a < 500 for a, b in zip(times, times[1:])) or times[-1] - times[0] < 1000:
        raise ValueError("decision_temporal_interval_invalid")
    ids = [sample["frame"]["capture_id"] for sample in samples]
    if len(set(ids)) != 3 or value["original_after"]["capture_id"] in ids:
        raise ValueError("decision_temporal_capture_duplicate")
    if any(sample["frame"]["window_identity"] != value["original_after"]["window_identity"] for sample in samples):
        raise ValueError("decision_temporal_window_mismatch")
    if type(value["selected_capture_ids"]) is not list or value["selected_capture_ids"] != ids:
        raise ValueError("decision_temporal_selection_invalid")
    if not _number(value["timeout_seconds"], 0, 8) or value["timeout_seconds"] == 0:
        raise ValueError("decision_temporal_budget_invalid")
    return value


def normalize_temporal_context(value):
    if type(value) is dict and value.get("schema") in ("temporal_playback.v2", "temporal_visual_change.v1"):
        return _normalize_picture_change_context(value)
    fields = {"schema", "original_after", "samples", "region", "analysis", "analysis_policy", "selected_capture_ids", "timeout_seconds"}
    if (type(value) is not dict or set(value) != fields or value.get("schema") != "temporal_playback.v1"
            or value.get("analysis_policy") != ANALYSIS_POLICY):
        raise ValueError("decision_temporal_fields_invalid")
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError):
        raise ValueError("decision_temporal_json_invalid") from None
    if len(encoded.encode("utf-8")) > 64 * 1024:
        raise ValueError("decision_temporal_context_too_large")
    value = json.loads(encoded)
    _frame(value["original_after"], "after")
    samples = value["samples"]
    if type(samples) is not list or not 3 <= len(samples) <= 7:
        raise ValueError("decision_temporal_samples_invalid")
    for sample in samples:
        if type(sample) is not dict or set(sample) != {"frame", "elapsed_ms", "observation"} or not _number(sample["elapsed_ms"], 0, 8000):
            raise ValueError("decision_temporal_sample_invalid")
        _frame(sample["frame"], "observation")
        observation = sample["observation"]
        if (type(observation) is not dict or set(observation) != {"capture_id", "position_seconds", "state"}
                or observation["capture_id"] != sample["frame"]["capture_id"]
                or observation["state"] not in ("playing", "paused", "loading", "ad", "error", "ended", "unknown")
                or observation["position_seconds"] is not None and not _number(observation["position_seconds"], 0, math.inf)):
            raise ValueError("decision_temporal_observation_invalid")
    times = [sample["elapsed_ms"] for sample in samples]
    ids = [sample["frame"]["capture_id"] for sample in samples]
    span = times[-1] - times[0]
    if any(b <= a for a, b in zip(times, times[1:])) or span < 1000:
        raise ValueError("decision_temporal_interval_invalid")
    if len(set(ids)) != len(ids) or value["original_after"]["capture_id"] in ids:
        raise ValueError("decision_temporal_capture_duplicate")
    if any(sample["frame"]["window_identity"] != value["original_after"]["window_identity"] for sample in samples):
        raise ValueError("decision_temporal_window_mismatch")
    selected = value["selected_capture_ids"]
    if (type(selected) is not list or len(selected) != 2 or any(type(i) is not str or i not in ids for i in selected)
            or ids.index(selected[0]) >= ids.index(selected[1])
            or times[ids.index(selected[1])] - times[ids.index(selected[0])] < 1000):
        raise ValueError("decision_temporal_selection_invalid")
    if not _number(value["timeout_seconds"], 0, 8) or value["timeout_seconds"] == 0:
        raise ValueError("decision_temporal_budget_invalid")
    region = value["region"]
    if (type(region) is not dict or set(region) != {"bbox", "content_bbox", "masks"}
            or not _rectangle(region["bbox"]) or not _rectangle(region["content_bbox"])
            or not _contains(region["bbox"], region["content_bbox"])
            or type(region["masks"]) is not list or len(region["masks"]) > 16
            or any(not _rectangle(mask) or not _contains(region["bbox"], mask) for mask in region["masks"])):
        raise ValueError("decision_temporal_region_invalid")
    analysis = value["analysis"]
    if (type(analysis) is not dict or set(analysis) != {"status", "reason", "metrics"}
            or analysis["status"] not in ("playing", "not_playing", "loading", "uncertain")
            or type(analysis["reason"]) is not list or not 1 <= len(analysis["reason"]) <= 16
            or any(type(code) is not str or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code) for code in analysis["reason"])
            or len(json.dumps(analysis).encode("utf-8")) > 16 * 1024):
        raise ValueError("decision_temporal_analysis_invalid")
    metrics = analysis["metrics"]
    if type(metrics) is not dict or set(metrics) != _METRICS:
        raise ValueError("decision_temporal_metrics_invalid")
    for key, low, high in (("frame_count", len(samples), len(samples)), ("valid_content_pixels", 0, 40_000_000),
            ("usable_frame_count", 0, len(samples)), ("positive_progress_intervals", 0, len(samples) - 1)):
        if type(metrics[key]) is not int or not low <= metrics[key] <= high:
            raise ValueError("decision_temporal_metrics_invalid")
    size = metrics["image_size"]
    if (type(size) is not list or len(size) != 2 or any(type(n) is not int or n <= 0 for n in size)
            or size[0] * size[1] > 40_000_000 or not _number(metrics["span_ms"], span, span)
            or not _number(metrics["usable_span_ms"], 0, span) or not _number(metrics["masked_fraction"], 0, 1)
            or type(metrics["semantic_review_suggested"]) is not bool
            or any(metrics[k] is not None and not _number(metrics[k], -1e6, 1e6) for k in ("progress_seconds", "progress_rate"))):
        raise ValueError("decision_temporal_metrics_invalid")
    pairs = metrics["motion_pairs"]
    if type(pairs) is not list or len(pairs) != len(samples) - 1:
        raise ValueError("decision_temporal_motion_invalid")
    for index, pair in enumerate(pairs):
        if (type(pair) is not dict or set(pair) != {"from_capture_id", "to_capture_id", "mean_gray_delta",
                "changed_pixel_fraction", "changed_block_fraction", "distributed_motion"}
                or pair["from_capture_id"] != ids[index] or pair["to_capture_id"] != ids[index + 1]
                or not _number(pair["mean_gray_delta"], 0, 255)
                or any(not _number(pair[k], 0, 1) for k in ("changed_pixel_fraction", "changed_block_fraction"))
                or type(pair["distributed_motion"]) is not bool):
            raise ValueError("decision_temporal_motion_invalid")
    return value


def prepare_temporal_context(root, value, frames, prepare_frame, *, include_upload):
    value = normalize_temporal_context(value)
    original = value["original_after"]
    path = Path(original["image_path"])
    original["image_path"] = str((path if path.is_absolute() else root / path).resolve(strict=True))
    if original != next(frame for frame in frames if frame["role"] == "after"):
        raise ValueError("decision_temporal_original_after_mismatch")
    uploaded, paths, size = [], {original["image_path"]}, None
    roles = (("sample_start", "sample_middle", "sample_end")
        if value["schema"] in ("temporal_playback.v2", "temporal_visual_change.v1") else ("sample_start", "sample_end"))
    selected = dict(zip(value["selected_capture_ids"], roles))
    for sample in value["samples"]:
        item, data, mime, dimensions = prepare_frame(root, sample["frame"], static_png=True)
        if mime != "image/png":
            raise ValueError("decision_temporal_png_required")
        if size is None:
            size = dimensions
        if dimensions != size or item["image_path"] in paths:
            raise ValueError("decision_temporal_image_binding_invalid")
        paths.add(item["image_path"])
        sample["frame"] = item
        if include_upload and item["capture_id"] in selected:
            uploaded.append({"capture_id": item["capture_id"], "role": selected[item["capture_id"]],
                "data_url": "data:image/png;base64," + base64.b64encode(data).decode("ascii")})
    # 原 after 已由共用证据入口验证；所有时序图必须与它同尺寸。
    _, _, original_mime, original_size = prepare_frame(root, original, static_png=True)
    if original_mime != "image/png" or size != original_size:
        raise ValueError("decision_temporal_geometry_mismatch")
    if value["schema"] == "temporal_playback.v1" and (list(size) != value["analysis"]["metrics"]["image_size"]
            or not _contains([0, 0, *size], value["region"]["bbox"])):
        raise ValueError("decision_temporal_geometry_mismatch")
    return value, uploaded


def provider_temporal_metadata(value):
    value = normalize_temporal_context(value)
    value["original_after"].pop("image_path")
    for sample in value["samples"]:
        sample["frame"].pop("image_path")
    return value
