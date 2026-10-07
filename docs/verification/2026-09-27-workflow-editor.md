# 可编辑工作流开发验证 / Editable workflow development verification

## 交付边界 / Delivery scope

之前的 API 执行链与 Codex 连续视觉会话改动已同步远端 `main`：`c7a3099607d039fb3e377be1de7ff26151d1101c`，已用 `git ls-remote` 核对。随后开发位于 `codex/dev-workflow-editor`，本页所述学习功能是未发布源码。MCP `0.1.0-test.8`、项目 `0.3.0` 未改，无新安装包。外部 API 没有付费供应商在线识别实测，不声称准确率。

The preceding API/Codex changes were synced to main; learning development is unreleased source on `codex/dev-workflow-editor`. Versions and published packages are unchanged. No paid-provider accuracy claim is made.

## 本方验证 / Main-agent checks

- 最终源码全套：桌面解释器下 `QT_QPA_PLATFORM=offscreen`、`python -X utf8 -m pytest -q`，**2112 passed，67.86s**。此前全套2103项、相关163项检查均保留；测试覆盖有重叠，不相加。
- 离屏原生 UI：真实 `MemoryEditorClient`、真实项目库、全新合成数据，编辑/保存/重开、条件/输出、关系切换、审核重置与纯审核保存；最终 UI 5 passed。1280×800 截图已人工检查，测试渲染显式加载本机微软雅黑。
- 实机新数据：同一个 MCP 连接、同一个新建 Qt 表单。先学习填写 City=Auckland；编辑动作目标为 Note、输入为 Wellington，执行后 City 仍为 Auckland，Note=Wellington；旧程序版本仍保留 City。
- 连续三步：Note=Dunedin → 当次原图读取 Note 并产出 `step-read.note_value` → 下游引用该输出填写 City=Dunedin。三个步骤均核对终态原回执，读取图像保留 SHA256；不是根据提交成功判定动作完成。
- 负向与恢复：从第三步开始缺上游输出时阻断且无执行票据；前置条件缺观察时阻断，显式补充观察后继续。新服务进程重开库后仍读到原运行、旧版本与阻塞原因。实际执行仍逐次使用新图定位与公共动作检查。
- 收尾：测试表单退出、MCP 驱动关闭；`cleanup_verified=true`、`host_alive=false`、pending_ids 为空。没有关闭用户应用。

The full suite passed before the final narrow changes; affected checks passed again afterward. Fresh native evidence covers learned-to-edited behavior, one continuous three-step dataflow, missing-dependency/condition refusal, reopen and cleanup. Offscreen widget tests are separate from physical input. These runs do not establish broad third-party-app or popup coverage for the new learning editor.

## 首次失败保留 / Retained initial failures

- 移植测试最初用无 PySide6 的轻量解释器，24 passed / 11 failed / 4 errors；改用已有桌面解释器后通过，未安装依赖。
- 新 MCP 学习反馈没有返回基线 ImageContent；修复当前反馈通道后相关测试通过。
- 异步命令的提交回执曾会被学习器当作最终动作；新增两项回归先失败，修复后通过。
- 审核重置后旧 UI 用例仍期望同次语义编辑沿用 reviewed，末次第一轮为158 passed / 1 failed；修正用例以验证先 pending、再独立审核保存，最终163 passed。
- 实机测试脚本一次过早读图（命令仍 running，图尚不存在），随后轮询终态后读到原图；没有重派输入。重开脚本一次把 `reason` 写成不存在的 `blocked_reason`，修正测试字段后通过。均未改记首次成功。
- 独立代码复核复现：第一步完成后重复同一 prepare 请求，服务曾返回第二步的新票据。准备本身不派发输入，但直接编辑器客户端重试可能混淆命令身份。修复已加入跨步骤、两步全部完成后、参数冲突、旧待定记录兼容的回归；本方最终全套2112项通过，独立复核另记。

Initial environmental, integration and harness failures remain recorded separately from successful reruns. No physical command was replayed because an observation was pending.

## 异步记录故障闭环 / Async recording invariant

1. Failure / 失败：提交阶段可被误记成动作完成。
2. Invariant / 不变量：学习事件与试运行只能消费关联请求的终态执行证据；提交成功不等于任务成功。
3. Fix / 位置：公共 `receipt_adapter.resolve_execution_receipt`、记录服务和宿主收尾刷新；保留提交回执摘要，另存终态回执摘要。
4. Reuse / 通用性：适用于所有异步 Agent 输入，不依赖本次表单标签。
5. Regression / 回归：pending 不生成事件、终态恢复、命令身份不匹配拒绝、终态内容变更拒绝；实机异步输入也验证记录。
6. Safety / 安全：不放宽定位或输入许可，不引入重放；unknown/pending 不能成为成功标记。

## 准备请求身份 / Preparation request identity

独立复核暴露的可复用不变量是：同一请求身份必须永久对应同一个准备结果，不能随着当前步骤推进而指向另一条命令。修复位于公共 `TrialService.prepare`，保存请求参数摘要与原始结果；成功、阻塞和复用待定票据都必须记录。回归覆盖两步完整运行、步骤间重复准备、完成后重复准备、参数冲突和阻塞恢复；不是对某个表单打补丁。准备仍无键鼠输入，修复不放宽原动作检查。 / A preparation request must retain one identity and result as the trial advances. The shared service persists its payload digest and original result; regressions cover a complete two-step run, retries across advancement/completion, payload conflicts and blocked recovery. Preparation remains input-free.

## 限制与证据 / Limits and evidence

工作台只准备命令，Agent 使用现有执行入口继续；图像结果由 Agent 判断并明确记录来源。当前拒绝循环分支；缺实时目标的键盘动作不会生成命令。取消待执行请求保留待核对票据，不代表撤回或回滚已派发输入。尚未进行新版安装包或新增弹窗场景实机验收。

The editor prepares commands, not a second executor. Visual verdicts remain Agent judgments. Cycles and keyboard steps without live targets are blocked. Cancelling a pending trial preserves its unresolved ticket; it does not undo input. No new installer or new popup live acceptance was performed.

本机证据 / Local evidence: `D:/AgentReviewAcceptance/20260927-workflow-editor-01`。关键文件：`full-source.xml`、`final-targeted.xml`、`final-targeted-rerun.xml`、`final-full-source.xml`、`frozen-source-final.json`、`live/verified-summary.json`、`live/cleanup.json`、`live/results`。最终记录冻结686个源码/测试/依赖文件摘要；本轮仅运行源码收集清单检查，没有生成交付ZIP。

独立复核通过：最终冻结686项全匹配，原两步合成复现通过，独立窄测试30 passed / 5.01s；核对了本轮三步实机回执、截图摘要与清理。报告为本机 `independent-final.md`。该结论限于冻结源码、独立服务/UI测试与已有实机证据核验，不等于独立实机操作。 / Independent recheck passed: 686 matching hashes, the repaired two-step reproducer, and 30 focused tests. The same run's live receipts, sampled image hashes and cleanup were inspected; no second physical GUI run was performed.
