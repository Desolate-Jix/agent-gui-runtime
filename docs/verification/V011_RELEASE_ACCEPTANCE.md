# v0.1.1 执行模式补丁验收 / Execution patch acceptance

2026-10-01，本报告记录 v0.1.1 发布前冻结候选的完成验收；公开资产以 [GitHub Release](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/instant-v0.1.1) 的 ZIP 与 `.sha256` 为准。/ This report records completed frozen-candidate acceptance; the release page provides the public ZIP and checksum.

基线是已发布 v0.1.0 的正式维护树（`652f464d558ccd675957b734da285e1323bfd1fc`），不是学习开发树。八个执行模块归入 `app.execution`，旧路径是同对象别名。六个完整实现移动前后字节相同；键盘请求模型、handler 与字段校验 AST 保持，仅调整归属和导入。原 owner、动作 API、七个 MCP 工具、API／Agent／local 路线继续保留。可选判断／用量合同未生产接线，不自动调用判断模型，不授予输入权限。/ The formal baseline preserves implementation identity, ownership and routes; optional judgment/usage remain unwired contracts.

| 检查 / Check | 本版实际结果 / Actual result |
| --- | --- |
| 正式源码 / Source | `pytest tests -q -p no:cacheprovider`：2086 passed，最终复测 50.29s。/ Final source rerun passed. |
| 隔离候选 / Isolated candidate | 2086 passed；294 个项目模块均在包内，未借用原工作树；739 项 manifest 哈希吻合。/ All module origins and manifest hashes verified inside the bundle. |
| 原始 STDIO / Original STDIO | 版本 0.1.1、原七工具；坏请求队列前拒绝、同连接恢复、原 ID 不重放、停止清理及重连只读回执通过，无输入或推理。/ Version/tools, rejection, receipt persistence and lifecycle pass without input/inference. |
| 本方实机 / Main live | `main-live-03`：长中英文前缀，单连接两轮双字段、点击、弹窗、429 零输入、显式恢复、读原 ID 无重放、最终清理。/ Full fresh continuous journey and cleanup pass. |
| 独立实机 / Independent live | Sol `independent-live-02` 在同冻结候选及全新窗口／数据独立重复完整流程并清理通过。/ Independent full rerun passes on the identical frozen candidate. |
| 原始证据审计 / Raw evidence audit | 每方 8 次真实 PNG HTTP 请求（含 1 次 429）、7 份点击前决策 trace、38 个图片哈希、中文状态精确匹配；MCP host、fixture 和全部自建后代退出。/ Per-route protocol, click decisions, images, UTF-8 state and complete process cleanup verified. |
| 测试服务修复 / Fixture repair | 失败 PNG 离线回放：修复前 3 failed／16 passed，修复后 19 passed；Main 独立再跑 19 passed。/ The actual fixture failure was reproduced and corrected offline before live reruns. |

源码与隔离包覆盖重叠，2086 不相加。实机冻结 manifest SHA-256：`de035a891115337258e2f589ea93820939cd4dc9fe7dbc5245ad0d06e16bf8ef`。最终交付仅刷新文档，全部非文档文件逐项与该冻结候选对比；不为文档重新构建运行时。包不附带权重、依赖环境、用户配置或本轮运行数据。/ Counts overlap; final delivery refreshes docs only and preserves every frozen non-document file.

## 首次失败保留 / Retained first attempts

- 原相关基线 168 passed；新边界迁移前 48 failed，属于新增合同尚未实现的红阶段。首次完整源码 2085 passed／1 failed：新增测试未解析正确的相对导入；修正测试后通过。/ Baseline and pre-implementation red checks are retained; the new relative-import assertion was corrected.
- 隔离候选首次 2083 passed／3 failed：新子进程测试依赖工作目录。改为隔离解释器、显式候选根与外部 cwd，逐项核对 module origin；候选全量复测 2086 passed。没有用 stub 或原工作树补漏包。/ Portable subprocess tests fixed cwd assumptions without masking delivery omissions.
- `main-live-01`：选定窗口身份不可用，0 个 GUI 输入，后续 capture 拒绝；窗口随后退出，具体环境／窗口生命周期原因未确认，原 runner 没有记录嵌套异常原因。五个只读探针未复现；没有声称产品根因已修复。测试脚本另修正了外层失败判定、Windows venv launcher 与实际 Qt PID 区分、后代清理核验。新窗口的完整重跑成功不覆盖首次失败。/ The initial identity refusal remains a failed attempt with an unconfirmed cause; no product fix is claimed.
- `independent-live-01`：City 精确填写后，回环测试 API 将长文本拆开的 City 白区域误当 Note，给出 `(320,161)`；真正 Note 在 `y=235..279`。原运行时以 `text_field_label_mismatch` 拒绝，Note 保持空白，清理完成。初次控制台乱码判断已用 UTF-8 原值纠正，文件无异常字符。/ The API fixture selected the wrong field; runtime rejection and cleanup held, and original Unicode values were correct.

这次故障的通用不变量是“模型候选不能绕过当前字段标签／身份校验”。破坏发生在测试 API 的候选生成，修复位置仅为外部 fixture：按白背景连通区域定位，文字孔洞不拆字段。生产公共层已经正确阻止误填，因此没有按单个软件放宽产品合同。离线真实 PNG、长短中文／英语、按钮与 429 协议回放防止夹具复发；Main 长文本单项及连续回归通过后，才交独立复测。安全校验、重放和最终提交权限均未放宽。/ The common label/identity invariant held. Only test-fixture candidate generation changed, with real-PNG regressions before the required main-then-independent live order.

## 范围与限制 / Scope and limits

外部 API 验收服务运行于本机回环，读取当前真实 PNG 并返回 `grounding.v1`；证明接口和公共门控流程，不证明供应商 API 连通、视觉准确率、token 费用、任意表单支持或提速。本版未重跑本地模型推理；历史结果不冒充本轮。可选判断模型、学习收益与学习工作台均未接入或验收。API／Agent 使用不要求本地权重。/ Loopback real-PNG acceptance establishes transport and execution flow, not provider/model accuracy, cost or universal coverage; local inference and learning are outside this patch's live evidence.

Escape 后测试弹窗消失，原窗口观察明确返回 unavailable 和父窗候选；调用方重新选择父窗，不把 unavailable 当任务成功或授权自动重试。最终关闭状态由 fixture 和 HWND／进程退出另行核验。/ Dialog disappearance is explicitly reported and followed by parent reselection, with separate effect and cleanup verification.

宿主与协调器仍共享部分历史 review/workflow 依赖；本补丁没有完成全部架构解耦，也不能因 `learn` 名称删除实际维护依赖。详见 [执行边界](../EXECUTION_MODULE_BOUNDARIES.md) 和 [判断／用量合同](../OPTIONAL_JUDGMENT_AND_MODEL_USAGE.md)。/ Some host/coordinator historical dependencies remain; this patch does not claim complete decoupling.

本机原始证据保存于 `D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261001-execution-patch-release-01`，包含源码／候选 XML、STDIO 回执、首次失败、修复前后 PNG 回放、双方独立新数据及交付／远端下载摘要；这些运行数据不进入公开包。/ Raw local evidence and publication verification remain outside the public bundle.
