# Learning Overlay Model Review 设计

## 目标

在学习模式的 Stage2 编号结果与最终融合之间增加一个独立、默认关闭的模型复核实验，用合成框图和对应 JSON 发现明显的错误分类、错误父子关系和缺失区域。实验不修改 Execute、PathGraph、正式安全 Gate，也不授权真实点击。

## 数据流

```text
Stage2 JSON + 原始截图 + 合成框图
  -> 受限模型复核
  -> review_patch（keep/remove/relabel/missing/needs_human_review）
  -> 确定性 patch validator
  -> 对 missing 生成定位任务
  -> 现有 OCR + VISTA/4B + rerank + gate dry-run
  -> 修订后的只读融合结果与 overlay
```

## 删除与修复闭环

删除只作用于错误的 Stage2 包装区域，不删除其原子元素。每一个 `remove` 必须生成一个 `removal_resolution`，并明确记录以下去向之一：

- `children_reparented`：有效子元素保留并回到现有父区；
- `relabel_replacement`：由同一完整 bbox 的受限重标结果替代；
- `precise_locator`：缺失局部对象进入 OCR、VISTA/4B、rerank 与 Gate dry-run；
- `stage1_repartition`：缺失栏或 pane 返回结构层重新分区；
- `needs_human_review`：证据不足，不允许自动完成。

`deleted_without_resolution` 是非法状态。只要存在未完成 repair、无内容去向的删除项、协议失败或替代覆盖未验证，工作流必须停在 `repair_pending`、`replacement_incomplete` 或 `needs_human_review`，不得生成完成状态。

## 工作流状态

```text
pending
  -> full_review
  -> focused_review
  -> patch_validated
  -> repair_pending
  -> repair_running
  -> recomposing
  -> replacement_verification
  -> completed_review_only
```

失败状态包括 `protocol_failed`、`needs_human_review`、`repair_failed`、`replacement_incomplete` 和 `stale_evidence`。`completed_review_only` 仍然不授权 Execute 或 Runtime PathGraph。

## 替代完整性 Gate

Gate 必须验证：

1. 每个删除区域都有唯一内容去向；
2. `children_reparented` 引用的原子元素仍存在于审核后 Stage2；
3. repair request 使用现有 Stage1 或精准定位输出，模型粗 ROI 不能直接成为最终 bbox；
4. repair 未完成时不能重新组合为完成产物；
5. 修复后重新运行 containment、ownership、overlap 与 coverage 检查；
6. 重新生成融合图、界面详情和只读 PathGraph，不能继续展示旧 overlay；
7. 所有产物保持 `display_only=true`、`execute_binding_enabled=false` 和 `artifact_is_authorization=false`。

## 模型权限

模型可以：

- 保留现有区域；
- 删除缺乏视觉或结构证据的区域；
- 在受限角色枚举内重标区域；
- 指出缺失内容、父区域和粗略 ROI；
- 标记需要人工复核的歧义。

模型不可以：

- 自由生成最终精确 bbox；
- 引用不存在的 region 或 parent；
- 修改 Stage1 根分区；
- 生成 Execute action；
- 绕过现有定位链和安全 Gate；
- 将复核产物直接提升为 Runtime PathGraph。

## Patch 合约

输出必须包含 `keep`、`remove`、`relabel`、`missing` 和 `needs_human_review`。`remove/relabel/keep` 必须引用现有 region ID；`relabel.new_role` 必须来自允许枚举；`missing` 只能给出描述、父区域、预期角色和粗略 ROI。最终 bbox 只能来自后续精准定位证据。

## 最小实验

第一轮只使用一个包含明显假卡片的聊天界面样本：

1. 检查成员列表或聊天列是否被错误识别为 `tile_card_parent` / `recommendation_item`；
2. 验证模型能删除或重标这些错误区域；
3. 验证缺失项会生成定位任务，而不是直接接受模型 bbox；
4. 生成 before/reviewed/diff overlay 和 JSON 报告；
5. 不接入正式面板数据流，结果通过人工审核后再决定是否进入生产链。

## 验收

- 明显错误区域减少，且正确区域没有被大量误删；
- 所有 patch 引用和角色通过 validator；
- missing 项不携带最终 bbox，且能转换为现有定位任务；
- `real_clicks=0`、`execute_binding_enabled=false`、`artifact_is_authorization=false`；
- 报告明确区分模型复核判断、确定性校验和定位链结果。

## 失败处理

无效 JSON、越权字段、未知 region、非法角色、跨根区修改或缺失证据时拒绝整个 patch，并保留原 Stage2 结果。不得用宽松 fallback 隐藏模型协议错误。
