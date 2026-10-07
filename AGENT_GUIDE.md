## 2026-10-03 明确恢复选择 / Explicit recovery choice

## 行选择失败的读值事实 / Row-selection failure facts

row_selection_state_changed 表示两次原生UIA扫描字典不一致，不等同于selected改变，也不同于 local_control_target_row_selection_state_changed。若 control_target_check.failure_evidence 存在，可核对其 changed_fields 与两侧有界摘要；缺失时保留未知原因，不能重试输入或归因用户。当前证据不会修改旧回执或放宽拒绝。 / A double-scan mismatch is distinct from a selection-state guard. Inspect optional bounded evidence; absent differences remain unknown and never justify replay or attribution.


`learning_workflow.takeover_preview` 新增可选 `resolution`：省略或 `adopt_success` 保持原“当前效果成功后接管”；`resume_unexecuted` 仅用于原任务已取消且确认未派发输入、当前完整新观察确认效果未完成的步骤。不能把 failed、未知或部分输入当作取消零输入。 / Optional resolution preserves default successful-effect adoption; explicit continuation requires a cancelled, proven zero-input original and a complete fresh observation showing the effect unmet. Failed, unknown or partial input is not eligible.

```json
{"action":"takeover_preview","admission_request_id":"<ready-admission>","source_run_id":"<original-run>","resolution":"resume_unexecuted"}
```

随后提交确切返回的 `preview_request_id` 与 `preview_sha256`；`takeover_commit` 不接受另一个 resolution。提交只导入并暂停在 `takeover_ready`，读取当前 wait_id 后明确 continue；原 execution ID 保留为取消，新步骤使用新 ID 与新截图，不能重发旧票据。同预览 ID 不可更改选择，ready 重复提交只读。 / Commit the exact preview identity/hash with no choice override. Commit imports a paused run; use its current wait ID for explicit continuation. The old execution stays cancelled and fresh execution/capture identities are required. Preview choices are immutable and ready retries are read-only.

普通工作台尚未提供这项恢复选择，不声称 UI 已接线。原窗口/PID 已退出，旧连接已由原正常结束入口核验清理并 exit 0；尚未重新连接，完整原生恢复仍待。 / This source/API slice does not yet wire an ordinary workbench choice. The original window/PID is absent and the old connection exits zero through verified normal cleanup; reconnect and complete native recovery are pending.

[合同与实证边界 / Contract and evidence limits](docs/verification/EXPLICIT_UNEXECUTED_TAKEOVER.md)

## 2026-10-02 当前候选与下一出口 / Current candidate and next outcome

历史保持：live-03仅准备，零尝试/输入且清理通过；v4/live-04 的 A 实际任务成功，但 Main 给 finish 多传 attempt_id 导致采集器退出，原0行/1unfinished，观察到清理318.975秒；v4/live-05 的 C 到step2，原异步回执被collector错误拒绝，原0行/1unfinished，观察到清理93.068秒。两现场原宿主/runner/窗口均退出，清理核验通过；未补造 finish、未重评分或拼接到v5。v5首C前 Main 只读核验误解 outputs 键的 KeyError 单列调用方错误，之后按真实键更正，耗时未扣除。 / Preparation, unfinished attempts, verified cleanup and caller errors remain separate; no original scores are rewritten or combined across candidates.

现有 agent_current/workflow_metrics、调用方 record_model_call 和公开任务摘要只能提供局部或调用方上报计量，完整规划/定位/核验/补救总量仍未闭合；A普通路线也没有工作流计量范围。总调用/token继续未知，不把工具数、等待或局部0次当总调用。不为计量购置API或换模型，继续测正确率和耗时。 / Existing hooks provide partial coverage only; complete actual call coverage remains open without replacing missing totals with tool counts or buying providers.

执行顺序调整为：立即结算已结束的原任务，不在计时窗口插入无关调查/文档；只修真实来源覆盖阻断并新冻结 → 首对原结果/replay/未决请求检查 → 余下五对与三项分别诊断 → 同窗口一次弹窗/一次宿主中断及收尾 → 按实测瓶颈优化，完成语义编辑后待审/复用、第三方应用迁移及完整计量缺口 → 再扩大正式三类对照和同候选独立验收。泛化重构、决策API接入、大型UI重做和重复打包后置；正式v0.1.1独立，当前不改版本、不推送或发布。 / Settle completed tasks promptly without inserting unrelated investigation into the attempt clock, repair the proven provenance blocker and freeze anew. Then validate the first pair, finish the pilot, bound recovery and complete measured optimization, edited reuse, transfer and telemetry before formal scale.

[异步回执故障与验证](docs/verification/LEARNING_BENCHMARK_ASYNC_ENVELOPE.md)。

## 2026-10-02 当前重心与实测进度 / Current focus and live progress

学习主线保持“真实教学生成→可审核修改→保存重开→换数据复用→实测收益”。P0 已完成。本批 P1 普通闭环已核验：live-p1-02 六步教学、Agent 整理和可见编辑重开；live-p1-03 在同一原窗口/会话不复位完成 R-381、R-590 两轮六步复用，均填写当次读取详情。原图固定引用和旧程序保留。审核者是 Agent，human_review=false。 / This batch verifies teaching, visible editing/reopening and two continuous fresh-data reuses, with pinned graph/program versions and truthful Agent attribution.

R-000 缺失目标在 step-3 停止，原 action_executed=false、dispatch_attempts=[]，未执行下游读取/填写；普通输入框改为 R-362 后完整六步完成。原宿主和窗口正常退出，cleanup_verified=true、pending_ids=[]。普通界面能看出失败步骤并重新输入，但具体 request_absent 原因目前仅在原回执，作为易用性限制保留。本批不是任意应用、完整 R1/R2 或独立验收。历史超时、遮挡拒绝、驱动错误、取消和多余 continue 拒绝均不改写为首次成功。 / Missing-target stopping, ordinary correction and cleanup pass within the declared scope; detailed failure wording and wider acceptance remain open.

当前 P2：source-v5/cohort-05 的首 A/C 原任务和 finish 都成功，A328.390326秒、C564.687463秒；C本次 step-4.current_detail 绑定 step-5 填写且最终显示 Matches current detail。但C来源覆盖因重复引用为partial，首对继续采集检查点尚未通过；保留原两行结果，停止本候选采余下五对。此计时包含执行者、工具往返、汇报、Main 核验和结算；C最终completed返回后至finish为344.305728秒，主会话收尾明显拖慢，不能归因于模型推理。 / Both first tasks originally succeed, but duplicate provenance references block the collection checkpoint. Keep original rows and stop this candidate before repair; caller settlement accounts for substantial elapsed time and does not identify model inference latency.

共同采集修复已核验：异步returned/running只读准入与真正终态分开；同session原路径规范化去重，原Windows规则引用沿只读索引读取；memory plan绑定原动作goal，附加视觉提示不替代动作语义。Main最终266 passed/10.67s，真实v5原件只读复查coverage=complete、errors=[]，58个唯一快照及原图SHA一致，旧journal/原分未改。部分步骤仍为Agent核验，全规则资格false、总调用/token未知；runtime/client/输入门控和终态评分不变。 / Bound asynchronous retrieval, canonical snapshots and original action semantics are verified by related regressions and actual retained files. Mixed Agent judgment, unknown usage and unchanged original scores remain explicit.

source-v6/cohort-06（849文件、种子2026100206、每路线计划6例/600秒）现已完成4对/8次任务并正常清理；原首对检查点通过，C四例来源coverage=complete、errors=[]，全规则资格仍false。A首次成功4/4，C3/4；C04调用方读取格式化错误经原请求reread补救，最终任务8/8完成，原首次失败与全部耗时保留。稳定两对中位耗时A298.986秒/C246.596秒，描述性节省17.5226%，未达30%目标；模型总调用/token未知，准确率提升未证实。A04后只读审计误展开评分records，执行worker隔离失效；停止余下2对layout，不记失败、不补分、不续采旧清单。原8行、missing4、零unfinished和cleanup证明保留；正式配额不抵扣、真人/独立验收未完成，正式v0.1.1独立不变。 / The closed candidate retains four pairs, eight completed tasks and its original first-success/recovery scores; two layout pairs remain unstarted after post-task oracle exposure. Stable descriptive timing saves 17.5226%, below the target. Call coverage and correctness improvement remain unproven; no formal credit or release change follows.

总模型调用/token 仍未知，省模型、正确率和速度收益均未证明。工具/交接数与等待不冒充模型调用或推理耗时；满分基线只报持平。正式 v0.1.1 独立保持；当前学习源码未发布、未改版本或打包。P1及P2 v2/v3/v4的候选证明分别保存，原失败不移入新候选，也不补改旧记录。 / Benefits and full usage remain unproven; the stable release is separate, and each candidate proof and original failure remains tied to its own frozen revision.

[当前执行计划](docs/superpowers/plans/2026-10-01-learning-mainline-refocus.md)；Main 证据：`D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261002-learning-mainline-01/live-p1-03/p1-main-audit.json`。以下日期段均为历史，不覆盖当前顺序。 / The plan and raw evidence control current status; dated sections below are historical.

## 2026-10-01 中断事实修复 / Durable interruption facts

读取死宿主原非终态 Agent 回执时，worker_status 的 terminal_available 仅说明原 worker 文件可读，不是工作流已结算。persisted_worker_evidence 是路径/hash 绑定的诊断，不能当新执行回执；没有此前 True 的未决输入保持 null，禁止重派。/ A terminal_available worker diagnostic does not settle a workflow or authorize replay; preserve unknown input and original receipts.

合同与证据界限见 [WORKFLOW_INTERRUPTION_CONTRACT.md](docs/WORKFLOW_INTERRUPTION_CONTRACT.md)。/ See the interruption contract and evidence limits.

## 2026-10-01 原会话退出后的只读入口 / Reading an exited session

`WorkflowRunClient` 现分离只读 attachment 核验与派发前 live gate。宿主实际退出后，新客户端及新开的普通 main 可读取本轮原结果、输出和回执，执行/继续/取消按钮禁用，账本与命令字节未变。活宿主仍完整验证 PID、创建时间及 runner；`control`、原回执绑定和动作门控保持原实现。 / Validated read-only attachment now works after the original host exits; dispatch still requires the original live identity and gate. Ordinary reopening preserves the ledger and disables action controls.

这只证明退出后的只读重连，不是原宿主进程重启续跑。活动 workflow 切换独立顶层弹窗仍不支持：admit 只放行原 ticket 的确切 EID/command，不能放宽竞争 select 代替窗口迁移合同。死宿主的原 worker 仍不能从磁盘自动恢复，未知结果不能当作未输入而重放。 / Read-only reconnection does not restore a dead worker or permit competing window selection; active dialogs and process restart remain open.
普通运行页仍用“连接会话”附着原目录，再“刷新状态”或回读原请求 ID。不要调用 start 启动新宿主，不要重发旧输入；`result_unknown` 继续未知，任何新 control 都必须经过存活身份检查。旧 pointer/library/source/profile/command/receipt 不一致时明确拒绝。 / Attach the original directory and read original IDs. Preserve unknown results and reject mismatched evidence; do not start a host or replay input.

验证：目标编辑预检 31 passed；Main 合并检查 93 passed；只读恢复相关 worker 回归 250 passed。集合重叠，不相加。只读修复首次红阶段 5 failed / 41 passed 保留；实际输入首次完成两轮。审计先把 runner 投影误当原 trial、随后构造器参数写错，两个失败报告保留；改为原 public runner.status 全量核对后通过，未重放输入。 / Overlapping checks are reported separately. First failures remain retained; audit repairs required no input replay.

证据 / Evidence：`D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261001-learning-target-rule-edit-01/main-live-audit-final.json`、`live-01/dead-host-reopened.json`、`D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261001-learning-recovery-boundary-01/main-integrated.xml`。未改版本、打包、发布或替换安装候选。 / No version, build, publication or installed-candidate replacement.

## 2026-10-01 学习运行的识图声明 / Vision declaration in learning runs

普通工作台连接 `agent_current` 会话后可勾选“此会话的 Agent 能接收并识别截图”；`agent_delegate` 显示客户端指定视觉子 Agent、转交截图并取得结果的声明。只在实际具备能力时声明，不根据模型名称推断。默认未勾选=未知；local/API 不显示此项也不发送能力字段。该选择不是动作授权。 / Declare actual client/Agent image capabilities explicitly. Default is unknown; local/API routes do not use this option. A capability declaration is not action authorization.

声明在明确启动时固定到原 run，自动 start 接续也使用同一份；换会话/来源清空，运行和等待期间禁改。继续原运行或恢复原回执不把当前 UI 选择重新套到旧票据。MCP 调用方仍可通过原 `request.vision_capabilities` 显式声明，没有新增 API。 / Explicit starts pin the declaration; continuation and recovery preserve the original request. The existing MCP field remains unchanged.

学习目标规则未命中后，已声明能力的原请求可进入当前截图识图等待。不存在目标回交 `grounding.v1` 的 absent；重复候选回交 ambiguous、至少两个当次图候选且不选择。没有选择时不得要求继续点击或新建替代输入。原 worker 以 request_absent/request_ambiguous 失败终止属于预期拒绝；仍核对原 run/EID、实际输入状态和清理。 / Non-target facts stop the original worker without selected input; inspect original identities and cleanup rather than replaying a replacement action.

本批 Main 已按原图验证两个实机反例；首次普通入口缺少声明导致 capability_unknown 的记录保留。此结论不证明模型准确率或学习收益，也不关闭活动工作流弹窗与宿主重连验收。

## 2026-10-01 独立弹窗与验收图像 / Standalone dialogs and acceptance images

弹窗是独立原生窗口时，先等原动作终态，再 discover 核对进程、标题和可信的窗口归属，按确切 handle/process_id 执行 select；后续 grounding 必须绑定弹窗自己的新截图。不要在父窗口截图上定位独立弹窗，也不要为焦点颜色变化放宽像素新鲜度。多候选或无法核对归属时停止。 / Settle the original action, verify the independent dialog's identity/ownership, explicitly select it and ground against its fresh capture. Parent pixels and weakened freshness cannot replace correct binding; ambiguity stops input.

关闭窗口后可能无法采集原目标：保留 action_executed=true 与 failed/post_action_observation_failed，核对 recovery 候选，再确切选择父窗口、采新图核验；不能因 failed 自动重发关闭动作。活动工作流禁止竞争 select，此路径不绕过 workflow admission；活动工作流跨窗口续接尚未验收。 / Preserve dispatch and unavailable post-close observation, verify and reselect the successor, then capture. Never replay a close solely because status is failed or bypass active-workflow admission.

截图默认每目录保留最新 40 张，各 purpose 共用配额；普通回执 image_path 不自动保护 PNG。连续验收在下一批采集前复制引用图像到独立证据目录，记录原路径、归档路径、SHA256 与 run/step/EID，核对字节且不改写回执。已缺原图须如实记录。 / Default retention keeps 40 captures per directory across purposes. Promptly archive scoped bytes and hashes without rewriting receipts; ordinary receipt paths do not protect images. See [evidence boundary](docs/WORKFLOW_DEFINITION_AND_RUN_EVIDENCE.md).

## 2026-09-30 可选逐调用计量 / Optional per-call telemetry

仅在实际持有逐调用记录时，使用原 learning_workflow 的 record_model_call，绑定原运行步骤或草稿整理回复；没有记录就不报，不用工具/交接次数估计模型调用，不把等待当推理耗时。status/synthesis_status 独立返回 caller_reported_partial，不认证供应商记录，也不改变总量未知或输入结果。完整字段和例子见[接口说明](docs/OPTIONAL_JUDGMENT_AND_MODEL_USAGE.md)。 / Report only actual supplied per-call telemetry bound to original receipts; never estimate hidden calls or inference time. Partial caller summaries remain separate and do not prove total usage or input success.

判断模型当前仅预留默认关闭的程序接口，没有可连接的供应商设置或新增 MCP 判断动作；继续现有规则和 Agent 核验。旧宿主未重载本次源码。 / The reserved judgment extension adds no provider settings or MCP judgment action; use existing checks. Running old hosts have not reloaded these changes.

> **2026-09-27 后续源码，未发布 / Unreleased source follow-up:** `external_api` 已接入现有执行链；配置完整 API 端点、视觉模型和密钥环境变量名后，可用原有单步与组合命令，API 自动定位，执行仍走公共检查。已发布 test.8 ZIP 仍仅预留 API 适配器，不能按本段当成已更新。 / External API grounding is now wired into the common execution path in source. The published test.8 ZIP remains adapter-only and has not been replaced.

# Agent 接入与操作 / Agent usage — v0.1.0-test.8

test.8 新增 [Agent 视觉组合命令协议](docs/development/AGENT_BATCH_PROTOCOL.md)：显式声明能力，使用 status/continue/cancel 继续原批次，不重发已完成输入。Agent `read_text` 返回原图，不加载本地 OCR。 / Test.8 adds explicit-capability Agent batches with status/continue/cancel and original-image reading, without replay or local OCR.

**使用新视觉来源前先核对服务端版本为 test.8 或更新。** 不要向 test.7 发送新增字段。 / Verify server version before using the new fields; test.7 does not support them.

识图交接与状态命令本身不点击；`grounding_execute` 仅用于独立单步，暂停中的组合命令须用 `agent_command_continue`。沿用公共执行路由，不自动重放。独立 API [仅保留接口](docs/development/EXTERNAL_VISION_API.md)。新窗口的 500ms 等待不等于页面就绪，仍需核对原图。 / Handoff/status do not click. Use grounding_execute only for standalone grounding and agent_command_continue for suspended batches. API remains reserved; launch waiting is not page-readiness proof.


> v0.1.0-test.8：源码与隔离候选各 2025 项通过，本方 local、当前 Agent、实际 Luna 委派的单项及连续操作与清理通过；同候选独立 local、visual 与 cleanup 均已完成。首次失败、恢复与具体覆盖见验收记录。独立 API 仍仅预留接口，宿主禁用。 / Source and isolated candidate each passed 2025 checks. Main-agent local/current/actual-Luna single and continuous journeys passed; same-candidate independent local, visual and cleanup gates are complete. Initial failures and scope remain documented. External API remains interface-only with its host route disabled.

**后续学习源码，未发布 / Unreleased learning source:** `learning_workflow` 控制接口和原生任务步骤页已接入源码。`read/save` 管理固定项目快照上的步骤版本；`start/prepare/status/review/cancel` 管理一次会话内的局部试运行。`prepare` 只返回确切待执行命令与 `execution_request_id`；Agent 须将该 ID 作为新的 `instant_run.request_id`，通过原有执行路由提交建议命令，读取原回执后才能 `review`。未决、失败或不确定结果不能当作成功或自动重试。详见[工作流编辑说明](docs/WORKFLOW_EDITOR.md)。真实连续使用验收尚未完成，版本未变且未打包。 / The source adds step revisions and local-trial controls. Preparation does not dispatch input; the Agent submits the suggested command through the existing Instant route using the ticket's execution request ID, inspects that receipt, then reviews. Continuous live acceptance remains open; no new version or package has been released.

## test.6：通用应用启动 / Installed applications

本节适用于 test.6；旧 test.5 包不包含新增接口，不需要为每个软件注册 MCP。 / Available in test.6, not older test.5 bundles. Apps do not need separate MCP registration.

`instant_run` 示例 / Examples:

```json
{"request_id":"app-01","command":{"kind":"launch","name":"Character Map"}}
{"request_id":"app-02","command":{"kind":"launch","path":"C:\\Tools\\Example.exe"}}
{"request_id":"app-03","command":{"kind":"launch","path":"C:\\Users\\YourName\\Desktop\\Example.lnk"}}
```

- `app_id/name/path` 三选一；名称先精确匹配（含别名），再部分匹配。有多个候选返回 `diagnostics.candidates`，明确选择 app_id，不取第一项猜测。 / Exactly one selector; choose an explicit candidate when ambiguous.
- `discover` 有界枚举用户/公共开始菜单、桌面快捷方式及 App Paths，不扫描整个磁盘；便携软件使用绝对路径。 / Bounded discovery, explicit paths for portable apps.
- `prefer_existing` 默认 true：无 URL/启动参数时复用唯一且身份匹配的现有窗口；多个窗口需 select。传 false 显式启动；带 URL/参数不会只聚焦而吞掉参数。 / Reuse unique identity-matched windows only for argument-free launches; preserve URL/argument semantics.
- `focused + reused_existing_window=true + launch_dispatched=false` 表示复用，用户原窗口不会因此获得会话清理所有权。不同 cwd 的快捷方式仍是不同候选，预览保留实际 cwd。 / Reuse does not grant cleanup ownership; distinct working directories remain distinct and visible in preview.
- `launched_window_ready` 只代表新窗口身份匹配。UWP 专用链接及转交不同 exe 的启动器暂不保证；unknown/unavailable 后先检查旧回执和 discover，不盲目重启。 / Dispatch is not readiness; inspect uncertain launcher outcomes without blind replay.
- 桌面可先 `desktop_capture`，再 `desktop_click`，request 包含 goal 和 `click_kind:"double"`。不用先 select，但内部仍绑定真实桌面宿主、新截图识别，不接受裸坐标。打开后 discover/select 新应用。 / Desktop commands resolve shell identity and use fresh recognition, not unbound raw coordinates.


**输入框聚焦行为 / Input-field focus behavior:** 普通“点击输入框”与结构化 input 目标现在也要求模型定位可编辑区内部，避免边框、占位文字字形或相邻搜索按钮；原目标标签保留。按钮/图标/框内单词不因此改成聚焦整个字段。仍须读图核对焦点、实际文字与跳转，派发不等于成功。仍须按回执与原图独立核验。/ Plain field-click goals and structured input targets now request interior focus without changing the original label or word/button/icon targets. Inspect actual focus, text and navigation; dispatch is not success. Verify the result independently from receipts and original images. [实测边界 / Limits](docs/verification/EXECUTION_INPUT_FOCUS.md).

test.6 的历史独立验收见 docs/verification/TEST6_CANDIDATE_ACCEPTANCE.md，不沿用为 test.7 通过证据。新表单源码实测见 [批量填写记录](docs/verification/BATCH_FORM_LIVE_ACCEPTANCE.md)。/ Historical test.6 acceptance does not validate this candidate; see the separate source batch-form evidence.

## 执行契约 / Execution contracts

### 调用方调度 / Caller scheduling

本节调整 Agent 的调用组织，不新增执行权限、模型或自主跨页执行器；适用于后续调用，实际提速尚未复测。 / This changes caller orchestration, not permissions, models or an autonomous cross-page executor. Live speedup is not yet measured.

1. **调用前准备 / Prepare before dispatch.** 一次整理当前可见区域中已知的字段、值、实际标签、可确认的顺序与完成条件，尽量合成一条 `form_fill`（最多 32 项）。缺失资料可并行询问，只暂缓依赖字段，不把其他已知字段一起停住。提前准备下一批的语义参数，不提前固定截图坐标；跳转、滚动或布局变化后使用新证据。 / Prepare known visible fields and completion conditions together, up to 32 per form call. Missing facts block only dependent fields. Prepare semantic arguments, never stale coordinates; reacquire evidence after layout changes.
2. **单连接连续调用 / Keep one connection.** 同一 MCP 连接和目标会话连续使用，输入命令串行；不在每组前重复 discover/select/prepare_models。窗口切换、身份变化、宿主重启或证据失效时才重新绑定、准备。 / Keep the MCP session alive and serialize input. Rediscover/rebind/reprepare only when state or evidence requires it.
3. **等待结果而不是闲置结果 / Await, do not abandon.** 优先 `instant_run`，显式设定当前版本支持且小于客户端超时的 `wait_ms`；客户端允许时，约 30 秒的批次使用 45000 ms 预算。这是最长等待，不是固定睡眠。客户端不足以等待时保留较短预算；收到 pending 后，立即进入原 `request_id` 的只读 `instant_result` 读取循环，不先插入分析、代码查询或新输入。仍 pending 时由调用方做约 1 秒有界间隔（若接口有 next 指引则遵循），不忙轮询；超过调用方总等待预算则报告 pending 并保留请求，禁止重放。 / Prefer an explicit supported wait below the client timeout; use 45 s for a roughly 30 s batch when supported. On pending, follow next and poll only the original ID with bounded intervals, without unrelated work or new input. An elapsed budget is not cancellation or permission to replay.
4. **一次检查有效结果 / Inspect once.** 默认请求 compact 回执和 after 原图，先看字段完成/中断情况，再看返回图判断效果。证据完整且结果符合预期时，直接发已准备的下一批；不例行再取 full JSON、再截相同画面或逐字段复述。图片缺失、过期、不清晰或状态变化时补取所需证据，不以减少往返为由盲目继续。 / Inspect compact progress and the original after-image, then dispatch the prepared next batch. Fetch additional evidence only when needed; missing or stale images never justify blind continuation.
5. **诊断与执行分开 / Separate diagnosis.** 正常链路内不读源码、不调研模型、不更新文档；失败则停止正常链路，提取该失败的必要日志、修复，再按项目要求复验。文字进度在开始占用键鼠、阻塞或收尾时集中报告，不让逐字段旁白拉长批次间隔。 / Keep unrelated investigation out of healthy batches. On failure, diagnose before resuming. Consolidate narration around input ownership, blockers and completion.
6. **诚实计时 / Honest timing.** 调用方计时应记录 dispatch、pending received、result received、review complete、next dispatch；资料问题另记 asked/answered。能获取服务端 finished_at 时单列“结果完成到取回”的延迟。没有主模型请求起止数据时，review 到 dispatch 只叫调用方处理时间，不叫纯推理时间；用户等待可能与执行重叠，不能重复相加。 / Record dispatch/pending/result/review/next-dispatch and separate question timestamps where instrumentation is available. Report retrieval lag against server completion; do not call uninstrumented caller processing model inference or double-count overlapping user waits.

单步章节中的“返回后再决定”适用于依赖新观察的动作；不要求把已支持、已规划的 `form_fill` 或 `input_sequence` 拆成逐键调用。调度规则不是已有自动调度器，也不意味着当前宿主或发布包已更新。 / Single-step guidance applies to observation-dependent actions, not splitting supported preplanned batches into individual keystrokes. This is a caller policy, not a shipped autonomous scheduler or a running-host update.

### Codex 连续视觉会话适配 / Codex visual-session adapter

Codex 使用 `agent_delegate` 时读取 [codex-vision-session 技能](skills/codex-vision-session/SKILL.md)：保留同一视觉子 Agent ID，后续以 `followup_task` 处理新截图，不逐图 `spawn_agent`。每次仍使用新请求与原图证据，原会话不可用则报告阻塞。这是 Codex 客户端技能，不改变通用 MCP 协议；其他客户端沿用自己的委派机制。 / The Codex skill reuses one visual worker with fresh evidence and request correlation; it does not change the generic MCP protocol or other clients.

### test.8 组合填写 / Batch composition

以下能力要求 test.8；早期 130 项契约检查已纳入完整回归，实际覆盖与限制见 [本版验收](docs/verification/TEST8_CANDIDATE_ACCEPTANCE.md)。Tab 分组仍要求调用方确认真实连续焦点顺序，不保证任意表单。 / These features require test.8. Earlier 130 contract checks are included in full regression; see release acceptance for live scope and limits. Tab groups require known contiguous focus order and are not a universal form guarantee.

- 先收齐当前已知值，将同页独立字段放入一条 `form_fill`；缺失值另问另补，不阻塞已知字段。准备好请求后直接执行，不在批次间插入无关代码/日志调查。 / Prepare all currently known values in one form request; ask separately for missing facts and avoid unrelated investigation between batches.
- 新增 `text_navigation:"tab_groups"`。只给已确认实际 Tab 顺序的连续文本字段相同 `tab_group`；不确定的字段省略该属性，新段使用另一个组名。非文本字段自动断组；不会因选择了下拉框就直接 Tab 到未确认的文本框。 / Explicit same-named groups apply only to consecutive text fields with known real Tab order; omit the group when uncertain. Non-text controls and group changes reset recognition.
- 每段首项重新定位，之后仍检查焦点标签、身份和输入后的实际值。错焦点中断，不自动补点、不自动重放。 / Each group head is freshly recognized; every continuation retains exact focus/identity/readback checks and interrupts on mismatch.
- `instant_run` 省略 `wait_ms` 或传 null：表格最多等 45000 ms，其他命令 25000 ms；显式范围为 0–120000 ms。结果就绪立即返回，不是额外睡眠。客户端工具超时应大于该预算并留传输余量；较短客户端可显式用 25000。 / Omitted/null wait uses 45 s for forms, 25 s otherwise; explicit 0–120 s is supported. This is a maximum response wait, not a fixed delay; client timeout must exceed it.
- 使用 `detail:"compact", images:"after"`；直接核对内联后图和字段结果。只有失败或需要诊断时取 full 回执，不例行追加 capture/image 请求；需要新观察时仍正常截图。 / Review the inline after-image and compact fields; retrieve full traces on demand rather than routinely recapturing.
- 报告总等待、框架执行、批间空档三项，区分等待用户补充信息与调用方空档；不能把框架毫秒数当用户全程耗时。 / Report elapsed user time, executor time and inter-batch gaps separately, including user-input waits.

混合分组参数示例（只用于已观察到匹配标签/顺序的表单） / Mixed-group request example, requiring observed matching labels/order:

```json
{"request_id":"mixed-form-01","command":{"kind":"form_fill","request":{"text_navigation":"tab_groups","fields":[{"kind":"text","field_goal":"First name","label":"First name","text":"Test","tab_group":"identity"},{"kind":"text","field_goal":"Last name","label":"Last name","text":"Person","tab_group":"identity"},{"kind":"dropdown","label":"Region","option":"Example Region"},{"kind":"text","field_goal":"City","label":"City","text":"Example City","tab_group":"location"},{"kind":"text","field_goal":"Postal code","label":"Postal code","text":"0000","tab_group":"location"}]}},"detail":"compact","images":"after"}
```

- 精确网页链接可用 `Click the result link labelled "完整可见标题"`；唯一性按本帧范围核对，完全离屏同名项不冒充可点目标，部分可见重名仍参与消歧。点击后仍须读原图确认网址/正文变化。 / Exact quoted links use current-frame identity; inspect post-images for navigation rather than trusting dispatch. See docs/verification/EXECUTION_BROWSER_RETEST_20260921.md.

- 显式按钮标签可写 `Click the '不保存' (Don't save) button`；保留否定文字、角色和快捷键后缀。只有同帧完整 UIA 树的唯一精确按钮才约束首次模型 ROI，不能用此语法掩盖多个候选。 / Quoted labels preserve identity and role; unique exact current UIA buttons seed the initial model ROI. [定位边界 / Limits](docs/verification/EXECUTION_QUOTED_BUTTON_TARGET.md)。
- 后图缺失且 `recovery.status=process_not_running` 表示目标进程已不在，不代表正常关闭或任务成功。保留原回执、核对任务效果，不重放输入；权限错误或其他窗口的枚举错误不能解释为退出。 / Target process absence is an observation, not effect verification or authorization to replay.

- 23 种按键包括原有 15 种及 `Shift+Left/Right/Up/Down/Home/End`、`Ctrl+Home/End`。只作用于当前目标焦点，x/y 不会先点击。 / Eight selection/document-boundary chords augment the existing fifteen; coordinates do not focus the field.
- 排名是分数诊断，`recommended_candidate_id` 才是明确推荐身份，不要自行取 `candidates[0]` 替代。`current_control_ocr_text_center` 是本次真实 OCR 文字中心，原模型点另行保留；这不等于任务已成功。 / Preserve explicit selection and coordinate provenance; neither ranking nor dispatch proves task effect.
- 浏览器 `browser_document_observation` 的空正文状态不等于页面空白或加载完成；先读原图，不能按旧图坐标配新控件，也不自动重放。 / Empty UIA is not an empty/ready page; inspect current images without mixing observation generations.
- 窗口、词级与观察恢复契约已纳入 test.4；链接文档中的早期源码状态属于历史记录。 / Window, word and observation contracts shipped in test.4; earlier source-only entries in linked documents are historical.

**test.5 窗口观察 / Window observation：** `close_launched_window` 等待时增加 `close_observation` 和 `next_action`；收到 `inspect_owned_window` 后保持会话，读取并选择确切弹窗，解决已授权选项后再核验原窗口消失。动作关闭目标时，派发成功与事后图缺失必须分开判断，不根据外层 `operation_succeeded=false` 重放；先检查退出诊断；目标仍存在时才明确选窗补图，已退出时不要重新选择不存在的窗口。`instant_stop.cleanup_verified` 只代表宿主收尾。 / Pending closure now carries owned-window diagnostics; inspect the exact dialog, resolve an authorized choice and verify disappearance before stopping. Dispatch may succeed with unavailable post-images; inspect rather than replay. [详细契约 / Details](docs/verification/EXECUTION_WINDOW_TRANSITIONS.md)。

本包只提供即时操作，不是学习桥。按用户指定的低风险任务使用本包接口，不使用另一套鼠标工具冒充本包测试。快捷入口使用管理员宿主且自动风险拦截关闭；一次只允许一个 Agent 控制桌面。付款、发送、删除、最终提交等不可逆操作不在本次测试范围。

Instant-mode operations only, not learning. Use this framework for the user's supervised low-risk task; do not substitute another input backend and claim package coverage. Quick setup uses an administrator host with automatic risk interception disabled. Only one Agent may operate the desktop. Payments, sending, deletion and final submissions are outside trial scope.

## 撤销的判定 / Undo interpretation

`Ctrl+Z` 派发应用原生撤销键，不保证事务回滚或清空文档；按当前应用内容和选区核验效果。同样截图不代表同样撤销历史，不要把它当成测试环境重置，也不要因未清空自动重复按键。 / Ctrl+Z invokes native application undo, not guaranteed rollback or fixture reset. Inspect content and selection; identical screenshots do not imply identical undo history. Do not replay automatically.

**源码恢复契约 / Source recovery contract:** `keyboard_target_not_foreground` 携带拒绝当刻两个 HWND，`phase=not_dispatched` 只证明没有派发该按键；先处理/取消已识别的弹窗，再选择目标并看图，用新请求继续。取消关闭后可明确再次调用 `close_launched_window`；同一模态等待不重复关闭，`instant_result` 查询不产生关闭动作。 / Inspect and resolve the actual focus/modal state before a new request; a new explicit close can follow observed modal dismissal, while receipt reads and pending-modal checks never resend. [边界 / Limits](docs/verification/EXECUTION_FOCUS_RECOVERY.md)。

**源码候选的跨宿主启动窗口收尾 / Source-candidate recovered launch cleanup:** 正常任务仍先关闭本会话启动窗口，再 stop/断连。若原宿主已经正常停止，先用既有 epoch recovery 读取同一准入到 ready；仅对带完整 `launched_window_ownership.v1` 的原成功新 launch，显式提交 `command={"kind":"close_launched_window","handle":原launch的handle,"process_id":原launch的process_id,"request":{"admission_request_id":"原ready准入ID","launch_request_id":"原新launch请求ID"}}`。读取原实际 ID，不猜 HWND/PID、不用 select/focus 授予归属；ID 沿用 1–80 字符小写 ASCII 校验。服务核对原命令/响应 SHA、输入/资源证明和前后原生身份，未知关闭不重发；pending 时继续检查实际弹窗，不自动重复 close。旧无证明响应不补写。此为源码候选新增接口，不代表已安装正式 v0.1.1 更新；T15 只验收单层同窗口生命周期。 / After normal owner shutdown, finalize the same existing epoch admission to ready, then explicitly close a proven original new launch using the original admission/launch IDs. Source hashes, terminal/resource proof and native identity are revalidated; selection grants no ownership, pending requires actual modal inspection, and unknown closure is never replayed. This source-only extension has bounded single-layer lifecycle evidence and is not an installed stable-release update. [契约与证据 / Contract and evidence](docs/verification/RECOVERED_LAUNCH_CLEANUP.md)。

**明确单词目标 / Explicit word targets（test.5）：** `Double-click the word "East" at the end of the line` 会保持词级目标并使用独立词框；不要把整行框或模型点当作目标命中证据。双击可能包含尾随空格，替换前读取实际选区或原图，效果不明时不自动重放。 / Preserve word identity, inspect actual selection and trailing whitespace before replacement, and never infer success from dispatch. [实测边界 / Limits](docs/verification/EXECUTION_WORD_CONTEXT_FIX.md)。

**窗口观察恢复 / Window observation recovery：** `operation_success_scope=input_route_only` 时，`operation_succeeded` 只描述输入路由，仍须检查 `observation_status` 和 `agent_review`。旧窗口 after 缺失会返回 `evidence_incomplete` 和 `recovery.candidates`；按任务明确选窗再查看新请求的截图，不重放原输入，也不把同进程窗口自动当后继。 / Inspect input and observation separately; explicitly select and inspect a recovery candidate without replacing old evidence. [完整契约 / Contract](docs/verification/EXECUTION_OBSERVATION_RECOVERY.md)。

## 连接顺序 / Connection sequence

**解释器一致 / One interpreter:** MCP服务及OCR取证脚本都使用本包安装后的 `.venv\Scripts\python.exe`（Python3.11，`rapidocr-onnxruntime==1.4.4`）。不要使用PATH里的其他 `python`；旧OCR1.2.3不提供词级元数据。出现缺字符元数据错误时报告解释器路径和OCR版本，不跳过错误或改用整行框充当单词定位。 / Use the locked package venv for services and helpers; old OCR1.2.3 lacks word metadata. Report interpreter/version on this error instead of weakening geometry validation.

**客户端常见错误 / Client pitfalls:** `instant_submit` 返回 `pending` 不是操作失败或最终回执；只轮询原 request_id 的 `instant_result`，不要重复提交动作。已停止会话不会被默认 `instant_start()` 自动重开，需要显式 `new_session=true`。正常结束时，在断开 MCP 前用 `close_launched_window` 关闭本会话启动的测试窗口，再 stop 并轮询清理状态。 / Pending requires polling, not replay. Explicitly request a new session after stop; close session-owned test windows before stopping/disconnecting.

1. `instant_start(new_session=true)`，随后查询 `instant_status`，等 `phase=ready`。同一任务保持同一 MCP 连接；断连会触发宿主收尾。 / Start a fresh session, poll until ready, and keep one continuous MCP connection for the task. Disconnect initiates host cleanup.
2. `instant_submit` 提交 `discover`，使用同一个 request_id 轮询 `instant_result`，从回执读取真实窗口与应用目录。 / Discover real windows and app catalog; poll the submitted ID.
3. 按实际返回值 `launch` 或 `select`，再 `capture` 并取原图。`select` 会切前台，不猜 HWND/PID。 / Launch or select an observed target, capture, and inspect the original image. Selection changes foreground; never invent HWND/PID.

```json
{"request_id":"discover-001","command":{"kind":"discover"}}
```

`launch` 使用发现结果里的 app_id，可附 url；`select` 使用真实 handle、process_id；`maximize`、`capture` 针对已选窗口。`prepare_models` 可在连续任务前预热一次，`release_models` 释放模型。不要把每次冷启动耗时当成热启动点击耗时。

Launch uses an observed app_id with optional url; select requires real handle/process_id. Maximize/capture use the selected window. Prepare models once for a continuous task and release them when appropriate; cold-start timings are not warm-click timings.

## 组合动作 / Input sequences

**自 test.5 起提供 / Available since test.5.** test.5 提供第七个工具 `instant_run`，接受原命令和 `kind=input_sequence`；默认有限等待后一次返回精简回执与原始后图。836 项测试、真实 Google 连续搜索及只填写已验证；不是跨站点准确率或整体提速保证。完整示例、部分完成与超时读取契约见 [组合动作说明 / Input sequences](docs/verification/EXECUTION_INPUT_SEQUENCE.md)。test.5 provides this entrypoint; older six-tool packages do not. / The seventh tool bundles a bounded wait, compact receipt and original after image. 836 tests and bounded Google continuous/fill-only cases passed; this is not cross-site accuracy or end-to-end speed assurance. Earlier test.4 has only six tools and does not support this entrypoint.

组合仅限 Agent 已决定的“聚焦字段 → 输入 → 核对 → 可选 Enter 搜索”。不要把需要观察后重新决策的结果点击提前加入，不把 `completed` 当成搜索结果正确。`pending` 不等于取消；沿用原 ID 读取，保持 MCP 连接。 / Group only already-decided field input and optional search; inspect the result before choosing a result link. Completion is not task success, and pending is not cancellation. Keep the connection and read the same ID.

## 表单填写 / Form fill（test.7）

`kind=form_fill` 支持最多 32 项文本、日期文本、下拉选项、复选状态和单选，按声明顺序填写，不自动提交。一个批次应尽量包含当前已知字段，避免每字段一次 Agent 往返。失败看 `completed_fields`、`interrupted_at`、`remaining_fields` 和原图；不要重放已完成字段。/ Declare up to 32 known fields in one ordered batch to reduce agent round trips. Read partial progress and images on interruption; never replay completed fields. See [完整协议 / Contract](docs/verification/EXECUTION_FORM_FILL.md).

```json
{"request_id":"form-batch-01","command":{"kind":"form_fill","request":{"text_navigation":"tab_sequence","fields":[{"kind":"text","field_goal":"Customer name:","label":"Customer name:","text":"Test Person"},{"kind":"text","field_goal":"Telephone:","label":"Telephone:","text":"0000000000"},{"kind":"text","field_goal":"E-mail address:","label":"E-mail address:","text":"test@example.invalid"}]}},"images":"after","detail":"compact","wait_ms":25000}
```

此例为 `instant_run`，只适用于已观察到的相同标签与 Tab 顺序。默认 `text_navigation=recognize_each` 可混合字段；`tab_sequence` 只接受具名文本，首项定位后每次 Tab 复验下一标签，不对错误焦点继续输入。完整当前 UIA 唯一可写字段可在模型调用前提供真实中心；证据缺失保留视觉路径。/ This example uses `instant_run` and observed labels/order. Default recognize-each supports mixed fields. Tab mode accepts labelled text only, verifies each next focus, and stops on mismatch. Unique current writable-control geometry may be used before inference; missing evidence retains visual localization.

日期示例：`{"kind":"date","field_goal":"Click the input labelled \"Date picker\"","value":"2026-10-15","format":"MM/DD/YYYY"}`。仅日期文本录入与读回，不自动点击日历。文件选择仍是独立流程：按钮→发现并选择原生文件窗口→填写用户批准的确切测试路径→核对→打开→重新选择原表单检查附件名；可能即时上传，不等于最终提交。/ Dates are formatted text input/readback, not calendar navigation. File selection remains an explicit native-dialog journey and may upload immediately; it is not final form submission.

文件控件不是普通文本字段：不要对网页 `File input` 使用 `kind=text` 期待弹出文件窗口。先用 `execute_recognition_plan` 点击当前可见的选择文件按钮，再用 `discover` 取得新对话框的真实 `handle/process_id`，`select` 后才能填写对话框内的文件名。窗口关闭后重新选择原网页并截图核对附件名；无事后帧不等于没执行，禁止盲目重放。原生带助记字母的完整标签如 `打开(O)` 应保留，建议用引号明确标签；修复支持动作宾语中的未加引号助记标题，不将后置用途 `to confirm the file` 当作另一个目标。/ A browser file picker is not a text field. Recognition-click its visible button, discover and select the actual native dialog, then fill its filename. Rebind the web window and inspect the filename after closure. Missing post-action imagery is not proof of no action; do not replay blindly. Preserve full mnemonic captions such as `打开(O)`, preferably quoted. Bare mnemonic action objects are recognized without interpreting a trailing purpose as another target.

`select` 的 `handle`、`process_id` 与 `kind` 同层；`press_key` 的 `x/y` 必填，为当前绑定窗口原图像素。`launch` 不保证有图，后续用 `capture` 观察。/ Put select's handle/process_id beside kind, not inside request. press_key requires x/y in the bound window's current image pixels. launch need not include an image; capture afterward.

## 单步输入 / Single-step input

每次只提交一个动作，回执返回并看图后再决定下一步。以下坐标仅为示例，必须替换为当前原始窗口截图上的像素坐标，不是桌面坐标或缩略图坐标。

Submit one action at a time, await the receipt and inspect images before proceeding. Example coordinates must be replaced using the current original window image, not desktop or thumbnail pixels.

```json
{"request_id":"click-001","command":{"kind":"step","operation":"execute_recognition_plan","request":{"goal":"Click the button labelled Search","task":"click_target"},"observation_wait_ms":2000}}
```

```json
{"request_id":"type-001","command":{"kind":"step","operation":"type_text","request":{"text":"Google Maps","x":500,"y":300,"click_before_typing":true,"clear_existing":true}}}
```

```json
{"request_id":"enter-001","command":{"kind":"step","operation":"press_key","request":{"key":"Enter","x":500,"y":300},"observation_wait_ms":2000}}
```

```json
{"request_id":"scroll-001","command":{"kind":"step","operation":"scroll","request":{"direction":"down","wheel_clicks":3,"x":500,"y":400}}}
```

`type_text.clear_existing=true` 显式替换已有内容，默认 false；不会自动回车或提交。`press_key.key` 精确支持：

`Enter`, `Tab`, `Shift+Tab`, `Escape`, `Backspace`, `Delete`, `Left`, `Right`, `Up`, `Down`, `Home`, `End`, `Ctrl+A`, `Ctrl+Z`, `Ctrl+Y`。

test.5 支持 `Shift+Left/Right/Up/Down/Home/End`、`Ctrl+Home/End`，共 23 种支持键；旧 test.3 不支持新增的 8 种。单项与连续测试的覆盖不同，详见发布记录。 / test.5 supports 23 keys including these eight new chords; do not send the additions to test.3. See release notes for single-operation versus continuous coverage. See [selection keys](docs/verification/EXECUTION_SELECTION_KEYS.md).

按键发给当前焦点；其 x/y 只用于窗口点校验，**不会点击或重新聚焦**。先通过截图确认焦点；切字段用 Tab/Shift+Tab。应用可能不支持撤销/重做，不把按键派发当作生效。不支持任意组合键、shell 或隐式 submit。

Explicit clear_existing replaces text; default false, without implicit Enter/submit. Keys above go to current focus. Their x/y do not click or refocus. Confirm focus, use Tab/Shift+Tab to change fields, and inspect results. Undo/redo support depends on the app. Arbitrary chords and shell commands are unsupported.

## 右击、双击和读取 / Right-click, double-click and reading

`request.click_kind` 为 `single`（默认）、`right`、`double`。右键只是打开菜单；查看原图后另发单击菜单项。双击只选目标词的效果必须看图确认，不能只看点击次数。 / Use single (default), right or double. Inspect the menu before a separate item click; verify actual word selection from images.

```json
{"request_id":"right-001","command":{"kind":"step","operation":"execute_recognition_plan","request":{"goal":"Right click inside the search input box","click_kind":"right"}}}
```

```json
{"request_id":"double-001","command":{"kind":"step","operation":"execute_recognition_plan","request":{"goal":"Double click the word Rotorua inside the search input box","click_kind":"double"}}}
```

```json
{"request_id":"read-001","command":{"kind":"read_text","max_chars":10000}}
```

`read_text` 的文字在 `receipt.result.text`，行框在 `receipt.result.lines`，原图信息在 `receipt.result.capture`；不是输入动作的 `response.data.result`。用同一request_id调用 `instant_image`。只读当前可见像素，`read_complete=false`不表示调用失败。 / Read results use the direct result/text/lines/capture contract, not the input-action envelope; retrieve the same ID's image. Visible pixels only; read_complete=false is not a command failure.

## 可恢复错误 / Actionable errors

`step.observation_wait_ms`只允许0–2000毫秒。先按工具schema检查参数；MCP外层schema拒绝可能是`isError=true`的文本块，而不是JSON业务回执。保留原始文本及字段名，不用JSON解析异常覆盖它，也不要把未入队请求算作执行失败后的重放。 / The observation-wait range is0–2000ms. Transport/schema rejection may be a plain-text MCP error rather than a JSON operation receipt. Preserve the raw error and invalid field instead of replacing them with a JSON parsing exception.

- 非法字段返回 validation_rejected，包含字段位置/允许字段；原填写值不回显。修正参数后再提交，不退出连接或重复加载模型。
- 宿主未就绪、已有命令处理中或正在关闭时返回 state_rejected 和 next 查询指引，不把被拒请求写入执行队列。
- 多候选或无有效坐标会返回候选诊断；使用当前证据明确目标，不凭候选列表盲点。
- 已输入但后图采集失败时，回执保留 error_code 和 capture_current_state_without_replaying_input 指引；先单独 capture，不能假定尚未输入。

Runtime command validation returns structured errors without echoing input values. SDK-level outer schema or pre-start invocation errors may instead be generic tool errors; do not include sensitive values when reporting them. Lifecycle admission rejections return status/result guidance where available and do not enqueue input. Ambiguous targeting returns candidate diagnostics. A post-input capture error calls for a separate capture, not another input attempt.

## Agent 判断结果 / Judge the outcome

### 回执取值 / Parsing receipts

先解析 MCP 文本块中的 JSON，不把调用方日志包装的 `parsed`/`value` 当成服务端字段。等待 `status=returned` 后，完整单步识别回执的操作细节位于 `receipt.result.response.data.result`；错误或未完成回执可能没有这一层，先检查状态和错误。表单完整回执读取 `receipt.result.fields`、`receipt.result.completed_fields`、`receipt.result.interrupted_at`；默认精简回执对应 `receipt.form.fields`、`receipt.form.completed_fields`、`receipt.form.interrupted_at`，不经过单步的 `response.data.result`。识别点击的 `selected_click_point` 为 `{"x":333,"y":132}`；`resolved_click_point.bbox` 为 `{"x":310,"y":123,"w":47,"h":18}`，**不是数组**。按键名读取，不能用 `[int(v) for v in bbox]`；那会把 `x` 等键名当数字。示例数字仅说明结构，不可作为操作坐标。

Parse the MCP JSON text, not client-log wrappers such as `parsed`/`value`. Completed full single-recognition-step details live at `receipt.result.response.data.result`; failed/pending receipts may omit it. Full form receipts instead use `receipt.result.fields`, `receipt.result.completed_fields` and `receipt.result.interrupted_at`; default compact form receipts use `receipt.form.fields`, `receipt.form.completed_fields` and `receipt.form.interrupted_at`. Points and rectangles are named-key objects, not arrays. Never reuse these illustrative coordinates. For screenshots, prefer the top-level `receipt.agent_review.before/after` tool arguments; do not recursively pick the first matching diagnostic field.

### 自行裁剪和OCR取证 / Client-side crops and OCR

识别点击的上述矩形使用 `x,y,w,h`；`captured_text_v1.lines[].bbox` 则使用 `x,y,width,height`，按具体契约读取，不混用键名。例如 Pillow `Image.crop` 要求 `left,top,right,bottom`，将宽高转换为 `(x,y,x+w,y+h)`，并检查区域在当前原图内、宽高大于零。不能直接传 `(x,y,w,h)`，也不能把上一轮截图坐标用于新截图。 / Recognition rectangles above use `x,y,w,h`; captured-text line boxes use `x,y,width,height`. Follow the specific contract, then convert dimensions to Pillow `(x,y,x+w,y+h)`. Check positive dimensions and current-image bounds; do not reuse an older capture's coordinates.

外部OCR进程非零退出、缺输出或JSON解析失败是**取证工具错误**，必须保留退出码和stderr，不能转换为“未识别到文字”或产品操作失败。 / Nonzero exit, missing output or invalid JSON is an **evidence-tool error**, not empty OCR or a proven product failure.

判断文本选区时只看目标输入行；不要合并浏览器标题、正文中的同词框。右键菜单可能遮住原文字，菜单展开图不适合作为唯一选区基线：优先使用本次打开菜单前的原图和全选后的原图，菜单关闭仅作辅助证据。未确认选区就停止后续替换，但把原因准确区分为操作失败或证据不足。 / Scope selection checks to the input row. Use the current pre-menu image as the unobscured baseline, not solely the menu-open frame; separate action failure from insufficient evidence.

- `returned` / `operation_succeeded` 只说明命令与输入链状态，不证明任务成功。识别点击的 `verified=null` 与 `retry_reason=awaiting_agent_review` 表示等待你的判断，不自动重放。
- 读取 `instant_result.agent_review`，分别执行 before/after 中的 `instant_image` 参数。默认 `view=after` 兼容旧调用；原 PNG 不缩放且验证 SHA-256。
- 主证据对是 `before_input` / `after_settled`；内部诊断的 `before_immediate` / `after_immediate` 和 diff 是另一组帧，**不可混用**。主证据没有额外服务器 diff；等待后图不保证渲染结束。
- 根据目标和图像报告 success / failure / uncertain，并说明可见依据。没有变化可能是目标原本已选中；画面变化也不证明点中了目标。文字部分匹配不等于完整目标身份验证。
- `evidence_incomplete`、结果未知或图不可读时，不猜成功、不盲目重试；可单独提交新的 capture。Agent 结论保留在其会话，本版没有服务端判定写回工具。

Returned/operation_succeeded describes command/input handling, not task success. Retrieve both original frames via agent_review. Compare the primary before_input/after_settled pair against the goal and report success/failure/uncertain with evidence. Immediate diagnostic diffs belong to a different pair. No change can be valid; change alone is not success. Missing evidence requires inspection or a separate capture, not replay. Agent judgements remain in its conversation.

## 重连与结束 / Reconnect and stop

**test.6 修复 / Fix:** `cleanup_pending` 表示原宿主保留所有权、等待清理，不是已停止。读取清理诊断、解除阻塞后，再调用 `instant_stop` 只重试清理并轮询状态；不会重放输入。不要持续盲目调用 stop，也不要删除会话记录以绕过 `previous_session_not_resolved`。宿主日志可能记录 `cleanup_report_error` / `cleanup_signal_error`；日志写入失败时不能用旧 report 判断已结束。已卡死的旧版本宿主不因修改源码而恢复。

`cleanup_pending` retains the original owner until cleanup can be verified. Inspect diagnostics, resolve the blocker, then explicitly call `instant_stop` to retry cleanup only and poll status. Never replay input or delete session records. Report/signal I/O failures may leave a stale report; previously stranded old-version hosts are not retroactively repaired. See [lifecycle evidence and limitations](docs/verification/V5_MODEL_CLEANUP_FIXES.md).

请求 ID 在会话内唯一。同 ID、同命令读取原回执；不同命令不得复用 ID。`pending` 继续查询原 ID，`result_unknown` 先检查现场，不能当作没执行。

先提交 `command={"kind":"close_launched_window","handle":本次launch返回的handle,"process_id":本次launch返回的process_id}` 正常关闭自己的测试窗口；不要填写用户原有窗口。随后调用 `instant_stop`，轮询 `instant_status`，直到 `cleanup_verified=true`，最后断连。第一次返回 false 可能只是仍在清理，不是终态失败。重连先用 `instant_start()` 附着历史；确实需要新任务且旧会话清理完成后才用 new_session=true。

IDs are unique per session. Reusing an ID retrieves its original receipt and never authorizes replay with different content. Poll pending IDs; unknown results may already have affected the target. Stop and poll until cleanup_verified=true. A transient false is not a final cleanup failure. Reattach before requesting a fresh session.


### 读取实际执行结果 / Read the actual execution result

不要递归抓取第一个 `action_executed`：`recognition_plan.execution_path` 是 planning 快照，实际输入读 `response.data.result.execution_path`、`agent_step_result` 与 `click_result`。目标关闭后 after 不存在不是未派发，也不独自证明成功，需核对当前窗口状态。 / Planning snapshots are not execution receipts. Read the actual execution fields and independently check task effects and target exit.


**可选条件等待，自 test.5 起提供 / Optional conditional wait, available since test.5:** 在 `step` 或搜索型 `input_sequence` 的 command 中提供 `observation_condition={"text":"准确的可访问名称","control_type":"Text"}`，并设正数 `observation_wait_ms`（最高2000）。只接受明确名称和角色；不知道准确标志时省略，不猜名称。`condition_met` 不等于任务成功或全页渲染完成；`timed_out` 不代表输入没执行，不自动重放。同步 UIA/截图 I/O 不受轮询预算硬中断。 / Supply an exact accessible name and role only when known; otherwise omit the condition. Condition success is not task/full-page success, and timeout must not trigger input replay. Polling budgets do not hard-interrupt synchronous UIA/capture I/O. [完整契约与实测 / Contract and tests](docs/verification/EXECUTION_CONDITIONAL_WAIT.md)。


请求ID必须为1–80位小写ASCII字母/数字/下划线/连字符，首位为字母或数字；非法ID返回invalid_request_id，不入队，修正后沿用同一连接。条件应选稳定的正文标志，不选天气/轮换广告。 / IDs use 1–80 lowercase ASCII alphanumeric/dash/underscore characters, starting alphanumeric. Invalid IDs are rejected before admission; correct them on the same connection. Prefer stable content markers over weather/rotating ads. [独立实测及已知限制 / Acceptance and limits](docs/verification/EXECUTION_AIONUI_ACCEPTANCE_20260921.md)。

### 明确字段名称 / Explicit field labels

字段名称来自当前界面，不要把产品名当字段名。需要指定标签时用 Click the input field labelled "当前完整名称"；未指定名称时可用 Click the search input field。命名字段缺失返回 named_field_current_uia_missing，不能把合成按钮当成可写字段。核对本次截图与诊断后再提交明确的新指令，不自动重放。 / Use the current full field label, not the application brand. Explicit label goals preserve their literal identity; a missing named field is not replaced by a synthetic button. Inspect current evidence before a new instruction; never replay automatically.

### Field-reading details / 字段读值细节

Plain named field goals tolerate one terminal label separator (`Address` / `Address:`); full words and explicit structured target identities remain intact. Before typing, the original current UIA identity and bounds are checked. After typing, the same focused runtime identity may resize: the read-only check requires a current real box containing the original point and two stable reads, and records `input_check.geometry_change`. It does not authorize another click or reuse new coordinates.

普通命名字段可忽略标签末尾单个冒号，不裁剪标签正文。输入前仍核对原身份与框；输入后同身份字段可扩缩，通过当前焦点、真实框、原点命中与稳定双读核对值，并记录只读几何变化，不据此自动重试输入。

### 焦点字段输入 / Focus-bound keyboard input

组合输入会固定当次识别字段，再核对实际焦点与当前值。浏览器自动填充遮住旧鼠标落点不等于字段失焦；仅该内部已绑定字段的键盘派发使用焦点复核，不会自动点击建议项。窗口、字段身份或焦点变化会中断并返回部分结果，不自动重试。 / A compound input binds the recognized field and checks its live focus/value. Autofill overlapping the old pointer point is not focus loss; only the internally bound keyboard path uses field-based revalidation. Changed identity/focus stops with partial progress, never automatic replay.


明确的裸字段描述（例如 Search box at the top-left of the webpage）也会保留当前UIA字段身份；不要求必须以Click开头。链接在UIA中的完整名称可能同时含标题、站点和URL；发生名称冲突时读取完整诊断和当前图，明确消歧，不重复盲点。/ Bare field-role phrases preserve current UIA identity too. Link accessible names may combine title/site/URL; inspect diagnostics and the current image before explicitly resolving ambiguity.

### Closed file-picker target / 已关闭文件窗口

`打开(O)` 或取消关闭对话框后，原绑定 HWND 已失效；先 `select` 原浏览器再 `capture`。直接截取旧对话框当前会返回 `ValueError: Window handle is not valid`，尚无结构化重新绑定指引；这不代表之前点击未执行，不要重放。/ After Open or Cancel closes a picker, explicitly select the original browser before capture. Capturing the old handle currently returns a raw invalid-window ValueError without a structured rebind hint. This is not evidence that the prior click failed; do not replay it.

**学习源码目标提议 / Learning-source target proposals:** compile 只读返回 proposed_target_recipes；save.request.target_recipes 传 recipe 对象并与 definition/expected_sha256 一起核验。自动提议 v2 固定原动作，人工编辑用 v3 editorial/unverified 并保留原 v2 上下文。普通 UI 已支持固定控件/多条件可见行及1–8条已有策略的排序和增删；预览只针对学习证据，保存不代表动作验证。动作类型、控件类型和声明的文本依赖必须相容；未知/未来输出拒绝。旧 v1/v2、图 pin 和程序不改写。 / Editorial revisions preserve source context and remain unverified; original execution tickets are never replayed on source errors.

**学习源码同会话整理 / Same-session synthesis:** workflow 学习停止后检查 `result.synthesis.status`。若为 `awaiting_agent`，直接使用 `result.synthesis.synthesis_request`；中断后可调用 `learning_workflow` 的 `synthesis_status`（synthesis_id）恢复，或 `synthesis_prepare`（learning_session_id）获取当前来源请求，两者返回顶层 `synthesis_request`。当前 Agent 查看请求引用的原图/事件以及可用 input_examples，一次回交 `synthesis_complete` 的原 synthesis_id/source_sha256、parameter_bindings、annotations。不调用视觉 continue、不新建会话、不重放动作；input_examples 缺失不能猜值。 / Consume the stop handoff directly or resume its exact identity, then return one structured reply from the current agent.

`draft_ready` 只是待审草稿。按 conversation.state 处理：initial_reply 回交一次；correct_once 根据 last_correction/errors 自动修正一次；awaiting_user 停止回复并向用户说明具体字段。收到用户真实补充或明确继续后，调用 synthesis_resume，传原 synthesis_id/source_sha256、last_correction.reply_request_id 为 after_reply_request_id，以及真实 user_instruction（1–4000字符）；后续 complete 必须带返回的 conversation.resume_request_id。不得编造用户补充或通过重开/prepare 重置预算。pending/unknown 先回读原外层 request_id；来源/存储错误不猜修。历史顺序未知时不推定最后回复。 / Follow the persisted reply state, allow one automatic correction, and resume only on actual user input; preserve original request and round identity.

**学习源码计量 / Learning-source metrics:** 原生结果、实际 API 尝试和已结束的 Agent 交接按本次原票据/历史幂等关联。recognition_handoffs 只记录从交出新截图到恢复/取消/过期/失败的 wait；包含调用方与人工空档，不能记成模型推理时长或一次模型调用。未结束的 grounding_wait 只有开始时钟，不补造终点；重复 status 不增记。主 Agent 全量调用和 usage 不可观测时仍为 null；metrics unavailable 不改变执行事实或授权重放。此变化未发布，见[开发证据](docs/verification/LEARNING_WORKFLOW_BENEFIT.md)。 / Handoff wall time is not model inference; missing telemetry never authorizes input replay.


**学习工作台运行适配 / Learning workbench runtime attachment:** 工作台以非所有者客户端附着现有 Instant 会话，复用原 submit/result，不 start/stop MCP 或宿主，不修改识图配置。运行使用已保存 program_id；原 Agent 仍处理明确的定位/结果判断等待。编辑器控制标记只帮助找回原请求；恢复出 start ready 后须用户明确选择 run，不自动续跑。not_submitted 与 result_unknown 分开，后者不得重放；回执、程序、起点与参数的原始绑定不符即报错。源码/离屏证据不代替实机验收。 / The editor is a non-owning client and resumes only verified original state; agent waits and physical acceptance retain their existing contracts.


**基准采集入口 / Benchmark collection:** 开发验收可使用 [LEARNING_BENCHMARK](docs/LEARNING_BENCHMARK.md) 的 freeze/baseline/compare。baseline 保持一个原 MCP 连接，调用方消费 JSON 行协议并复用识图会话；不把工具 returned/pending 或已派发当任务成功，不自动重放。未知全量调用不记零，生成报告仍为 empirical_acceptance=false。普通用户继续使用对话与工作台。 / This developer collector preserves original receipts and unknown totals; it does not replace normal controls or action confirmation.


**Record Desk 基准 / Record Desk benchmark:** 开发采集可传 --fixture-root 连接本轮新夹具；next/begin 返回冻结案例顺序和本次输入，不给详情真值。控制器只重置自建窗口并观察，真正点击/填写仍从原 MCP/gated action API 派发。finish 和离线比较按同 case/epoch 的新状态及事件复算；不把仅 discover 的 returned 记为任务成功。 / Private outcome evidence stays in the local benchmark journal; task input still uses the existing gated executor.


**学习源码执行策略 / Learning-source execution strategy:** learning_workflow start 可选 execution_strategy=learned|steps_only，省略为 learned；运行开始后不能切换，重用 start ID 搭配不同策略会冲突。steps_only 在原票据生成前禁用 target_memory，但保留本次动态目标描述与参数；preview 分开显示源程序审核状态和该变体待验证状态，不改源程序版本。verify 返回 steps_only_agent_review_required，当前 Agent 根据本轮证据走原 review，再按原 wait_id continue；不能写成 rule 判断。 / Pin strategy at start and retain the original program, receipt identity and Agent review provenance.

基准采集的 A 禁止工作流与目标记忆，B/C start 在落盘实际调用前固定对应策略，并核对后续回执；直接启用策略不是实际收益证据。API/当前 Agent/同会话委派/本地来源保持原配置，API/Agent 不需本地权重；总模型调用与 token 缺测时保持未知。 / Route checks do not attest full model telemetry or empirical benefit.
# 学习开发树的明确恢复入口 / Explicit recovery in the learning development tree

**忙碌拒绝和继续 / Busy rejection and continuation:** 工作流 continue 返回的 ready 不是重新提交 run 的授权；运行时可继续调度原任务。等待 ID 漂移先读原 status，grounding_required 只处理原 worker/request，不新建命令。明确 input_admission_rejection.v1 仅证明被拒请求在派发前没有输入，原 worker 必须独立核验。修改源码不等于旧 MCP 已加载；没有热加载入口时正常结束旧连接后重连，保留首次失败，不能拼接为同连接通过。 / A ready continuation response does not authorize a competing run; original scheduling can advance. Read original status after wait drift and resolve only the original grounding request. Typed busy rejection proves no input for that rejected request alone. Source edits do not reload an existing MCP: normally reconnect after ending the old connection, retaining failures without stitched continuous acceptance.

仅本开发源码新增两个实验性工具，正式 v0.1.1 下载包仍为原七工具。宿主异常退出后先调用 `instant_recovery_preview`，它只核对原资源与全部原输入终态/结算；未知或漂移时停止。明确准入使用 `instant_recover_session(request_id, preview_sha256)`，参数必须来自该预览，后续查询仍使用同一 ID/hash，不创建新请求来绕过未完成事务。/ Two experimental source-only tools verify original evidence and admit a successor with one durable ID/hash; they are not shipped in stable v0.1.1.

普通 `instant_start(new_session=true)` 清理门控保持。启动后的错误可能已有宿主；`host_launch_attempted=null` 与 `launch_unknown` 不等于未启动，禁止自动再次创建或重放旧输入。new_epoch_ready 仅证明新宿主可用，workflow_takeover_completed 仍为 False；不要通过普通旧 workflow verify/continue 改写结算或推进旧步骤。见 [本轮证据和限制](docs/verification/LEARNING_EPOCH_ADMISSION.md)。/ Unknown launch state and readiness grant neither retry nor workflow-takeover authority.

2026-10-02 live-07收尾 / Closed diagnostic update:

执行/审计边界：执行子会话不读取原benchmark journal、fixture_prepared/observed、records或score；这些由不参与输入的Main/审计者保留。执行者仅消费白名单回执、自己的原worker终态及新鲜PNG。若误接触评分数据，记录实际已输出内容和发生时刻、停止后续受影响采样并另冻新数据，不改旧成绩。 / Input workers use receipt-only projections and never audit raw oracle-bearing records; disclose exposure and close affected future sampling.
