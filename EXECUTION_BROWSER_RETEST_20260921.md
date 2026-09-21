# 浏览器与原生连续验收 / Browser and native continuous acceptance

2026-09-21 · v0.1.0-test.4 · 有人监督的 operator 模式 / Supervised operator mode.

## 通用修复 / Shared repairs

- 初始空剪贴板的零序号仅在持锁且确认没有格式时接受；非空、探针失败和写入后零序号不放行。 / Empty clipboard initialization is distinguished from failed/nonempty sequence observations.
- 明确引号标签保留角色，使用同一当前帧的唯一 UIA 控件约束首次视觉上下文；可见重复、部分可见和未知几何继续视为歧义。 / Exact quoted roles and current-frame identity constrain model context without ignoring ambiguous visible targets.
- 精确链接使用窄上下文，避免相邻结果行混入；模型落点仍须符合当前真实几何，不用合成框自证。 / Tight context prevents adjacent-link confusion; real geometry remains authoritative.

## 验证 / Verification

743 项隔离包回归通过，241 个运行时导入无原工作树泄漏；7 项构建检查和 MCP 零输入验证通过。源码与隔离集合重叠，不能相加。 / 743 isolated regressions, 241 imports without worktree leakage, 7 build checks and no-input MCP validation pass; counts overlap.

Codex 和 AionUi 分别在同一冻结候选上完成：新记事本三行文本、首行选区、不同文本替换与 Ctrl+Z、再次替换与原生菜单撤销、保存弹窗“不保存”；新 Edge 在 Python 文档搜索 csv、打开精确标题正文、Back，再重复正文/Back。正常关闭各自窗口，停止宿主并核对清理。 / Both agents independently completed native editing/dialog cleanup and two real browser article/Back loops on the same frozen runtime.

AionUi 首轮因客户端判据失败，修正后四组通过；保留五项客户端故障，不记为首次全部通过。维护者核验 562 个归档成员和 23 个原图引用。 / Five tester-client faults were retained separately from the successful rerun; raw artifacts were audited.

## 边界 / Limits

- Back 约 19.95–22.58 秒，链接 7.85–8.37 秒；不是性能保证。 / Measured command latency, not a performance guarantee.
- 原生撤销和 Back 使用既有 operator 覆盖，不是自动安全策略通过的证明。 / Existing operator override is not automatic-policy validation.
- 读取执行结果应使用 execution_path/agent_step_result 的实际执行字段，不把 recognition_plan 中 planning 快照的 false 当成实际未执行。 / Do not recursively select the first same-named scalar from a planning snapshot.
- 目标已退出后没有后图；用明确退出观察和独立窗口状态复核，不自动重放。 / Missing after-images on exit are not themselves task success or a reason to replay.
- 初始 UIA 正文缺失、翻译浮层 X、历史偶发缺帧/双击及跨设备覆盖仍有边界。 / Initial accessibility gaps, popup X, historical intermittent observations/selections and cross-device coverage remain limited.
