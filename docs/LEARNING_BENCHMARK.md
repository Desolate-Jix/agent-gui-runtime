# 学习基准采集 / Learning benchmark collection

## 2026-10-07 准确与速度先导 / Accuracy and speed pilot

同冻结安装版、同 revision4 程序和持续复用的两个 Sol worker 完成一族六对A/C；前五对与最后一对分属两次 MCP 连接，未宣称同一连接全通过。界面准确结果A/C均6/6；原collector首轮完成A6/6、C5/6，C09明确无输入拒绝漏记导致的失败保留。四对无中断/恢复且原采集完整的对照中位逐对提速32.9%，固定场景仅2.9%；并未证明准确率提升、长尾或每次稳定。三处定位真实 memory_uia 命中，但两处定位及四步判断/读取仍依赖Agent，因此采用unbound部分C诊断，不抵扣正式配额，总用量仍未知。详见[完整报告](verification/LEARNING_ACCURACY_SPEED_PILOT_20261007.md)。 / Six paired cases use the same installed product, immutable program and persistent workers across two MCP cohorts. GUI accuracy is6/6 per route; collector first-attempt completion remains A6/6,C5/6. Four clean pairs show32.9% median paired savings, but stable savings are2.9%. Partial unbound C, unknown usage and small samples do not establish formal benefit or every-run stability.

**最终 review completed 不等于 Runner completed。** 最后人工/Agent review 后，按原run查询status、续接确切final wait，并确认runner_state=completed、wait/pending/active_command_id为空，才结算完整运行；这次continue不增加桌面动作。明确accepted=false/action_executed=false/automatic_retry_allowed=false的拒绝回执是拒绝终态，不是输入成功；运输错误或缺失回执不能这样推定。 / Final review may complete the Trial while the Runner still waits. Continue the original final wait and confirm runner completion with empty pending fields before settlement. Explicit non-executed rejection is a rejected terminal receipt, not action success; transport errors are not equivalent.

## 连续图像保全 / Continuous image preservation

运行时默认每目录保留最新 40 张截图；普通回执引用不自动保护 PNG。每步结算后、下一采集批次前，把原回执/终态及定位、读取、规则帧的现存图像复制到独立归档，记录原路径、保存路径、字节 SHA256 与 run/step/EID，不修改原回执。旧原图缺失时，只有摘要相同且可核验的归档字节才可补齐，否则完整资格仍为 false。 / Archive original scoped image bytes promptly, before rolling retention removes them. Only verified matching archives close an unavailable original reference; do not rewrite receipts or substitute a different screenshot.

2026-10-01 的变化与编辑运行审计通过，但仍有 Agent 结果判断、未知总用量及未完成公平配额，不能列为正式 C 或经验收益达标。QA reviewed 标记仅检查审核失效，不冒充人工审核。详见[验收记录](verification/LEARNING_WORKFLOW_BENEFIT.md)。 / Current physical checks do not qualify formal C or empirical benefit; QA markers have no human-review claim.

## 2026-10-01 固定定义与实际覆盖 / Pinned definition and actual coverage

每个 case 新增可选 c_workflow 描述符，字段为 workflow_id、program_id、content_sha256、project_snapshot_id、start_step_id、artifact_path、target_memory_steps、rule_verification_steps。字段均来自本轮已保存版本与确切入口；artifact_path 必须指向 artifacts 中 kind=workflow、version=program_id 的同一文件。不得把 pending 手改为 reviewed 后冒充人工审核。冻结校验全部可达 success/failure/uncertain 分支、内容摘要及真实目标/结果规则集合。未配置该描述符的清单仍可用于诊断，但不是已审核 C 的证据。

Each case may bind a saved reviewed program and entry with the optional descriptor. The matching workflow artifact and exact reachable rule sets are verified at freeze time; unbound manifests remain diagnostic. Do not relabel pending definitions as human review.

绑定案例的 B/C 使用同一版本，begin 后先通过 instant_run 的 learning_workflow.read（workflow_id/program_id）取原完整回执，再 start。B 注入 steps_only，C 注入 learned；入口、输入、原 trial 和 prepare 票据不可偷换。完成必须来自该工作流的 run/continue/review/verify/status/cancel 回执，ready 或单纯返回不是任务完成。遇到 Agent 识图交接，按该 trial 原执行票据、当前 pending grounding ID 解析和续接；不新建识图执行。已有 record_model_call 按原 scope 记账，不能向其它运行填数。

Bound B/C reads and starts pin the same version with their original strategies. Completion requires the original workflow result, not a ready trial or returned transport status. Continue the same execution/grounding identity; caller telemetry remains bound to its actual original scope.

比较新增 workflow_provenance 与 c_route_contract。归档并复算原定义、history、命令/响应/异步终态、核验 JSON 和本会话图片字节，区分记忆执行命中、回退、未执行、未到达、未知以及 rule/agent/runtime 判断。规则事实和图片字节闭合分别显示，缺图不得取得完整资格；还有 Agent 动作判断也不能冒充全部规则核验。该资格只覆盖已记录的正向 scored、非恢复尝试，三类配额、完整用量和收益验收仍独立检查。

Comparison adds definition/coverage snapshots and qualification for recorded positive scored non-recovery attempts. It distinguishes actual memory execution and judgment sources, verifies archived bytes, and keeps missing evidence unknown. Qualification does not prove quotas, complete telemetry or benefit.

定义回读、校验和调用方空档仍在 begin→finish 的总耗时内，不可称作模型推理耗时；不同路线的初始化工作应在公平协议中保持一致。完整调用/token 仍未知，empirical_acceptance=false，原失败尝试不筛除。详细边界见[定义和运行证据](WORKFLOW_DEFINITION_AND_RUN_EVIDENCE.md)。 / Definition reads, checks and caller delays remain part of end-to-end time; preserve fair setup and failures. Complete usage and empirical acceptance stay open.

## 2026-10-01 逐类收益判断 / Per-family benefit assessment

`comparison.benefit_assessment` 保留原合并结果，并标记 `scope=matched_aggregate`。新增 `by_task_family`，分别输出每类的调用节省、稳定暖运行中位耗时、首轮正确率、样本充分性及阻塞原因；`all_families.state` 才表达全部任务类的收益目标是否达标。每类分别要求 20 对 A/C、稳定/未见/布局 8/6/6 与 B 至少 5 次，至少三类全部达标才为 met。任一类退步可为 not_met；缺计量、配额不足、重试不可比或满分基线仅持平不会被合并平均掩盖。

The aggregate remains available for compatibility, explicitly scoped as matched_aggregate. by_task_family evaluates each family independently; all_families reports the combined acceptance state. Each family keeps the 20 A/C, 8/6/6 and B5 quotas, and at least three families must meet all targets. Missing evidence and parity cannot establish benefit; regressions remain visible.

主 Agent 本轮复核评分与采集合同共 53 passed，证据为 `20261001-learning-acceptance-01/scoring-main-verified.xml`。这是合成数据与采集合同检查；实际三项收益、全量模型用量和 R4 实机对照仍未验收。 / The main-agent rerun passes 53 synthetic/collection checks; real benefits and complete usage remain unverified.

这是未发布学习源码的开发验收工具。普通用户继续在 Agent 对话和工作台中学习、审核、修改；无需使用下面的 JSON 协议。 / This unreleased developer tool does not replace normal conversation/workbench controls.

`scripts/benchmark_learning_workflow.py` 提供 `freeze`、`baseline`、`compare`。baseline 是持续采集会话，可记录 A/B/C；复用一个 `LearningBenchmarkClient` 和一个 Instant MCP 连接。调用方继续负责真实任务、识图交接与原有动作确认，脚本不自行调用模型、不绕过原执行器。 / Collection uses one existing MCP connection; the caller owns task execution, grounding and existing confirmations.

## 冻结 / Freeze

清单顶层字段为 `benchmark_id`、`model`、`cases`、`artifacts`。`model` 仅包含 `source`、`model`、`config_digest`（64 位小写 SHA256），不放密钥。可选 artifact 为 `{kind,path,version}`，kind 是 workflow/recipe/runtime_config，path 是本轮实际文件的绝对路径。冻结时只保存哈希、版本及路径，不复制配置内容。 / Pin public identity and artifact digests without embedding credentials.

每个 case 包含 `case_id,task_family,variation,cohort,seed,inputs,success_rule,timeout_seconds,cold_or_warm,is_negative,routes`。三个 family 固定为 `query_verify`、`unique_row_detail`、`current_detail_downstream`；scored 正向每类至少 stable 8、unseen 6、layout 6 个 A/C 配对，B 至少 5 个。负向和 recovery 单独分类，learning/warmup 不进入正向计分；每类每路线 warmup 最多 3 个。routes 顺序保存预定 A/C 先后次序，真实调度仍须按计划执行。 / Freeze quotas, cohorts and intended order before collection.

成功规则示例：`{"all":[{"path":["result","outputs","detail"],"equals":"expected current value"}]}`。必须根据真实回执选取路径，核对任务结果；仅检查 returned 不足以证明 GUI 任务成功。failed/cancelled/blocked、未决或超时不会成为正向完成。 / Rules must verify the intended outcome in an original terminal receipt.

```powershell
python -X utf8 scripts/benchmark_learning_workflow.py --phase freeze --spec D:/fresh/spec.json --manifest D:/fresh/manifest.json
python -X utf8 scripts/benchmark_learning_workflow.py --phase baseline --manifest D:/fresh/manifest.json --data-dir D:/fresh/collection-run --recognition-source agent_current
```

冻结自动保存 app/scripts 的 Python 源文件、相关依赖声明、计分代码和本轮夹具哈希。采集前及每次调用前检查增删改和所列 artifact；目录必须全新，不能覆盖旧采数。source/model/config_digest 属于调用方声明，清单本身不证明模型实际配置或种子确实改变了界面。 / Source drift is rejected; declared identities and actual case realization still require independent evidence.

API 路线用 `--recognition-source external_api --api-profile <absolute-path>`，本地路线用 `--recognition-source local --model-directory <path>`；Agent 路线无需本地模型。委派路线另传 `--delegate-profile`。`--allow-actions` 仅打开客户端原有动作通道，不能替代独立动作确认。 / API and Agent routes do not require local weights; enabling the client action path does not grant action approval.

## 同一连接采集 / Same-connection collection

baseline 从标准输入逐行接收 JSON，逐行返回结果。先等待 ready；下面是调用格式，case 与输入必须来自清单。 / Wait for ready, then send one operation per line.

```json
{"op":"begin","case_id":"query_verify-0","route":"A"}
{"op":"call","tool":"instant_run","arguments":{"request_id":"original-read","command":{"kind":"read_text"},"wait_ms":25000,"detail":"full","images":"none"}}
{"op":"call","tool":"instant_result","arguments":{"request_id":"original-read","detail":"full","images":"none"}}
{"op":"finish","request_id":"original-read","assessment":{"wrong_clicks":0,"recovery_count":0,"safe_rejection":false,"evidence":{"observer":"reviewer","detail":"Describe actual outcome evidence here"}}}
{"op":"stop"}
```

只有原调用 pending 时才需 instant_result；不为延长等待重交原命令。异步 Agent 命令用新的查询 ID 调 `agent_command_status`，其中 command_id 仍为原执行 ID；识图交接通过原 grounding 协议续接。相同原请求再次派发被拒绝，互相矛盾的终态也被拒绝。 / Poll the original receipt and preserve original command identity; no automatic replay.

begin 到 finish 使用 perf_counter_ns 记录端到端历时，包含调用方/人工空档和采集检查开销，不能标成模型推理时间。达到冻结超时后只允许原结果/状态回读及取消类请求。应先处理未决请求再 finish；若将未决尝试结束，它记录失败并阻止在该采集会话开始下一案例，需停止并核对宿主收尾。 / Timed-out or unresolved work remains visible and cannot overlap a new attempt.

每次显式重跑产生递增 attempt_index，首次失败保留；进程中断留下未结束 begin 和已写调用意图，不自动重连或重放。工作流 start 的 inputs 必须匹配冻结 inputs；已绑定 trial 的生产计量和相关原文件按原 run_id 归档。损坏/缺失计量标 unavailable，总模型调用和 token 保持未知。 / Original production measurements are archived when available; unknown coverage remains unknown.

## 比较及限制 / Comparison and limits

```powershell
python -X utf8 scripts/benchmark_learning_workflow.py --phase compare --data-dir D:/fresh/collection-run --output D:/fresh/report/comparison.json
```

输出 `comparison.json`、同目录 `runs.jsonl` 和 `report.md`，全部拒绝覆盖。比较回读带摘要链的原 journal，重算冻结规则、首次失败及重试；计分器、结果判定器及计量依赖必须与冻结源码匹配。摘要链用于发现本地意外修改，不是对抗恶意重写的签名。历史源码变化后应使用对应冻结候选复算，不改旧 manifest 绕过检查。 / Reports are recomputed with the pinned scoring implementation and retained raw evidence.

当前仍报告 `empirical_acceptance=false`：A/B/C 策略已在原命令边界接线并经真实只读联调；完整实机任务、模型全量调用/配置、冷暖与学习开销尚未验收。负向/易混/恢复集合、跨采集会话合并和真实收益仍未完成；错误点击只覆盖夹具 open_detail 事件。 / Actual strategy wiring is present; complete physical task and empirical acceptance remain open.

此前 benchmark-cases-cli-smoke-01 只执行 discover 两次，保留为连接/清理证据。本轮 live-execution-strategy-04 使用全新可见窗口和同一真实 MCP，C 由原生规则完成只读工作流，B 由当前 Agent 检视新图并 review/continue；A 检查工作流拒绝。三条记录均不满足预设查询任务，报告保持未完成，不计为真实收益。 / Preserve transport-only history and distinguish fresh read-only route checks from scored task completion.


## Record Desk 场景驱动 / Record Desk scene driver

`scripts.learning_benchmark_cases.build_cases(seed)` 生成 60 个正向 case，可写入 freeze 的 spec.cases。每类稳定 8、未见参数 6、布局变化 6；A/C 顺序交替，前 5 个附 B。`scenario_for(case)` 重建并核对完整 case，改 seed/输入/规则不会静默变成另一个场景。当前生成器只有 scored/warm 正向集，训练、冷启动、易混、负向和恢复仍须另行实现及冻结。 / The generator realizes the predefined positive set; it does not supply missing acceptance cohorts.

训练与最终案例应使用不同的新数据；详情以种子派生的 state 哈希值生成，不可直接从传给 Agent 的编号拼接。稳定/布局组保持内容，未见组换编号与当前值。下游正确值只给验收器，Agent 必须从本轮界面读取。 / Keep training and held-out cases separate and read current values from the interface.

先启动本轮新夹具，再给 baseline 添加 --fixture-root：

```powershell
python -X utf8 scripts/run_learning_workflow_fixture.py --data-root D:/fresh/record-desk --seed fresh-training
python -X utf8 scripts/benchmark_learning_workflow.py --phase baseline --manifest D:/fresh/manifest.json --data-dir D:/fresh/collection-run --recognition-source agent_current --fixture-root D:/fresh/record-desk
```

`{"op":"next"}` 只返回下一 case/route/inputs/cohort；begin 在同一个夹具窗口加载确切场景，保留准备证据、清除旧查询/选择/字段/验证和本窗口弹窗，并产生新 reset_event_index。清空控件属于自建夹具准备，不被记成 Agent 的任务输入。准备后才开始任务计时；有夹具时首轮按冻结顺序推进，显式重试仍保留失败与递增编号。 / Reset is setup, not simulated agent execution; scored timing starts afterward.

finish 使用带 nonce、请求哈希、PID 和窗口句柄的 observe_case 原回执。查询任务要求字段和过滤结果一致，打开详情要求目标编号与当前详情一致，下游任务要求填写的当前值已验证；旧 epoch、事件缺口或 oracle 不一致报错。正确拒绝不能来自 pending。派发仍走原 MCP；控制文件不提供任务点击/填写能力。 / The observer verifies current task outcomes without dispatching input.

fixture_prepared/fixture_observed 存在本地 journal；begin/next 不返回隐藏记录或详情。比较重新计算 case_verdict，不信任提前写下的成功布尔值。错误打开其他行会累计到 wrong_clicks，但这不是全桌面错误点击覆盖。三种布局 default/search_below_rows/detail_above_rows 已检查实际控件位置；同窗口换场景与当前值变化已做离屏契约检查。 / Outcome provenance stays private to the evaluator, with explicitly limited click coverage.

采集器连接既有夹具，不拥有它的进程；停止 MCP 后，启动夹具的调用方负责按原 nonce 关闭并检查 closed.json/进程终态。本轮真实 MCP＋离屏夹具 smoke 两轮都只有 discover，结果正确为任务未完成，双方清理通过。此证据不代表物理输入、模型推理或收益已通过。 / Ownership and cleanup remain explicit; metadata-only smoke is not task success.


## 实际路线策略 / Actual route policy

begin 返回 route_policy：A 为 ordinary，B 为 steps_only，C 为 learned。A 拒绝 learning_workflow 和 target_memory；B 拒绝直接携带 target_memory 的命令。B/C 的 start 缺省策略在写入 call 意图及派发前补齐，显式冲突直接拒绝；inputs 仍须与清单相同。后续工作流操作必须引用本 attempt 已绑定的 run，返回策略不符或缺失即报错。 / The journal records the actual policy-bearing command, with no silent override of an explicit conflict.

steps_only 仍使用同一已保存程序的步骤、目标含义、输入/当次输出和分支；它禁用原生记忆匹配及规则结果判断，结果走 Agent review。需要的动态目标条件被编译为本次模型目标描述，不能在去掉定位器时丢失目标编号。它不是另存一个伪装已审核的新程序；运行时保留原版本并在票据中标明策略。 / Remove deterministic resolution and native verification while preserving task identity and truthful provenance.

同一 attempt 的原 start 可以通过 instant_result 重复回读；它只确认原运行绑定，不能用旧 ready 快照覆盖后续完成状态。不同请求或 attempt 复用同 trial 仍拒绝。界面关闭/重开、未知回执及真实输入确认沿用原合同；策略不增加执行权限。 / Original-start reads remain idempotent without state rollback or extra action authority.
