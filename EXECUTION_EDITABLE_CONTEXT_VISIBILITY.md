> **test.4 发布状态 / Release status (2026-09-21):** 本文契约实现已随冻结候选 10 交付。下文较早的“仅源码/待测试/test.3 未更新”描述保留为当时记录，不代表当前 test.4 状态。最新限定实测和未覆盖范围以 [FIXES.md](FIXES.md) 为准。 / Implementation ships in test.4; earlier source-only/pending notes below are historical. Consult FIXES.md for current coverage and limits.

# 编辑区右键可见范围 / Editable context-click visibility

## 状态 / Status

源码修复，冻结候选 09 未改动且独立验收失败；318 项相关源码回归通过。source19 的编辑区菜单、撤销、不保存及网页命名搜索已实测；source20 的后退复验在点击前被重复 UIA 遍历阻断。公开版本仍为 test.3，新冻结包独立验收未完成。 / Source repairs have scoped regression and live evidence, but candidate09 failed independent acceptance and remains unchanged. Source20 was blocked before input by repeated UIA enumeration; public test.3 remains unchanged.

## 故障与不变量 / Failure and invariant

AionUi task18 的记事本右键位于 `(1264,681)`，完整编辑器范围为 `(0,0,2560,1335)`；通知只与编辑器右下边缘重叠 `152×9` 像素，却触发整个区域拒绝。定位容器范围不等于动作要求完全可见的交互范围。 / The click point was clear, but a notification overlapped a small corner of the full editor. A localization container is not the complete visibility footprint required by a point interaction.

修复位于公共识别点击范围分类及现有输入回执，不加入记事本或通知软件特例，不根据容器大小猜测，也不修改候选选择、grounding 结论或输入授权。 / The shared recognition-click classifier and existing receipt path are repaired without application exceptions, size heuristics, new grounding claims or authority changes.

## 明确边界 / Exact boundaries

- 仅现有本地操作模式、明确指向文本字段的右键操作，才考虑容器点语义。按钮、菜单项、单词、双击以及学习审批路径不改变。 / Only explicit generic-field right-clicks in existing local operator mode are eligible; buttons, menu items, words, double clicks and learning approvals are unchanged.
- 必须有同一图像、完整且未截断的当前 UIA 扫描；可见启用的唯一 Edit/Textbox 具有 Value/Text 模式，候选 source ID、真实框、图像尺寸和落点全部一致。缺证据保持原完整候选框检查。 / Require a same-image complete UIA scan, a unique visible enabled editable control, matching source identity and real bounds, valid dimensions and point. Missing evidence retains the full candidate-box check.
- 合格的容器右键保留原候选框，另记 `click_visibility_scope.scope=editable_container_point`，实际可见足迹为输入点所在的 `1×1` 像素。实时窗口归属、前台、鼠标和绑定变化仍由原输入层检查；点被遮挡时不能按下鼠标。 / Preserve the candidate box and record a separate 1×1 point footprint. Existing live ownership, foreground, pointer and binding checks still prevent dispatch when the point is blocked.
- `point_visibility` 与 `region_visibility` 分别留证。区域拒绝不能覆盖已有的点归属观察，更不代表目标点一定被遮挡。 / Keep point and region observations separate; a region rejection must not overwrite point evidence.
- 仍由 Agent 读取原图判断效果；无变化、缺图或拒绝都不会自动重放。 / The Agent still judges effects from original images; no automatic replay.

## 回归与验收 / Regression and acceptance

### UIA 有限遍历 / Finite UIA enumeration

source20 的同一 Back 控件在浏览器外壳树按 289 个节点的周期重复，主树和外壳树均耗尽预算，不能据此宣称目标身份唯一。公共 provider 改为直接读取 `FindAll(Children)` 有限数组、按预算取元素，不再依赖兄弟游标迭代。主树、外壳、菜单与浮窗共用遍历；环、重复身份、缺身份及 COM 读取异常保留诊断并标记扫描不完整，不放宽输入策略。 / Repeated Back identities exhausted both budgets in source20. The shared provider now reads finite child arrays within budget instead of sibling iterators. Cycles, duplicates, missing identities and COM failures remain explicit incomplete scans; input policy is unchanged.

364 项相关回归通过。source23 真实首次设置页面的只读扫描为主树 75、外壳 62 个控件，均完整且无遍历错误。该页面要求用户自行处理隐私设置，未执行识别点击；这不是网页搜索/后退完整验收。测试窗口与宿主已清理，新冻结包独立验收仍未完成。 / 364 scoped tests pass. Real first-run-overlay scans completed without traversal errors; browser privacy setup prevented click retesting. This is not full search/Back acceptance. The test window and host were closed; independent new-bundle acceptance remains pending.

### 原生编辑区及命名字段 / Native client area and named fields

当前原生 Edit 另采集 `native_client_geometry`：验证 HWND 的根窗口、进程、类及 UIA runtime identity，读取物理像素客户区（不含原生滚动条），不改变原 UIA 框。明确泛型编辑区右键可直接以唯一当前客户区中心主定位；不是模型失败后的换点兜底，不宣称菜单或任务已经成功。 / Observe the native Edit client rectangle with matching window/process/runtime identity. Generic editor context-clicks may use its current center as the primary locator, not a model-error fallback or an effect-verification claim.

`Quick search input box` 等命名字段保留完整名称；不得把限定词丢掉后用地址栏等任意 Edit 作为当前身份。 / Named field qualifiers remain part of identity; an unrelated address bar cannot corroborate a named webpage field.

### 绝对鼠标坐标 / Absolute mouse coordinates

source19 在 2412×1080 桌面上暴露 x=10 被旧向下取整公式发送到 x=9。修复为发送目标像素对应归一化区间的中心，保留按下前精确位置检查；错误信息补充期望、实测与移动后屏幕坐标。该修复不扩展多显示器能力。 / The old conversion sent pixel 10 to pixel 9 at 2412×1080. Send the center of the normalized pixel interval while retaining exact pre-down checks and reporting actual/expected positions. This does not expand multi-monitor support.

接口范围参见 [Microsoft MOUSEINPUT](https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-mouseinput)；区间换算也可对照 [Chromium input implementation](https://chromium.googlesource.com/chromium/src/+/main/ui/base/win/event_creation_utils.cc)。 / See the platform contract and a reference implementation above.

本轮 318 项相关源码检查通过；source19 已真实验证两次编辑区右键、菜单撤销、不保存及网页命名搜索→正文。source20 没有执行点击，已关窗并确认清理；它没有验证鼠标换算修复。新包独立验收未完成。 / 318 scoped checks pass; the listed source19 effects were observed. Source20 executed no clicks and ended with verified cleanup, so it did not verify the pointer fix. New-bundle independent acceptance remains pending.

离线覆盖完整/缺失/重复控件、错误角色和标签、陈旧图像、越界、被遮挡的真实点、精确按钮边缘遮挡、路由足迹及错误证据。实机必须另验编辑区右键、菜单操作、通知有无两种状态和正常收尾；离线通过不代替这些实测。 / Offline checks cover identity, role, freshness, bounds, blocked points, exact-button occlusion, route integration and evidence. Real context-click/menu journeys, with and without peripheral occlusion, and cleanup still require live acceptance.
