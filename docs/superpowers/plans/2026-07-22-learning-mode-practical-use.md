# Learning Mode Two-Week Practical-Use Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task by task.

**Goal:** 在两周内把学习模式推进到可用于真实软件测试、可人工纠错、可安全复用纠错经验的状态，而不是追求无人值守的通用识别。

**Architecture:** 保留 deterministic root partition、精准定位、Gate 和只读 PathGraph。新增证据驱动的 Surface Adapter 层为通用识别提供布局先验、排除区和验证规则；新增人工框编辑器与 CorrectionMemory，将人工修正保存为带适用范围和反例的候选规则。任何 Adapter、人工规则或模型复核都不能直接授权点击，也不能绕过安全 Gate。

**Tech Stack:** Python 3.11、FastAPI、现有原生 Web Panel、pytest、现有 OCR/UIA/VISTA/模型服务。

## Two-Week Delivery Rhythm

### Week 1: Make The Real Panel Usable

- 固定 Surface Adapter、人工框编辑、版本化修正和 CorrectionMemory 候选链路。
- 打通绑定、截图、学习草稿、人工修框、保存、重载、界面详情和只读 PathGraph。
- 先保证失败可见、可恢复、不会串用旧截图，也不会产生真实点击授权。

### Week 2: Validate Practical Use

- 在九个历史界面和六个陌生 holdout 上分批跑原图、Stage1 栏图、最终融合图三图验收。
- 按 root partition、atomic recall、ownership、精准定位、模型复核、界面详情分别记录失败，不合并宣传总准确率。
- 修复跨界面通用问题并回归旧界面；最后用真实面板完成一轮“自动草稿 -> 人工纠错 -> 保存重载 -> 只读产物”的实际试用。

两周结束的交付标准是“可以在真实软件上使用，并能快速人工纠错”，不是“一天完成”，也不是“陌生界面无人值守”。

## Global Constraints

- 不修改 Execute 模式模型和最终提交安全策略。
- Surface Adapter 只能输出先验、排除区、校验规则和证据，不能输出最终点击坐标。
- 应用名只能作为弱证据；没有可见结构证据时必须退回 GenericAdapter。
- 人工编辑只修改学习草稿和只读 PathGraph，不产生执行授权。
- CorrectionMemory 默认产生 candidate，必须经过回归和人工批准才能 active。
- 每次行为修改必须先写失败测试，再做最小实现，并运行窄验证。

## Task 1: Freeze And Audit Existing Surface Rules

**Files:**
- Create: `docs/learning/SURFACE_RULE_INVENTORY.md`
- Modify: `CURRENT_STATE.md`

1. 用 codegraph 记录 Browser、Chat、MediaPlayer 和 Generic 相关规则的真实调用路径。
2. 将每条规则标记为 common hard rule、surface prior、surface validator、legacy duplicate 或 app-name special case。
3. 记录九界面基线资产及后续陌生界面 holdout，禁止用单个应用截图作为通用结论。
4. 不改变生产行为，运行现有 root partition 和 recognition pipeline 窄测试。

## Task 2: Add Surface Adapter Contract

**Files:**
- Create: `app/learn/recognition/surface_adapters.py`
- Create: `tests/test_learning_surface_adapters.py`
- Modify: `app/learn/recognition/two_stage.py`

1. 先写失败测试，覆盖 Browser、Chat、MediaPlayer、Generic 选择及证据冲突回退。
2. 实现 `learning_surface_adapter_decision_v1`，字段包含 adapter_id、status、confidence、evidence、layout_priors、excluded_zones、validation_rules 和安全声明。
3. 应用名不能单独激活专用 Adapter；结构证据冲突时回退 GenericAdapter。
4. 将 decision 加入真实 Learning Mode 输出，第一阶段只作为诊断和下游显式输入，不改变 root bbox。
5. 运行 Adapter 测试和 recognition pipeline 回归。

## Task 3: Consolidate Browser Adapter

**Files:**
- Modify: `app/learn/recognition/surface_adapters.py`
- Modify: `app/learn/recognition/two_stage.py`
- Modify: `app/api/vision.py`
- Modify: relevant tests and benchmark fixtures

1. 先写浏览器上栏、网页主体、无浏览器栏页面的失败测试。
2. 把散落的 browser chrome 识别、排除和 viewport 验证迁移到 BrowserAdapter。
3. 删除固定高度作为最终边界的行为；固定比例只能作为弱候选。
4. 用九界面和陌生浏览器页面回归，确认旧界面没有污染。

## Task 4: Add Manual Bounding-Box Editor

**Files:**
- Modify: `app/web_panel/index.html`
- Modify: `app/web_panel/panel.js`
- Modify: `app/api/panel.py`
- Modify: `app/learn/draft_review.py`
- Add focused frontend/API tests

1. 先写 API 与状态转换失败测试。
2. 支持选中、添加、移动、缩放、删除、撤销、重做、角色和父级修改。
3. 保存版本化 `human_review_patch`，包含 screenshot checksum、before/after bbox、原因和来源。
4. 保存后自动重建编号图、界面详情和只读 PathGraph。
5. 验证刷新和历史草稿切换不会重复渲染或串用旧状态。

## Task 5: Add CorrectionMemory And Rule Lifecycle

**Files:**
- Create: `app/learn/correction_memory.py`
- Create: `app/learn/surface_rule_registry.py`
- Add tests and local schema docs

1. 保存人工修改的 before/after、edit_type、surface、evidence、reason、checksum、适用范围和反例。
2. 实现 candidate -> regression_verified -> human_approved -> active -> rolled_back 生命周期。
3. 只有 active 规则可参与生产学习流程；candidate 只用于离线比较。
4. 模型只能从修改差异生成候选规则和反例建议，不能自动激活。
5. 面板只读展示候选生命周期、surface、修改类型、证据状态和生产资格；保存人工修改后自动刷新。十五界面回归完成前不提供批准或启用按钮。

## Task 6: Migrate Chat And Media Rules

**Files:**
- Modify: `app/learn/recognition/surface_adapters.py`
- Modify: `app/learn/recognition/two_stage.py`
- Modify: tests and benchmark manifests

1. 将 conversation workspace 和 media catalog 的布局先验迁入 Adapter。
2. 移除应用名分支，保留证据驱动的结构规则。
3. 验证聊天子栏、图片消息、卡片组和播放器内容不会互相污染。

当前状态：已完成。Chat/Media 内容策略由已验证的 Surface Adapter policy 驱动；应用名不能单独启用专用 Adapter。真实 Stage2 输出边界和跨识别回归已覆盖，相关测试 `257 passed`；当前全仓回归为 `1875 passed`。

## Task 7: Real Panel Acceptance

**Files:**
- Modify: benchmark manifests, README and progress docs

1. 在九个历史界面和至少六个陌生界面运行完整学习流程。
2. 每批运行前执行 VISTA 资源预检；critical 时必须在模型调用前结构化暂停。续跑必须读取历史报告的已完成 case ID，不能只依赖会随资源推荐变化的 batch size/index；未运行样本不进通过/失败分母。
3. Protected 与 holdout manifest 必须进入同一验收分母；重复 case ID 直接拒绝，不能覆盖或缩小样本数。
4. 所有批次必须汇总到同一 aggregate；下一轮聚合可以继承上一版 aggregate 的批次来源并追加本轮报告。`collection_status`、质量结果和安全结果分别报告，重复完成样本和 manifest 漂移直接拒绝。
5. 每个界面保存原图、Stage1 栏图、最终融合图和 trace。
6. 分层报告 root partition、atomic control recall、ownership、precise calibration、review repair、page details 和 PathGraph draft。
7. 验证人工修改在面板内可完成，刷新后可恢复，且没有真实点击授权。
8. 明确列出仍需人工修正的界面；不宣传总准确率或无人值守稳定性。
9. 已完成 Apple Music、QQ 与 Windows Settings 真实面板人工修框、保存、重载回放；CorrectionMemory 保持 `candidate` 且 `production_eligible=false`，当前为三个 candidate、零 active。缺失、陈旧或无法完整解码的截图证据必须拒绝，不得替换原图或沿用旧坐标。
10. 已修复面板历史来源列表的 sidecar 全仓递归扫描：快速列表只读取显式或邻接证据，完整单产物审核仍保留关联发现。当前真实 HTTP 检查约为 `0.354s`，正常端口 `8765` 已重启并实测约 `0.389s`。
11. 已修复验收 runner 的模型生命周期断点：资源预检通过后必须启动并等待 VISTA locate stage 为 `running`，否则显式失败，禁止在模型未加载时继续。15 个样本已完成采集，最终 aggregate 为 `logs/benchmarks/learning_practical_acceptance_final_20260722/learning_practical_acceptance_aggregate_report.json`。
12. 已用真实浏览器检查当前 port-8765 面板：人工修改草稿、CorrectionMemory、页面详情和只读 PathGraph 各渲染一次，页面无横向溢出；CorrectionMemory 为三个 candidate、零 active，且没有批准或启用控件。该检查不替代十五界面模型验收。
13. 当前验收 checkpoint：`collection_status=collection_complete`，15/15 三图齐全；`quality_status=needs_review`，protected class expectation 为 6/9，chain completion 为 12/15。Apple Music 20260710、File Explorer、WhatsApp 仍失败；holdout class expectation 为 `not_covered`，且人工三图审核发现 GitHub Desktop 存在 file/diff row 被解释成 conversation/message 的语义污染。不得把本轮写成识别准确率或陌生界面通过。
14. surface-family 语义隔离的首个 common contract 已落地：只有已验证 Chat policy 或结构容器证据可以选择聊天 Stage1.5 角色，普通 OCR/页面文本不能把文件/代码窗格解释为聊天；非聊天多窗格使用中性 `list_pane/detail_pane`。File Explorer 的下游 row 误删也已修复，保存 trace 从 21 个已生成行保留 13 个改为保留 21 个，但仍未达到 25 个期望，因此上游 recall 继续失败。识别 pipeline 为 `237 passed`。下一步在 GPU 门禁允许后 fresh 复跑 GitHub Desktop、QQ、WhatsApp 三图，再补 holdout expectations；随后修剩余 `table_row` recall 与 conversation top-bar/row recall，并复跑完整 9+6。
15. CPU 离线修复已关闭剩余两类 common recall 缺口：File Explorer 以严格列/行节奏为前提恢复缩进或缺一列的行，固定截图输出 35 个 `table_row`；WhatsApp Stage1.5 子区按显式 `parent_region_id` 回挂层级并保留 10 个 conversation rows，近全宽顶部横线与独立全高侧栏共同恢复 40px top bar。九界面固定 trace 回归为 9/9 root expectation，另外八个 root geometry 不变。该结果仍需显卡空闲后的 GitHub Desktop/QQ/WhatsApp fresh model 三图复跑，不能写成准确率或完整验收。
16. Apple Music 的 `insufficient_hierarchy_nodes` 已定位为通用证据顺序问题：年份栏目标题被数字禁令误杀，且视觉候选在 OCR 数量门槛之后才运行。现已允许包含充分语义文字的年份标题，继续拒绝时间/计数/日期/纯年份；一个 OCR 片段只有在至少两个视觉卡片候选支持时才可合成。固定 trace 恢复 5 个 partial cards，学习草稿 region 从 44 增至 50；九界面 CPU 回放无 invalid。真实模型仍因用户占用 GPU 而暂停，历史验收 aggregate 不被本轮离线结果改写。
17. 已冻结三例 fresh model 定向复跑清单 `tests/fixtures/learning_practical_targeted_rerun_manifest_v1.json`：WhatsApp 验证结构修复，QQ 验证聊天层级，GitHub Desktop 验证非聊天语义隔离。三例 trace/截图均有 checksum，期望来自原图人工冻结，且 `used_for_rule_tuning=false`、`holdout_used_for_tuning=false`。该清单不含结果；显卡仍被用户占用，因此不得启动 VISTA/Qwen，也不得宣称 fresh 通过。
18. 已修复定向复跑报告的验收漏洞：runner 现在真实检查 `expected_bar_types`、`expected_absent_bar_types` 和 `expected_sub_bar_roles`，并输出实际栏/子栏角色。缺栏、出现禁止栏或缺少子栏会进入 `needs_review`，不能再被其他指标掩盖。该变更仅收紧 conformance gate，不是准确率指标。
19. 三例定向 fresh model 回归已完成：`logs/benchmarks/learning_practical_targeted_final_regression_20260722/learning_interface_chain_smoke_report.json`。WhatsApp、QQ、GitHub Desktop 均完成只读链、三图齐全并通过冻结的 class/structure audit。Stage1.5 现在在 parser 角色泛化时读取已验证 conversation profile；密集代码/文档界面会阻止弱语义 card row/parent，并把 `news_card/recommendation_item` 降级为只读 `document_section`，保留显式 `content_card/media_card`。聚焦测试 299 passed，全仓 1881 passed，VISTA 已关闭。该结果不是识别准确率、通用陌生界面通过或 Execute 授权。
20. 完整 protected 9 + holdout 6 真实模型复跑已聚合到 `logs/benchmarks/learning_practical_acceptance_final_aggregate_20260722/learning_practical_acceptance_aggregate_report.json`。15/15 三图齐全并完成只读链，带冻结类别期望的 9/9 通过。首版剩余的两个 Steam 失败经原图、Stage1、最终融合图核对后确认是 manifest 错误：两张原图底部均有真实群组聊天停靠区，现已要求 `bottom_bar` 并 fresh 复跑通过。六个 holdout 类别期望仍是 `not_covered`，因此不能宣传通用准确率或无人值守可靠性。VISTA 测试后已关闭，未发生真实点击、填写、提交、Execute 绑定或 Runtime PathGraph 晋升。

## Acceptance Boundary

- 可以绑定、截图、生成融合草稿、人工修框、保存并重建只读产物。
- Browser/Chat/MediaPlayer/Generic 选择有证据且可审计，未知界面可安全回退 Generic。
- 人工负反馈可形成候选规则，但未经批准不会影响生产。
- Execute、最终提交 Gate 和真实点击权限没有放宽。
- 两周目标是“可实际使用并可人工纠错”，不是“陌生界面全自动识别完成”。
