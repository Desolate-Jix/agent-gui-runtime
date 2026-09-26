# Agent 视觉组合命令 / Agent-vision batch commands

test.8 · Agent 组合命令协议 / Agent batch command protocol

## 使用 / Usage

在 `agent_current` 或 `agent_delegate` 会话中，`step/execute_recognition_plan`、`desktop_click`、`input_sequence`、`form_fill` 使用原执行器，新增可暂停的视觉交接。命令顶层显式声明 `vision_capabilities`；不支持或未知不会自动转到本地模型。`local` 会话行为不变。

Agent-source sessions reuse the existing executor with suspendable grounding. Declare `vision_capabilities` explicitly on the command; unsupported/unknown capability never silently starts a local model. Local-source behavior is unchanged.

```json
{
  "request_id": "fill-1",
  "command": {
    "kind": "input_sequence",
    "vision_capabilities": {"image_transport": "supported", "current_vision": "supported"},
    "request": {"field_goal": "Search input", "text": "Google Maps", "clear_existing": true, "submit_search": true}
  },
  "images": "after"
}
```

1. 接收 `agent_command.v1`。`running` 不是完成；用新外层 `request_id` 调用 `agent_command_status`，request 为 `{"command_id":"fill-1"}`。原始提交回执保持不可变，不用反复读它期待进度更新。
2. `awaiting_grounding` 时检查同次返回原图和 `pending_grounding`。按其 `output_schema` 返回 `grounding_resolve`，引用 **pending 的 request_id**，不是外层轮询 ID。
3. 找到唯一目标后，以新外层 ID 调用 `agent_command_continue`，request 为 `{"command_id":"fill-1","grounding_request_id":"ag-..."}`。不要调用独立 `grounding_execute`，也不要重新提交整批。
4. 原工作线程继续，保留前面已执行的字段和输入；遇到下一次识别再次交接。文本/UIA 校验、控件约束及失败中断沿用原公共路径。
5. 到 `completed/failed/cancelled` 才是终态；检查完整结果及原图，由 Agent 判断实际效果。`completed` 仅表示声明的组合动作路径完成，不证明整个用户任务成功。

Submit once; query fresh status receipts, ground the pending original image, then explicitly continue the original command. Each outer request ID is unique. The same worker resumes without replaying earlier fields. Only terminal statuses end the command, and task-effect judgment remains with the Agent.

## 中断、取消与图像 / Interruption, cancellation and images

- `agent_command_cancel` 请求合作取消；已开始的输入不能撤回。等待终态或清理报告，不能把取消请求返回当作零副作用证明。 / Cancellation is cooperative, not rollback or proof of zero input.
- 活动命令期间拒绝其他输入、窗口选择和启动；允许状态、定位回传/取消和关闭。关闭宿主先等待工作线程退出，再销毁协调器。 / Competing input and target changes are rejected; shutdown waits for the worker before coordinator teardown.
- 无候选、歧义、不支持、错误、过期会结束本命令并保留失败证据，不静默重试。重启不自动恢复输入。 / Negative grounding and expiry terminate without replay; restart never resumes input automatically.
- 等待识别时返回当前定位图；派发中图像为 unavailable，不把识别前图冒充执行后图。完成结果支持 `instant_image(view=before|after)`，均读取原始记录，不再次截图。 / Pending images are grounding evidence; inflight input has no after image yet. Completed receipts expose recorded originals, not recaptures.
- Agent 来源的 `read_text` 返回 `agent_read_required`、`text=null` 和原图，调用方自行视觉读取；不加载本地 OCR。 / Agent-source read_text returns the original image for client reading, without local OCR.
- `agent_delegate` 的具体模型由客户端按显式 profile 调用，宿主不自动获得客户端密钥或替客户端挑选型号。 / The client invokes the explicitly selected delegate; the host neither inherits credentials nor chooses a model itself.

## 验证状态 / Verification

后台测试覆盖协议、暂停/恢复、取消竞态、过期、无候选、重复请求和异常输入证据。当前最新完整源码回归为 **2010 passed in 39.32s**（较早的 1992 项是历史检查点）。冻结候选 `v0.1.0-test.8-candidate01` 另经隔离 `python -I` 全套测试 **2010 passed in 42.80s**（driver wall 43.172s）；283 个项目模块无原工作树导入，715 项 manifest 全部哈希匹配，入口预检通过。其真实连续 GUI 验收仍在进行，独立验收尚未开始。`20260926-agent-batch-01` 实际 stdio + 新记事本完成定位→组合输入→UIA 值核对→Agent 原图读取→撤销→关闭，宿主清理已核对。该轮发现派发中误返回定位前图，已补回归并修复。

Unit/contract tests cover handoff, cancellation races, expiry, negatives, duplication and uncertain-input evidence; **2010 source checks passed in 39.32s**. Frozen test.8 candidate01 passed **2010 tests in 42.80s** with 283 project modules confined to the candidate, all 715 manifest hashes matching, and entrypoint preflight passing. Frozen continuous GUI acceptance is ongoing; no independent acceptance has been dispatched. A real stdio/Notepad slice completed batch typing, UIA readback, image reading, undo and cleanup. Its inflight-image mislabel was reproduced and repaired. Local evidence stays outside Git.

### 真实网页连续样本 / Continuous real-browser sample

**后续修复已实测 / Follow-up verified:** `20260926-agent-controls-01` 独立只读探针发现原生展开值为 3，但 ARIA 明确为 false；不是完全没有状态。公共读取器现读取原生/ARIA 两种事实并报告 `expansion_source`。`agent-controls-02` 真实框架完成：展开→无此选项中断→选择 PDF→同会话文本两项与下拉恢复三字段批次（完成索引 `[0,1,2]`）。原图与选中值一致，没有提交；本轮核对 15 张图像摘要。源码全套为 **2010 passed in 39.32s**。冻结 test.8 candidate01 的隔离全套、模块来源、manifest 与入口预检已通过；冻结候选的连续 GUI 验收仍进行中，独立验收未开始。下方菜单限制明确是首次失败历史，不代表当前不支持。

The probe established a native LeafNode value alongside explicit ARIA expansion. The shared reader now records its expansion source and rejects conflicting/changing facts. The repaired real run selected PDF, then completed a three-field mixed batch in the same session, with original-image and value evidence; 15 image digests were checked. **2010 source checks passed in 39.32s.** Frozen test.8 candidate01 passed its isolated 2010-test suite, module-origin, manifest-hash and entrypoint checks. Its continuous GUI acceptance is in progress; independent acceptance has not started. The earlier dropdown failure below is historical, not a current unsupported-capability statement.

该实现依据 UIA 提供的实际控件属性，不匹配 Google URL 或特定标签；参考 [Microsoft ARIA→UIA 映射](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-ariaspecification)。新增状态缺失、重复、格式异常、原生矛盾、读取中状态/来源变化回归，未知仍不当作折叠。

This uses observed UIA properties, not site-specific labels. Regression covers missing/malformed/duplicate states, conflicts and source/state changes; unknown still does not mean collapsed.

`20260926-agent-batch-06` 在同一新开 Edge / Google 高级搜索窗口中完成：双字段逐项定位填写 → 凭据过期中断 → 文本分组受限中断 → 只补未完成字段 → 取消新命令 → 关闭本轮窗口与宿主清理。前后原图分别核对 `Auckland museum / Sky Tower` 和 `Wellington / Cable Car`。没有搜索或提交。

One new Edge window and MCP session covered two-field filling, an expired handoff, interrupted grouped navigation, explicit recovery of only unfinished content, cancellation and owned-window/host cleanup. Original images show both requested text pairs. No form was submitted.

- 过期发生于 Agent 续接接近 180 秒截止，执行时凭据已过期，未执行输入；不是模型推理耗时。 / The handoff expired at execution after a late continuation; no input occurred. This is not model inference latency.
- 测试驱动首次把全角 `：` 写成半角 `:`，确切 UIA 标签核对中断；改用实测标签后第一字段完成。 / An incorrect ASCII colon in the driver failed exact accessible-label matching; the observed full-width label corrected it.
- Google 输入框的下一个 Tab 目标是清除按钮，不是下一个文本框；`tab_groups` 如实以 `text_group_focus_not_edit` 中断，未向错误控件输入。该页面应使用 `recognize_each`，不能宣称此页支持连续文本 Tab 分组。 / Tab reaches a clear button, not the next edit; use per-field recognition on this page. Do not count the interrupted group as passing.
- **首次失败历史（已修复） / Historical first failure (fixed):** Google 自定义文件类型菜单最初因原生 ExpandCollapse 为 LeafNode 且读取器未检查 ARIA，返回 `form_control_expansion_unavailable`。后续已在同类真实控件上完成 PDF 选择及同会话混合表单恢复；不要把首次失败改记成首次成功，也不要继续把它描述为当前不支持。 / The first run returned `form_control_expansion_unavailable` because the reader did not yet inspect ARIA for this LeafNode. A later real run selected PDF and recovered a mixed form in-session. Preserve the first failure; do not label the capability currently unsupported.
- 字段耗时包含等待 Agent 返回定位的时间；不能把整段 wall time 当作本地输入延迟。 / Field wall time includes client grounding waits, not only local execution.

### 通用浏览器修复 / Shared browser repair

1. **失败 / Failure：** 新浏览器的 Agent 定位正确，但 UIA 命中只有 Pane，报 `text_field_target_not_writable`。
2. **公共不变量 / Invariant：** 已明确进入文本聚焦上下文时，浏览器内容准备不能再依赖英文目标句式；截图可见不等于 UIA 文档已可读。
3. **修复位置 / Location：** `app/core/local_text_focus.py` 与 `app/operation/screen_reading/browser_content_readiness.py`，重用现有文档准备及绑定校验。
4. **通用性 / Generality：** 根据内部文本操作上下文触发，不写 Google URL、中文标签或坐标特例；浏览器地址栏排除保留。
5. **回归 / Regression：** `test_explicit_batch_focus_prepares_browser_without_goal_grammar`，修前失败、修后通过；batch-02 至 batch-05 失败留档，batch-06 首个双字段批次完成。
6. **影响 / Impact：** 没有降低可写性、窗口身份或坐标约束，也没有增加自动重放；诊断只补有限的类型/祖先信息，不记录字段私密值。

Explicit text-focus context now activates existing browser document preparation independently of natural-language goal grammar. This common-layer change retains editability, binding, coordinates and no-replay checks. The focused regression failed before the fix and passed afterward; earlier live failures remain preserved. Full-form, packaged continuous and independent AionUi acceptance still remain to be completed.
