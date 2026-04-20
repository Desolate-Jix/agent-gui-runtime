# RUNTIME_STATE_GRAPH

英文版：`RUNTIME_STATE_GRAPH.md`

这两份文档需要保持同步更新。

---

## 先记住这一张图

如果只记住一句话，那就是：

这个运行时不是在“每次看图都重新猜一次”，而是在“持续建立一张可复用的软件结构图”。

这张图里有 3 个核心对象：

- `state`：当前是什么界面
- `target`：这个界面里有什么可以点
- `transition`：点了之后会跳到哪里

整条主链路是：

`看到当前界面 -> 识别状态 -> 找到目标 -> 点击 -> 验证 -> 写回结果 -> 下次复用`

## 分层理解

把整个系统看成 5 层会更容易理解。

### 第一层：感知层

目标：

- 看见当前界面
- 提取文字、控件、位置

主要步骤：

1. 截取当前绑定窗口
2. 跑 OCR
3. 必要时调用 AI 识图
4. 生成一个统一的观察对象

输入：

- 已绑定窗口
- 当前截图

输出：

- `ObservationFrame`
- 候选状态信息
- OCR / vision 返回的原始目标

### 第二层：状态层

目标：

- 判断当前界面到底是什么状态
- 如果以前没见过，就注册成一个新状态

主要步骤：

1. 拿当前观察结果去匹配已有状态
2. 如果匹配成功，返回已知 `AppState`
3. 如果匹配失败，创建新的 `AppState`

输入：

- `ObservationFrame`
- 已有的 `AppState`

输出：

- 一个确定的 `AppState`
- 这个状态的匹配置信度

### 第三层：目标层

目标：

- 确定当前状态里有哪些目标能点
- 为每个目标保存后续可复用的本地视觉资产

主要步骤：

1. 读取当前状态下已有的目标
2. 如果状态是新的，就注册新的 `ActionTarget`
3. 裁剪并保存：
   - target patch
   - context patch
4. 创建或更新 `TargetAsset`

输入：

- `AppState`
- OCR / vision 目标结果
- 当前截图

输出：

- `ActionTarget`
- `TargetAsset`

### 第四层：执行层

目标：

- 稳定地把目标点下去

主要步骤：

1. 读取 target asset
2. 优先做本地匹配：
   - target patch
   - context patch
   - OCR
   - AI fallback
3. 得到最终点击点
4. 执行点击

输入：

- `ActionTarget`
- `TargetAsset`
- 当前截图

输出：

- 点击结果
- 实际点击点

### 第五层：验证与记忆层

目标：

- 判断这次点击是否真的成功
- 把结果写回状态图

主要步骤：

1. 截取 after screenshot
2. 通过下面几类证据验证：
   - 文字锚点
   - 目标锚点
   - ROI diff
   - 数值/计数器变化
3. 判断 next state 是什么
4. 写入：
   - `ReplayCase`
   - `TransitionRecord`
5. 更新目标置信度和优先点击点

输入：

- before screenshot
- after screenshot
- validator 规则

输出：

- 成功 / 失败
- next state
- 更新后的记忆

## 层与层之间怎么调用

调用顺序是：

`第一层 -> 第二层 -> 第三层 -> 第四层 -> 第五层`

更具体一点就是：

1. 感知层先生成 `ObservationFrame`
2. 状态层用它去找或创建 `AppState`
3. 目标层根据当前状态和截图，加载或创建 `ActionTarget` 与 `TargetAsset`
4. 执行层拿这些目标记录去点击
5. 验证层判断动作是否成功，并把结果写回成 `TransitionRecord` 和 `ReplayCase`

所以每一层回答的问题都不同：

- 第一层回答：当前看到了什么
- 第二层回答：这是什么状态
- 第三层回答：这个状态里有哪些目标可用
- 第四层回答：应该点哪里
- 第五层回答：点完后是否成功、状态发生了什么变化

## 一次完整点击的例子

比如当前界面是 `home_page`，目标是打开设置页。

### 第 1 步：感知层

- 截图
- OCR 识别到 `Start`、`Settings`、`Exit`
- AI 或本地 parser 给出一个目标：`settings_button`

### 第 2 步：状态层

- 运行时把当前观察结果和已知状态做对比
- 判断当前状态就是 `home_page`

### 第 3 步：目标层

- 运行时加载 `settings_button`
- 运行时加载 `settings_button_asset`
- 找到：
  - 已保存的 patch
  - 已保存的 context patch
  - 已保存的 hit point

### 第 4 步：执行层

- 运行时先在当前截图里做本地匹配
- 得到最终点击点
- 执行点击

### 第 5 步：验证层

- 运行时截取点击后的截图
- 检查 `General`、`Advanced` 是否出现
- 判断新状态是 `settings_page`

### 第 6 步：写回记忆

- 写入 `ReplayCase`
- 写入 `TransitionRecord`
- 提高这个目标和这条跳转的置信度

## 为什么一定要保存按钮 Patch

原因很简单：

第一次运行时，可以让 AI 帮你发现按钮。
第二次运行时，如果这个按钮已经是已知目标，就不应该还依赖 AI。

所以每个已知目标都要保存：

- `target patch`：按钮本体
- `context patch`：按钮周围上下文

这样下次就能变成：

1. 先本地 patch 匹配
2. 本地点击
3. OCR 或 AI 只作为 fallback

## 这份文档应该怎么读

建议按这个顺序读：

1. `先记住这一张图`
2. `分层理解`
3. `层与层之间怎么调用`
4. `一次完整点击的例子`
5. 最后再看后面的实体和字段定义

前面几节是在讲“运行逻辑”。
后面几节是在讲“字段字典”。

## 目标

这份文档定义了运行时如何把一个 GUI 软件逐步积累成一张可复用的状态图。

系统不应该把每一张截图都当成一次全新的、一次性的识别任务。
相反，系统应该持续积累可复用的软件结构：

- 当前界面状态是什么
- 这个状态里有哪些目标
- 每个目标的位置在哪里
- 点击这个目标后预期会发生什么
- 如何验证这次跳转是否真的发生
- 哪个目标 patch 可以在下次直接复用，而不必再次调用 AI

长期执行循环是：

`Observe -> Recognize State -> Select Target -> Execute -> Verify -> Register -> Reuse`

## 核心原则

系统保存的知识模型应该是一张状态图，而不是一份扁平的页面列表。

- 节点 = `AppState`
- 边 = `TransitionRecord`
- 节点上的可操作对象 = `ActionTarget`
- 用于本地稳定复用的视觉资产 = `TargetAsset`
- 一次真实运行留下的证据 = `ReplayCase`

这会让系统从：

- `AI 看图 -> AI 猜下一步点击`

变成：

- `运行时识别已知状态 -> 加载已知目标 -> 点击 -> 验证 -> 更新状态图`

## 运行阶段

### 阶段 1：Observe

输入：

- 已绑定窗口句柄
- 当前整窗截图或 ROI 截图

输出：

- `ObservationFrame`
- 一个 `AppState` 候选匹配结果，或者 `unknown`

职责：

- 截图
- 收集 OCR 和 vision 输出
- 生成一个标准化观察对象，供后续状态匹配使用

### 阶段 2：Register State

如果当前界面无法高置信度匹配已有状态，则创建新的 `AppState`。

职责：

- 分配稳定的 `state_id`
- 保存状态签名字段
- 保存定义这个状态时使用的截图
- 注册 vision 解析返回的可见目标

### 阶段 3：Register Targets

对当前界面中的每一个可操作目标，创建或更新 `ActionTarget` 及其对应的 `TargetAsset`。

职责：

- 保存目标 bbox 和 hit point
- 保存可见文字和控件类型
- 保存 target patch 和 context patch
- 定义下次如何匹配这个目标

### 阶段 4：Execute

当一个目标被选中时：

- 优先使用已有的本地 target asset
- 如果本地匹配较弱，则回退到 OCR 或 AI 解析
- 使用最终确定的 `hit_point` 点击

### 阶段 5：Verify

点击后：

- 截取 after screenshot
- 检查验证锚点
- 判断这次动作是否导致：
  - 页面跳转
  - 弹窗打开
  - tab 切换
  - 开关切换
  - 未知结果

### 阶段 6：Register Transition

如果这次动作是有意义的，则持久化这条跳转：

`from_state + action_target -> to_state`

这就是让系统后续可以复用的图边。

### 阶段 7：Reuse

下次再遇到同一个状态时：

- 加载已知目标和保存的 patch
- 优先做本地匹配
- 只有当匹配或验证失败时才再次调用 AI

## 目录策略

建议的运行时持久化目录：

```text
logs/
  app-states/
  app-actions/
    validators/
  app-transitions/
  replay-cases/
  target-patches/
    {app_name}/
      {state_id}/
        {target_id}/
          target-*.png
          context-*.png
          meta-*.json
  captures/
  verify/
```

当前仓库已经把很多运行时数据写在 `logs/` 下。
这份文档把 `target-patches/` 正式定义为一等运行时存储。

## 实体模型

## 1. ObservationFrame

用途：

- 表示某一时刻的一张标准化截图观察结果
- 作为状态识别和目标注册的输入

建议字段：

```json
{
  "frame_id": "string",
  "app_name": "string",
  "window_handle": 0,
  "captured_at": "iso_datetime",
  "image_path": "string",
  "image_width": 0,
  "image_height": 0,
  "window_rect": {
    "left": 0,
    "top": 0,
    "right": 0,
    "bottom": 0
  },
  "ocr_texts": ["string"],
  "vision_state_hint": "string|null",
  "layout_hash": "string|null"
}
```

字段调用方式：

- `frame_id`
  - 生产者：截图流水线
  - 消费者：replay case、调试日志
- `app_name`
  - 生产者：绑定层或请求上下文
  - 消费者：状态存储分区
- `window_handle`
  - 生产者：window manager
  - 消费者：证据记录，不作为长期身份
- `image_path`
  - 生产者：screenshot service
  - 消费者：OCR、验证、replay case
- `ocr_texts`
  - 生产者：OCR 运行时
  - 消费者：状态识别、验证锚点
- `layout_hash`
  - 生产者：后续的缩略图/布局指纹模块
  - 消费者：快速状态候选过滤

## 2. AppState

用途：

- 表示一个可识别的 UI 状态
- 作为状态图中的节点

建议字段：

```json
{
  "state_id": "home_page",
  "app_name": "demo_app",
  "state_name": "Home Page",
  "window_size_bucket": "1366x768",
  "summary": "main landing page with Start and Settings buttons",
  "signature": {
    "primary_texts": ["Start", "Settings", "Exit"],
    "secondary_texts": ["Version", "Status"],
    "layout_hash": "string|null",
    "anchor_patches": [
      {
        "name": "home_title",
        "path": "logs/app-states/.../anchor-001.png"
      }
    ]
  },
  "target_ids": ["start_button", "settings_button"],
  "entry_image_path": "string",
  "tags": ["main", "stable"],
  "version": 1
}
```

字段调用方式：

- `state_id`
  - 生产者：状态注册逻辑
  - 消费者：跳转图、动作查找、patch 路径分区
- `window_size_bucket`
  - 生产者：几何层
  - 消费者：详细匹配前的快速缩小范围
- `signature.primary_texts`
  - 生产者：OCR + AI 解析
  - 消费者：状态识别和验证
- `signature.layout_hash`
  - 生产者：后续指纹步骤
  - 消费者：粗粒度状态匹配
- `target_ids`
  - 生产者：目标注册
  - 消费者：已知动作加载
- `entry_image_path`
  - 生产者：截图服务
  - 消费者：审计和调试

## 3. ActionTarget

用途：

- 表示某个状态中的一个可操作目标
- 保存足够的几何信息和语义信息，以便执行动作

建议字段：

```json
{
  "target_id": "settings_button",
  "state_id": "home_page",
  "action_name": "Open Settings",
  "label": "Settings",
  "control_type": "button",
  "action_type": "click",
  "bbox": {
    "x": 100,
    "y": 200,
    "width": 120,
    "height": 40
  },
  "bbox_norm": {
    "x": 0.10,
    "y": 0.26,
    "width": 0.12,
    "height": 0.05
  },
  "hit_point": {
    "x": 160,
    "y": 220
  },
  "text": "Settings",
  "text_candidates": ["Settings"],
  "match_strategy": "patch_then_ocr_then_ai",
  "target_asset_id": "settings_button_asset",
  "validator_profile_id": "validator_settings_open",
  "expected_transition_ids": ["home_to_settings"],
  "successful_points": [],
  "forbidden_points": [],
  "notes": "top-right main action",
  "version": 1
}
```

字段调用方式：

- `target_id`
  - 生产者：目标注册
  - 消费者：动作执行、跳转关联、patch asset 查找
- `bbox`
  - 生产者：AI parser 或 OCR parser
  - 消费者：patch 裁剪和点击坐标生成
- `bbox_norm`
  - 生产者：注册逻辑
  - 消费者：跨分辨率重定位
- `hit_point`
  - 生产者：parser 或本地点位策略
  - 消费者：直接点击执行
- `text`
  - 生产者：OCR/vision 解析
  - 消费者：OCR fallback 和验证
- `match_strategy`
  - 生产者：目标注册默认策略
  - 消费者：运行时执行器
- `target_asset_id`
  - 生产者：target asset 创建流程
  - 消费者：patch store 查找
- `successful_points`
  - 生产者：执行反馈
  - 消费者：未来优先点位排序
- `forbidden_points`
  - 生产者：执行反馈
  - 消费者：避开已知坏点

## 4. TargetAsset

用途：

- 保存已知目标的本地视觉素材
- 让第二次及以后的执行尽量减少对 AI 的依赖

建议字段：

```json
{
  "target_asset_id": "settings_button_asset",
  "target_id": "settings_button",
  "state_id": "home_page",
  "app_name": "demo_app",
  "patch_path": "logs/target-patches/demo_app/home_page/settings_button/target-001.png",
  "context_patch_path": "logs/target-patches/demo_app/home_page/settings_button/context-001.png",
  "source_image_path": "logs/captures/capture-001.png",
  "bbox": {
    "x": 100,
    "y": 200,
    "width": 120,
    "height": 40
  },
  "hit_point": {
    "x": 160,
    "y": 220
  },
  "match_method": "template",
  "confidence": 0.94,
  "created_at": "iso_datetime",
  "updated_at": "iso_datetime"
}
```

字段调用方式：

- `patch_path`
  - 生产者：注册阶段或成功点击后的 crop-and-save 流程
  - 消费者：模板匹配阶段
- `context_patch_path`
  - 生产者：crop-and-save 流程
  - 消费者：当 target patch 本身歧义较大时的上下文辅助匹配
- `source_image_path`
  - 生产者：截图服务
  - 消费者：审计和调试
- `match_method`
  - 生产者：asset 注册策略
  - 消费者：匹配器选择
- `confidence`
  - 生产者：asset 创建/更新逻辑
  - 消费者：判断本地复用是否足够可信

## 5. ValidatorProfile

用途：

- 定义如何判断一个目标动作是否真的成功

建议字段：

```json
{
  "validator_profile_id": "validator_settings_open",
  "target_name": "Settings Open Validator",
  "target_roi": {
    "x": 0,
    "y": 0,
    "width": 0,
    "height": 0
  },
  "ocr_roi": {
    "x": 0,
    "y": 0,
    "width": 0,
    "height": 0
  },
  "appear_texts": ["General", "Advanced"],
  "disappear_texts": ["Start", "Exit"],
  "appear_target_ids": ["settings_back_button"],
  "strict_rule": {
    "type": "text_and_diff"
  },
  "weak_rule": {
    "type": "diff_only"
  },
  "version": 1
}
```

字段调用方式：

- `target_roi`
  - 生产者：目标注册或后续调优
  - 消费者：局部 diff 验证
- `ocr_roi`
  - 生产者：validator 配置过程
  - 消费者：点击后的 OCR 验证
- `appear_texts`
  - 生产者：AI 预测或人工修正
  - 消费者：after-state 验证
- `disappear_texts`
  - 生产者：AI 预测或人工修正
  - 消费者：跳转确认
- `appear_target_ids`
  - 生产者：已知 next-state target 注册
  - 消费者：作为状态变化的强证据

## 6. TransitionRecord

用途：

- 表示从一个状态，通过一个目标动作，到另一个状态的一条图边

建议字段：

```json
{
  "transition_id": "home_to_settings",
  "from_state_id": "home_page",
  "action_id": "settings_button",
  "to_state_id": "settings_page",
  "success_type": "strict",
  "confidence": 0.95,
  "effect_type": "navigate",
  "verification": {
    "appear_texts": ["General", "Advanced"],
    "disappear_texts": ["Start", "Exit"],
    "matched_targets": ["settings_back_button"]
  },
  "case_path": "logs/replay-cases/replay-001.json",
  "timestamp": "iso_datetime"
}
```

字段调用方式：

- `from_state_id`
  - 生产者：运行时状态识别
  - 消费者：图遍历和回放
- `action_id`
  - 生产者：执行器
  - 消费者：动作查找和策略调优
- `to_state_id`
  - 生产者：after-state 识别
  - 消费者：导航规划和记忆图
- `effect_type`
  - 生产者：AI 预测，再由运行时确认
  - 消费者：规划器和执行器预期
- `verification`
  - 生产者：验证步骤
  - 消费者：未来的可信度校准

## 7. ReplayCase

用途：

- 保存一次执行尝试的真实证据

建议字段：

```json
{
  "case_id": "replay-001",
  "app_name": "demo_app",
  "state_before_id": "home_page",
  "action_id": "settings_button",
  "state_after_id": "settings_page",
  "before_image_path": "logs/captures/before-001.png",
  "after_image_path": "logs/captures/after-001.png",
  "target_patch_path": "logs/target-patches/.../target-001.png",
  "context_patch_path": "logs/target-patches/.../context-001.png",
  "click_point": {
    "x": 160,
    "y": 220
  },
  "verification_result": {
    "strict_success": true,
    "weak_success": true,
    "diff_changed": true,
    "matched_appear_texts": ["General"]
  },
  "success": true,
  "timestamp": "iso_datetime"
}
```

字段调用方式：

- `before_image_path`、`after_image_path`
  - 生产者：截图服务
  - 消费者：回放分析和调试
- `target_patch_path`、`context_patch_path`
  - 生产者：patch store
  - 消费者：失败分析和 asset 刷新
- `verification_result`
  - 生产者：verifier
  - 消费者：更新 target confidence 和 transition confidence

## AI 识图输出契约

AI parser 应该返回一个可以直接用来生成 `AppState`、`ActionTarget` 和跳转预期的数据结构。

建议 vision 返回结构：

```json
{
  "image": {
    "width": 0,
    "height": 0
  },
  "screen_state": {
    "state_id": "home_page",
    "state_name": "Home Page",
    "summary": "main landing page"
  },
  "targets": [
    {
      "target_id": "settings_button",
      "label": "Settings",
      "control_type": "button",
      "action_type": "click",
      "bbox": {
        "x": 100,
        "y": 200,
        "width": 120,
        "height": 40
      },
      "bbox_norm": {
        "x": 0.10,
        "y": 0.26,
        "width": 0.12,
        "height": 0.05
      },
      "hit_point": {
        "x": 160,
        "y": 220
      },
      "text": "Settings",
      "text_candidates": ["Settings"],
      "confidence": 0.94,
      "clickable_confidence": 0.97,
      "expected_after": [
        {
          "effect_type": "navigate",
          "next_state_id": "settings_page",
          "next_state_name": "Settings Page",
          "confidence": 0.83,
          "reason": "settings menu likely opens the settings page",
          "verification_anchors": {
            "appear_texts": ["General", "Advanced"],
            "disappear_texts": ["Start", "Exit"],
            "appear_controls": ["settings_back_button"]
          }
        }
      ]
    }
  ],
  "text_nodes": []
}
```

这些字段后续怎么用：

- `screen_state.*`
  - 用来创建或更新 `AppState`
- `targets[*]`
  - 用来创建或更新 `ActionTarget`
- `targets[*].expected_after[*]`
  - 用来生成 `TransitionRecord` 预期和 `ValidatorProfile`
- `verification_anchors`
  - 直接用于点击后的验证

## 新状态注册流程

当运行时进入一个未知界面时：

1. 截取整窗截图
2. 调用 OCR，必要时调用 AI vision parser
3. 构建 `ObservationFrame`
4. 判断当前没有高置信度匹配的已有状态
5. 创建 `AppState`
6. 为每个返回的目标创建 `ActionTarget`
7. 为每个目标裁剪并保存 `TargetAsset`
8. 持久化所有记录

结果：

- 这个界面下次就变成可复用状态
- 未来如果本地匹配有效，就不需要再次全量调用 AI

## 已知状态执行流程

当运行时识别到一个已知状态时：

1. 加载 `AppState`
2. 加载该状态下的所有 `ActionTarget`
3. 对选中的目标加载 `TargetAsset`
4. 按下面顺序做本地匹配：
   1. target patch
   2. context patch
   3. OCR text match
   4. AI reparse fallback
5. 解析最终 `hit_point`
6. 点击
7. 截取 after screenshot
8. 使用 `ValidatorProfile` 验证
9. 更新 `ReplayCase`
10. 更新 `TransitionRecord`
11. 必要时刷新 patch asset

## Patch 保存逻辑

Patch 保存应该发生在两个时机。

### A. 状态注册时

如果某个目标第一次被发现，则保存：

- `target patch`
- `context patch`
- metadata JSON

### B. 成功点击后

如果一次点击被验证为成功，可以选择刷新：

- 最佳 target patch
- 最佳 context patch
- 成功点击点列表

这意味着系统会持续改进本地 target asset 库。

## Patch 裁剪定义

### target patch

- 按目标 bbox 精确裁剪
- 用于精确模板匹配

### context patch

- 以目标 bbox 为中心向外扩一圈再裁剪
- 建议边距：20 到 60 px，取决于 UI 密度
- 用于解决目标本体过于通用的问题

## 验证逻辑

验证不能只依赖单一信号。

建议顺序：

1. 文字锚点
   - 预期文字是否出现
   - 预期文字是否消失
2. 目标锚点
   - 已知 next-state target 是否出现
3. 局部 diff
   - 目标 ROI 或状态 ROI 是否变化
4. 数值/计数器变化
   - 适用于 MouseTester 这类界面
5. 回退到整图 diff
   - 只作为弱信号

## 置信度更新规则

建议策略：

- 严格验证成功：
  - 提升 `TransitionRecord.confidence`
  - 提升 `TargetAsset.confidence`
- 多次只有弱验证成功：
  - 保持中等置信度
- 本地 patch match 后多次失败：
  - 降低 `TargetAsset.confidence`
  - 下次优先 OCR 或 AI fallback
- 同一点击点多次失败：
  - 追加到 `ActionTarget.forbidden_points`

## ID 约定

建议命名：

- `state_id`
  - `home_page`
  - `settings_page`
  - `settings_dialog_open`
- `target_id`
  - `settings_button`
  - `confirm_button`
  - `back_tab`
- `transition_id`
  - `home_to_settings`
  - `settings_to_home`
- `validator_profile_id`
  - `validator_settings_open`
- `target_asset_id`
  - `settings_button_asset`

ID 应该是机器稳定的短标识，而不是自然语言长句。

## 这个仓库的近期接入计划

### 已经和这套模型对得上的现有部分

- `AppState`
- `ActionTarget`
- `ValidatorProfile`
- `TransitionRecord`
- `ReplayCase`
- `action_registry`
- `transition_memory`
- `replay_case_store`
- screenshot capture
- OCR service
- click execution
- verification

### 下一步要补的部分

1. 一等公民的 `TargetAsset` schema 和 store
2. `logs/target-patches/` 持久化
3. screenshot 或 asset 模块中的 patch crop helper
4. 在 OCR/AI fallback 前增加本地 target match 阶段
5. 一个能直接返回 target geometry 和 expected transitions 的 AI parser contract

## 实际效果

这套模型落地后，系统的行为会变成：

### 第一次进入一个界面

- AI 帮忙解析界面
- 运行时注册状态
- 运行时保存目标和 patch

### 第二次进入同一个界面

- 运行时识别状态
- 运行时加载已知目标和 patch
- 运行时优先本地点击
- AI 只在失败时作为 fallback

这就是从一次性识图，转向可复用软件记忆的关键架构变化。
