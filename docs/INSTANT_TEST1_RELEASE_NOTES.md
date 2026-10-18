# v0.1.0-test.1 — 首个公开测试版 / First public test release

Agent Review Instant 的首个对外即时模式测试包，基于内部 preview.6 的已核验源码。仅更改公开版本标识、交付命名和文档，保留已测试的执行链。

The first public instant-mode test bundle, based on the verified internal preview.6 source. Public branding, version identifiers and documentation change; the tested execution implementation is retained.

## 包含 / Included
- 六个 MCP stdio 工具、管理员宿主桥、窗口发现与启动、识别点击、文本、Enter、滚动。 / Six MCP tools, administrator host bridge, discovery/launch, recognition clicks, text, Enter and scroll.
- 原图与 SHA-256、Agent 判断结果、即时与等待后帧区分、不自动重放、停止清理。 / Original images and hashes, Agent judgement, explicit frame stages, no automatic replay and cleanup.
- 模型下载、安装和配置脚本；模型与依赖外置，不重复打包。 / Model download, installation and configuration scripts; weights and dependencies are external.

## 证据范围 / Evidence boundary
- 内部候选通过 254 项本地回归，覆盖验证语义、帧归属、部分文字、缺失后图、输入路由、MCP 和管理员桥隔离测试。 / 254 local candidate regressions covered receipt semantics, frame provenance, partial text, missing evidence, input routes, MCP and isolated administrator bridge tests.
- 真实 MCP 无输入检查覆盖六工具、宿主启动、窗口发现、同 ID 回执、重连和清理。包清单、文件哈希与 ZIP 完整性单独检查。 / Real no-input MCP checks cover discovery, host lifecycle, replay protection, reconnect and cleanup; bundle manifests/hashes are checked separately.
- 外部 Agent 曾在同机前版进行可逆导航测试。这不等于当前公开包已通过所有软件、跨机器安装或小目标准确率验收。 / Earlier external-agent navigation tests on one machine do not certify all applications, cross-machine installation or small-target accuracy.

## 已知限制 / Known limitations

测试版不是稳定版、完整审核工作台或学习模式。需要 Windows x64、Python 3.11、较大的模型与运行环境；冷启动较慢。模型和不完整 OCR 可能定位不准，Agent 必须看图判断。快捷设置开启管理员宿主并关闭自动风险拦截，仅在本人看护下测试低风险操作；系统 UAC 与窗口/坐标完整性检查仍保留。

This is not a stable release, full review workbench or learning-mode product. Windows x64, Python 3.11 and substantial model/environment storage are required. Cold startup is slow; model/OCR targeting can be inaccurate. Supervise low-risk operations and inspect images. Quick setup uses an elevated host with automatic risk interception disabled; UAC and window/coordinate integrity checks remain.

分支 `codex/release-instant-test-1` 用于本测试版源码快照；标签 `instant-v0.1.0-test.1` 固定发布内容。完整产品开发仍在原开发分支，发布分支不混入模型、私人历史或未完成工作树改动。

Branch `codex/release-instant-test-1` is this distribution snapshot; tag `instant-v0.1.0-test.1` pins the release. Full-product development remains separate. No models, private history or unrelated working-tree changes are included in the release tree.
