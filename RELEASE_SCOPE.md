# v0.1.0-test.6 发布范围 / Release scope

本版是 Windows 受监督执行模式测试版，标签 `instant-v0.1.0-test.6`。学习模式不随本次发布。
This supervised execution-only test release uses `instant-v0.1.0-test.6`. Learning mode is not shipped.

## Included / 包含

- MCP stdio runtime with seven tools, including `instant_run` and bounded `input_sequence`.
- Fresh visible-image OCR, compact original-image receipts, 23 editing keys, window/session lifecycle and explicit cleanup verification.
- Conditional observation for a known UIA text/control marker; default waits and confirmation boundaries are unchanged.
- Bilingual setup and agent guidance, plus verification reports under `docs/verification/`.
- Installed desktop app discovery and launch by name/ID/path; automatic desktop target resolution. / 安装应用发现与名称/ID/路径启动，桌面目标自动解析。
- Structured model startup/cleanup diagnostics, retained-owner cleanup retry and unresolved-session start rejection. / 模型诊断、保留原 owner 的清理重试与结构化启动拒绝。
- `form_fill` through existing `instant_run` / `instant_submit`: 1–12 declared text/dropdown/checkbox/radio fields, bounded UIA state reads and per-field receipts. No new MCP tool, Excel cell editing, automatic final submission or automatic retry. / 通过既有 `instant_run` / `instant_submit` 接入 1–12 项文本／下拉／复选／单选字段、有界 UIA 状态读取及逐字段回执；不新增 MCP 工具，不做 Excel 单元格编辑，不自动提交或重试。See / 参见 [form-fill contract / 表单契约](docs/verification/EXECUTION_FORM_FILL.md).
- Learning GUI/STDIO startup entrypoints are excluded. Shared historically named runtime dependencies remain; no new lightweight-learning code or tools are included. / 排除学习 GUI/STDIO 启动入口，保留共用依赖；不带入新轻量学习代码和工具。

## Evidence and limits / 证据与边界

- Previous model-fix source regression: 923 passing checks. Candidate packaging checks and Codex/AionUi acceptance are tracked separately; historical test.5 success is not test.6 acceptance. / 上一批源码 923 项通过；本候选包检查、Codex/AionUi 实测另行记录，不沿用旧版通过结论。
- Source and frozen candidate06 each passed 1544 checks (overlapping, not additive). Codex real single/continuous forms, Maps and cleanup passed; independent AionUi form changes/repeats and Maps recovery passed on the same frozen runtime. / 源码与冻结candidate06各1544项通过；Codex真实单项／连续、同包独立复测及收尾已完成，集合不相加。
- Independent Maps focus failed once with a model point 5px outside the field; no input was dispatched, and an explicit reviewed retry succeeded. Retain this failure separately. SDK outer validation/start-order error details, model accuracy and friend-machine cleanup compatibility remain limited. Dropdown selection covers current visible options, not automatic option scrolling. / 地图首次模型点偏出5px而零输入拒绝，明确复核重试成功；保留失败。外层错误信息、模型精度及朋友机器兼容性仍有限制，下拉不自动滚动寻找选项。
- Final documentation may differ from the frozen candidate; all non-document runtime/configuration/test files must match its manifest before archiving. / 最终文档可更新，归档前所有非文档运行时／配置／测试文件必须与冻结验收包摘要一致。
- This does not claim cross-site accuracy, whole-page completion, unattended automation, long-term stability, universal hardware support, or support for payment, sending, deletion or final submission.
- Models, dependencies and user data are not shipped. Use [FRIEND_SETUP.md](FRIEND_SETUP.md), then run no-input smoke before explicitly authorizing supervised low-risk input.

The package builder is `scripts/build_instant_bundle.py`. The bundle is expected to contain the maintained source, `README.md`, `AGENT_GUIDE.md`, `FRIEND_SETUP.md`, `RELEASE_SCOPE.md`, `CHANGELOG.md`, `docs/verification/` and scripts; package validation must precede any publication claim.
