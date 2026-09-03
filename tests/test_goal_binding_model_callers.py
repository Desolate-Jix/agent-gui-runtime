from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = ROOT / "configs" / "model_profiles"
PROFILE_NAMES = (
    "goal_binding_qwen_incumbent.json",
    "goal_binding_ui_venus_1_5_2b_f16.json",
    "learn_mode_gui_actor_3b.json",
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
    before = dict(__import__("os").environ)
    profiles = [callers.load_goal_binding_profile(PROFILE_DIR / name) for name in PROFILE_NAMES]

    assert all(profile["artifact_manifest"]["status"] == "not_acquired" for profile in profiles)
    assert touched == []
    assert dict(__import__("os").environ) == before


def test_profiles_are_closed_non_authorizing_and_use_exact_model_ids() -> None:
    from app.learn.hybrid.goal_binding_model_callers import load_goal_binding_profile

    profiles = {
        profile["profile_id"]: profile
        for profile in (load_goal_binding_profile(PROFILE_DIR / name) for name in PROFILE_NAMES)
    }
    assert profiles["goal_binding_ui_venus_1_5_2b_f16"]["model_id"] == "inclusionAI/UI-Venus-1.5-2B"
    assert profiles["learn_mode_gui_actor_3b"]["model_id"] == "microsoft/GUI-Actor-3B-Qwen2.5-VL"
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


def test_ui_venus_and_phi_workers_return_only_native_output_trace() -> None:
    worker = _worker_module()
    for provider_id, raw_native in (
        ("ui_venus_1_5_2b_f16", '{"point":[250,375]}'),
        ("phi_ground_any_bf16", "<x>5000</x><y>5000</y>"),
    ):
        envelope = worker.native_trace_envelope(
            profile_identity={"profile_id": provider_id, "preprocessing_sha256": "a" * 64, "runtime_sha256": "b" * 64, "native_output_kind": "ui_venus_point_v1"},
            raw_native_output=raw_native,
            resource_metrics={"latency_ms": 1.0, "peak_vram_bytes": 0},
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


def test_probe_uses_no_gold_holdout_or_candidate_mapping(tmp_path: Path) -> None:
    from app.learn.hybrid.goal_binding_model_callers import (
        load_goal_binding_profile,
        probe_goal_binding_profile,
    )

    image = tmp_path / "screen.png"
    image.write_bytes(b"not-an-image-needed-before-acquisition")
    profile = load_goal_binding_profile(PROFILE_DIR / "goal_binding_ui_venus_1_5_2b_f16.json")
    with pytest.raises(ValueError, match="not acquired|artifact"):
        probe_goal_binding_profile(profile=profile, image_path=image)
