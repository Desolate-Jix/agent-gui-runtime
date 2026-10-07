# 学习工作流图像核验：流程与性能测试 / Learning image-check flow and performance

日期 / Date: 2026-10-07。范围是当前维护源码 `codex/dev-workflow-editor`，未更新安装器、版本或发布。 / Source-only evaluation; no installer/version/publication changes.

结论：同一窗口、连接、定位和两步流程中，默认图像核验的三个正例全部成功，中位端到端耗时 9.884 秒；逐步 Sol 审核的三个正例全部成功，中位 29.778 秒。此次有限比较的耗时下降 66.8%，速度约 3.01 倍。两路线均成功，不能据此宣称准确率提升或所有应用稳定。 / All three positive runs per route completed. Median duration fell by 66.8% in this bounded comparison; no accuracy improvement or general reliability claim follows.

## 设计与公平性 / Design and comparison

- 全新自有 Qt 窗口 Image Flow Lab，全新运行时数据根；先真实教学 Open detail → Back home，通过项目公开学习入口生成两步工作流。Main 查看原图并做非人工 QA 审核，保存确切版本，库正常关闭/重开两次核对 program ID、内容 SHA 和定义。 / Fresh owned app/data, real teaching, public compilation and nonhuman QA; library reopened twice with exact pins.
- 图像开/关的两个已审核定义只差 `verification.image_check`。相同动作、分支、文字预期和 target_memory；两路线都复用教学得到的 UIA 定位。这里只评估结果核验路线，不是完整“从零 Agent 对学习复用”的收益比较。 / Both routes reuse the same learned UIA locator; only outcome image checks differ. This is not a from-scratch-agent versus learned-execution benchmark.
- 最终 c03 三对按 image/agent、agent/image、image/agent 交替。每对更换当前数据，动态文字在稳定状态 ROI 外；同对两路线使用相同数据。输入单一属主，全部经正式门控动作接口；没有直接坐标点击、旧学习资产、原生 Computer Use 或 GPT 咨询。 / Alternating paired order, new dynamic data per pair, one input owner and maintained gated actions.
- 图像规则 ROI `[33,109,266,40]`、阈值 0.95，比较有区别的当前状态内容；点击前定位与门禁仍执行。Agent 路线由同一个持续复用的 Sol worker 实际查看每张新截图并返回 verdict。 / Discriminating state ROI, unchanged input gates, one reused Sol worker with actual fresh-image review.
- 开始计时在准备新样本之后、公共 start 调用之前；结束在最终 status 返回、独立 oracle 核对之前。包括 workflow 启动、操作、截图/核验、轮询、审核交接和结算；不包括学习、QA、保存重开、样本准备与最终宿主关闭。 / Timed reuse includes start through final status, not learning/setup/reopening/host cleanup.

## 实测 / Measurements

| c03 pair | 图像 / Image, s | Agent review, s | 两路线完整成功 / Both completed |
|---|---:|---:|---|
| 01 | 9.883916 | 31.017619 | 是 / Yes |
| 02 | 9.794124 | 29.778231 | 是 / Yes |
| 03 | 9.899810 | 29.349763 | 是 / Yes |
| 中位 / Median | **9.883916** | **29.778231** | 3/3 each |

每个正例实际 Open/Back 各点击一次、最终回到 HOME，Runner 与 Trial 均 completed；pending、wait、active_command 为空。 / Each positive run had exactly one Open and one Back click, ended at HOME, and left no pending/wait/active command.

可观察结果审核交接：图像正例合计 0 次，Agent 正例合计 6 次（每次流程 2 次）。这不是完整模型 API 调用计数。两路线的全模型调用、token 和纯 inference 时间均未知；遥测中 partial coverage 下的 observed zero 不代表模型未工作。 / Observed outcome-review handoffs: 0 versus 6. Full API-call/token/inference totals remain unknown.

三次 Agent 路线调用方观察到的审核交接等待分别 20.921、19.438、19.109 秒，中位 19.438 秒；包含派发、worker 工具、判断、答案传递和等待空档，不能全部归入推理。图像路线宿主记录的两步 verification 阶段合计分别 26.938、28.566、31.547 ms，这只是已分类阶段，不能冒充全量截图/输入成本。图像流程仍约 9.9 秒，剩余的截图、定位、门禁、客户端与轮询阶段尚未全部细分。 / Handoff waits include orchestration and worker activity. Recorded local verification is partial; remaining end-to-end cost is not fully partitioned.

## 连续流程、负例与回放 / Continuous flow, negative test and replay

同一窗口/连接内完成六个正例和一个负例，保留累积状态。负例阻止 Open 的状态跳转：实际只有一次 Open 点击，仍是 HOME；图像检查没有放行，原 pending 与 history 在审核等待中保持，Sol 看图判 failure，工作流正确终止 failed，未自动再点击。这是拒绝测试通过，不是任务成功。 / The blocked transition remained HOME and was handed to Sol without replay; expected rejection passed, while the workflow itself failed.

Main 从归档参考 PNG 与实际当前 PNG 复算六个成功 proof，逐字段一致；用实际 HOME/DETAIL 对向原图核对两次错误状态均不匹配；另用真实 ROI 裁片生成两个双副本离线图，验证 ambiguity 拒绝。后两张是派生离线样本，不计现场准确率。 / Six proofs recomputed exactly; two actual opposite-state images rejected; two derived duplicate-crop images rejected as ambiguous.

正常收尾：源 MCP 客户端退出前停止宿主，`cleanup_verified=true`、`host_alive=false`、无 cleanup_error；自有 fixture 正常关闭 exit0。此轮没有死宿主恢复或跨应用覆盖，不把正常重开/轮询称为这些验收。 / Host/client/fixture closed normally. No dead-host recovery or cross-app coverage is claimed.

## 首次失败与修复 / First failures and repairs

1. 测试辅助脚本先遇到 import 路径、target_recipes 包装错误和非原子响应文件读取；原失败保留，修正辅助脚本与新请求，未通过重派输入掩盖未知动作。 / Helper import/payload/file-read errors remain preserved.
2. 最早 driver 在动作 pending 时提前查询 workflow，收到 command_pending 并退出；原动作随后结算。辅助 driver 改成读取原 execution ID 至终态后再查 workflow，不绕过生产门禁。 / Initial collector queried too early; follow-up polling retains original execution IDs.
3. c02 Agent 路线第二步遭点击前鼠标漂移拒绝：预期 `(490,418)`，实际 `(1640,769)`；action_executed=false，没有 Back 事件。原因只能确定为光标不在目标，不能认定人为操作。该次失败保留，不并入 c03 成功统计，也未放宽门禁。更换独立 c03 cohort 后六个正例连续成功。 / Cursor drift caused a correct pre-click refusal; original failure is not relabeled successful.
4. 本轮发现 benchmark provenance 未将有效 image_check 计作本地规则，且没有归档参考图复算。修复公共计量层：合法 image_check 计规则，缺参考/伪 proof/错误当前图保持 unknown；collector 仅从确切学习库归档参考 PNG。 matcher 增加只用于离线复算的 current_raw 参数，默认运行路径未变。 / Provenance now counts valid image rules only with independently recomputed archived pixels; malformed/missing proof stays unknown.

运行时不变量：未知输入不重放；窗口/当前截图/候选身份仍绑定；点击点漂移拒绝；结果证明必须对应原执行和实际当前字节。修复位于测试辅助及公共计量层，不是应用特判，不放宽发送/提交/支付或任何点击门禁。 / Shared invariants and dangerous-action gates remain intact.

## 证据与检查 / Evidence and verification

证据根 / Evidence root:
`.superpowers/sdd/2026-10-07-image-flow-performance`

- `programs.json`：版本、两次库重开和非人工 reviewer；`source-freeze.json`：实测前 17 文件 SHA。测试后仅 collector 的算法冻结清单补入 image_verification.py；16 个其余冻结文件未变。后续 SHA 在 `source-freeze-post-scoring.json`，不覆写原 freeze。本轮 driver 没调用这个 collector。 / Original freeze preserved; only future collector freeze metadata changed after live tests.
- `driver-c03.py`、`c03-*-result.json`：精确单调时钟、原 execution IDs、Runner/Trial、独立 oracle 及审核回答；`bridge-01/runtime/session-*/` 保存原命令、回执、观察 envelope、PNG 和 trace；`c03-judgment-*-request/answer.json` 记录 SHA、实际 worker 时间与 verdict。 / Original receipts, images and review records retained.
- `aggregate_main.py` / `aggregate-main.json`：Main 的完整结果断言、原图/歧义回放与性能计算；退出 0。 / Main offline recomputation passed.
- Main 执行：清洁桌面解释器 `python -B -X utf8 -m pytest tests/test_benchmark_provenance.py tests/test_benchmark_collection_images.py tests/test_benchmark_collection_provenance.py tests/test_benchmark_collection.py tests/test_selection_benchmark_provenance.py tests/test_image_verification.py tests/test_workflow_image_verification.py -q`，**218 passed in 12.00s**；日志 `backend-logs/main-final-regression.txt`。计量修复前 red 日志保留；worker 218 与 Main 218 不相加。 / Main regression passed; duplicate runs are not summed.
- `bridge-01/closed.json` / `fixture-01/closed.json`：正常清理证据。 / Normal cleanup evidence.
- 独立 Sol 证据审阅在 Main 主链及清理完成后进行，审核结论另存 `audit/`；这是独立证据审核，不等于另一 Agent 重跑桌面或人工验收。 / Independent evidence audit follows Main completion; it is not a second live run or human acceptance.

## 为什么完整流程仍接近十秒 / Why the full flow still takes almost ten seconds

按用户追问，Main 从第一对图像原执行回执读取 `local_step_timings`、`invocation_timings` 和 runtime verification 单调时钟，另存 `latency-main.json`。 / Main extracted original action and verification timings after the timing-scope question.

| 实际阶段 / Actual phase | Open detail, ms | Back home, ms |
|---|---:|---:|
| action owner 总计 / total | 2808.084 | 2800.388 |
| 其中 route_call（含以下点击/验证） / inclusive route | 772.129 | 774.400 |
| 其中动作后观察（含固定等待） / post-action observation | **2021.088** | **2012.441** |
| route 内 click_point / within route | 368.830 | 371.224 |
| route 内 post_click_verification / within route | 282.413 | 283.995 |
| 后续图像核验 owner.observe / later image observation | **11.9224** | **15.0154** |

`app/core/observation_policy.py:3` 的通用渲染宽限是 2000 ms，并包含 execute_recognition_plan；`app/execution/local_direct_step.py:396` 在无 condition 时实际等满宽限才拍后图。两原件明确 `render_grace_ms=2000`。因此本例两次动作至少约四秒花在这处固定等待，模板匹配本身不是秒级瓶颈。点击 route 另外有 settle 200 ms、hold 70 ms，以及后点击验证默认 250 ms；均嵌套在 route 内，不能重复相加。 / The generic action path waits a fixed two-second grace per action when no condition is supplied. Nested settle/hold/post-click waits must not be double-counted.

扣除两次完整 action invocation 与这两次图像观察后，端到端尚余 **4247.921 ms** 未被这些计时覆盖，不能全部归到匹配、IPC 或推理。调用方含 status/文件轮询、保存与结算；需追加准确分段计时才能分配余量。Agent 路线还有本轮两次 pending/history 保留核对的测试调用，所测交接包含这些开销，不代表纯模型速度。 / Remaining wall time is unclassified; review-route timing also includes test-side preservation checks.

优化优先级：让有当前状态判据的固定窗口使用有界状态观察，短间隔截图、成功即继续，取代固定等满两秒；超时/低置信度保留原请求交 Agent，绝不重新点击。然后补齐未分类阶段计时，决定调度与证据写入的优化。这一轮仅定位瓶颈，没有改等待策略或宣称已达到 MAA 的半秒体验。 / Prioritize bounded condition observation over unconditional grace, preserving gates and uncertain-state review; then instrument the remaining wall time. No wait-policy change or half-second claim in this round.


## 边界与后续 / Limits and next scope

这是一个自有合成应用、每路线三个流程的小样本。它支持默认图像结果核验可在该固定窗口减少审核等待，并在本次错误状态中保留 Agent 审核；不支持外部应用通用准确率、长期每次成功、全模型调用节约、安装版效果或完整学习收益主张。 / Limited synthetic-app evidence supports reduced review waiting and preserved uncertain-state review only.

后续发布前仍需把本轮源码纳入一个安装候选，做候选依赖/升级验证，并另设外部软件、窗口几何/主题变化与故障恢复的独立数据批次。优先保持准确的状态判据与失败证据，再细分剩余延迟；本任务不自动发版。 / Before release: integrate into one candidate, validate dependencies/upgrades, and separately evaluate external apps, geometry/theme variation and recovery.
