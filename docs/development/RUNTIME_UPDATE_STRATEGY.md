# Runtime 更新与 HTTP 兼容策略（提案）

后续：已实施并纳入 [Runtime 0.1.8 发布](../releases/EXECUTION_018_20261024.md)，使用说明见
[确认后更新](../RUNTIME_UPDATES.zh-CN.md)。下文保留最初只读提案及其历史核查
基线，不代表所有建议都已实现；0.1.7 及更早安装包没有更新器，须先手动安装 0.1.8。

2026-10-24。状态：只读审查后的设计建议；**没有实现或启用自动更新**。审查开始时的已发布基线为 Runtime 0.1.6 / Amadeus 扩展 0.0.4；当前 Agent 适配器仍以自己的安装态验收和发布记录为准。本方案不把新更新器混入本轮 Agent 模式验收。

## 建议

保留独立 Runtime 和轻量 HTTP 扩展。先完成当前 Agent 模式的安装态实测与发布，再单独实现“自动检查 → 可选预下载 → 用户明确应用 → 安全切换 → 失败回退”。普通 Runtime 修复不要求重新导入相同 Amadeus wheel；只在扩展自己的 Skill、贡献声明或 Host 契约发生变化时更新扩展。

HTTP 能力发现只解决兼容判断，不能让旧 Runtime 获得尚未安装的新代码。生产代码或依赖发生变化仍需更新 Runtime；不从 HTTP 响应下载并执行任意补丁，不在活动 Python 进程内替换模块。

## 已有基础与缺口

| 项目 | 当前证据 | 对更新的含义 |
| --- | --- | --- |
| Runtime 版本 | `app/instant_mcp.py` 的 `INSTANT_VERSION=0.1.6`；构建检查核对 MCP 与安装描述符版本 | 可以显示安装版与运行版；不能由版本号推断所有业务能力 |
| HTTP | `app/instant_mcp_http.py` 只接受 `/mcp`，127.0.0.1、独立 Bearer secret、Host/Origin 检查、stateful initialize、单 owner | 继续复用此门禁；目前没有 `/health`、业务能力或更新接口 |
| 协议发现 | 原生 MCP initialize 和 `tools/list`；业务合同另在工具 schema/返回值中 | 增加明确业务能力投影，避免按精确发行版配对 |
| 安装描述符 | `execution-installation.json` 为 `execution_installation.v1`，文件摘要、`workflow_queue.v1`，能力仍有历史 `learning_workflow.v1` | 这是既有安装/执行合同，不可直接当新 Agent 能力目录，也不能因含 learning 名称就删除 |
| 安装器 | `scripts/build_component_installer.py` + `packaging/component_installer.cs`；固定 product ID，用户级覆盖升级，校验嵌入清单/载荷/旧文件所有权，拒绝覆盖未知或已修改文件 | 可以复用文件完整性和数据保留逻辑；不是完整的自动更新器 |
| 回滚 | 安装失败时恢复本次修改的文件及集成状态；回滚失败保留备份并报错 | 没有断电恢复日志，也没有“安装成功但新版本启动失败”后的持久回退槽 |
| 运行检测 | `RunningGuard` 检查进程映像位于安装根；`Exclusive` 检查文件占用 | 外部 Python 启动安装根里的 `.py` 时，映像路径检查可能遗漏；Python 文件未占用也不证明任务闲置 |
| 会话门禁 | `InstantSession` 的 `owner.lock` 按 data root 加锁；HTTP 按 daemon 保持 owner；DELETE 要求无 in-flight POST、host 退出、pending 清空和 cleanup_verified | 可作为单会话依据；不足以覆盖同一安装的其他 data root、stdio、直接 CLI 或启动竞争 |
| 发行信任 | 安装器 `signed=False`；安装描述符 `publisher_verified=False`；当前发布附 SHA-256 | 摘要证明字节一致性，不独立证明发布者身份；不能据此自动执行远端文件 |
| 环境 | `setup_instant.ps1` 将 `.venv-agent`、`.python`、缓存放在安装根；API/Agent 3.11/3.12，新增默认 3.12；哈希锁和 binary-only 安装 | 更新必须管理环境兼容，不能只覆盖源码后就宣称完成，也不能更新活动环境 |
| Amadeus 扩展 | 0.0.4 为 `runtime.kind=none`，HTTP MCP 声明 + Skill，Host API 范围 `>=0.1,<0.2` | 扩展不含 Runtime、Python 或模型；不应为更新 Runtime 而恢复外部可执行文件启动器 |

源码范围：上表所列文件及 `app/core/instant_attachment_transport.py`、`scripts/build_execution_component.py`、`scripts/check_execution_component.py`、`tests/test_component_installer.py`。本次仅审查源码与已有记录，没有运行安装/桌面测试。安装器现有测试覆盖升级、占用文件、篡改及集成回滚；这些测试的存在不等于本轮重新通过。

## 按业务能力兼容，分别发布

建议增加只读 MCP `instant_capabilities`（拟议名称），由维护中的 stdio/HTTP 共用工具工厂提供，通过现有鉴权和同一 Work 的原连接读取。可在 initialize 的标准 `experimental` 扩展中给出简短索引，但不要把业务能力冒充 MCP 标准能力。

拟议 `runtime_capabilities.v1` 至少包含：

- `runtime_version`、不可变构建标识；发行版本用于诊断和已知缺陷阻止列表。
- 精确业务合同：如实际支持的 `agent_command.v1`、`grounding.v1`、`task_plan.v2`、审核包 schema。
- 当前配置可用的识别源、证据传输和调用限制；区分“编译支持”与“当前配置可用”。
- 输入启用状态只做报告，不能通过能力发现自动打开。能力存在也不替代目标、证据、审核或授权。

客户端先读取真实 `tools/list`/schema 和能力，再选择兼容路径。可选新字段缺失时降级；缺少必需合同或合同 major 不兼容时只阻止依赖的功能并显示升级入口。不要要求 `runtime_version == 某一版本`，也不要解析工具说明文字猜能力。旧 0.1.6 无此工具时保留经过验证的原工具路径，将新功能标为未知/不可用，不为检测能力提交真实输入。

兼容合同不变时，Runtime 和扩展可以有不同版本号；一次修复不必重发 wheel。若新功能需要更新 Skill 才能正确调用，仍需发布新的 wheel 或由 Host 支持的受审分发流程更新；HTTP 不会远程替换已安装 Skill。

当前 HTTP 明确只接受 SDK 的握手协议版本；即便 SDK 上游新增 sessionless 模式，本项目也不能据此丢掉 owner/清理语义。MCP 协议版本、业务合同版本、Runtime 版本、扩展版本、Amadeus Host API 版本分别判断。[官方 MCP 握手合同](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle)、[Python SDK 版本迁移说明](https://py.sdk.modelcontextprotocol.io/migration/)。

能力读取不能为了诊断另建连接抢占 owner。当前未启动过 host 的 session 不会自然产生 `cleanup_verified=true`；若以后支持独立诊断连接，需单独设计并验证“从未创建 Runtime host”的安全释放，不能强迫先启动输入宿主再清理。

## 更新状态机与可信来源

第一阶段可做“检查更新、展示版本差异和固定发布入口”，失败或离线只影响检查，不影响已安装版本。检查不得自动触发输入、安装、环境同步或后台重启。自动检查的频率/关闭入口和可选预下载策略独立配置，不以 Agent 每次调用为触发点。

拟议状态为 `idle → checking → available → downloading → staged → awaiting_apply → applying → verifying → ready`；错误进入 `failed` 或 `rolled_back`。`available`、`staged` 与 `ready` 是不同事实。任务执行中可以完成只读检查和隔离下载，不能进入 `applying`。

发布侧生成机器可读更新目标，至少绑定渠道、递增元数据序号、发行版/构建标识、完整目标文件名、字节数/SHA-256、平台/架构、业务合同、依赖锁摘要、数据 schema 兼容范围和发行说明。稳定渠道排除 draft/prerelease；同版本不同字节不静默替换。不能只比较 `latest` 或按字符串排序版本。

下载源固定为本项目受信发布源，使用 HTTPS；校验响应大小、超时、重定向与目标摘要。不得接受服务响应给出的任意 shell 命令、可执行文件路径或本机/私网下载地址。公开发行下载不需要连接 token；MCP token、模型 key 和用户会话资料不得发送至更新站点。

**执行自动下载物之前必须解决信任根。** 推荐采用维护中的 TUF 客户端/签名元数据机制，随可信安装器固化初始 root，使用到期时间、元数据版本和密钥轮换，避免自写签名/防重放协议。明确区分元数据防降级和用户主动回退：主动回退只能选择已验证的本地旧版本，不能降低远端可信元数据水位。[TUF 官方规范](https://theupdateframework.github.io/specification/latest/)。

GitHub 的 release asset API 提供 `size`、`digest` 和版本化下载地址，可以用于一致性核对，但同源的 SHA256SUMS 不能独立建立发布者信任。[官方 API](https://docs.github.com/en/rest/releases/assets)。可在发布流程使用 immutable release：先创建 draft、上传完整文件再发布；其 tag/附件锁定与 release attestation 增强可审计性。是否已启用必须实际查证，本次不宣称本仓库已有此保护。[官方不可变发布说明](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases)。

若选 GitHub attestation 作为自动应用的信任链，需在客户端验证固定仓库/发行身份，并测试工具可用性、离线/吊销和回退策略；仅检查 API 的 `immutable` 字段不足。官方有 `gh release verify` / `gh release verify-asset`，本机 `gh` 当前不在 PATH，不能作为已有终端用户依赖。[官方校验方法](https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/secure-your-dependencies/verify-release-integrity)。

Windows Authenticode 可另行提供发布者校验与用户可见签名；采用时要校验信任链、撤销/时间戳以及项目允许的签名身份，并继续核对目标全文件摘要。`WinVerifyTrust` 只有返回 0 才表示验证成功；“任意受信证书签过”不等于本项目发布物。[Microsoft API](https://learn.microsoft.com/en-us/windows/win32/api/wintrust/nf-wintrust-winverifytrust)。证书购买和服务接入不属于当前授权实施范围。

## 应用、活动任务阻止与回退

建议由独立本地维护器负责应用；不要向普通 GUI 工具面增加无门槛的“安装任意 URL”。维护器与所有维护入口使用同一安装级生命周期/维护协调机制，身份绑定用户 SID、规范安装根与产品 ID。更新器取得排他维护权后，启动器不能抢先启动；所有 stdio、HTTP、当前 Agent CLI 和 child host 都必须合作，不能只按某个 data root 的锁判断。

显式应用前同时满足：

1. 下载物与更新元数据已验证；安装根、所有权、用户修改、磁盘空间和环境前置检查通过。
2. 所有相关任务已终止并结算原 ID；没有 pending/unknown 输入、未完成审核/续行、未解决清理错误或 in-flight 请求。未知状态阻止应用，不通过超时、断线或删记录当作空闲。
3. 对已启动过的 Runtime，确认原任务窗口按原授权处理、`host_alive=false`、`pending_ids=[]`、`cleanup_verified=true`，再释放原 HTTP owner；所有相关 daemon/child host 真正退出。`instant_stop` 只是请求，daemon 退出也不证明 child 已停；现 `close()` 等待 15 秒后可保留 child 继续收尾。
4. 对从未创建过 host 的空实例，维护器验证无任务、无请求/owner 竞争和无相关进程；不伪造 cleanup_verified。
5. 在实际切换点再次验证维护权和进程身份（PID + 创建时间 + 可信启动归属）。不强杀进程、不自动取消任务，也不拿任务授权代替维护应用确认。

旧 0.1.6 不支持安装级协作锁。首次迁移不能声称无缝自动：要求操作员结束所有入口，结合已知启动身份和原会话记录核对，存在不可分类运行实例就拒绝切换。新正常安装器也要遵守相同维护门禁，否则仍可绕过更新器的安全检查。

保留已有文件所有权/未知文件保留规则。第一实现可复用显式正常安装器完成覆盖，但必须承认它现有的回滚只覆盖本次失败，不能宣传完整的启动失败回退。后续建议独立不可变版本槽 + 持久事务日志 + 上一良好版本指针，稳定启动器在独占维护期间切换指针；断电后能判定恢复目标。

Python 环境在最终版本槽路径创建和验证，不把已创建的 venv 随目录重命名。依赖锁/Python 合同未变时才考虑经过验证的环境复用；变化时隔离创建新环境，禁止对活动 `.venv-agent` 执行 pip/uv 同步，失败保留旧槽。用户数据、模型和真实配置/密钥继续独立，不随版本槽回滚或清空；同一 Python minor 不等于可共享 Amadeus 环境。

切换后只做无输入健康检查：安装清单、隔离 import/维护入口、实际版本/能力和原生 HTTP 安全握手；不得为证明安装成功自动执行点击、截图或模型付费调用。健康检查失败时先确认新进程退出，再回到已验证旧版本并记录失败。数据迁移默认向后兼容；存在不可逆数据变更时停在明确迁移/恢复流程，不能只回退程序文件。

## 实施顺序与需要决定的事项

| 阶段 | 可做的独立交付 | 完成依据 |
| --- | --- | --- |
| 当前 Agent 发布 | 验收确切安装载荷/客户端、固定摘要与发布说明；扩展是否需要变更由真实 HTTP/Skill 合同决定 | 安装态实测、原请求证据、收尾及确切发布字节 |
| A：检查与兼容 | 只读能力投影、兼容降级、固定发行源更新检查、版本/下载信息展示 | 旧客户端/旧服务兼容、鉴权、无输入与无自动安装 |
| B：受控应用 | 可信元数据校验、隔离预下载、安装级维护门禁、显式应用 | 并发启动竞争、全部入口活动阻止、未知输入拒绝、失败无损 |
| C：可靠回退 | 版本槽、环境生命周期、持久更新事务、健康检查和回退 | 下载损坏、磁盘满、文件被改、进程拒绝退出、安装失败、新版启动失败、切换中断/恢复、数据兼容 |

现在可设计或实施 A；B/C 应作为独立变更，不能依据本设计文档标为已提供。更新机制至少补足上述针对性离线/隔离故障测试，再验证一个旧版→新版→故障回退的安装态生命周期；无需把 GUI 功能测试扩大为每项更新故障的桌面动作。

用户只需在进入相应实施阶段前决定：更新检查是否默认开启及频率；是否默认预下载；stable/preview 渠道；采用 TUF 还是 GitHub attestation/代码签名的具体信任链及其密钥管理；旧版本保留数量/磁盘预算。推荐 stable、每日最多一次检查、下载按设置、每次显式应用、至少保留一个上一良好版本。上述默认值是建议，不是已经保存或生效的配置。
