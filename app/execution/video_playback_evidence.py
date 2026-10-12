"""只读分析已绑定播放器的连续截图，不采图、不联网、不派发输入。"""

from hashlib import sha256
from io import BytesIO
from math import isclose, isfinite
from pathlib import Path
import re
from types import MappingProxyType

from PIL import Image, ImageChops, ImageDraw, UnidentifiedImageError


DEFAULT_POLICY = MappingProxyType({
    "min_frame_count": 3, "min_span_ms": 1000, "min_valid_pixels": 256,
    "max_masked_fraction": 0.5, "min_positive_intervals": 2,
    "min_progress_delta_seconds": 0.1, "min_progress_rate": 0.25,
    "max_progress_rate": 2.5, "progress_step_tolerance_seconds": 0.25,
})
_FRAME_FIELDS = {"image_path", "sha256", "capture_id", "window_identity", "elapsed_ms"}
_STATES = {"playing", "paused", "loading", "ad", "error", "ended", "unknown"}
_CAPTURE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}\Z")
_MAX_BYTES = 20 * 1024 * 1024
_MAX_PIXELS = 40_000_000


class _InvalidEvidence(ValueError):
    pass


def _require(condition, reason):
    if not condition:
        raise _InvalidEvidence(reason)


def _number(value):
    if type(value) not in (int, float):
        return False
    try:
        return isfinite(value)
    except OverflowError:
        return False


def _policy(policy):
    _require(policy is None or isinstance(policy, dict), "policy_invalid")
    supplied = {} if policy is None else policy
    _require(not set(supplied) - set(DEFAULT_POLICY), "policy_invalid")
    result = dict(DEFAULT_POLICY)
    result.update(supplied)
    _require(all(_number(value) for value in result.values()), "policy_invalid")
    for key, minimum, maximum in (
            ("min_frame_count", 3, 7), ("min_valid_pixels", 256, _MAX_PIXELS),
            ("min_positive_intervals", 2, 6)):
        _require(type(result[key]) is int and minimum <= result[key] <= maximum, "policy_invalid")
    _require(result["min_span_ms"] >= 1000, "policy_invalid")
    _require(0 <= result["max_masked_fraction"] <= 0.5, "policy_invalid")
    _require(result["min_progress_delta_seconds"] >= 0.1, "policy_invalid")
    _require(0.25 <= result["min_progress_rate"] <= result["max_progress_rate"] <= 2.5, "policy_invalid")
    _require(0 <= result["progress_step_tolerance_seconds"] <= 0.25, "policy_invalid")
    return result


def _identity(identity):
    _require(isinstance(identity, dict) and set(identity) == {
        "handle", "process_id", "process_create_time"}, "identity_invalid")
    _require(all(type(identity[key]) is int and identity[key] > 0
        for key in ("handle", "process_id")), "identity_invalid")
    _require(_number(identity["process_create_time"]) and identity["process_create_time"] > 0,
        "identity_invalid")
    return dict(identity)


def _rectangle(value, outer, reason):
    _require(isinstance(value, (list, tuple)) and len(value) == 4
        and all(type(item) is int for item in value), reason)
    x, y, width, height = value
    _require(x >= 0 and y >= 0 and width > 0 and height > 0, reason)
    ox, oy, ow, oh = outer
    _require(ox <= x and oy <= y and x + width <= ox + ow and y + height <= oy + oh, reason)
    return x, y, width, height


def _region(region, size, policy):
    _require(isinstance(region, dict) and {"bbox", "content_bbox", "masks"} <= set(region),
        "region_invalid")
    player = _rectangle(region["bbox"], (0, 0, *size), "region_invalid")
    content = _rectangle(region["content_bbox"], player, "region_invalid")
    masks = region["masks"]
    _require(isinstance(masks, (list, tuple)) and len(masks) <= 32, "mask_invalid")
    cx, cy, width, height = content
    valid = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(valid)
    for mask in masks:
        x, y, mw, mh = _rectangle(mask, player, "mask_invalid")
        left, top = max(x, cx), max(y, cy)
        right, bottom = min(x + mw, cx + width), min(y + mh, cy + height)
        if right > left and bottom > top:
            draw.rectangle((left - cx, top - cy, right - cx - 1, bottom - cy - 1), fill=0)
    pixels = valid.histogram()[255]
    fraction = 1 - pixels / (width * height)
    _require(pixels >= policy["min_valid_pixels"]
        and fraction <= policy["max_masked_fraction"], "masked_content_insufficient")
    return content, valid, pixels, fraction


def _png(frame):
    digest = frame["sha256"]
    _require(isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest) is not None,
        "image_hash_invalid")
    reference = frame["image_path"]
    _require(isinstance(reference, str) and 0 < len(reference) <= 32768
        and "\x00" not in reference and "://" not in reference
        and not reference.startswith(("//", "\\\\")), "image_path_invalid")
    path = Path(reference)
    _require(path.is_absolute(), "image_path_invalid")
    try:
        with path.open("rb") as source:
            raw = source.read(_MAX_BYTES + 1)
    except OSError:
        raise _InvalidEvidence("image_read_failed") from None
    _require(len(raw) <= _MAX_BYTES, "image_too_large")
    _require(sha256(raw).hexdigest() == digest, "image_hash_mismatch")
    try:
        with Image.open(BytesIO(raw)) as image:
            _require(image.format == "PNG" and not getattr(image, "is_animated", False),
                "image_format_invalid")
            _require(0 < image.width * image.height <= _MAX_PIXELS, "image_size_invalid")
            size = image.size
            image.verify()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError):
        raise _InvalidEvidence("image_invalid") from None
    return raw, size


def _gray(raw, content, valid, sample_size):
    x, y, width, height = content
    try:
        with Image.open(BytesIO(raw)) as image:
            crop = image.crop((x, y, x + width, y + height)).convert("L")
            # 先抹掉遮挡像素再缩小，避免字幕通过插值污染邻接内容。
            masked = ImageChops.multiply(crop, valid)
            return list(masked.resize(sample_size, Image.Resampling.BOX).tobytes())
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError):
        raise _InvalidEvidence("image_invalid") from None


def _motion(before, after, valid, size, first_id, last_id):
    width, height = size
    total, changed, absolute = 0, 0, 0
    blocks, changed_blocks = {}, {}
    for index, weight in enumerate(valid):
        if not weight:
            continue
        block = ((index % width) * 4 // width, (index // width) * 4 // height)
        delta = abs(after[index] - before[index])
        total += 1
        absolute += delta
        blocks[block] = blocks.get(block, 0) + 1
        if delta >= 12:
            changed += 1
            changed_blocks[block] = changed_blocks.get(block, 0) + 1
    active = {block for block, count in blocks.items()
        if changed_blocks.get(block, 0) / count >= 0.05}
    pixel_fraction = changed / total
    block_fraction = len(active) / len(blocks)
    distributed = (pixel_fraction >= 0.05 and block_fraction >= 0.25
        and len({block[0] for block in active}) >= 2
        and len({block[1] for block in active}) >= 2)
    return {"from_capture_id": first_id, "to_capture_id": last_id,
        "mean_gray_delta": round(absolute / total, 6),
        "changed_pixel_fraction": round(pixel_fraction, 6),
        "changed_block_fraction": round(block_fraction, 6), "distributed_motion": distributed}


def evaluate_playback_sequence(frames, region, observations, policy=None):
    """可信状态与读数由绑定观察器提供；画面运动本身永不构成播放成功。"""
    metrics = {"frame_count": 0, "span_ms": 0, "image_size": None,
        "valid_content_pixels": 0, "masked_fraction": 0,
        "usable_frame_count": 0, "usable_span_ms": 0,
        "positive_progress_intervals": 0, "progress_seconds": None, "progress_rate": None,
        "motion_pairs": [], "semantic_review_suggested": False}

    def result(status, reason):
        return {"status": status, "reason": [reason], "metrics": metrics}

    try:
        effective = _policy(policy)
        _require(isinstance(frames, (list, tuple)), "frames_invalid")
        metrics["frame_count"] = len(frames)
        _require(effective["min_frame_count"] <= len(frames) <= 7, "frame_count_invalid")
        _require(isinstance(observations, (list, tuple)) and len(observations) == len(frames),
            "observation_invalid")
        capture_ids, elapsed, readings, states = [], [], [], []
        identity = None
        for frame, observation in zip(frames, observations):
            _require(isinstance(frame, dict) and _FRAME_FIELDS <= set(frame), "frame_fields_invalid")
            capture_id = frame["capture_id"]
            _require(isinstance(capture_id, str) and _CAPTURE_ID.fullmatch(capture_id) is not None
                and capture_id not in capture_ids, "capture_id_invalid")
            current_identity = _identity(frame["window_identity"])
            _require(identity is None or current_identity == identity, "identity_changed")
            identity = current_identity
            moment = frame["elapsed_ms"]
            _require(_number(moment) and moment >= 0
                and (not elapsed or moment > elapsed[-1]), "elapsed_invalid")
            _require(isinstance(observation, dict)
                and {"capture_id", "position_seconds", "state"} <= set(observation)
                and observation["capture_id"] == capture_id
                and isinstance(observation["state"], str) and observation["state"] in _STATES,
                "observation_invalid")
            position = observation["position_seconds"]
            _require(position is None or _number(position) and position >= 0, "position_invalid")
            capture_ids.append(capture_id)
            elapsed.append(moment)
            readings.append(position)
            states.append(observation["state"])
        metrics["span_ms"] = elapsed[-1] - elapsed[0]
        _require(isfinite(metrics["span_ms"])
            and metrics["span_ms"] >= effective["min_span_ms"], "span_insufficient")
        pixels, size, content, valid = [], None, None, None
        for frame in frames:
            raw, current_size = _png(frame)
            _require(size is None or current_size == size, "image_size_changed")
            if size is None:
                size = current_size
                content, valid, count, fraction = _region(region, size, effective)
                metrics.update(image_size=list(size), valid_content_pixels=count, masked_fraction=fraction)
                scale = min(1, 160 / max(content[2:]))
                sample_size = (max(1, round(content[2] * scale)), max(1, round(content[3] * scale)))
                sample_valid = list(valid.resize(sample_size, Image.Resampling.BOX).tobytes())
            pixels.append(_gray(raw, content, valid, sample_size))
        metrics["motion_pairs"] = [_motion(pixels[index - 1], pixels[index], sample_valid,
            sample_size, capture_ids[index - 1], capture_ids[index]) for index in range(1, len(frames))]
        start = len(states)
        while start > 0 and states[start - 1] == "playing":
            start -= 1
        metrics["usable_frame_count"] = len(states) - start
        if start < len(states):
            metrics["usable_span_ms"] = elapsed[-1] - elapsed[start]
        latest = states[-1]
        if latest == "loading":
            return result("loading", latest)
        if latest in {"paused", "ad", "error", "ended"}:
            return result("not_playing", latest)
        # 只有末尾无冲突区间中的持续分散运动可建议一次语义核验。
        diagnostic_start = len(states)
        while diagnostic_start > 0 and states[diagnostic_start - 1] in {"playing", "unknown"}:
            diagnostic_start -= 1
        if (len(states) - diagnostic_start >= effective["min_frame_count"]
                and elapsed[-1] - elapsed[diagnostic_start] >= effective["min_span_ms"]):
            pairs = metrics["motion_pairs"][diagnostic_start:]
            metrics["semantic_review_suggested"] = len(pairs) >= 2 and all(
                pair["distributed_motion"] for pair in pairs[-2:])
        if latest != "playing":
            return result("uncertain", "state_unverified")
        if (metrics["usable_frame_count"] < effective["min_frame_count"]
                or metrics["usable_span_ms"] < effective["min_span_ms"]):
            return result("uncertain", "playing_sequence_insufficient")
        positions = readings[start:]
        if any(position is None for position in positions):
            return result("uncertain", "progress_unavailable")
        deltas = [positions[index] - positions[index - 1] for index in range(1, len(positions))]
        metrics["positive_progress_intervals"] = sum(
            delta >= effective["min_progress_delta_seconds"] or isclose(
                delta, effective["min_progress_delta_seconds"], rel_tol=1e-12, abs_tol=0)
            for delta in deltas)
        metrics["progress_seconds"] = positions[-1] - positions[0]
        metrics["progress_rate"] = metrics["progress_seconds"] / (metrics["usable_span_ms"] / 1000)
        if any(delta < 0 for delta in deltas):
            return result("uncertain", "position_regressed")
        if any(delta > effective["max_progress_rate"] * (elapsed[start + index + 1]
                - elapsed[start + index]) / 1000 + effective["progress_step_tolerance_seconds"]
                for index, delta in enumerate(deltas)):
            return result("uncertain", "position_jump")
        if metrics["positive_progress_intervals"] < effective["min_positive_intervals"]:
            return result("uncertain", "progress_insufficient")
        if not effective["min_progress_rate"] <= metrics["progress_rate"] <= effective["max_progress_rate"]:
            return result("uncertain", "progress_rate_invalid")
        metrics["semantic_review_suggested"] = False
        return result("playing", "sustained_progress")
    except _InvalidEvidence as error:
        metrics["semantic_review_suggested"] = False
        return result("uncertain", str(error))


__all__ = ["DEFAULT_POLICY", "evaluate_playback_sequence"]
