# Observe Operation Service Boundary Design

## 背景

Learn Worker 已经通过中立的 Learn task service 执行模型复核、识别草稿和两阶段理解，但下面两个分支仍直接导入 API：

```text
Learning Worker
  -> app.api.models.request
  -> app.api.vision.observe_screen / locate_target
```

这使后台任务依赖 FastAPI transport、`APIResponse` 和一个超过九千行的 API 模块。Windows `multiprocessing.spawn` 会在子进程重新加载这些依赖，也让 Operation、Learn 和 HTTP 的职责边界难以验证。

只读审计得到：

- `observe_screen` 直接依赖 16 个本地 helper；传递闭包包含 106 个 helper，约 2,598 行。
- `locate_target` 直接依赖 19 个本地 helper；传递闭包包含 171 个 helper，约 5,816 行。
- `locate_target` 同时包含普通精准定位、Learn 全目标校准、VISTA、rerank、预点击证据和 PathGraph review，风险显著高于 Observe。
- `app.learn.calibration_sequence` 也直接调用 `app.api.vision.locate_target`。
- `app.api.action` 仍通过 API 函数复用 Observe、recognition plan 和 overlay。

因此本轮不能把 Observe 和 Locate 一次搬走，也不能增加一层仍然反向导入 `app.api.vision` 的假 service。

## 目标

第一阶段只整理 Observe：

```text
API adapter ───────────────┐
                           ├─> Observe application task
Learn Worker adapter ──────┘
                                  |
                     Operation base observation
                                  |
                     Learn observation enrichment
```

完成后：

- Operation 原始观察负责截图来源、OCR/UIA/视觉理解、运行上下文和基础 Trace 数据。
- Learn 增强负责 `screen_map`、学习 PathGraph 候选、deep review 和视觉资产。
- API 只负责请求校验、兼容转换和 `APIResponse`。
- Learn Worker 不再为了 `vision_observe_screen` 加载 `app.api.*`。
- Locate 保持原状，等待独立设计和回归检查点。

## 非目标

- 不迁移 `locate_target`、`recognition_plan` 或 VISTA 定位链。
- 不修改 Execute、Gate、final-submit、点击、输入、滚动或真实动作授权。
- 不启动模型，不更换模型配置，不调整 prompt。
- 不改变 `/vision/observe_screen` 路由、公开字段、OpenAPI 名称或响应 JSON。
- 不改变 Trace operation 名称、截图来源优先级、PathGraph 非授权语义或视觉资产策略。
- 不删除现有兼容 import，除非静态引用和回归测试都证明没有调用者。

## 设计

### 1. 中立合同

新增 `app.operation.observe.contracts`：

- `ObserveScreenTaskInput`
- `ObserveScreenTaskResult`
- `ObserveScreenTaskFailure`

合同只依赖 Pydantic 和 Operation/通用 schema，不导入 FastAPI、`APIResponse`、`ErrorModel` 或 `app.api.*`。

`app.api.models.request.VisionObserveScreenRequestModel` 暂时保留公开名称，并通过显式转换构建 `ObserveScreenTaskInput`。这样不改变 OpenAPI、旧 import 和校验错误位置。

### 2. Operation base observation

新增 `app.operation.observe.service`，负责：

1. 解析保存截图或绑定窗口截图；
2. 创建 `operation_context`；
3. 运行现有 screen reading；
4. 在主路径失败时生成现有 degraded observation；
5. 返回图像身份、OCR/UIA/模型结果、运行上下文和 timing；
6. 不生成 Learn PathGraph，不授权执行。

截图绑定和 capture freshness 规则必须保持原样。降级结果必须明确记录，不得把模型失败伪装成完整理解。

### 3. Learn observation enrichment

把 Learn 专属逻辑拆到 `app.learn.observe_enrichment` 及其小模块：

- `screen_map_builder.py`：构建 sections、candidates、cards 和风险标记；
- `observe_path_graph.py`：只读学习 PathGraph 候选和 screen-map 对齐；
- `observe_deep_review.py`：deep review 与 ElementMemory 初始化计划；
- `observe_visual_assets.py`：视觉资产裁剪和 learned interface map。

这些模块可依赖 Operation 的原始观察结果，但 Operation 不反向依赖 Learn。

### 4. 应用任务与适配器

新增 `app.learn.workflow_tasks.observe.run_observe_task()`：

```text
ObserveScreenTaskInput
  -> Operation base observation
  -> optional Learn enrichment
  -> ObserveScreenTaskResult
```

API adapter 将结果映射回现有 `APIResponse`。Worker 直接验证中立 input 并序列化 task result 的兼容响应，不导入 `app.api.*`。

### 5. Trace 与错误

- Operation service 返回结构化阶段结果和原始异常分类。
- Learn task 负责 `observe_screen` 业务 Trace payload。
- API adapter 只映射错误，不吞异常，不重新解释成功状态。
- 现有 `trace_path`、`timings`、`model_io` 和失败 code 必须由 characterization tests 冻结。

### 6. 安全边界

- Observe 始终是 `read_only`，`requires_gate=false`。
- 结果中的 PathGraph、screen map、visual assets 和建议动作都不是执行授权。
- 点击仍只能通过 `POST /action/execute_recognition_plan`。
- 本轮不改变 action taxonomy、candidate freshness 或 final-submit guard。

## 实施顺序

1. 先冻结 Observe API、Worker、Trace 和 degraded-path 行为。
2. 提取中立合同，不改变调用路径。
3. 提取 Operation base observation，并让旧 API 调用它。
4. 分批迁移 Learn enrichment helper，每批运行相关测试。
5. 新增 Observe task service 和兼容 adapter。
6. 切换 Worker 的 `vision_observe_screen` 分支。
7. 用干净子进程证明该分支没有加载 `app.api`。
8. 保留 Locate 现状并为下一轮记录依赖清单。

## 验收

- `/vision/observe_screen` 成功、失败、degraded 和 deep 结果与旧合同一致。
- 保存截图覆盖和 live capture 都可复跑。
- Trace 路径、operation 名称、timings、model I/O 失败字段不变。
- Worker 子进程执行 Observe 时 `sys.modules` 中不存在 `app.api`。
- `app.operation.observe.*` 不导入 `app.learn.*` 或 `app.api.*`。
- 所有真实动作计数保持为零，本轮没有 live click、fill 或 submit。
- 相关测试、完整测试、语法检查和 Panel health 通过。

## 后续

Locate 必须另立设计。它至少需要拆成：

1. 通用精准定位；
2. Learn 全目标校准；
3. VISTA/ROI/rerank；
4. pre-click evidence；
5. Learn PathGraph review。

在这些边界和回归测试形成前，不迁移 Locate，也不使用兼容 fallback 掩盖 API 耦合。
