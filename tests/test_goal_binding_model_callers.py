from __future__ import annotations

import importlib.util
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = ROOT / "configs" / "model_profiles"
PROFILE_NAMES = (
    "goal_binding_qwen_incumbent.json",
    "goal_binding_ui_venus_1_5_2b_f16.json",
    "goal_binding_gui_actor_3b_bf16.json",
    "goal_binding_phi_ground_any_bf16.json",
    "goal_binding_ui_venus_2_9b_q6_k.json",
    "goal_binding_groundnext_7b_q6_k.json",
    "goal_binding_ui_venus_1_5_8b_q6_k.json",
)


def _worker_module():
    path = ROOT / "scripts" / "model_servers" / "goal_binding_transformers_worker.py"
    spec = importlib.util.spec_from_file_location("goal_binding_transformers_worker", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_import_and_profile_load_never_start_or_download_a_model(monkeypatch) -> None:
    import app.learn.hybrid.goal_binding_model_callers as callers

    touched: list[object] = []
    monkeypatch.setattr(Path, "mkdir", lambda *args, **kwargs: touched.append(args))
    def forbidden(*args, **kwargs):
        pytest.fail("metadata loading must not verify artifacts or start a process")
    monkeypatch.setattr(callers, "_verified", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    before = dict(__import__("os").environ)
    profiles = [callers.load_goal_binding_profile(PROFILE_DIR / name) for name in PROFILE_NAMES]

    assert [profile["artifact_manifest"] for profile in profiles] == [
        json.loads((PROFILE_DIR / name).read_text(encoding="utf-8"))["artifact_manifest"]
        for name in PROFILE_NAMES
    ]
    assert touched == []
    assert dict(__import__("os").environ) == before


def test_profiles_are_closed_non_authorizing_and_use_exact_model_ids() -> None:
    from app.learn.hybrid.goal_binding_model_callers import load_goal_binding_profile

    profiles = {
        profile["profile_id"]: profile
        for profile in (load_goal_binding_profile(PROFILE_DIR / name) for name in PROFILE_NAMES)
    }
    assert profiles["goal_binding_ui_venus_1_5_2b_f16"]["model_id"] == "inclusionAI/UI-Venus-1.5-2B"
    assert profiles["goal_binding_gui_actor_3b_bf16"]["model_id"] == "microsoft/GUI-Actor-3B-Qwen2.5-VL"
    assert profiles["goal_binding_phi_ground_any_bf16"]["model_id"] == "microsoft/Phi-Ground-Any"
    for profile in profiles.values():
        assert profile["artifact_is_authorization"] is False
        assert profile["execute_binding_enabled"] is False
        assert profile["final_submit_forbidden"] is True
        assert set(profile) == {
            "contract_version", "profile_id", "arm_id", "provider_id", "model_id",
            "repository_id", "upstream_revision", "artifacts", "artifact_manifest",
            "runtime", "dtype_or_quantization", "native_output", "coordinate_space",
            "preprocessing", "max_output_bytes", "timeout_seconds", "license",
            "artifact_is_authorization", "execute_binding_enabled", "final_submit_forbidden",
        }
        assert profile["runtime"]["entrypoint"].startswith(
            "scripts.model_servers.goal_binding_provider_runtimes:"
        )


def test_ui_venus_profile_seals_the_windows_sdpa_runtime_with_its_native_shape() -> None:
    from app.learn.hybrid.goal_binding_model_callers import load_goal_binding_profile

    profile = load_goal_binding_profile(
        PROFILE_DIR / "goal_binding_ui_venus_1_5_2b_f16.json"
    )

    assert profile["runtime"]["kind"] == "transformers_sdpa_windows_v1"
    assert profile["native_output"]["kind"] == "ui_venus_point_v1"


def test_windows_sdpa_runtime_rejects_a_non_ui_venus_native_shape() -> None:
    from app.learn.hybrid.goal_binding_model_callers import _validate_profile

    profile = json.loads(
        (PROFILE_DIR / "goal_binding_ui_venus_1_5_2b_f16.json").read_text(
            encoding="utf-8"
        )
    )
    profile["native_output"] = {
        "kind": "gui_actor_topk_points_v1",
        "raw_format": "utf8_native",
    }

    with pytest.raises(ValueError, match="runtime kind.*native output"):
        _validate_profile(profile)


def test_windows_sdpa_runtime_rejects_a_non_ui_venus_provider_id() -> None:
    from app.learn.hybrid.goal_binding_model_callers import _validate_profile

    profile = json.loads(
        (PROFILE_DIR / "goal_binding_ui_venus_1_5_2b_f16.json").read_text(
            encoding="utf-8"
        )
    )
    profile["provider_id"] = "gui_actor_3b_bf16"

    with pytest.raises(ValueError, match="runtime kind.*provider_id"):
        _validate_profile(profile)


def test_ui_venus_and_phi_workers_return_only_native_output_trace() -> None:
    worker = _worker_module()
    for provider_id, raw_native in (
        ("ui_venus_1_5_2b_f16", '{"point":[250,375]}'),
        ("phi_ground_any_bf16", "<x>5000</x><y>5000</y>"),
    ):
        envelope = worker.native_trace_envelope(
            profile_identity={"profile_id": provider_id, "preprocessing_sha256": "a" * 64, "runtime_sha256": "b" * 64, "native_output_kind": "ui_venus_point_v1"},
            raw_native_output=raw_native,
            resource_metrics={
                "latency_ms": 1.0,
                "peak_vram_bytes": None,
                "peak_vram_status": "unavailable",
                "generation_tokens": None,
                "request_bytes": 10,
                "provider_stdout_bytes": 0,
                "provider_stderr_bytes": 0,
                "timeout_seconds": 120,
            },
        )
        assert envelope["raw_native_output"] == raw_native
        assert envelope["parsed_native"] is None
        assert "candidate" not in json.dumps(envelope, ensure_ascii=False).casefold()
        assert "gold" not in json.dumps(envelope, ensure_ascii=False).casefold()


def test_gui_actor_caller_preserves_topk_raw_but_selects_top1_only() -> None:
    from app.learn.hybrid.goal_binding_model_callers import native_adapter_for_profile

    profile = {
        "provider_id": "gui_actor_3b_bf16",
        "native_output": {"kind": "gui_actor_topk_points_v1"},
        "coordinate_space": "normalized_0_1",
    }
    raw = {"topk_points": [[0.25, 0.375], [0.75, 0.625]]}
    proposal = native_adapter_for_profile(profile)(raw, goal_index=0, profile={
        "contract_version": "goal_binding_native_profile_v1",
        "provider_id": "gui_actor_3b_bf16",
        "native_shape": "gui_actor_topk_points_v1",
        "coordinate_space": "normalized_0_1",
    })
    assert proposal.point == (0.25, 0.375)
    assert raw["topk_points"][1] == [0.75, 0.625]


def test_gguf_profile_requires_model_mmproj_and_runtime_hashes(tmp_path: Path) -> None:
    from app.learn.hybrid.goal_binding_model_callers import (
        load_goal_binding_profile,
        make_goal_binding_arm,
    )

    profile = load_goal_binding_profile(PROFILE_DIR / "goal_binding_ui_venus_2_9b_q6_k.json")
    with pytest.raises(ValueError, match="not acquired|artifact"):
        make_goal_binding_arm(profile=profile, artifact_dir=tmp_path)


def test_each_caller_binds_exact_pid_create_time_and_cleanup_receipt(tmp_path: Path) -> None:
    from app.learn.hybrid.goal_binding_model_callers import (
        exact_process_identity,
        verified_no_process_cleanup_receipt,
    )

    assert exact_process_identity({"pid": 42, "create_time_ns": 99}) == {"pid": 42, "create_time_ns": 99}
    receipt = verified_no_process_cleanup_receipt("test-provider")
    assert receipt["verified"] is True
    assert receipt["owned_processes"] == []
    assert receipt["provider"] == "test-provider"


def test_unknown_residue_or_gpu_owner_blocks_next_provider() -> None:
    from app.learn.hybrid.goal_binding_model_callers import cleanup_receipt_is_clean

    assert cleanup_receipt_is_clean({
        "contract_version": "simple_native_provider_cleanup_v1", "provider": "x",
        "verified": True, "cleanup_status": "verified", "owned_processes": [],
        "provider_processes_after": [], "helper_processes_after": [],
        "orphan_descendant_pids": [], "active_listeners_after": [], "lease_files_after": [],
    }) is True
    assert cleanup_receipt_is_clean({
        "contract_version": "simple_native_provider_cleanup_v1", "provider": "x",
        "verified": True, "cleanup_status": "verified", "owned_processes": [{"pid": 1}],
        "provider_processes_after": [], "helper_processes_after": [],
        "orphan_descendant_pids": [], "active_listeners_after": [], "lease_files_after": [],
    }) is False


def test_session_cleanup_uses_bound_delayed_worker_identity(monkeypatch, tmp_path: Path) -> None:
    from app.learn.hybrid import goal_binding_model_callers as callers
    from app.learn.hybrid import windows_process_scope as scopes
    from scripts.model_servers.goal_binding_transformers_worker import write_json

    launcher = {"pid": 41, "create_time_ns": 100}
    worker = {"pid": 42, "create_time_ns": 101}
    digest = "a" * 64
    session = callers.GoalBindingProviderSession(
        {"provider_id": "ui_venus_1_5_2b_f16", "arm_id": "ui"},
        tmp_path,
        tmp_path / "run",
    )
    session.root = tmp_path / "session"
    session.root.mkdir()
    session.config_sha = digest
    session.config = {"scope_name": "scope", "code_identity": {}}
    session.launcher_identity = launcher
    session.identity = launcher
    session.baseline = {"status": "verified", "owners": []}
    session.profile = {"provider_id": "ui_venus_1_5_2b_f16", "max_output_bytes": 16384}
    session.runtime_state = None
    session.sequence = 1

    class Process:
        def wait(self, timeout):
            assert session.identity == worker
            return 0
        def poll(self): return 0
        def close(self): return None

    class Scope:
        closed = False
        def pids(self):
            assert self.closed is False
            return [launcher["pid"], worker["pid"]]
        def close(self): self.closed = True

    session.process = Process()
    session.scope = Scope()
    write_json(session.root / "worker-identity.json", worker)
    write_json(session.root / "stopped.json", {
        "session_sha256": digest,
        "worker_process_identity": worker,
        "runtime_cleanup": {"status": "released"},
    })
    monkeypatch.setattr(
        scopes,
        "observe_process_scope_cleanup",
        lambda *args, **kwargs: {
            "cleanup_status": "verified",
            "member_identities_after": [],
            "member_pids_after": [],
            "active_listeners_after": [],
        },
    )
    monkeypatch.setattr(scopes, "_identity_for_pid", lambda pid: worker)
    monkeypatch.setattr(
        __import__("psutil"),
        "Process",
        lambda pid: SimpleNamespace(parents=lambda: [SimpleNamespace(pid=launcher["pid"])]),
    )
    monkeypatch.setattr(callers, "_gpu_ownership_snapshot", lambda: {"status": "verified", "owners": []})

    receipt = session.cleanup()

    assert receipt["verified"] is True
    assert receipt["cleanup_observations"][0]["worker_process_identity"] == worker


@pytest.mark.parametrize("failure", ["wrong_incarnation", "outside_scope", "not_descended", "malformed"])
def test_session_cleanup_rejects_unverified_live_worker_identity(monkeypatch, tmp_path: Path, failure: str) -> None:
    from app.learn.hybrid import goal_binding_model_callers as callers
    from app.learn.hybrid import windows_process_scope as scopes
    from scripts.model_servers.goal_binding_transformers_worker import write_json

    launcher = {"pid": 41, "create_time_ns": 100}
    worker = {"pid": 42, "create_time_ns": 101}
    session = callers.GoalBindingProviderSession({"provider_id": "ui_venus_1_5_2b_f16", "arm_id": "ui"}, tmp_path, tmp_path / "run")
    session.root = tmp_path / "session"
    session.root.mkdir()
    session.config_sha = "a" * 64
    session.config = {"scope_name": "scope", "code_identity": {}}
    session.launcher_identity = launcher
    session.identity = launcher
    session.baseline = {"status": "verified", "owners": []}
    session.profile = {"provider_id": "ui_venus_1_5_2b_f16", "max_output_bytes": 16384}
    session.runtime_state = None
    session.sequence = 1
    session.process = SimpleNamespace(wait=lambda timeout: 0, poll=lambda: 0, close=lambda: None)
    members = [launcher["pid"], worker["pid"]] if failure != "outside_scope" else [launcher["pid"]]
    session.scope = SimpleNamespace(pids=lambda: members, close=lambda: None)
    write_json(session.root / "worker-identity.json", {"pid": worker["pid"]} if failure == "malformed" else worker)
    write_json(session.root / "stopped.json", {"session_sha256": session.config_sha, "worker_process_identity": worker, "runtime_cleanup": {"status": "released"}})
    observed = {"pid": worker["pid"], "create_time_ns": 999} if failure == "wrong_incarnation" else worker
    parents = [] if failure == "not_descended" else [SimpleNamespace(pid=launcher["pid"])]
    monkeypatch.setattr(scopes, "_identity_for_pid", lambda pid: observed)
    monkeypatch.setattr(__import__("psutil"), "Process", lambda pid: SimpleNamespace(parents=lambda: parents))
    monkeypatch.setattr(scopes, "observe_process_scope_cleanup", lambda *args, **kwargs: {"cleanup_status": "verified", "member_identities_after": [], "member_pids_after": [], "active_listeners_after": []})
    monkeypatch.setattr(callers, "_gpu_ownership_snapshot", lambda: {"status": "verified", "owners": []})

    receipt = session.cleanup()

    assert receipt["verified"] is False
    assert receipt["cleanup_observations"][0]["errors"]


def test_probe_uses_no_gold_holdout_or_candidate_mapping(tmp_path: Path) -> None:
    from app.learn.hybrid.goal_binding_model_callers import (
        load_goal_binding_profile,
        probe_goal_binding_profile,
    )

    image = tmp_path / "screen.png"
    image.write_bytes(b"not-an-image-needed-before-acquisition")
    profile = load_goal_binding_profile(PROFILE_DIR / "goal_binding_ui_venus_1_5_2b_f16.json")
    profile["upstream_revision"] = "not_acquired"
    for artifact in profile["artifacts"]:
        artifact["sha256"] = "not_acquired"
        artifact["bytes"] = "not_acquired"
    profile["artifact_manifest"] = {
        "status": "not_acquired",
        "relative_path": "manifests/ui_venus_1_5_2b_f16.json",
        "sha256": "not_acquired",
    }
    profile["runtime"]["sha256"] = "not_acquired"
    profile["preprocessing"]["sha256"] = "not_acquired"
    with pytest.raises(ValueError, match="not acquired|artifact"):
        probe_goal_binding_profile(profile=profile, image_path=image)


def test_probe_uses_explicit_artifact_root_not_screenshot_parent(monkeypatch, tmp_path: Path) -> None:
    import app.learn.hybrid.goal_binding_model_callers as callers

    image = tmp_path / "capture" / "screen.png"
    image.parent.mkdir()
    image.write_bytes(b"screen")
    artifact_dir = tmp_path / "artifacts"
    seen: list[Path] = []
    fake_arm = SimpleNamespace(
        provider_id="provider",
        call=lambda _image, _request: "[1,2]",
        cleanup=lambda: {"verified": True},
    )
    monkeypatch.setattr(
        callers,
        "make_goal_binding_arm",
        lambda *, profile, artifact_dir: seen.append(artifact_dir) or fake_arm,
    )

    callers.probe_goal_binding_profile(
        profile={}, image_path=image, artifact_dir=artifact_dir
    )

    assert seen == [artifact_dir]




def test_runtime_functions_are_real_lazy_entrypoints(tmp_path: Path) -> None:
    from scripts.model_servers import goal_binding_provider_runtimes as runtimes

    assert callable(runtimes.run_ui_venus)
    assert callable(runtimes.run_gui_actor)
    assert callable(runtimes.run_phi_ground_any)
    assert callable(runtimes.run_llama_cpp)


def test_phi_runtime_uses_exact_white_top_left_lanczos_canvas(tmp_path: Path) -> None:
    from PIL import Image
    from scripts.model_servers import goal_binding_provider_runtimes as runtimes

    image_path = tmp_path / "screen.png"
    Image.new("RGB", (840, 840), "black").save(image_path)
    observed: dict[str, object] = {}

    class FakeLLM:
        def generate(self, inputs, sampling_params):
            observed["inputs"] = inputs
            observed["sampling"] = sampling_params
            return [SimpleNamespace(outputs=[SimpleNamespace(text="<x>2500</x><y>5000</y>", token_ids=[1, 2])])]

    result = runtimes.run_phi_ground_any(
        image_path=image_path,
        goal="button: Open",
        profile={"timeout_seconds": 7},
        artifact_root=tmp_path,
        dependencies={"llm": FakeLLM(), "sampling_params": lambda **kw: kw},
    )

    padded = observed["inputs"][0]["multi_modal_data"]["image"]
    assert padded.size == (1680, 1008)
    assert padded.getpixel((1007, 1007)) == (0, 0, 0)
    assert padded.getpixel((1200, 1007)) == (255, 255, 255)
    assert result["raw_native_output"] == "<x>2500</x><y>5000</y>"


def test_phi_worker_projects_back_to_original_pixels_and_rejects_padding() -> None:
    worker = _worker_module()

    assert worker._parse_phi("<x>5000</x><y>5000</y>", width=840, height=840) == {
        "point": [700.0, 420.0]
    }
    with pytest.raises(ValueError, match="padding|outside"):
        worker._parse_phi("<x>9000</x><y>5000</y>", width=840, height=840)


def test_ui_venus_runtime_uses_frozen_center_prompt_and_exact_decode(tmp_path: Path) -> None:
    from PIL import Image
    from scripts.model_servers import goal_binding_provider_runtimes as runtimes

    image_path = tmp_path / "screen.png"
    Image.new("RGB", (4, 3), "white").save(image_path)
    observed: dict[str, object] = {}

    class InputIds:
        shape = (1, 2)

    class Processor:
        def apply_chat_template(self, messages, **kwargs):
            observed["messages"] = messages
            return "rendered"
        def __call__(self, **kwargs):
            return {"input_ids": InputIds(), "pixel_values": object()}
        def batch_decode(self, values, **kwargs):
            observed["decoded_ids"] = values
            observed["decode_kwargs"] = kwargs
            return ["[250,375]"]

    class Model:
        device = "cuda"
        def generate(self, **kwargs):
            observed["generate"] = kwargs
            return [[10, 11, 12]]

    cuda = SimpleNamespace(is_available=lambda: False)
    result = runtimes.run_ui_venus(
        image_path=image_path,
        goal="button: Open",
        profile={},
        artifact_root=tmp_path,
        dependencies={"model": Model(), "processor": Processor(), "torch": SimpleNamespace(cuda=cuda), "process_vision_info": lambda messages: ([messages[0]["content"][0]["image"]], None)},
    )

    prompt = observed["messages"][0]["content"][1]["text"]
    assert prompt == runtimes.UI_VENUS_CENTER_POINT_PROMPT.format(goal="button: Open")
    assert observed["decoded_ids"] == [[12]]
    assert observed["decode_kwargs"]["clean_up_tokenization_spaces"] is False
    assert result["raw_native_output"] == "[250,375]"
    assert observed["generate"]["max_new_tokens"] == 128


def test_gui_actor_runtime_calls_official_topk_three_and_preserves_all_points(tmp_path: Path) -> None:
    from scripts.model_servers import goal_binding_provider_runtimes as runtimes

    calls: list[dict[str, object]] = []
    prediction = {"topk_points": [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]], "entropy": 0.7}

    def inference(conversation, model, tokenizer, data_processor, *, use_placeholder, topk):
        calls.append({"conversation": conversation, "use_placeholder": use_placeholder, "topk": topk})
        return prediction

    result = runtimes.run_gui_actor(
        image_path=tmp_path / "screen.png",
        goal="button: Open",
        profile={},
        artifact_root=tmp_path,
        dependencies={"model": object(), "processor": object(), "tokenizer": object(), "inference": inference, "grounding_system_message": "official system"},
    )

    assert calls[0]["use_placeholder"] is True and calls[0]["topk"] == 3
    assert result["parsed_native"] == {"topk_points": prediction["topk_points"]}
    assert calls[0]["conversation"][0]["content"][0]["text"] == "official system"
    assert calls[0]["conversation"][1]["content"][1]["text"] == "button: Open"








def test_worker_subprocess_happy_path_with_tiny_fake_provider(tmp_path: Path) -> None:
    from PIL import Image

    image = tmp_path / "screen.png"
    Image.new("RGB", (2, 3), "white").save(image)
    identity = tmp_path / "identity.json"
    identity.write_text('{"pid":42,"create_time_ns":99}', encoding="utf-8")
    (tmp_path / "fake_provider.py").write_text(
        "def run(**kwargs):\n    return '[250,375]'\n", encoding="utf-8"
    )
    payload = {
        "image_path": str(image), "goal": "button: Open",
        "profile": {
            "profile_id": "ui", "provider_id": "ui_venus_1_5_2b_f16",
            "runtime": {"entrypoint": "fake_provider:run", "sha256": "a" * 64},
            "preprocessing": {"sha256": "b" * 64},
            "native_output": {"kind": "ui_venus_point_v1"},
            "timeout_seconds": 5,
        },
        "screenshot": {
            "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
            "width": 2, "height": 3, "capture_id": "capture/test",
        },
        "parent_identity_path": str(identity),
        "artifact_root": str(tmp_path),
    }
    request = tmp_path / "request.json"
    request.write_text(json.dumps(payload), encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(tmp_path) + os.pathsep + str(ROOT)

    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts/model_servers/goal_binding_transformers_worker.py"), "--execute", "--request-json", str(request)],
        cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8", timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    envelope = json.loads(completed.stdout)
    assert envelope["raw_native_output"] == "[250,375]"
    assert envelope["resource_metrics"]["peak_vram_bytes"] is None


def test_worker_dispatches_provider_after_pinned_runtime_is_available(monkeypatch, tmp_path: Path) -> None:
    from PIL import Image

    worker = _worker_module()
    image = tmp_path / "screen.png"
    Image.new("RGB", (1, 1), "white").save(image)
    identity = tmp_path / "identity.json"
    identity.write_text('{"pid":42,"create_time_ns":99}', encoding="utf-8")
    profile = {"profile_id": "ui", "provider_id": "ui_venus_1_5_2b_f16", "runtime": {"kind": "transformers", "sha256": "not_acquired"}, "preprocessing": {"identity": "x", "sha256": "not_acquired"}, "native_output": {"kind": "ui_venus_point_v1"}}
    monkeypatch.setattr(worker, "_dispatch_provider", lambda **kwargs: "[250,375]", raising=False)
    result = worker._run_provider_once({"image_path": str(image), "goal": "button: Open", "profile": profile, "screenshot": {"sha256": __import__("hashlib").sha256(image.read_bytes()).hexdigest(), "width": 1, "height": 1, "capture_id": "capture/test"}, "parent_identity_path": str(identity)})
    assert result["raw_native_output"] == "[250,375]"

def test_learn_mode_gui_actor_profile_remains_legacy_learn_schema() -> None:
    profile = json.loads((PROFILE_DIR / "learn_mode_gui_actor_3b.json").read_text(encoding="utf-8"))
    assert profile["mode_scope"] == "learn_only"
    assert profile["output_contract"] == "action_region_verification_v1"
