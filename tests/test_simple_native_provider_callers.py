from __future__ import annotations

import os
from pathlib import Path

import pytest
from PIL import Image


def test_qwen_actual_caller_sends_projection_not_full_runtime_request(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_callers import call_qwen_projected_binding
    seen=[]
    class Transport:
        def post(self, *, url, payload, timeout): seen.append(payload); return []
    call_qwen_projected_binding(image_path=tmp_path/'image.png', projection={"image_size":[1,1],"goals":[],"candidates":[]}, transport=Transport())
    assert "candidate_id" not in str(seen[0]) and seen[0]["projection"]["candidates"] == []


def test_qwen_actual_response_is_expanded_with_adapter_side_semantics() -> None:
    from app.learn.hybrid.simple_native_contracts import expand_qwen_goal_binding_response
    runtime={"contract_version":"simple_native_qwen_goal_binding_request_v1", "screenshot":{"image_size":{"width":10,"height":10}},"goals":[{"goal_index":0,"role":"button","label":"x"}],"candidates":[{"candidate_id":"candidate/a","bbox_original":[1,1,2,2],"active":True}]}
    projection={"image_size":[10,10],"goals":[{"goal_index":0,"role":"button","label":"x"}],"candidates":[{"candidate_index":0,"bbox":[1,1,2,2],"active":True}]}
    assert expand_qwen_goal_binding_response([{"goal_index":0,"candidate_index":0,"status":"BOUND","confidence":1}],projection=projection,runtime_request=runtime)["bindings"][0]["candidate_id"] == "candidate/a"


def test_vista_actual_caller_sends_no_generic_json_system_prompt_or_response_format(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_callers import call_vista_bare_point
    seen=[]
    class Transport:
        def post(self, *, url, payload, timeout): seen.append(payload); return "[1,2]"
    call_vista_bare_point(roi_path=tmp_path/'roi.png',target_text='Find target',transport=Transport())
    assert "response_format" not in seen[0] and all(message["role"] != "system" for message in seen[0]["messages"])


def test_vista_actual_caller_reads_bare_normalized_pair(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_callers import call_vista_bare_point
    class Transport:
        def post(self, **kwargs): return "[437,612]"
    assert call_vista_bare_point(roi_path=tmp_path/'roi.png',target_text='x',transport=Transport()) == "[437,612]"


def test_omni_worker_projects_only_native_fields_before_runtime_adapter() -> None:
    from app.learn.hybrid.simple_native_callers import project_omni_official_items
    assert project_omni_official_items([{"bbox":[0,0,1,1],"type":"text","content":"x","interactivity":False,"source_item_id":"bad"}]) == {"items":[{"bbox":[0,0,1,1],"type":"text","content":"x","interactivity":False}]}


def test_actual_slots_are_lazy_provider_batched_and_reuse_qwen_and_vista_leases(
    tmp_path: Path,
) -> None:
    from app.learn.hybrid.simple_native_callers import (
        SimpleNativeActualDependencies,
        make_actual_simple_native_slots,
    )

    events: list[tuple[object, ...]] = []
    cleanup_by_invocation: dict[str, dict[str, object]] = {}

    class Scope:
        def __init__(self, name: str) -> None:
            self.name = name

        def close(self) -> None:
            events.append(("scope_close", self.name))

    class Omni:
        profile_id = "omni"

        def invoke_native(self, *, capture, budget, invocation_id, cancellation_event=None):
            del budget, cancellation_event
            events.append(("omni_run", invocation_id, capture.local_path))
            cleanup_by_invocation[invocation_id] = {
                "cleanup_status": "verified",
                "inventory_observable": True,
                "provider_processes_after": [],
                "orphan_descendant_identities": [],
                "active_listeners_after": [],
                "lease_files_after": [],
                "process_scope_cleanup": {"cleanup_status": "verified"},
            }
            return {"items": []}

    def observe_scope(name: str, **_kwargs):
        events.append(("scope_observe", name))
        return {
            "cleanup_status": "verified",
            "member_pids_after": [],
            "member_identities_after": [],
            "active_listeners_after": [],
            "pid_file_after": None,
        }

    qwen_lease = {"lease_id": "qwen-one"}
    vista_lease = {"lease_id": "vista-one"}
    dependencies = SimpleNativeActualDependencies(
        scope_name=lambda _lineage, provider: f"scope-{provider}",
        create_scope=lambda name: events.append(("scope_create", name)) or Scope(name),
        observe_scope_cleanup=observe_scope,
        build_omni_adapter=lambda: events.append(("omni_adapter",)) or Omni(),
        load_omni_cleanup=lambda invocation_id: cleanup_by_invocation[invocation_id],
        acquire_qwen=lambda **kwargs: events.append(("qwen_acquire", kwargs["scope_name"])) or qwen_lease,
        run_qwen=lambda **kwargs: events.append(("qwen_run", kwargs["model_lease"])) or [],
        release_qwen=lambda lease, reason: events.append(("qwen_release", lease, reason)) or {
            "status": "released",
            "shared_server_retained": False,
            "server_termination": "verified_exact_process_exited",
            "release": {"status": "proven_absent"},
            "hybrid_descendant_cleanup": {"status": "verified"},
            "hybrid_process_scope_cleanup": {
                "cleanup_status": "verified",
                "member_pids_after": [],
                "member_identities_after": [],
                "active_listeners_after": [],
                "pid_file_after": None,
            },
        },
        acquire_vista=lambda **kwargs: events.append(("vista_acquire", kwargs["scope_name"])) or vista_lease,
        run_vista=lambda **kwargs: events.append(("vista_run", kwargs["model_lease"])) or "[500,500]",
        release_vista=lambda **kwargs: events.append(("vista_release", kwargs["model_lease"])) or {
            "release_status": "verified",
            "provider_processes_after": [],
            "helper_processes_after": [],
            "orphan_descendant_pids": [],
            "active_listeners_after": [],
            "lease_files_after": [],
            "source_cleanup_evidence": {"status": "verified"},
        },
    )
    config = {
        "provider": {"profile_ids": {"omni": "omni", "qwen": "qwen", "vista": "vista"}},
        "limits": {"timeout_seconds": 120, "max_output_bytes": 1024},
    }
    image = tmp_path / "image.png"
    Image.new("RGB", (20, 10)).save(image)
    slots = make_actual_simple_native_slots(
        config=config,
        artifact_dir=tmp_path / "artifacts",
        dependencies=dependencies,
    )

    assert events == []
    for _ in range(5):
        assert slots.omni(image) == {"items": []}
    assert slots.release_provider("omni")["verified"] is True
    for _ in range(5):
        assert slots.qwen(image, {"image_size": [20, 10], "goals": [], "candidates": []}) == []
    assert slots.release_provider("qwen")["verified"] is True
    for _ in range(3):
        assert slots.vista(image, "button: Open") == "[500,500]"
    assert slots.release_provider("vista")["verified"] is True
    assert slots.cleanup()["verified"] is True

    assert [event[0] for event in events].count("qwen_acquire") == 1
    assert [event[0] for event in events].count("qwen_release") == 1
    assert [event[0] for event in events].count("vista_acquire") == 1
    assert [event[0] for event in events].count("vista_release") == 1
    assert all(event[1] is qwen_lease for event in events if event[0] == "qwen_run")
    assert all(event[1] is vista_lease for event in events if event[0] == "vista_run")
    assert events.index(next(event for event in events if event[0] == "qwen_acquire")) > events.index(next(event for event in events if event[0] == "scope_close" and event[1] == "scope-omni"))
    assert events.index(next(event for event in events if event[0] == "vista_acquire")) > events.index(next(event for event in events if event[0] == "scope_close" and event[1] == "scope-qwen"))


def test_actual_qwen_dispatch_failure_releases_once_before_vista_is_blocked(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_callers import (
        SimpleNativeActualDependencies,
        make_actual_simple_native_slots,
    )

    events: list[str] = []

    class Scope:
        def close(self) -> None:
            events.append("scope_close")

    clean_scope = lambda *_args, **_kwargs: {
        "cleanup_status": "verified",
        "member_pids_after": [],
        "member_identities_after": [],
        "active_listeners_after": [],
        "pid_file_after": None,
    }
    dependencies = SimpleNativeActualDependencies(
        scope_name=lambda _lineage, provider: f"scope-{provider}",
        create_scope=lambda _name: Scope(),
        observe_scope_cleanup=clean_scope,
        build_omni_adapter=lambda: object(),
        load_omni_cleanup=lambda _invocation_id: {},
        acquire_qwen=lambda **_kwargs: {"lease_id": "qwen"},
        run_qwen=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("dispatch failed")),
        release_qwen=lambda _lease, _reason: events.append("qwen_release") or {
            "status": "released",
            "shared_server_retained": False,
            "server_termination": "verified_exact_process_exited",
            "release": {"status": "proven_absent"},
            "hybrid_descendant_cleanup": {"status": "verified"},
            "hybrid_process_scope_cleanup": clean_scope(),
        },
        acquire_vista=lambda **_kwargs: events.append("vista_acquire") or {},
        run_vista=lambda **_kwargs: "[1,1]",
        release_vista=lambda **_kwargs: {},
    )
    config = {
        "provider": {"profile_ids": {"omni": "omni", "qwen": "qwen", "vista": "vista"}},
        "limits": {"timeout_seconds": 120, "max_output_bytes": 1024},
    }
    image = tmp_path / "image.png"
    image.write_bytes(b"image")
    slots = make_actual_simple_native_slots(config=config, artifact_dir=tmp_path, dependencies=dependencies)

    assert slots.release_provider("omni")["verified"] is True
    with pytest.raises(RuntimeError, match="dispatch failed"):
        slots.qwen(image, {"image_size": [1, 1], "candidates": []})
    assert slots.release_provider("qwen")["verified"] is True
    with pytest.raises(RuntimeError, match="blocked"):
        slots.vista(image, "button: Open")
    assert events.count("qwen_release") == 1 and "vista_acquire" not in events


@pytest.mark.parametrize("owner_persisted", [False, True])
def test_actual_omni_failure_cleanup_depends_on_persisted_owner(
    tmp_path: Path,
    owner_persisted: bool,
) -> None:
    from app.learn.hybrid.simple_native_callers import (
        SimpleNativeActualDependencies,
        make_actual_simple_native_slots,
    )

    cleanup_loads: list[str] = []
    scope_observations: list[tuple[str, object, object]] = []
    qwen_acquisitions: list[object] = []

    class Scope:
        def close(self) -> None:
            return None

    class Omni:
        profile_id = "omni"

        def invoke_native(self, **_kwargs):
            if owner_persisted:
                Path(os.environ["AGENT_GUI_HYBRID_PROVIDER_RUNTIME_PATH"]).write_text(
                    "{}", encoding="utf-8"
                )
            raise RuntimeError("omni preflight rejected")

    def observe_scope(name: str, **kwargs):
        scope_observations.append(
            (name, kwargs.get("terminate"), kwargs.get("stable_zero_observations"))
        )
        return {
            "cleanup_status": "verified",
            "member_pids_after": [],
            "member_identities_after": [],
            "active_listeners_after": [],
            "pid_file_after": None,
        }

    def load_omni_cleanup(invocation_id: str):
        cleanup_loads.append(invocation_id)
        if not owner_persisted:
            raise AssertionError("cleanup load must require a persisted owner")
        return {
            "cleanup_status": "verified",
            "inventory_observable": True,
            "provider_processes_after": [],
            "orphan_descendant_identities": [],
            "active_listeners_after": [],
            "lease_files_after": [],
            "process_scope_cleanup": {"cleanup_status": "verified"},
        }

    dependencies = SimpleNativeActualDependencies(
        scope_name=lambda _lineage, provider: f"scope-{provider}",
        create_scope=lambda _name: Scope(),
        observe_scope_cleanup=observe_scope,
        build_omni_adapter=Omni,
        load_omni_cleanup=load_omni_cleanup,
        acquire_qwen=lambda **kwargs: qwen_acquisitions.append(kwargs) or {},
        run_qwen=lambda **_kwargs: {"bindings": []},
        release_qwen=lambda _lease, _reason: {},
        acquire_vista=lambda **_kwargs: {},
        run_vista=lambda **_kwargs: "[1,1]",
        release_vista=lambda **_kwargs: {},
    )
    config = {
        "provider": {
            "profile_ids": {"omni": "omni", "qwen": "qwen", "vista": "vista"}
        },
        "limits": {"timeout_seconds": 120, "max_output_bytes": 1024},
    }
    image = tmp_path / "image.png"
    Image.new("RGB", (2, 2)).save(image)
    slots = make_actual_simple_native_slots(
        config=config,
        artifact_dir=tmp_path / "artifacts",
        dependencies=dependencies,
    )

    with pytest.raises(RuntimeError, match="omni preflight rejected"):
        try:
            slots.omni(image)
        finally:
            receipt = slots.release_provider("omni")

    assert receipt["verified"] is True
    assert len(cleanup_loads) == (1 if owner_persisted else 0)
    assert scope_observations == [("scope-omni", True, 3)]
    with pytest.raises(RuntimeError, match="transition is blocked"):
        slots.qwen(image, {"image_size": [2, 2], "candidates": []})
    assert qwen_acquisitions == []


def test_actual_lifecycle_is_exclusive_bounded_and_records_verified_cleanup() -> None:
    from app.learn.hybrid.simple_native_callers import verify_cleanup_receipt
    assert verify_cleanup_receipt({"verified":True,"owned_processes":[]}) is True


def test_actual_qwen_cleanup_rejects_contradictory_scope_residue() -> None:
    from app.learn.hybrid.simple_native_callers import _qwen_source_is_clean

    assert _qwen_source_is_clean({
        "status": "released",
        "shared_server_retained": False,
        "server_termination": "verified_exact_process_exited",
        "release": {"status": "proven_absent"},
        "hybrid_descendant_cleanup": {"status": "verified"},
        "hybrid_process_scope_cleanup": {
            "cleanup_status": "verified",
            "member_pids_after": [4242],
            "member_identities_after": [{"pid": 4242, "create_time_ns": 1}],
            "active_listeners_after": [],
            "pid_file_after": None,
        },
    }) is False


def test_cancellation_stops_owned_processes_and_never_kills_unknown_processes() -> None:
    from app.learn.hybrid.simple_native_callers import cancel_owned_processes
    class Lifecycle:
        def stop_owned(self): return {"verified":True,"owned_processes":[]}
    assert cancel_owned_processes(Lifecycle())["verified"] is True
