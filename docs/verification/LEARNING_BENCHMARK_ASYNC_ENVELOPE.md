# Learning benchmark receipt boundaries / 学习采集回执边界

This source-only slice belongs to the learning mainline. Stable v0.1.1 is separate. / 本切片仅属学习源码主线，正式v0.1.1独立不变。

## Original asynchronous envelope / 原异步回执

1. **Failure / 现象：** source-v4/live-05 的 Find 输入原worker已completed、action_executed=true；collector却拒绝读取最初的returned/running回执并退出。C仅step1核验完成，无finish。原0行/1unfinished和93.068秒观察区间保留。
2. **Invariant / 共同约束：** 外层只读请求returned不等于内层输入任务终态；合法原异步回执必须可取回，但不能把running当完成。 / Read completion and action completion are distinct.
3. **Fix / 修复位置：** `scripts/benchmark_learning_workflow.py::_internal_result_source` 只读准入识别原`agent_command.v1`、确切command_id和允许状态，保留attempt/run/step/ticket/command/SHA绑定。原`_terminal`、`_request_terminal`、`_succeeded`未改，随后用原agent_command_status结算真正终态。
4. **Why common / 非应用专补：** 这是原MCP异步输入回执的一般边界，适用其他原生应用或网站任务；不添加Record Desk坐标、答案或重放。 / The fix belongs to shared receipt collection, not an application adapter.
5. **Regression / 回归：** Main运行五份相关manifest/scoring/collection/provenance/case测试，215 passed/10.22s。RED 5 failed/3 passed保留；窄异步准入及拒绝集16 passed。真实旧Find原文件通过未改InstantSession.result只读投影和新准入，原SHA未变；source-v5/live-06完整C六步和原finish成功。
6. **Safety / 安全影响：** 只取原结果，不派发新输入，不改坐标/窗口/危险动作检查；未知、跨轮、身份/命令/哈希漂移仍拒绝。不能凭running重放输入或填写未知值。 / No input authority or terminal guard is relaxed.

Evidence / 证据根：`D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261002-learning-mainline-01`。

- `p2/live-05/main-async-result-audit.json`、原journal及stderr。
- `p2/internal-agent-result-wiring/actual.diff`、原RED/GREEN日志、`main-command.json`、`main-final.xml`。
- `main-original-public-envelope.json`、`main-bound-public-envelope-check.json`。
- `p2/live-06/mailbox/replies/main-finish-c01.stdout`、原session终态和PNG；这只证明声明范围的任务效果，来源覆盖限制见下段。

## Provenance repair verified; new live checkpoint open / 来源修复已核验，新实机检查点开放

1. **Failure / 现象：** v5首A/C原任务均first_attempt_success=true，A328.390326秒、C564.687463秒。但C coverage=partial，errors=[benchmark_evidence_reference_invalid]，steps=[]；不宣称完整覆盖资格。
2. **Invariant / 共同约束：** 同一个原session内文件只收录一次；原Windows引用与标准证据引用必须指向相同原字节，保留原回执不变。 / Original path aliases must not duplicate snapshots or alter their contents.
3. **Location / 定位：** collector `_provenance` 把自动`responses/EID.json`和规则`responses\EID.json`分别加入，Windows解析同文件后生成两个同POSIX ref；`benchmark_provenance._files`的唯一性检查正确拒绝。step1/5各一对，文本/SHA相同，60份原快照文件哈希和根目录检查通过。共同collector已在session根检查后按真实path去重，只读lookup规范化反斜杠；原观察/envelope逐字比较、SHA、唯一冲突和越界检查保留。
4. **Why common / 非应用专补：** 这是Windows原路径到跨平台证据引用的序列化边界，不依赖某个窗口、标签或任务答案。
5. **Regression / 回归：** 路径窄RED2 failed/4 passed保留，修复后GREEN6 passed；Main首次组合262 passed/2 failed发生于图片fixture的非声明start参数，修正fixture后最终七模块266 passed/10.67s。真实原只读复查58个唯一快照、原图SHA及rule1/5无错误，coverage=complete；Agent动作核验仍导致全规则资格false。旧journal和原分未重写。source-v6另冻849文件、尚未实机，不拼接v5成绩。 / Related and actual-file checks pass without rescoring; a new frozen candidate awaits live sampling.
6. **Safety / 安全影响：** 不修改输入执行链；唯一性、哈希和session根约束保留。部分Agent核验仍不得改称全规则核验。 / Preserve evidence constraints and truthful judgment coverage.

原证据：`p2/live-06/measurement-C01-audit.json`、`evidence/collection/journal.jsonl`。最终C completed外回执在begin后220.381735秒，随后到finish344.305728秒；主会话核验/汇报/compaction未扣除，KeyError单独耗时未知。当前模型总调用/token仍未知，三项收益未证明；本先导formal credit=0。

## Caller errors / 调用方错误

v4/live-04中Main指导finish多传attempt_id，原CLI TypeError退出；A现场成功但原0行/1unfinished，318.975秒仅为begin到清理观察区间，非最终finish耗时。旧参数、错误和正常清理原样保留。现Main独占finish，只传request_id/assessment，并在最终原PNG和终态核对后立即结算。

v5首C结算前Main只读核验错误使用嵌套`outputs['step-4']['current_detail']`；原结构是平键`step-4.current_detail`。KeyError发生于API提交前，随后更正；没有输入重放、分数重写或扣除耗时。 / Both caller errors stay distinct from runtime faults and successful reruns.


## Original action goal / 原动作目标

1. **Failure / 现象：** 路径修复后的真实旧只读检查在step3仍报benchmark_current_memory_plan_unverified。合法基本goal被拒，而错误使用视觉hint的测试反而放行。
2. **Invariant / 共同约束：** matched memory plan绑定原动作基本goal；带当前行条件的grounding_goal仅供miss/ambiguous/unsupported视觉路径，不替代动作语义。
3. **Fix / 修复位置：** benchmark_provenance._target仅一行比较对象改为step.action.field_goal/goal；原command已按expected精确验证。生产者runtime_target:31–33/43/60、MemoryGroundingTarget.goal/plan、agent_command_jobs:83–89独立核对；runtime未修改。
4. **Why common / 非应用专补：** 所有动态参数行定位及memory匹配均遵循相同基本语义，不绑定测试记录或坐标。
5. **Regression / 回归：** 真实shape正例与错误hint反例RED2 failed、GREEN及原拒绝集6 passed；Main组合266 passed，真实六步只读复查5个memory_execution_hit、rule1/5及两图SHA通过，所有原件不变。memory-goal-causality.json和main-actual-readonly-check.json记录因果及SHA。
6. **Safety / 安全影响：** 不改执行权限；command/reference/window/context/capture/SHA/freshness检查保持，错误提示不能冒充基本goal；未知输入不改称完成。

原版本独立回放：p2/live-06/original-comparison/comparison.json和main-original-replay-audit.json在原12个依赖及manifest620源文件门控下复算，原partial不变。原四个进程退出、pending_ids/workers=[]、sampler_stopped=true、cleanup_verified=true，见main-cleanup-witness.json。Main只读辅助脚本字段/会话绑定错误单列，未改原数据或扣除耗时。

2026-10-02 live-07收尾 / Closed diagnostic update:

2026-10-02 live-07最新：首对与四例C原来源覆盖均通过，四对原结算和cleanup通过；C04本地输出格式化误把terminal_receipt=None当dict，原status4文件已成功返回，reread恢复，无派发重放，recovery_count=1、first_attempt_success=false保留。Main只读投影误用row键的KeyError没有改原件；后续按finish真实字段处理。 / Read-only caller errors are retained separately from runtime inputs and original scores.

审计隔离事件：Failure=执行A子会话在A04以后打印原journal payload并暴露records；Invariant=普通执行者不得消费评分快照；Fix location=Main委派契约/只读白名单投影，非产品fallback；Why not app-only=所有基准的执行/评分角色均应分开；Regression evidence=原事件记录、A05未begin、missing4与原cleanup，不伪称已有自动防读测试；Safety=无新增点击/权限或评分改写，剩余采样已停止。 / The original exposure, stopped future sampling and cleanup are the evidence; there is no new automatic access-control test or runtime bypass.
