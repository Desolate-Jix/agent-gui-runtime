# Amadeus 扩展更新实现（2026-10-24，未发布源码）

后续交付：已提交 [Amadeus PR #261](https://github.com/Code-Amadeus/Amadeus/pull/261)，
分支 `codex/confirmed-extension-updates`，提交
`194223917cfcc3296d2af1aebf8da8315ae1b1fa`。尚待上游审查、合入和构建；下文“未提交”
描述的是开发验收时状态，不再代表当前 Git 交付状态。Runtime 0.1.8 发布不替代该 PR。

本轮在独立的 `E:/amadeus` 工作树实现 Host 商店更新，不修改 Runtime 的扩展 wheel，
也不修改正在运行的 Amadeus 安装。基线为 `9547f39ad518134ce4594f5a52a92c8a61629f45`。
开始时没有 tracked 修改；原有部署及验证类未跟踪文件全部保留。没有拉取、建分支、
commit、push、发布或重载用户进程。以下能力只有新源码，不能宣称现有安装已升级。

## 已实现的用户流程

1. **可选每日检查。** Manage plugins 中新增开关，默认关闭；启用后每天刷新官方目录，
   只对兼容、未撤回、未封禁且高于安装版本的更新提示。候选不变时不重复通知。
   检查不下载或安装 wheel，不改变运行中的 Work/MCP，也不自动恢复受损安全状态。
   自动版本比较采用官方目录的 `X.Y.Z` 合同；本地 prerelease 可排队导入，但不参与
   本轮自动更新候选比较。
2. **选择精确版本，等待应用退出。** 商店安装按钮改为安排下次应用启动。持久记录
   `id/version/digest`，显示版本和摘要，可取消；排队阶段不改已安装包。
   原生本地 wheel 选择器也可首次安装：先复制所选 wheel 的精确字节并检查身份，
   再排队到下次启动；保留本地包及 prerelease 原有兼容性，不要求它先进入商店。
3. **停机边界内安装。** 下次应用启动、backend 尚未启动时，main 端互斥阻止并发
   backend 启动。要求没有自有进程、启动/停止事务或未确认清理，本机 backend
   端口确实拒绝连接，并且全部已登记 backend 启动的清理凭据通过验证。仅端口关闭、
   `/shutdown` 成功、root PID 退出或强制杀进程都不足以授权更新。活动、超时及未知
   状态均阻止安装。后端运行期间仍可安全排队，不会替换其包或重放 Work。硬崩溃或清理未确认时，
   回滚也须等待真实停止证明；不能因恢复排队就绕过活动进程屏障。
4. **重新验证与原生确认。** 在该边界内重新下载官方目录；排队摘要发生变化、离线、
   撤回、封禁或不兼容均不能安装。现有大小、wheel digest、Host 检查、审核事实及
   原生安装确认继续保留。原生确认显示本次精确目标。本地排队不依赖目录，
   安装前及确认后重新核对已冻结的 wheel digest，并保留原生本地依赖安装路线。失败或取消消费本次排队意图，
   下次启动不会自动重试；需要用户重新选择。
5. **保留上一已验证版本。** 对商店或安全排队的本地版本替换，在保存新记录前写持久
   `extensions/update-rollback.json`，保存上一 package/install 引用、旧配置、
   Provider 绑定和原有 OS 加密的 secret 密文。旧 wheel/环境被清理器保护，不因
   desired record 已换新就删除。
6. **健康确认与显式保留。** 核对当前进程的 package version/revision、Host startup
   accepted 及完整、无重复的贡献 ready；纯前端包使用 native applied revision，
   不伪造 backend 贡献。管理器还提供状态刷新。该投影不证明远端 MCP 调用成功，
   因此仍需用户实际检查后明确选择保留；此前不删除回滚记录。
7. **失败与跨启动恢复。** 安装保存/应用事务失败先尝试恢复旧 package/config/加密
   secret，同时保留全局安全封禁事实。持久写盘仍失败时保留两版文件和恢复日志。
   未确认更新跨进程或启动失败后，禁止静默再次激活新包，管理器可安排下次应用启动
   回滚；停机边界中核对保留的旧 wheel digest 和 package，再显示原生旧版本确认。
   恢复不会重放 Work、MCP 调用或桌面动作。原生回滚确认之后再次核对旧 wheel
   digest；旧字节损坏或确认时被替换都拒绝恢复，保留两版和日志。

两类版本独立：Runtime 的兼容 HTTP 修复不要求同步发布或重装 Amadeus wheel。
扩展自身的 Skill、配置、权限或 Host 合同变更才需要新扩展及独立审核。本实现不允许
Runtime HTTP 服务下载、执行或替换 wheel；不改变固定的 0.0.4 制品及其旧下载 URL。
Amadeus 与 Runtime 的默认检查开关分别由各产品定义，本轮 Host 默认关闭不改变
Runtime 的独立设置。

## 接口和文件

新增 catalog 请求为 `auto-check(enabled)`、`schedule(id,version)`、`cancel-scheduled`、
`rollback`、`health`、`confirm-update`。renderer 不可提供 URL、digest、review 或
安装路径；商店排队身份由 main 从官方目录取得，本地路径只接受原生文件选择器。
原 `install` 入口保留原生检查，并在生产 main 的停机边界内执行。catalog view 仅返回开关、排队版本摘要及回滚状态，不返回
恢复记录或 secret 密文。

主要源码位于 Amadeus 的：

- `electron/src/main/extensionUpdates.ts`：停机互斥与持久 last-good 日志。
- `electron/src/main/extensionCatalog.ts`：每日检查、通知、精确版本排队与启动消费。
- `electron/src/main/extensions.ts`：事务恢复、旧环境保留、健康及用户确认、显式回滚。
- `electron/src/main/desktopSettings.ts`：只恢复目标扩展，保留全局设置与安全高水位。
- `electron/src/main/index.ts`：真实 main 生命周期、停机证明、通知与可信 IPC 接线。
- `electron/src/main/backendProcessTree.ts`、`server/backend_cleanup.py`：启动前持久登记、
  Windows Job 计数与跨进程清理凭据验证。
- `server/app.py`、`agent_host/provider_runtime.py`、`agent_host/adapters/pi.py`：实际
  Host/Provider/Work 清理结果，不再从吞掉的 close 异常推导成功。
- `electron/src/shared/extensionCatalog.ts`、`extensions.ts`：请求/状态及排队结果合同。
- `electron/src/renderer/components/ExtensionSettings.tsx`、`ExtensionCatalog.tsx` 及
  `electron/src/renderer/locales/zh-CN.json`：开关、排队、取消、保留、回滚与中英说明。

`update-preferences.json` 保存独立检查偏好与待执行身份；不保存凭证。
`update-rollback.json` 的 secret 部分只复制现有加密密文，不调用模型或外部服务。
`backend-cleanup.json` 在每次 spawn 前持久登记 owner；独立 receipt 绑定 launch id、
instance nonce、项目、解释器、root PID 和创建时间。Python 在创建 Provider 前进入
只计数的 Windows Job，没有 kill-on-close 或 breakaway 标志。只有所有 Provider
关闭成功、Work 已终止且受控子进程退出后，root 只写 approval。独立 observer 在
root 加入 Job 前启动并持有 Job 查询句柄，确认 root 身份已退出且 Job 计数为零后
才写最终 settled receipt；Electron 还核对 root 与 observer 的 PID/创建时间均已退出。
Job 名无法重新打开不作为停止证据。后来的进程不能覆盖旧的未确认 owner；复用无自有
句柄的 backend 会留下 unknown 屏障。清理验证不终止独立 Runtime HTTP daemon。
全部 owner 经真实退出证明核验后，原子压缩活动索引，保留独立回执存档；同一索引的
登记、unknown 标记与核验串行执行，避免历史重启次数增加导致重复扫描或丢失新登记。

这是新协议的停止证明。首次迁移没有 ledger 只说明从未登记新协议启动，不能证明
旧版 Pi/MCP orphan 已退出。首次使用前需要先人工关闭旧 Host 及其所有旧入口并核对
旧子进程；不能把口头确认或端口关闭写成 clean receipt。遗留 unknown/未确认 owner
会阻止后续安装，需要实际清理/迁移检查，不能在界面点“确认”绕过。

## 检查与尚未验收

最终检查（在 `E:/amadeus/electron` 运行）：

- `tsc --noEmit`、`npm run check:config`、`git diff --check` 通过。
- 完整 `npm test`：**637 passed / 0 failed / 0 skipped**。
- 之后仅清理索引压缩与并发边界作小修，相关 Node **19 passed / 0 skipped**，含两项
  真实 Windows 自建进程回归；TypeScript 与 diff 检查再次通过。该组与完整检查重叠，
  不将它相加为新的总数。
- 更新相关五模块：**133 passed**，已包含在上述完整检查内，含原生回滚确认期间的
  篡改、纯前端包及不完整/重复健康投影正负控。
- 独立清理模块最终检查：**Node 14 passed**（比完整检查时增加一项 noapproval
  负控）、**Python 48 passed**；Node 含真实 Windows Job/observer 自建无 GUI
  子进程。生产 API 冻结后未再修改；五个 Python 文件语法检查通过。

分组结果有重叠，不相加作为独立用例总数。完整日志为
`E:/amadeus/build/extension-updates-complete-805cdf870c7444ba88cf0d742ab84904.log`。
独立生命周期证据位于
`D:/AgentGUI-Projects/evidence/current-agent-mode-20261024/`：
`amadeus-backend-cleanup-node.log`、`amadeus-backend-cleanup-junit.xml`、
`amadeus-cleanup-test-environment.json`。Python 使用现成的 Amadeus Python 3.12.14；
测试专用依赖 overlay 的路径及版本记在环境清单，不修改用户运行环境。

新增的源码/测试文件已出现在 `git status --short`，尚未暂存或提交：
`electron/src/main/extensionUpdates.ts`、`electron/tests/extensionUpdates.test.mjs`、
`server/backend_cleanup.py`、`tests/test_backend_cleanup.py`；原有未跟踪文件保留。

测试使用临时合成目录、wheel/Host 假件及可控状态；未启动 Electron、操作桌面、
调用付费 API 或修改用户安装。现有安装测试中的合成子进程清理检查不产生桌面输入。
尚无新打包应用实机生命周期、真实官方已准入扩展升级或远端 MCP 的端到端验收。
官方目录为空时，自动检查可工作，但不能凭空提供一个已审核更新。

Host startup/projection ready 和用户实际功能检查保持分离。回滚保存的是扩展包及
配置/密文，不是第三方包自身数据迁移的通用事务；需要不可逆迁移的扩展必须另有
人工迁移与恢复方案，不能从本轮记录推定数据可逆。独立 Runtime daemon 的运行任务
与升级由 Runtime 更新器管理，Amadeus 不会擅自停止它。全新机器、物理断电及系统
通知可靠性未在本轮离线检查中认证。更新日志采用文件 fsync 后 rename；本轮未证明
Windows 物理断电时该日志替换具有 WRITE_THROUGH 等价保证。写入异常保留旧包或
recovery 状态，不宣称其消除了硬件断电风险。清理协议目前仅验证 Windows Job；
其他平台不能从一次正常进程退出推导“所有子进程已停止”。

原方案见 [Amadeus 更新策略](AMADEUS_UPDATE_STRATEGY.md)与
[Runtime 更新策略](RUNTIME_UPDATE_STRATEGY.md)。两者的历史“未实现”状态应按各自
日期阅读；本页仅报告本轮未发布的 Host 源码交付。
