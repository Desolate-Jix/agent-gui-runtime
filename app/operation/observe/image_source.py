from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageStat

from app.core.screenshot import screenshot_service
from app.operation.observe.contracts import ObserveScreenTaskInput


def capture_visual_readiness(image_path: str | Path) -> dict[str, Any]:
    path = Path(image_path)
    with Image.open(path) as image:
        sample = image.convert("RGB")
        sample.thumbnail((160, 120))
        quantized = sample.quantize(colors=32)
        colors = quantized.getcolors(maxcolors=32) or []
        total_pixels = max(1, sample.width * sample.height)
        dominant_pixels = max(
            (count for count, _color in colors),
            default=total_pixels,
        )
        dominant_color_ratio = dominant_pixels / total_pixels
        color_bucket_count = len(colors)

        grayscale = sample.convert("L")
        margin_x = max(2, grayscale.width // 32)
        margin_y = max(2, grayscale.height // 32)
        core = grayscale.crop(
            (
                margin_x,
                margin_y,
                grayscale.width - margin_x,
                grayscale.height - margin_y,
            )
        )
        grid_size = 5
        informative_tile_count = 0
        for row in range(grid_size):
            for column in range(grid_size):
                tile = core.crop(
                    (
                        column * core.width // grid_size,
                        row * core.height // grid_size,
                        (column + 1) * core.width // grid_size,
                        (row + 1) * core.height // grid_size,
                    )
                )
                if ImageStat.Stat(tile).stddev[0] >= 8.0:
                    informative_tile_count += 1

    informative_tile_ratio = informative_tile_count / (grid_size * grid_size)
    ready = dominant_color_ratio < 0.985 and informative_tile_count >= 3
    return {
        "contract_version": "learning_capture_visual_readiness_v2",
        "ready": ready,
        "dominant_color_ratio": round(dominant_color_ratio, 6),
        "color_bucket_count": color_bucket_count,
        "informative_tile_count": informative_tile_count,
        "informative_tile_ratio": round(informative_tile_ratio, 6),
        "reason": (
            "visual_information_present"
            if ready
            else "low_information_startup_surface"
        ),
    }


def resolve_observe_image_source(
    task: ObserveScreenTaskInput,
    *,
    capture_window: Callable[..., dict[str, Any]] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    max_attempts: int = 4,
    retry_delay_seconds: float = 0.75,
) -> tuple[str, dict[str, Any] | None]:
    capture = capture_window or screenshot_service.capture_window
    if task.capture_live:
        live_capture = capture(
            save_image=True,
            purpose="observe_screen",
            name_hint=task.app_name or "observe_screen",
        )
        image_path = str(Path(str(live_capture["image_path"])).resolve())
    elif task.image_path:
        return task.image_path, None
    else:
        raise ValueError("Provide image_path or set capture_live=true")

    readiness_requested = bool(
        task.metadata.get("learning_studio_draft_capture") is True
        or task.metadata.get("require_capture_readiness") is True
    )
    if (
        task.agent_mode != "learn"
        or not readiness_requested
        or not Path(image_path).exists()
    ):
        return image_path, live_capture

    attempts: list[dict[str, Any]] = []
    capture_payload = dict(live_capture)
    for attempt_index in range(max_attempts):
        readiness = capture_visual_readiness(image_path)
        attempts.append(
            {
                "attempt": attempt_index + 1,
                "image_path": image_path,
                **readiness,
            }
        )
        if readiness["ready"] is True:
            capture_payload["image_path"] = image_path
            capture_payload["capture_readiness"] = {
                **readiness,
                "attempt_count": attempt_index + 1,
                "attempts": attempts,
            }
            return image_path, capture_payload
        if attempt_index + 1 < max_attempts:
            sleep(retry_delay_seconds)
            capture_payload = capture(
                save_image=True,
                purpose="observe_screen_ready_retry",
                name_hint=task.app_name or "learning_observe",
            )
            image_path = str(capture_payload.get("image_path") or "")
            if not image_path or not Path(image_path).exists():
                raise RuntimeError(
                    "Learning capture readiness retry did not create an image"
                )

    raise RuntimeError(
        "Learning capture stayed on a low-information startup surface after "
        f"{max_attempts} attempts"
    )
