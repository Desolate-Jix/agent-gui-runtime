# 学习模式计划

更新日期：2026-06-02

本文记录当前对 `agent-gui-runtime` 学习模式的计划。学习模式是可选能力，不应该削弱现有点击前闸门，也不应该让历史记忆直接绕过真实窗口校验。

## 1. 总目标

学习模式分三步推进：

1. 重复界面稳定测试。
2. 匹配策略优化。
3. 泛化结构探索。

先做前两项。只有当稳定测试和匹配策略都有可量化证据后，再考虑更强的跨界面泛化。

## 2. 两个学习模式

### 2.1 指令学习模式

指令学习模式只学习用户明确下达的一条指令。

适用场景：

- 用户说“点击鼠标测试页面里的鼠标图标”。
- 用户说“点击第一个搜索结果”。
- 用户说“打开 Serato 的职业页面”。

学习目标：

- 记录这条指令在当前界面中最终点击了什么。
- 记录为什么这个点是可信的。
- 记录点击前后的截图和验证证据。
- 下次相同窗口、相同内容、相同指令时，优先尝试复用，不必重新调用大模型。

硬性规则：

- 只记录执行成功并通过后验验证的动作。
- 失败、被闸门拒绝、人工取消、验证不通过的动作不能写成可复用学习记录。
- 复用时仍要校验当前窗口、窗口大小、app、目标指令、截图相似度和点击点边界。
- 复用仍要执行真实点击和后验验证。
- 复用失败时回退到普通识别流程，不允许静默点历史坐标。

### 2.2 探索学习模式

探索学习模式不是学习某一条用户指令，而是探索当前界面有哪些可操作路径。

适用场景：

- 测试一个新页面有哪些按钮、导航、卡片、输入框。
- 构建一个界面状态图。
- 找出哪些操作会跳转、展开、弹窗或改变内容。

学习目标：

- 自动尝试当前界面的可点击候选。
- 生成状态节点和操作边。
- 把界面从 A 状态点击到 B 状态的过程保存成路径图。

硬性规则：

- 初期只允许 dry-run。
- 真实点击探索必须有深度限制、黑名单、回退策略和状态去重。
- 不探索危险操作，例如删除、支付、提交隐私信息、关闭重要窗口。
- 探索结果是界面 action map，不是某个用户指令的直接复用记录。

## 3. 第一阶段：重复界面稳定测试

目的：证明同一个界面、同一个任务反复运行时，runtime 不是偶然点对。

首选测试对象：

```text
MouseTester.cn
目标：点击鼠标测试区域或鼠标图标
```

每次运行记录：

- 当前窗口信息：进程、标题、handle、窗口大小、DPI/缩放信息。
- 指令原文和模型用英文归一化目标。
- 截图：source、pre-action、post-action、diff、target crop。
- OCR evidence：目标附近文字、坐标、置信度。
- vision evidence：模型 bbox、anchor relations、grounding constraints。
- candidate rank：top-k、分数、拒绝原因。
- pre-click decision：是否放行，原因。
- clicked point：窗口相对坐标。
- verification：截图变化、OCR 变化、焦点/状态变化。
- timings：每个阶段耗时。
- path graph：本次运行的节点和边。

稳定性指标：

- top-1 候选是否稳定。
- OCR 命中是否稳定。
- bbox 漂移量。
- click point 漂移量。
- pre-click gate 是否稳定放行或稳定拒绝。
- 后验验证是否稳定通过。
- 失败属于哪一层：OCR、视觉模型、融合、排序、闸门、点击、验证。

第一阶段验收：

- 同一任务连续多次运行，有稳定 trace。
- 可以解释每次成功或失败发生在哪一层。
- 成功运行能写入永久学习记录。
- 学习复用能跳过大模型，但仍完成真实点击和验证。

## 4. 第二阶段：匹配策略优化

目的：不是只记死坐标，而是提高“当前界面是否就是上次学过的界面”的判断能力。

### 4.1 图像匹配

建议分层：

1. 全局粗筛：
   - pHash / dHash / aHash
   - 判断当前窗口整体是否和学习记录相似。
2. 局部确认：
   - target crop template matching
   - ORB / AKAZE 特征匹配
   - 判断目标区域是否仍在相似位置。
3. 坐标安全校验：
   - 历史点击点必须仍在窗口内。
   - 历史点击点附近应存在相似图像或相似 OCR。

### 4.2 OCR 文本签名

对搜索结果页、列表页、动态内容页，纯图像相似度不够。需要 OCR 辅助：

- 保存目标附近 OCR 文本。
- 保存同排/同列邻居文字。
- 保存页面区域标题或导航文字。
- 保存候选目标的相对关系，而不是只保存绝对坐标。

示例：

```text
目标：第一个 Google 自然搜索结果
稳定结构：
- 位于 Google 搜索标签栏下方
- 位于搜索结果列表第一项
- 目标附近有标题、摘要、来源 URL
不稳定内容：
- 搜索结果标题每天可能变化
- AI Overview 可能出现或消失
```

这种场景不能只靠截图完全一致。复用前应检查“结构一致”，必要时回退普通视觉识别。

### 4.3 结构匹配

学习记录应该逐步从“图像相似”升级到“结构相似”：

- app/process 一致。
- window size bucket 一致。
- 页面状态 hint 一致。
- OCR 布局签名一致。
- UIA/浏览器 accessibility 节点相似。
- 目标相对区域一致。

## 5. 第三阶段：泛化结构探索

暂缓，不作为当前优先实现。

未来方向：

- 把“点击第一个搜索结果”泛化到不同搜索词。
- 把“打开职业页面”泛化到不同招聘站点的公司卡片。
- 把“关闭窗口”泛化到不同桌面应用的 title bar close button。

前提：

- 已经有稳定的重复界面测试。
- 已经能量化匹配策略的准确率和误点率。
- 已经有负样本，避免过度泛化。

## 6. 学习记录格式建议

每条指令学习记录保存为永久目录：

```text
artifacts/local-learning/instructions/{learned_instruction_id}/
  learned_instruction.json
  path_graph.json
  source_window.png
  pre_action.png
  post_action.png
  diff.png
  target_crop.png
  context_crop.png
```

`learned_instruction.json` 建议字段：

```json
{
  "contract_version": "learned_instruction_v1",
  "learned_instruction_id": "uuid",
  "created_at": "2026-06-02T00:00:00",
  "goal": {
    "original": "点击鼠标图标",
    "normalized": "Click the mouse icon"
  },
  "app": {
    "app_name": "browser",
    "process_name": "msedge.exe"
  },
  "window_signature": {
    "title": "MouseTester.cn - Microsoft Edge",
    "size": {"width": 1280, "height": 720},
    "size_bucket": "1280x720"
  },
  "target": {
    "bbox": {"x": 100, "y": 200, "w": 80, "h": 60},
    "click_point": {"x": 140, "y": 230},
    "click_strategy": "learned_confirmed_point"
  },
  "matching": {
    "source_image_hash": "...",
    "target_crop_hash": "...",
    "ocr_signature": [],
    "structure_signature": {}
  },
  "evidence": {
    "recognition_trace_path": "logs/traces/vision/...",
    "action_trace_path": "logs/traces/actions/...",
    "path_graph_path": "artifacts/local-learning/instructions/{id}/path_graph.json"
  },
  "verification": {
    "passed": true,
    "method": ["screenshot_diff", "ocr_change"]
  }
}
```

## 7. 复用流程

复用不是直接点击。推荐流程：

```text
收到指令
-> 查 learned_instruction index
-> 筛选 goal/app/window 候选
-> 当前截图
-> 图像粗筛
-> OCR/结构匹配
-> 点击点边界检查
-> 生成 reuse path graph
-> 调用真实点击
-> 后验验证
-> 成功：记录 reuse trace
-> 失败：回退普通识别流程
```

复用结果状态：

- `reused_verified`：复用点击并验证成功。
- `reuse_rejected`：匹配不足，未点击，回退普通流程。
- `reuse_clicked_but_unverified`：点击后验证失败，必须标记为失败并禁止提升置信度。
- `fallback_to_recognition`：复用失败后进入正常视觉识别。

## 8. 路径图关系

学习模式必须和路径图结合。

指令学习写入路径图节点：

```text
goal
screen capture
ocr / vision / uia evidence
candidate rank
pre-click gate
target point
real click
verification
learning record
learning assets
```

复用时路径图节点：

```text
goal
learned instruction lookup
current screen capture
image match
ocr / structure match
reuse gate
target point
real click
verification
reuse trace
```

路径图必须由结构化数据确定性生成。AI 可以翻译 label 或写复盘摘要，但不能发明节点、边、点击点或验证结果。

## 9. 当前实现状态

已经有的基础：

- `learning_mode="instruction"` 的最小切片。
- 成功真实点击后可保存 `learned_instruction_v1`。
- 永久学习目录位于 `artifacts/local-learning/instructions/{id}/`。
- 测试面板 path graph 能从 API response 渲染学习资产节点。
- `execute_recognition_plan` 支持 learned instruction 复用的保守校验。

仍需补：

- 学习记录索引 API。
- 学习记录列表/详情面板。
- `path_graph.json` 持久化。
- 图像 hash 和 target crop 匹配。
- OCR 签名匹配。
- 复用失败自动回退普通识别。
- 探索模式 dry-run 原型。

## 10. 下一步建议

第一批任务：

1. 为 `artifacts/local-learning/instructions/` 建索引读取器。
2. 增加 `GET /learning/instructions` 和 `GET /learning/instructions/{id}`。
3. 在测试面板显示学习记录列表和截图证据。
4. 为每次成功学习写 `path_graph.json`。
5. 对 MouseTester 做两次运行：
   - 第一次普通识别并学习。
   - 第二次 learned instruction 复用。
6. 输出稳定性报告：是否跳过视觉模型、是否点击同一点、验证是否通过、耗时下降多少。

