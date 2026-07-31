# Learn Worker Service Boundary Design

## 背景

`app.api.panel` 在模块加载时导入 `app.learn.workflow_worker`。Worker 在子进程执行以下任务时，又动态导入 `app.api.panel` 的请求模型和 route endpoint：

- `panel_learning_recognition_trial`
- `panel_learning_two_stage_understanding`
- `panel_learning_model_review_repair`

这不会必然造成 Python 导入崩溃，但形成了职责反向依赖：

```text
Panel API -> Learn Worker -> Panel API
```

Worker 因此依赖 HTTP adapter、Panel 本地 helper 和 API 响应结构。Windows `multiprocessing.spawn` 会在子进程重新导入这些模块，使这种耦合同时影响启动、错误映射和测试隔离。

## 目标

将依赖方向调整为：

```text
Panel API adapter ─┐
                   ├─> Learn task application service
Worker adapter ────┘
```

Panel 负责 HTTP 合同和 `APIResponse` 转换；Worker 负责进程、租约、取消、结果持久化和 adoption；Learn task service 负责只读学习任务。

## 非目标

本轮不做以下工作：

- 不修改 Execute Mode。
- 不修改 Gate、final-submit、点击、输入、滚动或真实动作授权。
- 不启动或更换模型。
- 不改变 Panel 路由路径、公开请求字段或响应 JSON。
- 不顺便拆分整个 `app/api/panel.py`。
- 不迁移 benchmark、SEEK Profile、PathGraph promotion 或人工审核功能。
- 不删除兼容入口。

## 设计原则

### 1. 公共 API 模型保持原位

现有 `PanelRunLearning*Request` 类暂时保留在 `app.api.panel`。这样可以保持：

- 旧 import 路径；
- OpenAPI component 名称；
- Pydantic validation 错误位置；
- 现有测试和外部调用；
- multiprocessing/pickle 可见模块路径。

Panel adapter 使用 `request.model_dump()` 显式转换为 Learn task input。Learn Worker 使用同一份 Learn task input 验证原始 payload。

### 2. Learn 合同不模拟 HTTP

新增 `app.learn.workflow_contracts`，提供：

```python
class LearningTaskFailure(BaseModel):
    code: str
    details: str


class LearningTaskResult(BaseModel):
    outcome: Literal["completed", "safe_stopped", "failed"]
    payload: dict[str, Any]
    failure: LearningTaskFailure | None = None
```

每个任务有独立 input：

- `ModelReviewTaskInput`
- `RecognitionTaskInput`
- `TwoStageTaskInput`

`LearningTaskResult` 不包含 HTTP 状态码、FastAPI `Request`、`HTTPException` 或 `APIResponse`。

### 3. 兼容响应由 adapter 生成

新增 `app.learn.workflow_task_result_adapter`，提供临时兼容函数：

```python
def model_review_result_to_legacy_response(
    result: LearningTaskResult,
) -> dict[str, Any]:
    ...
```

它只负责把中立 task result 映射为当前 `APIResponse.model_dump(mode="json")` 等价结构。Panel 和 Worker 都调用这个 adapter，避免两处复制错误消息和缺省值。

该 adapter 是兼容桥，不是 Learn service 的正式返回合同。

### 4. Application service 不依赖 API

新增包：

```text
app/learn/workflow_tasks/
    __init__.py
    model_review.py
    recognition.py
    two_stage.py
```

每个 service：

- 接收强类型 task input；
- 接收显式 `project_root`；
- 返回 `LearningTaskResult`；
- 不导入 `app.api.*`；
- 不返回 `APIResponse`；
- 不执行真实点击、填写或提交；
- 保持当前异常到 safe-stop/failure 的映射。

### 5. Worker 只负责调度和生命周期

`execute_learning_stage_worker_task()` 继续：

1. 校验 task kind；
2. 执行模型资源 preflight；
3. 调用对应 Learn task service；
4. 通过兼容 adapter 生成当前 worker response；
5. 交给现有 worker result envelope 保存。

Worker 的取消、超时、result adoption、摘要校验和 identity 校验不变。

## 分步迁移

### Checkpoint 0：冻结现有行为

先增加 characterization tests，覆盖：

- model review route 的成功和失败 JSON；
- model review Worker 的同输入结果；
- Trace 写入；
- 模型 preflight 顺序；
- Worker envelope status；
- 安全计数和禁止执行字段。

### Checkpoint 1：Model Review

先抽离最小的 `model review/repair`：

```text
Panel request
  -> ModelReviewTaskInput
  -> run_model_review_task()
  -> LearningTaskResult
  -> legacy response adapter
  -> APIResponse
```

Worker 使用相同 service 和 adapter。完成后，Worker 的 model-review 分支不得导入 Panel。

### Checkpoint 2：Recognition

抽离 recognition task 以及仅由它使用的 helper。共享 helper 只有在两个以上 application service 都需要时才进入公共模块。

### Checkpoint 3：Two Stage

最后抽离 two-stage orchestration。它依赖 observe bundle、layout graph、surface rules、overlay 和 artifact 保存，因此必须在前两个 checkpoint 已稳定后处理。

### Checkpoint 4：边界封闭

删除 `workflow_worker` 对所有 `app.api.*` 的动态导入，增加静态和运行时边界测试。

## 兼容合同

以下内容必须保持不变：

- `/panel/run_learning_recognition_trial`
- `/panel/run_learning_two_stage_understanding`
- `/panel/run_learning_model_review_repair`
- 现有 Panel request 字段、默认值、约束和 OpenAPI schema
- `APIResponse` 的 `success/message/data/error`
- Worker result envelope、adoption 和 digest
- 模型资源 preflight 与模型关闭时行为
- Trace category、operation 和关键 payload

## 安全不变量

每个迁移任务必须显式断言：

```text
real_clicks == 0
target_app_clicks == 0（字段存在时）
live_fills == 0
live_submits == 0
runtime_promotions == 0（字段存在时）
final_submit_forbidden == true（字段存在时）
artifact_is_authorization == false（字段存在时）
execute_binding_enabled == false（字段存在时）
```

缺少某个原本存在的安全字段属于回归，不能通过降低断言解决。

## 错误处理

- Panel task 的业务失败继续转换为当前失败响应，不让异常无意升级为 HTTP 500。
- Worker 模型资源 preflight 失败继续形成 Worker failure，不伪装成已完成 task。
- Task service 内的业务异常转换为 `LearningTaskFailure`，保留当前错误 code 和 details。
- Worker 生命周期异常仍由 `_run_learning_stage_worker_entry` 捕获并写入 result envelope。
- 不增加隐藏主路径失败的 fallback。

## 验证

### 静态边界

检查以下生产子图：

- `app.learn.workflow_worker`
- `app.learn.workflow_contracts`
- `app.learn.workflow_task_result_adapter`
- `app.learn.workflow_tasks.*`

不得直接、动态或通过字符串模块名引用 `app.api.*`。

### 运行时边界

在干净 Python 子进程中仅导入并执行 Worker task，断言：

```python
"app.api.panel" not in sys.modules
```

### 双入口一致性

同一 task input 经 Panel 和 Worker 执行时，核心 application result 必须一致。允许差异仅限于 HTTP envelope 和 Worker lifecycle envelope。

### 回归范围

每个 checkpoint 运行：

1. 新增的 focused tests；
2. `tests/test_learning_workflow_stage_worker.py`；
3. 对应 Panel route tests；
4. `python -m py_compile`；
5. 完整 `pytest tests -q`；
6. 面板健康检查。

## 完成标准

仅在以下条件全部满足时，阶段 4 才算完成：

- 三个任务都由 Learn application service 承担；
- Panel 只做 HTTP adapter；
- Worker 只做 task dispatch 和生命周期；
- Learn task 生产子图不依赖 `app.api.*`；
- route/schema/response/Trace/Worker envelope 均通过兼容回归；
- 全部安全不变量通过；
- 模型未因离线测试意外启动；
- 完整测试通过。
