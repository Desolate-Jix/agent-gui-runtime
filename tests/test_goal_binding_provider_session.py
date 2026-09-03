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
        selected = dict(profile, **changes)
        arm = callers.make_goal_binding_arm(profile=selected, artifact_dir=tmp_path)
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
