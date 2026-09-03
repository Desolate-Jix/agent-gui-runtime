"""Lazy executable runtimes for the sealed goal-binding provider profiles.

The module intentionally imports no model framework at import time.  Every heavy
dependency, checkpoint load, source import, listener, and child process is scoped
to the selected function call.
"""
from __future__ import annotations

import base64
from hashlib import sha256
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Any, Mapping
from urllib import error as urllib_error
from urllib import request as urllib_request


UI_VENUS_CENTER_POINT_PROMPT = (
    "Locate the center point of the UI element described by the instruction: "
    "{goal}. Return only [x,y], with x and y normalized to 0-1000."
)
PHI_GROUND_ANY_PROMPT = (
    "Locate the UI element described by: {goal}. Return only "
    "<x>VALUE</x><y>VALUE</y> using the 0-10000 padded-canvas coordinates."
)
GGUF_GROUNDING_PROMPT = (
    "Locate the center of the UI element described by: {goal}. "
    "Return only [x,y] normalized to 0-1000."
)


def _sha_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_path(root: Path, relative: object) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("provider artifact path is invalid")
    root = root.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("provider artifact escapes the verified artifact root")
    return path


def verified_artifact_paths(
    profile: Mapping[str, object], artifact_root: Path
) -> dict[str, Path]:
    """Resolve and re-hash every profile-declared runtime artifact."""
    artifacts = profile.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError("provider artifact list is unavailable")
    result: dict[str, Path] = {}
    for item in artifacts:
        if not isinstance(item, Mapping):
            raise ValueError("provider artifact entry is invalid")
        role, expected_sha, expected_bytes = (
            item.get("role"), item.get("sha256"), item.get("bytes")
        )
        if (
            not isinstance(role, str)
            or role in result
            or not isinstance(expected_sha, str)
            or len(expected_sha) != 64
            or isinstance(expected_bytes, bool)
            or not isinstance(expected_bytes, int)
            or expected_bytes < 0
        ):
            raise ValueError("provider artifact identity is not verified")
        path = _safe_path(artifact_root, item.get("relative_path"))
        if (
            not path.is_file()
            or path.stat().st_size != expected_bytes
            or _sha_file(path) != expected_sha
        ):
            raise ValueError("provider artifact changed after verification")
        result[role] = path
    return result


def _json_safe(value: object) -> object:
    try:
        return json.loads(
            json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("provider native telemetry is not JSON-safe") from exc


def _metrics(
    *,
    generation_tokens: int | None,
    peak_vram_bytes: int | None,
    provider_stdout_bytes: int = 0,
    provider_stderr_bytes: int = 0,
) -> dict[str, object]:
    if peak_vram_bytes is not None and peak_vram_bytes < 0:
        raise ValueError("peak VRAM observation is invalid")
    return {
        "generation_tokens": generation_tokens,
        "peak_vram_bytes": peak_vram_bytes,
        "peak_vram_status": "measured" if peak_vram_bytes is not None else "unavailable",
        "provider_stdout_bytes": provider_stdout_bytes,
        "provider_stderr_bytes": provider_stderr_bytes,
    }


def _result(
    raw: str,
    *,
    parsed_native: object = None,
    telemetry: Mapping[str, object],
    child_cleanup: Mapping[str, object] | None = None,
) -> dict[str, object]:
    if not isinstance(raw, str):
        raise ValueError("provider raw output must be exact UTF-8 text")
    result = {
        "raw_native_output": raw,
        "parsed_native": _json_safe(parsed_native),
        "telemetry": _json_safe(dict(telemetry)),
    }
    if child_cleanup is not None:
        result["child_cleanup"] = _json_safe(dict(child_cleanup))
    return result


def _cuda_peak(torch_module: object) -> int | None:
    cuda = getattr(torch_module, "cuda", None)
    try:
        if cuda is None or not cuda.is_available():
            return None
        return int(cuda.max_memory_allocated())
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None


def _decode_generated(processor: object, inputs: Mapping[str, object], generated: object) -> tuple[str, int | None]:
    sequences = getattr(generated, "sequences", generated)
    sequence = sequences[0]
    input_ids = inputs.get("input_ids")
    prompt_length = int(input_ids.shape[-1]) if hasattr(input_ids, "shape") else 0
    continuation = sequence[prompt_length:] if prompt_length else sequence
    decoded = processor.batch_decode(
        [continuation], skip_special_tokens=True, clean_up_tokenization_spaces=False
    )
    if not isinstance(decoded, list) or len(decoded) != 1 or not isinstance(decoded[0], str):
        raise ValueError("provider processor did not decode exact UTF-8 text")
    try:
        count = len(continuation)
    except TypeError:
        count = None
    return decoded[0], count


def run_ui_venus(
    *,
    image_path: Path,
    goal: str,
    profile: Mapping[str, object],
    artifact_root: Path,
    incumbent_projection: object = None,
    incumbent_request: object = None,
    listener_port: int | None = None,
    dependencies: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Run the official UI-Venus center-point Transformers path in BF16."""
    if incumbent_projection is not None or incumbent_request is not None:
        raise ValueError("challenger cannot receive incumbent candidate projection")
    deps = dict(dependencies or {})
    if deps:
        model, processor, torch_module = deps["model"], deps["processor"], deps["torch"]
    else:
        paths = verified_artifact_paths(profile, artifact_root)
        import torch as torch_module
        from transformers import AutoModelForVision2Seq, AutoProcessor

        checkpoint = paths["model"].parent
        processor = AutoProcessor.from_pretrained(
            checkpoint, local_files_only=True, trust_remote_code=True
        )
        model = AutoModelForVision2Seq.from_pretrained(
            checkpoint,
            local_files_only=True,
            trust_remote_code=True,
            torch_dtype=torch_module.bfloat16,
            device_map="cuda",
        ).eval()
    from PIL import Image

    image = Image.open(image_path).convert("RGB")
    prompt = UI_VENUS_CENTER_POINT_PROMPT.format(goal=goal)
    messages = [{"role": "user", "content": [{"type": "image", "image": image}, {"type": "text", "text": prompt}]}]
    rendered = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = processor(text=[rendered], images=[image], padding=True, return_tensors="pt")
    device = getattr(model, "device", "cuda")
    inputs = {key: value.to(device) if hasattr(value, "to") else value for key, value in inputs.items()}
    cuda = getattr(torch_module, "cuda", None)
    if cuda is not None and getattr(cuda, "is_available", lambda: False)():
        cuda.reset_peak_memory_stats()
    generated = model.generate(**inputs, max_new_tokens=64, do_sample=False)
    raw, token_count = _decode_generated(processor, inputs, generated)
    return _result(
        raw,
        telemetry=_metrics(
            generation_tokens=token_count,
            peak_vram_bytes=_cuda_peak(torch_module),
        ),
    )


def _load_verified_source_module(path: Path, expected_sha256: str) -> object:
    if path.suffix.casefold() != ".py" or _sha_file(path) != expected_sha256:
        raise ValueError("official GUI-Actor source artifact is not an exact verified Python file")
    module_name = "goal_binding_verified_gui_actor_" + expected_sha256[:16]
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ValueError("official GUI-Actor source artifact cannot be imported")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_gui_actor(
    *,
    image_path: Path,
    goal: str,
    profile: Mapping[str, object],
    artifact_root: Path,
    incumbent_projection: object = None,
    incumbent_request: object = None,
    listener_port: int | None = None,
    dependencies: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Construct the official pointer runtime and retain its complete top-k result."""
    if incumbent_projection is not None or incumbent_request is not None:
        raise ValueError("challenger cannot receive incumbent candidate projection")
    deps = dict(dependencies or {})
    if deps:
        model, processor, inference = deps["model"], deps["processor"], deps["inference"]
        torch_module = deps.get("torch")
    else:
        paths = verified_artifact_paths(profile, artifact_root)
        source_item = next(
            item for item in profile["artifacts"]
            if isinstance(item, Mapping) and item.get("role") == "source"
        )
        source = _load_verified_source_module(paths["source"], str(source_item["sha256"]))
        import torch as torch_module

        model_class = getattr(source, "GUIActor", None) or getattr(
            source, "Qwen2VLForConditionalGenerationWithPointer", None
        )
        processor_class = getattr(source, "AutoProcessor", None)
        inference = getattr(source, "inference", None)
        if not callable(getattr(model_class, "from_pretrained", None)) or not callable(
            getattr(processor_class, "from_pretrained", None)
        ) or not callable(inference):
            raise ValueError("official GUI-Actor source API is unavailable")
        checkpoint = paths["model"].parent
        model = model_class.from_pretrained(
            checkpoint,
            local_files_only=True,
            torch_dtype=torch_module.bfloat16,
            device_map="cuda",
        ).eval()
        processor = processor_class.from_pretrained(checkpoint, local_files_only=True)
    cuda = getattr(torch_module, "cuda", None) if torch_module is not None else None
    if cuda is not None and getattr(cuda, "is_available", lambda: False)():
        cuda.reset_peak_memory_stats()
    prediction = inference(
        model=model,
        processor=processor,
        image_path=str(image_path),
        instruction=goal,
        use_placeholder=True,
        topk=3,
    )
    safe_prediction = _json_safe(prediction)
    if not isinstance(safe_prediction, dict) or not isinstance(safe_prediction.get("topk_points"), list):
        raise ValueError("official GUI-Actor inference did not return topk_points")
    raw = json.dumps(safe_prediction, ensure_ascii=False, separators=(",", ":"))
    return _result(
        raw,
        parsed_native=safe_prediction,
        telemetry=_metrics(
            generation_tokens=None,
            peak_vram_bytes=_cuda_peak(torch_module) if torch_module is not None else None,
        ),
    )


def run_phi_ground_any(
    *,
    image_path: Path,
    goal: str,
    profile: Mapping[str, object],
    artifact_root: Path,
    incumbent_projection: object = None,
    incumbent_request: object = None,
    listener_port: int | None = None,
    dependencies: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Run Phi-Ground-Any through its vLLM multimodal path and frozen canvas."""
    if incumbent_projection is not None or incumbent_request is not None:
        raise ValueError("challenger cannot receive incumbent candidate projection")
    from PIL import Image

    source = Image.open(image_path).convert("RGB")
    ratio = min(1680 / source.width, 1008 / source.height)
    resized = source.resize(
        (round(source.width * ratio), round(source.height * ratio)), Image.Resampling.LANCZOS
    )
    padded = Image.new("RGB", (1680, 1008), "white")
    padded.paste(resized, (0, 0))
    deps = dict(dependencies or {})
    if deps:
        llm = deps["llm"]
        sampling_factory = deps["sampling_params"]
    else:
        paths = verified_artifact_paths(profile, artifact_root)
        from vllm import LLM, SamplingParams

        llm = LLM(
            model=str(paths["model"].parent),
            trust_remote_code=True,
            dtype="bfloat16",
            limit_mm_per_prompt={"image": 1},
        )
        sampling_factory = SamplingParams
    prompt = PHI_GROUND_ANY_PROMPT.format(goal=goal)
    sampling = sampling_factory(temperature=0.0, max_tokens=64)
    outputs = llm.generate(
        [{"prompt": prompt, "multi_modal_data": {"image": padded}}], sampling
    )
    try:
        generated = outputs[0].outputs[0]
        raw = generated.text
        tokens = len(generated.token_ids)
    except (AttributeError, IndexError, TypeError) as exc:
        raise ValueError("Phi-Ground-Any vLLM output is invalid") from exc
    if not isinstance(raw, str):
        raise ValueError("Phi-Ground-Any raw output is not UTF-8 text")
    return _result(
        raw,
        telemetry=_metrics(generation_tokens=tokens, peak_vram_bytes=None),
    )


def _wait_ready(*, port: int, deadline: float) -> None:
    url = f"http://127.0.0.1:{port}/health"
    last_error: BaseException | None = None
    while time.monotonic() < deadline:
        try:
            with urllib_request.urlopen(url, timeout=0.25) as response:
                if 200 <= response.status < 300:
                    return
        except (OSError, urllib_error.URLError) as exc:
            last_error = exc
        time.sleep(0.05)
    raise TimeoutError("llama.cpp provider listener did not become ready") from last_error


def _post_json(*, port: int, payload: Mapping[str, object], timeout: float) -> object:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = urllib_request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib_request.urlopen(request, timeout=timeout) as response:
        raw = response.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError("llama.cpp response exceeded the transport bound")
    return json.loads(raw.decode("utf-8"))


def _llama_prompt(
    *, goal: str, incumbent_request: object, incumbent_projection: object
) -> str:
    if incumbent_request is None and incumbent_projection is None:
        return GGUF_GROUNDING_PROMPT.format(goal=goal)
    if not isinstance(incumbent_request, Mapping) or not isinstance(incumbent_projection, Mapping):
        raise ValueError("incumbent runtime request and projection must be supplied together")
    return (
        "Return only a bare per-goal binding array for this frozen request projection:\n"
        + json.dumps(incumbent_projection, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )


def run_llama_cpp(
    *,
    image_path: Path,
    goal: str,
    profile: Mapping[str, object],
    artifact_root: Path,
    incumbent_projection: object = None,
    incumbent_request: object = None,
    listener_port: int | None = None,
    dependencies: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Launch one verified llama-server on loopback, call it once, then reap it."""
    if not isinstance(listener_port, int) or not 1024 <= listener_port <= 65535:
        raise ValueError("llama.cpp requires one reserved loopback listener port")
    deps = dict(dependencies or {})
    paths = deps.get("paths") or verified_artifact_paths(profile, artifact_root)
    if not isinstance(paths, Mapping) or not all(role in paths for role in ("runtime", "model", "mmproj")):
        raise ValueError("llama.cpp requires verified runtime, model, and mmproj artifacts")
    popen = deps.get("popen", subprocess.Popen)
    wait_ready = deps.get("wait_ready", _wait_ready)
    post_json = deps.get("post_json", _post_json)
    timeout = float(profile.get("timeout_seconds", 120))
    max_output = int(profile.get("max_output_bytes", 16384))
    command = [
        str(paths["runtime"]), "-m", str(paths["model"]), "--mmproj", str(paths["mmproj"]),
        "--host", "127.0.0.1", "--port", str(listener_port), "--ctx-size", "4096",
        "--n-gpu-layers", "99",
    ]
    child = None
    server_stdout = b""
    server_stderr = b""
    termination = "not_started"
    with tempfile.TemporaryDirectory(prefix="goal-binding-llama-", dir=artifact_root) as temp:
        stdout_path, stderr_path = Path(temp) / "stdout.bin", Path(temp) / "stderr.bin"
        try:
            with stdout_path.open("wb") as stdout_handle, stderr_path.open("wb") as stderr_handle:
                child = popen(
                    command,
                    cwd=str(artifact_root),
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    creationflags=0,
                )
                wait_ready(port=listener_port, deadline=time.monotonic() + min(timeout, 30.0))
                media = base64.b64encode(image_path.read_bytes()).decode("ascii")
                prompt = _llama_prompt(
                    goal=goal,
                    incumbent_request=incumbent_request,
                    incumbent_projection=incumbent_projection,
                )
                response = post_json(
                    port=listener_port,
                    timeout=timeout,
                    payload={
                        "messages": [{"role": "user", "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + media}},
                        ]}],
                        "temperature": 0,
                        "max_tokens": 64,
                        "stream": False,
                    },
                )
                try:
                    raw = response["choices"][0]["message"]["content"]
                    generation_tokens = response.get("usage", {}).get("completion_tokens")
                except (KeyError, IndexError, TypeError, AttributeError) as exc:
                    raise ValueError("llama.cpp native response is invalid") from exc
                if not isinstance(raw, str) or len(raw.encode("utf-8")) > max_output:
                    raise ValueError("llama.cpp native output is invalid or exceeds profile bound")
        finally:
            if child is not None:
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=5.0)
                        termination = "terminated"
                    except (subprocess.TimeoutExpired, TimeoutError):
                        child.kill()
                        child.wait(timeout=5.0)
                        termination = "killed"
                else:
                    child.wait(timeout=0)
                    termination = "exited"
            if stdout_path.exists():
                server_stdout = stdout_path.read_bytes()
            if stderr_path.exists():
                server_stderr = stderr_path.read_bytes()
        cleanup = {
            "status": "verified" if child is not None and child.poll() is not None else "failed",
            "child_pid": getattr(child, "pid", None),
            "listener": {"host": "127.0.0.1", "port": listener_port},
            "termination": termination,
        }
        if cleanup["status"] != "verified":
            raise RuntimeError("llama.cpp child cleanup could not be verified")
        return _result(
            raw,
            telemetry=_metrics(
                generation_tokens=generation_tokens if isinstance(generation_tokens, int) else None,
                peak_vram_bytes=None,
                provider_stdout_bytes=len(server_stdout),
                provider_stderr_bytes=len(server_stderr),
            ),
            child_cleanup=cleanup,
        )


__all__ = [
    "GGUF_GROUNDING_PROMPT",
    "PHI_GROUND_ANY_PROMPT",
    "UI_VENUS_CENTER_POINT_PROMPT",
    "run_gui_actor",
    "run_llama_cpp",
    "run_phi_ground_any",
    "run_ui_venus",
    "verified_artifact_paths",
]
