# Amadeus 适配包更新策略（2026-10-24，只读调研）

后续：用户已授权实施，当前上游工作树改动与检查见
[更新实现记录](AMADEUS_UPDATE_IMPLEMENTATION.md)。下文是实施前的历史调研，不代表
已运行的 Amadeus 或已发布扩展已经重新加载这些变更。

## 结论

采用“稳定的 HTTP 连接扩展 + 独立更新的 Runtime + 运行时能力核对”。Runtime
正常修复和兼容性新增不需要连带发布 Amadeus wheel；只有扩展连接配置、权限披露、
Skill 调用协议或 Host 兼容要求实际变化时，才发布新的扩展版本。

这一解耦已有架构基础，不要求先修改 Amadeus 上游。商店的自动检查和无人值守升级
则不是现成功能；新版本仍须独立审核，不能用自动构建代替准入。

本文未改变源码、服务、Amadeus 安装或商店配置，未发布、提交、调用模型或操作桌面。
它是一份待实施方案，不能作为新 Agent 模式已安装、已通过 HTTP 或实机验收的证明。

## 核查基线

| 对象 | 2026-10-24 核查结果 |
| --- | --- |
| Amadeus 本地 `E:/amadeus` | HEAD `9547f39ad518134ce4594f5a52a92c8a61629f45`；GitHub main 同一提交，无需拉取；现有未跟踪文件保留 |
| Amadeus 应用版本 | 源码目标 `0.17.1-alpha.1`；应用版本不等于 Host API 版本，也不证明某个已运行进程加载了该源码 |
| Amadeus-Extensions main | `c4f533867b6774261fd41ea678f9ee7be8471536` |
| 官方商店目录 | `catalog/v1/index.json` 仍为 `sequence=0`、`entries=[]`；尚无已准入包 |
| 已发布 Runtime / 扩展 | Runtime `0.1.6` / 扩展 `0.0.4`，HTTP loopback 已存在；扩展只有 review-candidates 证据，未准入商店 |
| 新 current-agent 封装 | 未发布源码；`CurrentAgentClient` / JSONL CLI 的基本点击工作流，不是已接入 HTTP 扩展的新工具集；暂不支持管理员模式 |

Amadeus 运行时协议来源另固定于 `server/extensions/protocol-source.json`：manifest
规则来自 Extensions `b444dd8b452a914f68cdba439cc3e79a9a1e53cf`，SDK 为 `0.1.0`。
商店 checker 还有独立 pin。协议来源、商店最新 main、Amadeus 应用版本和实际
加载版本必须分别记录，不能因为商店更新就假设 Host 自动升级了协议。

## 现有扩展为何可以保持不变

`0.0.4` 的 `runtime.kind=none`，只有 HTTP MCP 声明及 Skill，没有 Runtime 二进制、
Python 启动器、模型权重或第三方依赖。它配置稳定的 `runtime_url` 与 secret
`connection_token`，默认地址 `http://127.0.0.1:17665/mcp`。Runtime 由操作员独立
安装、启动和停止；扩展不能安装、启动或升级它。

当前兼容约束如下：

- `engines.amadeus_host_api=">=0.1,<0.2"`；Host 当前 `HOST_API="0.1"`，这不是
  Amadeus `0.17.x` 应用版本范围。
- 平台 `win32`；wheel 的 `Requires-Python` 另为 `>=3.12,<3.13`。资源包不因此
  运行 Python 代码，但商店兼容检查仍会使用 wheel Python 约束。
- MCP contract `amadeus.mcp-server/v0` 和 Skill contract `amadeus.skill/v0`。
- 没有 Runtime patch 版本锁，也没有“Runtime 每一版必须发布一个扩展”的协议。

首次接入新 Agent 工作流可能需要更新一次 Skill，之后把易变的工具参数与状态说明
交回 Runtime 的实际 tools/schema/响应。保持扩展中的稳定规则：同一连接、单输入
所有者、原请求 ID、只读 pending、真实证据、显式 review/continue 和确认收尾。
不为每个 Runtime 补丁重写 Skill 的固定版本宣传文案。

不能往现有 manifest 随意添加 `runtime_min_version` 等字段：现有 schema 拒绝
未声明字段。Runtime 合同核对应放在 Runtime 状态/工具响应，发布版本的兼容范围
放在说明及构建验证中；如果确实需要新的 manifest 字段，应走上游协议变更。

## 商店到底更新什么

当前 Amadeus `docs/extension_catalog.md` 明确描述手动更新：

1. Installed 页读取本地状态，不做启动联网检查；打开 Browse 或显式检查才刷新目录。
2. 推荐高于已安装版本、兼容、未撤回且未封禁的 `X.Y.Z` 候选。
3. 更新与安装走同一条下载、大小/摘要核对、原生确认、准备、持久化流程；安装前
   必须重新读取官方目录，显示缓存不能授权安装。
4. MCP/Skill 保存后须重启 backend；Skill 的变更还须新 Work。保存版本与当前
   已加载版本分别显示。没有自动更新或自动回滚。

Extensions 的 `catalog/SUBMISSION.md` 要求每个新版本重新审核实际 wheel
SHA-256，并由维护者完成独立 publication 流程和线上字节验证。任何变化后的 wheel
必须用新版本，不能替换 `0.0.4` 字节，也不能用 mutable `latest` wheel URL。
现有 `review-candidates/.../0.0.4`、preflight PASS 或本地验收均不等于商店批准。

因此应分别谈：自动生成候选、自动检查更新、下载/安装更新、独立商店准入。
前两项可以减少人工劳动，均不能自动产生后两项的权限或审核结论。

## 当前 Agent 与图像链路

Amadeus Main Chat 不直接获得 MCP 工具和安装的 Skill；可承载本模式的是绑定
Runtime MCP 的 Pi Work Agent，或另经验证的兼容 Codex/ACP Provider。不能把
Amadeus 主聊天的人格模型等同于能调用 Runtime 的执行 Agent。

当前 Pi 依赖 `@earendil-works/pi-coding-agent` 与 `pi-mcp` `1.2.0`。Host 使用原生
`createMcpExtension` / `StreamableHttpTransport`；MCP `ImageContent` 有传入模型的
实现。但原生工具结果图像默认可能缩放/转换，模型元数据也参与图片是否发送的判断。
Amadeus 已有两条精确 DeepSeek 旧别名的 metadata 兼容逻辑；它不是任意模型的
图像支持证明。HTTP 成功、MCP 出图、model 名称或一个声明都不能证明模型真正读图。

Pi 原生已有 `images.autoResize` 设置（默认 true，文档上限 2000×2000）；需要
原尺寸时优先评估该受支持设置，无须先 patch 上游或缓存。它关闭自动缩放，并不
保证所有格式都保持原字节，也不能突破模型服务的大小限制；应对 Runtime PNG
实测实际模型请求里的尺寸和摘要，再声明原图传输。此次未修改该设置。

Runtime 原有 HTTP 入口已接受底层 `agent_current` 识别来源和
`vision_capabilities`，但新 CLI 封装中的 prepare/resolve/continue/verify 状态管理
并未因此自动成为 HTTP 工具。`0.0.4` Skill 仍主要描述原 external-api/Decision
及 Main review 合同；它没有完整描述新的受管基本点击工作流。

接通时应复用同一 Runtime 会话与原派发路径，把需要的受管操作暴露给 HTTP，或
明确使用并验证原底层合同；不再引入第二个输入执行者。新封装的验证、动作范围和
Decision 隔离不能被旧底层功能的存在替代证明，管理员模式仍不在新封装支持范围。
尤其要验证 Pi 实际交付的图片尺寸及坐标换算：Runtime 的点位始终基于原 capture
坐标；缩放后的图片不是与原 PNG 字节相同的证据。

## 最小实施顺序

1. **一次适配新模式。** Runtime 明确 HTTP 新模式入口及支持的操作范围；补一个
   兼容原 API 路线的新 Skill 版本，按运行中的来源和实际合同选择流程，不能替用户
   更改来源、声明支持未知图像能力或关闭门禁。仅 HTTP/Skill 变更需要新 wheel。
2. **补运行时合同自述。** 优先扩展现有只读 `instant_status`，返回独立的 build
   identity、实际识别来源、协议/能力版本以及本入口暴露的操作；现有 MCP initialize
   `serverInfo.version` 只作为服务版本。字段和命名以实施后的实际 schema 为准，本文
   不声明已有一个不存在的 `capabilities` API。未知合同只阻塞依赖动作，保留状态读取。
3. **保持连接稳定。** URL/token/扩展 ID 不随 Runtime patch 改变。升级只在无活动
   输入、原回执已结算且清理确认的会话边界进行；旧 Work/原 MCP 连接不能被热更新
   直接接管，也不能为了重连重发输入。升级完成后新连接重新读版本和合同。
4. **自动兼容检查，按内容发布扩展。** Runtime 发布流水线对保留的 wheel/Skill
   跑合成 HTTP 合同检查，检查 initialize、tools/schema、图像返回、旧参数、pending
   原 ID、取消/未知输入和清理；不产生真实输入或付费模型调用。若扩展资源字节未变，
   保留原扩展版本与固定 URL，并记录新 Runtime 的检查结果；变了才构建新版本。
5. **实际需要新扩展才送审。** 自动生成 wheel、摘要、diff、preflight 和候选说明，
   保留一个人工审核/发布流程。自动化可准备审查材料，不能填写虚构 reviewer、
   自动声称准入或绕过 Host 安装确认。

第 2、4 项是建议新增的 Runtime 工作，并非本次已实现功能。现源码的 status 主要
返回识别来源、宿主/目标/pending/清理等状态，不能把包版本或静态声明等同于真实
加载能力。发现 tools 只是 schema 兼容证据；有图像的真实 Agent 链路仍须独立验收。

## 哪些需求需要改上游

| 需求 | 归属与最小做法 |
| --- | --- |
| Runtime 修复后不用同步发扩展 | 无须改 Amadeus；稳定 HTTP 合同，按扩展实际内容决定版本 |
| 新 Agent 模式接入现有 HTTP MCP | 主要改 Runtime 入口及扩展 Skill；当前 Host 已有 HTTP 与 ImageContent 通路，仍须验收真实图像和坐标 |
| 自动检测并提示商店新版本 | 需 Amadeus 上游增加有明确设置/频率的检查调度；复用现有 refresh/recommendedUpdate 和安全存储 |
| 自动更新已安装扩展 | 需 Amadeus 上游显式产品/授权设计，维持原生确认、审核摘要、secret/config、backend/new-Work 边界；当前不支持 |
| Runtime 安装包自己检查/升级 | Runtime 安装/发布系统负责，独立于商店；当前未发现一个可直接启用的维护型自动更新器 |
| Main Chat 直接操作 MCP | 涉及 Amadeus 权限架构变更；不是实现本方案的必要条件 |

首选先做解耦与自动兼容检查。只要 wheel 不变，就没有需要用户频繁手动同步的
适配包；额外建设商店自动升级不能解决 Runtime 本体的独立升级。

## 证据与检查范围

- [Amadeus 核查提交](https://github.com/Code-Amadeus/Amadeus/commit/9547f39ad518134ce4594f5a52a92c8a61629f45)
- [Host profile 与生命周期](https://github.com/Code-Amadeus/Amadeus/blob/9547f39ad518134ce4594f5a52a92c8a61629f45/docs/extension_host_profile_v0.1.md)
- [商店手动更新和联网边界](https://github.com/Code-Amadeus/Amadeus/blob/9547f39ad518134ce4594f5a52a92c8a61629f45/docs/extension_catalog.md)
- [商店原生安装路径](https://github.com/Code-Amadeus/Amadeus/blob/9547f39ad518134ce4594f5a52a92c8a61629f45/electron/src/main/extensionCatalog.ts)
- [推荐版本选择](https://github.com/Code-Amadeus/Amadeus/blob/9547f39ad518134ce4594f5a52a92c8a61629f45/electron/src/renderer/components/extensionCatalogModel.ts)
- [Host 兼容检查](https://github.com/Code-Amadeus/Amadeus/blob/9547f39ad518134ce4594f5a52a92c8a61629f45/server/extensions/package.py) 与 [目录兼容检查](https://github.com/Code-Amadeus/Amadeus/blob/9547f39ad518134ce4594f5a52a92c8a61629f45/server/extensions/catalog.py)
- [Pi 图像 metadata 边界](https://github.com/Code-Amadeus/Amadeus/blob/9547f39ad518134ce4594f5a52a92c8a61629f45/docs/pi-rpc-provider.md) 与 [Host MCP 投影](https://github.com/Code-Amadeus/Amadeus/blob/9547f39ad518134ce4594f5a52a92c8a61629f45/agent_host/pi_runtime/mcp.ts)
- [Extensions 官方目录快照](https://github.com/Code-Amadeus/Amadeus-Extensions/blob/c4f533867b6774261fd41ea678f9ee7be8471536/catalog/v1/index.json)
- [投稿、审核与不可变制品](https://github.com/Code-Amadeus/Amadeus-Extensions/blob/c4f533867b6774261fd41ea678f9ee7be8471536/catalog/SUBMISSION.md)
- [0.0.4 待审证据](https://github.com/Code-Amadeus/Amadeus-Extensions/blob/c4f533867b6774261fd41ea678f9ee7be8471536/catalog/review-candidates/io.github.desolate-jix.gui-runtime/0.0.4/README.md)
- 本仓库：[已发布扩展](../../integrations/amadeus/agent-review-instant/README.md)、[current-agent 未发布范围](CURRENT_AGENT_MODE.zh-CN.md)、[HTTP 入口](../../scripts/start_instant_mcp_http.py)、[MCP 服务](../../app/instant_mcp.py)、[静态能力门禁](../../app/vision/recognition_source.py)。

已读本地代码、文档、已安装 Pi 1.2.0 的 content/image-process 实现，并用官方 GitHub
只读 API 核对两个仓库当前 main。此次未运行应用、测试、付费 API、桌面动作或安装
升级；对产品流程的结论是源码与规范证据，未声称重新实机复测。
