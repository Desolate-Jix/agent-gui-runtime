# 学习模式路径图面板重做方案

Last updated: 2026-06-24.

## 目标

新版学习模式路径图不再把所有节点平铺成一张拥挤的散点图，而是把一个软件或网页学成一张可编辑的界面地图：

- 允许完全替换旧路径图 UI；旧图只作为兼容数据源，不作为新的交互形态约束。
- 能看到整个软件的路径和状态流转。
- 每个界面按区域分层：固定按钮、导航栏、变动区、详情区、表单区、危险操作区。
- 固定按钮和导航栏优先走截图识别，不每次重新让模型定位。
- 变动区只给模型大致 ROI，让模型在局部截图内识别，减少全屏理解和大范围 grounding。
- 操作面板能手动查看每个按钮截图、当前匹配图、ROI 图、来源截图、风险标签。
- 操作面板能修改学习路径图，包括区域、按钮、动作类型、危险等级和允许范围。

## 核心结构

建议新增 `learned_interface_map_v1`，作为未来 Learn Mode 的主产物。它比当前 PathGraph 更偏向“界面地图”，PathGraph 可以由它派生。

```json
{
  "contract_version": "learned_interface_map_v1",
  "app_id": "seek",
  "states": [],
  "regions": [],
  "visual_assets": [],
  "dynamic_areas": [],
  "transitions": [],
  "safety_policy": {}
}
```

### State

State 代表一个可复现的界面状态，不直接保存旧坐标作为授权。

必备字段：

- `state_id`
- `page_type`
- `title_pattern`
- `url_pattern`
- `window_title_pattern`
- `state_fingerprint`
- `regions`
- `entry_actions`
- `exit_actions`

### Region

Region 是路径图的主视觉层。每个状态先切区域，再看区域里的节点。

推荐类型：

- `fixed_controls`：固定按钮区，例如 Apply、Save、Continue。
- `navigation`：导航栏、标签栏、筛选栏。
- `dynamic_collection`：变动列表，例如 SEEK 岗位卡片列表。
- `detail_content`：详情正文，例如 SEEK 右侧岗位详情。
- `form_flow`：多步申请表单。
- `danger_zone`：最终提交、支付、删除、发送等高危区域。

Region 必备字段：

- `region_id`
- `label`
- `role`
- `bbox_hint`
- `container_id`
- `scrollable`
- `stability`
- `children`

`bbox_hint` 只能作为当前截图 ROI 搜索范围，不能作为点击授权。

### Visual Asset

固定按钮、导航栏、稳定图标都应学习为视觉资产。

必备字段：

- `asset_id`
- `label`
- `role`
- `semantic_action`
- `danger_level`
- `tight_crop_ref`
- `context_crop_ref`
- `source_capture_id`
- `source_bbox`
- `source_click_point`
- `match_policy`
- `allowed_region_ids`
- `can_authorize_click=false`

低风险视觉资产可以进入快路径，但仍必须通过：

- 当前截图匹配
- top1/top2 分数差检查；相似按钮重复出现时必须标记 ambiguous，不能走快路径
- 默认校准 ROI 只能小范围围绕 source bbox；如果需要大区域搜索，必须显式来自 region scope，而不能自动外扩到相邻同类按钮
- candidate freshness
- region scope
- action taxonomy
- Gate
- final submit guard

视觉资产不是点击授权。它只负责把“这个按钮大概率在当前截图哪里”快速召回出来，再交给执行层审查。

### Dynamic Area

变动区不要把每个卡片都学成固定按钮截图。

推荐字段：

- `area_id`
- `region_id`
- `entity_type`
- `entity_pattern`
- `roi_policy`
- `model_budget`
- `scroll_policy`
- `identity_mapping`

执行时流程：

```text
state_match
-> dynamic_area ROI
-> local screenshot crop
-> OCR / lightweight model / VISTA only inside ROI
-> candidate freshness
-> Gate
```

这样 SEEK 的岗位卡片、搜索结果、新闻列表都可以用区域约束加速，而不是全屏扫。

固定区和变动区的分工：

- 固定按钮 / 导航栏 / 稳定图标：学习 tight crop + context crop，执行时先截图匹配。
- 变动列表 / 正文 / 搜索结果：学习区域、滚动容器和实体模式，执行时只给模型区域截图和大致坐标。
- 表单流：学习步骤、字段类型、继续按钮、最终提交危险区；最终提交永远需要独立审核。

## 面板布局

### 左侧

左侧只负责工作流，不放系统工具列表。

学习模式建议：

- 绑定 / 截图
- 快速建图
- 深度校验
- 视觉资产
- 路径编辑
- 回归测试
- Trace 审计

执行模式建议：

- 当前状态
- 可用动作
- 定位预览
- 执行动作
- 滚动 / 输入
- 验证结果
- Trace 审计

系统设置放右下角齿轮入口，所有模式都可访问。

### 中间

中间是大路径图画布。

显示层级：

1. 软件 / 网站
2. 状态节点
3. 当前状态的区域泳道
4. 区域里的固定按钮、动态区、表单步骤
5. 点击某节点时展开子路径图

画布顶部应显示当前视觉资产校准条：

- `visual_asset_calibration_report_v1` 路径
- status
- matched / total
- fast lane count
- high risk match count
- final submit fast-lane count
- median / max visual recall ms

默认隐藏子路径，只显示区域摘要。点击区域后才展开该区域内部节点。

大画布交互规则：

- 默认显示软件/网站的状态图和当前状态的区域泳道。
- 子路径默认折叠，避免节点爆炸。
- 固定按钮以小截图缩略图呈现，不只是文字节点。
- 动态区显示为大 ROI 容器，不展开所有临时候选。
- 危险区使用独立边界和风险标签，不和普通按钮混在一起。
- 支持缩放、平移、搜索、按区域过滤和按风险过滤。

### 右侧

右侧是 Inspector。

点状态时显示：

- 状态识别规则
- 截图
- 区域列表
- 可用动作
- 上次 trace

点区域时显示：

- bbox hint
- scroll policy
- dynamic/fixed 类型
- 子节点列表
- 当前 ROI 截图

点按钮截图时显示：

- tight crop
- context crop
- 当前 ROI
- 当前 match crop
- 当前 calibration match 状态
- matched / ambiguous / threshold / scope
- match score
- score gap
- ambiguous / second-best evidence
- semantic action
- danger level
- 是否可走快路径
- 为什么允许或阻止

### 底部

底部是证据条，不参与主要布局：

- 当前截图
- crop 图
- overlay 图
- match 图
- trace 链接
- 最近一次 Gate 结果

## 编辑能力

最小 MVP 应支持：

- 修改 region 名称和类型。
- 修改 region bbox hint。
- 把按钮移动到另一个 region。
- 修改按钮 `semantic_action`。
- 修改按钮 `danger_level`。
- 标记按钮为 `fixed_visual_asset` 或 `dynamic_candidate`。
- 删除误学节点。
- 合并重复节点。
- 重新裁剪按钮截图。
- 保存为 `learned_interface_map_v1`。

所有编辑都要写 `path_graph_edit_trace_v1`，不能静默改图。

## SEEK 映射

SEEK 搜索结果页建议分成：

- `top_search_area`
  - 搜索框
  - 地点框
  - 筛选按钮
- `results_list`
  - 动态岗位卡片集合
  - 列表滚动容器
- `job_detail`
  - 详情头部
  - Apply / Quick apply
  - Save
  - 详情正文
  - 详情滚动容器
- `application_form`
  - 简历选择
  - 求职信
  - 雇主问题
  - SEEK profile step
  - review step
- `danger_zone`
  - Submit application
  - Send application
  - Complete application

`Apply / Quick apply` 是 `open_apply_flow`，不是 `final_submit`。

`Submit application` 永远是 `final_submit`，即使命中截图也必须人工/结构化审核。

## MVP 顺序

1. 本地截图 smoke：证明固定按钮 crop 可以生成、匹配、低风险快路径小于 1 秒。
2. SEEK artifact 导出：把已观察到的 Apply / Quick apply bbox 写入视觉资产 crop。
3. Trace 面板：显示 Visual Assets 阶段和 crop/match/ROI 图片。
4. 学习路径图面板第一版：按状态和区域展示，不再平铺所有子节点。
5. Inspector 第一版：点按钮能看截图和风险标签。
6. 编辑第一版：能改区域、按钮类型、危险等级，并保存。
7. SEEK 本地截图回归：不用鼠标，只用保存截图验证 quick apply / apply 召回。
8. SEEK live 校准：只做到 Apply Entry dry-run / observe，不点最终提交。

新增大画布 MVP：

1. 用 `learned_interface_map_v1` 作为主数据源，不再直接用旧平铺 PathGraph 绘图。
2. 画布只画 state、region、dynamic area、fixed visual asset、danger zone 五类节点。
3. 固定按钮节点必须能显示 tight crop 缩略图，并能从 Inspector 打开 source/current/match 图片。
4. 支持 operator 修改 region、按钮动作类型、危险等级、允许区域，并写编辑 trace。
5. 后续再做拖拽改布局和重新裁剪按钮截图，避免第一版又变成复杂且不稳定的交互。

## 当前实施状态

已完成第一片可验证能力：

- `scripts\visual_asset_local_smoke.py` 可以在本地合成 SEEK-like 截图，不抢鼠标，导出 `learned_interface_map_v1`。
- `learned_interface_map_v1` 已包含 states、regions、fixed visual assets、dynamic areas、danger zones 和 editor policy。
- 本地 smoke 会调用 `merge_visual_asset_match_evidence()`，把 Quick Apply 当前截图匹配证据回填进对应 fixed visual asset，包括 current ROI、current match、score、score gap、bbox、click point 和 candidate freshness。
- 本地 smoke 同时学习一个高危 `Submit application` 截图资产；它可以被匹配为证据，但必须标记 `semantic_action=final_submit`、`danger_level=final_submit`、`is_high_risk=true`，并保持 `fast_lane_allowed=false`、`can_authorize_click=false`。
- 本地 smoke 现在通过 `visual_asset_calibration_report_v1` 统一校准 fixed visual assets；最近一次离线结果中 Quick Apply 截图匹配耗时约 9ms，高危 Submit 匹配耗时约 11ms，`final_submit_fast_lane_count=0`。
- 已补“重复相似按钮”回归：如果两个低风险按钮截图过于相似，top1/top2 分数差不足会标记 ambiguous，并禁止 fast lane。
- Learn Replay 面板已增加 Interface Map 路径、加载按钮和保存按钮，可以显示区域摘要、固定按钮截图、动态 ROI 和危险区。
- 点击任意区域、固定按钮、动态 ROI 或危险区的 Inspect 可以查看详情，包括 source crop、source image、bbox/click point、scope、match policy、semantic action、danger level、fast-lane eligibility 和 raw JSON。
- 当前面板可以编辑区域 label/type，以及固定按钮的 semantic action、danger level、region，并通过 `/panel/save_interface_map` 保存到 `artifacts\interface-maps\`。
- 当前面板可以在固定按钮 Inspector 内按 source image + bbox 重新裁剪 tight/context crop；`/panel/crop_interface_asset` 会写 `learned_interface_map_asset_crop_trace_v1`，回填 crop 路径到当前地图，但仍保持 `can_authorize_click=false`，需要再次校准后才能作为当前截图候选。
- 保存会写 `learned_interface_map_edit_trace_v1`，并继续保持 `can_authorize_click=false`。
- 当前面板仍不是最终大画布编辑器；下一步才做区域拖拽、按钮重裁剪、导入最近一次 `visual_asset_recall_v1` 的 current ROI/current match 证据和显式编辑历史。

## 设计约束

- 白、灰、黑为主色。
- 状态色只用于状态，不做大面积装饰。
- 图不追求炫酷，优先可读、可编辑、可审计。
- 子路径默认折叠。
- 图片证据永远可点开。
- 大图区域要支持缩放、平移、搜索、按 region 折叠。
- Drag 只在按住拖动时生效，松手后布局稳定落位。
- 所有危险动作都必须在 UI 上有明显标签。
