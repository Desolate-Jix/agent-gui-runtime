from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


MODEL: Any = None
PROCESSOR: Any = None
MODEL_NAME = "inclusionAI/VISTA-4B"
MAX_NEW_TOKENS = 32
GENERATE_LOCK = threading.Lock()
ACTIVE_REQUEST: dict[str, Any] | None = None


def _load_image(url: str):
    from PIL import Image

    if url.startswith("data:"):
        _, payload = url.split(",", 1)
        return Image.open(io.BytesIO(base64.b64decode(payload))).convert("RGB")
    if url.startswith("http://") or url.startswith("https://"):
        with urllib.request.urlopen(url, timeout=30) as response:
            return Image.open(io.BytesIO(response.read())).convert("RGB")
    return Image.open(url).convert("RGB")


def _message_text_and_image(messages: list[dict[str, Any]]) -> tuple[str, Any | None]:
    text_parts: list[str] = []
    image = None
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            text_parts.append(content)
            continue
        if not isinstance(content, list):
            continue
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" and isinstance(item.get("text"), str):
                text_parts.append(item["text"])
            elif item.get("type") == "image_url":
                image_url = item.get("image_url")
                if isinstance(image_url, dict) and isinstance(image_url.get("url"), str):
                    image = _load_image(image_url["url"])
            elif item.get("type") == "image" and isinstance(item.get("image"), str):
                image = _load_image(item["image"])
    return "\n".join(part for part in text_parts if part.strip()).strip(), image


def _vista_prompt(instruction: str) -> str:
    if "Output the center point of the position corresponding to the instruction" in instruction:
        return instruction
    return (
        "Output the center point of the position corresponding to the instruction: "
        f"{instruction}. The output should just be the coordinates of a point, in the format [x,y]."
    )


def _point_payload(text: str) -> dict[str, Any]:
    match = re.search(r"\[\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\]", text)
    point = None
    if match:
        point = {"x": float(match.group(1)), "y": float(match.group(2)), "coordinate_space": "normalized_0_1000"}
    return {
        "contract_version": "vista_point_v1",
        "status": "ready" if point else "unparsed",
        "point": point,
        "raw_text": text,
    }


def _generate(messages: list[dict[str, Any]], *, max_tokens: int, temperature: float) -> str:
    import torch

    if MODEL is None or PROCESSOR is None:
        raise RuntimeError("model is not loaded")
    instruction, image = _message_text_and_image(messages)
    if image is None:
        raise ValueError("VISTA-4B requires an image")
    if not instruction:
        raise ValueError("VISTA-4B requires an instruction")
    prompt = _vista_prompt(instruction)
    chat_messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": image},
                {"type": "text", "text": prompt},
            ],
        }
    ]
    text = PROCESSOR.apply_chat_template(chat_messages, tokenize=False, add_generation_prompt=True)
    inputs = PROCESSOR(text=[text], images=[image], padding=True, return_tensors="pt")
    target_device = next(MODEL.parameters()).device
    inputs = inputs.to(target_device)
    generate_kwargs: dict[str, Any] = {
        "max_new_tokens": max(1, min(int(max_tokens or MAX_NEW_TOKENS), MAX_NEW_TOKENS)),
        "do_sample": temperature > 0,
    }
    if temperature > 0:
        generate_kwargs["temperature"] = float(temperature)
    with torch.inference_mode():
        generated = MODEL.generate(**inputs, **generate_kwargs)
    new_tokens = generated[:, inputs["input_ids"].shape[1] :]
    return PROCESSOR.batch_decode(new_tokens, skip_special_tokens=True)[0].strip()


class VistaHandler(BaseHTTPRequestHandler):
    server_version = "VistaOpenAIServer/0.1"

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            print("client disconnected before response could be sent", flush=True)

    def do_GET(self) -> None:
        if self.path.rstrip("/") in {"/health", "/v1/health"}:
            self._send_json(
                200,
                {
                    "status": "busy" if GENERATE_LOCK.locked() else "ok",
                    "model": MODEL_NAME,
                    "pid": os.getpid(),
                    "active_request": ACTIVE_REQUEST,
                },
            )
            return
        if self.path.rstrip("/") in {"/v1/models", "/models"}:
            self._send_json(
                200,
                {
                    "object": "list",
                    "data": [
                        {
                            "id": MODEL_NAME,
                            "object": "model",
                            "owned_by": "local",
                        }
                    ],
                },
            )
            return
        self._send_json(404, {"error": {"message": f"unknown route: {self.path}"}})

    def do_POST(self) -> None:
        global ACTIVE_REQUEST
        if self.path.rstrip("/") not in {"/v1/chat/completions", "/chat/completions"}:
            self._send_json(404, {"error": {"message": f"unknown route: {self.path}"}})
            return
        acquired = GENERATE_LOCK.acquire(blocking=False)
        if not acquired:
            self._send_json(
                503,
                {
                    "error": {
                        "message": "VISTA model is already processing another request",
                        "type": "model_busy",
                        "active_request": ACTIVE_REQUEST,
                    }
                },
            )
            return
        try:
            length = int(self.headers.get("Content-Length") or "0")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            ACTIVE_REQUEST = {
                "started_at": time.time(),
                "client": self.client_address[0] if self.client_address else None,
                "max_tokens": int(payload.get("max_tokens") or MAX_NEW_TOKENS),
            }
            text = _generate(
                payload.get("messages") if isinstance(payload.get("messages"), list) else [],
                max_tokens=int(payload.get("max_tokens") or MAX_NEW_TOKENS),
                temperature=float(payload.get("temperature") or 0.0),
            )
            wants_json = (payload.get("response_format") or {}).get("type") == "json_object"
            content = json.dumps(_point_payload(text), ensure_ascii=False) if wants_json else text
            self._send_json(
                200,
                {
                    "id": f"vista-{int(time.time() * 1000)}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": MODEL_NAME,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": content},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                },
            )
        except Exception as exc:
            self._send_json(500, {"error": {"message": str(exc), "type": exc.__class__.__name__}})
        finally:
            ACTIVE_REQUEST = None
            GENERATE_LOCK.release()

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}", flush=True)


def _torch_dtype(dtype: str):
    import torch

    normalized = dtype.casefold()
    if normalized in {"auto", ""}:
        return "auto"
    if normalized in {"bf16", "bfloat16"}:
        return torch.bfloat16
    if normalized in {"fp16", "float16"}:
        return torch.float16
    if normalized in {"fp32", "float32"}:
        return torch.float32
    raise ValueError(f"unsupported dtype: {dtype}")


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenAI-compatible VISTA-4B point-grounding server")
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--model-name", default="inclusionAI/VISTA-4B")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1244)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--dtype", default="bfloat16")
    parser.add_argument("--max-new-tokens", type=int, default=32)
    args = parser.parse_args()

    global MODEL, PROCESSOR, MODEL_NAME, MAX_NEW_TOKENS
    MODEL_NAME = args.model_name
    MAX_NEW_TOKENS = int(args.max_new_tokens)
    model_path = str(Path(args.model_path).resolve())

    try:
        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor
    except Exception as exc:
        print(
            "Missing VISTA runtime dependencies. Install with: uv sync --group vista "
            "or install torch transformers accelerate safetensors. "
            f"Original error: {exc}",
            file=sys.stderr,
            flush=True,
        )
        return 2

    dtype = _torch_dtype(args.dtype)
    device_map = "auto" if args.device == "auto" else None
    model_kwargs: dict[str, Any] = {"trust_remote_code": True}
    if dtype != "auto":
        model_kwargs["torch_dtype"] = dtype
    if device_map:
        model_kwargs["device_map"] = device_map
    print(f"Loading VISTA model from {model_path} on device={args.device} dtype={args.dtype}", flush=True)
    try:
        PROCESSOR = AutoProcessor.from_pretrained(model_path, trust_remote_code=True)
        MODEL = AutoModelForImageTextToText.from_pretrained(model_path, **model_kwargs)
    except OSError as exc:
        message = str(exc)
        if getattr(exc, "winerror", None) == 1455 or "os error 1455" in message.casefold():
            print(
                "VISTA model load failed because Windows reported insufficient virtual memory "
                "(WinError/os error 1455: page file is too small). Close memory-heavy apps or "
                "increase the Windows page file, then start VISTA again.",
                file=sys.stderr,
                flush=True,
            )
        raise
    if args.device != "auto":
        MODEL = MODEL.to(args.device)
    MODEL.eval()
    print(f"VISTA OpenAI-compatible server listening on {args.host}:{args.port}", flush=True)
    ThreadingHTTPServer((args.host, args.port), VistaHandler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
