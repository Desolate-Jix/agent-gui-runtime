> **test.4 发布状态 / Release status (2026-09-21):** 本文契约实现已随冻结候选 10 交付。下文较早的“仅源码/待测试/test.3 未更新”描述保留为当时记录，不代表当前 test.4 状态。最新限定实测和未覆盖范围以 [FIXES.md](FIXES.md) 为准。 / Implementation ships in test.4; earlier source-only/pending notes below are historical. Consult FIXES.md for current coverage and limits.

# 单词目标上下文修复 / Word-target context repair

2026-09-20，源码未发布；公开 test.3 和冻结候选 07 未修改。 / Source-only; public test.3 and frozen candidate 07 unchanged.

## 故障与通用修复 / Failure and common repair

1. **Failure：** 同一真实记事本内双击 `Beta` 并替换成功，随后要求 `Double-click the word East at the end ...`，实际选中了 `South `。MCP 的操作派发成功不能作为目标命中证明；检查原图和只读 Edit 选区后停止替换，保留首次失败。 / The second word was misselected despite successful dispatch; inspection prevented replacement of the wrong word.
2. **Root invariant：** 明确的单词目标应保持词级身份，位置描述不能吞入标签并静默改走整行定位。共享解析器遗漏介词 `at`，未能抽出 `East`，随后使用整行 OCR 和 96 px 窄裁剪，目标在裁剪外。 / An omitted `at` delimiter lost word identity and switched to line OCR with a crop excluding the target.
3. **Fix location：** `app/operation/recognition/text_match.py` 的明确单词上下文边界增加 `at`，复用现有 `scan_words` 与至少 320 px 的词级裁剪。没有新增执行器、OCR 后备或重试。 / The shared parser now retains the word target and reaches the existing word-OCR path.
4. **Why not app-only：** 没有硬编码 East、记事本或坐标；同一解析/定位路径供网站和原生应用使用。引号内标签、多个备选词、近似词及重复词的原有约束不变。 / No application, word or coordinate is hardcoded; quoted labels and ambiguity handling remain intact.
5. **Regression：** 先得到 3 failed / 36 passed，再修复为 39 passed；包含实际句子、句首位置、引号内 `look at`、备选词及独立词框路由。扩展到相关目标和 Vista 契约共 100 passed。 / Red-to-green and related contract checks pass.
6. **Safety impact：** 未增加或关闭安全功能；本轮使用现有 operator 配置。修正定位输入而非放宽判断条件，效果仍由 Agent 查看原图判断，不自动重放。 / Existing operator configuration is unchanged; this repairs localization, not policy thresholds or effect verification.

## 原图复核 / Original-frame replay

- 首次模型点 `(58,26)`；真实失败原图 SHA-256：`11947f4a1d61169078a6ac8bd1e0126a1098e48267ccaf54a08996e2c3298410`。
- 固定同一原图、原模型点及原始指令，修复后真实本地 OCR 找到 `East`，框 `(104,24,32,16)`，点击点校正为 `(120,32)`，来源 `local_ocr_text_center`。 / Real OCR on the unchanged failure frame and point found the exact word and corrected its center.
- 复核不派发输入。`reports/execution-cross-site-20260920/word-at-replay/replay.json`；重跑脚本 `replay_word_at.py`。辅助脚本最初两处字段读取错误已修正，不计作产品错误或成功测试。 / Replay is read-only; two initial helper schema mistakes were corrected and excluded from product results.

## 新会话连续实测 / Fresh-session continuous acceptance

真实新建记事本，同一 MCP 连接，全程由框架 `instant_*` 操作，不制作测试界面。每步原图由 Agent 检查，另以只读 Edit 正文/选区独立核对。 / One continuous MCP connection controlling real Notepad, with image inspection and independent read-only text/selection checks.

| 目标 / Target | 实际选区 / Selected | 点击点 / Point | 含观察等待耗时 / Command ms | 替换 / Replacement |
|---|---|---|---:|---|
| Beta | `Beta ` | `(68,11)` | 3859.131 | `Delta ` |
| East | `East` | `(120,32)` | 3555.964 | `West` |
| North | `North ` | `(26,31)` | 3239.475 | `Central ` |
| West | `West` | `(134,32)` | 2977.728 | `East` |

四次定位均为 `local_ocr_text_center`。原生双击词中间位置可能包含尾随空格，替换按实际选区保留分隔符，不宣称选区一定等于纯单词。 / Native double-click may include trailing whitespace; replacements preserve separators based on observed selection.

模型准备本次 8510.052 ms，单独列出，不摊入点击；填入替换文字约 476–569 ms。本轮没有做速度优化。 / Cold model preparation is reported separately; no performance optimization was made.

最后正文经保存文件字节核对为 `Alpha Delta Gamma\r\nCentral South East`。两轮测试各自正常保存、框架确认 `window_closed` 后才退出宿主；两组 `cleanup_verified=true`，没有把客户端退出导致关窗算正常关闭。 / Both runs saved exact generated content and closed normally before host cleanup.

证据总索引：`reports/execution-cross-site-20260920/word-double-reviewed.json`；21 份 MCP 取图与原始回执内帧摘要匹配，两轮原始证据约 8.623 MiB（另有少量只读重放产物），低于本批 30 MiB 目标。 / Twenty-one image-to-source bindings were audited; raw evidence remains below the batch storage target.

## 限制与下一步 / Limits and next steps

- 这是一次失败留档和一次修复后连续任务；4 次选词不是 4 个独立任务，也不是按钮总体准确率。历史网站上其他偶发双击、滚动缺帧不能因此一并关闭。 / Four selections do not establish general button accuracy or resolve unrelated historical intermittency.
- 保存提示消失后旧目标事后图不可用：底层按键成功、外层 `operation_succeeded=false` 的既有边界仍在。Agent 本轮通过明确选择后继另存为窗口继续，没有重放按键。 / Successor-window observation remains an open usability boundary; the agent explicitly selected the successor without replaying input.
- 继续处理同文撤销、历史焦点来源与观察连续性；Codex 单项及连续实测完成后冻结一个候选，再由 AionUi 对同一候选独立验收。未派发本轮外部测试、未打包或发布。 / Resolve remaining state/observation issues before freezing and independently testing one candidate.
