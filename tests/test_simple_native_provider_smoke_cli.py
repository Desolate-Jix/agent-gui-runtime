from __future__ import annotations

import json
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
    assert json.loads((tmp_path / "provider-diagnostic.json").read_text(encoding="utf-8"))["screen_count"] == 5


def test_cli_actual_requires_explicit_model_start_flag() -> None:
    result = _run("--mode", "actual", "--artifact-dir", ".artifacts/nope")
    assert result.returncode != 0 and "operator-approved-model-start" in result.stderr


def test_cli_actual_flag_does_not_bypass_current_user_approval_policy() -> None:
    result = _run("--mode", "actual", "--operator-approved-model-start", "--artifact-dir", ".artifacts/nope")
    assert result.returncode != 0 and "current user approval" in result.stderr


def test_config_contains_no_holdout_and_no_scorer_fields_in_provider_projection() -> None:
    config=json.loads((ROOT / "configs/benchmarks/simple_native_provider_smoke_v1.json").read_text(encoding="utf-8"))
    assert "holdout" not in json.dumps(config).lower() and "gold" not in json.dumps(config["provider"]).lower()


def test_cli_rejects_changed_screenshot_and_prompt_hashes(tmp_path: Path) -> None:
    config=json.loads((ROOT / "configs/benchmarks/simple_native_provider_smoke_v1.json").read_text(encoding="utf-8")); config["screens"][0]["sha256"]="0"*64
    path=tmp_path / "bad.json"; path.write_text(json.dumps(config),encoding="utf-8")
    result=_run("--config", str(path))
    assert result.returncode != 0 and "sha256" in result.stderr
