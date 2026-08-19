# OmniParser 学习识别 Shadow 接入设计

## 目标

把 OmniParser 作为可选的学习识别 provider 接入现有 `learn_observe_bundle_v1`，在不改变执行授权边界的前提下，提高视觉控件发现、图标语义和无 UIA 界面的候选覆盖率；同时用本机 RTX 4070 SUPER 对一张已脱敏静态图完成真实推理和资源测量。

## 范围

本轮交付一个最小可验证纵向切片：

1. 定义并校验 `screen_parser_result_v1` provider 输出。
2. 将 panel/worker 的 `observation_evidence.omniparser` 转发到 `observe_bundle.sources.omniparser`。
3. 让 Two-stage Stage1 能读取同一 OmniParser 输出，但强制投影为 review-only。
4. 候选必须携带当前截图 SHA、capture/run identity、图像尺寸、坐标空间、provider 与模型 revision；缺少或过期 lineage 时不得进入 ROI grounding。
5. 提供只读本地 smoke runner，把官方 OmniParser 输出规范化为 `screen_parser_result_v1` 并写入 JSON artifact。
6. 在一张已脱敏静态图上运行一次冷启动与至少三次热推理，记录延迟、候选数、无效 bbox、GPU 显存和停止后的资源回收。

本轮不让 OmniParser 直接生成可执行点击，不替换 UIA/OCR，不在长截图 composite 上生成点击坐标，也不执行任何真实 GUI 动作。

## 架构

数据流：

```text
current immutable screenshot
  -> OmniParser learn-only provider
  -> screen_parser_result_v1
  -> observation_evidence.omniparser
  -> learn_observe_bundle_v1.sources.omniparser
  -> parser_candidate_v1
  -> freshness + eligibility gate
  -> learning draft / human review
```

Two-stage 的 Stage1 复用同一 provider 输出，但其投影始终为：

```text
review_only=true
grounding_eligible=false
artifact_is_authorization=false
execute_binding_enabled=false
```

执行侧仍要求 fresh capture、UIA/OCR/视觉交叉证据、`pre_click_decision_v1`、`POST /action/execute_recognition_plan` 与 post-action verification。

## `screen_parser_result_v1`

顶层必填字段：

- `contract_version = "screen_parser_result_v1"`
- `provider = "omniparser"`
- `status = "success" | "failed"`
- `profile_id`
- `model_revision`
- `capture_id`
- `source_run_id`
- `screenshot_sha256`
- `image_size = {width, height}`
- `coordinate_space = "image_normalized_xyxy" | "image_pixel_xyxy"`
- `elements`（成功时）
- `timing`、`resource_usage`、`provenance`
- `error`（失败时，包含稳定的 `code` 与可操作的 `details`）

每个 element 保留官方 `type`、`content`、`bbox`、`interactivity`、`source`，并生成稳定 `element_id`。原始 provider 输出不可被面板直接改写；人工修改保存为后续 review patch。

## Freshness 与授权边界

- `interactivity=true` 只表示 OmniParser 的交互性证据，不是点击权限。
- `parser_candidate_v1.freshness.same_screenshot` 必须为 true 且 `stale=false`，候选才可进入 ROI grounding。
- 缺 screenshot SHA、capture identity、有效 image size、合法 bbox 或 provider revision 时，候选保留为 review-only，并返回结构化阻断原因。
- Stage1 永远不提升 OmniParser 候选的 grounding/execute 权限。
- 长截图只按 tile/viewport 分段解析；composite 仅用于阅读与人工审查，不能派生实时点击点。

## 本地运行与资源

- 官方代码固定到 `microsoft/OmniParser` 的 `v.2.0.1` tag/commit；代码、权重和临时环境放在已忽略的 `tools/`、`models/` 目录。
- 使用独立的可选 runtime，不修改 Qwen/VISTA 的既有锁定依赖。
- OmniParser 与 Qwen 8B 使用同一 `gpu_vision` 排他资源组；可用显存低于 8 GiB 时 fail closed，不启动完整推理。
- 不启动 OmniTool VM 或 Gradio；只运行 parser。
- smoke 输入使用 `artifacts/demos/seek_three_interface_contact_sheet.png`，不捕获新屏幕、不点击 SEEK。

## 错误处理

- provider 不存在、依赖缺失、权重缺失、协议不合法、bbox 非法、截图 SHA 不一致、CUDA OOM 都必须产生明确失败结果，不能伪装成空成功。
- provider 失败不能自动回退为可点击候选；现有 OCR/UIA/Qwen 路径可继续独立工作，但结果必须显示 OmniParser provider 的失败状态。
- 不允许 broad `except` 吞掉原始错误；artifact 保留错误类型、阶段与建议下一步，但不记录密钥或隐私数据。

## 验证标准

1. 既有 parser、Stage1、workflow task 测试保持通过。
2. 新测试先失败再通过，覆盖主链路转发、Stage1 review-only、freshness 拒绝和非授权字段。
3. 真实 smoke 输出非空 `screen_parser_result_v1`，所有 bbox 合法且绑定输入截图 SHA。
4. 规范化结果能被现有 `parse_existing_evidence_to_inventory()` 消费。
5. 三次热推理记录 P50/P95、候选数和 GPU 峰值；停止后无残留模型进程，显存回到可解释的桌面基线附近。
6. 文档明确区分“provider 可用”“候选生成”“grounding eligible”“执行授权”。

## 非目标

- 本轮不完全替换 Qwen、UIA、OCR、VISTA 或现有 Gate。
- 不从 stitched composite 直接点击。
- 不自动迁移历史学习 artifact。
- 不执行 fill、upload、Continue、final submit/send/confirm/payment。
- 不把 metadata-only profile 无条件标成 launchable；实际 runtime 可用性必须单独探测。

