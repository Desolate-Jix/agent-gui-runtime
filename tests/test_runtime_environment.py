import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys

import pytest


def _missing_version(name):
    raise importlib.metadata.PackageNotFoundError(name)


def test_missing_metadata_is_actionable_but_never_execution_readiness():
    from app.runtime_environment import inspect_environment
    report = inspect_environment(find_spec=lambda name: None, version=_missing_version)
    assert report["contract_version"] == "native_environment_metadata_v1"
    assert report["status"] == "blocked"
    assert "PySide6" in report["missing_modules"]
    assert "mcp" in report["missing_modules"]
    assert report["runtime_verified"] is False
    assert report["imports_exercised"] is False
    assert report["artifact_is_authorization"] is False


def test_discovered_modules_are_explicitly_unverified_and_no_models_are_probed():
    from app.runtime_environment import inspect_environment
    seen = []

    def discover(name):
        assert "." not in name
        seen.append(name)
        return object()

    report = inspect_environment(find_spec=discover, version=lambda name: "1.2.3",
                                 python_version=(3, 11, 9), platform="win32")
    assert report["status"] == "metadata_present_unverified"
    assert report["missing_modules"] == []
    assert len(seen) == len(set(seen))
    assert not {"torch", "transformers", "paddleocr", "cv2", "numpy"}.intersection(seen)
    assert report["runtime_verified"] is False
    assert report["model_assets_checked"] is False


def test_lookup_failures_are_reported_without_private_exception_text():
    from app.runtime_environment import inspect_environment

    def fail(name):
        raise ValueError("private-environment-secret")

    report = inspect_environment(find_spec=fail, version=_missing_version)
    assert report["status"] == "blocked"
    assert report["probe_errors"]
    assert "private-environment-secret" not in json.dumps(report)


def test_discoverable_modules_without_distribution_metadata_remain_blocked():
    from app.runtime_environment import inspect_environment
    report = inspect_environment(find_spec=lambda name: object(), version=_missing_version)
    assert report["status"] == "blocked"
    assert report["missing_modules"] == []
    assert "Pillow" in report["missing_distributions"]


def test_distribution_probe_failure_is_redacted_and_blocks_readiness():
    from app.runtime_environment import inspect_environment

    def fail(name):
        raise OSError("private-distribution-path")

    report = inspect_environment(find_spec=lambda name: object(), version=fail)
    assert report["status"] == "blocked"
    assert report["probe_errors"][0]["stage"] == "distribution_version"
    assert "private-distribution-path" not in json.dumps(report)


@pytest.mark.parametrize("python_version,platform", [((3, 12, 1), "win32"), ((3, 11, 9), "linux")])
def test_unsupported_runtime_platform_is_not_metadata_ready(python_version, platform):
    from app.runtime_environment import inspect_environment
    report = inspect_environment(profile="windows_runtime", find_spec=lambda name: object(),
                                 version=lambda name: "1.2.3", python_version=python_version, platform=platform)
    assert report["status"] == "blocked"


def test_desktop_and_bridge_profiles_do_not_require_window_or_model_packages():
    from app.runtime_environment import inspect_environment
    for profile in ("desktop_review", "agent_bridge"):
        report = inspect_environment(profile=profile, find_spec=lambda name: object(), version=lambda name: "1.2.3")
        names = [item["module"] for item in report["checks"]]
        assert not {"loguru", "pywinauto", "mss", "torch"}.intersection(names)


def test_standalone_checker_runs_without_any_site_packages_and_does_not_create_state(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts/check_desktop_environment.py"
    result = subprocess.run([sys.executable, "-S", str(script)], cwd=tmp_path, capture_output=True,
                            text=True, encoding="utf-8", timeout=15)
    assert result.returncode == 2
    report = json.loads(result.stdout)
    assert report["status"] == "blocked"
    assert report["imports_exercised"] is False
    assert not list(tmp_path.iterdir())


def test_checker_import_does_not_load_desktop_package_or_application_backends(tmp_path):
    root = Path(__file__).resolve().parents[1]
    code = "import sys,json;sys.path.insert(0," + repr(str(root)) + ");from app.runtime_environment import inspect_environment;inspect_environment();print(json.dumps(sorted(sys.modules)))"
    result = subprocess.run([sys.executable, "-S", "-c", code], cwd=tmp_path, capture_output=True,
                            text=True, encoding="utf-8", timeout=15)
    assert result.returncode == 0, result.stderr
    modules = json.loads(result.stdout)
    assert not any(name.startswith(("app.desktop_review", "app.core", "PySide6", "pywinauto", "comtypes", "torch")) for name in modules)
