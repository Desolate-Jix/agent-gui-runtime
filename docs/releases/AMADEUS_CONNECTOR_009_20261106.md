# Windows Desktop Automation extension 0.0.9

Release date: 2026-11-06. Runtime remains **0.1.11**.

## English

The Amadeus extension now explains what it helps you do before presenting setup details: handle repetitive Windows tasks such as searching the web, editing and saving text, and navigating folders. Its proposed store display name is **Windows Desktop Automation (GUI Runtime)**.

The English and Chinese introductions describe multi-step operation, screenshot checks and returning uncertain steps to Amadeus for review. They distinguish existing controlled Runtime examples from validation of a particular Amadeus/version combination.

This is a presentation and documentation update. The package ID, HTTP MCP connection fields, permissions, provider binding, execution Skill behavior and operator-only disconnected recovery boundary are unchanged from 0.0.8. Existing `runtime_url` and `connection_token` values need no migration. Runtime is installed, configured, started and stopped separately; the connector does not supply that service. The supported external API route requires no local GPU, but sends screenshots/task information to the selected providers and may incur API fees.

- [Extension 0.0.9 download](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/amadeus-extension-v0.0.9)
- [Features and setup](../../integrations/amadeus/agent-review-instant/README.md)
- [Fixed Host preflight](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/amadeus-extension-v0.0.9/preflight.json)
- [Build and package verification](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/amadeus-extension-v0.0.9/BUILD_VERIFICATION.json)

Validation covers package format, pinned Host acceptance, curated policy, native HTTP projection, version/link consistency and the exact wheel diff from 0.0.8. No new installed GUI task, paid API benchmark or performance claim is included. Author release and store approval remain separate; 0.0.8's existing approval does not approve these new bytes. Published 0.0.8 artifacts remain unchanged.

## 简体中文

Amadeus 扩展现在先说明能帮你做什么，再介绍配置细节：将网页搜索、文本编辑与保存、文件夹导航等重复 Windows 桌面操作交给 Amadeus。拟更新的商店名称是 **Windows 桌面操作（GUI Runtime）**。

中英文介绍同步说明连续多步操作、截图核验，以及把存疑步骤交回 Amadeus 审核的能力。现有 Runtime 受控任务示例与特定 Amadeus／版本组合的验收范围分别说明。

本次仅更新展示文案和说明。插件 ID、HTTP MCP 连接字段、权限、执行 Agent 绑定、执行 Skill 行为，以及断线恢复仅限操作员的边界均与 0.0.8 相同。已有 `runtime_url` 和 `connection_token` 无需迁移。Runtime 仍需单独安装、配置、启动和停止，扩展不包含该服务。当前外部 API 路线无需本地 GPU，但会将截图和任务信息发送给所选模型服务，可能产生 API 费用。

- [扩展 0.0.9 下载](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/amadeus-extension-v0.0.9)
- [功能介绍与安装指南](../../integrations/amadeus/agent-review-instant/README.zh-CN.md)
- [固定 Host 预检](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/amadeus-extension-v0.0.9/preflight.json)
- [构建与包体核对](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/amadeus-extension-v0.0.9/BUILD_VERIFICATION.json)

验证范围包括包格式、固定 Host 接受、商店策略、原生 HTTP 配置映射、版本／链接一致性及相对 0.0.8 的实际 wheel 差异。本次没有新增安装态 GUI 任务、付费 API benchmark 或性能结论。作者发布与商店批准分开；0.0.8 的已有批准不覆盖新包字节，旧版发布产物保持不变。

## Rebuild / 复现构建

Build only the extension directory using CPython 3.12.10, setuptools 83.0.0 and wheel 0.47.0. With these build tools already installed, run from `integrations/amadeus/agent-review-instant`:

仅构建扩展目录。使用 CPython 3.12.10、setuptools 83.0.0 和 wheel 0.47.0；准备好构建工具后，在 `integrations/amadeus/agent-review-instant` 中运行：

```powershell
$env:SOURCE_DATE_EPOCH = '1793923200'
python -I -B -c "import setuptools.build_meta as b; print(b.build_wheel('dist'))"
```

For store preflight, use the catalog's pinned Host/checker environment and `tools/preflight_submission.py`. / 商店预检使用目录固定的 Host／检查环境和 `tools/preflight_submission.py`。
