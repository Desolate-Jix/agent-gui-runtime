"""只在拥有当前截图的观察调用内收集原生字段命中证据。"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import logging
import time

from PIL import Image, ImageChops


_collector: ContextVar[Callable | None] = ContextVar("current_native_field_hit_collector", default=None)
_phase_clock = time.monotonic
_phase_wait = time.sleep


@contextmanager
def pinned_field_hit_collector(callback):
    """能力只随当前调用传播，不从请求元数据或保存的证明恢复。"""
    if callback is not None and not callable(callback):
        raise ValueError("field hit collector must be callable")
    token = _collector.set(callback)
    try:
        yield
    finally:
        _collector.reset(token)


def collect_current_field_hit(*, image_path, uia_snapshot, point):
    callback = _collector.get()
    if callback is None:
        return None
    return callback(image_path=image_path, uia_snapshot=uia_snapshot, point=point)


def _crop_rgb(image_bytes, size, bbox):
    with Image.open(BytesIO(image_bytes)) as image:
        if image.format != "PNG" or image.size != size:
            raise ValueError("field hit capture must be a matching PNG")
        x, y, w, h = (bbox[key] for key in ("x", "y", "w", "h"))
        if (any(type(value) is not int for value in (x, y, w, h))
                or min(x, y) < 0 or min(w, h) <= 0 or x + w > size[0] or y + h > size[1]):
            raise ValueError("field hit bbox is outside the source capture")
        return image.convert("RGB").crop((x, y, x + w, y + h))


def _caret_phase_difference(source, current):
    """极窄连续竖线只允许等待相位，不允许将不同像素作为匹配结果。"""
    diff = ImageChops.difference(source, current)
    box = diff.getbbox()
    if box is None:
        return False
    width, height = box[2] - box[0], box[3] - box[1]
    if not (1 <= width <= 2 and 8 <= height <= min(24, source.height - 2)):
        return False
    pixels = diff.crop(box).tobytes()
    changed = sum(pixels[index:index + 3] != b"\x00\x00\x00" for index in range(0, len(pixels), 3))
    return 8 <= changed <= 48 and changed == width * height


def make_field_hit_collector(owner, *, image_path, image_bytes, uia_snapshot, capture_id,
                             capture_started_ns, captured_at_ns, application_fact,
                             target_window_handle, target_process_id, window_rect):
    """仅固定输入，实际启用能力时才校验；普通识别不额外要求命中证明。"""
    arguments = deepcopy(dict(image_path=image_path, image_bytes=image_bytes, uia_snapshot=uia_snapshot,
        capture_id=capture_id, capture_started_ns=capture_started_ns, captured_at_ns=captured_at_ns,
        application_fact=application_fact, target_window_handle=target_window_handle,
        target_process_id=target_process_id, window_rect=window_rect))
    bound_collector = None

    def collect(*, image_path, uia_snapshot, point):
        nonlocal bound_collector
        if _collector.get() is not collect:
            raise ValueError("field hit collector is outside its owned observation scope")
        if bound_collector is None:
            bound_collector = _make_bound_collector(owner, **arguments)
        return bound_collector(image_path=image_path, uia_snapshot=uia_snapshot, point=point)

    return collect


def _make_bound_collector(owner, *, image_path, image_bytes, uia_snapshot, capture_id,
                          capture_started_ns, captured_at_ns, application_fact,
                          target_window_handle, target_process_id, window_rect):
    """固定原始观察，前后被动截图与双次原生命中共同证明当前字段。"""
    from .fresh_learning_observation import _bound_rect, _canonical_bytes, _require_uia_rect
    from .fresh_text_field import _field_uia_identity
    from .live_runtime_composition import _bound_identity, _validated_saved_capture, _validated_uia_snapshot
    from .windows_text_field_reader import WindowsTextFieldReader

    if (not isinstance(window_rect, Mapping) or set(window_rect) != {"x", "y", "width", "height"}
            or any(type(value) is not int for value in window_rect.values())
            or min(window_rect["width"], window_rect["height"]) <= 0
            or type(target_window_handle) is not int or target_window_handle <= 0
            or type(target_process_id) is not int or target_process_id <= 0
            or not isinstance(capture_id, str) or not capture_id
            or type(capture_started_ns) is not int or type(captured_at_ns) is not int
            or not 0 < capture_started_ns <= captured_at_ns <= time.perf_counter_ns()
            or not isinstance(application_fact, Mapping)):
        raise ValueError("field hit source binding is invalid")
    fact = deepcopy(dict(application_fact))
    created = fact.get("process_create_time")
    if type(created) not in (int, float) or not 0 < created < float("inf"):
        raise ValueError("field hit native process identity is unavailable")
    rect = dict(window_rect)
    size = rect["width"], rect["height"]
    identity = target_window_handle, target_process_id, size
    snapshot = _validated_uia_snapshot(uia_snapshot, expected_identity=identity)
    _require_uia_rect(snapshot, rect)
    if snapshot.get("scan_complete") is not True or snapshot.get("truncated") is not False:
        raise ValueError("field hit requires a complete source UIA snapshot")
    source_path = Path(image_path).resolve()
    source_bytes = bytes(image_bytes)
    source_sha = sha256(source_bytes).hexdigest()
    uia_sha = sha256(_canonical_bytes(snapshot)).hexdigest()

    def verify_binding():
        bound = owner._window_manager.get_bound_window()
        if (_bound_identity(bound, target_window_handle=target_window_handle) != identity
                or _bound_rect(bound) != rect
                or owner._read_application_fact(target_window_handle, target_process_id) != fact):
            raise ValueError("field hit native owner binding changed")
        if sha256(source_path.read_bytes()).hexdigest() != source_sha:
            raise ValueError("field hit original capture changed")

    def fresh_pixels(bbox, seen_paths):
        verify_binding()
        result = owner._screenshot_service.capture_window(save_image=True, focus_window=False,
            purpose="learning-field-hit-proof")
        verify_binding()
        path, payload, _ = _validated_saved_capture(result, expected_size=size)
        if path == source_path or path in seen_paths:
            raise ValueError("field hit fresh capture reused an evidence path")
        seen_paths.add(path)
        rgb = _crop_rgb(payload, size, bbox)
        return path, sha256(rgb.tobytes()).hexdigest(), rgb

    def matching_pixels(bbox, source_crop, source_rgb, phase, seen_paths):
        started = _phase_clock()
        deadline = started + 1.500
        captures = 0
        outcome = "rejected"
        try:
            for attempt in range(4):
                if attempt and _phase_clock() >= deadline:
                    break
                path, digest, crop = fresh_pixels(bbox, seen_paths)
                captures += 1
                if digest == source_rgb:
                    if attempt and _phase_clock() > deadline:
                        break
                    outcome = "exact"
                    return path, digest
                if not _caret_phase_difference(source_crop, crop):
                    raise ValueError(f"field hit source field pixels changed {phase} native hit")
                remaining = deadline - _phase_clock()
                if attempt == 3 or remaining <= 0:
                    break
                _phase_wait(min(0.150, remaining))
            raise ValueError(f"field hit caret phase did not return to exact source {phase} native hit")
        finally:
            # 只记录时长与次数，不增加持久证明字段或泄漏图像内容。
            logging.getLogger(__name__).info("field_hit_pixel_phase phase=%s captures=%d elapsed_ms=%.3f outcome=%s",
                phase, captures, (_phase_clock() - started) * 1000, outcome)

    def collect(*, image_path, uia_snapshot, point):
        if (Path(image_path).resolve() != source_path
                or sha256(_canonical_bytes(uia_snapshot)).hexdigest() != uia_sha
                or not isinstance(point, Mapping) or set(point) != {"x", "y"}
                or any(type(value) is not int for value in point.values())):
            raise ValueError("field hit request differs from the owned source")
        verify_binding()
        field = _field_uia_identity(snapshot, point)
        bbox = field["bbox"]
        source_crop = _crop_rgb(source_bytes, size, bbox)
        source_rgb = sha256(source_crop.tobytes()).hexdigest()
        matches = [control for control in snapshot["controls"] if isinstance(control, Mapping)
            and tuple(control.get("runtime_id") or ()) == field["runtime_id"]]
        if len(matches) != 1 or not isinstance(matches[0].get("control_id"), str) or not matches[0]["control_id"]:
            raise ValueError("field hit target identity is unavailable")
        field_id = matches[0]["control_id"]
        seen_paths = set()
        before_path, before_rgb = matching_pixels(bbox, source_crop, source_rgb, "before", seen_paths)
        if owner._text_field_reader is None:
            owner._text_field_reader = WindowsTextFieldReader(window_manager=owner._window_manager,
                native_identity_reader=owner._native_identity_reader)
        before_hit_ns = time.perf_counter_ns()
        hit = owner._text_field_reader.observe_field_hit(target_field_id=field_id,
            capture_id=capture_id, target_window_handle=target_window_handle,
            target_process_id=target_process_id, process_create_time=created,
            window_rect=tuple(rect[key] for key in ("x", "y", "width", "height")),
            target_bbox=tuple(bbox[key] for key in ("x", "y", "w", "h")),
            click_point=(point["x"], point["y"]), expected_runtime_id=field["runtime_id"],
            expected_control_type=field["control_type"])
        after_hit_ns = time.perf_counter_ns()
        verify_binding()
        expected_target = {"window_handle": target_window_handle, "process_id": target_process_id,
            "process_create_time": created, "window_rect": [rect[key] for key in ("x", "y", "width", "height")]}
        if (not isinstance(hit, Mapping) or hit.get("contract_version") != "windows_field_hit_observation_v1"
                or hit.get("provider") != "windows_uia.from_point" or hit.get("capture_id") != capture_id
                or hit.get("target_field_id") != field_id or hit.get("target") != expected_target
                or hit.get("runtime_id") != list(field["runtime_id"])
                or not isinstance(hit.get("control_type"), str)
                or hit["control_type"].casefold() != field["control_type"].replace(" ", "")
                or hit.get("bbox") != bbox
                or hit.get("point") != dict(point) or type(hit.get("observed_at_ns")) is not int
                or not before_hit_ns <= hit["observed_at_ns"] <= after_hit_ns
                or type(hit.get("sample_count")) is not int or hit["sample_count"] != 2
                or hit.get("artifact_is_authorization") is not False or hit.get("action_executed") is not False):
            raise ValueError("field hit native result differs from the owned source")
        after_path, after_rgb = matching_pixels(bbox, source_crop, source_rgb, "after", seen_paths)
        return {"contract_version": "current_field_hit_binding_v1", "capture_id": capture_id,
            "screenshot_sha256": source_sha, "uia_snapshot_sha256": uia_sha,
            "capture_started_ns": capture_started_ns, "captured_at_ns": captured_at_ns,
            "before_hit_ns": before_hit_ns, "after_hit_ns": after_hit_ns,
            "target": expected_target, "hit": deepcopy(dict(hit)),
            "pixels": {"bbox": dict(bbox), "source_rgb_sha256": source_rgb,
                "before_rgb_sha256": before_rgb, "after_rgb_sha256": after_rgb}}

    return collect
