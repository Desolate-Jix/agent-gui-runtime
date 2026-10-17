"""观察已改变且短暂稳定的画面；只决定采图时机，不核准动作或任务结果。"""
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from time import perf_counter

from PIL import Image, ImageChops


def _pixels(frame, geometry=None):
    try:
        data = Path(frame["image_path"]).read_bytes()
        size, rect = frame["window_size"], frame["window_rect"]
        if sha256(data).hexdigest() != frame["sha256"]:
            raise ValueError("hash")
        current_geometry = (size["width"], size["height"], tuple(rect))
        if geometry is not None and current_geometry != geometry:
            raise ValueError("geometry")
        with Image.open(BytesIO(data)) as source:
            if source.size != current_geometry[:2] or source.format != "PNG":
                raise ValueError("image")
            image = source.convert("RGB")
        return image, sha256(image.tobytes()).hexdigest(), current_geometry
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError("adaptive_observation_capture_invalid") from error


def _changed_fraction(before, current):
    channels = ImageChops.difference(before, current).split()
    maximum = ImageChops.lighter(ImageChops.lighter(channels[0], channels[1]), channels[2])
    histogram = maximum.histogram()
    return sum(histogram[9:]) / (current.width * current.height)


def observe_after_transition(capture, *, before, timeout_ms, cancel, clock=perf_counter, cancelled=None):
    """在原两秒上限内只读采样；无变化或连续变化时保留完整宽限。"""
    if type(timeout_ms) is not int or not 400 <= timeout_ms <= 2000:
        raise ValueError("adaptive_observation_budget_invalid")
    started = clock()
    deadline = started + timeout_ms / 1000
    from .task_plan_observation import CLOCK_ID
    started_ns = int(started * 1_000_000_000)
    original, _digest, geometry = _pixels(before)
    samples = []
    previous = None
    stable_since = None
    stable_samples = 0
    def stopped():
        return cancel.is_set() or cancelled is not None and cancelled()
    while True:
        if stopped():
            raise ValueError("adaptive_observation_cancelled")
        remaining = max(0, deadline - clock())
        if remaining and cancel.wait(min(.1, remaining)):
            raise ValueError("adaptive_observation_cancelled")
        if stopped():
            raise ValueError("adaptive_observation_cancelled")
        after = capture()
        pixels, digest, _geometry = _pixels(after, geometry)
        observed = clock()
        fraction = _changed_fraction(original, pixels)
        substantial = fraction >= max(128 / (pixels.width * pixels.height), .0005)
        if substantial and digest == previous:
            stable_samples += 1
        elif substantial:
            stable_since = observed
            stable_samples = 1
        else:
            stable_since = None
            stable_samples = 0
        previous = digest
        finished = clock()
        elapsed = (finished - started) * 1000
        samples.append({"elapsed_ms": round(elapsed, 3), "image_path": after["image_path"],
                        "sha256": after["sha256"], "changed_fraction": round(fraction, 6),
                        "changed_pixels": round(fraction * pixels.width * pixels.height),
                        "substantial_change": substantial, "stable_samples": stable_samples})
        if stopped():
            raise ValueError("adaptive_observation_cancelled")
        # 不以少量光标像素启动快路径；稳定必须来自至少三个不同采样时刻。
        stable = (stable_samples >= 3 and stable_since is not None
                  and observed - stable_since >= .2 and elapsed >= 400)
        if stable or finished >= deadline:
            return after, {"schema": "adaptive_observation.v1", "budget_ms": timeout_ms,
                           "clock_id": CLOCK_ID, "started_ns": started_ns,
                           "deadline_ns": started_ns + timeout_ms * 1_000_000,
                           "elapsed_ms": elapsed, "early": bool(stable and finished < deadline),
                           "reason": "changed_then_stable" if stable else "budget_exhausted",
                           "samples": samples, "readiness": "unassessed", "effect_verified": False,
                           "authorizes_action": False, "automatic_retry_allowed": False}
