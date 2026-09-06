from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path


def test_checkpoint_role_is_a_shard_but_transformers_needs_its_directory(tmp_path):
    from app.learn.hybrid.gui_actor_current_source import _checkpoint_directory
    checkpoint = tmp_path / "model"
    checkpoint.mkdir()
    (checkpoint / "model-00001-of-00002.safetensors").write_bytes(b"sealed shard")
    (checkpoint / "config.json").write_text("{}", encoding="utf-8")
    receipt = {"verified_roles": {"model": {"relative_path": "model/model-00001-of-00002.safetensors"}}}
    assert _checkpoint_directory(tmp_path, receipt) == checkpoint
import subprocess

import pytest


def _profile() -> dict[str, object]:
    return {
        "provider_id": "gui_actor_3b_bf16",
        "repository_id": "microsoft/GUI-Actor-3B-Qwen2.5-VL",
        "upstream_revision": "5fb97348752cb3d50be9709f47d9ae6c99725949",
        "artifact_manifest": {"status": "verified", "relative_path": "reports/deployment.json", "sha256": "a" * 64},
        "artifacts": [],
        "runtime": {"isolated_runtime_path": "artifacts/runtime/Scripts/python.exe", "kind": "gui_actor_transformers_sdpa_windows_v1"},
        "native_output": {"kind": "gui_actor_topk_points_v1", "raw_format": "utf8_native"},
        "coordinate_space": "normalized_0_1",
        "preprocessing": {"source_revision": "microsoft/GUI-Actor@d98d1bbd01862f9112114b83b032f492c365a173"},
        "timeout_seconds": 12,
        "max_output_bytes": 16384,
    }


def _verified(root: Path) -> dict[str, object]:
    return {
        "contract_version": "gui_actor_current_source_receipt_v1",
        "source_binding": "current_source_external_v1",
        "frozen_deployment_seal": "not_invoked",
        "runtime_python": str(root / "artifacts/runtime/Scripts/python.exe"),
        "code_identity": {"app/learn/hybrid/model_test_storage.py": "b" * 64},
    }


def test_current_source_verifier_rejects_unverified_deployment_before_model_load(tmp_path: Path) -> None:
    from app.learn.hybrid import gui_actor_current_source as subject

    source = tmp_path / "official-source.json"
    source.write_text(json.dumps({
        "contract_version": "goal_binding_gui_actor_source_identity_v1",
        "official_source_revision": "microsoft/GUI-Actor@d98d1bbd01862f9112114b83b032f492c365a173",
        "project_revision": "ca138459132fe1b88d5923af2842f11711efbce9",
        "official_source_files": {},
        "code_files": {"app/learn/hybrid/model_test_storage.py": "0" * 64},
    }), encoding="utf-8")

    with pytest.raises(subject.GuiActorCurrentSourceError, match="deployment hash differs"):
        subject.verify_current_source_identity(_profile(), tmp_path)


def test_parent_runner_accepts_only_nonce_bound_current_child_response(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.learn.hybrid import gui_actor_current_source as subject

    image = tmp_path / "screen.png"
    image.write_bytes(b"known-public-image")
    root = tmp_path / "models"
    runtime = root / "artifacts/runtime/Scripts/python.exe"
    runtime.parent.mkdir(parents=True)
    runtime.write_bytes(b"python")
    out = tmp_path / "out"
    monkeypatch.setattr(subject, "load_gui_actor_profile", lambda _path: _profile())
    monkeypatch.setattr(subject, "verify_current_source_identity", lambda _profile, _root, **_kwargs: _verified(root))
    monkeypatch.setattr(subject, "inventory_storage_bytes", lambda _root: 1024)
    monkeypatch.setattr(subject, "_gpu_preflight", lambda: {"status": "ready", "required_free_mib": 10_240, "available_free_mib": 11_000, "utilization_percent": 0})

    def fake_child(*, command, cwd, stdout_path, stderr_path, timeout_seconds):
        assert command[0] == str(root / "artifacts/runtime/Scripts/python.exe")
        assert command[1:3] == ["-B", str(tmp_path / "scripts/run_learning_gui_actor_once.py")]
        assert "--child" in command
        invocation = json.loads(Path(command[command.index("--invocation") + 1]).read_text(encoding="utf-8"))
        response = {
            "contract_version": "gui_actor_current_source_child_result_v1",
            "invocation_nonce": invocation["invocation_nonce"],
            "image_sha256": invocation["image_sha256"],
            "target_sha256": invocation["target_sha256"],
            "raw_output_utf8": '{"topk_points":[[0.5,0.4]]}',
            "provider_id": "gui_actor_3b_bf16",
            "native_profile": invocation["native_profile"],
            "current_source_receipt": invocation["current_source_receipt"],
        }
        result_path = Path(command[command.index("--child-result") + 1])
        result_path.write_text(json.dumps(response), encoding="utf-8")
        stdout_path.write_bytes(b"child stdout")
        stderr_path.write_bytes(b"")
        return {"exit_code": 0, "cleanup": {"status": "verified_exact_child_exited", "pid": 321}}

    monkeypatch.setattr(subject, "_run_exact_child", fake_child)
    result = subject.run_gui_actor_once(
        project_root=tmp_path,
        image_path=image,
        target_text="known target",
        artifact_root=root,
        out_dir=out,
    )

    assert result["raw_output_utf8"] == '{"topk_points":[[0.5,0.4]]}'
    assert result["native_output_ref"]["sha256"] == sha256(result["raw_output_utf8"].encode("utf-8")).hexdigest()
    assert result["source_score"] is None
    assert result["execute_binding_enabled"] is False
    assert result["child_exit_code"] == 0
    assert result["cleanup"]["status"] == "verified_exact_child_exited"
    assert Path(result["stdout_trace"]["path"]).read_bytes() == b"child stdout"


def test_parent_runner_rejects_child_provenance_mismatch_before_return(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.learn.hybrid import gui_actor_current_source as subject

    image = tmp_path / "screen.png"
    image.write_bytes(b"known-public-image")
    root = tmp_path / "models"
    runtime = root / "artifacts/runtime/Scripts/python.exe"
    runtime.parent.mkdir(parents=True)
    runtime.write_bytes(b"python")
    monkeypatch.setattr(subject, "load_gui_actor_profile", lambda _path: _profile())
    monkeypatch.setattr(subject, "verify_current_source_identity", lambda _profile, _root, **_kwargs: _verified(root))
    monkeypatch.setattr(subject, "inventory_storage_bytes", lambda _root: 1024)
    monkeypatch.setattr(subject, "_gpu_preflight", lambda: {"status": "ready", "required_free_mib": 10_240, "available_free_mib": 11_000, "utilization_percent": 0})

    def fake_child(*, command, cwd, stdout_path, stderr_path, timeout_seconds):
        invocation = json.loads(Path(command[command.index("--invocation") + 1]).read_text(encoding="utf-8"))
        bad = {"contract_version": "gui_actor_current_source_child_result_v1", "invocation_nonce": "wrong", "image_sha256": invocation["image_sha256"], "target_sha256": invocation["target_sha256"], "raw_output_utf8": "{}", "provider_id": "gui_actor_3b_bf16", "native_profile": invocation["native_profile"], "current_source_receipt": invocation["current_source_receipt"]}
        Path(command[command.index("--child-result") + 1]).write_text(json.dumps(bad), encoding="utf-8")
        stdout_path.write_bytes(b""); stderr_path.write_bytes(b"")
        return {"exit_code": 0, "cleanup": {"status": "verified_exact_child_exited", "pid": 321}}

    monkeypatch.setattr(subject, "_run_exact_child", fake_child)
    with pytest.raises(subject.GuiActorCurrentSourceError, match="nonce"):
        subject.run_gui_actor_once(project_root=tmp_path, image_path=image, target_text="known target", artifact_root=root, out_dir=tmp_path / "out")


def test_exact_child_timeout_kills_and_records_exact_cleanup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.learn.hybrid import gui_actor_current_source as subject

    class FakeChild:
        pid = 456
        returncode = None
        def wait(self, timeout=None):
            if self.returncode is None:
                raise subprocess.TimeoutExpired(["python"], timeout)
            return self.returncode
        def kill(self):
            self.returncode = -9

    child = FakeChild()
    monkeypatch.setattr(subject.subprocess, "Popen", lambda *args, **kwargs: child)
    with pytest.raises(subject.GuiActorCurrentSourceError, match="timed out") as error:
        subject._run_exact_child(
            command=["python", "child.py"], cwd=tmp_path,
            stdout_path=tmp_path / "stdout.bin", stderr_path=tmp_path / "stderr.bin",
            timeout_seconds=1,
        )
    assert child.returncode == -9
    assert error.value.child["cleanup"]["status"] == "verified_exact_child_killed"


def test_exact_child_large_create_time_is_decimal_text_without_rounding() -> None:
    from app.learn.hybrid import gui_actor_current_source as subject

    class FakeChild:
        pid = 457
        returncode = None

        def kill(self):
            self.returncode = -9

        def wait(self, timeout=None):
            return self.returncode

    create_time_ns = 1_788_000_000_000_000_123
    state = subject._kill_exact_child(
        FakeChild(), created_ns=create_time_ns, status="timed_out",
    )
    expected = "1788000000000000123"
    assert state["create_time_ns"] == expected
    assert state["cleanup"]["create_time_ns"] == expected
    assert isinstance(state["create_time_ns"], str)


def test_startup_failure_is_persisted_after_new_output_directory_is_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import gui_actor_current_source as subject

    image = tmp_path / "screen.png"
    image.write_bytes(b"known-public-image")
    root = tmp_path / "models"
    root.mkdir()
    monkeypatch.setattr(subject, "inventory_storage_bytes", lambda _root: 1024)
    monkeypatch.setattr(subject, "load_gui_actor_profile", lambda _path: _profile())
    monkeypatch.setattr(subject, "_gpu_preflight", lambda: (_ for _ in ()).throw(subject.GuiActorCurrentSourceError("GPU preflight rejected")))

    with pytest.raises(subject.GuiActorCurrentSourceError, match="GPU preflight"):
        subject.run_gui_actor_once(
            project_root=tmp_path, image_path=image, target_text="known target",
            artifact_root=root, out_dir=tmp_path / "out",
        )
    failure = json.loads((tmp_path / "out" / "failure-result.json").read_text(encoding="utf-8"))
    assert failure["contract_version"] == "gui_actor_current_source_failure_v1"
    assert failure["outcome"] == "failed"
    assert failure["failure_stage"] == "gpu_preflight"
    assert failure["child"]["cleanup"]["status"] == "not_started"
    assert failure["stdout_trace"] is None
    assert not (tmp_path / "out" / "result.json").exists()


def test_nonzero_child_persists_cleanup_and_trace_before_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import gui_actor_current_source as subject

    image = tmp_path / "screen.png"
    image.write_bytes(b"known-public-image")
    root = tmp_path / "models"
    runtime = root / "artifacts/runtime/Scripts/python.exe"
    runtime.parent.mkdir(parents=True)
    runtime.write_bytes(b"python")
    monkeypatch.setattr(subject, "load_gui_actor_profile", lambda _path: _profile())
    monkeypatch.setattr(subject, "verify_current_source_identity", lambda _profile, _root, **_kwargs: _verified(root))
    monkeypatch.setattr(subject, "inventory_storage_bytes", lambda _root: 1024)
    monkeypatch.setattr(subject, "_gpu_preflight", lambda: {"status": "ready"})

    def failed_child(*, stdout_path, stderr_path, **_kwargs):
        stdout_path.write_bytes(b"child stdout")
        stderr_path.write_bytes(b"child stderr")
        return {
            "exit_code": 7,
            "cleanup": {
                "status": "verified_exact_child_exited",
                "pid": 999,
                "create_time_ns": 123,
                "exit_code": 7,
            },
        }

    monkeypatch.setattr(subject, "_run_exact_child", failed_child)
    with pytest.raises(subject.GuiActorCurrentSourceError, match="unsuccessfully"):
        subject.run_gui_actor_once(
            project_root=tmp_path, image_path=image, target_text="known target",
            artifact_root=root, out_dir=tmp_path / "out",
        )
    failure = json.loads((tmp_path / "out" / "failure-result.json").read_text(encoding="utf-8"))
    assert failure["failure_stage"] == "child_exit"
    assert failure["child"]["exit_code"] == 7
    assert failure["child"]["cleanup"]["pid"] == 999
    assert Path(failure["stdout_trace"]["path"]).read_bytes() == b"child stdout"
    assert not (tmp_path / "out" / "result.json").exists()


def test_timeout_persists_exact_child_cleanup_before_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import gui_actor_current_source as subject

    image = tmp_path / "screen.png"
    image.write_bytes(b"known-public-image")
    root = tmp_path / "models"
    runtime = root / "artifacts/runtime/Scripts/python.exe"
    runtime.parent.mkdir(parents=True)
    runtime.write_bytes(b"python")
    monkeypatch.setattr(subject, "load_gui_actor_profile", lambda _path: _profile())
    monkeypatch.setattr(subject, "verify_current_source_identity", lambda _profile, _root, **_kwargs: _verified(root))
    monkeypatch.setattr(subject, "inventory_storage_bytes", lambda _root: 1024)
    monkeypatch.setattr(subject, "_gpu_preflight", lambda: {"status": "ready"})

    def timed_out_child(*, stdout_path, stderr_path, **_kwargs):
        stdout_path.write_bytes(b"partial stdout")
        stderr_path.write_bytes(b"partial stderr")
        error = subject.GuiActorCurrentSourceError("GUIActor child timed out and was killed")
        error.child = {
            "status": "timed_out",
            "pid": 1001,
            "create_time_ns": 456,
            "exit_code": -9,
            "cleanup": {"status": "verified_exact_child_killed", "pid": 1001, "exit_code": -9},
        }
        raise error

    monkeypatch.setattr(subject, "_run_exact_child", timed_out_child)
    with pytest.raises(subject.GuiActorCurrentSourceError, match="timed out"):
        subject.run_gui_actor_once(
            project_root=tmp_path, image_path=image, target_text="known target",
            artifact_root=root, out_dir=tmp_path / "out",
        )
    failure = json.loads((tmp_path / "out" / "failure-result.json").read_text(encoding="utf-8"))
    assert failure["failure_stage"] == "child_timeout"
    assert failure["child"]["cleanup"]["status"] == "verified_exact_child_killed"
    assert Path(failure["stderr_trace"]["path"]).read_bytes() == b"partial stderr"
    assert not (tmp_path / "out" / "result.json").exists()


def test_invalid_utf8_success_child_trace_persists_raw_failure_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import gui_actor_current_source as subject

    image = tmp_path / "screen.png"
    image.write_bytes(b"known-public-image")
    root = tmp_path / "models"
    runtime = root / "artifacts/runtime/Scripts/python.exe"
    runtime.parent.mkdir(parents=True)
    runtime.write_bytes(b"python")
    monkeypatch.setattr(subject, "load_gui_actor_profile", lambda _path: _profile())
    monkeypatch.setattr(subject, "verify_current_source_identity", lambda _profile, _root, **_kwargs: _verified(root))
    monkeypatch.setattr(subject, "inventory_storage_bytes", lambda _root: 1024)
    monkeypatch.setattr(subject, "_gpu_preflight", lambda: {"status": "ready"})

    def invalid_stdout_child(*, command, stdout_path, stderr_path, **_kwargs):
        invocation = json.loads(Path(command[command.index("--invocation") + 1]).read_text(encoding="utf-8"))
        response = {
            "contract_version": "gui_actor_current_source_child_result_v1",
            "invocation_nonce": invocation["invocation_nonce"],
            "image_sha256": invocation["image_sha256"],
            "target_sha256": invocation["target_sha256"],
            "raw_output_utf8": "{}",
            "provider_id": "gui_actor_3b_bf16",
            "native_profile": invocation["native_profile"],
            "current_source_receipt": invocation["current_source_receipt"],
        }
        Path(command[command.index("--child-result") + 1]).write_text(json.dumps(response), encoding="utf-8")
        stdout_path.write_bytes(b"\xff")
        stderr_path.write_bytes(b"child stderr")
        return {
            "exit_code": 0,
            "cleanup": {"status": "verified_exact_child_exited", "pid": 1003, "exit_code": 0},
        }

    monkeypatch.setattr(subject, "_run_exact_child", invalid_stdout_child)
    with pytest.raises(subject.GuiActorCurrentSourceError, match="not UTF-8"):
        subject.run_gui_actor_once(
            project_root=tmp_path, image_path=image, target_text="known target",
            artifact_root=root, out_dir=tmp_path / "out",
        )
    failure = json.loads((tmp_path / "out" / "failure-result.json").read_text(encoding="utf-8"))
    assert failure["failure_stage"] == "trace_verification"
    assert failure["child"]["cleanup"]["pid"] == 1003
    assert failure["stdout_trace"]["encoding"] == "invalid-utf8"
    assert failure["stdout_trace"]["sha256"] == sha256(b"\xff").hexdigest()
    assert (tmp_path / "out" / "child.stdout.utf8").read_bytes() == b"\xff"
    assert not (tmp_path / "out" / "result.json").exists()


def test_interrupt_persists_owned_child_cleanup_then_reraises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import gui_actor_current_source as subject

    image = tmp_path / "screen.png"
    image.write_bytes(b"known-public-image")
    root = tmp_path / "models"
    runtime = root / "artifacts/runtime/Scripts/python.exe"
    runtime.parent.mkdir(parents=True)
    runtime.write_bytes(b"python")
    monkeypatch.setattr(subject, "load_gui_actor_profile", lambda _path: _profile())
    monkeypatch.setattr(subject, "verify_current_source_identity", lambda _profile, _root, **_kwargs: _verified(root))
    monkeypatch.setattr(subject, "inventory_storage_bytes", lambda _root: 1024)
    monkeypatch.setattr(subject, "_gpu_preflight", lambda: {"status": "ready"})

    def interrupted_child(*, stdout_path, stderr_path, **_kwargs):
        stdout_path.write_bytes(b"partial stdout")
        stderr_path.write_bytes(b"partial stderr")
        error = KeyboardInterrupt()
        error.child = {
            "status": "interrupted",
            "pid": 1002,
            "create_time_ns": 789,
            "exit_code": -9,
            "cleanup": {"status": "verified_exact_child_killed", "pid": 1002, "exit_code": -9},
        }
        raise error

    monkeypatch.setattr(subject, "_run_exact_child", interrupted_child)
    with pytest.raises(KeyboardInterrupt):
        subject.run_gui_actor_once(
            project_root=tmp_path, image_path=image, target_text="known target",
            artifact_root=root, out_dir=tmp_path / "out",
        )
    failure = json.loads((tmp_path / "out" / "failure-result.json").read_text(encoding="utf-8"))
    assert failure["failure_stage"] == "interrupted"
    assert failure["child"]["cleanup"]["pid"] == 1002


def test_cli_accepts_the_explicit_model_start_marker_without_gating(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import run_learning_gui_actor_once as cli

    image = tmp_path / "screen.png"
    image.write_bytes(b"x")
    received: dict[str, object] = {}

    def fake_run(**kwargs: object) -> dict[str, object]:
        received.update(kwargs)
        return {}

    monkeypatch.setattr(cli, "run_gui_actor_once", fake_run)
    cli.main(["--image", str(image), "--goal", "target", "--out", str(tmp_path / "out")])
    assert received["image_path"] == image
    assert received["target_text"] == "target"
    assert received["artifact_root"] == Path("E:/") / "\u6a21\u578b\u6d4b\u8bd5"


def test_gpu_preflight_requires_ten_gib_and_low_utilization(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.learn.hybrid import gui_actor_current_source as subject

    monkeypatch.setattr(subject.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, b"11000, 4\n", b""))
    ready = subject._gpu_preflight()
    assert ready["status"] == "ready"
    assert ready["required_free_mib"] == 10_240
    monkeypatch.setattr(subject.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, b"10239, 4\n", b""))
    with pytest.raises(subject.GuiActorCurrentSourceError, match="free GPU memory"):
        subject._gpu_preflight()
