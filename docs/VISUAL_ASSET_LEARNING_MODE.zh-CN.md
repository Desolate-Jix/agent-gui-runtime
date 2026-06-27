# Visual Asset Learning Mode

本文定义学习模式如何从界面中沉淀固定按钮、图标和稳定控件的截图资产，并让执行模式用这些资产快速召回候选。核心原则是：

```text
视觉资产只负责召回候选，不负责授权点击。
```

也就是说，`Quick apply`、`Apply`、`Continue`、`Next`、`Save`、常见图标按钮这类稳定控件，可以在学习模式里保存截图 crop。执行模式再次看到同类界面时，先用 OpenCV 模板匹配或相似图匹配找出当前截图里的 bbox 和 click point，再交给 OCR、PathGraph scope、action taxonomy、candidate freshness、`pre_click_decision_v1` 和 final-submit guard 审核。

## 模式分工

### Learn Fast

目标：快速生成当前页面可用的视觉资产草稿。

输入：

- 当前截图
- `screen_map_v1`
- OCR / UIA / DOM 证据
- PathGraph draft 中的按钮、输入框、卡片和导航节点

输出：

- `visual_asset_v1` 草稿
- tight crop：控件 bbox 加少量边距
- context crop：控件 bbox 加上下文边距
- source capture id、viewport size、DPI、browser zoom
- source bbox、source click point、click point relative policy
- semantic action 初判，例如 `open_apply_flow`

Learn Fast 产出的资产状态应为：

```json
{
  "asset_status": "draft_observed",
  "usable_for_recall": true,
  "can_authorize_click": false
}
```

### Learn Deep

目标：把草稿资产升级成可跨会话复用的稳定资产。

应额外完成：

- 多次截图确认控件稳定出现
- 生成不同 scale 的匹配策略
- 采集相似负样本，例如 `Save`、广告按钮、footer 按钮、final submit
- 绑定允许出现的 page type 和 container id
- 记录 expected text / negative text
- 校准 `min_score`、`score_gap_to_second`、NMS 和 scale range
- 明确 action taxonomy 和 danger level

Learn Deep 产出的资产状态应为：

```json
{
  "asset_status": "verified_stable",
  "usable_for_recall": true,
  "requires_gate": true,
  "can_authorize_click": false
}
```

## PathGraph 字段建议

`runtime_path_graph_v1` 应把视觉资产放在图级资产库中，节点只引用资产，不把图片内容直接塞进节点：

```json
{
  "visual_assets": {
    "contract_version": "visual_asset_store_v1",
    "assets": []
  },
  "nodes": [
    {
      "node_id": "seek.job_detail.quick_apply",
      "node_type": "action_element",
      "label": "Quick apply",
      "semantic_action": "open_apply_flow",
      "danger_level": "flow_entry",
      "container_id": "seek:job_detail",
      "visual_asset_refs": ["seek.quick_apply.primary.v1"],
      "requires_gate": true,
      "final_submit_guard_required": true
    }
  ]
}
```

单个资产建议记录：

```json
{
  "contract_version": "visual_asset_v1",
  "asset_id": "seek.quick_apply.primary.v1",
  "asset_type": "button_crop",
  "asset_status": "draft_observed",
  "label": "Quick apply",
  "semantic_action": "open_apply_flow",
  "danger_level": "flow_entry",
  "source": {
    "capture_id": "capture-id",
    "trace_path": "logs/traces/...",
    "coordinate_space": "source_capture_px",
    "screenshot_size": [1290, 1341],
    "window_rect": [0, 0, 1290, 1341],
    "dpi_scale": 1.25,
    "browser_zoom": 1.0
  },
  "source_geometry": {
    "bbox": [1000, 180, 1140, 225],
    "click_point": [1070, 203],
    "click_point_policy": "learned_relative_point",
    "click_point_relative": [0.5, 0.5]
  },
  "crop": {
    "tight_crop_ref": "artifacts/visual_assets/seek/quick_apply_tight.png",
    "context_crop_ref": "artifacts/visual_assets/seek/quick_apply_context.png",
    "padding_px": 6,
    "context_padding_px": 16,
    "hash": "sha256-or-average-hash",
    "phash": "perceptual-hash",
    "size_px": [140, 45]
  },
  "template_refs": {
    "tight_crop_ref": "artifacts/visual_assets/seek/quick_apply_tight.png",
    "context_crop_ref": "artifacts/visual_assets/seek/quick_apply_context.png",
    "source_image_path": "artifacts/screenshots/current_observe.png"
  },
  "match_policy": {
    "methods": ["gray_template", "edge_template", "ocr_confirm"],
    "scale_variants": [0.9, 1.0, 1.1],
    "min_score": 0.88,
    "min_score_gap": 0.06,
    "nms_iou": 0.4,
    "roi_policy": "last_known_then_container_then_page_region"
  },
  "scope": {
    "allowed_page_types": ["seek_job_detail"],
    "allowed_container_ids": ["seek:job_detail"],
    "expected_text": ["Quick apply", "Apply"],
    "negative_text": ["Submit", "Send application", "Complete application"]
  },
  "can_authorize_click": false
}
```

## 执行模式召回顺序

执行模式使用视觉资产时，应按下面顺序走：

```text
current capture
-> state_match / page_type
-> PathGraph node recall
-> visual_asset_match_v1 in ROI
-> OCR / UIA / DOM semantic confirm
-> candidate freshness check
-> pre-click gate
-> action taxonomy guard
-> scoped final-submit guard
-> click
-> post-click verification
```

当前实现状态：

- `POST /vision/observe_screen` 在 `agent_mode=learn` 时自动生成 `visual_asset_learning_v1`。
- Learn Mode 自动裁出的资产必须同时携带 `crop.*` 和 `template_refs.*`。`crop` 是资产自身的学习记录，`template_refs` 是 Interface Map、校准 CLI、面板 Inspector 和 Execute recall 的公共读取入口。
- 自动裁出的资产必须保留 `source_geometry.bbox`、`source_geometry.click_point`、`source_geometry.click_point_relative` 和 `source_is_authorization=false`。这些字段只用于审核、复裁和限定下次搜索 ROI，不能直接授权点击。
- `POST /vision/recognition_plan` 在执行识别计划开头运行 `visual_asset_recall_v1`。
- 召回会从请求 `metadata.visual_assets`、`metadata.visual_asset_learning.visual_assets`、或复用的 observe trace 里读取资产。
- `visual_asset_match_v1` 会对当前截图做灰度模板匹配和边缘模板匹配，支持多尺度搜索，并输出 top candidates、top1/top2 score gap、当前 ROI crop 和当前匹配 crop。
- 当前截图匹配成功后，召回结果会生成带 `candidate_freshness` 的 `seeded_candidate_v1`。
- 对低风险动作，例如 `open_apply_flow` / `Quick apply`，可启用 reviewed seeded-candidate 快路径，跳过 VISTA 点定位。
- 对 `final_submit` / `send` / `confirm` / payment 类资产，即使命中模板，也只作为证据写入 trace，不进入快路径。
- Trace 中应查看 `visual_asset_recall`、每个 match 的 `current_roi_ref` / `current_match_ref` / `match_method` / `score_gap_to_second`，以及 `execution_path.visual_asset_recall_status` 和 `execution_path.visual_asset_fast_lane_used`。
- 面板 Trace Inspector 会把 `visual_asset_recall_v1` 渲染成 `Visual Assets` 阶段，并把 `template_path`、`current_roi_ref`、`current_match_ref` 作为图片证据预览。

搜索 ROI 的优先级：

1. 上次同节点的 bbox 附近，仅作为搜索区域。
2. PathGraph 允许的 container bbox。
3. 当前 page type 的典型区域。
4. 全屏 fallback，只允许低风险动作使用。
5. 无候选、低分或歧义时，才进入 VISTA / 大模型定位 fallback。

## 防旧坐标混用

视觉资产必须遵守 candidate freshness contract：

- source bbox 和 source click point 永远不能直接点击。
- last known bbox 只能用来限定搜索 ROI。
- `visual_asset_match_v1` 必须绑定 current capture id。
- click point 必须从 current matched bbox 重新计算。
- 当前截图尺寸、窗口 rect、DPI、browser zoom 与资产来源不一致时，应降低置信度或进入 fallback。
- trace 必须同时记录 source bbox 和 current matched bbox。

## 按钮截图策略

MVP 推荐：

- tight crop：bbox 加 `4px..8px`。
- context crop：bbox 加 `12px..20px`。
- 保留原始 crop，同时生成高度归一化版本，例如 `32px / 40px / 48px`。
- 默认 scale：`0.9, 1.0, 1.1`。
- DPI / zoom 变化时扩展到 `0.85, 0.9, 1.0, 1.1, 1.25, 1.5`。
- 先做灰度模板匹配，再加 edge template 辅助，最后用 OCR / UIA / DOM 做语义确认。

不要把动态内容做成固定模板，例如职位标题、公司名、薪资和正文描述。这些应继续走 OCR、结构化读取和语义判断。

## 动作安全分类

固定按钮截图必须绑定动作类型：

- `open_apply_flow`：`Apply` / `Quick apply`，只表示进入申请流程。
- `continue_next_step`：`Continue` / `Next`，只表示当前表单下一步。
- `fill_field`：输入、选择、勾选等安全填写动作。
- `possible_final_submit`：可能提交、发送、确认、支付的按钮。
- `final_submit` / `send` / `confirm` / `payment`：必须强拦。

`Apply` 在岗位详情页可以是 `open_apply_flow`，但在申请表单、最终 Review 或 footer 区域出现时必须重新按当前 flow scope 判断，不能复用旧语义。

## Trace 证据

每次视觉资产召回应写入：

- asset id
- source capture id
- current capture id
- source crop path
- current ROI path
- current match crop path
- matched bbox
- click point
- match method
- match score
- score gap
- scale used
- top candidates
- ROI used
- OCR text in bbox
- expected / negative text result
- container scope result
- page type result
- semantic action
- danger level
- gate decision
- final-submit guard result

overlay 应显示：

- source crop 缩略图
- current ROI 框
- matched bbox
- click point
- top-2 候选框
- OCR 文字框
- Gate 结果和拒绝原因

## 最小 MVP

第一阶段只做一个受控目标：

```text
SEEK job_detail 页面里的 Quick apply / Apply
```

验收条件：

- Learn Fast 能保存 `Quick apply` / `Apply` 的 tight/context crop。
- Learn Deep 能把资产标成 `verified_stable` 或保持 `draft_observed` 并说明原因。
- Execute Mode 能在当前截图里用资产召回新的 bbox/click point。
- 召回结果可以生成 `seeded_candidate_v1`，但 `can_authorize_click=false`。
- 候选仍必须通过 OCR/scope/action taxonomy/Gate/final-submit guard。
- `Submit application`、`Send`、`Confirm`、payment 不允许被视觉资产自动授权。
- trace 和 overlay 能看出本次点击点来自当前截图匹配，而不是旧截图坐标。


## ?????? 2026-06-24

`observe_screen` ??????????? Learn Mode ????

- `visual_asset_learning` ??????????????
- `learned_interface_map` ??????????????? ROI ??????????????
- ??????? `region_id`???????? `children.fixed_visual_asset_refs`?
- ??????????????????????? `status=skipped` ???????? screen reading / Learn Deep ?????

???????

1. ????????? `region_id`?
2. ???? `scope.allowed_region_ids`?
3. ??? `scope.allowed_container_ids`?????? screen map ? `section_id`?
4. ???????? bbox ??? bbox ????????

???????

- `Submit` / `Send application` / `Confirm` / `Payment` ?????? `button`?`icon_button`?`menu_item` ? `link` ???????????????????
- ??????????????? `Review and submit` ????????????
- ???????? `can_authorize_click=false`???????????? Gate ???

???? SEEK trace?

- `D:gent-gui-runtime\logs	racesision60624-234240-146649__learn-mode-fast-observe__seek.json`
- `asset_count=4`?`region_count=3`?`danger_zone_count=0`?


## ??????? 2026-06-24

`recognition_plan` ????????????????

- `visual_asset_learning.visual_assets`
- `learned_interface_map.fixed_visual_assets`

????????/??????????????????????????? Learn trace??????

1. ? `template_refs.tight_crop_ref` ?????????
2. ? `source_geometry.bbox` ?????? ROI?
3. ? `region_id` / `allowed_region_ids` ?? ROI `container_id`?
4. ???????????? fresh bbox / click point?
5. ?? `seeded_candidate_v1`?? `candidate_freshness.source=visual_asset_match_v1`?
6. ???????? `allow_seeded_candidate_without_model=true`????? VISTA?
7. ?????? `can_authorize_click=false`????????????scope?Gate ? final-submit guard?

SEEK saved-image dry-run ???

- `click Job search` recognition plan ? `252ms`?
- ????? `411ms`?
- `visual_asset_fast_lane_used=true`?`vista_point_grounding_used=false`?


## 2026-06-25 低风险视觉资产快车道执行规则

低风险视觉资产快车道现在不只是 dry-run 预览，也进入了真实执行路径，但条件非常窄：

- 识别计划必须来自当前截图的视觉资产匹配：`visual_asset_fast_lane_used=true`。
- pre-click gate 必须已经允许。
- 候选必须有当前截图中的 bbox / click point / freshness 证据。
- 目标文本不能命中 final submit / send / confirm / payment 类危险语义。
- dry-run 仍然渲染 overlay；真实点击才跳过 overlay，以节省时间。
- 真实点击的 trace 必须写入：
  - `execution_path.low_risk_visual_fast_lane`
  - `execution_path.recognition_plan_overlay_rendered`
  - `effective_execution_options.click_timing`

当前 SEEK 外部 Edge 实测：

- 目标：`click Job search`
- Action trace：`D:\agent-gui-runtime\logs\traces\actions\20260625-000813-564299__execute-mode-click__seek.json`
- Recognition trace：`D:\agent-gui-runtime\logs\traces\vision\20260625-000813-421299__execute-mode-recognition-plan__seek.json`
- runtime 总耗时：`980.725ms`
- `capture_live_window=720.460ms`
- `recognition_plan=190.464ms`
- `click_point=67.380ms`

结论：

- 学过的固定按钮可以不再走 VISTA 点定位。
- 1 秒内的主要瓶颈已经从模型定位转移到实时截图。
- 下一步需要在学习模式里把固定按钮截图、固定区域、动态 ROI 和危险按钮标签保存成可编辑路径图，同时在执行模式里定义短 TTL fresh capture 复用规则。


## 2026-06-25 视觉资产审核分级

学习模式现在会给固定按钮截图写入 `review_policy`，供路径图、面板和执行模式直接读取：

- `low_risk_fast_lane_eligible`：普通固定导航 / 搜索 / 打开类按钮。可以走低风险视觉快车道，目标是大约 1 秒内完成，不继续牺牲稳定性去死扣几十毫秒。
- `gate_required`：申请入口、继续下一步等流程按钮。它们不是最终提交，但仍需要 scope / OCR / Gate 校验，不进入低风险绿色快车道。
- `manual_review_required`：`Submit application`、`Send`、`Confirm`、`Payment`、`Complete application` 等高危按钮。截图只作为证据，必须结构化审核后才允许点击，且不能被视觉资产自动授权。

`learned_interface_map.fixed_visual_assets[*]` 会透传：

- `review_policy`
- `click_permission`
- `fast_lane_eligible`
- `can_authorize_click=false`

`learned_interface_map.danger_zones[*]` 也会保留同一份 `review_policy`，方便面板把高危按钮单独显示出来。
