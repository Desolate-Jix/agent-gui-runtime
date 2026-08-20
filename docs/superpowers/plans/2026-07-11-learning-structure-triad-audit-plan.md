# Learning Structure Triad Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立原图、Stage1 栏图、最终融合图的强制审核工作流，并用通用证据规则修复三个回归界面的结构错误。

**Architecture:** 在现有 `two_stage.py` 中保留结构生成与编号流程，但增加结构证据验证和独立 Stage1 overlay。质量计算放入独立 benchmark/audit 脚本，fixture 只提供标注，生产识别逻辑不读取界面身份。

**Tech Stack:** Python 3、Pillow、pytest、现有 Learning Mode trace/replay。

## Global Constraints

- 生产规则禁止应用名、网站名、专用文本和固定界面坐标。
- `structure_region_match_rate >= 0.95`，每条归一化边界误差 `<= 0.10`。
- Stage1 未通过时禁止 Stage2。
- 全程 display-only，实时点击、填写和提交次数保持 0。

---

### Task 1: 结构证据门槛

**Files:**
- Modify: `app/learn/recognition/stage1_audit.py`
- Modify: `app/learn/recognition/two_stage.py`
- Test: `tests/test_learn_stage1_region_selection_audit.py`
- Test: `tests/test_learn_recognition_pipeline.py`

**Interfaces:**
- Consumes: `audit_stage1_region_selection(localized_regions, screen_size, overlay_path)`
- Produces: `missing_structure_families`、`unknown_only_structure`、`unsupported_sidebar_evidence` 失败分类。

- [ ] 添加 `unknown-only` 与单元素伪侧栏的失败测试。
- [ ] 运行目标测试并确认因缺少新门槛而失败。
- [ ] 最小实现结构族覆盖与侧栏证据校验。
- [ ] 运行目标测试并确认通过。

### Task 2: 主网格末列不得变成右栏

**Files:**
- Modify: `app/learn/recognition/two_stage.py`
- Test: `tests/test_learn_recognition_pipeline.py`

**Interfaces:**
- Consumes: `_split_right_sidebar_region(...)`
- Produces: 只有独立面板证据存在时才建立 `right_sidebar`。

- [ ] 用重复卡片网格 fixture 写右侧末列误分栏失败测试。
- [ ] 运行测试并确认当前实现失败。
- [ ] 增加跨列同类卡片连续性检查并保留主网格。
- [ ] 运行测试并确认通过。

### Task 3: 原生工具栏子项必须渲染

**Files:**
- Modify: `app/learn/recognition/two_stage.py`
- Test: `tests/test_learn_recognition_pipeline.py`

**Interfaces:**
- Consumes: `_render_two_stage_overlay(...)`
- Produces: 仅在真实浏览器 chrome 证据成立时抑制 chrome 子项；原生工具栏控件保留。

- [ ] 写 legacy `browser_chrome` 区域但无 URL/地址栏证据的渲染失败测试。
- [ ] 运行测试并确认顶栏子框缺失。
- [ ] 将抑制条件改为证据驱动，并保留浏览器噪声抑制测试。
- [ ] 运行测试并确认两类行为均通过。

### Task 4: 三联图与质量报告

**Files:**
- Modify: `app/learn/recognition/two_stage.py`
- Modify: `scripts/render_learning_interface_demo_visual_report.py`
- Create: `scripts/run_learning_structure_triad_benchmark.py`
- Create: `artifacts/benchmarks/learning_structure_triad_manifest_v1.json`
- Test: `tests/test_learning_interface_demo_visual_report.py`
- Create: `tests/test_learning_structure_triad_benchmark.py`

**Interfaces:**
- Produces: `stage1_structure_overlay_path` 与 `learning_structure_triad_report_v1`。
- Metric: `structure_region_match_rate`、`normalized_boundary_error`、`missing_regions`、`unexpected_regions`。

- [ ] 写同 capture/checksum 三联图、缺图 invalid、边界误差和匹配率测试。
- [ ] 运行测试并确认缺少实现。
- [ ] 实现 Stage1-only overlay、三联 contact sheet 和 benchmark runner。
- [ ] 运行测试并确认通过。

### Task 5: 三界面回归与文档同步

**Files:**
- Modify: `README.md`
- Modify: `PROJECT_SUMMARY.md`
- Modify: `CURRENT_STATE.md`
- Modify: `NEXT_STEPS.md`

**Interfaces:**
- Consumes: 三个固定 trace/screenshot fixture。
- Produces: 可复跑 benchmark report 和逐界面三联图。

- [ ] 复跑 Apple Music、Python.org、Windows 设置。
- [ ] 人工检查三联图并记录未通过项，不以测试绿色替代视觉审核。
- [ ] 运行保护集回归，确认一个界面的调整没有污染其他界面。
- [ ] 同步文档中的指标定义、已知限制和报告路径。
- [ ] 运行目标测试、相关测试集和 `py_compile`。

