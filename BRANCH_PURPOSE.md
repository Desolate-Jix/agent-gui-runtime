# Legacy web review source archive / 旧网页审核源码归档

## Purpose / 用途

This branch preserves the current old web-panel experiment source (learning-result review, workflow editing, runtime debug navigation and the old local launcher) before retirement. It is an archive, not the active native desktop development branch or a validated formal release.

本分支保存退役前的旧网页实验端源码：学习结果审核、流程编辑、运行时调试导航及旧本机启动器。它不是原生桌面日常开发分支，也不是验收通过的正式发行版。

## Exact scope / 精确范围

`LEGACY_WEB_SOURCE_MANIFEST.json` lists the 13 captured files with original SHA-256, byte length and Git blob identity. Other files come from the earlier preparation baseline `f03d933538c33886fcd356f120102ef81731fb8f` and are not a snapshot of every current uncommitted formal change. Restoring the current integration may require maintained modules from the active project; this archive alone is not claimed runnable.

清单记录 13 个当前旧网页文件的原始摘要、长度和 Git 对象。其余内容继承较早准备基线，并未备份所有当前正式版改动。恢复当前集成可能仍需日常项目中的维护模块；不能仅凭此分支声称完整应用可运行。

The native project stays at `codex/dev-native-desktop`. No models, runtime data, unique experiment history or local ignored documents were added. Source backup is not a complete data/environment backup. Archiving does not authorize deletion of still-used files; dependency and test retirement must be verified separately.

原生日常开发仍在 `codex/dev-native-desktop`。本次不加入模型、运行数据、唯一实验历史或本地忽略文档。源码归档不等于数据/环境全备份；仍被调用的文件必须另行核验依赖与测试退役，不能因上传就删除。

## Verification / 验证

The archive operation checks all captured bytes against its manifest, reads the newly published remote commit back, and preserves the main HEAD/index/worktree source. It performs no GUI, Agent, model or external-input acceptance. The source rule scan reports only its scoped patterns, not an exhaustive privacy guarantee.

归档操作逐文件检查清单、回读新远端提交，并保持主工作树 HEAD/索引/源码。未执行 GUI、Agent、模型或外部输入验收；规则扫描只代表所检查的模式，不是穷尽隐私保证。

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
