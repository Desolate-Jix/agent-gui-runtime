# 通用审核修复与九界面归纳设计

## 目标

把当前模型复核实验从“发现并删除错误包装框”推进为通用、可审计的修复闭环。QQ 仅作为失败发现样本；公共实现不得包含应用名称、固定坐标、特定标题或单界面阈值。

修复是否有效不以单个界面变好为准，而以冻结的九界面基线共同验证：

1. Apple Music：媒体卡片和导航结构。
2. Python.org：密集双列文档和列表。
3. Windows Settings：设置控件与磁贴。
4. File Explorer：文件行、列和主内容区。
5. Steam Friends：会话工作区和局部子栏。
6. WhatsApp：多列聊天结构和输入区。
7. Notepad：内部元素稀疏的大编辑区。
8. WeChat：聊天列表、消息区和成员/工具子栏。
9. Bilibili：首页媒体卡片与混合导航。

## 设计原则

- 模型只负责提出语义复核意见和粗修复意图，不拥有最终几何。
- 删除错误 wrapper 时必须保留其原子 children，并记录唯一去向。
- 修复请求必须携带完整来源，不能用一个聚合请求隐藏多个失败。
- 最终 geometry 只能来自确定性重分区或通过 Gate 的精准定位。
- 修复结果保持 display-only，不授权 Execute 或 Runtime PathGraph。
- 任一来源未闭合、原子内容丢失或人工复核未完成时，状态必须保持 pending。

## 通用数据流

```text
Stage2 + composite overlay
  -> model review patch
  -> strict patch validator
  -> removal resolution compiler
  -> generic repair requests
     -> deterministic repartition executor
     -> precise locator executor (OCR/VISTA/rerank/Gate dry-run)
  -> replacement integrity gate
  -> recomposed display-only Stage2
  -> nine-interface regression and rule adjudication
```

该链保持默认关闭，位于实验 probe 内。正式 Stage1、Stage2、Execute、PathGraph 和安全 Gate 不因本实验改变。

## Repair Request 合同

每个通用修复请求至少包含：

```json
{
  "repair_request_id": "review_repair_1",
  "repair_route": "stage1_repartition",
  "parent_region_id": "...",
  "source_removed_region_ids": ["..."],
  "source_child_item_ids": ["..."],
  "rough_roi": {"x": 0, "y": 0, "w": 0, "h": 0},
  "expected_role": "member_list",
  "completion_contract": {
    "all_children_assigned_once": true,
    "replacement_inside_parent": true,
    "no_new_sibling_overlap": true,
    "no_geometry_from_model_roi": true
  },
  "display_only": true,
  "execute_binding_enabled": false,
  "artifact_is_authorization": false
}
```

多个删除 wrapper 可以合并为一个请求，但必须显式列出全部 `source_removed_region_ids` 和去重后的 `source_child_item_ids`。聚合依据只能是同一父区域、相邻/重叠修复范围和兼容语义角色。

## 修复执行器

### Deterministic Repartition

针对 `stage1_repartition`，复用现有确定性结构证据和分区逻辑，在请求的父区域内重新编译候选区域。输入包含原图、父区域、现有原子元素和请求来源；输出新的 replacement regions。不得读取应用名称决定规则，不得复制 rough ROI 作为最终 bbox。

### Precise Locator

针对 `precise_locator`，复用 OCR、VISTA、rerank 和 Gate dry-run。输出必须包含候选证据、最终点/框、坐标变换和 Gate 结论。Gate 未通过时修复失败，不执行真实点击。

## Replacement Integrity Gate

完成状态必须同时满足：

- 每个 remove 恰好有一个 resolution。
- 每个来源 wrapper 都出现在某个 repair request 或 `children_reparented` resolution 中。
- 所有原子 child ID 在重组后恰好归属一次。
- replacement 位于声明的 parent 内。
- replacement 不新增明显 sibling overlap、越界或环。
- replacement geometry 来源可信。
- 所有 repair request 已完成。
- `needs_human_review` 为空。

否则状态按原因保持 `repair_pending`、`repair_failed`、`replacement_incomplete` 或 `needs_human_review`。

## 九界面归纳流程

每次候选通用规则调整必须执行：

1. 冻结修改前九界面输出和 checksums。
2. 对九界面运行同一 repair compiler、executor 和 integrity gate。
3. 保存每个界面的原图、Stage1 图、审核前融合图、审核后融合图和结构化 diff。
4. 分类变化为 `improved`、`unchanged`、`regressed`、`invalid_fixture` 或 `not_applicable`。
5. 从跨界面失败中归纳 invariant，不从应用名称归纳规则。
6. 规则只有满足晋升 Gate 才可留在公共层。

### 规则晋升 Gate

候选规则必须满足：

- 至少改善两个不同结构族，或者修复一个明确的安全/数据完整性 invariant。
- 九个有效界面没有新增原子内容丢失、重复归属、越界或错误可执行候选。
- 不降低现有 Stage1 gate、replacement integrity gate 或安全阈值。
- 没有应用名称、固定坐标、固定文本标题或样本 checksum 分支。
- 每个改善和退化都有三图/四图与 JSON diff 证据。

单界面改善只能进入 `case_observation`，不能直接晋升为通用规则。

## 报告字段

总报告不输出通用准确率，只输出：

- `cases_attempted / improved / unchanged / regressed / invalid`。
- 每个 case 的 before/after root、group、item ownership 和 integrity gate 差异。
- `candidate_rule_id`、`supported_interface_families` 和 `rule_promotion_allowed`。
- 修复请求数量、完成数量、pending 数量和 human-review 数量。
- 原图、Stage1、审核前融合图、审核后融合图路径。
- 零点击、零填写、零提交安全计数。

## 验收边界

本阶段通过意味着：通用修复合同可运行，九界面回归可暴露污染，至少一个跨结构 invariant 得到验证。它不代表开放世界识别可靠、模型复核可靠、Live GUI 操作可靠或 Runtime PathGraph 可执行。

在九界面结果产生前，QQ 必须继续保持 `repair_pending`；不得把 fixture-only completion 解释为真实界面修复完成。
