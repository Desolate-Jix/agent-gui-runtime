# Agent Review Instant

**v0.1.0-test.5 / execution-mode test release**

面向 Windows 的 MCP GUI 执行运行时：在受监督、低风险场景中读取当前原始截图，识别控件并执行有限的点击、输入、编辑、滚动和窗口操作。
A Windows MCP GUI execution runtime for supervised, low-risk work: inspect current original screenshots, recognize controls, and perform bounded input, editing, scrolling and window actions.

> **测试版，不是生产稳定版。** 快速配置会使用管理员宿主、真实鼠标/键盘输入，并关闭自动风险拦截；不要用于付款、发送、删除或最终提交。
> **Test release, not production-stable.** The quick setup uses an administrator host, real input, and disabled automatic risk interception. Never use it for payment, sending, deletion, or final submission.

## Download / 下载

- [Download test.5 ZIP / 下载](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v0.1.0-test.5/AgentReviewInstant-v0.1.0-test.5.zip)
- [Release page / 发布页](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/instant-v0.1.0-test.5)
- [Setup, official model and configuration / 安装、官方模型与配置](FRIEND_SETUP.md)
- [Agent operation guide / Agent 操作指南](AGENT_GUIDE.md)
- [Release scope / 发布范围](RELEASE_SCOPE.md)
- [Package verification / 交付核验](docs/verification/TEST5_PACKAGE_ACCEPTANCE.md)
- [Historical web/learning workbench archive / 历史网页与学习工作台归档](https://github.com/Desolate-Jix/agent-gui-runtime/tree/codex/archive-learning-workbench)（not part of this release / 不属于本发布）

这是源码包，不是独立安装器；Python 依赖、模型权重、账号和用户数据另行准备。
This is a source bundle, not a standalone installer; install Python dependencies and official model weights separately. No accounts or user data are included.

## Supported surface / 支持范围

- MCP stdio connection with **7 tools**, including `instant_run`; serial same-session commands and cleanup receipts.
- `input_sequence`: focus → type → check the focused field value → optionally press Enter; separate support for 23 editing keys. / 组合填写、读回核对与可选回车，编辑键另行支持。
- Fresh visible-image OCR, line/word boxes, original before/after images, and agent-side outcome review.
- Window discovery, launch, focus, maximize and close for session-owned windows.
- Single/right/double click with field, menu, button, word and quoted-label targeting.
- Optional explicit `observation_condition` for a known UIA text/control marker; default waits remain unchanged.
- Compact original images in receipts; this runtime does not provide full-page DOM extraction or whole-page completion claims.

## Quick start / 快速开始

1. Windows x64，Python 3.11，安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)；确认有专用低风险测试窗口。
2. 解压后按 [FRIEND_SETUP.md](FRIEND_SETUP.md) 安装依赖、下载官方 [VISTA-4B](https://huggingface.co/inclusionAI/VISTA-4B)，并生成本地 MCP 配置。
3. 将生成的 `agent-review-instant` stdio 条目加入 Agent；确认 UAC 与 `--enable-local-input` 仅在你愿意进行真实输入时启用。
4. 按 [AGENT_GUIDE.md](AGENT_GUIDE.md) 逐项执行：核对目标和原图，检查回执与 after-image，不确定结果不要重放。
5. 结束时关闭会话窗口，调用 `instant_stop`，轮询 `instant_status` 直到 `cleanup_verified=true`。

## Tested preview / 已验证预览

test.5 源码回归 **841 项通过**；同一会话的 Google 连续搜索、输入序列、条件等待、窗口恢复及 AionUi 最终独立轮次已保留在验证记录中。前期客户端中止与失败记录不隐藏，receipt-only 复核不冒充完整 GUI 覆盖。
The test.5 source regression passed **841 checks**. Same-session Google sequences, input-sequence behavior, conditional waits, window recovery and the final AionUi round are recorded in the verification reports. Earlier aborted attempts remain visible; receipt-only checks are not presented as full GUI coverage.

已验证范围不等于跨站点准确率、长期稳定性、全页面完成或所有硬件兼容性保证。先做无输入 smoke，再做明确授权的单步低风险操作；始终核对原图、目标窗口、坐标新鲜度和清理结果。
Verified scope is not a cross-site accuracy, longevity, whole-page completion, or universal hardware guarantee. Run the no-input smoke first, then only explicitly authorized low-risk single actions; always verify original images, window identity, coordinate freshness and cleanup.

## License / 许可证

[ISC License](LICENSE). Dependencies and model weights retain their own licenses and are downloaded from official sources.
