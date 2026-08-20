from __future__ import annotations

from types import SimpleNamespace

from app.core import gpu_resources


def _memory(*, available_gib: float, total_gib: float = 32.0):
    return SimpleNamespace(available=int(available_gib * 1024**3), total=int(total_gib * 1024**3))


def test_gpu_resource_preflight_uses_normal_batch_when_machine_is_idle(monkeypatch) -> None:
    monkeypatch.setattr(
        gpu_resources,
        "_gpu_snapshot",
        lambda: {
            "available": True,
            "devices": [
                {
                    "index": 0,
                    "memory_total_mib": 16384,
                    "memory_used_mib": 800,
                    "memory_free_mib": 15584,
                    "utilization_percent": 4,
                }
            ],
            "compute_processes": [],
        },
    )
    monkeypatch.setattr(gpu_resources, "_known_model_pids", lambda: set())
    monkeypatch.setattr(gpu_resources.psutil, "virtual_memory", lambda: _memory(available_gib=24))

    result = gpu_resources.build_model_resource_preflight(
        {"profile_id": "vista_4b_transformers", "gpu_memory_gib": 10}
    )

    assert result["resource_mode"] == "normal"
    assert result["recommended_batch_size"] == 8
    assert result["external_gpu_process_count"] == 0
    assert result["reason_codes"] == []


def test_gpu_resource_preflight_reduces_batch_for_external_game_load(monkeypatch) -> None:
    monkeypatch.setattr(
        gpu_resources,
        "_gpu_snapshot",
        lambda: {
            "available": True,
            "devices": [
                {
                    "index": 0,
                    "memory_total_mib": 16384,
                    "memory_used_mib": 11200,
                    "memory_free_mib": 5184,
                    "utilization_percent": 78,
                }
            ],
            "compute_processes": [
                {"pid": 4040, "process_name": "game.exe", "used_memory_mib": 7600}
            ],
        },
    )
    monkeypatch.setattr(gpu_resources, "_known_model_pids", lambda: {9090})
    monkeypatch.setattr(gpu_resources.psutil, "virtual_memory", lambda: _memory(available_gib=15))

    result = gpu_resources.build_model_resource_preflight(
        {"profile_id": "vista_4b_transformers", "gpu_memory_gib": 10}
    )

    assert result["resource_mode"] == "critical"
    assert result["recommended_batch_size"] == 1
    assert result["external_gpu_process_count"] == 1
    assert "external_gpu_process_detected" in result["reason_codes"]
    assert "high_gpu_utilization" in result["reason_codes"]


def test_gpu_resource_preflight_does_not_treat_known_model_as_user_load(monkeypatch) -> None:
    monkeypatch.setattr(
        gpu_resources,
        "_gpu_snapshot",
        lambda: {
            "available": True,
            "devices": [
                {
                    "index": 0,
                    "memory_total_mib": 16384,
                    "memory_used_mib": 9800,
                    "memory_free_mib": 6584,
                    "utilization_percent": 3,
                }
            ],
            "compute_processes": [
                {"pid": 9090, "process_name": "python.exe", "used_memory_mib": 9200}
            ],
        },
    )
    monkeypatch.setattr(gpu_resources, "_known_model_pids", lambda: {9090})
    monkeypatch.setattr(gpu_resources.psutil, "virtual_memory", lambda: _memory(available_gib=20))

    result = gpu_resources.build_model_resource_preflight(
        {"profile_id": "vista_4b_transformers", "gpu_memory_gib": 10}
    )

    assert result["resource_mode"] == "normal"
    assert result["recommended_batch_size"] == 8
    assert result["external_gpu_process_count"] == 0


def test_gpu_resource_preflight_allows_single_batch_for_resident_profile_under_low_system_memory(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        gpu_resources,
        "_gpu_snapshot",
        lambda: {
            "available": True,
            "devices": [
                {
                    "index": 0,
                    "memory_total_mib": 12282,
                    "memory_used_mib": 9300,
                    "memory_free_mib": 2982,
                    "utilization_percent": 4,
                }
            ],
            "compute_processes": [
                {
                    "pid": 9091,
                    "process_name": "llama-server.exe",
                    "used_memory_mib": 0,
                }
            ],
        },
    )
    monkeypatch.setattr(gpu_resources, "_known_model_pids", lambda: {9090, 9091})
    monkeypatch.setattr(
        gpu_resources,
        "_profile_model_pids",
        lambda _profile: {9090, 9091},
        raising=False,
    )
    monkeypatch.setattr(
        gpu_resources,
        "_known_model_reserved_memory_mib",
        lambda _pids: 7168,
    )
    monkeypatch.setattr(
        gpu_resources.psutil,
        "virtual_memory",
        lambda: _memory(available_gib=1.8),
    )

    result = gpu_resources.build_model_resource_preflight(
        {"profile_id": "qwen3_vl_8b_q4_k_m", "gpu_memory_gib": 7}
    )

    assert result["model_launch_allowed"] is True
    assert result["resource_mode"] == "constrained"
    assert result["recommended_batch_size"] == 1
    assert "low_system_memory_with_resident_profile" in result["reason_codes"]
    assert "low_system_memory" not in result["reason_codes"]


def test_gpu_resource_preflight_attributes_wddm_zero_memory_row_to_running_model(monkeypatch) -> None:
    monkeypatch.setattr(
        gpu_resources,
        "_gpu_snapshot",
        lambda: {
            "available": True,
            "devices": [
                {
                    "index": 0,
                    "memory_total_mib": 12282,
                    "memory_used_mib": 9300,
                    "memory_free_mib": 2700,
                    "utilization_percent": 98,
                }
            ],
            "compute_processes": [
                {"pid": 9091, "process_name": "llama-server.exe", "used_memory_mib": 0}
            ],
        },
    )
    monkeypatch.setattr(gpu_resources, "_known_model_pids", lambda: {9090, 9091})
    monkeypatch.setattr(gpu_resources, "_known_model_reserved_memory_mib", lambda _pids: 7168)
    monkeypatch.setattr(gpu_resources.psutil, "virtual_memory", lambda: _memory(available_gib=12))

    result = gpu_resources.build_model_resource_preflight(
        {"profile_id": "qwen3_vl_8b_q4_k_m", "gpu_memory_gib": 7}
    )

    assert result["model_launch_allowed"] is True
    assert result["resource_mode"] != "critical"
    assert result["known_model_process_count"] == 1
    assert result["gpu"]["known_model_memory_mib"] == 7168
    assert result["gpu"]["known_model_memory_source"] == "profile_reserved_memory"
    assert "insufficient_gpu_memory_for_profile" not in result["reason_codes"]
    assert "high_gpu_utilization" not in result["reason_codes"]


def test_known_model_pids_include_recursive_launcher_children(monkeypatch, tmp_path) -> None:
    pid_file = tmp_path / "model.pid"
    pid_file.write_text("9090", encoding="utf-8")
    monkeypatch.setattr(
        gpu_resources,
        "load_model_profiles",
        lambda: [{"profile_id": "model", "pid_file": str(pid_file), "gpu_memory_gib": 7}],
    )
    monkeypatch.setattr(gpu_resources.psutil, "pid_exists", lambda pid: pid in {9090, 9091, 9092})

    class _Process:
        def __init__(self, pid: int) -> None:
            self.pid = pid

        def children(self, *, recursive: bool):
            assert recursive is True
            return [SimpleNamespace(pid=9091), SimpleNamespace(pid=9092)]

    monkeypatch.setattr(gpu_resources.psutil, "Process", _Process)

    assert gpu_resources._known_model_pids() == {9090, 9091, 9092}


def test_gpu_resource_preflight_recognizes_default_profile_pid_file(
    monkeypatch,
    tmp_path,
) -> None:
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    (logs_dir / "learn_mode_qwen3_vl_8b-server.pid").write_text(
        "9090",
        encoding="utf-8",
    )
    profile = {
        "profile_id": "learn_mode_qwen3_vl_8b",
        "gpu_memory_gib": 7,
    }
    monkeypatch.setattr(gpu_resources, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(gpu_resources, "load_model_profiles", lambda: [profile])
    monkeypatch.setattr(
        gpu_resources,
        "_gpu_snapshot",
        lambda: {
            "available": True,
            "devices": [
                {
                    "index": 0,
                    "memory_total_mib": 12000,
                    "memory_used_mib": 8500,
                    "memory_free_mib": 3500,
                    "utilization_percent": 3,
                }
            ],
            "compute_processes": [
                {
                    "pid": 9091,
                    "process_name": "llama-server.exe",
                    "used_memory_mib": 0,
                }
            ],
        },
    )
    monkeypatch.setattr(
        gpu_resources.psutil,
        "pid_exists",
        lambda pid: pid in {9090, 9091},
    )
    monkeypatch.setattr(
        gpu_resources.psutil,
        "Process",
        lambda _pid: SimpleNamespace(
            children=lambda recursive: [SimpleNamespace(pid=9091)]
        ),
    )
    monkeypatch.setattr(
        gpu_resources.psutil,
        "virtual_memory",
        lambda: _memory(available_gib=20),
    )

    result = gpu_resources.build_model_resource_preflight(profile)

    assert result["known_model_process_count"] == 1
    assert result["gpu"]["known_model_memory_mib"] == 7168
    assert result["model_launch_allowed"] is True
    assert "high_external_gpu_memory_use" not in result["reason_codes"]
    assert "insufficient_gpu_memory_for_profile" not in result["reason_codes"]


def test_gpu_resource_preflight_ignores_idle_wddm_process_rows(monkeypatch) -> None:
    monkeypatch.setattr(
        gpu_resources,
        "_gpu_snapshot",
        lambda: {
            "available": True,
            "devices": [
                {
                    "index": 0,
                    "memory_total_mib": 16384,
                    "memory_used_mib": 700,
                    "memory_free_mib": 15684,
                    "utilization_percent": 2,
                }
            ],
            "compute_processes": [
                {"pid": 1000, "process_name": "dwm.exe", "used_memory_mib": 0},
                {"pid": 2000, "process_name": "explorer.exe", "used_memory_mib": 0},
            ],
        },
    )
    monkeypatch.setattr(gpu_resources, "_known_model_pids", lambda: set())
    monkeypatch.setattr(gpu_resources.psutil, "virtual_memory", lambda: _memory(available_gib=20))

    result = gpu_resources.build_model_resource_preflight(
        {"profile_id": "vista_4b_transformers", "gpu_memory_gib": 10}
    )

    assert result["resource_mode"] == "normal"
    assert result["recommended_batch_size"] == 8
    assert result["external_gpu_process_count"] == 0
    assert result["observed_external_gpu_process_count"] == 2


def test_gpu_resource_preflight_uses_small_batches_for_unattributed_wddm_memory_load(monkeypatch) -> None:
    monkeypatch.setattr(
        gpu_resources,
        "_gpu_snapshot",
        lambda: {
            "available": True,
            "devices": [
                {
                    "index": 0,
                    "memory_total_mib": 12282,
                    "memory_used_mib": 2512,
                    "memory_free_mib": 9488,
                    "utilization_percent": 8,
                }
            ],
            "compute_processes": [
                {"pid": 17168, "process_name": "game.exe", "used_memory_mib": 0},
            ],
        },
    )
    monkeypatch.setattr(gpu_resources, "_known_model_pids", lambda: set())
    monkeypatch.setattr(gpu_resources.psutil, "virtual_memory", lambda: _memory(available_gib=16))

    result = gpu_resources.build_model_resource_preflight(
        {"profile_id": "vista_4b_transformers", "gpu_memory_gib": 10}
    )

    assert result["resource_mode"] == "constrained"
    assert result["recommended_batch_size"] == 2
    assert "unattributed_wddm_gpu_memory_use" in result["reason_codes"]


def test_gpu_resource_preflight_blocks_new_model_when_free_vram_is_below_profile_requirement(monkeypatch) -> None:
    monkeypatch.setattr(
        gpu_resources,
        "_gpu_snapshot",
        lambda: {
            "available": True,
            "devices": [
                {
                    "index": 0,
                    "memory_total_mib": 12282,
                    "memory_used_mib": 4284,
                    "memory_free_mib": 7716,
                    "utilization_percent": 39,
                }
            ],
            "compute_processes": [
                {"pid": 17168, "process_name": "game.exe", "used_memory_mib": 0},
            ],
        },
    )
    monkeypatch.setattr(gpu_resources, "_known_model_pids", lambda: set())
    monkeypatch.setattr(gpu_resources.psutil, "virtual_memory", lambda: _memory(available_gib=16))

    result = gpu_resources.build_model_resource_preflight(
        {"profile_id": "vista_4b_transformers", "gpu_memory_gib": 10}
    )

    assert result["resource_mode"] == "critical"
    assert result["model_launch_allowed"] is False
    assert result["requested_gpu_memory_mib"] == 10240
    assert result["available_gpu_memory_mib"] == 7716
    assert "insufficient_gpu_memory_for_profile" in result["reason_codes"]


def test_gpu_resource_preflight_is_conservative_when_gpu_probe_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        gpu_resources,
        "_gpu_snapshot",
        lambda: {"available": False, "reason": "nvidia_smi_unavailable", "devices": [], "compute_processes": []},
    )
    monkeypatch.setattr(gpu_resources, "_known_model_pids", lambda: set())
    monkeypatch.setattr(gpu_resources.psutil, "virtual_memory", lambda: _memory(available_gib=20))

    result = gpu_resources.build_model_resource_preflight(
        {"profile_id": "vista_4b_transformers", "gpu_memory_gib": 10}
    )

    assert result["resource_mode"] == "constrained"
    assert result["recommended_batch_size"] == 2
    assert result["reason_codes"] == ["gpu_probe_unavailable"]


def test_nvidia_output_decoder_preserves_windows_chinese_process_name(monkeypatch) -> None:
    encoded = "游戏客户端.exe".encode("gb18030")
    monkeypatch.setattr(gpu_resources, "_windows_ansi_encoding", lambda: "gb18030")

    assert gpu_resources._decode_nvidia_output(encoded) == "游戏客户端.exe"
