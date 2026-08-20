# Learn/Execute MVP Checkpoint

## 目标

这个 checkpoint 用来回答一个问题：当前 Learn Mode 产物能不能安全地支撑 Execute Mode 做连续 agent 调用，而不是只会点击一个按钮。

它不是新的后端多步执行器。多步决策仍然由上层 agent 做；本层只证明每次调用都能从 PathGraph 里取出一个可解释动作，并通过现有单步 Execute API 生成证据。

2026-06-19 面板更新后，这个 checkpoint 也能在测试面板中直接观察：Learn Mode 会显示 Artifact Replay 和 PathGraph Safe Validation；Execute Mode 会显示 PathGraph Task Run。切换工作区时，另一个工作区的功能页会隐藏，Session/System 工具仍然全局可见。学习产物会渲染到原来的导航路径图卡片里；安全验证或任务运行每调用一次 `/execute/step`，返回的 `path_graph_runtime_state_v1` 会高亮当前节点、当前动作边、已完成边或失败边。Timeline 同步显示 skill、低层动作类型、from/to state 和 trace path。

2026-06-19 之后，开始新的 Learn Mode 样本前还要看 `learn_sample_readiness_gate_v1`。它由 `scripts/learn_sample_readiness_gate.py` 合成 checkpoint 和统一回归结果，面板 Learn Mode / Artifact Replay 会显示 `ready_for_new_learn_sample`。当前门禁要求：5 个 baseline 全通过，click / scroll / input / read / guarded actions 覆盖完整，`artifact_authorizes_click=false`，`write_actions_clicked=0`，`final_submissions=0`，并且存在 `artifacts/templates/learn_sample_template_v1.json`。Codex 内置浏览器只用于 ChatGPT 会话；测试面板和新样本 smoke 必须使用外部浏览器或原生应用窗口。

## 当前产物

- `logs/smoke/seek_learn_safe_validation_20260619.json`
  - 验证 SEEK 学习产物里的安全动作。
  - `open_job_card` 必须是 click。
  - `read_detail` 必须滚动 `seek:job_detail`。
  - `load_more_results` 必须滚动 `seek:results_list`。
  - `apply_entry` 必须隐藏。
  - Learn safe validation 中不暴露 input 动作。
- `logs/smoke/seek_learn_task_run_3jobs_20260619.json`
  - 把现有 SEEK 3-job artifact replay 包装成学习产物回放报告。
  - 要求 `jobs_opened=3`、`jobs_fully_read=3`、`card_click_open_rate=1.0`。
  - 要求 `post_click_layout_drift_count=0`、`wrong_scope_scroll_count=0`、`final_submissions=0`。
- `artifacts/skills/learned_skill_matrix_v1.json`
  - 汇总现有学习样本中的通用 Execute skill。
  - 当前必须覆盖 click、scroll、input、read、guarded actions。
  - 现在还必须覆盖 Table Directory 的 filter/tab、sort/filter-click、table record open。
  - `artifact_authorizes_click=false`，也就是 artifact 只是证据，不是点击许可。
- `artifacts/table_directory/runtime_path_graph_table_directory_v1.json`
  - 第五类 UI family 的路径图种子：`table/filter/sort -> row detail`。
  - 包含 `switch_filter_tab`、`sort_records`、`open_record_from_table`、`read_record_detail`、`return_to_table`、`load_more_records`。
  - `blocked_write_action` 默认隐藏，用来证明 Edit / Delete / Save / Create / Upload / Login / Submit / Purchase 等高风险入口不能出现在可用动作里。
- `logs/smoke/table_directory_datatables_real_1record_20260619.json`
  - 当前真实外部网站 smoke，使用公开 DataTables row-details 页面。
  - 先 dry-run 并检查 overlay，再执行 approved plan 点击第一行左侧展开控件。
  - 第二步调用 `read_record_detail` 滚动页面，截图确认详情内容可见。
  - 报告写入 `real_external_smoke=true`、`fixture_only=false`。
- `logs/smoke/learn_execute_mvp_checkpoint_20260619.json`
  - 总 checkpoint，当前状态为 `pass`。
- `logs/smoke/learn_sample_readiness_gate_20260619.json`
  - 新样本前置门禁，当前 `ready_for_new_learn_sample=true`。

## 执行动作类型

Execute Mode 的“当前状态 / 可用动作”不应该只显示点击。它应该显示 agent 下一步可以选择的动作类型：

- click：例如打开列表卡片、打开搜索结果、点击搜索按钮。
- scroll/read：例如滚动详情栏、滚动页面正文、继续读取当前内容。
- input：只允许明确的低风险公开输入，例如 Python Docs public search query。
- guard：例如 Apply / Submit / Save / Delete 这类动作默认隐藏或阻断。
- filter/tab：例如切换只读筛选 tab 或 chip。
- sort：例如点击只读排序列头或排序按钮。
- table row open：例如点击表格行的展开/详情控件、行标题或主链接来打开目录记录详情。若页面有左侧加号、三角、chevron 等展开列，应优先定位这个控件，而不是普通文字。

这些动作都来自学习产物和当前状态匹配结果，但每次真实执行仍要经过对应的底层 API 和安全检查。

## 回归门禁

`scripts/artifact_replay_regression_report.py` 输出：

```json
{
  "regression_gate": {
    "overall_status": "pass",
    "can_continue_to_new_family": true,
    "blocking_failures": []
  }
}
```

`scripts/learn_sample_readiness_gate.py` 输出：

```json
{
  "status": "pass",
  "ready_for_new_learn_sample": true,
  "next_sample_policy": {
    "codex_in_app_browser": "chatgpt_only",
    "test_panel_target": "external_browser_or_native_app"
  }
}
```

只有 `can_continue_to_new_family=true` 且 `ready_for_new_learn_sample=true` 时，才适合继续真实网站或桌面应用学习。否则先修当前失败的主路径，不要加兜底掩盖问题。

## 运行命令

```powershell
uv run python scripts\learn_execute_checkpoint_report.py --fail-on-error
uv run python scripts\artifact_replay_regression_report.py --out logs\smoke\artifact_replay_regression_20260619.json --fail-on-error
uv run python scripts\learn_sample_readiness_gate.py --fail-on-error
uv run pytest tests\test_learn_execute_checkpoint_report.py tests\test_artifact_replay_regression_report.py tests\test_path_graph_execute.py tests\test_learn_sample_readiness_gate.py -q
```

## 下一步

下一阶段要先通过 `learn_sample_readiness_gate_v1`，再换一个完全不同的网站或应用做新的学习样本。入口应该是：

1. 复制并填写 `artifacts/templates/learn_sample_template_v1.json`。
2. 用 checkpoint 和 readiness gate 检查通用 skill 覆盖没有倒退。
3. 先 dry-run observe / available actions，再 dry-run `/execute/step`。
4. 只执行一个安全 live action，之后再跑小型 task run。
5. 通过后把新样本加入 unified artifact replay regression。

不要把连续多步 orchestration 塞进 Execute API；Execute API 保持单步、可审计、可回放。
