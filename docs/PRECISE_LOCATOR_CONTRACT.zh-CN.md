# PreciseLocator 公共定位合同

## 目标

`PreciseLocator` 是学习模式与执行模式共享的定位证据层。它不拥有任务决策，也不授权点击。

- 学习模式固定以 `display_only + no_click + dry_run_gate` 调用。
- 执行模式可以复用同一份定位证据，但真实动作仍必须经过 `/action/execute_recognition_plan` 的 Gate。
- VISTA-4B 只是一种点位证据源，不是最终定位裁判。

## 输入合同

每次定位必须携带：

- `run_id`、`capture_id`、截图路径和尺寸；
- `window_binding_id`，没有同窗口证据时 UIA 不能计为当前证据；
- `target_id`、`target_role`、`target_label`；
- `parent_region_id`、`parent_region_bbox`；
- `source_candidate_bbox`、来源、置信度和 freshness；
- 当前 observe trace、OCR、UIA、视觉候选引用；
- `execute_binding_enabled=false` 和 `click_performed=false`（学习模式）。

## 数据流

1. **候选 freshness 与 bbox 质量检查**
   - 校验截图、尺寸、父区和坐标空间一致；
   - 区分 `candidate_bbox_ok`、`candidate_bbox_misaligned`、`candidate_bbox_stale`、`candidate_outside_parent`、`candidate_label_too_generic`；
   - 原 bbox 只是一名候选，不能作为 hidden answer。
2. **候选重建**
   - 从当前截图 OCR、同窗口 UIA、整屏理解视觉框、父区布局槽位生成候选；
   - 所有候选必须位于父区内，并记录来源；
   - 图标类目标不能因为没有 OCR 就自动通过。
3. **VISTA 点位提议**
   - 默认使用原图或无标注父区 ROI；
   - 编号 overlay 默认仅供人类审核，不作为模型输入；
   - debug ablation 使用 overlay 时必须单独标记和统计。
4. **证据 rerank**
   - 组合点是否落入候选、到中心距离、文本匹配、角色匹配、OCR/UIA/视觉支持、父区一致性、hit-area 合理性；
   - 输出逐项分数、第一名与第二名差距；
   - 不因候选来自原 bbox 而给予隐藏加权。
5. **dry-run gate**
   - 检查 freshness、点位、候选差距、危险语义和父区边界；
   - 学习模式只输出 `locate_review_pass`、`locate_review_failed` 或 `needs_human_review`；
   - 不生成 `click_authorized`、`execute_ready` 或 Runtime PathGraph 授权。

## 输出合同

`precise_locator_evidence_v1` 至少包含：

- 原始候选和 bbox 质量分类；
- OCR/UIA/视觉候选及来源计数；
- VISTA point、模型输入模式和坐标变换；
- rerank 分数明细、最终候选和 margin；
- dry-run gate 状态、review 标记和 failure reason；
- `overlay_used_as_model_input`、`numbered_overlay_used`；
- `execute_binding_enabled=false`、`click_performed=false`。

## 验证顺序

1. 先实现纯数据合同和 bbox 质量分类，不改变当前行为。
2. 接 OCR、当前 observe 的视觉候选和同窗口 UIA 候选。
3. 接 VISTA 原图/父区 ROI 点位证据。
4. 接 rerank 与 dry-run gate，再替换学习模式当前的单点一致性检查。
5. 在 Apple Music、Python、Windows 设置、QQ 上分别保存原图、Stage1 栏图、最终融合图和定位 trace。
6. 新界面回归必须同时复跑旧界面，防止类规则污染。

## 报告口径

- 不输出一个总“准确率”。
- 按 `media_card`、`text_button`、`icon_button`、`nav_item`、`window_control` 等类别报告。
- `inside_candidate_bbox` 只是点位一致性，不等于定位成功。
- fixture、overlay-assisted、raw-image 和 live-current-window 结果必须分开。
- 小样本不能证明稳定性或 SEEK E2E 能力。
