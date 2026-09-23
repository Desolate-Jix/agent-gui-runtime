# 批量表单与真实失败修复 / Batched forms and real-failure repairs

2026-09-23，未发布源码；test.6 包未更新。用户随后恢复测试，当前实机记录见 [组合填写实测](BATCH_FORM_LIVE_ACCEPTANCE.md)。下方暂停记录为较早检查点，不代表当前状态。/ Unreleased source; testing resumed with user authorization. See the linked live record; the earlier paused checkpoint below is historical.

## 组合填写 / Grouped filling

- 一次 form_fill 可声明 1–32 个字段，文本、日期、下拉、单选、复选可混合，内部按顺序执行，一次返回整批结果和最终图。不要把同一已知表格拆成每字段一次 Agent 调用。
- One call accepts 1–32 declared fields, including mixed text/date/choice controls. Return one batch result and final image; keep detailed per-action evidence locally.
- requested_fields、completed_fields、remaining_fields、interrupted_at 同时进入精简回执。pending 只轮询原 request_id；失败不重放整批。
- Pending is not cancellation. Poll the same request ID; partial completion must never trigger replay of completed input.
- 可选 text_navigation=tab_sequence 只适用于 Tab 顺序已知的连续文本字段，每项提供确切可访问 label；只识别首项，后续 Tab → 核对标签/窗口/进程/可写身份 → 填写并读回。异常焦点在输入前中断。
- Optional tab_sequence is for consecutive named text fields only. It performs one initial recognition, then locally verifies each Tab focus and readback. Dropdown/file/calendar controls are not blind keyboard continuations.
- 不自动猜测离屏字段或跨页滚动；当前不可访问字段中断并返回剩余索引。文件选择仍使用明确的文件对话框步骤，不包含最终提交。
- Offscreen/unavailable fields interrupt; no guessed scrolling or blind cross-page continuation. File selection remains explicit, final submission excluded.

### 示例 / Example

~~~json
{"kind":"form_fill","request":{"text_navigation":"tab_sequence","fields":[{"kind":"text","field_goal":"Click the First name input","label":"First name","text":"Runtime"},{"kind":"text","field_goal":"Last name","label":"Last name","text":"Test"},{"kind":"text","field_goal":"Preferred Name","label":"Preferred Name","text":"TEST ONLY"}]}}
~~~

真实 httpbin 三字段已测得 Tab 组合提速，但不能外推到所有网站；当前代码仍待冻结候选和独立验收。/ A real httpbin three-field comparison measures a Tab-group improvement, not universal support. Frozen-candidate and independent acceptance remain pending.

## 已定位失败 / Evidenced failures

1. Preferred Name：同一 UIA 快照的文件按钮出现整页高度 (1378 px)，错误阻止了 31 px 高输入框的唯一可见标签关联。修复公共 form_label_binding 的同行控件分组，不硬编码页面或落点；原始快照离线回放现在恢复唯一真实 Edit 框。仍须真实识别复验。
2. Gender：请求为 Prefer not to say，原始选项已读到 Prefer Not To Say；不是 OCR 看不到，而是编排层仅逐字比较。改为精确优先，再匹配唯一 NFC/空白/大小写等价项，保留原始实际名称用于点击与值核对。碰到多个等价项仍报歧义，不使用子串/模糊匹配。缺失/歧义回执返回有界可见选项供 Agent 改正。

1. A full-height file-control wrapper incorrectly shadowed a short Edit field's adjacent label. The shared clustering fix restores the actual unique field from the recorded UIA snapshot, without site coordinates.
2. The Gender option was already in UIA; literal casing comparison rejected it. Exact-first, unique case/whitespace normalization now resolves the actual option and retains its original label. Collisions remain ambiguous.

## 状态 / Status

Paused live session: D:\AgentReviewAcceptance\20260923-form-tab-group-01. Only select/capture ran before pause; no grouped fill was dispatched. cleanup_verified=true, host_alive=false, pending_ids=[]. User browser preserved.

Evidence from prior actual form: D:\AgentReviewAcceptance\20260923-user-form-01. Raw screenshots/receipts remain private because the application URL contains a token. No packaging, push, external-agent acceptance or final submission.

3. 通用识别/按键未提供专用 popup HWND 时，原可见性函数把同进程自有下拉窗口当成外部遮挡。公共 window_manager 现在仍核验同 PID、原生 owner 与 popup 屏幕矩形；显式 HWND 继续精确匹配。外国窗口、错 owner/PID、矩形不可用或点在矩形外均拒绝。
3. Generic click/key visibility now recognizes an observed same-process owned popup inside its current native screen rectangle. Explicit popup bindings stay exact; foreign ownership/process, missing geometry and out-of-rectangle points remain rejected. This changes popup ownership classification, not a blanket interception bypass.

## 本轮边界 / Delivery boundary

早期暂停期间仅改源码与离线回归；之后的真实测试单独记录，不将旧版或替代路径成功当作当前版本验收。/ Earlier paused work was source-only; resumed live testing is recorded separately. Older or substitute-path success does not validate the current candidate.

## 离线验证 / Offline verification

- 完整源码回归：python -m pytest -q，1662 passed in 32.99s。
- 自有弹层独立复核：test_native_menu_ownership.py + test_generic_owned_popup_visibility.py，21 passed in 0.24s。
- git diff --check 通过。无本轮实机输入、无打包。
- Full source regression and focused popup tests passed; these are offline checks, not live acceptance.
