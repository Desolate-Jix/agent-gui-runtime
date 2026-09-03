from __future__ import annotations

import json
import argparse
from hashlib import sha256
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_simple_native_provider_smoke.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=ROOT, text=True, capture_output=True, check=False)


def test_cli_defaults_to_preflight_and_never_builds_actual_callers() -> None:
    result = _run()
    assert result.returncode == 0 and "preflight" in result.stdout


def test_cli_replay_runs_only_the_five_regression_cases(tmp_path: Path) -> None:
    result = _run("--mode", "replay", "--replay-dir", "tests/fixtures/simple_native_provider_smoke/replay", "--artifact-dir", str(tmp_path))
    assert result.returncode == 0
    provider_path = tmp_path / "provider-diagnostic.json"
    assert json.loads(provider_path.read_text(encoding="utf-8"))["screen_count"] == 5
    report = json.loads((tmp_path / "regression-report.json").read_text(encoding="utf-8"))
    assert report["provider_artifact_sha256"] == sha256(provider_path.read_bytes()).hexdigest()


def test_cli_actual_requires_explicit_model_start_flag() -> None:
    result = _run("--mode", "actual", "--artifact-dir", ".artifacts/nope")
    assert result.returncode != 0 and "operator-approved-model-start" in result.stderr


def test_cli_actual_flag_reaches_only_injected_lazy_factory(tmp_path: Path, monkeypatch) -> None:
    from scripts import run_simple_native_provider_smoke as cli

    calls: list[dict[str, object]] = []
    monkeypatch.setenv("AGENT_GUI_TEST_DENY_REAL_MODEL_WRAPPER", "1")
    monkeypatch.setattr(
        cli,
        "_arguments",
        lambda: argparse.Namespace(
            mode="actual",
            config=ROOT / "configs/benchmarks/simple_native_provider_smoke_v1.json",
            artifact_dir=tmp_path / "actual",
            replay_dir=None,
            operator_approved_model_start=True,
        ),
    )

    def factory(*, config, artifact_dir):
        calls.append({"config": config, "artifact_dir": artifact_dir})
        return cli._replay_slots(ROOT / "tests/fixtures/simple_native_provider_smoke/replay")

    assert cli.main(actual_slots_factory=factory) == 0
    assert len(calls) == 1
    assert "scorer_gold_path" not in calls[0]["config"]
    assert (tmp_path / "actual" / "provider-diagnostic.json").is_file()


def test_config_names_exact_launchable_provider_profiles() -> None:
    config = json.loads(
        (ROOT / "configs/benchmarks/simple_native_provider_smoke_v1.json").read_text(encoding="utf-8")
    )
    assert config["provider"]["profile_ids"] == {
        "omni": "local.runtime/omniparser/shadow-v2",
        "qwen": "qwen3_vl_8b_q4_k_m",
        "vista": "vista_4b_transformers",
    }


def test_config_contains_no_holdout_and_no_scorer_fields_in_provider_projection() -> None:
    config=json.loads((ROOT / "configs/benchmarks/simple_native_provider_smoke_v1.json").read_text(encoding="utf-8"))
    assert "holdout" not in json.dumps(config).lower() and "gold" not in json.dumps(config["provider"]).lower()


def test_cli_rejects_changed_screenshot_and_prompt_hashes(tmp_path: Path) -> None:
    config=json.loads((ROOT / "configs/benchmarks/simple_native_provider_smoke_v1.json").read_text(encoding="utf-8")); config["screens"][0]["sha256"]="0"*64
    path=tmp_path / "bad.json"; path.write_text(json.dumps(config),encoding="utf-8")
    result=_run("--config", str(path))
    assert result.returncode != 0 and "sha256" in result.stderr


def test_cli_replay_rejects_malformed_jsonl(tmp_path: Path) -> None:
    replay=tmp_path / "replay"; replay.mkdir()
    for name in ("omni.jsonl", "qwen.jsonl", "vista.jsonl"):
        (replay / name).write_text("THIS IS INVALID\n", encoding="utf-8")
    result=_run("--mode", "replay", "--replay-dir", str(replay), "--artifact-dir", str(tmp_path / "out"))
    assert result.returncode != 0 and "replay fixture invalid" in result.stderr


def test_cli_replay_abstains_when_qwen_cardinality_disagrees_with_omni(tmp_path: Path) -> None:
    replay = tmp_path / "replay"
    replay.mkdir()
    omni = {"items": [{"bbox": [0.1, 0.1, 0.2, 0.2], "type": "text", "content": "x", "interactivity": True}]}
    incompatible = [
        {"goal_index": index, "candidate_index": 0, "status": "BOUND", "confidence": 1}
        for index in range(4)
    ]
    (replay / "omni.jsonl").write_text("\n".join(json.dumps(omni) for _ in range(5)) + "\n", encoding="utf-8")
    (replay / "qwen.jsonl").write_text("\n".join(json.dumps(incompatible) for _ in range(5)) + "\n", encoding="utf-8")
    (replay / "vista.jsonl").write_text("[500,500]\n", encoding="utf-8")

    artifact_dir = tmp_path / "out"
    result = _run("--mode", "replay", "--replay-dir", str(replay), "--artifact-dir", str(artifact_dir))

    assert result.returncode == 0
    provider = json.loads((artifact_dir / "provider-diagnostic.json").read_text(encoding="utf-8"))
    report = json.loads((artifact_dir / "regression-report.json").read_text(encoding="utf-8"))
    assert provider["metrics"]["qwen"]["schema_invalid"] == 2
    assert provider["metrics"]["vista"]["attempted"] == 0
    assert report["abstained"] == report["denominator"] == 25
