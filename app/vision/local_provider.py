from __future__ import annotations

import base64
import json
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PIL import Image

from app.core.runtime_artifacts import build_review_overlay_path
from app.vision.grid_overlay import create_grid_overlay_image
from app.vision.ocr_anchors import (
    DEFAULT_PROMPT_ANCHOR_LIMIT,
    DEFAULT_PROMPT_FOCUS_NEIGHBOR_LIMIT,
    DEFAULT_PROMPT_TEXT_MATCH_THRESHOLD,
    build_prompt_anchor_projection,
    scale_ocr_anchor_payload,
)
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
        self._model_loading_retries = 0

    def analyze(self, req: VisionAnalyzeRequest) -> VisionAnalyzeResponse:
        self._model_loading_retries = 0
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
        last_raw_text = ""

        for attempt in self._build_attempt_plan(original_image_size, task=req.task):
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
                diagnostics = getattr(exc, "diagnostics", None)
                if isinstance(diagnostics, dict):
                    attempt_record.update(diagnostics)
                    diagnostic_io = diagnostics.get("model_io")
                    if isinstance(diagnostic_io, dict) and isinstance(diagnostic_io.get("raw_text"), str):
                        last_raw_text = diagnostic_io["raw_text"]
                if raw_text:
                    last_raw_text = raw_text
                    attempt_record["raw_text_preview"] = self._raw_text_preview(raw_text)
                attempt_records.append(attempt_record)
                last_error = exc

        if parsed is None or raw_response is None:
            summary = f"local vision endpoint failed after {len(attempt_records)} attempt(s)"
            if last_error is not None:
                summary = f"{summary}: {last_error}"
            if last_raw_text:
                summary = f"{summary}; raw_text_preview={self._raw_text_preview(last_raw_text)}"
            final_error = RuntimeError(summary)
            final_error.diagnostics = {
                "contract_version": "model_io_trace_v1",
                "status": "failed",
                "provider": "local",
                "model_name": self.model_name,
                "image_path": str(image_path),
                "attempt_count": len(attempt_records),
                "attempts": attempt_records,
            }
            raise final_error from last_error

        if len(attempt_records) > 1:
            notes.append(f"provider_retry_count={len(attempt_records) - 1}")
        if self._model_loading_retries:
            notes.append(f"model_loading_wait_retries={self._model_loading_retries}")

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
            "contract_version": "provider_model_trace_v1",
            "provider": "local",
            "model_name": self.model_name,
            "image_path": str(image_path),
            "raw_text": raw_text,
            "model_json": parsed,
            "endpoint_response": raw_response,
            "attempts": attempt_records,
        }
        normalized.notes.extend([note for note in notes if note not in normalized.notes])
        return normalized

    def _call_openai_compatible_endpoint(self, image_path: Path, prompt: str, *, max_tokens: int = 2048) -> dict[str, Any]:
        payload = {
            "model": self.model_name,
            "temperature": 0.1,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a GUI screenshot parser. Return one valid JSON object only. "
                        "Use double-quoted keys and string values, put commas between every field and array item, "
                        "escape inner quotes and newlines inside strings, and never use trailing commas."
                    ),
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
        loading_deadline = time.monotonic() + self.timeout_seconds
        while True:
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
                if self._model_is_loading(exc.code, details) and time.monotonic() < loading_deadline:
                    self._model_loading_retries += 1
                    time.sleep(min(1.0, max(0.0, loading_deadline - time.monotonic())))
                    continue
                raise RuntimeError(f"local vision endpoint returned HTTP {exc.code}: {details}") from exc
            except URLError as exc:
                raise RuntimeError(f"failed to reach local vision endpoint {self.endpoint}: {exc.reason}") from exc

    def _model_is_loading(self, status_code: int, details: str) -> bool:
        return status_code == 503 and "loading model" in details.casefold()

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

    def _raw_text_preview(self, text: str, *, limit: int = 300) -> str:
        compact = " ".join(str(text or "").split())
        if len(compact) <= limit:
            return compact
        return compact[:limit] + "..."

    def _parse_json_object(self, text: str) -> dict[str, Any]:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`").strip()
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].strip()
        parse_error: json.JSONDecodeError | None = None
        for candidate in self._json_object_candidates(cleaned):
            for repaired, notes in self._json_repair_candidates(candidate):
                try:
                    parsed = json.loads(repaired)
                    for note in notes:
                        self._append_parse_note(parsed, note)
                    break
                except json.JSONDecodeError as exc:
                    parse_error = exc
            else:
                continue
            break
        else:
            if parse_error is None:
                raise RuntimeError("local vision endpoint did not return a JSON object")
            raise parse_error
        if not isinstance(parsed, dict):
            raise RuntimeError("local vision endpoint JSON root must be an object")
        return parsed

    def _json_object_candidates(self, text: str) -> list[str]:
        candidates = [text]
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            extracted = text[start : end + 1]
            if extracted != text:
                candidates.append(extracted)
        return candidates

    def _json_repair_candidates(self, text: str) -> list[tuple[str, list[str]]]:
        variants: list[tuple[str, list[str]]] = [(text, [])]
        repair_steps = [
            (self._remove_trailing_commas, "json_repair=removed_trailing_commas"),
            (self._escape_raw_newlines_in_strings, "json_repair=escaped_raw_string_newlines"),
            (self._escape_inner_string_quotes, "json_repair=escaped_inner_string_quotes"),
            (self._insert_missing_commas_before_keys, "json_repair=inserted_missing_commas_before_keys"),
            (self._close_truncated_regions_payload, "json_repair=closed_truncated_regions_payload"),
        ]
        for repair_fn, note in repair_steps:
            snapshot = list(variants)
            for candidate, notes in snapshot:
                repaired = repair_fn(candidate)
                if repaired != candidate:
                    variants.append((repaired, [*notes, note]))
        combined = self._insert_missing_commas_before_keys(
            self._escape_inner_string_quotes(
                self._escape_raw_newlines_in_strings(
                    self._remove_trailing_commas(text)
                )
            )
        )
        if combined != text:
            variants.append(
                (
                    combined,
                    [
                        "json_repair=combined_structural_repairs",
                    ],
                )
            )
        deduped: list[tuple[str, list[str]]] = []
        seen: set[str] = set()
        for candidate, notes in variants:
            if candidate in seen:
                continue
            seen.add(candidate)
            deduped.append((candidate, notes))
        return deduped

    def _remove_trailing_commas(self, text: str) -> str:
        return re.sub(r",(\s*[}\]])", r"\1", text)

    def _insert_missing_commas_before_keys(self, text: str) -> str:
        # Repair model outputs like: `"screen_summary":"x"\n"state_guess":"y"`.
        return re.sub(
            r'([}\]"0-9eE]|true|false|null)(\s*\n\s*)"([A-Za-z_][A-Za-z0-9_]*)"\s*:',
            r'\1,\2"\3":',
            text,
        )

    def _close_truncated_regions_payload(self, text: str) -> str:
        if '"regions"' not in text or '"targets"' in text and '"observers"' in text and text.rstrip().endswith("}"):
            return text
        regions_key = text.find('"regions"')
        array_start = text.find("[", regions_key)
        if array_start < 0:
            return text
        last_item_end = self._last_complete_array_item_end(text, array_start)
        if last_item_end is None:
            return text
        prefix = text[: last_item_end + 1].rstrip()
        prefix = prefix.rstrip(",")
        return f'{prefix}\n  ],\n  "targets": [],\n  "observers": [],\n  "notes": ["json_repair=truncated_regions_payload"]\n}}'

    def _last_complete_array_item_end(self, text: str, array_start: int) -> int | None:
        stack: list[str] = ["["]
        in_string = False
        escape = False
        last_item_end: int | None = None
        index = array_start + 1
        while index < len(text):
            char = text[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                index += 1
                continue
            if char == '"':
                in_string = True
            elif char in "[{":
                stack.append(char)
            elif char in "]}":
                if not stack:
                    return last_item_end
                opener = stack[-1]
                if (opener, char) not in {("[", "]"), ("{", "}")}:
                    return last_item_end
                stack.pop()
                if char == "}" and stack == ["["]:
                    last_item_end = index
                if not stack:
                    return last_item_end
            index += 1
        return last_item_end

    def _escape_raw_newlines_in_strings(self, text: str) -> str:
        output: list[str] = []
        in_string = False
        escape = False
        for char in text:
            if not in_string:
                output.append(char)
                if char == '"':
                    in_string = True
                    escape = False
                continue
            if escape:
                output.append(char)
                escape = False
                continue
            if char == "\\":
                output.append(char)
                escape = True
                continue
            if char == '"':
                output.append(char)
                in_string = False
                continue
            if char == "\n":
                output.append("\\n")
                continue
            if char == "\r":
                output.append("\\r")
                continue
            if char == "\t":
                output.append("\\t")
                continue
            output.append(char)
        return "".join(output)

    def _escape_inner_string_quotes(self, text: str) -> str:
        output: list[str] = []
        in_string = False
        escape = False
        for index, char in enumerate(text):
            if not in_string:
                output.append(char)
                if char == '"':
                    in_string = True
                    escape = False
                continue

            if escape:
                output.append(char)
                escape = False
                continue
            if char == "\\":
                output.append(char)
                escape = True
                continue
            if char != '"':
                output.append(char)
                continue

            next_char = self._next_non_space(text, index + 1)
            if next_char is None or next_char in {":", ",", "}", "]"}:
                output.append(char)
                in_string = False
                continue
            output.append('\\"')
        return "".join(output)

    def _next_non_space(self, text: str, start: int) -> str | None:
        for char in text[start:]:
            if not char.isspace():
                return char
        return None

    def _append_parse_note(self, parsed: Any, note: str) -> None:
        if not isinstance(parsed, dict):
            return
        notes = parsed.get("notes")
        if isinstance(notes, list):
            notes.append(note)
        elif notes:
            parsed["notes"] = [str(notes), note]
        else:
            parsed["notes"] = [note]

    def _build_attempt_plan(self, image_size: ImageSize, *, task: str | None = None) -> list[_InferenceAttempt]:
        max_dim = max(image_size.width, image_size.height)
        if task == "observe_screen":
            return [
                _InferenceAttempt(
                    tag="fast_observation",
                    max_edge=1280 if max_dim > 1280 else None,
                    compact_prompt=True,
                    max_regions=12,
                ),
                _InferenceAttempt(
                    tag="fast_observation_retry",
                    max_edge=1024 if max_dim > 1024 else None,
                    compact_prompt=True,
                    max_regions=8,
                ),
            ]
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

        prompt_req = self._request_for_inference_prompt(req, original_image_size=original_image_size, inference_size=inference_size)
        prompt = build_region_analysis_prompt(
            prompt_req,
            inference_size,
            compact=attempt.compact_prompt,
            max_regions=attempt.max_regions,
            grid_overlay_spacing=grid_spacing,
        )
        try:
            max_tokens = self._max_output_tokens(req)
            raw_response = self._call_openai_compatible_endpoint(
                inference_path,
                prompt,
                max_tokens=max_tokens,
            )
            raw_text = self._extract_message_text(raw_response)
            try:
                parsed_model_json = self._parse_json_object(raw_text)
            except Exception as exc:
                error = RuntimeError(f"{exc}; raw_text_preview={self._raw_text_preview(raw_text)}")
                error.diagnostics = {
                    "raw_text_preview": self._raw_text_preview(raw_text),
                    "model_io": self._model_io_attempt_payload(
                        req=req,
                        prompt=prompt,
                        image_path=image_path,
                        inference_path=inference_path,
                        inference_size=inference_size,
                        original_image_size=original_image_size,
                        max_tokens=max_tokens,
                        raw_text=raw_text,
                        raw_response=raw_response,
                        parsed_model_json=None,
                        runtime_normalized_json=None,
                        parse_status="failed",
                        parse_error=str(exc),
                        attempt=attempt,
                    ),
                }
                raise error from exc
            parsed = self._remap_to_original_image(parsed_model_json, inference_size, original_image_size)
            attempt_meta = {
                "inference_image_size": inference_size.to_dict(),
                "original_image_size": original_image_size.to_dict(),
                "model_io": self._model_io_attempt_payload(
                    req=req,
                    prompt=prompt,
                    image_path=image_path,
                    inference_path=inference_path,
                    inference_size=inference_size,
                    original_image_size=original_image_size,
                    max_tokens=max_tokens,
                    raw_text=raw_text,
                    raw_response=raw_response,
                    parsed_model_json=parsed_model_json,
                    runtime_normalized_json=parsed,
                    parse_status="success",
                    parse_error=None,
                    attempt=attempt,
                ),
            }
            if grid_spacing is not None:
                attempt_meta["grid_overlay"] = {
                    "enabled": True,
                    "spacing": grid_spacing,
                    "artifact_path": str(grid_overlay_path.resolve()) if grid_overlay_path is not None else None,
                }
            if isinstance(prompt_req.metadata.get("ocr_anchors"), dict):
                prompt_projection = build_prompt_anchor_projection(
                    prompt_req.metadata["ocr_anchors"],
                    max_anchors=int(prompt_req.metadata["ocr_anchors"].get("prompt_max_anchors") or DEFAULT_PROMPT_ANCHOR_LIMIT),
                    text_match_threshold=float(
                        prompt_req.metadata["ocr_anchors"].get("prompt_text_match_threshold") or DEFAULT_PROMPT_TEXT_MATCH_THRESHOLD
                    ),
                    focus_neighbor_limit=int(
                        prompt_req.metadata["ocr_anchors"].get("prompt_focus_neighbor_limit", DEFAULT_PROMPT_FOCUS_NEIGHBOR_LIMIT)
                    ),
                )
                attempt_meta["ocr_anchors"] = {
                    "enabled": True,
                    "coordinate_space": prompt_req.metadata["ocr_anchors"].get("coordinate_space"),
                    "anchor_count": int(prompt_req.metadata["ocr_anchors"].get("anchor_count") or 0),
                    "prompt_profile": str((prompt_projection or {}).get("profile") or "relation_matrix_compact"),
                    "prompt_anchor_count": int((prompt_projection or {}).get("anchor_count") or 0),
                    "prompt_text_anchor_count": int((prompt_projection or {}).get("text_anchor_count") or 0),
                    "prompt_goal_match_count": int((prompt_projection or {}).get("goal_match_count") or 0),
                    "prompt_focus_relation_count": int((prompt_projection or {}).get("focus_relation_count") or 0),
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

    def _model_io_attempt_payload(
        self,
        *,
        req: VisionAnalyzeRequest,
        prompt: str,
        image_path: Path,
        inference_path: Path,
        inference_size: ImageSize,
        original_image_size: ImageSize,
        max_tokens: int,
        raw_text: str,
        raw_response: dict[str, Any] | None,
        parsed_model_json: dict[str, Any] | None,
        runtime_normalized_json: dict[str, Any] | None,
        parse_status: str,
        parse_error: str | None,
        attempt: _InferenceAttempt,
    ) -> dict[str, Any]:
        return {
            "contract_version": "model_io_attempt_v1",
            "status": parse_status,
            "provider": "local",
            "model_name": self.model_name,
            "endpoint": self._chat_completions_url(),
            "task": req.task,
            "app_name": req.app_name,
            "goal": req.goal,
            "state_hint": req.state_hint,
            "provider_mode": req.provider_mode,
            "attempt": {
                "tag": attempt.tag,
                "compact_prompt": attempt.compact_prompt,
                "max_regions": attempt.max_regions,
                "requested_max_edge": attempt.max_edge,
            },
            "input": {
                "image_path": str(image_path),
                "inference_image_path": str(inference_path),
                "original_image_size": original_image_size.to_dict(),
                "inference_image_size": inference_size.to_dict(),
                "max_tokens": max_tokens,
                "prompt": prompt,
            },
            "output": {
                "raw_text": raw_text,
                "raw_response": raw_response,
                "parsed_model_json": parsed_model_json,
                "runtime_normalized_json": runtime_normalized_json,
                "parse_error": parse_error,
            },
            "raw_text": raw_text,
            "raw_text_preview": self._raw_text_preview(raw_text),
            "raw_response": raw_response,
            "parsed_model_json": parsed_model_json,
            "runtime_normalized_json": runtime_normalized_json,
            "parse_error": parse_error,
        }

    def _max_output_tokens(self, req: VisionAnalyzeRequest) -> int:
        metadata = req.metadata or {}
        configured = metadata.get("max_output_tokens")
        if configured is not None:
            try:
                return max(256, min(4096, int(configured)))
            except (TypeError, ValueError):
                pass
        return 2048 if req.task == "observe_screen" else 2048

    def _request_for_inference_prompt(
        self,
        req: VisionAnalyzeRequest,
        *,
        original_image_size: ImageSize,
        inference_size: ImageSize,
    ) -> VisionAnalyzeRequest:
        metadata = dict(req.metadata or {})
        anchor_payload = metadata.get("ocr_anchors")
        if isinstance(anchor_payload, dict):
            scaled = scale_ocr_anchor_payload(
                anchor_payload,
                from_size=original_image_size,
                to_size=inference_size,
                coordinate_space="inference_image",
            )
            if scaled is not None:
                metadata["ocr_anchors"] = scaled
        return VisionAnalyzeRequest(
            image_path=req.image_path,
            task=req.task,
            app_name=req.app_name,
            goal=req.goal,
            state_hint=req.state_hint,
            provider_mode=req.provider_mode,
            metadata=metadata,
        )

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
        recovered_count = self._recover_normalized_1000_items(parsed, inference_size)
        if recovered_count:
            notes = parsed.setdefault("notes", [])
            if isinstance(notes, list):
                notes.append(f"coordinate_space_recovered=normalized_1000;items={recovered_count}")
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

    def _recover_normalized_1000_items(self, parsed: dict[str, Any], image_size: ImageSize) -> int:
        recovered_count = 0
        for collection_name in ("regions", "targets", "observers"):
            items = parsed.get(collection_name) or []
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                diagonal = item.get("diagonal")
                if isinstance(diagonal, dict) and self._diagonal_is_normalized_1000(diagonal, image_size):
                    item["diagonal"] = self._scale_diagonal(
                        diagonal,
                        scale_x=float(image_size.width) / 1000.0,
                        scale_y=float(image_size.height) / 1000.0,
                        max_width=image_size.width,
                        max_height=image_size.height,
                    )
                    recovered_count += 1
                bbox = item.get("bbox")
                if isinstance(bbox, dict) and self._bbox_is_normalized_1000(bbox, image_size):
                    item["bbox"] = self._scale_bbox(
                        bbox,
                        scale_x=float(image_size.width) / 1000.0,
                        scale_y=float(image_size.height) / 1000.0,
                        max_width=image_size.width,
                        max_height=image_size.height,
                    )
                    recovered_count += 1
        return recovered_count

    def _diagonal_is_normalized_1000(self, diagonal: dict[str, Any], image_size: ImageSize) -> bool:
        values = self._float_coordinates(diagonal, ("x1", "y1", "x2", "y2"))
        if values is None:
            return False
        x1, y1, x2, y2 = values
        exceeds_pixel_bounds = max(x1, x2) > image_size.width or max(y1, y2) > image_size.height
        within_normalized_bounds = all(0.0 <= value <= 1000.0 for value in values)
        return exceeds_pixel_bounds and within_normalized_bounds

    def _bbox_is_normalized_1000(self, bbox: dict[str, Any], image_size: ImageSize) -> bool:
        values = self._float_coordinates(bbox, ("x", "y", "w", "h"))
        if values is None:
            return False
        x, y, w, h = values
        exceeds_pixel_bounds = x + w > image_size.width or y + h > image_size.height
        within_normalized_bounds = all(0.0 <= value <= 1000.0 for value in values)
        return exceeds_pixel_bounds and within_normalized_bounds

    def _float_coordinates(self, values: dict[str, Any], keys: tuple[str, ...]) -> tuple[float, ...] | None:
        try:
            return tuple(float(values[key]) for key in keys)
        except (KeyError, TypeError, ValueError):
            return None

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
