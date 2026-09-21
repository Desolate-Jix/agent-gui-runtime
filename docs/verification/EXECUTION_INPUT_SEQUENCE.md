# 组合输入与合并回执 / Input sequences and bundled receipts

状态 / Status: **2026-09-21：785 项测试通过，真实 Google 同会话连续搜索 3/3、只填不提交 1/1；未打包、未发布。**
**785 tests passed, with final same-session Google searches 3/3 and fill-only 1/1. Not packaged or released.**
首次失败、修复、对照耗时和限制见 [验收记录 / Verification record](EXECUTION_INPUT_SEQUENCE_TESTS.md)。 / The linked record retains initial failures, fixes, comparison timings and limits.

## 范围 / Scope

- `input_sequence` 在同一串行宿主命令内执行：识别并聚焦字段 → 填写 → 读取当前焦点字段核对内容 → 可选 Enter 搜索 → 返回后图。所有输入复用 `execute_local_step`，没有第二套鼠标键盘后端、站点坐标或学习内容。 / One serial host command focuses a recognized field, types, reads the focused field to check its value, optionally presses Enter for search, and observes. All input reuses `execute_local_step`; no new input backend, site coordinates or learning assets.
- `instant_run` 合并提交、有限等待、精简回执与原图传输；模型和宿主沿用当前会话，不每步重新启动。 / `instant_run` combines submission, bounded waiting, a compact receipt and original image transport using the existing session.
- 不新增安全策略、不更改现有放行设置。字段读取是组合步骤的功能前置条件，不是重新启用风险分类器。 / No new safety policy or changes to existing authorization settings. Field reading is a functional sequence precondition, not a new risk classifier.

## 新入口 / New entrypoint

连接、选择窗口和模型准备仍按原流程完成。之后优先调用 `instant_run`： / Start, select the target and prepare models as before; then prefer `instant_run`:

```json
{
  "request_id": "search-001",
  "command": {
    "kind": "input_sequence",
    "request": {
      "field_goal": "Click the search input field",
      "text": "Google Maps",
      "clear_existing": true,
      "submit_search": true
    },
    "observation_wait_ms": 2000
  },
  "wait_ms": 25000,
  "detail": "compact",
  "images": "after"
}
```

- `field_goal`：当前截图中的输入框定位要求，不是点击结果或提交表单的任务。 / Describe the input field, not a result link or final form submission.
- `submit_search` 必填。`false` 只填写核对，`true` 才按 Enter；不自动点击结果链接。 / Required boolean; false fills and checks only, true also presses Enter. No automatic result-link click.
- `clear_existing=true` 替换整个字段；`false` 按现场选区替换/插入，读取不到选区则中断。 / Replace the entire field by default; false inserts/replaces the observed selection, interrupting if that selection is unavailable.
- `observation_wait_ms` 沿用 0–2000ms 的渲染宽限，仅用于最后的 Enter 后观察。可选 observation_condition 现已支持明确标志等待，见文末更新；截图不证明加载完成。 / Existing 0–2000ms grace applies to the final Enter observation. Optional explicit-marker waiting is now supported as described below; neither it nor a screenshot proves full-page completion.
- `wait_ms` 为 MCP 本次等待回执的上限（0–30000ms），**不是动作超时或取消**。超时返回 `pending`、`wait_expired=true`、`command_cancelled=false` 和确切的 `next` 参数。保持连接，按原 ID 查结果，不新建 ID 重放。 / The MCP wait limit is not an action deadline or cancellation. On timeout, keep the connection and follow `next` with the same ID; never replay under a new ID.

## 回执与图片 / Receipt and images

- 新 `instant_run` 默认 `detail=compact, images=after`；原六个工具仍保留。 / The new seventh tool defaults to compact JSON plus the after image; the six original tools remain.
- `instant_result` 默认仍是完整 JSON、无图片，保持原调用习惯；可指定 `detail=compact`、`images=after|both`，一次取齐。 / Existing result calls default to full JSON without images; compact and inline image delivery are optional.
- 原图按原回执路径读取并校验 SHA-256，不缩放、不重新截图。`image_delivery` 标明 before/after、摘要和对应 content 索引；图片缺失独立报告，不能把输入成功篡改成输入未发生。 / Images are read from the immutable receipt evidence and hash-checked without recapture/resizing. Delivery metadata identifies each frame and content index. Missing image delivery does not negate earlier input.
- 精简回执保留请求 ID、状态、错误、完成步骤、中断位置、输入核对、耗时、图片引用；冗长模型诊断留在完整回执中。`full_receipt` 给出读取工具参数与本地路径。发现窗口清单和 `read_text` 正文不会被精简丢掉。 / Compact receipts retain operational facts, errors, progress, input checks, timings and image references. Full diagnostics remain retrievable. Discovery lists and read-text content remain available.
- `operation_succeeded` 对组合只表示声明步骤完成；`task_effect_verified=null`，搜索是否成功仍由 Agent 看图判断。 / Sequence completion is not task success; the agent judges the search outcome from the image.

## 中断和限制 / Interruptions and limits

- UIA 可读且当前拥有焦点的字段才支持自动核对。没有 UIA、只绘制在画布上的输入框、密码字段或值读取失败会返回具体读取原因和已完成步骤；不以“粘贴 API 返回成功”冒充内容正确。 / Automatic checking requires a readable, focused UIA field. Unsupported canvas/password/unreadable controls return the read error and partial progress rather than claiming pasted text was verified.
- 点击后 UIA 焦点发布可能略滞后，仅对 `text_field_keyboard_focus_unavailable` 最多只读等待 500ms，不重复点击。字段聚焦保留整图模型定位，避免相同方位提示在局部裁图中改选另一个字段；框内单词、按钮及严格填写路径不受此优化影响。 / Focus publication may lag; only that transient error gets up to 500ms of read-only waiting. Plain field focusing retains full-image grounding instead of reinterpreting spatial prompts on a crop. Word/button and strict fill paths are unchanged.
- 输入变化使用同一字段实例核对，允许该实例的字段尺寸变化；窗口/实例改变或内容不匹配则中断，不自动重输或回车。 / Check the same field instance, allowing its field-size changes; identity/value mismatches interrupt without retyping or Enter.
- 每步先记录派发中状态，完成后保存子步回执；`sequence-progress/<request_id>.json` 保留崩溃/等待期间的部分进度。后图缺失时绝不拿前一步图替代。 / Per-step dispatch checkpoints and receipts preserve partial progress; missing after evidence is never substituted with a prior step's frame.
- Windows 进度文件使用唯一临时文件和原子发布；只对共享冲突类 WinError 5/32/33 最多重试发布 500ms。输入不会因此重放，持续文件错误仍暴露。 / Unique temporary files and atomic JSON publication retry only sharing-related WinError 5/32/33 for up to 500ms; input is never replayed and persistent errors remain visible.
- 本轮减少调用次数和回执体积，也省去普通字段聚焦的第二次裁图推理；未删原单步截图/诊断，未证明整体提速倍率。 / Fewer external calls and compact receipts, plus avoiding a second cropped inference for plain field focus; original step evidence remains. No overall speedup factor is established.

## 验收边界 / Verification scope

单元/契约覆盖参数拒绝、旧默认行为、同 ID、等待超时、组合顺序、插入选区、读取/值/派发/图片失败、原图摘要、精简错误保留及 Windows 发布冲突。真实 MCP smoke 验证七个工具、错误后继续、重连读取与清理；它本身不派发输入。 / Unit/contracts cover validation, compatibility, IDs, waits, sequence order, selection insertion, read/value/dispatch/image failures, original hashes, error fidelity and Windows publication races. Separate stdio smoke checks seven tools, recovery, reconnect and cleanup without input.

真实输入仅覆盖 Google 的普通字段聚焦、替换搜索、只填写和零等待后同 ID 取回；插入选区、跨站点、弹窗干扰、长时间稳定性及 AionUi 独立验收仍待做。新包发布前仍须完成 Codex 单项/连续及同一冻结候选的独立验收。 / Live coverage is limited to Google focus, replacement searches, fill-only and retrieval after zero wait. Live selection insertion, cross-site cases, dialog interference, long sessions and independent AionUi acceptance remain pending before release.

## 后续优化 / Follow-up optimization

上述 785 项为最初组合动作验收记录。当前源码完整回归为826项，并新增可选 `command.observation_condition`；仅在 `submit_search=true` 时用于最后的 Enter 后观察，不重复聚焦或输入，也不改默认固定等待。精简回执保留 `observation.condition`、sample_count 和原图摘要；完整 samples 在详细回执。实际单项、同会话连续、超时恢复及已有标志负控见 [条件等待记录](EXECUTION_CONDITIONAL_WAIT.md)。 / The initial 785-test record is historical. Current source has 826 checks and an optional command-level condition, applied only after the final search Enter. It neither repeats input nor changes default fixed waits. Compact receipts preserve condition diagnostics, sample counts and image hashes; full samples remain in detailed receipts. See the linked real and contract verification.

最新独立实测与回执修复见 [AionUi验收](EXECUTION_AIONUI_ACCEPTANCE_20260921.md)。上文“独立验收待做”是早期状态；当前限定Google连续验收已完成，跨站点/模态/长时覆盖仍待做。当前完整回归836项。 / See the latest independent acceptance; the earlier pending status is historical. Cross-site, modal and longevity coverage remains. Current full regression: 836 checks.
