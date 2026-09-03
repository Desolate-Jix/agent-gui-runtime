from __future__ import annotations

from copy import deepcopy
import importlib
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/run_goal_binding_provider_ab.py"
CONFIG = ROOT / "configs/benchmarks/goal_binding_provider_ab_v1.json"


def test_cli_defaults_to_preflight_and_constructs_no_model_callers(tmp_path):
    result = subprocess.run([sys.executable, str(SCRIPT), "--artifact-root", str(tmp_path / "absent")], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["mode"] == "preflight" and report["model_callers_constructed"] is False
    assert report["profiles_ready"] is False
    assert report["preflight_scope"] == "config_storage_profile_only"
    assert report["runtime_resource_check"] == "performed_by_session_before_start"
    assert any(item["status"] == "not_acquired" for item in report["profiles"])
    assert not (tmp_path / "absent").exists()


def test_config_contains_exact_five_screens_25_targets_and_no_holdout():
    actual = json.loads(CONFIG.read_text(encoding="utf-8"))
    baseline = json.loads((ROOT / "configs/benchmarks/simple_native_provider_smoke_v1.json").read_text(encoding="utf-8"))
    assert actual["screens"] == baseline["screens"]
    assert actual["provider"] == baseline["provider"]
    assert len(actual["screens"]) == 5 and sum(len(s["target_ids"]) for s in actual["screens"]) == 25
    assert "gold" not in json.dumps(actual["provider"]).lower()


def test_config_freezes_incumbent_stage1_and_conditional_stage2_order():
    cli = importlib.import_module("scripts.run_goal_binding_provider_ab")
    config = cli._config(CONFIG)
    assert config["matrix"]["incumbent"] == "goal_binding_qwen_incumbent"
    assert config["matrix"]["stage1"] == list(cli.STAGE1)
    assert config["matrix"]["stage2"] == list(cli.STAGE2)
    assert config["matrix"]["stage2_fallback"] == "goal_binding_ui_venus_1_5_8b_q6_k"


@pytest.mark.parametrize("mode", ["snapshot", "arm", "matrix"])
def test_snapshot_arm_and_matrix_require_explicit_model_start_flag(tmp_path, mode):
    cli = importlib.import_module("scripts.run_goal_binding_provider_ab")
    def forbidden(**kwargs):
        pytest.fail("caller constructed without approval")
    assert cli.main(["--mode", mode, "--artifact-root", str(tmp_path / "absent")], slots_factory=forbidden, arm_factory=forbidden) == 2
    assert not (tmp_path / "absent").exists()


@pytest.mark.parametrize("flag", ["--holdout", "--execute", "--gold", "--download"])
def test_cli_cannot_address_holdout_or_action_execution(flag):
    cli = importlib.import_module("scripts.run_goal_binding_provider_ab")
    with pytest.raises(SystemExit):
        cli.main([flag])


def test_help_and_import_do_not_import_model_libraries():
    result = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0 and "--operator-approved-model-start" in result.stdout
    code = "import scripts.run_goal_binding_provider_ab; import sys; assert not {'torch','transformers','vllm','gui_actor'} & set(sys.modules)"
    assert subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True).returncode == 0


@pytest.fixture
def experiment(tmp_path, monkeypatch):
    from hashlib import sha256
    from PIL import Image
    from app.learn.hybrid import model_test_storage
    from app.learn.hybrid.simple_native_smoke import ProviderCase, SimpleNativeSlots
    from app.learn.hybrid.goal_binding_ab import GoalBindingArm, adapt_incumbent_candidate_index, make_native_point_adapter
    from app.learn.hybrid.goal_binding_native_adapters import parse_ui_venus_point
    from app.learn.hybrid.goal_binding_ab_score import score_goal_binding_arm
    from scripts import run_simple_native_provider_smoke as smoke
    cli = importlib.import_module("scripts.run_goal_binding_provider_ab")
    storage, root = tmp_path / "storage", tmp_path / "run"
    monkeypatch.setattr(model_test_storage, "MODEL_TEST_ROOT", storage)
    cases, targets, events = [], [], []
    for index in range(1, 6):
        image = tmp_path / f"case-{index:03d}.png"
        Image.new("RGB", (100, 80), (index, 20, 30)).save(image)
        goals = tuple(f"Select the button labeled 'target-{n}'" for n in range(1, 6))
        cases.append(ProviderCase(case_id=f"case-{index:03d}", image_path=image, image_size=(100, 80), image_sha256=sha256(image.read_bytes()).hexdigest(), goals=goals))
        targets.extend({"screen_id": f"case-{index:03d}", "role": "button", "label": f"target-{n}", "goal": goals[n-1], "partition": "regression", "acceptable_candidate_ids": [], "acceptable_regions": [[10, 20, 30, 40]]} for n in range(1, 6))
    gold = tmp_path / "synthetic-score.json"
    gold.write_text(json.dumps({"targets": targets}), encoding="utf-8")
    monkeypatch.setattr(smoke, "_cases", lambda config: cases)
    monkeypatch.setattr(cli, "_available", lambda profile, root: profile)
    monkeypatch.setattr(cli, "_score_report", lambda artifact, config: score_goal_binding_arm(provider_artifact=artifact, gold_path=gold), raising=False)
    def clean(provider):
        return {"contract_version": "simple_native_provider_cleanup_v1", "provider": provider, "verified": True, "cleanup_status": "verified", "owned_processes": [], "provider_processes_after": [], "helper_processes_after": [], "orphan_descendant_pids": [], "active_listeners_after": [], "lease_files_after": []}
    state = {"passer": None, "broken_cleanup": False, "incompatible": False, "events": events}
    def slots_factory(*, config, artifact_dir):
        assert "gold" not in json.dumps(config).casefold()
        receipts = []
        def release(provider):
            events.append("release:" + provider)
            receipt = clean(provider)
            receipts.append(receipt)
            return receipt
        def omni(image):
            events.append("omni")
            return {"items": [{"bbox": [0.1, 0.25, 0.3, 0.5], "type": "text", "content": "target", "interactivity": True}]}
        return SimpleNativeSlots(omni=omni, qwen=lambda *a: pytest.fail("legacy Qwen called"), vista=lambda *a: "[500,500]", release_provider=release, cleanup=lambda: {"contract_version": "simple_native_actual_session_cleanup_v1", "verified": True, "provider_receipts": receipts})
    def arm_factory(*, profile, artifact_dir, run_root):
        arm_id, provider = profile["arm_id"], profile["provider_id"]
        events.append("construct:" + arm_id)
        def call(image, request):
            events.append("call:" + arm_id)
            if arm_id in (*cli.STAGE2, cli.FALLBACK) and (request == {"goal": "button: Open"} or (state["incompatible"] and arm_id == cli.STAGE2[0])):
                if state["incompatible"] and arm_id == cli.STAGE2[0]:
                    from scripts.model_servers.goal_binding_transformers_worker import native_trace_envelope
                    envelope = native_trace_envelope(profile_identity={"profile_id": profile["profile_id"], "runtime_sha256": "a" * 64, "preprocessing_sha256": "b" * 64, "native_output_kind": profile["native_output"]["kind"]}, raw_native_output="", parsed_native=None, worker_process_identity={"pid": 42, "create_time_ns": 99}, resource_metrics={"latency_ms": 0, "peak_vram_bytes": None, "peak_vram_status": "unavailable", "generation_tokens": None, "request_bytes": 0, "provider_stdout_bytes": 0, "provider_stderr_bytes": 0, "timeout_seconds": 5}, request_lineage={"screenshot_sha256": sha256(image.read_bytes()).hexdigest(), "screenshot_dimensions": [100, 80]})
                    envelope.update(contract_version="goal_binding_native_trace_v2", outcome="provider_failure", failure={"kind": "provider_platform_incompatible", "message": "fixture incompatible", "attempted": False, "terminal": True})
                    return envelope
                return "[500,500]"
            if provider == "qwen3_vl_8b_q4_k_m":
                return [{"goal_index": 0, "candidate_index": None, "status": "UNBOUND", "confidence": 0.0}]
            return [0.2, 0.375] if state["passer"] == arm_id else [-1, -1]
        adapt = adapt_incumbent_candidate_index if provider == "qwen3_vl_8b_q4_k_m" else make_native_point_adapter(parse_ui_venus_point, {"contract_version": "goal_binding_native_profile_v1", "provider_id": provider, "native_shape": "ui_venus_point_v1", "coordinate_space": "normalized_0_1"})
        def cleanup():
            events.append("cleanup:" + arm_id)
            return clean(provider) | ({"verified": False, "cleanup_status": "failed"} if state["broken_cleanup"] else {})
        return GoalBindingArm(arm_id, provider, call, adapt, cleanup)
    def run(mode, *extra, factories=True):
        return cli.main(["--mode", mode, "--storage-root", str(storage), "--artifact-root", str(root), "--operator-approved-model-start", *extra], slots_factory=slots_factory if factories else None, arm_factory=arm_factory if factories else None)
    return cli, root, storage, state, run


def test_all_arms_are_forced_to_one_snapshot_sha(experiment):
    cli, root, _, state, run = experiment
    assert run("snapshot") == 0
    assert run("arm", "--arm-id", cli.INCUMBENT) == 0
    assert run("arm", "--arm-id", cli.STAGE1[0]) == 0
    outputs = [json.loads((root / "arms" / arm / "provider-diagnostic.json").read_text(encoding="utf-8")) for arm in (cli.INCUMBENT, cli.STAGE1[0])]
    assert outputs[0]["omni_snapshot_ref"] == outputs[1]["omni_snapshot_ref"]
    assert state["events"].count("omni") == 5
    assert all(sum(event == "call:" + arm for event in state["events"]) == 25 for arm in (cli.INCUMBENT, cli.STAGE1[0]))
    assert run("snapshot") == 2


def test_stage2_is_skipped_when_any_stage1_arm_passes(experiment):
    cli, root, _, state, run = experiment
    state["passer"] = cli.STAGE1[0]
    assert run("matrix") == 0
    report = json.loads((root / "matrix-report.json").read_text(encoding="utf-8"))
    assert [item["arm_id"] for item in report["arms"]] == [cli.INCUMBENT, *cli.STAGE1]
    assert not any("construct:" + arm in state["events"] for arm in (*cli.STAGE2, cli.FALLBACK))


def test_score_mode_never_constructs_model_or_omni_callers(experiment, monkeypatch):
    cli, root, _, state, run = experiment
    assert run("snapshot") == 0
    assert run("arm", "--arm-id", cli.INCUMBENT) == 0
    before = list(state["events"])
    monkeypatch.setattr(cli, "_profile", lambda *args: pytest.fail("score opened model profiles"))
    assert run("score", factories=False) == 0
    assert state["events"] == before
    assert json.loads((root / "matrix-report.json").read_text(encoding="utf-8"))["holdout_accessed"] is False


def test_cleanup_failure_and_storage_overage_block_next_arm(experiment, monkeypatch):
    from app.learn.hybrid import model_test_storage
    cli, root, _, state, run = experiment
    assert run("snapshot") == 0
    state["broken_cleanup"] = True
    assert run("matrix") == 2
    assert "construct:" + cli.STAGE1[0] not in state["events"]
    before = list(state["events"])
    monkeypatch.setattr(model_test_storage, "inventory_storage", lambda root: {"logical_bytes": cli.CAP + 1, "within_cap": False, "max_bytes": cli.CAP})
    assert run("matrix") == 2
    assert state["events"] == before


def test_snapshot_tamper_and_holdout_root_block_before_caller(experiment):
    cli, root, storage, state, run = experiment
    assert run("snapshot") == 0
    candidate = root / "omni-snapshot-v1/case-001.candidates.json"
    candidate.write_bytes(candidate.read_bytes() + b" ")
    before = list(state["events"])
    assert run("arm", "--arm-id", cli.INCUMBENT) == 2
    assert state["events"] == before
    assert cli.main(["--artifact-root", str(root / "holdout")]) == 2


@pytest.mark.parametrize("incompatible", [False, True])
def test_stage2_order_uses_venus_1_5_8b_only_after_venus_2_incompatibility(experiment, incompatible):
    cli, root, _, state, run = experiment
    state["incompatible"] = incompatible
    assert run("matrix") == 0
    arms = [item["arm_id"] for item in json.loads((root / "matrix-report.json").read_text(encoding="utf-8"))["arms"]]
    assert arms == [cli.INCUMBENT, *cli.STAGE1, *cli.STAGE2, *([cli.FALLBACK] if incompatible else [])]
    if incompatible:
        report = json.loads((root / "arms" / cli.STAGE2[0] / "binder-report.json").read_text(encoding="utf-8"))
        assert report["metrics"]["provider_failure_abstain"]["numerator"] == 25
        assert report["metrics"]["native_parse_success"]["numerator"] == 0
    for arm_id in (*cli.STAGE2, *([cli.FALLBACK] if incompatible else [])):
        probe = json.loads((root / "probes" / arm_id / "probe.json").read_text(encoding="utf-8"))
        assert probe["cleanup"]["verified"] is True and probe["contains_holdout"] is False
        assert probe["candidate_mapping"] is None


def test_manual_stage2_cannot_skip_stage1(experiment):
    cli, _, _, state, run = experiment
    assert run("snapshot") == 0
    before = list(state["events"])
    assert run("arm", "--arm-id", cli.STAGE2[0]) == 2
    assert state["events"] == before


def test_cleanup_is_evidence_only_and_does_not_read_gold_or_construct_callers(experiment, monkeypatch):
    cli, root, _, state, run = experiment
    assert run("snapshot") == 0
    assert run("arm", "--arm-id", cli.INCUMBENT) == 0
    before = list(state["events"])
    monkeypatch.setattr(cli, "_score_report", lambda *args: pytest.fail("cleanup opened Gold"))
    assert run("cleanup", factories=False) == 0
    assert state["events"] == before
    assert json.loads((root / "cleanup-receipt.json").read_text(encoding="utf-8"))["verified"] is True


def test_unacquired_arm_records_blocker_without_caller_or_fake_score(experiment, monkeypatch):
    from app.learn.hybrid.goal_binding_model_callers import _verified
    cli, root, _, state, run = experiment
    assert run("snapshot") == 0
    monkeypatch.setattr(cli, "_available", _verified)
    before = list(state["events"])
    assert run("arm", "--arm-id", cli.INCUMBENT) == 2
    assert state["events"] == before
    journal = json.loads((root / "stage-journal.json").read_text(encoding="utf-8"))
    assert journal["events"][-1]["state"] == "profile_unavailable"
    assert journal["events"][-1]["inference_attempted"] is False
    assert not (root / "arms" / cli.INCUMBENT / "binder-report.json").exists()


def test_completed_matrix_resume_does_not_reload_any_provider(experiment):
    cli, _, _, state, run = experiment
    state["passer"] = cli.STAGE1[0]
    assert run("matrix") == 0
    before = list(state["events"])
    assert run("matrix", factories=False) == 0
    assert state["events"] == before


def test_config_cannot_change_frozen_order_or_targets(tmp_path):
    cli = importlib.import_module("scripts.run_goal_binding_provider_ab")
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    config["matrix"]["stage1"].reverse()
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ValueError, match="stage order"):
        cli._config(path)
