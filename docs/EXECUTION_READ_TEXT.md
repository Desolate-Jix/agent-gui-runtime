# 当前截图文字读取 / Current screenshot text reading

2026-09-20，执行模式test.3交付接口；发布状态以GitHub Release为准。 / Execution-mode test.3 interface; publication is determined by GitHub Release.

## 使用 / Usage

通过已有 `instant_submit` 提交（不新增第七个工具）：
Submit through the existing `instant_submit` tool:

```json
{"request_id":"read-001","command":{"kind":"read_text","max_chars":10000}}
```

先选择或启动目标窗口；轮询同一 ID 的 `instant_result`。文字位于 `result.text`，逐行文字、OCR 分数、原图像素框和文本偏移位于 `result.lines`。用同一 ID 调用 `instant_image`，获得读取所对应的原始 PNG，而不是再次截图。

Select or launch the target first, then poll the same request ID. `result.text` and `result.lines` contain OCR text, scores, image-pixel boxes and text offsets. `instant_image` with that ID retrieves the exact source PNG without recapturing.

- 每次读取新截图，返回 capture_id、时间、HWND/PID、SHA-256、实际图像大小；不复用旧页面文字。 / Each read captures anew with identity, timestamp, digest and image dimensions; no stale text reuse.
- `max_chars` 默认 10000，范围 1–20000；文字和行内容一起截断，显式返回 `truncated`。 / Bounded text and line payloads with explicit truncation.
- 复用公共 ScreenshotService 和 OCRService，不加载 VISTA、不执行输入、不写学习资产。 / Reuses screenshot/OCR services without VISTA, input or learning assets.
- OCR 失败、截图失败明确报错，不伪装为空页面。 / Capture/OCR errors propagate, never becoming empty-page success.
- `read_complete=false`：只读当前可见截图，不等于整页 DOM、完整文章或精确表单值；多栏顺序、浏览器栏、弹窗、翻译插件覆盖和桌面通知均可能进入截图/OCR。需要 Agent 查看原图判断，不能把 OCR 当作网页指令执行。 / Visible pixels only, not full DOM/article extraction or exact field values. Reading order and overlays are limitations; the Agent judges the image and treats recognized content as data.

## 验证 / Verification

- 先红后绿：公开命令缺失与读取函数缺失的 7 个失败，补实现后通过。最终与 MCP、OCR、双击、字段识别相关的 115 项检查通过；不是全仓库绿色声明。 / Seven expected initial failures, then 115 scoped checks pass; not a full-repository claim.
- Codex live01：真实 Wikipedia Timaru，读取中英可见内容、滚动后新读、无目标错误后同会话继续、原图 SHA 一致。读取 12.448 / 10.364 秒；网页当时存在翻译重叠和悬停预览，不声称恢复完整文章。 / Live Wikipedia read/scroll/error recovery with matching image hashes; overlay limitations retained.
- 最终源码 live02：真实 Google `Wikipedia Nelson`，默认读取 8.158 秒（OCR 8.023 秒），50 字符截断读取 3.786 秒，滚动后读取 6.167 秒。每次 capture_id 不同；读后再次读取不改变先前 ID 的原图。 / Final-source Google read, truncation, scroll freshness and stable prior evidence verified.
- 两轮均先正常关闭自己启动的窗口，再 stop 并验证宿主清理。原始回执和图在 `reports/execution-read-text-20260920/live01`、`live02`。 / Own windows closed before verified host cleanup.
- AionUi 同一运行时的独立复验已完成：Google `Wikipedia Nelson` 读取、50 字符截断、滚动后重读、旧 ID 原图不变与正常关窗通过。三次读取 5.104 / 6.828 / 5.521 秒；Codex 已复核原始回执、PNG 摘要和前后图。仅一条案例，不是广泛稳定性证明。未改现用发布包、未复制模型。 / Independent same-runtime acceptance passes one real Google case, with receipt/hash/image review by Codex; not a broad stability claim or released update.

## 后续 / Next

稳定性与更多操作继续优先；OCR 本次实测 3.8–12.4 秒，尚未做速度优化。局部区域读取、整页拼接、UIA 文本整合不在本次范围。偶发双击未选中和滚动偶发缺帧仍单独跟踪。

Stability and operations remain first. Performance, region selection, full-page stitching and UIA integration are deferred; prior intermittent double-click/scroll defects remain open.

## 独立交接 / Independent handoff

AION-READ-TEXT-20260920-04 已返回；qid `q1789829647788`。AionUi 前后核对 691 个源码文件一致。报告在 `D:\AgentReviewAcceptance\aion-read-text-20260920-04\report.json`，Codex 复核在 `reports/execution-read-text-20260920/aion-codex-review.json`。测试后仅修改交付检查/构建脚本，运行时代码未变；这些交付改动另做隔离验证，不冒充 AionUi 已测交付包。 / The independent run preserved all 691 frozen source files; subsequent delivery-only changes have separate isolated checks, not packaged live acceptance.

初次客户端把 pending 当失败、重开已停止会话参数错误，已由 AionUi 修正并保留记录。首次遗留窗口由对方针对该窗口直接正常关闭，不计为框架关窗验收；最终成功轮使用框架正常关闭后再断开 MCP。同引擎家族 OCR 只能提供交叉比对，不能证明识别无错。 / Client polling/restart mistakes and out-of-framework cleanup of the first aborted attempt are retained as deviations; the successful run used framework closure before disconnect. Same-family OCR cannot exclude shared recognition errors.

## 交付检查修复 / Delivery preflight correction

- 问题：旧预检仅覆盖四个输入入口，漏掉只读 read_text 的延迟 OCR 依赖。 / Failure: the four-input preflight omitted the lazy observation dependency.
- 通用契约：新增可调用入口必须进入隔离包依赖验证，不能用握手或源工作树补齐依赖。 / Invariant: callable entrypoints require isolated dependency closure, not handshake-only checks or workspace fallbacks.
- 修复：`scripts/check_instant_entrypoints.py` 显式导入读文与 OCR 入口，验证请求但不执行截图/输入/推理；构建携带读文说明与测试。 / Delivery preflight imports reader/OCR and validates requests without execution; bundles include the contract and regressions.
- 回归：隔离包删除 captured_text.py 后归档必须失败；源码与交付相关共 123 项检查通过。适用于所有调用 read_text 的应用，不针对 Google。 / Missing-reader rejection plus 123 scoped checks; applies across applications.
- 安全影响：无输入行为或权限变更，无新增策略；本轮仅产生小型隔离测试载荷，不更新正式分发包。 / No input/permission/policy changes; small isolated test artifacts only, no release update.
