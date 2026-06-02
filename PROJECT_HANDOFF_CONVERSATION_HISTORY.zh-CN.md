# 项目对话交接记录

更新日期：2026-06-02

这份文档给下一位接手 `agent-gui-runtime` 的 agent 使用。它记录本轮长对话中已经形成的项目判断、实现方向、关键修复、已知问题和下一步建议。接手时请先读本文，再读 `PROJECT_SUMMARY.md`、`CURRENT_STATE.md`、`AGENT_API_WORKFLOW.md`、`API_FIELD_REFERENCE.zh-CN.md`。

## 1. 项目定位

`agent-gui-runtime` 不是完整 agent，而是给上层 agent 使用的 Windows 本地 GUI 自动化运行时。它负责：

- 发现/打开应用。
- 绑定窗口。
- 截图。
- OCR 和视觉模型识别。
- 生成候选目标和点击计划。
- 通过点击前闸门控制真实点击。
- 记录 trace、overlay、timings 和学习证据。

当前核心链路：

```text
Agent 指令
-> runtime API
-> 截图 / OCR / 视觉模型
-> page_structure / screen_reading
-> candidate_rank / narrow_search / pre_click_decision
-> dry-run 或人工确认
-> 真实 SendInput 点击
-> 后验验证
```

## 2. 用户关心的核心方向

本轮对话里，用户持续强调这些原则：

- 这是给 agent 设计的 runtime，任务拆解也应该是 agent 能力的一部分。
- 视觉精准定位不能只靠模型随便框，要结合 OCR 坐标、包含/排除关系、候选排序和点击前闸门。
- 对 UI 图标，不能因为“不发文字”就丢失周边文字上下文；文字应该作为定位边界和排除证据。
- 点击阀门里的真实点击必须是坐标驱动的真实点击。
- 自动化执行要保守：没有通过 pre-click gate 时不自动点，但测试面板可以把 review 候选坐标自动填入人工复核框。
- 学习模式是可选功能，先做“重复界面稳定测试”和“匹配策略优化”，再考虑泛化结构。
- 本地学习记录要永久保存截图和路径图证据，不能混在普通临时截图目录里。

## 3. 已完成的重要功能和修复

### 3.1 OCR 坐标和视觉定位

早期问题：模型会输出超出图片大小的坐标，例如 QQ 关闭按钮返回了大于截图宽度的 `x` 坐标。

修复方向：

- 运行时会恢复/处理 Qwen 风格 `0..1000` 归一化坐标，再映射回实际截图坐标。
- OCR anchors 不再只是完整大列表，而是用 `relation_matrix_compact` 形式发送给模型。
- 默认 prompt anchor 数量从 `32` 提到 `48`。
- 当 OCR 中存在强目标文字匹配时，会优先携带该文字附近更多同排/同列文字排布证据。
- 对无文字图标，周边 OCR 文字用于边界和排除规则，但最终 bbox 必须排除文字区域。
- 对含文字控件，最终 bbox 应包含被引用 OCR 文本和可点击控件表面。

### 3.2 Serato / Seek 卡片定位

问题：用户要求打开 Serato 职业界面时，模型一开始选到了左上角/上一张卡片附近。

演进过程：

- 曾尝试增加 `above_exclusion_boundary`，用目标文字上方的 OCR 文字作为负向边界，防止候选框跨入上一张卡片。
- 用户后来要求删除负面边界。
- 当前策略改成更通用的 `unreferenced_text_contamination`：
  - 如果模型给出的较大 semantic bbox 包含目标文本之外的无关 OCR 文本，则记录污染证据。
  - 候选保留为 review-only，不自动点击。
  - 面板仍可显示 OCR-tight 的 review bbox 和 click point 供人工确认。

相关代码：

- `app/page_structure/fusion.py`
- `tests/test_page_structure_fusion.py`

### 3.3 精准定位返回 review 候选并自动填入面板

问题：当 pre-click gate 不放行时，`/vision/locate_target` 以前可能没有 `located_bbox` / `located_point`，导致测试面板候选框不自动填。

修复方向：

- `/vision/locate_target` 如果没有正式推荐候选，会从 `candidate_result.rejected[0]` 中取最佳 review 候选。
- 返回 `located_bbox` / `located_point`。
- `location_status` 可为 `requires_pre_click_confirmation`。
- `selected_click_point` 仍为空，表示 agent 不能自动点击。
- 测试面板收到成功定位结果后，会自动填入：
  - 候选框校验 bbox。
  - 点击闸门坐标。
  - label。

相关代码：

- `app/api/vision.py`
- `app/settings_panel/desktop.py`
- `tests/test_vision_observe_locate.py`
- `tests/test_settings_panel_modules.py`

### 3.4 整屏理解和 State hint

问题：精准定位页面的 `State hint` 不应该总是人工填写，也不应该默认永远是旧值。

修复方向：

- `POST /vision/observe_screen` 作为整屏理解阶段，要求模型输出短的 `state_guess`。
- 运行时将其暴露为 `suggested_state_hint`。
- 测试面板在整屏理解成功后自动填入精准定位的 `State hint`。
- 对模型提示词建议：面向视觉模型的 `goal` / `state_hint` 尽量转成英文，原始用户中文保存在 metadata/trace 中。

相关文档：

- `AGENT_API_WORKFLOW.md`
- `README.en.md`
- `README.md`

### 3.5 执行 API 和 agent 流程补齐

用户曾要求模拟 agent 执行：

```text
打开桌面的 Edge 浏览器，打开谷歌浏览器，搜索 ai 的最新进展，点击第一个链接
```

尝试后暴露的问题：

- 之前缺少打开应用 API。
- 之前缺少输入文字 API。
- agent 流程应该先启动 runtime 和视觉模型。

后续补齐：

- `GET /apps`
- `POST /apps/open`
- `POST /runtime/prepare`
- `GET /runtime/models`
- `POST /runtime/models/start`
- `POST /action/type_text`
- `POST /action/execute_recognition_plan`
- approved-plan reuse，避免 dry-run 和 real click 都跑一遍大模型。

关键规则：

- agent 不应该直接使用 raw `vision_regions` bbox 点击。
- agent 应优先 dry-run，成功后用 `approved_plan_id` 执行真实点击。
- 测试面板的 `execute_confirmed_point` 是人工复核路径，不是 agent 自主路径。

### 3.6 时间统计

用户要求加入各部分时间统计。

当前 API 路径返回 `runtime_timing_v1`：

- `total_ms`
- `steps[*].name`
- `steps[*].elapsed_ms`

用于判断耗时集中在：

- 截图。
- OCR anchor 准备。
- 视觉模型推理。
- 候选排序。
- pre-click gate。
- overlay 渲染。
- 真实点击。
- 后验验证。

最近定位失败排查中发现：

- 最新 `/vision/locate_target` trace 服务端实际 `success=true`。
- 耗时约 `459192ms`，约 7 分 39 秒。
- 测试面板过去写死 `300s` 超时，所以 UI 显示“请求失败”。
- 已修复为使用面板 `Timeout seconds` / `configs/vision.json` 的 `timeout_seconds`，默认 `600s`。

相关代码：

- `app/settings_panel/desktop.py`
- `app/vision/factory.py`
- `configs/vision.json`

### 3.7 测试面板和启动脚本

用户反馈火绒删除了 PowerShell 脚本，导致面板打不开。

处理方向：

- `start_test_panel.bat` 改成不依赖 `.ps1`。
- 可检查 `/health`。
- 必要时启动 FastAPI runtime。
- 打开 `scripts/settings_panel.py`。

注意：当前 `scripts/start_test_panel.ps1` 在 git 状态中是删除状态。

### 3.8 动态路径图和学习模式

用户提到想要“像八爪鱼一样的动态节点图”来展示路径图。

当前方向：

- 路径图不是 AI 随机生成，而是从 API response / trace 合同确定性生成。
- AI 只能做可选总结或 label 翻译，不能发明节点、边、坐标、验证结果。
- 已新增/规划 `ACTION_PATH_GRAPH_SPEC.zh-CN.md` 描述路径图格式。
- 测试面板 response 区已经能渲染动态 action path graph。

学习模式拆分：

- 探索模式：尝试当前界面所有可行操作，生成路径图。
- 指令学习模式：只学习用户下达的具体指令路径。

当前已先实现最小指令学习切片：

- `learning_mode="instruction"` 成功真实点击并验证后，写 `learned_instruction_v1`。
- 永久证据目录：

```text
artifacts/local-learning/instructions/{id}/
```

包含：

- `learned_instruction.json`
- source screenshot
- pre-action screenshot
- post-action screenshot
- diff image
- target crop

复用时：

- 跳过视觉模型。
- 校验同 goal、app、window handle、window size、point bounds。
- 仍执行真实点击和后验验证。

## 4. 最近一次“请求失败”的真实原因

用户问“为什么会请求失败”。

排查结论：

- FastAPI `/health` 正常。
- 模型进程存在。
- 后端定位 trace 实际写出，且 `success=true`。
- 失败不是模型没返回，而是测试面板客户端超时。
- 旧面板异步请求写死 `timeout=300`。
- 最新定位请求耗时约 `459.19s`。
- 已改为读取 `Timeout seconds`，默认 `600s`。

验证：

```powershell
uv run pytest tests/test_settings_panel_modules.py tests/test_vision_route.py tests/test_local_vision_provider.py
uv run python -m py_compile app\settings_panel\desktop.py app\vision\factory.py
```

结果：`24 passed`，编译通过。

注意：手动用 PowerShell 读取中文 trace 时要加 `-Encoding UTF8`，否则会把中文读乱码，看起来像 JSON 坏了。

## 5. 当前工作区状态提示

接手 agent 不要贸然回滚以下修改。当前工作区有大量未提交改动，是本轮迭代的一部分。

已知修改/新增大类：

- API 工作流文档和字段参考。
- README 双语版本。
- 当前状态/项目总结。
- action / vision API。
- page structure fusion。
- settings panel。
- vision factory。
- configs。
- tests。
- `ACTION_PATH_GRAPH_SPEC.zh-CN.md` 为新增未跟踪文件。

接手前建议运行：

```powershell
git status --short
```

再按任务读取相关 diff，不要执行 `git reset --hard` 或回滚用户/前序 agent 的改动。

## 6. 推荐下一步

### 6.1 先确保面板重新启动

因为超时修复在 `desktop.py` 中，已经打开的测试面板需要重启才能加载新逻辑。

建议：

```powershell
start_test_panel.bat
```

或：

```powershell
uv run python scripts\settings_panel.py
```

### 6.2 再跑一次长耗时定位

目标：确认面板不再 300 秒提前失败。

观察点：

- response 是否正常回来。
- `location_status` 是否为 `requires_pre_click_confirmation`。
- candidate box 是否自动填入。
- path graph 是否显示 trace / timing / gate 节点。

### 6.3 继续完善学习模式

建议按用户认可的两大目标推进：

1. 重复界面稳定测试。
2. 匹配策略优化。

之后再做泛化结构。

第一批可做：

- 为 learned instruction 建索引页/API。
- 在路径图里展示 learned instruction 的截图节点和目标 crop。
- 增加截图相似度匹配：
  - pHash / dHash 做快速粗筛。
  - ORB/SIFT/AKAZE 或 template matching 做局部确认。
  - OCR 文本签名辅助处理搜索结果页这种内容变化页面。

### 6.4 继续优化中文指令入模

已观察到中文直接输入模型时更容易炸或误选。

当前推荐：

- 原始中文保存在 metadata/trace。
- 发给视觉模型的 `goal`、`state_hint`、negative constraints 尽量转为简洁英文。
- 对需要点击“第一个搜索结果”这类任务，英文目标应明确：

```text
Click the first organic Google search result title.
```

并给 state hint：

```text
main organic search results list below Google navigation tabs
```

## 7. 接手 agent 的工作习惯要求

根据仓库 `AGENTS.md`：

- 修改代码时遵循 `skills/code-implementation-loop/SKILL.md`：
  1. 做最小有意义修改。
  2. 运行最窄相关验证。
  3. 检查结果。
  4. 修失败。
  5. 重跑直到验证通过或遇到真实 blocker。
- 行为/API/架构变化要同步文档。
- 不要停止在草稿代码，能跑 smoke check 就要跑。
- 不要回滚未确认来源的脏改动。

## 8. 快速索引

关键文档：

- `AGENT_API_WORKFLOW.md`：agent 调用 API 的主流程。
- `API_FIELD_REFERENCE.zh-CN.md`：中文 API 字段说明。
- `LEARNING_MODE_PLAN.zh-CN.md`：学习模式计划，包括指令学习、探索学习、稳定测试、匹配策略和泛化边界。
- `PROJECT_SUMMARY.md`：项目总览和里程碑。
- `CURRENT_STATE.md`：当前实现状态和真实证据。
- `ACTION_PATH_GRAPH_SPEC.zh-CN.md`：路径图格式。

关键代码：

- `app/api/vision.py`
- `app/api/action.py`
- `app/page_structure/fusion.py`
- `app/settings_panel/desktop.py`
- `app/vision/prompting.py`
- `app/vision/local_provider.py`
- `app/vision/factory.py`
- `app/core/runtime_artifacts.py`

关键测试：

- `tests/test_settings_panel_modules.py`
- `tests/test_vision_observe_locate.py`
- `tests/test_page_structure_fusion.py`
- `tests/test_vision_route.py`
- `tests/test_local_vision_provider.py`
- `tests/test_execute_recognition_plan_route.py`
