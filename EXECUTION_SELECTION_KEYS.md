> **test.4 发布状态 / Release status (2026-09-21):** 本文契约实现已随冻结候选 10 交付。下文较早的“仅源码/待测试/test.3 未更新”描述保留为当时记录，不代表当前 test.4 状态。最新限定实测和未覆盖范围以 [FIXES.md](FIXES.md) 为准。 / Implementation ships in test.4; earlier source-only/pending notes below are historical. Consult FIXES.md for current coverage and limits.

# 局部选区与文档导航 / Selection and document navigation

2026-09-20。**仅源码，未发布、尚未实机验收。** 公开 test.3 与冻结候选 07 仍支持原有 15 种编辑键。 / Source-only, unreleased and not live-accepted. Public test.3 and candidate07 retain the previous 15 keys.

## 小步范围 / Bounded scope

按执行优先计划 A 补齐局部选择与文档首尾导航，不建立新的输入器。共享 `EditingKey` / `EDITING_KEY_CHORDS` 增加 8 种组合，源码合计 23 种： / Extend the existing shared key contract with eight chords, 23 total in source; reuse the existing input backend.

| 新增 / Added | 常见编辑器语义 / Typical editor behavior |
| --- | --- |
| Shift+Left / Shift+Right | 扩展或收缩一个字符的选区 / Extend or shrink selection by a character |
| Shift+Up / Shift+Down | 按显示行扩展或收缩选区 / Extend or shrink selection by visual line |
| Shift+Home / Shift+End | 选择到当前行首或行尾 / Select toward line start or end |
| Ctrl+Home / Ctrl+End | 跳到文档开头或末尾 / Navigate to document start or end |

实际行为由目标应用决定，浏览器非文本焦点可能执行页面导航；不能把框架派发成功当作选区正确。 / The target app defines semantics. Non-editable browser focus may navigate the page; dispatch is not proof of selection.

## 调用 / Invocation

```json
{"kind":"step","operation":"press_key","request":{"key":"Shift+Home","x":100,"y":100}}
```

`x/y` 必须来自当前原图，是已有窗口校验点，**不点击、不改变焦点**。先观察焦点和光标，再发一个组合键，读取原请求的 `instant_image(view=after)` 判断选区。不自动填写、不自动提交，不支持任意快捷键。 / Coordinates do not focus or click. Observe current focus, issue one chord, then review its image; no arbitrary chords, typing or submission.

## 验证 / Verification

- 先验证新键在旧契约中失败，再修改共享枚举与虚拟键映射。 / Tests first demonstrate rejection by the old contract.
- 覆盖 MCP 接收并只入队一次、接口/后端一致、修饰键先按下且倒序释放、失败后仍释放已尝试按键、不重放、导航键扩展位。 / Regression covers admission, schema/backend agreement, modifier ordering, failure release without replay, and extended-key flags.
- 当前定向回归：`test_local_editing_keys.py`、`test_instant_mcp.py`、`test_instant_bundle.py`、`test_local_step_observation.py`、`test_local_step_timings.py` 共 188 项通过。它们不发送真实桌面输入。 / 188 scoped checks pass; these do not dispatch live desktop input.
- 桌面由 AionUi 的既有验收占用时只做后台检查；不得以单元测试替代实机选区截图。 / Background checks do not substitute for live selection evidence.
- 下次实机：全新记事本多行内容，逐个验证 8 种新键、选区替换及撤销，正常清理后，再交同一冻结候选给 AionUi。 / Next: validate all eight chords and selection replacement/undo in a new Notepad, then independently repeat the same frozen candidate.


## 实机补充 / Live follow-up

上文“下次实机”已完成源码首次验证：全新记事本，8 种新键的独立只读 `EM_GETSEL` 结果均符合预期，并保留框架原图。Shift+Home 选中第三行，填写 Gamma 只替换该行；Ctrl+Z 恢复原文和 [22,32] 选区。 / The source-only first live run verifies eight chords and selected-line replacement/undo, with independent read-only selection queries and framework images.

初始八键 346.058–356.297 ms，含 250 ms 观察等待；不是模型识别耗时。追加 Shift+Home 曾因键盘派发前目标不在前台失败，未自动重放；新截图核对状态后用新请求继续，原失败保留。不能据此宣称 100% 稳定。 / One subsequent focus-loss failure is retained; no automatic replay. This is not a long-run reliability certificate.

20 条命令、16 张取回原图全部与回执原件摘要核对；窗口正常关闭、宿主清理通过。证据 `reports/execution-cross-site-20260920/notepad04/`、`notepad34-reviewed.json`，约 1.12 MiB。188 项定向回归再次通过。 / Receipts/images and cleanup checked; 188 scoped tests pass again. No frozen candidate, ZIP or public release changed.
