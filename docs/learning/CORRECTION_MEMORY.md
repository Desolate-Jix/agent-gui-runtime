# 学习模式 CorrectionMemory

## 目标

CorrectionMemory 把面板中的人工框修改保存为可审计的候选经验。它解决的是“同类错误以后能否复用修正经验”，不是让模型看到一次修改后自动改变生产识别逻辑。

人工编辑保存后会生成：

- 版本化 `human_review_patch_v1`；
- `learning_correction_memory_entry_v1` 修正记录；
- `learning_surface_rule_registry_v1` 中的 `candidate` 规则记录。

所有产物都保持 `artifact_is_authorization=false`、`execute_binding_enabled=false` 和 `final_submit_forbidden=true`。

## 修正记录

每条修正记录至少包含：

- 原学习草稿路径和 SHA-256；
- 原截图路径和 SHA-256；
- 人工修改原因；
- Surface Adapter 与可见结构证据；
- `add`、`delete`、`update_bbox`、`update_role` 或 `update_parent` 的 before/after；
- 适用范围、反例要求和安全声明。

应用名不能单独成为复用条件。规则必须保留可见结构证据，并在回归中证明不会污染其他界面。

## 生命周期

```text
candidate
  -> regression_verified
  -> human_approved
  -> active
  -> rolled_back
```

- `candidate`：人工修改刚保存，只能用于离线比较。
- `regression_verified`：固定回归和 holdout 通过，且没有失败样本。
- `human_approved`：人工明确批准适用范围。
- `active`：人工确认激活原因和反例覆盖后，才可由生产读取入口加载。
- `rolled_back`：人工记录回滚原因后立即退出生产读取集合。

禁止跳级。模型可以建议候选规则和反例，但不能批准、激活或回滚。激活证据文件在读取时会重新校验 SHA-256；文件缺失或被修改时直接拒绝加载。

## 当前边界

- 人工编辑器和候选记录链已经可用。
- 当前没有预置或自动激活规则。
- `load_active_surface_rules()` 是唯一允许读取生产候选的入口，只返回完整走完生命周期且证据校验通过的规则。
- 真实面板已把这些规则作为 Surface Adapter 的受限建议输入；只暴露 rule ID、人工范围、edit type 和当前证据匹配，不直接复用旧截图 bbox。
- Chat/Media 内容策略迁移已经完成；真实面板多界面验收仍属于两周计划后续任务。
