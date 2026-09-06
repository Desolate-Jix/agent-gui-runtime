from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest


def test_parse_vista_normalized_pair_accepts_only_finite_bare_pair() -> None:
    from app.learn.hybrid.vista_current_source import (
        VistaCurrentSourceError,
        parse_vista_normalized_pair,
    )

    assert parse_vista_normalized_pair("[0,1000]") == [0.0, 1000.0]
    for raw in ('{"point":[1,2]}', "[1,2,3]", "[true,2]", "[1e999,2]", "[-1,2]", "[1,1001]"):
        with pytest.raises(VistaCurrentSourceError):
            parse_vista_normalized_pair(raw)


def test_native_request_preserves_exact_target_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import vista_current_source as subject

    seen: list[bytes] = []

    class Response:
        def read(self, _limit):
            return b'{"choices":[{"message":{"content":"[1,2]"}}]}'

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    def open_request(request, timeout):
        seen.append(request.data)
        return Response()

    monkeypatch.setattr(subject.urlrequest, "urlopen", open_request)
    assert subject._request_native_pair(
        port=14321, roi_bytes=b"roi", target_text=" exact target ",
        timeout_seconds=1, response_path=tmp_path / "response.bin",
    ) == "[1,2]"
    payload = json.loads(seen[0].decode("utf-8"))
    assert payload["messages"][0]["content"][0]["text"].startswith(" exact target \n")


def test_verifier_rejects_arbitrary_model_path_before_any_server_start(tmp_path: Path) -> None:
    from app.learn.hybrid import vista_current_source as subject

    with pytest.raises(subject.VistaCurrentSourceError, match="trusted local asset"):
        subject.verify_vista_current_source(project_root=Path.cwd(), model_path=tmp_path)


def test_verifier_rejects_pinned_profile_drift_before_model_hashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import vista_current_source as subject

    monkeypatch.setattr(subject, "_PROFILE_SHA256", "0" * 64)
    with pytest.raises(subject.VistaCurrentSourceError, match="profile hash differs"):
        subject.verify_vista_current_source(
            project_root=Path.cwd(), model_path=subject.DEFAULT_MODEL_PATH,
        )


def test_verifier_rejects_pinned_server_source_drift_before_model_hashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import vista_current_source as subject

    monkeypatch.setattr(subject, "_SERVER_SHA256", "0" * 64)
    with pytest.raises(subject.VistaCurrentSourceError, match="server hash differs"):
        subject.verify_vista_current_source(
            project_root=Path.cwd(), model_path=subject.DEFAULT_MODEL_PATH,
        )


def test_auxiliary_config_and_tokenizer_identity_is_recorded(tmp_path: Path) -> None:
    from app.learn.hybrid import vista_current_source as subject

    for name in subject._AUXILIARY_MODEL_FILES:
        (tmp_path / name).write_text(name, encoding="utf-8")
    identity = subject._auxiliary_model_identity(tmp_path)
    assert [item["name"] for item in identity] == list(subject._AUXILIARY_MODEL_FILES)
    assert identity[0]["sha256"] == sha256(b"config.json").hexdigest()


class _FakeChild:
    pid = 12001
    returncode = None

    def poll(self):
        return self.returncode

    def kill(self):
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode if self.returncode is not None else 0


def _receipt(root: Path) -> dict[str, object]:
    return {
        "contract_version": "vista_current_source_receipt_v1",
        "provider_id": "vista_4b",
        "runtime_python": str(root / "python.exe"),
        "profile": {"path": "profile", "sha256": "a" * 64, "profile_id": "vista_4b_transformers"},
        "server": {"path": "server", "sha256": "b" * 64},
        "code_identity": {"app/learn/hybrid/vista_current_source.py": "c" * 64},
        "model": {"path": "model", "index_sha256": "d" * 64, "shards": []},
    }


def _prepare_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path]:
    from app.learn.hybrid import vista_current_source as subject

    image = tmp_path / "roi.png"
    image.write_bytes(b"prepared-roi")
    monkeypatch.setattr(subject, "verify_vista_current_source", lambda **_kwargs: _receipt(tmp_path))
    monkeypatch.setattr(subject, "_gpu_preflight", lambda: {"model_launch_allowed": True})
    monkeypatch.setattr(subject, "_allocate_port", lambda: 14321)
    members = [
        {"pid": 12001, "create_time_ns": "0"},
        {"pid": 12002, "create_time_ns": "1"},
    ]
    monkeypatch.setattr(subject, "_snapshot_owned_tree", lambda *_args, **_kwargs: members)
    monkeypatch.setattr(subject, "_wait_ready", lambda *_args, **_kwargs: members)
    monkeypatch.setattr(subject, "_verify_owned_listener", lambda **_kwargs: True)
    monkeypatch.setattr(
        subject, "_cleanup_owned_tree",
        lambda child, *, created_ns, members, port, status: {
            "status": status, "pid": child.pid, "create_time_ns": str(created_ns),
            "exit_code": -9,
            "cleanup": {
                "status": "verified_exact_child_killed", "pid": child.pid,
                "create_time_ns": str(created_ns), "exit_code": -9,
                "owned_members": members, "owned_members_after": [],
                "active_listeners_after": [], "owned_tree_status": "verified_owned_tree_reaped",
                "owned_tree_exited": True, "listener_absent": True,
            },
        },
    )
    monkeypatch.setattr(subject.subprocess, "Popen", lambda *_args, **_kwargs: _FakeChild())
    return image, tmp_path / "out"


def test_runner_persists_valid_raw_pair_and_exact_owned_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import vista_current_source as subject

    image, out = _prepare_runner(tmp_path, monkeypatch)

    def native(**kwargs):
        kwargs["response_path"].write_bytes(b'{"choices":[{"message":{"content":"[17, 999]"}}]}')
        return "[17, 999]"

    monkeypatch.setattr(subject, "_request_native_pair", native)
    result = subject.run_vista_once(
        project_root=tmp_path, image_path=image, target_text="known public target", out_dir=out,
    )

    assert result["raw_output_utf8"] == "[17, 999]"
    assert result["normalized_point_0_1000"] == [17.0, 999.0]
    assert result["source_score"] is None
    assert result["native_output_ref"]["sha256"] == sha256(b"[17, 999]").hexdigest()
    assert result["cleanup"]["status"] == "verified_exact_child_killed"
    assert [member["pid"] for member in result["cleanup"]["owned_members"]] == [12001, 12002]
    persisted = json.loads((out / "result.json").read_text(encoding="utf-8"))
    assert persisted["roi_image_sha256"] == sha256(b"prepared-roi").hexdigest()


def test_unverified_completed_cleanup_retries_exact_owned_tree_before_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import vista_current_source as subject

    image, out = _prepare_runner(tmp_path, monkeypatch)
    monkeypatch.setattr(subject, "_request_native_pair", lambda **_kwargs: "[17, 999]")
    members = [{"pid": 12001, "create_time_ns": "0"}, {"pid": 12002, "create_time_ns": "1"}]
    calls: list[tuple[object, list[dict[str, object]], str]] = []

    def cleanup(child, *, members: list[dict[str, object]], status: str, **_kwargs):
        calls.append((child, list(members), status))
        verified = len(calls) == 2
        return {
            "status": status, "pid": child.pid, "create_time_ns": "0", "exit_code": -9,
            "cleanup": {
                "status": "verified_exact_child_killed" if verified else "failed_exact_child_cleanup",
                "pid": child.pid, "create_time_ns": "0", "exit_code": -9,
                "owned_members": list(members), "owned_members_after": [] if verified else list(members),
                "active_listeners_after": [],
                "owned_tree_status": "verified_owned_tree_reaped" if verified else "cleanup_failed",
                "owned_tree_exited": verified, "listener_absent": verified,
            },
        }

    monkeypatch.setattr(subject, "_cleanup_owned_tree", cleanup)
    with pytest.raises(subject.VistaCurrentSourceError, match="cleanup is unverified"):
        subject.run_vista_once(
            project_root=tmp_path, image_path=image, target_text="known public target", out_dir=out,
        )

    assert [call[2] for call in calls] == ["completed", "failed"]
    assert all(call[1] == members for call in calls)
    assert calls[0][0] is calls[1][0]
    failure = json.loads((out / "failure-result.json").read_text(encoding="utf-8"))
    assert failure["failure_stage"] == "native_parse"
    assert failure["error"] == {
        "type": "VistaCurrentSourceError", "message": "VISTA owned server cleanup is unverified",
    }
    assert failure["child"]["cleanup"]["status"] == "verified_exact_child_killed"
    assert not (out / "result.json").exists()


def test_malformed_utf8_response_persists_raw_trace_and_reaps_owned_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import vista_current_source as subject

    image, out = _prepare_runner(tmp_path, monkeypatch)

    def malformed(**kwargs):
        kwargs["response_path"].write_bytes(b"\xff")
        raise subject.VistaCurrentSourceError("VISTA owned server response is not UTF-8 JSON")

    monkeypatch.setattr(subject, "_request_native_pair", malformed)
    with pytest.raises(subject.VistaCurrentSourceError, match="not UTF-8"):
        subject.run_vista_once(
            project_root=tmp_path, image_path=image, target_text="known public target", out_dir=out,
        )
    failure = json.loads((out / "failure-result.json").read_text(encoding="utf-8"))
    assert failure["child"]["cleanup"]["status"] == "verified_exact_child_killed"
    assert failure["traces"]["response"]["encoding"] == "invalid-utf8"
    assert (out / "vista.response.bin").read_bytes() == b"\xff"
    assert not (out / "result.json").exists()


def test_readiness_timeout_reaps_owned_child_and_persists_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import vista_current_source as subject

    image, out = _prepare_runner(tmp_path, monkeypatch)
    monkeypatch.setattr(
        subject, "_wait_ready",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(subject.VistaCurrentSourceError("VISTA owned server readiness timed out")),
    )
    with pytest.raises(subject.VistaCurrentSourceError, match="readiness timed out"):
        subject.run_vista_once(
            project_root=tmp_path, image_path=image, target_text="known public target", out_dir=out,
        )
    failure = json.loads((out / "failure-result.json").read_text(encoding="utf-8"))
    assert failure["failure_stage"] == "server_readiness"
    assert failure["child"]["cleanup"]["status"] == "verified_exact_child_killed"


def test_gpu_preflight_rejection_persists_without_starting_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import vista_current_source as subject

    image = tmp_path / "roi.png"
    image.write_bytes(b"prepared-roi")
    starts: list[object] = []
    monkeypatch.setattr(
        subject, "_gpu_preflight",
        lambda: (_ for _ in ()).throw(
            subject.VistaCurrentSourceError("VISTA GPU preflight rejected model launch"),
        ),
    )
    monkeypatch.setattr(
        subject.subprocess, "Popen",
        lambda *_args, **_kwargs: starts.append(True),
    )
    with pytest.raises(subject.VistaCurrentSourceError, match="GPU preflight rejected"):
        subject.run_vista_once(
            project_root=tmp_path, image_path=image, target_text="known public target",
            out_dir=tmp_path / "out",
        )
    failure = json.loads((tmp_path / "out" / "failure-result.json").read_text(encoding="utf-8"))
    assert starts == []
    assert failure["failure_stage"] == "gpu_preflight"
    assert failure["child"]["cleanup"]["status"] == "not_started"


def test_root_gone_after_observed_descendant_preserves_owned_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import vista_current_source as subject

    image, out = _prepare_runner(tmp_path, monkeypatch)
    root = {"pid": 12001, "create_time_ns": "0"}
    descendant = {"pid": 12002, "create_time_ns": "1"}
    observations = iter([[root], subject.VistaCurrentSourceError("root process is gone")])
    cleaned: list[dict[str, object]] = []

    def snapshot(*_args, **_kwargs):
        value = next(observations)
        if isinstance(value, BaseException):
            raise value
        return value

    def readiness(_child, *, owned_members, **_kwargs):
        owned_members[:] = subject._merge_members(owned_members, [descendant])
        raise subject.VistaCurrentSourceError("VISTA owned server readiness timed out")

    def cleanup(_child, *, members, **_kwargs):
        cleaned.extend(members)
        return {
            "status": "failed", "pid": 12001, "create_time_ns": "0", "exit_code": -9,
            "cleanup": {"status": "verified_exact_child_killed", "pid": 12001,
                        "create_time_ns": "0", "exit_code": -9,
                        "owned_tree_status": "verified_owned_tree_reaped",
                        "owned_tree_exited": True, "listener_absent": True},
        }

    monkeypatch.setattr(subject, "_snapshot_owned_tree", snapshot)
    monkeypatch.setattr(subject, "_wait_ready", readiness)
    monkeypatch.setattr(subject, "_cleanup_owned_tree", cleanup)
    with pytest.raises(subject.VistaCurrentSourceError, match="readiness timed out"):
        subject.run_vista_once(
            project_root=tmp_path, image_path=image, target_text="exact target ",
            out_dir=out,
        )
    assert cleaned == [root, descendant]


def test_cleanup_never_terminates_unrelated_pid_when_root_is_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import vista_current_source as subject

    events: list[int] = []

    class OwnedDescendant:
        pid = 12002

        def terminate(self):
            events.append(self.pid)

        def kill(self):
            events.append(-self.pid)

    calls = {"count": 0}

    def current(_members):
        calls["count"] += 1
        return [OwnedDescendant()] if calls["count"] == 1 else []

    monkeypatch.setattr(subject, "_current_owned_processes", current)
    monkeypatch.setattr(subject.psutil, "wait_procs", lambda values, timeout: (values, []))
    monkeypatch.setattr(subject, "_listener_pids", lambda _port: [])
    state = subject._cleanup_owned_tree(
        _FakeChild(), created_ns=0,
        members=[{"pid": 12001, "create_time_ns": "0"}, {"pid": 12002, "create_time_ns": "1"}],
        port=14321, status="failed",
    )
    assert events == [12002]
    assert state["cleanup"]["status"] == "verified_exact_child_killed"


def test_interrupt_preserves_observed_owned_descendant_for_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import vista_current_source as subject

    image, out = _prepare_runner(tmp_path, monkeypatch)
    root = {"pid": 12001, "create_time_ns": "0"}
    descendant = {"pid": 12002, "create_time_ns": "1"}
    cleaned: list[dict[str, object]] = []
    monkeypatch.setattr(subject, "_snapshot_owned_tree", lambda *_args, **_kwargs: [root])

    def readiness(_child, *, owned_members, **_kwargs):
        owned_members[:] = subject._merge_members(owned_members, [descendant])
        raise KeyboardInterrupt()

    def cleanup(_child, *, members, **_kwargs):
        cleaned.extend(members)
        return {
            "status": "interrupted", "pid": 12001, "create_time_ns": "0", "exit_code": -9,
            "cleanup": {"status": "verified_exact_child_killed", "pid": 12001,
                        "create_time_ns": "0", "exit_code": -9,
                        "owned_tree_status": "verified_owned_tree_reaped",
                        "owned_tree_exited": True, "listener_absent": True},
        }

    monkeypatch.setattr(subject, "_wait_ready", readiness)
    monkeypatch.setattr(subject, "_cleanup_owned_tree", cleanup)
    with pytest.raises(KeyboardInterrupt):
        subject.run_vista_once(
            project_root=tmp_path, image_path=image, target_text="target", out_dir=out,
        )
    assert cleaned == [root, descendant]
    failure = json.loads((out / "failure-result.json").read_text(encoding="utf-8"))
    assert failure["failure_stage"] == "interrupted"


def test_foreign_listener_is_refused_before_health_or_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import vista_current_source as subject

    monkeypatch.setattr(subject, "_listener_pids", lambda _port: [9999])
    with pytest.raises(subject.VistaCurrentSourceError, match="not owned"):
        subject._verify_owned_listener(
            port=14321, owned_members=[{"pid": 12001, "create_time_ns": "1"}],
        )


def test_owned_descendant_tree_is_terminated_and_verified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import vista_current_source as subject

    events: list[int] = []

    class OwnedProcess:
        def __init__(self, pid: int):
            self.pid = pid

        def terminate(self):
            events.append(self.pid)

        def kill(self):
            events.append(-self.pid)

    processes = [OwnedProcess(12001), OwnedProcess(12002)]
    calls = {"count": 0}

    def current(_members):
        calls["count"] += 1
        return processes if calls["count"] == 1 else []

    monkeypatch.setattr(subject, "_current_owned_processes", current)
    monkeypatch.setattr(subject.psutil, "wait_procs", lambda values, timeout: (values, []))
    monkeypatch.setattr(subject, "_listener_pids", lambda _port: [])
    child = _FakeChild()
    state = subject._cleanup_owned_tree(
        child,
        created_ns=0,
        members=[
            {"pid": 12001, "create_time_ns": "0"},
            {"pid": 12002, "create_time_ns": "1"},
        ],
        port=14321,
        status="completed",
    )
    assert events == [12002, 12001]
    assert state["cleanup"]["status"] == "verified_exact_child_killed"
    assert state["cleanup"]["owned_tree_status"] == "verified_owned_tree_reaped"
    assert state["cleanup"]["owned_members_after"] == []
    assert state["cleanup"]["active_listeners_after"] == []
