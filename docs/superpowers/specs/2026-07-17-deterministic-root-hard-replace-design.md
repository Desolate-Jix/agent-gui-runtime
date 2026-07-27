# Deterministic Root Hard Replace Design

## Goal

用已经通过九界面固定回放的 deterministic root partition 正式替换旧 Learning Mode Stage1 分栏实现，随后优化下游融合输出，并删除失去生产或回归用途的旧代码与实验资产。

## Scope

- 只修改只读 Learning Mode 的识别、展示、回归与文档。
- 不修改 Execute、Runtime PathGraph promotion、安全 Gate、真实点击、填写或提交。
- 所有学习产物继续保持 `display_only=true`、`execute_binding_enabled=false`、`artifact_is_authorization=false`。
- 九界面原图、root partition、final fusion 三图回放继续作为固定回归证据。

## Architecture

### Canonical Stage1

`app/learn/recognition/root_partition.py` 成为唯一正式根区实现。`panel`、API、pipeline、Stage1-only runner 和 two-stage builder 不再暴露或接受 strategy 参数，也不再运行时选择 `legacy_v1`。

旧实现不保留隐藏 CLI rollback。需要恢复时使用 Git 历史，而不是长期维护第二条运行路径。

### Downstream Contract

正式 root partition 继续通过现有 Stage1 contract adapter 进入 Stage1 localization、Stage1.5、Stage2 numbering、calibration、fusion、page details 和只读 PathGraph draft。root validator 与 Stage1 gate 保留，任何失败都必须明确停止 Stage2，不增加兜底路径。

### Optimization Order

1. 迁移正式 root 实现并删除 strategy 分叉。
2. 运行聚焦测试和九界面回放，确认根区与下游合同未改变。
3. 以三图人工审核暴露的问题优化 final fusion 密度与分组，不改变 root 合同。
4. 重新做引用可达性审计，只删除旧 Stage1 专属 helper。
5. 删除 production/benchmark 均不引用的 adjudication 实验模块、runner、专属测试和 fixture；保留一份压缩历史结论。
6. 全量回归并同步精简文档。

## Deletion Rules

可以删除：

- `legacy_v1` strategy 参数、dispatch、CLI 选项和专属测试。
- 仅能从旧 `_stage1_structure_regions` 到达的 helper。
- 已结束且 production/九界面 benchmark 均不导入的 hierarchical model adjudication 实验代码、runner、专属测试和 fixture。
- 重复或已被最终结论取代的实验计划/说明。

必须保留：

- Stage2 numbering、calibration、fusion 与 page-details 仍引用的 helper。
- deterministic root validator、Stage1 gate、overlay/crop 生成。
- 九界面 manifest、runner、三图 comparison 与失败报告。
- `deterministic_root_partition_v1` 正式 contract 和只读安全字段。

任何删除都必须先有引用或可达性证据，不能根据文件名或 `legacy` 字样猜测。

## Error Handling

- root input 缺少有效屏幕尺寸时显式失败。
- root validator 或 Stage1 gate 失败时报告明确 failure category，并停止 Stage2。
- 不允许自动回退旧 Stage1。
- benchmark fixture 缺失或 checksum 不匹配时标为 invalid，不计入通过。

## Verification

- 聚焦单元测试覆盖唯一正式入口、无 legacy 参数、root contract、安全字段和 Stage1 gate。
- 九界面固定回放输出同源 original/root/final 三图，报告 9 attempted、0 invalid，并逐图人工审核。
- `py_compile` 覆盖修改的 Python 模块和 runner。
- 全仓库测试通过。
- 搜索确认 production、panel、CLI 和文档不再宣传或暴露 `legacy_v1`；历史结论中的引用必须明确标为历史。

## Known Limitation

九界面 fixture 仍依赖本机 gitignored trace/screenshot，尚非 clean-clone hermetic。它不阻塞本次 hard replace，但必须在文档中保留为测试基础设施债务，不能把固定回放解释成通用识别准确率。
