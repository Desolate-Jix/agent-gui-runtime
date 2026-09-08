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
