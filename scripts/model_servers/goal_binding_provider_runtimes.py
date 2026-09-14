"""Lazy executable runtimes for the sealed goal-binding provider profiles.

The module intentionally imports no model framework at import time.  Every heavy
dependency, checkpoint load, source import, listener, and child process is scoped
to the selected function call.
"""
from __future__ import annotations

import base64
from hashlib import sha256
import json
import math
import os
import sys
from pathlib import Path
import time
from typing import Any, Mapping
from urllib import error as urllib_error
from urllib import request as urllib_request


UI_VENUS_CENTER_POINT_PROMPT = (
    "Output the center point of the position corresponding to the following instruction: \n"
    "{goal}. \n\nThe output should just be the coordinates of a point, in the format [x,y]. "
    "Additionally, if the task is infeasible (e.g., the task is not related to the image), the output should be [-1,-1]."
)
PHI_GROUND_ANY_PROMPT = (
    "<|user|> \n{goal}<|image_1|> \n<|end|> \n<|assistant|>"
)
GGUF_GROUNDING_PROMPT = (
    "Locate the center of the UI element described by: {goal}. "
    "Return only [x,y] normalized to 0-1000."
)


class ProviderIntegrityError(RuntimeError):
    """提供者传输身份或工件完整性不可验证。"""


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
    if profile.get("provider_id") == "qwen3_vl_8b_q4_k_m":
        from app.learn.hybrid.goal_binding_managed_artifacts import verify_managed_artifacts
        return verify_managed_artifacts(profile, artifact_root)
    if profile.get("provider_id") == "ui_venus_1_5_2b_f16":
        from app.learn.hybrid.goal_binding_deployed_artifacts import verify_ui_venus_deployment
        return verify_ui_venus_deployment(profile, artifact_root)
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
    if isinstance(value, Mapping):
        value = {key: _json_safe(item) for key, item in value.items()}
    elif isinstance(value, (list, tuple)):
        value = [_json_safe(item) for item in value]
    elif hasattr(value, "detach"):
        value = value.detach().cpu().tolist()
    elif hasattr(value, "tolist"):
        value = value.tolist()
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


def phi_image_geometry(width: int, height: int) -> dict[str, object]:
    ratio = width / height
    if ratio > 1680 / 1008:
        new_width, new_height = 1680, int(1680 / ratio)
    else:
        new_width, new_height = int(1008 * ratio), 1008
    if min(new_width, new_height) <= 0:
        raise ValueError("Phi image cannot fit its canvas")
    return {"original_dimensions": [width, height], "canvas_dimensions": [1680, 1008], "resized_dimensions": [new_width, new_height], "reshape_ratio": new_width / width}


def _load_dependencies(profile: Mapping[str, object], artifact_root: Path) -> dict[str, object]:
    try:
        paths = verified_artifact_paths(profile, artifact_root)
    except ValueError as exc:
        raise ProviderIntegrityError(str(exc)) from exc
    provider = profile["provider_id"]
    revisions = {"ui_venus_1_5_2b_f16": "inclusionAI/UI-Venus@192a9247ad1129279ba1d6c263d4c9e7ecef3644", "gui_actor_3b_bf16": "microsoft/GUI-Actor@d98d1bbd01862f9112114b83b032f492c365a173", "phi_ground_any_bf16": "microsoft/Phi-Ground@395640833d9b4748446d007257d87924df733ecb"}
    if profile.get("preprocessing", {}).get("source_revision") != revisions[provider]:
        raise ProviderIntegrityError("official source revision differs from pinned provider source")
    if provider == "ui_venus_1_5_2b_f16":
        runtime = profile.get("runtime")
        if (
            not isinstance(runtime, Mapping)
            or runtime.get("kind") != "transformers_sdpa_windows_v1"
        ):
            raise ProviderIntegrityError(
                "UI-Venus requires the sealed transformers_sdpa_windows_v1 runtime"
            )
    if provider == "gui_actor_3b_bf16":
        runtime = profile.get("runtime")
        if (
            not isinstance(runtime, Mapping)
            or runtime.get("kind") != "gui_actor_transformers_sdpa_windows_v1"
        ):
            raise ProviderIntegrityError(
                "GUI-Actor requires its sealed SDPA runtime"
            )
    checkpoint = paths["model"].parent
    if provider == "phi_ground_any_bf16":
        if sys.platform == "win32":
            raise RuntimeError("provider_platform_incompatible: vLLM has no native Windows runtime; WSL fallback is forbidden")
        from vllm import LLM, SamplingParams
        return {"llm": LLM(model=str(checkpoint), trust_remote_code=True, dtype="bfloat16", max_model_len=8192, max_num_seqs=10, tensor_parallel_size=1, limit_mm_per_prompt={"image": 1}), "sampling_params": SamplingParams}
    import torch
    from transformers import AutoProcessor
    processor = AutoProcessor.from_pretrained(checkpoint, local_files_only=True)
    if provider == "ui_venus_1_5_2b_f16":
        from transformers import AutoModelForImageTextToText
        from qwen_vl_utils import process_vision_info
        model = AutoModelForImageTextToText.from_pretrained(checkpoint, local_files_only=True, torch_dtype=torch.bfloat16, low_cpu_mem_usage=True, attn_implementation="sdpa").to("cuda").eval()
        return {"model": model, "processor": processor, "torch": torch, "process_vision_info": process_vision_info}
    from gui_actor.modeling_qwen25vl import Qwen2_5_VLForConditionalGenerationWithPointer
    from gui_actor.inference import inference
    from gui_actor.constants import grounding_system_message
    model = Qwen2_5_VLForConditionalGenerationWithPointer.from_pretrained(checkpoint, local_files_only=True, torch_dtype=torch.bfloat16, device_map="cuda:0", attn_implementation="sdpa").eval()
    return {"model": model, "processor": processor, "tokenizer": processor.tokenizer, "torch": torch, "inference": inference, "grounding_system_message": grounding_system_message}


class _LoadedSession:
    def __init__(self, call, dependencies):
        self.call, self.dependencies = call, dependencies

    def __call__(self, **kwargs):
        if self.dependencies is None:
            raise RuntimeError("provider runtime is closed")
        return self.call(**kwargs, dependencies=self.dependencies)

    def close(self):
        if self.dependencies is not None:
            self.dependencies.clear()
            self.dependencies = None
        return {"status": "released"}


def open_session(*, profile, artifact_root, session_root, scope_name, listener_port):
    provider = profile["provider_id"]
    calls = {"ui_venus_1_5_2b_f16": run_ui_venus, "gui_actor_3b_bf16": run_gui_actor, "phi_ground_any_bf16": run_phi_ground_any}
    if provider in calls:
        return _LoadedSession(calls[provider], _load_dependencies(profile, artifact_root))
    if provider == "qwen3_vl_8b_q4_k_m":
        return _ManagedIncumbentSession(profile, artifact_root, session_root, scope_name)
    return _LlamaSession(profile, artifact_root, session_root, scope_name, listener_port)


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
    deps = dict(dependencies) if dependencies is not None else _load_dependencies(profile, artifact_root)
    model, processor, torch_module = deps["model"], deps["processor"], deps["torch"]
    from PIL import Image

    image = Image.open(image_path).convert("RGB")
    prompt = UI_VENUS_CENTER_POINT_PROMPT.format(goal=goal[:-1] if goal.endswith(".") else goal)
    messages = [{"role": "user", "content": [{"type": "image", "image": image}, {"type": "text", "text": prompt}]}]
    rendered = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    image_inputs, video_inputs = deps["process_vision_info"](messages)
    inputs = processor(text=[rendered], images=image_inputs, videos=video_inputs, padding=True, return_tensors="pt")
    device = getattr(model, "device", "cuda")
    inputs = {key: value.to(device) if hasattr(value, "to") else value for key, value in inputs.items()}
    cuda = getattr(torch_module, "cuda", None)
    if cuda is not None and getattr(cuda, "is_available", lambda: False)():
        cuda.reset_peak_memory_stats()
    generated = model.generate(**inputs, max_new_tokens=128, do_sample=False, temperature=0.0)
    raw, token_count = _decode_generated(processor, inputs, generated)
    return _result(
        raw,
        telemetry=_metrics(
            generation_tokens=token_count,
            peak_vram_bytes=_cuda_peak(torch_module),
        ),
    )




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
    """Construct the official pointer runtime and retain only its bounded top-k result."""
    if incumbent_projection is not None or incumbent_request is not None:
        raise ValueError("challenger cannot receive incumbent candidate projection")
    deps = dict(dependencies) if dependencies is not None else _load_dependencies(profile, artifact_root)
    model, processor, inference = deps["model"], deps["processor"], deps["inference"]
    torch_module = deps.get("torch")
    cuda = getattr(torch_module, "cuda", None) if torch_module is not None else None
    if cuda is not None and getattr(cuda, "is_available", lambda: False)():
        cuda.reset_peak_memory_stats()
    conversation = [
        {"role": "system", "content": [{"type": "text", "text": deps["grounding_system_message"]}]},
        {"role": "user", "content": [{"type": "image", "image": str(image_path)}, {"type": "text", "text": goal}]},
    ]
    prediction = inference(
        conversation, model, deps["tokenizer"], processor,
        use_placeholder=True,
        topk=3,
    )
    if not isinstance(prediction, Mapping) or "topk_points" not in prediction:
        raise ValueError("GUI-Actor prediction must contain topk_points")
    native = {"topk_points": _json_safe(prediction["topk_points"])}
    raw = json.dumps(native, ensure_ascii=False, separators=(",", ":"))
    return _result(
        raw,
        parsed_native=native,
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
    geometry = phi_image_geometry(source.width, source.height)
    resized = source.resize(
        tuple(geometry["resized_dimensions"]), Image.Resampling.LANCZOS
    )
    padded = Image.new("RGB", (1680, 1008), "white")
    padded.paste(resized, (0, 0))
    deps = dict(dependencies) if dependencies is not None else _load_dependencies(profile, artifact_root)
    llm, sampling_factory = deps["llm"], deps["sampling_params"]
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


def _verify_listener(*, port: int, identity: Mapping[str, object], scope_name: str) -> bool:
    import psutil
    try:
        return _observe_exact_listener(port=port, identity=identity, scope_name=scope_name)
    except (OSError, RuntimeError, psutil.Error) as exc:
        if isinstance(exc, ProviderIntegrityError):
            raise
        raise ProviderIntegrityError("llama listener identity is unobservable") from exc


def _observe_exact_listener(*, port: int, identity: Mapping[str, object], scope_name: str) -> bool:
    from app.learn.hybrid.windows_process_scope import _listeners, _identity_for_pid, WindowsProcessScope
    listeners = _listeners([port])
    if any(item["pid"] != identity["pid"] for item in listeners):
        raise ProviderIntegrityError("llama listener belongs to another process")
    if not listeners:
        return False
    if _identity_for_pid(identity["pid"]) != identity:
        raise ProviderIntegrityError("llama listener process incarnation changed")
    scope = WindowsProcessScope(scope_name, create=False)
    try:
        if identity["pid"] not in scope.pids():
            raise ProviderIntegrityError("llama listener process is outside its exact Job")
    finally:
        scope.close()
    return True


def _wait_ready(*, port: int, deadline: float, identity: Mapping[str, object], scope_name: str, model_id: str) -> None:
    url = f"http://127.0.0.1:{port}/health"
    last_error: BaseException | None = None
    while time.monotonic() < deadline:
        if not _verify_listener(port=port, identity=identity, scope_name=scope_name):
            time.sleep(0.05)
            continue
        try:
            with urllib_request.urlopen(url, timeout=0.25) as response:
                health = json.loads(response.read(16385).decode("utf-8"))
            if health.get("status") == "ok":
                with urllib_request.urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=0.25) as response:
                    models = json.loads(response.read(16385).decode("utf-8"))
                if [item.get("id") for item in models.get("data", [])] != [model_id]:
                    raise ProviderIntegrityError("llama listener model identity mismatch")
                return
        except (OSError, urllib_error.URLError) as exc:
            last_error = exc
        time.sleep(0.05)
    raise TimeoutError("llama.cpp provider listener did not become ready") from last_error


class _LlamaSession:
    def __init__(self, profile, artifact_root, session_root, scope_name, listener_port):
        from app.learn.hybrid.windows_process_scope import spawn_process_in_scope
        from scripts.model_servers.goal_binding_transformers_worker import write_json
        if not isinstance(listener_port, int) or not 1024 <= listener_port <= 65535:
            raise ProviderIntegrityError("llama requires a reserved listener")
        try:
            paths = verified_artifact_paths(profile, artifact_root)
        except ValueError as exc:
            raise ProviderIntegrityError(str(exc)) from exc
        self.profile, self.root, self.scope_name, self.port = profile, session_root, scope_name, listener_port
        self.identity = None
        self.child = None
        self.closed = False
        command = [str(paths["runtime"]), "-m", str(paths["model"]), "--mmproj", str(paths["mmproj"]), "--host", "127.0.0.1", "--port", str(listener_port), "--alias", str(profile["model_id"]), "--ctx-size", "4096", "--n-gpu-layers", "99"]
        def before_resume(identity):
            self.identity = dict(identity)
            write_json(session_root / "llama-identity.json", self.identity)
        try:
            with (session_root / "llama.stdout.bin").open("xb") as stdout, (session_root / "llama.stderr.bin").open("xb") as stderr:
                self.child = spawn_process_in_scope(command, scope_name=scope_name, cwd=artifact_root, stdout=stdout, stderr=stderr, before_resume=before_resume)
            _wait_ready(port=listener_port, deadline=time.monotonic() + profile["timeout_seconds"], identity=self.identity, scope_name=scope_name, model_id=profile["model_id"])
        except BaseException:
            self.close()
            raise

    def __call__(self, *, image_path, goal, incumbent_request=None, incumbent_projection=None, **kwargs):
        if incumbent_request is not None or incumbent_projection is not None:
            raise ProviderIntegrityError("challenger cannot use incumbent projection")
        if self.closed or not _verify_listener(port=self.port, identity=self.identity, scope_name=self.scope_name):
            raise ProviderIntegrityError("llama exact listener is unavailable before request")
        media = base64.b64encode(image_path.read_bytes()).decode("ascii")
        response = _post_json(port=self.port, timeout=self.profile["timeout_seconds"], payload={"model": self.profile["model_id"], "messages": [{"role": "user", "content": [{"type": "text", "text": GGUF_GROUNDING_PROMPT.format(goal=goal)}, {"type": "image_url", "image_url": {"url": "data:image/png;base64," + media}}]}], "temperature": 0, "max_tokens": 64, "stream": False})
        try:
            raw = response["choices"][0]["message"]["content"]
            tokens = response.get("usage", {}).get("completion_tokens")
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("llama native response is invalid") from exc
        return _result(raw, telemetry=_metrics(generation_tokens=tokens, peak_vram_bytes=None))

    def close(self):
        if not self.closed:
            self.closed = True
            if self.child is not None:
                if self.child.poll() is None:
                    self.child.kill()
                self.exit_code = self.child.wait(timeout=5)
                self.child.close()
        return {"status": "released", "server_process_identity": self.identity, "listener_port": self.port, "exit_code": getattr(self, "exit_code", None)}


def _managed_artifact_identity(profile, selected, artifact_root=None):
    from app.core import model_server
    if artifact_root is not None:
        paths = verified_artifact_paths(profile, artifact_root)
        if any(paths[role] != (model_server.ROOT_DIR / selected[key]).resolve() for role, key in (("model", "model_path"), ("mmproj", "mmproj_path"), ("runtime", "server_path"))):
            raise ProviderIntegrityError("managed incumbent selected paths changed")
        return {item["role"]: item["sha256"] for item in profile["artifacts"] if item["role"] in {"model", "mmproj", "runtime"}}
    result = {}
    for role, key in (("model", "model_path"), ("mmproj", "mmproj_path"), ("runtime", "server_path")):
        path = (model_server.ROOT_DIR / selected[key]).resolve()
        artifact = next((item for item in profile["artifacts"] if item["role"] == role), None)
        if artifact is None or not path.is_file() or path.stat().st_size != artifact["bytes"] or _sha_file(path) != artifact["sha256"]:
            raise ProviderIntegrityError("managed incumbent artifact identity is not sealed")
        result[role] = artifact["sha256"]
    return result


class _ManagedIncumbentSession:
    def __init__(self, profile, artifact_root, session_root, scope_name):
        from app.core import model_server
        from app.learn.hybrid.windows_process_scope import WindowsProcessScope, process_scope_name
        self.profile = profile
        self.artifact_root = artifact_root
        self.selected = model_server.profile_for_stage("understanding", "qwen3_vl_8b_q4_k_m")
        self.hashes = _managed_artifact_identity(profile, self.selected, self.artifact_root)
        self.port = self.selected["port"]
        self.scope_name = process_scope_name({"run_id": session_root.name, "workflow_revision": 1,
            "operation_id": "goal_binding_managed_incumbent", "stage": "goal_binding",
            "stage_execution_id": sha256((scope_name + "\0" + str(session_root)).encode("utf-8")).hexdigest()}, "qwen")
        self.server_scope = WindowsProcessScope(self.scope_name, create=True)
        previous_scope = os.environ.get("AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME")
        try:
            os.environ["AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME"] = self.scope_name
            self.lease = model_server.ensure_and_acquire_scoped_qwen_model_lease(stage="understanding", profile_id="qwen3_vl_8b_q4_k_m", request_id="goal-binding-" + session_root.name, wait_seconds=profile["timeout_seconds"], profile_validator=lambda selected: _managed_artifact_identity(profile, selected, self.artifact_root))
        except BaseException:
            self.server_scope.close()
            raise
        finally:
            if previous_scope is None:
                os.environ.pop("AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME", None)
            else:
                os.environ["AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME"] = previous_scope
        self.identity = self.lease["server_process_identity"]
        self.closed = False

    def __call__(self, *, image_path, incumbent_projection, incumbent_request, **kwargs):
        from app.core import model_server
        if self.closed or not _verify_listener(port=self.port, identity=self.identity, scope_name=self.scope_name):
            raise ProviderIntegrityError("incumbent exact listener is unavailable before request")
        image = image_path.read_bytes()
        from PIL import Image
        with Image.open(image_path) as opened:
            media_type = Image.MIME[opened.format]
        raw = model_server.run_qwen_projection_model_raw(projection=incumbent_projection, screenshot_bytes=image, screenshot_media_type=media_type, screenshot_sha256=sha256(image).hexdigest(), model_lease=self.lease, timeout_seconds=self.profile["timeout_seconds"])
        return _result(raw, telemetry=_metrics(generation_tokens=None, peak_vram_bytes=None))

    def close(self):
        from app.core import model_server
        if not self.closed:
            try:
                release = model_server.release_scoped_qwen_model_lease(self.lease, "goal_binding_arm_complete")
                model_server._validate_exact_qwen_cleanup_evidence(release, self.lease)
                if _managed_artifact_identity(self.profile, self.selected, self.artifact_root) != self.hashes:
                    raise ProviderIntegrityError("managed incumbent artifact changed during arm")
                self.release = release
                self.closed = True
            finally:
                self.server_scope.close()
        return {"status": "released", "server_process_identity": self.identity, "listener_port": self.port, "managed_release": self.release, "artifact_hashes_before_after": self.hashes}


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




def run_llama_cpp(*, image_path: Path, goal: str, profile: Mapping[str, object], artifact_root: Path, incumbent_projection=None, incumbent_request=None, listener_port=None, dependencies=None) -> dict[str, object]:
    scope_name = os.environ.get("AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME", "")
    if not scope_name or dependencies is not None:
        raise ProviderIntegrityError("llama runtime requires its parent-owned process scope")
    from uuid import uuid4
    session_root = artifact_root / "goal-binding-single-probe" / uuid4().hex
    session_root.mkdir(parents=True, exist_ok=False)
    session = open_session(profile=profile, artifact_root=artifact_root, session_root=session_root, scope_name=scope_name, listener_port=listener_port)
    try:
        return session(image_path=image_path, goal=goal, incumbent_projection=incumbent_projection, incumbent_request=incumbent_request)
    finally:
        session.close()


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
