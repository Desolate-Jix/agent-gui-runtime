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
