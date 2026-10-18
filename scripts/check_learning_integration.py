"""串行运行明确列出的离线学习接缝测试；不是全仓测试或模型验收。

覆盖 Python 学习选择/资产/Agent 接缝及明确列出的 Node.js 面板状态/渲染测试。不会启动模型、OCR、GPU
作业、浏览器、GUI 或网络服务；完整仓库和实际模型测试明确不在此入口中。
"""

import argparse
import os
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
    "tests/test_learning_new_asset_offline.py",
    "tests/test_web_panel_route.py::test_web_panel_serves_browser_control_surface",
    "tests/test_web_panel_route.py::test_web_panel_serves_static_assets",
    "tests/test_learning_new_asset_agent_roundtrip.py",
    "tests/test_agent_observation_compiled_projection.py",
    "tests/test_agent_observation_adapter_v1.py",
    "tests/test_agent_runtime_api_v1.py",
    "tests/test_live_controller_w4.py",
    "tests/test_interface_workflow_review.py",
    "tests/test_reviewed_workflow_compiler_v2.py",
    "tests/test_reviewed_workflow_v2_api.py",
    "tests/test_learning_asset_readonly_compatibility.py",
    "tests/test_runtime_contracts.py::test_dataflow_requires_latest_detail_snapshot_for_downstream_steps",
    "tests/test_runtime_contracts.py::test_candidate_freshness_rejects_stale_capture_coordinates",
    "tests/test_runtime_contracts.py::test_action_taxonomy_separates_apply_entry_from_final_submit",
    "tests/test_runtime_contracts.py::test_scoped_final_submit_ignores_search_submit_outside_application_flow",
    "tests/test_runtime_contracts.py::test_scoped_final_submit_blocks_inside_active_application_container",
    "tests/test_runtime_contracts.py::test_scroll_scope_invariant_flags_non_target_pane_change",
    "tests/test_runtime_contracts.py::test_ocr_canonicalization_is_short_acronym_only",
    "tests/test_development_state_paths.py",
    "tests/test_start_test_panel_launcher.py",
    "tests/test_check_learning_environment.py",
    "tests/test_application_metadata.py",
    "tests/test_portfolio_hybrid_v1_1_benchmark_v2_runtime_recovery.py::test_reserve_attempt_is_metadata_only_idempotent_and_cleanup_recoverable",
    "tests/test_portfolio_hybrid_v1_1_benchmark_v2_runtime_recovery.py::test_reserve_attempt_accepts_only_the_existing_initial_reservation",
    "tests/test_portfolio_hybrid_v1_1_benchmark_v2_runtime_recovery.py::test_reserve_attempt_rejects_nonempty_invalid_reservation",
    "tests/test_portfolio_hybrid_v1_1_benchmark_v2_runtime_recovery.py::test_prepare_screen_groups_rejects_nonreservation_journal_before_allocation",
    "tests/test_portfolio_hybrid_v1_1_benchmark_v2_runtime_recovery.py::test_cleanup_rejects_missing_or_partial_reservation_journal",
    "tests/test_portfolio_hybrid_v1_1_benchmark_v2_runner.py::test_holdout_h2_first_claim_creates_exact_attempt_and_reopens_opened_chain",
    "tests/test_portfolio_hybrid_v1_1_benchmark_v2_runner.py::test_holdout_h2_reservation_failure_does_not_append_opened",
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
    "tests/js/interface_workflow_v2_panel.test.cjs",
    "tests/js/agent_runtime_panel.test.cjs",
    "tests/js/panel_primary_navigation.test.cjs",
)


def build_commands(suite: str, *, python: str = sys.executable) -> list[list[str]]:
    """固定集合不按文件名猜测副作用，也不静默缩小失败集合。"""
    if suite not in {"fast", "integration"}:
        raise ValueError("suite must be fast or integration")
    tests = _FAST + (_INTEGRATION if suite == "integration" else ())
    # 显式禁用 xdist，避免环境中的 pytest 插件改变此离线入口的串行语义。
    commands = [[python, "-m", "pytest", "-q", "-p", "no:xdist", *tests]]
    if suite == "integration":
        commands.append(["node", "--test", "--test-concurrency=1", *_JAVASCRIPT])
    return commands


def run_checks(suite: str, *, runner=subprocess.run) -> int:
    # 只约束测试子进程，避免外部插件/参数偷偷扩大离线集合或写入用户状态。
    environment = {
        **os.environ, "PYTEST_ADDOPTS": "", "PYTEST_PLUGINS": "",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONIOENCODING": "utf-8",
        "AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH": ":memory:", "CUDA_VISIBLE_DEVICES": "",
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
    }
    for command in build_commands(suite):
        print("OFFLINE CHECK: " + subprocess.list2cmdline(command), flush=True)
        try:
            runner(command, cwd=ROOT, check=True, env=environment)
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
