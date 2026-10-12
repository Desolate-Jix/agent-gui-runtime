"""一次定位播放器，随后仅从绑定原图提取保守的播放进度。"""
from collections import OrderedDict
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
import math
from pathlib import Path
import re
import time
from uuid import uuid4

import numpy as np
from PIL import Image

from app.vision.grounding_contract import validate_grounding_result

_CACHE = OrderedDict()
_TIME = re.compile(r"(?<!\d)(\d{1,2}:\d{2}(?::\d{2})?)\s*/\s*(\d{1,2}:\d{2}(?::\d{2})?)(?!\d)")


def _image(frame, session_dir):
    try:
        session = Path(session_dir).resolve(strict=True)
        source = Path(frame["image_path"])
        path = source.resolve(strict=True)
        if source.is_symlink() or not path.is_relative_to(session) or path.stat().st_size > 20 * 1024 * 1024:
            raise ValueError("path")
        raw = path.read_bytes()
        if sha256(raw).hexdigest() != frame["sha256"]:
            raise ValueError("hash")
        with Image.open(BytesIO(raw)) as im:
            if (im.format != "PNG" or getattr(im, "is_animated", False)
                    or getattr(im, "n_frames", 1) != 1 or im.width * im.height > 40_000_000):
                raise ValueError("png")
            im.verify()
        with Image.open(BytesIO(raw)) as im:
            if frame.get("image_size", {"width": im.width, "height": im.height}) != {"width": im.width, "height": im.height}:
                raise ValueError("size")
            return im.convert("RGB")
    except (KeyError, OSError, TypeError, ValueError, SyntaxError, Image.DecompressionBombError):
        raise ValueError("video_playback_frame_invalid") from None


def _region(box, size):
    if (not isinstance(box, list) or len(box) != 4 or any(type(v) is not int for v in box)
            or min(box[:2]) < 0 or min(box[2:]) < 32
            or box[0] + box[2] > size[0] or box[1] + box[3] > size[1]):
        raise ValueError("video_playback_region_invalid")
    x, y, w, h = box
    # 排除标题、控制栏和常见顶部弹幕带；变化量不能单独证明播放。
    top, bottom = max(2, h // 10), max(20, h // 5)
    return {"bbox": box, "content_bbox": [x + 2, y + top, w - 4, h - top - bottom], "masks": []}


def page_loading(frame, *, session_dir):
    """仅延后近乎全白内容页；非白内容仍须由唯一定位调用判断。"""
    image = _image(frame, session_dir)
    w, h = image.size
    content = image.crop((w // 10, h // 5, w * 9 // 10, h * 9 // 10))
    content.thumbnail((128, 128))
    return bool(np.mean(np.all(np.asarray(content) >= 245, axis=2)) >= .995)


def locate_player(coordinator, original_frame, *, goal, session_dir, remaining_seconds, api_grounder=None):
    if (type(remaining_seconds) not in (float, int) or not math.isfinite(remaining_seconds)
            or remaining_seconds <= 0):
        raise ValueError("video_playback_budget_exhausted")
    started = time.monotonic()
    original = deepcopy(original_frame)
    image = _image(original, session_dir)
    if api_grounder is None:
        raise ValueError("video_playback_locator_unavailable")
    request_id = "video-player-" + uuid4().hex
    remaining = remaining_seconds - (time.monotonic() - started)
    if remaining <= 0:
        raise ValueError("video_playback_budget_exhausted")
    result = api_grounder.ground(request_id=request_id, capture={**original,
        "image_size": {"width": image.width, "height": image.height}},
        goal="Locate the entire main video player for this task: " + goal +
            ". Include its playback controls; exclude recommendations, previews and advertisements. "
            "Return absent or ambiguous if the intended main player cannot be identified. Only locate; do not act.",
        timeout_seconds=min(8.0, remaining))
    validated = validate_grounding_result(result["result"], request_id=request_id,
        capture_id=original["capture_id"], image_size=image.size)
    # 定位拒绝也保留已去凭据的 provider 计时；诊断不授予采用权限。
    folder = Path(session_dir) / "video-playback-observer"
    folder.mkdir(exist_ok=True)
    diagnostic = {"schema": "video_player_locator_diagnostic.v1", "source_frame": original,
        "grounding_result": validated.model_dump(), "provider": result.get("provider", {}),
        "elapsed_ms": (time.monotonic() - started) * 1000}
    with (folder / (request_id + "-diagnostic.json")).open("x", encoding="utf-8") as stream:
        json.dump(diagnostic, stream, ensure_ascii=False, allow_nan=False)
    if time.monotonic() - started >= remaining_seconds:
        raise ValueError("video_playback_budget_exhausted")
    if result.get("action_executed") is not False or validated.status != "found" or len(validated.candidates) != 1:
        raise ValueError("video_playback_player_ambiguous")
    candidate = validated.candidates[0]
    if (candidate.id != validated.selected_candidate_id or candidate.evidence_source != "api_visual"
            or candidate.confidence is not None and candidate.confidence < .85):
        raise ValueError("video_playback_player_ambiguous")
    b = candidate.bbox
    region = _region([b.x, b.y, b.width, b.height], image.size)
    evidence = {"schema": "video_player_locator.v1", "source_frame": original,
                "grounding_result": validated.model_dump(), "provider": result.get("provider", {}),
                "region": region, "elapsed_ms": (time.monotonic() - started) * 1000}
    path = folder / (request_id + ".json")
    raw = (json.dumps(evidence, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    with path.open("xb") as stream:
        stream.write(raw)
    return {"region": region, "evidence": evidence,
            "refs": [{"path": path.relative_to(session_dir).as_posix(), "sha256": sha256(raw).hexdigest()}]}


def _ocr_rows(image):
    from app.core.ocr_service import ocr_service
    # 复用唯一轻量 OCR 引擎；失败直接显式降为不确定，不启动其他模型。
    engine = ocr_service._get_rapidocr_engine()
    raw, _ = engine(np.asarray(image)[:, :, ::-1].copy())
    matches = ocr_service._parse_matches(raw)
    return [{"text": m.text, "score": m.score,
             "bbox": [m.bbox.x, m.bbox.y, m.bbox.width, m.bbox.height]} for m in matches]


def _pause_bars(image):
    pixels = np.asarray(image.convert("L"))
    h, w = pixels.shape
    # 只接受左下控制区中孤立、等高的两条亮色竖线。
    crop = pixels[int(h * .8):, :max(1, int(w * .16))] > 210
    visited = np.zeros(crop.shape, dtype=bool)
    bars = []
    for yy, xx in zip(*np.where(crop)):
        if visited[yy, xx]:
            continue
        pending, points = [(int(xx), int(yy))], []
        visited[yy, xx] = True
        while pending:
            x, y = pending.pop()
            points.append((x, y))
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if 0 <= nx < crop.shape[1] and 0 <= ny < crop.shape[0] and crop[ny, nx] and not visited[ny, nx]:
                    visited[ny, nx] = True
                    pending.append((nx, ny))
        xs, ys = zip(*points)
        bw, bh = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
        if 2 <= bw <= 10 and 8 <= bh <= 30 and 2 <= bh / bw <= 8 and len(points) / (bw * bh) >= .85:
            bars.append((min(xs), min(ys), bw, bh))
    pairs = []
    for i, a in enumerate(bars):
        for b in bars[i + 1:]:
            left, right = sorted((a, b))
            if (abs(left[1] - right[1]) <= 1 and abs(left[2] - right[2]) <= 1 and abs(left[3] - right[3]) <= 1
                    and 2 <= right[0] - left[0] - left[2] <= left[2] * 2):
                pairs.append((left, right))
    return len(pairs) == 1


def _seconds(text):
    parts = [int(p) for p in text.split(":")]
    if any(p >= 60 for p in parts[1:]):
        return None
    return float(sum(p * 60 ** i for i, p in enumerate(reversed(parts))))


def _anchor_stable(original, image, box):
    x, y, w, h = box
    strips = [(x, max(0, y - 8), x + w, y), (x, y + h, x + w, min(image.height, y + h + 8)),
              (max(0, x - 8), y, x, y + h), (x + w, y, min(image.width, x + w + 8), y + h)]
    usable = 0
    for left, top, right, bottom in strips:
        if (right - left) * (bottom - top) < 64:
            continue
        usable += 1
        a = np.asarray(original.crop((left, top, right, bottom)).convert("L"), dtype=np.int16)
        b = np.asarray(image.crop((left, top, right, bottom)).convert("L"), dtype=np.int16)
        if float(np.mean(np.abs(a - b) > 24)) > .05:
            return False
    # 全屏缺少稳定边缘锚点时仍保留图像，交时序模型核验归属。
    return usable > 0


def _observation_key(frame, locator, session_dir):
    return (str(Path(session_dir).resolve()), frame["sha256"],
            sha256(json.dumps(locator, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest())


def _observation_path(key):
    return Path(key[0]) / "video-playback-observer" / ("observation-" + key[-1][:16] + "-" + key[1] + ".json")


def observation_evidence_refs(frame, locator, *, session_dir):
    from .task_plan_observation_evidence import reference
    path = _observation_path(_observation_key(frame, locator, session_dir))
    if not path.is_file():
        raise ValueError("video_playback_observation_evidence_missing")
    return [reference(Path(session_dir).resolve(), path)]


def observe_player_frame(frame, locator, *, session_dir):
    image = _image(frame, session_dir)
    evidence = locator.get("evidence", {})
    source = evidence.get("source_frame", {})
    original_image = _image(source, session_dir)
    if (frame.get("window_identity") != source.get("window_identity")
            or frame.get("window_rect", source.get("window_rect")) != source.get("window_rect")
            or image.size != original_image.size):
        raise ValueError("video_playback_window_changed")
    region = _region(locator["region"]["bbox"], image.size)
    if region != locator["region"] or region != evidence.get("region"):
        raise ValueError("video_playback_region_changed")
    key = _observation_key(frame, locator, session_dir)
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return {**_CACHE[key], "capture_id": frame["capture_id"]}
    x, y, w, h = region["bbox"]
    crop = image.crop((x, y, x + w, y + h))
    position, state, reason = None, "unknown", "controls_inconclusive"
    rows = []
    pause_control = False
    if not _anchor_stable(original_image, image, region["bbox"]):
        reason = "player_anchor_unavailable_or_changed"
    elif not (pause_control := _pause_bars(crop)):
        # 控件隐藏时 OCR 无法形成播放证明，直接保留未知并交时序判断。
        reason = "playing_control_unavailable"
    else:
        try:
            rows = _ocr_rows(crop)
        except (RuntimeError, ValueError, OSError, ImportError):
            reason = "ocr_unavailable"
    positions, blockers = [], []
    for row in rows:
        if row.get("score", 0) < .9:
            continue
        text = row["text"].strip().lower()
        for pattern, result in ((r"\b(advertisement|advert|skip ad|sponsored)\b|广告", "ad"),
            (r"\b(playback error|failed to load|video unavailable)\b|播放失败|播放错误", "error"),
            (r"\b(loading|buffering)\b|加载中|缓冲中", "loading"),
            (r"\bpaused\b|已暂停", "paused"), (r"\bvideo ended\b|播放结束", "ended")):
            if re.search(pattern, text):
                blockers.append(result)
        box = row.get("bbox", [])
        if len(box) == 4 and box[1] >= h * .8:
            for match in _TIME.finditer(text):
                current, total = _seconds(match[1]), _seconds(match[2])
                if current is not None and total is not None and 0 <= current < total:
                    positions.append(current)
    if blockers:
        state = next(s for s in ("ad", "error", "paused", "ended", "loading") if s in blockers)
        reason = "explicit_player_blocker"
    elif len(positions) == 1 and pause_control:
        position, state, reason = positions[0], "playing", "visible_progress_and_pause_control"
    value = {"position_seconds": position, "state": state}
    # 诊断原件与缓存都来自本次像素；缓存命中前仍校验原图哈希与窗口。
    folder = Path(session_dir) / "video-playback-observer"
    folder.mkdir(exist_ok=True)
    path = _observation_path(key)
    if not path.exists():
        with path.open("x", encoding="utf-8") as stream:
            json.dump({"frame_sha256": frame["sha256"], "region": region, "rows": rows,
                       "observation": value, "reason": reason}, stream, ensure_ascii=False, allow_nan=False)
    _CACHE[key] = value
    while len(_CACHE) > 64:
        _CACHE.popitem(last=False)
    return {"capture_id": frame["capture_id"], **value}
