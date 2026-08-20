# Locate Operation Service Boundary Audit

## 实施状态

第一实现检查点已完成：

- 已新增 `app.operation.locate` 的 transport-neutral contracts；
- 已新增普通单目标 `run_single_target_locate()`；
- API 普通 Locate 分支已改用该服务；
- rejected review candidate、bbox/point、Observe evidence、no-click 和失败上浮
  已有独立回归；
- API 内三个重复定位归一化 helper 已删除；
- Learn 全目标校准尚未移动，Worker 和 calibration sequence 的 API 依赖仍保留。

验证结果为聚焦 `117 passed`、全仓库 `2188 passed, 1 skipped`，没有启动模型
或执行真实 GUI 动作。

## 结论

`Locate` 适合成为方案 A 的下一个单模块整理点，但不能直接把
`app.api.vision.locate_target()` 整段移动到 `app.operation`。

当前入口只有 267 行，却同时包含两条不同路径：

1. 普通单目标精准定位；
2. Learn Mode 全目标校准和模型复核。

二者还共同承担截图来源解析、Observe Trace 复用、Operation context、
PathMap review、Trace 写入和 HTTP 响应包装。安全整理必须先冻结行为，再把
中立定位能力、Learn 增强和 API 适配分开。

## 当前调用链

```text
HTTP POST /vision/locate_target
  -> app.api.vision.locate_target

Learn Worker task vision_locate_target
  -> app.learn.workflow_worker
  -> app.api.models.request.VisionLocateTargetRequestModel
  -> app.api.vision.locate_target

Learn calibration sequence
  -> app.learn.calibration_sequence._run_locate_target
  -> app.api.models.request.VisionLocateTargetRequestModel
  -> app.api.vision.locate_target
```

`workflow_worker` 和 `calibration_sequence` 因而依赖 API transport。与已经
整理的 Observe 不同，Locate 还会调用 `recognition_plan()`，所以不能通过
增加一个反向导入 `app.api.vision` 的包装器来宣称完成分层。

## 当前职责

### 共同职责

- 解析保存截图或实时绑定窗口截图；
- 创建 read-only Operation context；
- 绑定 `capture_id`、`viewport_size` 和证据引用；
- 复用 checksum/goal 对齐的 Observe Trace；
- 记录 timing、Operation trace link 和 vision Trace；
- 明确 `action_executed=false`；
- 返回兼容的 `target_location_v1`。

### 普通 Locate 路径

- 构造 `VisionRecognitionPlanRequestModel`；
- 运行 OCR、视觉候选、rerank 和 pre-click evidence 所在的
  `recognition_plan`；
- 从正式推荐候选或 review 候选取得 bbox/point；
- 生成 `path_map_review_v1`；
- 只返回定位证据，不执行点击。

### Learn 全目标路径

- 识别 `metadata.learn_all_targets`；
- 读取 Learn grounding/VISTA 配置；
- 可选运行 Learn model review；
- 应用 add/update/remove delta；
- 从 screen map 构造全目标和 review boxes；
- 执行 VISTA 坐标验证；
- 生成校准 overlay、PathMap review 和 Learn location status。

### API 适配职责

- 验证 `VisionLocateTargetRequestModel`；
- 转换 `APIResponse`、`VisionResultData` 和 `ErrorModel`；
- 保留公开路由和旧响应消息。

## 必须保持的契约

1. Locate 始终是 no-click；任何结果都不得授权真实动作。
2. `capture_id`、`viewport_size`、source、bbox、point 和 freshness 不得跨截图混用。
3. 普通 Locate 只产生 pre-click evidence；真实动作仍只能进入
   `POST /action/execute_recognition_plan`。
4. Learn 全目标、review boxes、overlay 和 PathMap review 都是只读资产。
5. rejected review candidate 可以用于人工复核，但不能伪装成 click success。
6. 模型失败、协议错误、截图漂移和候选生成错误必须显式失败，不能由兼容层吞掉。
7. Gate、final-submit、send、confirm、payment 和其他危险动作规则不在本次重构范围。
8. Trace operation 名称、错误 code、响应消息和现有 JSON 字段必须兼容。

## 建议边界

```text
API adapter ───────────────────────┐
                                   ├─> Locate application task
Learn Worker adapter ──────────────┤
Calibration sequence adapter ──────┘
                                          |
                            Operation single-target locate
                                          |
                         optional Learn calibration enrichment
```

### `app.operation.locate`

中立 Operation 层只负责：

- transport-neutral Locate input/result/failure contract；
- 图片身份和 Operation runtime context；
- 单目标 recognition-plan 定位；
- bbox/point 和 pre-click evidence 归一化；
- no-click execution evidence。

它不得依赖 `app.learn`、FastAPI、`APIResponse` 或 Panel。

### `app.learn.locate_enrichment`

Learn 层负责：

- `learn_all_targets` 请求判定；
- screen map model review；
- review delta；
- VISTA 全目标校准；
- review-only overlay；
- Learn PathMap review 和 location status。

### `app.learn.workflow_tasks.locate`

应用任务负责选择普通 Locate 或 Learn enrichment，并返回 transport-neutral
结果。Worker 和 calibration sequence 都调用这里，不再导入 `app.api.*`。

### API adapter

公开路由保留原名称和 schema，只做：

- API request 到中立 task input 的显式转换；
- task result/failure 到旧 `APIResponse` 的兼容转换；
- HTTP 边界上的验证错误表达。

## 最小实施顺序

1. 新增 characterization tests，冻结普通定位、review candidate、Observe
   Trace 复用、Learn review boxes、VISTA 状态、失败 Trace 和 no-click 字段。
2. 新增 transport-neutral contracts，不改变现有调用方。
3. 提取普通单目标 Locate service，路由仍调用旧适配器。
4. 提取 Learn calibration enrichment。
5. 新增共享 Locate application task。
6. 切换 Worker 和 calibration sequence，增加干净子进程断言：
   `vision_locate_target` 不加载 `app.api.*`。
7. 最后缩减 API 路由；公共路由、请求模型和响应字段保持兼容。

每一步只做一个职责边界，并运行对应的最窄回归。任何 candidate freshness、
pre-click evidence、Trace 或 no-click 差异都应阻止继续拆分。

## 当前验证基线

- `locate_target`：`app/api/vision.py:6067-6333`，267 行。
- 直接调用 19 个同文件 helper，并调用同文件 `recognition_plan()`。
- 两个非 HTTP 生产调用方仍直接导入 API。
- Locate、Learn Worker、校准序列和 task-boundary 相关测试：
  `114 passed`。
- 模型进程：`0`；没有真实 GUI 动作。
- codegraph 在本次审计中返回 `Transport closed`，因此调用链使用 AST 和
  精确文本引用扫描确认。

## 本检查点不做

- 不移动 Locate 生产代码；
- 不更改模型、prompt、batch、timeout 或 VISTA 参数；
- 不启动模型；
- 不运行真实 GUI 流程；
- 不修改 Execute、Gate 或 final-submit；
- 不删除兼容请求模型、路由、Trace 或回归 fixture。
