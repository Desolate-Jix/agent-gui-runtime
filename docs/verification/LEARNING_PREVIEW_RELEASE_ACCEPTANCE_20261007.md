# 学习测试版安装验收 / Learning preview installed acceptance

2026-10-07。冻结候选为 pair03 / execution-source-14 / learning-candidate-12。Main Astra 完成教学、单项、连续使用和清理后，Sol 在同一安装载荷上使用独立的新数据、连接与教学内容复验。两批均通过下列限定范围；源码发布与网络上传结果另由发布记录确认。 / The frozen candidate is pair03 / execution-source-14 / learning-candidate-12. Main Astra completed teaching, individual operations, continuous use and cleanup before Sol repeated acceptance with independent fresh data, connection and teaching on the same installed payloads. Both passed the scope below; source and network publication are confirmed separately by release receipts.

## 两个独立组件 / Two independent components

- 执行组件 **0.1.2-preview.1**：独立安装，提供维护运行时及 Agent 接口。既有委派识图、外部视觉 API 和可选本地模型路线保留，不强制安装模型权重。 / Execution **0.1.2-preview.1** installs independently and provides the maintained runtime and Agent interfaces. Delegated vision, external vision API and optional local-model routes remain; local weights are not required.
- 学习工作台 **0.1.0-preview.1**：可选的独立安装器，用于查看、审核、修改和保存学习库中的任务步骤、流程图及独立界面；支持简体中文和 English。运行时通过已连接的执行会话执行动作。 / Learning Workbench **0.1.0-preview.1** is optional and independently installed. It exposes task steps, workflow graphs and standalone interfaces for inspection, review, editing and saving, with Simplified Chinese and English. Actions run through the connected execution session.
- 学习结果默认提议本地图像核验；人工可以修改稳定区域、阈值或关闭该选项。经过审核的匹配步骤可直接验证结果，不匹配或不可验证时保留请求交给 Agent 审核，不自动重放点击。 / Learned results propose local image checks by default. Users can edit the stable region or threshold, or disable the option. Reviewed matching steps can verify results directly; unmatched or unverifiable results preserve the request for Agent review without replaying input.

## 冻结与依赖 / Freeze and dependencies

| 安装器 / Installer | 字节 / Bytes | SHA-256 |
| --- | ---: | --- |
| AgentGUIRuntimeExecutionPreview-Setup.exe | 2,812,928 | `fc8e343549d84d3deceb3d116451bc739729402fdefc2b5a1ba5a097e96ea5e7` |
| AgentLearningWorkbenchPreview-Setup.exe | 122,622,976 | `d67443fdb9c77d60db4063a66b501e1be1ae45baf9c2af2b2a8cbecad86728b9` |

两个安装器均未签名。安装后 Main 和 Sol 分别核对 execution 520 文件、learning 338 文件的大小和 SHA，均匹配同一安装载荷清单。生产源码及资源闭合共 570 项；隔离包验证实际入口，不以工具发现代替输入入口检查。 / Both installers are unsigned. Main and Sol each verified all 520 execution and 338 learning installed files against the same payload manifests by size and SHA. The production source/resource closure contains 570 entries; isolated checks exercise functional entrypoints rather than relying only on tool discovery.

冻结 EXE 离线验证包括 zh-CN/en-US 启动、真实 PNG 图像匹配、原图预览、阈值修改后保存重开和关闭图像核验后持久化。执行包无 Qt 与模型权重要求。 / Frozen EXE offline checks cover zh-CN/en-US startup, real PNG matching, source-image preview, threshold edit/save/reopen and persistence after disabling image checks. The execution bundle requires neither Qt nor model weights.

## 实装主链 / Installed mainline

| 验收 / Acceptance | Main Astra | Independent Sol |
| --- | --- | --- |
| 全新教学 HOME → DETAIL → HOME / Fresh teaching | 两原事件完成 / 2 completed original events | 两原事件完成 / 2 completed original events |
| 普通及连续完整任务 / Normal and continuous tasks | 5 正例完成 / 5 positive tasks completed | 5 正例完成 / 5 positive tasks completed |
| 1200 ms 延迟转换 / Delayed transition | 完整返回 HOME / Completed back to HOME | 完整返回 HOME / Completed back to HOME |
| 阻止跳转的负例 / Blocked transition | 仅 Open 一次，原请求审核为失败 / One Open, original request reviewed as failure | 同样单次 Open，未重放 / Same one Open, no replay |
| GUI 保存后观察 / Observation after GUI Save | 原 job completed，fresh postcapture | 原 job completed，fresh postcapture |
| 正常关闭重开 / Normal close and reopen | `[false, true]` 图像选项持久化 / Image options persisted | `[false, false]` 图像选项持久化 / Image options persisted |
| 已发布确切版本 / Existing pinned versions | 不被编辑静默改变 / Unchanged by edits | 不被编辑静默改变 / Unchanged by edits |
| 最终清理 / Final cleanup | GUI、fixture 正常退出，host cleanup verified | GUI、fixture 正常退出，host cleanup verified |

两批均在同一批自身连接内累计运行，使用本轮新数据与实时采集，未读取旧学习资产。教学通过公共 compile/synthesis/save/read 形成确切版本，再由实际安装工作台的“结果与读取”页面修改并保存；修改后的步骤保持待审核，不被自动宣称审核通过。 / Each batch accumulates state within its own connection using fresh data and captures, without old learned assets. Public compile/synthesis/save/read produces pinned versions, then the installed workbench edits and saves them through its Results and reads tab. Edited steps remain pending review rather than being automatically approved.

Main 保存图 SHA 为 `c6650df101549ac6a85620b3157cc50664a34fa764ae957af2b7a838db2b142e`；Sol 保存图 SHA 为 `66a192b99e5dd75487e879a1c263bee687eceb005861c987951dd31f2940a756`。Main 核对 Sol 的 23 个原始 job、23 个动作 trace、图像结果 SHA、保存/重开对象及清理记录，并实际打开教学、正负例、保存和重开截图。 / The Save capture hashes are shown above for Main and Sol. Main audited Sol's 23 original jobs, 23 action traces, result image hashes, saved/reopened objects and cleanup records, and opened the teaching, positive/negative, Save and reopened screenshots.

所有真实点击经过项目 execute_recognition_plan 接口，保留候选、坐标、策略与动作 trace；本批维护测试使用 local-operator selection，原策略允许且无绕过、无动作重试。未使用 Codex 原生 Computer Use 或 Sky。 / All real clicks use the project's execute_recognition_plan interface with candidate, coordinate, policy and action traces. These maintenance tests use local-operator selection with an allowed original policy, no bypass and no action retries. Codex native Computer Use and Sky were not used.

## 原始失败与回归 / Original failures and regression

第一批教学事件丢失及第二批保存后绑定丢失仍保留为原失败，修复后的第三批结果单独记录：

- [终态回执读取占用](LEARNING_TERMINAL_READ_LOCK_20261007.md)：实锁复现后修复公共读取边界；Main 快照与异步学习回归 **13 passed**。原占用句柄来源仍未知。 / The common receipt-read boundary was repaired after a real-lock reproduction; Main's snapshot/async-learning regression passed **13 checks**. The original lock holder remains unknown.
- [已绑定窗口标题刷新](LEARNING_BOUND_TITLE_REFRESH_20261007.md)：修复公共窗口刷新契约；Main 窗口发现、grounding、动作后转换与截图所有权回归 **55 passed**。瞬时空标题的来源仍未知。 / The common bound-window refresh contract was repaired; Main's discovery, grounding, post-action transition and capture-ownership regression passed **55 checks**. The source of the transient empty title remains unknown.
- 图像/等待相关源码检查此前 **269 passed**；冻结包的实际功能入口另行通过。以上是分批验证，不是一次最终全套测试的计数。 / Earlier image/wait source checks passed **269 tests**; actual frozen-package functional entrypoints were verified separately. These are separate validation batches, not a single final full-suite count.

正常关闭使目标窗口消失时，关闭动作原 job 的 failed/action_executed=true 回执保留，正常退出由进程 exit0 独立证明，不改写为 completed。Sol 编排中两个提前只读请求被 agent_command_in_progress 拒绝、未执行输入；原拒绝保留，未重派动作。 / Original close jobs remain failed/action_executed=true when the target disappears; normal exit is separately established by exit0, without rewriting the receipt as completed. Two early read-only requests in Sol's orchestration were rejected by agent_command_in_progress without input; the rejections remain and no action was replayed.

截图短期缓存清除了 Sol 教学 before 的临时路径，但同 SHA 原字节仍保存在本轮不可变 evidence-objects 与原动作记录内。Main 核对字节和实际图像；未修改原事件路径，也未替换成其他批次截图。 / Short-term retention removed transient paths for Sol's teaching-before captures, while the original SHA-identical bytes remain in this batch's immutable evidence objects and action records. Main verified bytes and pixels; original event paths were not rewritten and no other batch's screenshots were substituted.

## 性能与范围 / Performance and scope

保留已有等待设置，不继续扩展性能调整。第三批三次无延迟图像完整任务中位数约 Main **5.94 s**、Sol **5.97 s**；这是本轮小型受控两步流程。Agent 对照的总时长含人工编排/等待，不能当作模型推理耗时。此前受控优化对比见 [等待优化验证](LEARNING_IMAGE_WAIT_EARLY_EXIT_20261007.md)，不宣称所有应用速度或准确率提升。 / Existing waits remain and further tuning is deferred. Third-pair no-delay image-task medians are approximately **5.94 s** for Main and **5.97 s** for Sol on this small controlled two-step flow. Agent-control wall time includes orchestration/waiting and is not model inference latency. The earlier controlled comparison is documented separately; no general application speed or accuracy gain is claimed.

本轮没有验证新的外部 API 服务商准确率、广泛应用可靠性、token/成本收益，也没有复测 Sol 的区域拖动编辑。旧便携 candidate02 首次自行退出原因仍未知，不能宣称已修复；本次范围是新的独立安装测试版。正式 instant-v0.1.1 保持不变。原始私有数据、截图、用户库与测试脚手架不作为公开资产上传。 / This batch does not establish a new API provider's accuracy, broad application reliability, token/cost gains, or Sol's region-drag editing. The old portable candidate02 first-exit cause remains unknown and is not claimed fixed. This release scope is the new independently installed preview; stable instant-v0.1.1 remains unchanged. Private raw data, screenshots, user libraries and test harnesses are excluded from public assets.
