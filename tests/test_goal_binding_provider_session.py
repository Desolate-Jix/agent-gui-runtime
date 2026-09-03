from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

from scripts.model_servers import goal_binding_transformers_worker as worker


def payload(tmp_path, provider="ui_venus_1_5_2b_f16"):
    image = tmp_path / "screen.png"
    Image.new("RGB", (800, 600), "white").save(image)
    identity = tmp_path / "identity.json"
    identity.write_text('{"pid":42,"create_time_ns":99}', encoding="utf-8")
    return {
        "image_path": str(image), "goal": "button: Open",
        "profile": {"profile_id": provider, "provider_id": provider,
                    "runtime": {"sha256": "a" * 64},
                    "preprocessing": {"sha256": "b" * 64},
                    "native_output": {"kind": worker._native_kind_for_provider(provider)},
                    "timeout_seconds": 5},
        "screenshot": {"sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                       "width": 800, "height": 600, "capture_id": "capture/test"},
        "parent_identity_path": str(identity), "artifact_root": str(tmp_path),
    }


def test_native_malformed_then_valid_continues_and_retains_exact_raw(monkeypatch, tmp_path):
    request = payload(tmp_path)
    raw = iter(['\u9519\u8bef [250,375]', '[250,375]'])
    monkeypatch.setattr(worker, "_dispatch_provider", lambda **kw: next(raw))
    first = worker._run_provider_once(request)
    second = worker._run_provider_once(request)
    assert first["outcome"] == "provider_failure"
    assert first["failure"] == {"kind": "malformed_native_output", "message": "UI-Venus native output is invalid", "attempted": True, "terminal": False}
    assert first["raw_native_output"] == '\u9519\u8bef [250,375]'
    assert second["outcome"] == "native_output"
    assert second["parsed_native"] == '[250,375]'


def test_gui_telemetry_raw_is_separate_from_full_ordered_topk(monkeypatch, tmp_path):
    request = payload(tmp_path, "gui_actor_3b_bf16")
    prediction = {"topk_points": [[0.2, 0.3], [0.9, 0.1]], "attention": [1, 2]}
    monkeypatch.setattr(worker, "_dispatch_provider", lambda **kw: prediction)
    result = worker._run_provider_once(request)
    assert json.loads(result["raw_native_output"]) == prediction
    assert result["parsed_native"] == {"topk_points": prediction["topk_points"]}


def test_official_gui_no_pointer_preserves_raw_and_same_runtime_continues(monkeypatch, tmp_path):
    from scripts.model_servers import goal_binding_provider_runtimes as runtimes
    request = payload(tmp_path, "gui_actor_3b_bf16")
    predictions = [
        {"topk_points": None, "generated_text": "\u65e0\u5b9a\u4f4d", "attention": [0.1, 0.2]},
        {"topk_points": [[0.2, 0.3], [0.9, 0.1]], "attention": [1, 2]},
    ]
    loads, calls = [], []
    model = object()
    def infer(conversation, selected_model, tokenizer, processor, **kwargs):
        calls.append(selected_model)
        return predictions[len(calls) - 1]
    def load(*args):
        loads.append(1)
        return {"model": model, "processor": object(), "tokenizer": object(),
                "inference": infer, "grounding_system_message": "grounding"}
    monkeypatch.setattr(runtimes, "_load_dependencies", load)
    runtime = runtimes.open_session(profile=request["profile"], artifact_root=tmp_path,
                                    session_root=tmp_path, scope_name="unused", listener_port=None)
    try:
        first = worker._run_provider_once(request, dispatcher=runtime)
        second = worker._run_provider_once(request, dispatcher=runtime)
    finally:
        runtime.close()
    assert json.loads(first["raw_native_output"]) == predictions[0]
    assert first["raw_native_output_sha256"] == hashlib.sha256(first["raw_native_output"].encode("utf-8")).hexdigest()
    assert first["failure"]["kind"] == "malformed_native_output"
    assert first["failure"]["terminal"] is False
    assert first["failure"]["attempted"] is True
    assert second["outcome"] == "native_output"
    assert second["parsed_native"] == {"topk_points": predictions[1]["topk_points"]}
    assert loads == [1] and calls == [model, model]


@pytest.mark.parametrize("raw,ok", [(' [ ] \n', True), ('{"x":1}', False), ('[{"x":1,"x":2}]', False), ('[NaN]', False)])
def test_incumbent_decodes_strict_bare_json_list(monkeypatch, tmp_path, raw, ok):
    request = payload(tmp_path, "qwen3_vl_8b_q4_k_m")
    request.update(incumbent_request={}, incumbent_projection={})
    monkeypatch.setattr(worker, "_dispatch_provider", lambda **kw: raw)
    result = worker._run_provider_once(request)
    assert result["raw_native_output"] == raw
    assert result["outcome"] == ("native_output" if ok else "provider_failure")
    if ok:
        assert result["parsed_native"] == []


def test_phi_adapter_uses_actual_capture_dimensions():
    from app.learn.hybrid.goal_binding_model_callers import _adapter_profile
    profile = {"provider_id": "phi_ground_any_bf16", "native_output": {"kind": "phi_ground_any_v1"}}
    assert _adapter_profile(profile, image_size=(800, 600))["image_size"] == [800, 600]


@pytest.fixture
def offline_arm(monkeypatch, tmp_path):
    from app.learn.hybrid import goal_binding_model_callers as callers
    from app.learn.hybrid.windows_process_scope import windows_process_scope_available
    if not windows_process_scope_available():
        pytest.skip("real Windows Job primitives unavailable")
    request = payload(tmp_path)
    profile = request["profile"]
    profile.update(arm_id="test-arm", max_output_bytes=65536, timeout_seconds=5,
                   artifacts=[{"role": "runtime", "relative_path": "python.exe"}],
                   artifact_manifest={"sha256": "c" * 64})
    profile["runtime"].update(kind="transformers", worker="scripts/model_servers/goal_binding_transformers_worker.py", entrypoint="fake_provider:run")
    fake = tmp_path / "fake_provider.py"
    fake.write_text(
        "from pathlib import Path\n"
        "import time\n"
        "def open_session(**kwargs):\n"
        "    root = kwargs['artifact_root']\n"
        "    with (root/'events.txt').open('a') as f: f.write('load\\n')\n"
        "    class Session:\n"
        "        def __call__(self, **request):\n"
        "            with (root/'events.txt').open('a') as f: f.write('call\\n')\n"
        "            goal=request['goal']\n"
        "            if goal == 'timeout': time.sleep(30)\n"
        "            if goal == 'oom': raise RuntimeError('out of memory')\n"
        "            return 'bad' if goal == 'malformed' else '[250,375]'\n"
        "        def close(self):\n"
        "            with (root/'events.txt').open('a') as f: f.write('close\\n')\n"
        "            return {'status':'released'}\n"
        "    return Session()\n", encoding="utf-8")
    monkeypatch.setattr(callers, "_verified", lambda profile, artifact_dir: profile)
    monkeypatch.setattr(callers, "_worker_python", lambda *args: Path(sys.executable), raising=False)
    baseline = {"status": "verified", "owners": [{"pid": 10, "create_time_ns": 20, "used_memory_mib": None}], "raw": "10, N/A"}
    monkeypatch.setattr(callers, "_gpu_ownership_snapshot", lambda: baseline, raising=False)
    monkeypatch.setattr(callers, "_resource_preflight", lambda profile: {"model_launch_allowed": True, "status": "ready"}, raising=False)
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    arms = []
    def make(**changes):
        run_root = changes.pop("run_root", None)
        selected = dict(profile, **changes)
        arm = callers.make_goal_binding_arm(profile=selected, artifact_dir=tmp_path, run_root=run_root)
        arms.append(arm)
        return arm
    yield make, Path(request["image_path"]), tmp_path
    for arm in arms:
        arm.cleanup()


def test_persistent_arm_real_mailbox_one_load_two_calls_one_cleanup(offline_arm):
    make, image, root = offline_arm
    arm = make()
    assert not (root / "events.txt").exists()
    one = arm.call(image, {"goal": "malformed"})
    two = arm.call(image, {"goal": "valid"})
    assert one["outcome"] == "provider_failure"
    assert two["outcome"] == "native_output"
    assert one["worker_process_identity"] == two["worker_process_identity"]
    assert (root / "events.txt").read_text().splitlines() == ["load", "call", "call"]
    receipt = arm.cleanup()
    assert receipt["verified"] is True
    assert arm.cleanup() == receipt
    assert (root / "events.txt").read_text().splitlines() == ["load", "call", "call", "close"]


@pytest.mark.parametrize("scenario", ["atomic_rename", "missing_final", "oversized_tmp"])
def test_atomic_response_rename_does_not_hide_other_output_failures(offline_arm, monkeypatch, scenario):
    make, image, _ = offline_arm
    original_write, original_is_file = worker.atomic_write, Path.is_file
    name = "000008.json" if scenario == "missing_final" else "000008.json.tmp"
    raced = []
    def write(path, body):
        if path.parent.name == "requests" and path.suffix == ".json":
            transient = path.parent.parent / "responses" / name
            transient.write_bytes(b"x" * (65537 if scenario == "oversized_tmp" else 1))
        original_write(path, body)
    def is_file(path):
        result = original_is_file(path)
        if result and path.name == name and path.parent.name == "responses" and scenario != "oversized_tmp":
            path.unlink()
            raced.append(path.name)
        return result
    monkeypatch.setattr(worker, "atomic_write", write)
    monkeypatch.setattr(Path, "is_file", is_file)
    arm = make()
    if scenario == "atomic_rename":
        assert arm.call(image, {"goal": "valid"})["outcome"] == "native_output"
        assert raced == [name]
        assert arm.cleanup()["verified"] is True
    else:
        expected = FileNotFoundError if scenario == "missing_final" else RuntimeError
        with pytest.raises(expected):
            arm.call(image, {"goal": "valid"})
        assert arm.cleanup()["verified"] is False


def test_real_mailbox_separates_model_and_run_roots(offline_arm):
    make, image, root = offline_arm
    run_root = root.parent / (root.name + "-run")
    arm = make(run_root=run_root)
    first = arm.call(image, {"goal": "valid"})
    second = arm.call(image, {"goal": "valid"})
    assert first["outcome"] == second["outcome"] == "native_output"
    assert first["worker_process_identity"] == second["worker_process_identity"]
    assert first["request_lineage"]["screenshot_sha256"] == hashlib.sha256(image.read_bytes()).hexdigest()
    receipt = arm.cleanup()
    assert receipt["verified"] is True
    cleanup_path = Path(receipt["cleanup_observations"][0]["cleanup_path"])
    assert cleanup_path.is_relative_to(run_root) and not cleanup_path.is_relative_to(root)
    config = json.loads(cleanup_path.with_name("session.json").read_text(encoding="utf-8"))
    assert Path(config["artifact_root"]) == root
    assert (root / "events.txt").read_text().splitlines() == ["load", "call", "call", "close"]


@pytest.mark.parametrize("field", ["image_path", "parent_identity_path"])
def test_real_mailbox_rejects_paths_outside_verified_session(offline_arm, monkeypatch, field):
    make, image, root = offline_arm
    original = worker.atomic_write
    def tamper(path, body):
        if path.parent.name == "requests" and path.suffix == ".json":
            request = json.loads(body)
            request["payload"][field] = str(image if field == "image_path" else root / "identity.json")
            body = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        original(path, body)
    monkeypatch.setattr(worker, "atomic_write", tamper)
    arm = make(run_root=root.parent / (root.name + "-run"))
    with pytest.raises(RuntimeError, match="mailbox payload identity mismatch"):
        arm.call(image, {"goal": "valid"})
    assert arm.cleanup()["verified"] is False
    assert (root / "events.txt").read_text().splitlines() == ["load", "close"]


def test_real_session_runner_cleanup_is_accepted_by_frozen_scorer(offline_arm):
    from test_goal_binding_ab import _run
    from app.learn.hybrid.goal_binding_ab_score import _verified_cleanup_receipt
    make, _, root = offline_arm
    arm = make(coordinate_space="normalized_0_1000")
    artifact = _run(root / "diagnostic", arm=arm)
    document = json.loads(artifact.path.read_text(encoding="utf-8"))
    receipt = document["cleanup_receipt"]
    assert _verified_cleanup_receipt(receipt, provider_id=arm.provider_id) == receipt
    assert document["provider_phase_cleanup"] == [receipt]
    reference = document["cleanup_evidence_ref"]
    raw = Path(reference["path"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == reference["sha256"]
    full = json.loads(raw)
    observation = full["cleanup_observations"][0]
    assert observation["contract_version"] == "goal_binding_provider_call_cleanup_v1"
    assert observation["request_count"] == 25
    assert json.loads(Path(observation["cleanup_path"]).read_text(encoding="utf-8")) == full
    assert (root / "events.txt").read_text().splitlines() == ["load"] + ["call"] * 25 + ["close"]


@pytest.mark.parametrize("delay,budget,verified", [(2.3, 10, True), (5, 0.1, False)])
def test_managed_close_has_independent_bounded_budget(offline_arm, monkeypatch, delay, budget, verified):
    from app.core import model_server
    from app.learn.hybrid import goal_binding_model_callers as callers
    make, image, root = offline_arm
    fake = root / "fake_provider.py"
    source = fake.read_text(encoding="utf-8")
    source = source.replace("return {'status':'released'}", "return managed_close()")
    source += (
        "\ndef managed_close():\n"
        "    from app.core import model_server\n"
        "    from scripts.model_servers import goal_binding_provider_runtimes as runtimes\n"
        "    obj = object.__new__(runtimes._ManagedIncumbentSession)\n"
        "    obj.closed=False; obj.lease={}; obj.profile={}; obj.selected={}; obj.artifact_root=None\n"
        "    obj.server_scope=type('Scope',(),{'close':lambda self:None})()\n"
        "    obj.hashes={}; obj.identity=None; obj.port=None\n"
        f"    def release(*args): time.sleep({delay}); return {{'lease':{{}}}}\n"
        "    model_server.release_scoped_qwen_model_lease=release\n"
        "    model_server._validate_exact_qwen_cleanup_evidence=lambda *args: None\n"
        "    runtimes._managed_artifact_identity=lambda *args: {}\n"
        "    return obj.close()\n"
    )
    fake.write_text(source, encoding="utf-8")
    monkeypatch.setattr(callers, "_CLEANUP_TIMEOUT_SECONDS", budget, raising=False)
    monkeypatch.setattr(model_server, "_validate_exact_qwen_cleanup_evidence", lambda *args: None)
    arm = make(provider_id="qwen3_vl_8b_q4_k_m", native_output={"kind": "qwen_goal_binding_array_v1"})
    arm.call(image, {"goal": "valid", "incumbent_runtime_request": {}, "incumbent_projection": {}})
    receipt = arm.cleanup()
    assert receipt["verified"] is verified
    evidence = receipt["cleanup_observations"][0]
    if verified:
        assert evidence["runtime_cleanup"]["managed_release"] == {"lease": {}}
        assert evidence["exit_code"] == 0
    else:
        assert "provider cleanup deadline exceeded" in evidence["errors"]
        assert "managed incumbent release evidence is unavailable" in evidence["errors"]


def test_identical_request_across_arms_and_runs_never_overwrites(offline_arm):
    make, image, root = offline_arm
    paths = []
    for arm_id in ("one", "two", "one", "two"):
        arm = make(arm_id=arm_id)
        result = arm.call(image, {"goal": "valid"})
        paths.append(result["request_lineage"]["session_id"])
        assert arm.cleanup()["verified"] is True
    assert len(set(paths)) == 4
    assert len(list(root.rglob("raw/000001.utf8"))) == 4


@pytest.mark.parametrize("goal,kind", [("oom", "provider_oom"), ("timeout", "provider_timeout")])
def test_terminal_failure_cleanly_reaps_and_remaining_goals_unattempted(offline_arm, goal, kind):
    make, image, root = offline_arm
    arm = make(timeout_seconds=2 if goal == "timeout" else 5)
    first = arm.call(image, {"goal": goal})
    second = arm.call(image, {"goal": "valid"})
    assert first["failure"]["kind"] == kind
    assert first["failure"]["attempted"] is True
    assert second["failure"]["kind"] == "provider_unavailable_after_" + kind
    assert second["failure"]["attempted"] is False
    assert arm.cleanup()["verified"] is True
    assert (root / "events.txt").read_text().splitlines().count("call") == 1


def test_new_gpu_owner_or_unobservable_probe_blocks_cleanup(offline_arm, monkeypatch):
    from app.learn.hybrid import goal_binding_model_callers as callers
    make, image, root = offline_arm
    arm = make()
    arm.call(image, {"goal": "valid"})
    monkeypatch.setattr(callers, "_gpu_ownership_snapshot", lambda: {"status": "verified", "owners": [{"pid": 999, "create_time_ns": 777, "used_memory_mib": None}]})
    receipt = arm.cleanup()
    assert receipt["verified"] is False
    assert receipt["owned_processes"][0]["pid"] == 999


def test_gguf_uses_host_python_not_server_executable(tmp_path):
    from app.learn.hybrid.goal_binding_model_callers import _worker_python
    assert _worker_python({"runtime": {"kind": "llama_cpp"}}, tmp_path) == Path(sys.executable).resolve()


def test_wddm_gpu_na_is_unknown_not_zero_and_query_failure_is_unavailable(monkeypatch):
    from types import SimpleNamespace
    from app.learn.hybrid import goal_binding_model_callers as callers, windows_process_scope
    monkeypatch.setattr(windows_process_scope, "_identity_for_pid", lambda pid: {"pid": pid, "create_time_ns": 33})
    monkeypatch.setattr(callers.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout=b"123, [N/A]\n"))
    observation = callers._gpu_ownership_snapshot()
    assert observation["owners"] == [{"pid": 123, "create_time_ns": 33, "used_memory_mib": None}]
    def fail(*args, **kwargs):
        raise callers.subprocess.CalledProcessError(1, "nvidia-smi")
    monkeypatch.setattr(callers.subprocess, "run", fail)
    assert callers._gpu_ownership_snapshot()["status"] == "unavailable"


def test_dependency_load_failure_is_explicit_not_inference_and_persisted(offline_arm):
    make, image, root = offline_arm
    (root / "fake_provider.py").write_text("def open_session(**kwargs):\n    raise ImportError('missing dependency')\n", encoding="utf-8")
    arm = make()
    first = arm.call(image, {"goal": "valid"})
    second = arm.call(image, {"goal": "valid"})
    assert first["failure"]["kind"] == "provider_dependency_failure"
    assert first["failure"]["attempted"] is False
    assert second["failure"]["kind"] == "provider_unavailable_after_provider_dependency_failure"
    assert len(list(root.rglob("responses/*.json"))) == 2
    assert arm.cleanup()["verified"] is True


def test_probe_always_cleans_up_when_call_raises(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from app.learn.hybrid import goal_binding_model_callers as callers
    cleaned = []
    def call(*args):
        raise ValueError("bad capture")
    monkeypatch.setattr(callers, "make_goal_binding_arm", lambda **kw: SimpleNamespace(call=call, cleanup=lambda: cleaned.append(True)))
    with pytest.raises(ValueError, match="bad capture"):
        callers.probe_goal_binding_profile(profile={}, image_path=tmp_path / "x.png", artifact_dir=tmp_path)
    assert cleaned == [True]


def test_official_ui_loader_constructs_once_and_two_inferences(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from scripts.model_servers import goal_binding_provider_runtimes as runtimes
    events = []
    class Model:
        device = "cuda"
        def to(self, device): return self
        def eval(self): return self
        def generate(self, **kwargs): events.append(("generate", kwargs)); return [[1, 2]]
    class Processor:
        def apply_chat_template(self, messages, **kwargs): events.append(("messages", messages)); return "prompt"
        def __call__(self, **kwargs): return {"input_ids": SimpleNamespace(shape=(1, 1))}
        def batch_decode(self, *args, **kwargs): return ["[250,375]"]
    def load_model(*args, **kwargs): events.append(("load", kwargs)); return Model()
    fake_transformers = SimpleNamespace(AutoModelForImageTextToText=SimpleNamespace(from_pretrained=load_model), AutoProcessor=SimpleNamespace(from_pretrained=lambda *a, **kw: Processor()))
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(bfloat16="bf16", cuda=SimpleNamespace(is_available=lambda: False)))
    monkeypatch.setitem(sys.modules, "qwen_vl_utils", SimpleNamespace(process_vision_info=lambda messages: ([messages[0]["content"][0]["image"]], None)))
    monkeypatch.setattr(runtimes, "verified_artifact_paths", lambda *a: {"model": tmp_path / "model.safetensors"})
    profile = {"provider_id": "ui_venus_1_5_2b_f16", "preprocessing": {"source_revision": "inclusionAI/UI-Venus@192a9247ad1129279ba1d6c263d4c9e7ecef3644"}}
    session = runtimes.open_session(profile=profile, artifact_root=tmp_path, session_root=tmp_path, scope_name="unused", listener_port=None)
    image = tmp_path / "screen.png"
    Image.new("RGB", (2, 2)).save(image)
    for _ in range(2):
        result = session(image_path=image, goal="Open.", profile=profile, artifact_root=tmp_path)
        assert result["raw_native_output"] == "[250,375]"
    session.close()
    assert [name for name, value in events].count("load") == 1
    assert [name for name, value in events].count("generate") == 2
    assert events[0][1]["local_files_only"] is True
    assert events[0][1]["torch_dtype"] == "bf16"
    messages = next(value for name, value in events if name == "messages")
    assert messages[0]["content"][1]["text"] == "Output the center point of the position corresponding to the following instruction: \nOpen. \n\nThe output should just be the coordinates of a point, in the format [x,y]. Additionally, if the task is infeasible (e.g., the task is not related to the image), the output should be [-1,-1]."


def test_tensor_telemetry_projection_preserves_order():
    from scripts.model_servers.goal_binding_provider_runtimes import _json_safe
    class Array:
        def tolist(self): return [[0.9, 0.2], [0.1, 0.3]]
    assert _json_safe({"topk_points": Array()}) == {"topk_points": [[0.9, 0.2], [0.1, 0.3]]}


def test_phi_integer_resize_ratio_is_used_once():
    from scripts.model_servers.goal_binding_provider_runtimes import phi_image_geometry
    geometry = phi_image_geometry(801, 600)
    assert geometry == {"original_dimensions": [801, 600], "canvas_dimensions": [1680, 1008], "resized_dimensions": [1345, 1008], "reshape_ratio": 1345 / 801}
    point = worker._parse_phi("<x>5000</x><y>5000</y>", width=801, height=600)
    assert point["point"] == [840 / (1345 / 801), 504 / (1345 / 801)]


def test_llama_foreign_listener_rejected_before_health_or_image(monkeypatch):
    from scripts.model_servers import goal_binding_provider_runtimes as runtimes
    from app.learn.hybrid import windows_process_scope
    monkeypatch.setattr(windows_process_scope, "_listeners", lambda ports: [{"port": 12345, "pid": 999}])
    monkeypatch.setattr(runtimes.urllib_request, "urlopen", lambda *a, **kw: pytest.fail("foreign listener must not receive HTTP"))
    with pytest.raises(runtimes.ProviderIntegrityError, match="listener"):
        runtimes._wait_ready(port=12345, deadline=__import__("time").monotonic() + 1, identity={"pid": 42, "create_time_ns": 99}, scope_name="unused", model_id="model")


def test_phi_vllm_fixed_loader_parameters_and_native_windows_failure(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from scripts.model_servers import goal_binding_provider_runtimes as runtimes
    profile = {"provider_id": "phi_ground_any_bf16", "preprocessing": {"source_revision": "microsoft/Phi-Ground@395640833d9b4748446d007257d87924df733ecb"}}
    monkeypatch.setattr(runtimes, "verified_artifact_paths", lambda *a: {"model": tmp_path / "model.safetensors"})
    with pytest.raises(RuntimeError, match="platform_incompatible"):
        runtimes._load_dependencies(profile, tmp_path)
    monkeypatch.setattr(runtimes.sys, "platform", "linux")
    calls = []
    monkeypatch.setitem(sys.modules, "vllm", SimpleNamespace(LLM=lambda **kw: calls.append(kw) or object(), SamplingParams=object))
    runtimes._load_dependencies(profile, tmp_path)
    assert calls[0]["max_model_len"] == 8192
    assert calls[0]["max_num_seqs"] == 10
    assert calls[0]["tensor_parallel_size"] == 1


def test_managed_incumbent_session_keeps_one_lease_and_exact_raw(monkeypatch, tmp_path):
    from app.core import model_server
    from scripts.model_servers import goal_binding_provider_runtimes as runtimes
    events = []
    lease = {"server_process_identity": {"pid": 42, "create_time_ns": 99}, "server_socket": {"port": 12345}}
    monkeypatch.setattr(model_server, "ensure_and_acquire_scoped_qwen_model_lease", lambda **kw: events.append("load") or lease)
    monkeypatch.setattr(model_server, "run_qwen_projection_model_raw", lambda **kw: events.append(kw["model_lease"]) or ' \n[] ')
    monkeypatch.setattr(model_server, "release_scoped_qwen_model_lease", lambda selected, reason: events.append("close") or {"status": "released"})
    monkeypatch.setattr(model_server, "_validate_exact_qwen_cleanup_evidence", lambda result, selected: selected)
    monkeypatch.setattr(runtimes, "_verify_listener", lambda **kw: True, raising=False)
    monkeypatch.setattr(runtimes, "_managed_artifact_identity", lambda *a: {"model": "a" * 64}, raising=False)
    monkeypatch.setattr(model_server, "profile_for_stage", lambda *a: {"port": 12345})
    session = runtimes._ManagedIncumbentSession({"timeout_seconds": 3}, tmp_path, tmp_path, "scope")
    image = tmp_path / "image.png"
    Image.new("RGB", (2, 2)).save(image)
    for _ in range(2):
        assert session(image_path=image, incumbent_projection={}, incumbent_request={})["raw_native_output"] == ' \n[] '
    session.close()
    assert events == ["load", lease, lease, "close"]


def test_llama_session_owns_one_scoped_child_for_two_requests(monkeypatch, tmp_path):
    from scripts.model_servers import goal_binding_provider_runtimes as runtimes
    from app.learn.hybrid import windows_process_scope as scope_api
    from uuid import uuid4
    if not scope_api.windows_process_scope_available():
        pytest.skip("Windows Job unavailable")
    name = scope_api.benchmark_worker_scope_name_v1(authority_kind="test_only", run_id="llama-test", stage="goal_binding", operation_id="llama", worker_id="fake", payload_sha256="a" * 64, execution_nonce=uuid4().hex)
    owner = scope_api.WindowsProcessScope(name, create=True)
    actual_spawn = scope_api.spawn_process_in_scope
    spawned, posts = [], []
    def spawn(command, **kwargs):
        spawned.append(command)
        return actual_spawn([sys._base_executable, "-c", "import time; time.sleep(30)"], **kwargs)
    monkeypatch.setattr(scope_api, "spawn_process_in_scope", spawn)
    monkeypatch.setattr(runtimes, "verified_artifact_paths", lambda *a: {"runtime": tmp_path / "llama.exe", "model": tmp_path / "model.gguf", "mmproj": tmp_path / "mmproj.gguf"})
    monkeypatch.setattr(runtimes, "_wait_ready", lambda **kw: None)
    monkeypatch.setattr(scope_api, "_listeners", lambda ports: [{"port": 12345, "pid": session.identity["pid"]}])
    monkeypatch.setattr(runtimes, "_post_json", lambda **kw: posts.append(kw) or {"choices": [{"message": {"content": "[1,2]"}}]})
    session = None
    try:
        session = runtimes._LlamaSession({"model_id": "fake", "timeout_seconds": 5}, tmp_path, tmp_path, name, 12345)
        image = tmp_path / "image.png"
        Image.new("RGB", (2, 2)).save(image)
        for _ in range(2):
            assert session(image_path=image, goal="Open")["raw_native_output"] == "[1,2]"
        assert len(spawned) == 1 and len(posts) == 2
        assert session.identity["pid"] in owner.pids()
        receipt = session.close()
        assert receipt["exit_code"] is not None
    finally:
        if session:
            session.close()
        owner.close()


def test_worker_capture_mutation_during_inference_is_integrity_failure(monkeypatch, tmp_path):
    request = payload(tmp_path)
    def mutate(**kwargs):
        Path(request["image_path"]).write_bytes(b"changed")
        return "[250,375]"
    monkeypatch.setattr(worker, "_dispatch_provider", mutate)
    with pytest.raises(ValueError, match="screenshot.*changed"):
        worker._run_provider_once(request)


def test_gui_worker_top1_invalid_never_selects_valid_top2(monkeypatch, tmp_path):
    from app.learn.hybrid.goal_binding_native_adapters import parse_gui_actor_top1
    request = payload(tmp_path, "gui_actor_3b_bf16")
    monkeypatch.setattr(worker, "_dispatch_provider", lambda **kw: {"topk_points": [[2, 2], [0.2, 0.3]], "telemetry": [1, 2]})
    result = worker._run_provider_once(request)
    proposal = parse_gui_actor_top1(result["parsed_native"], goal_index=0, profile={"contract_version": "goal_binding_native_profile_v1", "provider_id": "gui_actor_3b_bf16", "native_shape": "gui_actor_topk_points_v1", "coordinate_space": "normalized_0_1"})
    assert proposal.status == "PROVIDER_FAILURE"
    assert proposal.point is None


def test_listener_probe_uncertainty_is_infrastructure_failure(monkeypatch):
    from app.learn.hybrid import windows_process_scope
    from scripts.model_servers import goal_binding_provider_runtimes as runtimes
    def fail(ports):
        raise OSError("cannot inspect listeners")
    monkeypatch.setattr(windows_process_scope, "_listeners", fail)
    with pytest.raises(runtimes.ProviderIntegrityError, match="listener"):
        runtimes._verify_listener(port=12345, identity={"pid": 42, "create_time_ns": 99}, scope_name="unused")


def test_same_size_mailbox_goal_tamper_is_rejected(offline_arm, monkeypatch):
    make, image, root = offline_arm
    original = worker.atomic_write
    def tamper(path, body):
        if path.parent.name == "requests" and path.suffix == ".json":
            request = json.loads(body)
            request["payload"]["goal"] = "other"
            body = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        original(path, body)
    monkeypatch.setattr(worker, "atomic_write", tamper)
    arm = make()
    with pytest.raises(RuntimeError, match="session mismatch"):
        arm.call(image, {"goal": "valid"})
    assert arm.cleanup()["verified"] is False


def test_source_pin_cannot_be_transferred_to_another_repository(monkeypatch, tmp_path):
    from scripts.model_servers import goal_binding_provider_runtimes as runtimes
    monkeypatch.setattr(runtimes, "verified_artifact_paths", lambda *a: {"model": tmp_path / "model.safetensors"})
    profile = {"provider_id": "phi_ground_any_bf16", "preprocessing": {"source_revision": "other/repo@395640833d9b4748446d007257d87924df733ecb"}}
    with pytest.raises(runtimes.ProviderIntegrityError, match="source revision"):
        runtimes._load_dependencies(profile, tmp_path)
