from __future__ import annotations

import base64
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PIL import Image

from app.core.runtime_artifacts import build_review_overlay_path
from app.vision.grid_overlay import create_grid_overlay_image
from app.vision.prompting import build_region_analysis_prompt
from app.vision.schemas import ImageSize, VisionAnalyzeRequest, VisionAnalyzeResponse


@dataclass(frozen=True)
class _InferenceAttempt:
    tag: str
    max_edge: int | None
    compact_prompt: bool
    max_regions: int


class LocalVisionProvider:
    def __init__(self, endpoint: str | None = None, model_name: str | None = None, timeout_seconds: float = 30.0) -> None:
        self.endpoint = endpoint
        self.model_name = model_name or "local_stub"
        self.timeout_seconds = float(timeout_seconds)

    def analyze(self, req: VisionAnalyzeRequest) -> VisionAnalyzeResponse:
        image_path = Path(req.image_path)
        with Image.open(image_path) as image:
            original_image_size = ImageSize(width=image.width, height=image.height)
        notes: list[str] = []
        if not self.endpoint:
            notes.append("Local provider is currently running in stub mode.")
            return VisionAnalyzeResponse(
                provider="local",
                image_size=original_image_size,
                screen_summary=f"Local provider stub analyzed image: {image_path.name}",
                state_guess=req.state_hint,
                regions=[],
                targets=[],
                observers=[],
                notes=notes,
                raw_text=None,
                raw_response={
                    "provider": "local",
                    "contract_version": "vision_regions_v1",
                    "image_size": original_image_size.to_dict(),
                    "model_name": self.model_name,
                    "image_path": str(image_path),
                    "task": req.task,
                    "goal": req.goal,
                    "app_name": req.app_name,
                    "state_hint": req.state_hint,
                    "mode": "stub",
                },
            )

        raw_text = ""
        raw_response: dict[str, Any] | None = None
        parsed: dict[str, Any] | None = None
        attempt_records: list[dict[str, Any]] = []
        last_error: Exception | None = None

        for attempt in self._build_attempt_plan(original_image_size):
            attempt_record = {
                "tag": attempt.tag,
                "compact_prompt": attempt.compact_prompt,
                "max_regions": attempt.max_regions,
                "requested_max_edge": attempt.max_edge,
            }
            try:
                parsed, raw_text, raw_response, attempt_meta, attempt_notes = self._run_attempt(
                    image_path=image_path,
                    req=req,
                    original_image_size=original_image_size,
                    attempt=attempt,
                )
                attempt_record.update(attempt_meta)
                attempt_record["status"] = "success"
                attempt_records.append(attempt_record)
                notes.extend(attempt_notes)
                break
            except Exception as exc:
                attempt_record["status"] = "failed"
                attempt_record["error"] = str(exc)
                attempt_records.append(attempt_record)
                last_error = exc

        if parsed is None or raw_response is None:
            summary = f"local vision endpoint failed after {len(attempt_records)} attempt(s)"
            if last_error is not None:
                summary = f"{summary}: {last_error}"
            raise RuntimeError(summary) from last_error

        if len(attempt_records) > 1:
            notes.append(f"provider_retry_count={len(attempt_records) - 1}")

        parsed["provider"] = self.model_name or "local"
        parsed.setdefault("contract_version", "vision_regions_v1")
        parsed.setdefault("image_size", original_image_size.to_dict())
        parsed.setdefault("state_guess", req.state_hint)
        parsed.setdefault("regions", [])
        parsed.setdefault("targets", [])
        parsed.setdefault("observers", [])
        parsed.setdefault("notes", [])
        parsed["model_name"] = self.model_name
        from app.vision.normalizer import normalizer

        normalized = normalizer.normalize(parsed, "local", image_size=original_image_size.to_dict())
        normalized.raw_text = raw_text
        normalized.raw_response = {
            "model_json": parsed,
            "endpoint_response": raw_response,
            "attempts": attempt_records,
        }
        normalized.notes.extend([note for note in notes if note not in normalized.notes])
        return normalized

    def _call_openai_compatible_endpoint(self, image_path: Path, prompt: str) -> dict[str, Any]:
        payload = {
            "model": self.model_name,
            "temperature": 0.1,
            "max_tokens": 4096,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a GUI screenshot parser. Return valid JSON only.",
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": self._image_data_url(image_path)}},
                    ],
                },
            ],
        }
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            self._chat_completions_url(),
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"local vision endpoint returned HTTP {exc.code}: {details}") from exc
        except URLError as exc:
            raise RuntimeError(f"failed to reach local vision endpoint {self.endpoint}: {exc.reason}") from exc

    def _chat_completions_url(self) -> str:
        endpoint = str(self.endpoint or "").rstrip("/")
        if endpoint.endswith("/chat/completions"):
            return endpoint
        if endpoint.endswith("/v1"):
            return f"{endpoint}/chat/completions"
        return f"{endpoint}/v1/chat/completions"

    def _image_data_url(self, image_path: Path) -> str:
        suffix = image_path.suffix.lower()
        mime = "image/png"
        if suffix in {".jpg", ".jpeg"}:
            mime = "image/jpeg"
        elif suffix == ".webp":
            mime = "image/webp"
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{encoded}"

    def _extract_message_text(self, raw_response: dict[str, Any]) -> str:
        choices = raw_response.get("choices") or []
        if not choices:
            raise RuntimeError("local vision endpoint returned no choices")
        content = ((choices[0] or {}).get("message") or {}).get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            return "\n".join(parts).strip()
        raise RuntimeError("local vision endpoint returned unsupported message content")

    def _parse_json_object(self, text: str) -> dict[str, Any]:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`").strip()
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].strip()
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start < 0 or end <= start:
                raise RuntimeError("local vision endpoint did not return a JSON object")
            parsed = json.loads(cleaned[start : end + 1])
        if not isinstance(parsed, dict):
            raise RuntimeError("local vision endpoint JSON root must be an object")
        return parsed

    def _build_attempt_plan(self, image_size: ImageSize) -> list[_InferenceAttempt]:
        max_dim = max(image_size.width, image_size.height)
        attempts = [
            _InferenceAttempt(
                tag="default",
                max_edge=1280 if max_dim > 1280 else None,
                compact_prompt=False,
                max_regions=8,
            ),
            _InferenceAttempt(
                tag="compact_retry",
                max_edge=1024 if max_dim > 1024 else None,
                compact_prompt=True,
                max_regions=6,
            ),
        ]
        if max_dim > 1600:
            attempts.append(
                _InferenceAttempt(
                    tag="compact_retry_small",
                    max_edge=896,
                    compact_prompt=True,
                    max_regions=5,
                )
            )
        return attempts

    def _run_attempt(
        self,
        *,
        image_path: Path,
        req: VisionAnalyzeRequest,
        original_image_size: ImageSize,
        attempt: _InferenceAttempt,
    ) -> tuple[dict[str, Any], str, dict[str, Any], dict[str, Any], list[str]]:
        inference_path = image_path
        inference_size = original_image_size
        attempt_notes: list[str] = []
        temp_dir: tempfile.TemporaryDirectory[str] | None = None
        grid_overlay_path: Path | None = None
        grid_spacing = self._grid_overlay_spacing(req)
        if attempt.max_edge is not None and max(original_image_size.width, original_image_size.height) > attempt.max_edge:
            temp_dir = tempfile.TemporaryDirectory(prefix="vision-inference-")
            inference_path = Path(temp_dir.name) / f"{image_path.stem}__{attempt.max_edge}.png"
            inference_size = self._resize_image_for_inference(image_path, inference_path, attempt.max_edge)
            attempt_notes.append(
                "inference_scaled="
                f"{original_image_size.width}x{original_image_size.height}->{inference_size.width}x{inference_size.height}"
            )
        if grid_spacing is not None:
            if temp_dir is None:
                temp_dir = tempfile.TemporaryDirectory(prefix="vision-inference-")
            grid_temp_path = Path(temp_dir.name) / f"{inference_path.stem}__grid-{grid_spacing}.png"
            grid_overlay_path = build_review_overlay_path(
                name_hint=f"{req.app_name or image_path.stem}-grid-reference",
                suffix=f"grid-{grid_spacing}px",
            )
            create_grid_overlay_image(inference_path, grid_temp_path, spacing=grid_spacing)
            create_grid_overlay_image(inference_path, grid_overlay_path, spacing=grid_spacing)
            inference_path = grid_temp_path
            attempt_notes.append(f"grid_overlay_spacing={grid_spacing}px")
        if attempt.compact_prompt:
            attempt_notes.append("compact_prompt_mode=true")

        prompt = build_region_analysis_prompt(
            req,
            inference_size,
            compact=attempt.compact_prompt,
            max_regions=attempt.max_regions,
            grid_overlay_spacing=grid_spacing,
        )
        try:
            raw_response = self._call_openai_compatible_endpoint(inference_path, prompt)
            raw_text = self._extract_message_text(raw_response)
            parsed = self._parse_json_object(raw_text)
            parsed = self._remap_to_original_image(parsed, inference_size, original_image_size)
            attempt_meta = {
                "inference_image_size": inference_size.to_dict(),
                "original_image_size": original_image_size.to_dict(),
            }
            if grid_spacing is not None:
                attempt_meta["grid_overlay"] = {
                    "enabled": True,
                    "spacing": grid_spacing,
                    "artifact_path": str(grid_overlay_path.resolve()) if grid_overlay_path is not None else None,
                }
            if inference_size != original_image_size:
                attempt_meta["coordinate_remap"] = {
                    "from": inference_size.to_dict(),
                    "to": original_image_size.to_dict(),
                }
            return parsed, raw_text, raw_response, attempt_meta, attempt_notes
        finally:
            if temp_dir is not None:
                temp_dir.cleanup()

    def _grid_overlay_spacing(self, req: VisionAnalyzeRequest) -> int | None:
        metadata = req.metadata or {}
        raw = metadata.get("grid_overlay")
        if raw in (None, False):
            return None
        if raw is True:
            return 100
        if isinstance(raw, int):
            return max(20, int(raw))
        if isinstance(raw, dict):
            if not raw.get("enabled", True):
                return None
            spacing = raw.get("spacing", 100)
            try:
                return max(20, int(spacing))
            except Exception:
                return 100
        return None

    def _resize_image_for_inference(self, source_path: Path, target_path: Path, max_edge: int) -> ImageSize:
        with Image.open(source_path) as image:
            width, height = image.size
            current_max = max(width, height)
            if current_max <= max_edge:
                image.save(target_path)
                return ImageSize(width=width, height=height)
            scale = float(max_edge) / float(current_max)
            resized = image.resize(
                (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
                Image.Resampling.LANCZOS,
            )
            resized.save(target_path)
            return ImageSize(width=resized.width, height=resized.height)

    def _remap_to_original_image(
        self,
        parsed: dict[str, Any],
        inference_size: ImageSize,
        original_image_size: ImageSize,
    ) -> dict[str, Any]:
        if inference_size == original_image_size:
            parsed["image_size"] = original_image_size.to_dict()
            return parsed
        scale_x = float(original_image_size.width) / float(inference_size.width)
        scale_y = float(original_image_size.height) / float(inference_size.height)
        for collection_name in ("regions", "targets", "observers"):
            items = parsed.get(collection_name) or []
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                if isinstance(item.get("diagonal"), dict):
                    item["diagonal"] = self._scale_diagonal(
                        item["diagonal"],
                        scale_x=scale_x,
                        scale_y=scale_y,
                        max_width=original_image_size.width,
                        max_height=original_image_size.height,
                    )
                if isinstance(item.get("bbox"), dict):
                    item["bbox"] = self._scale_bbox(
                        item["bbox"],
                        scale_x=scale_x,
                        scale_y=scale_y,
                        max_width=original_image_size.width,
                        max_height=original_image_size.height,
                    )
        parsed["image_size"] = original_image_size.to_dict()
        return parsed

    def _scale_diagonal(
        self,
        diagonal: dict[str, Any],
        *,
        scale_x: float,
        scale_y: float,
        max_width: int,
        max_height: int,
    ) -> dict[str, int]:
        x1 = self._clamp_coordinate(diagonal.get("x1"), scale_x, max_width)
        y1 = self._clamp_coordinate(diagonal.get("y1"), scale_y, max_height)
        x2 = self._clamp_coordinate(diagonal.get("x2"), scale_x, max_width)
        y2 = self._clamp_coordinate(diagonal.get("y2"), scale_y, max_height)
        if x2 <= x1:
            x2 = min(max_width, x1 + 1)
        if y2 <= y1:
            y2 = min(max_height, y1 + 1)
        return {"x1": x1, "y1": y1, "x2": x2, "y2": y2}

    def _scale_bbox(
        self,
        bbox: dict[str, Any],
        *,
        scale_x: float,
        scale_y: float,
        max_width: int,
        max_height: int,
    ) -> dict[str, int]:
        x = self._clamp_coordinate(bbox.get("x"), scale_x, max_width)
        y = self._clamp_coordinate(bbox.get("y"), scale_y, max_height)
        w = max(1, int(round(float(bbox.get("w") or 0) * scale_x)))
        h = max(1, int(round(float(bbox.get("h") or 0) * scale_y)))
        if x + w > max_width:
            w = max(1, max_width - x)
        if y + h > max_height:
            h = max(1, max_height - y)
        return {"x": x, "y": y, "w": w, "h": h}

    def _clamp_coordinate(self, value: Any, scale: float, upper_bound: int) -> int:
        try:
            scaled = int(round(float(value) * scale))
        except Exception:
            scaled = 0
        return max(0, min(upper_bound, scaled))
