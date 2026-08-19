# OmniParser Learning Shadow Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 接通 OmniParser 的学习态 shadow 输出、截图 lineage 与本机真实无动作 smoke，同时保持所有执行授权关闭。

**Architecture:** 官方 OmniParser 输出先规范化为 `screen_parser_result_v1`，再进入现有 `sources.omniparser` 适配器。Recognition pipeline 可把同截图交互证据送入 ROI grounding；Two-stage Stage1 只接收 review-only 投影。真实 provider 通过独立 smoke runner 调用，不污染现有 Qwen/VISTA runtime。

**Tech Stack:** Python 3.11、Pydantic/FastAPI 既有合同、pytest、official OmniParser v.2.0.1、PyTorch CUDA、PowerShell/nvidia-smi。

**Spec:** `docs/superpowers/specs/2026-08-19-omniparser-learning-shadow-integration-design.md`

## Global Constraints

- OmniParser 输出永远不是点击授权；`artifact_is_authorization=false`、`execute_binding_enabled=false`、`real_action_requires_gate=true`。
- 只有同一 screenshot SHA、非 stale 的候选可进入 ROI grounding。
- Stage1 OmniParser 投影始终 review-only、grounding-disabled。
- 不修改或覆盖当前未提交的 SEEK demo/识别改动。
- 不运行真实 GUI 点击；smoke 只使用已脱敏静态图。
- 所有中文文件以 UTF-8 读写。

---

### Task 1: 主流程转发、Stage1 投影与 freshness gate

**Files:**
- Modify: `app/learn/workflow_tasks/recognition.py`
- Modify: `app/learn/recognition/trace_input.py`
- Modify: `app/learn/recognition/eligibility.py`
- Modify: `app/learn/recognition/parsers.py`
- Test: `tests/test_learning_workflow_task_boundaries.py`
- Test: `tests/test_learn_stage1_inventory_from_observe_trace.py`
- Test: `tests/test_learn_recognition_parsers.py`

**Interfaces:**
- Consumes: `observation_evidence.omniparser` as `screen_parser_result_v1` or compatible official raw result.
- Produces: `learn_observe_bundle_v1.sources.omniparser` and review-only Stage1 items with preserved parser lineage.

- [ ] 写主流程转发、Stage1 read-only 与 stale/missing screenshot lineage 的失败测试。
- [ ] 运行三个测试文件并确认失败原因是缺少接线/freshness gate。
- [ ] 最小实现深拷贝转发、provenance 字段转发、Stage1 review-only 投影和 parser freshness 阻断。
- [ ] 重跑三个测试文件直至通过，并运行 `python -m py_compile`。
- [ ] 独立审查该任务的 diff 与安全边界。

### Task 2: 规范化合同与真实 OmniParser smoke runner

**Files:**
- Create: `app/learn/recognition/omniparser_provider.py`
- Create: `scripts/run_omniparser_learn_smoke.py`
- Create: `tests/test_omniparser_provider.py`
- Modify: `configs/model_profiles/learn_mode_omniparser_v2.json`
- Modify: `tests/test_learn_recognition_model_profiles.py`

**Interfaces:**
- Consumes: official OmniParser `parsed_content_list`, screenshot path and pinned model provenance.
- Produces: validated `screen_parser_result_v1` JSON with SHA, image size, timing, resource data and stable error codes.

- [ ] 写规范化成功、非法 bbox、缺权重/依赖、截图 SHA 绑定和非授权字段测试。
- [ ] 运行 provider 测试并确认 RED。
- [ ] 实现纯规范化模块和 learn-only CLI；profile 只声明 provider contract/runtime probe，不无条件宣称 launchable。
- [ ] 重跑 provider/profile 测试与 `py_compile`。
- [ ] 克隆固定官方 tag、下载固定 revision 权重到 gitignored 目录，记录代码/权重 hash 与许可证来源。
- [ ] 用已脱敏 contact sheet 跑一次真实冷启动和三次热推理，保存 JSON/日志并确认无 GUI 动作。
- [ ] 独立审查 runner、错误合同、许可证与资源生命周期。

### Task 3: 面板可见状态与文档

**Files:**
- Modify: `app/learn/workflow_tasks/recognition.py`
- Modify: `app/web_panel/panel.js`
- Modify: `app/web_panel/index.html`
- Test: `tests/test_learning_draft_review.py`
- Test: `tests/js/panel_learning_observation_evidence.test.cjs`
- Modify: `README.md`
- Modify: `ARCHITECTURE.md`
- Modify: `CURRENT_STATE.md`
- Modify: `NEXT_STEPS.md`
- Modify: `docs/superpowers/specs/2026-07-03-learning-recognition-rebuild-design.md`

**Interfaces:**
- Consumes: `screen_parser_result_v1` and recognition trial summary.
- Produces: panel-visible provider status/candidate counts/lineage warnings without execute controls.

- [ ] 写 panel evidence 保留 Omni 输出和 review response 暴露 provider 状态的失败测试。
- [ ] 运行 Python/JS 窄测试确认 RED。
- [ ] 实现只读状态呈现，区分 provider success、candidate generated、grounding eligible 和 execution authorized。
- [ ] 更新相关文档，记录真实 smoke 指标与未完成限制。
- [ ] 运行窄 Python/JS 回归、`node --check`、`git diff --check`。
- [ ] 做一次最终全分支独立审查并处理阻断性发现。

