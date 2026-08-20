# 操作路径图规范

本文档定义 `runtime_path_graph_v1`。它用于把一次 agent 运行的证据、决策、动作和验证过程表达成节点关系图，供测试面板、回归测试、自学习系统和人工复盘使用。

## 设计原则

操作路径图不是 AI 凭空生成的解释图，也不是根据仓库文件结构生成的项目结构图。

它的来源应该是确定性的运行数据：

- API response
- recognition/action trace
- screenshot artifact
- OCR/UIA/vision/candidate/pre-click/timing/verification contract
- approved plan 或未来 learning record

AI 可以参与两个非权威环节：

- 把节点标签翻译成人更容易读的短语
- 根据已有节点和边生成自然语言复盘摘要

AI 不应该决定是否存在某个关键节点、某条安全边、某个点击点或某个验证结论。关键事实必须来自 runtime 结构化数据。

## 当前测试面板版本

当前 Tkinter 测试面板里的动态路径图是即时派生视图：

```text
latest API response -> deterministic parser -> nodes/edges -> Tk Canvas force graph
```

也就是说，它现在不是读取一个单独的 `runtime_path_graph_v1` 文件，而是从最新 API 返回内容中抽取节点：

```text
goal
screen capture
OCR evidence
UIA evidence
vision evidence
candidate rank
narrow search
pre-click gate
approved plan
target point
real click
post-click verification
timings
trace artifact
```

后续学习模式可以把同一套结构持久化为 `path_graph.json`。

## 推荐文件位置

单次成功/失败运行可保存为：

```text
logs/path-graphs/
  20260531-xxxx__execute-recognition-plan__browser.json
```

学习记录可内嵌或旁挂：

```text
logs/learned-actions/
  browser/
    google-search-result/
      20260531-xxxx/
        record.json
        path_graph.json
        before_full.png
        target_crop.png
        context_crop.png
        after_click.png
```

## 顶层结构

```json
{
  "contract_version": "runtime_path_graph_v1",
  "graph_id": "20260531-xxxx__execute-recognition-plan__browser",
  "created_at": "2026-05-31T12:00:00Z",
  "goal": {
    "normalized": "Click the first organic Google search result title",
    "original": "搜索 ai 的最新进展，点击第一个链接"
  },
  "context": {
    "app_name": "browser",
    "operation": "execute_recognition_plan",
    "window": {
      "process_name": "msedge.exe",
      "title": "Google - Microsoft Edge",
      "handle": 123456,
      "size": [1280, 720]
    }
  },
  "sources": {
    "response_trace_path": "logs/traces/actions/...",
    "recognition_trace_path": "logs/traces/vision/...",
    "before_screenshot": "artifacts/screenshots/...",
    "after_screenshot": "artifacts/screenshots/..."
  },
  "nodes": [],
  "edges": [],
  "layout": {
    "kind": "force",
    "hints": []
  }
}
```

## Node 结构

每个节点表示一个事实、证据、决策、动作或产物。

```json
{
  "id": "pre_click_gate",
  "type": "gate",
  "label": "Pre-click gate",
  "status": "passed",
  "summary": "1 candidate allowed",
  "data_ref": {
    "path": "data.result.pre_click_decision",
    "trace_path": "logs/traces/actions/..."
  },
  "bbox": null,
  "point": null,
  "metrics": {
    "allowed_candidate_count": 1
  }
}
```

### Node 字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | 图内唯一 ID。稳定、短、可被 edge 引用。 |
| `type` | string | 节点类型。见下方枚举。 |
| `label` | string | 面板显示用短标签。可以由 runtime 生成，也可以由 AI 翻译，但不能改变事实。 |
| `status` | string | 节点状态。用于颜色和安全判断。 |
| `summary` | string/null | 简短摘要。 |
| `data_ref` | object/null | 指向原始 response/trace 字段。 |
| `bbox` | object/null | 如果节点对应屏幕区域，使用 `{x,y,w,h}` 或 `{x,y,width,height}`。 |
| `point` | object/null | 如果节点对应点击点，使用 `{x,y}`。 |
| `metrics` | object | 计数、耗时、分数等。 |

### Node type 枚举

```text
goal
screen_capture
evidence
ocr_evidence
uia_evidence
vision_evidence
candidate_rank
narrow_search
gate
approved_plan
target
action
verification
timing
trace_artifact
learning_record
fallback
error
```

### Status 枚举

```text
pending
observed
passed
blocked
executed
verified
failed
skipped
reused
neutral
```

## Edge 结构

边表达节点之间的依赖、支持、筛选、执行或验证关系。

```json
{
  "from": "candidate_rank",
  "to": "pre_click_gate",
  "relation": "checked_by",
  "status": "passed",
  "weight": 1.0,
  "reason": "Top candidate passed local grounding and margin checks"
}
```

### Edge 字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `from` | string | 起点 node id。 |
| `to` | string | 终点 node id。 |
| `relation` | string | 关系类型。 |
| `status` | string | 关系状态。 |
| `weight` | number/null | 可选权重，用于布局或置信度显示。 |
| `reason` | string/null | 可解释说明。 |

### Relation 枚举

```text
requires
produces
supports
refines
rejects
checks
selects
approves
reuses
drives
executes
verifies
measures
writes
falls_back_to
```

## 最小示例

```json
{
  "contract_version": "runtime_path_graph_v1",
  "graph_id": "demo",
  "goal": {
    "normalized": "Click close window button",
    "original": "关闭窗口"
  },
  "nodes": [
    {"id": "goal", "type": "goal", "label": "Goal", "status": "observed"},
    {"id": "screen", "type": "screen_capture", "label": "Screen capture", "status": "observed"},
    {"id": "ocr", "type": "ocr_evidence", "label": "OCR x113", "status": "observed"},
    {"id": "vision", "type": "vision_evidence", "label": "Vision grounding", "status": "observed"},
    {"id": "candidate", "type": "candidate_rank", "label": "Candidate rank", "status": "passed"},
    {"id": "gate", "type": "gate", "label": "Pre-click gate", "status": "blocked"},
    {"id": "trace", "type": "trace_artifact", "label": "Trace file", "status": "observed"}
  ],
  "edges": [
    {"from": "goal", "to": "screen", "relation": "requires", "status": "passed"},
    {"from": "screen", "to": "ocr", "relation": "produces", "status": "passed"},
    {"from": "screen", "to": "vision", "relation": "produces", "status": "passed"},
    {"from": "ocr", "to": "candidate", "relation": "supports", "status": "passed"},
    {"from": "vision", "to": "candidate", "relation": "supports", "status": "passed"},
    {"from": "candidate", "to": "gate", "relation": "checks", "status": "blocked"},
    {"from": "gate", "to": "trace", "relation": "writes", "status": "passed"}
  ]
}
```

## 生成规则

推荐生成器按以下顺序构图：

1. 从请求或 trace 读取 `goal_original` 和 normalized model-facing goal。
2. 从 capture/live capture 记录生成 `screen_capture` 节点。
3. 如果有 OCR，生成 `ocr_evidence` 节点，并写入文本数量、anchor 数量、prompt 矩阵数量。
4. 如果有 UIA，生成 `uia_evidence` 节点，并写入 control 数量和 scan 状态。
5. 如果调用过视觉模型，生成 `vision_evidence` 节点，并写入 provider/model/attempt/timing。
6. 如果有 `candidate_rank_v1`，生成 `candidate_rank` 节点。
7. 如果有 `narrow_search_v1`，生成 `narrow_search` 节点。
8. 如果有 `pre_click_decision_v1`，生成 `gate` 节点，`allowed=false` 时状态为 `blocked`。
9. 如果复用了 `approved_plan_id`，生成 `approved_plan` 节点，状态为 `reused`。
10. 如果产生了可点击点，生成 `target` 节点并写入 `{x,y}`。
11. 如果执行真实点击，生成 `action` 节点。
12. 如果做了点击后验证，生成 `verification` 节点。
13. 如果有 `timings`，生成 `timing` 节点或多个 timing 子节点。
14. 每个写出的 trace、overlay、截图 artifact 都可以生成 `trace_artifact` 节点。

## 与学习模式的关系

学习模式第一阶段可以直接保存 `runtime_path_graph_v1`，用于稳定性测试：

```text
same goal
same app/window
same before screenshot hash
same selected target point
same gate result
same verification result
```

第二阶段可以比较两张路径图：

```text
candidate drift
bbox drift
OCR anchor drift
pre-click gate drift
timing regression
fallback path difference
```

第三阶段再把多张路径图归纳为结构泛化规则，但结构规则必须保留来源图列表，不能脱离成功/失败证据。

