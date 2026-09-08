# Archived legacy web review experiments / 已归档旧网页审核实验

Use [branch purpose / 分支用途](BRANCH_PURPOSE.md) and [exact source manifest / 精确源码清单](LEGACY_WEB_SOURCE_MANIFEST.json).

This is a bounded source archive, not the current formal native release or a complete environment/data backup. Active development: `codex/dev-native-desktop`.

这是范围明确的旧源码归档，不是当前原生正式发行版，也不是完整数据/环境备份。日常开发请使用 `codex/dev-native-desktop`。

## R8S test originals / R8S 测试原件

Two current test files are appended before migrating their three legacy-adapter procedures to the maintained owner. The manifest now lists 15 source/test originals: the original 13 R8R web files plus these two R8S tests. Other current test helpers/maintained implementations are not included by this operation; the archive is not claimed runnable. Original assertions and bytes remain available here; current shared-contract coverage must be verified separately, with old entrypoints unavailable.

在将三个旧适配层测试过程迁到维护模块之前，追加两份当前测试原件。清单现有 15 份源码/测试原件：R8R 的 13 个网页文件及 R8S 的两份测试。本次不加入其他当前测试辅助文件或维护实现，不声称归档可独立运行。原断言和字节保留在此；现有通用契约覆盖需在旧入口不可用时另行验证。

## R8T interface review and persistence tests / R8T 界面审核与持久化测试

Append the exact two current test originals before removing their legacy adapters: interface review load/save/delete and workflow-store runtime-attachment coverage. The combined manifest now records 17 originals across R8R/R8S/R8T. The baseline has 74 passing cases; migration must retain necessary behavior and prove execution with legacy entrypoints unavailable. This archive is still not a complete current project or a runnable environment/data backup.

移除旧适配前，追加两份当前测试原件：界面审核加载/保存/删除，以及工作流持久化和运行时附着状态。R8R/R8S/R8T 清单共 17 份原件。本轮原始基线 74 项通过；迁移必须保留必要业务验证，并在旧入口不可用时重跑。归档仍不是完整当前项目或可运行环境/数据备份。

## R8U learning and artifact consumers / R8U 学习与产物调用方

Preserve six exact pre-migration test originals: learning demo scaffold, page detail candidate, goal readiness, offline new assets, synthetic SEEK replay and model artifact loading. All 23 originals across R8R/R8S/R8T/R8U are listed and raw-hash verified. These tests contain synthetic fixtures; archiving their source does not back up models, user data or a runnable current project. Necessary behavior must remain on maintained owners, with legacy entrypoints blocked during verification.

保存六份修改前测试原件：学习演示骨架、页面详情候选、目标就绪度、离线新资产、合成 SEEK 回放和模型产物加载。R8R/R8S/R8T/R8U 共 23 份原件按清单核验原始摘要。测试使用合成素材；源码归档不等于模型、用户数据或完整可运行项目备份。必要业务应保留在维护实现中，并在旧入口禁用时验证。

## R8V lifecycle and old boundary tests / R8V 生命周期与旧边界测试

Preserve five exact originals before classifying and migrating runner, stage-operation, stage-worker, deterministic-root and continuous-handoff tests. The manifest now lists 28 byte-verified originals. Shared business/worker contracts must remain; pure retired-web presentation, request-model or mocked routing tests may retire only with explicit classification and separate retained-contract verification. Archived failures are not fixed merely by retirement. No model, user history or runnable current environment backup is implied.

在分类与迁移前保存运行器、阶段操作、后台任务、确定性分区和连续任务交接的五份准确测试原件，清单共 28 份按原始字节核验。共享业务和 worker 契约必须保留；纯旧网页呈现、请求模型或模拟路由检查仅在明确分类并独立验证保留契约后退役。归档退休不等于修复原失败，也不代表模型、用户历史或完整运行环境备份。

## R8W persistence proof migration / R8W 持久化证明迁移

Preserve the exact Hybrid v1.1 persistence proof script before replacing its legacy lifecycle, draft-review and interface-review calls with maintained owners. All 29 manifest originals are byte-verified. Retain synthetic provider boundaries, rejection controls, exact saved-byte reload, fresh-process compilation/publication ordering and non-authorization assertions. The archived fake Qwen response has a known protocol mismatch; archiving is not a repair. This source archive is not a model, user-history or runnable environment backup.

在将 Hybrid v1.1 持久化证明脚本的旧生命周期、草稿审核和界面流程审核调用改为维护实现前，保存准确原件；清单共 29 份按原始字节核验。保留合成 provider 隔离、拒绝负控、准确保存字节重载、全新进程编译／发布顺序以及不授权断言。归档中的假 Qwen 响应存在已知协议不一致，归档不是修复；本源码归档不包含模型、用户历史或完整运行环境。
