"""只运行明确列出的离线学习接缝测试；不是全仓测试或模型验收。"""

import argparse
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
_FAST = (
    "tests/test_learn_hybrid_target_selection.py",
    "tests/test_learn_hybrid_refinement_policy.py",
    "tests/test_learn_hybrid_selection_review.py",
    "tests/test_learn_hybrid_selection_comparison.py",
)
_INTEGRATION = (
    "tests/test_learning_selection_actual_flow.py",
    "tests/test_learning_selection_actual_origin.py",
    "tests/test_learning_static_capture.py",
    "tests/test_learning_gui_actor_current_source.py",
    "tests/test_learning_vista_current_source.py",
    "tests/test_learning_selection_refinement.py",
    "tests/test_learning_selection_acceptance_catalog.py",
    "tests/test_learning_selection_acceptance_runner.py",
    "tests/test_learning_selection_acceptance_export.py",
    "tests/test_omni_trusted_asset_paths.py",
    "tests/test_learning_selection_public_flow.py",
    "tests/test_learning_selection_roundtrip.py",
    "tests/test_learning_selection_save_integrity.py",
    "tests/test_learning_workflow_selection_mode.py",
    "tests/test_panel_selection_rollout_boundary.py",
    "tests/test_check_learning_integration.py",
    "tests/test_goal_binding_native_adapters.py",
    "tests/test_goal_binding_provider.py",
    "tests/test_learn_hybrid_contracts.py",
    "tests/test_learn_hybrid_review.py",
)
_JAVASCRIPT = (
    "tests/js/panel_learning_selection_review.test.cjs",
    "tests/js/panel_learning_hybrid_review.test.cjs",
    "tests/js/panel_learning_selection_flow.test.cjs",
)


def build_commands(suite: str, *, python: str = sys.executable) -> list[list[str]]:
    """固定集合不按文件名猜测副作用，也不静默缩小失败集合。"""
    if suite not in {"fast", "integration"}:
        raise ValueError("suite must be fast or integration")
    tests = _FAST + (_INTEGRATION if suite == "integration" else ())
    commands = [[python, "-m", "pytest", "-q", *tests]]
    if suite == "integration":
        commands.append(["node", "--test", *_JAVASCRIPT])
    return commands


def run_checks(suite: str, *, runner=subprocess.run) -> int:
    for command in build_commands(suite):
        print("OFFLINE CHECK: " + subprocess.list2cmdline(command), flush=True)
        try:
            runner(command, cwd=ROOT, check=True)
        except subprocess.CalledProcessError as error:
            print(f"Offline check failed: exit {error.returncode}", file=sys.stderr)
            return error.returncode if error.returncode > 0 else 1
        except OSError as error:
            print(f"Offline check could not start: {error}", file=sys.stderr)
            return 1
    print("Selected offline checks passed; actual-model and full-repository tests were not run.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("fast", "integration"), default="fast")
    return run_checks(parser.parse_args().suite)


if __name__ == "__main__":
    raise SystemExit(main())
