# test.5 delivery verification / test.5 交付核验

## Checks / 检查

- Source regression: **841 passed in 27.02s**. / 源码回归通过。
- Independent bundle, isolated Python (-I): **841 passed in 28.25s**. / 独立交付目录、隔离解释器通过。
- Real input-handler dependency imports, schema validation and module-root checks passed outside the working tree. These checks dispatch no input. / 输入入口依赖闭合通过，不冒充实机输入。
- Package MCP stdio: server version 0.1.0-test.5, seven tools, invalid-field recovery on the same host/connection, discovery, original-ID replay receipts, stopped-host rejection and reconnect retrieval passed. cleanup_verified=true. No screenshots, GUI input or model inference in this packaging smoke. / 包内真实协议及清理通过，本轮打包 smoke 不操作桌面、不运行模型。
- Build regression covers maintained application_profiles/seek dependencies, exact retired paths, required files, manifest-only ZIP contents and mutation/overwrite rejection. / 打包回归覆盖依赖、精确排除及清单校验。

## Live evidence / 实机证据

The execution implementation is the previously validated source at 588da2afb41fed78782c6dd729e9a3d296eb2ce2; only the public MCP version string changed in production code for this release. See [independent acceptance](EXECUTION_AIONUI_ACCEPTANCE_20260921.md) and [continuous browser retest](EXECUTION_BROWSER_RETEST_20260921.md).
执行实现沿用该已验收提交，生产代码只变更 MCP 对外版本字符串。上述记录包含 Codex 连续实测、AionUi 独立实测与回执补丁复核；没有声称 AionUi 又对新 ZIP 做了一轮完整实机测试。

Known limitation: interrupted-client window ownership recovery remains incomplete. Conditional markers do not prove whole-page readiness or task success. This is a supervised test release, not a stable or unattended release.
已知限制：客户端中断后的窗口归属恢复尚不完整；条件标志不证明整页加载或任务成功。本版本为受监督测试版。

## Repository cleanup / 仓库整理

main exposes execution mode. Historical learning/web workbench source is retained on codex/archive-learning-workbench. All 19 former branch tips were checked against preserved tags before removing branch refs; see [archive index](../history/BRANCH_ARCHIVE.md). Local uncommitted work and user data were not deleted.
主线展示执行模式，旧工作台独立归档。19 个原分支先核验标签再删除分支引用；没有删除本机未提交源码或用户数据。
