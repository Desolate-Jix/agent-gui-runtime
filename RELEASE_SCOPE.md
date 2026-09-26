# v0.1.0-test.8 发布范围 / Release scope

> v0.1.0-test.8：源码与隔离候选各 2025 项通过，本方 local、当前 Agent、实际 Luna 委派的单项及连续操作与清理通过；同候选独立 local、visual 与 cleanup 均已完成。首次失败、恢复与具体覆盖见验收记录。独立 API 仍仅预留接口，宿主禁用。 / Source and isolated candidate each passed 2025 checks. Main-agent local/current/actual-Luna single and continuous journeys passed; same-candidate independent local, visual and cleanup gates are complete. Initial failures and scope remain documented. External API remains interface-only with its host route disabled.

执行模式的有人看护测试版，不是稳定版；学习模式不发布。/ Supervised execution-mode test release, not production-stable. Learning is excluded.

**验收范围 / Acceptance scope:** 同一 candidate03 运行时经本方三来源连续测试及同候选独立 local、visual 与 cleanup 复验；最终包仅更新文档，所有非文档源文件与冻结候选逐字节一致。 / The same candidate03 runtime passed main-agent three-source journeys and independent local, visual and cleanup checks. Only documentation changed for delivery; every non-document source matches the frozen candidate byte for byte.

test.8 新增 `agent_current`、`agent_delegate` 路由和可恢复 Agent 组合命令。Agent 路线不需本地 VISTA/模型/OCR 权重；`read_text` 返回原图给 Agent，不运行本地 OCR。能力 unknown/unsupported 时停止所选路线，不隐式回退。委派模型由客户端明确选择（例如 Astra 委派给 Luna），宿主不继承 API 凭据。独立 API 仅保留 adapter/config/mock 协议检查：宿主路由禁用、不要求 key 或 live-provider，也不宣称服务商兼容。这些新增能力要求 test.8。详见 [test.8 候选验收](docs/verification/TEST8_CANDIDATE_ACCEPTANCE.md)、[Agent 组合协议](docs/development/AGENT_BATCH_PROTOCOL.md) 与 [Agent 视觉设计](docs/development/AGENT_VISION_BACKENDS_DESIGN.md)。

Test.8 adds `agent_current` and `agent_delegate` routes and resumable Agent commands. Agent routes require no local VISTA/model/OCR weights; `read_text` returns the original image for the Agent instead of running local OCR. Unknown or unsupported capability stops the selected route without implicit fallback. Delegate model selection is explicit and client-owned (for example, Astra delegates to Luna); the host does not inherit API credentials. External API support is reserved to adapter/config/mock protocol checks: host route disabled, no key or live-provider requirement, and no provider compatibility claim. These additions require test.8. See [test.8 candidate acceptance](docs/verification/TEST8_CANDIDATE_ACCEPTANCE.md), [Agent batch protocol](docs/development/AGENT_BATCH_PROTOCOL.md) and [Agent vision design](docs/development/AGENT_VISION_BACKENDS_DESIGN.md).

## Included / 包含

- MCP stdio runtime with seven tools, including `instant_run` and bounded `input_sequence`.
- Fresh visible-image OCR, compact original-image receipts, 23 editing keys, window/session lifecycle and explicit cleanup verification.
- Conditional observation for a known UIA text/control marker; default waits and confirmation boundaries are unchanged.
- Bilingual setup and agent guidance, plus verification reports under `docs/verification/`.
- Installed desktop app discovery and launch by name/ID/path; automatic desktop target resolution. / 安装应用发现与名称/ID/路径启动，桌面目标自动解析。
- Structured model startup/cleanup diagnostics, retained-owner cleanup retry and unresolved-session start rejection. / 模型诊断、保留原 owner 的清理重试与结构化启动拒绝。
- `form_fill` through existing tools: 1–32 text/date/dropdown/checkbox/radio fields with partial receipts and remaining indexes. Optional `tab_sequence` verifies each named writable text field after Tab; default `recognize_each` supports mixed fields. Unique current UIA text geometry may precede visual inference. / 通过既有工具组合填写 1–32 项，返回完成与剩余索引；可选 Tab 续填逐项核对标签，默认逐项识别支持混合字段，唯一当前文本框几何可先于视觉定位。See / 参见 [form-fill contract / 表单契约](docs/verification/EXECUTION_FORM_FILL.md).
- Shared label, popup, date and native-file-dialog fixes; JSON-quoted labels preserve embedded quotes and backslashes rather than selecting a truncated name. No new MCP tool, spreadsheet editing, automatic final submission or replay. / 通用标签、弹窗、日期及原生文件选择修复；转义标签不再截断为另一字段名。不新增 MCP 工具、电子表格编辑、自动提交或重放。
- Learning GUI/STDIO startup entrypoints are excluded. Shared historically named runtime dependencies remain; no new lightweight-learning code or tools are included. / 排除学习 GUI/STDIO 启动入口，保留共用依赖；不带入新轻量学习代码和工具。

## Evidence and limits / 证据与边界

- Source live evidence includes repeated mixed eight-field forms, named-text Tab batches, invalid-option interruption/recovery and native synthetic-file selection/cancel/reopen. See [batch acceptance](docs/verification/BATCH_FORM_LIVE_ACCEPTANCE.md). These source results are not frozen-candidate or independent acceptance. / 源码实测包括混合八项连续填写、具名 Tab 组合、非法选项中断恢复、虚构附件选择及取消重开；不能代替冻结包与独立验收。
- Source and isolated candidate03 each passed 1759 checks. Codex completed two four-field rounds and native choose/cancel/reopen/reselect; AionUi independently repeated the same frozen runtime. Earlier failures and the stale-dialog capture limitation remain in the [acceptance record](docs/verification/TEST7_CANDIDATE_ACCEPTANCE.md). / 源码与隔离候选03各1759项；Codex和AionUi同包分别完成两轮四字段与原生选择/取消/重开/重选，保留首次失败及失效窗口截图限制。
- Visual multi-select, custom date widgets, automatic option scrolling and arbitrary websites are not universally supported. Model localization may refuse a target; partial completion must be inspected rather than automatically replayed. / 视觉多选、自定义日期控件、自动滚动选项和任意网站尚非通用支持；定位可拒绝，需检查部分结果而非自动重放。
- Final documentation may differ from the frozen candidate; all non-document runtime/configuration/test files must match its manifest before archiving. / 最终文档可更新，归档前所有非文档运行时／配置／测试文件必须与冻结验收包摘要一致。
- This does not claim cross-site accuracy, whole-page completion, unattended automation, long-term stability, universal hardware support, or support for payment, sending, deletion or final submission.
- Models, dependencies and user data are not shipped. Use [FRIEND_SETUP.md](FRIEND_SETUP.md), then run no-input smoke before explicitly authorizing supervised low-risk input.

The package builder is `scripts/build_instant_bundle.py`. The bundle is expected to contain the maintained source, `README.md`, `AGENT_GUIDE.md`, `FRIEND_SETUP.md`, `RELEASE_SCOPE.md`, `CHANGELOG.md`, `docs/verification/` and scripts; package validation must precede any publication claim.
