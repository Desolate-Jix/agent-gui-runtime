# 输入框内部聚焦修复 / Editable-field focus fix

2026-09-21 · 未发布源码 / Unreleased source, based on test.4.

## 故障与公共契约 / Failure and common contract

- 故障：B 站首页第一次点击搜索框后，输入“女巫”没有进入字段。原回执的点击点 (1064,143) 在当帧 UIA Edit 的左边界 x=1071 之外 7 像素；后来调整目标描述才聚焦成功。首次失败保留，不能算首次成功。/ The original click was 7 px left of the current editable control; typing did not populate the field. A later reworded attempt worked. Preserve this first failure separately.
- 被破坏的契约：字段点击应传递“聚焦可编辑内部”的意图，而不是仅定位视觉外框/文字。普通点击输入框未走已有 fill_field 的内部聚焦提示。/ Plain field clicks lacked the interior-focus instruction already used by fill_field.
- 修复位置：公共 `app/api/vision.py::_vista_direct_prompt`。使用现有字段意图解析，为普通字段点击和结构化 input 目标补齐内部聚焦提示，保留目标全文和标签。/ The common prompt router now supplies interior-focus semantics while preserving full goals and labels.
- 非站点特例：没有 B 站域名判断、坐标补偿、固定边框或新模型；单词、按钮、图标和链接不改成字段。/ No site checks, fixed coordinates, new model or retargeting of word/button/icon/link goals.
- 影响：没有新增或放宽拦截；没有改变点击派发、重试和 Agent 判定契约。模型仍可能误定位，不能保证所有输入框均命中。/ Interception, dispatch, retry and Agent review contracts are unchanged. Prompt guidance is not a universal accuracy guarantee.

## 回归 / Verification

- 新增 11 项路由测试；修复前正确测试集为 6 失败、5 通过，修复后相关集 24 通过；全量 `python -m pytest -q`：754 通过。/ Eleven new routing tests; corrected baseline 6 failed/5 passed, focused suite 24 passed and full suite 754 passed.
- 同一 MCP 连接、真实 Edge、框架输入：原 B 站目标原文一次成功，点 (1100,143)，输入框真实显示“女巫”并进入结果页。/ The exact original goal succeeded at (1100,143), with visible text and search results.
- 同一窗口连续“女巫 → 女巫noita → 女巫”：三次字段聚焦、填写及 Enter 均由原图核对成功；随后点击首个视频，另取新图确认视频已加载。/ Three successive focus/type/search cycles passed; the first video opened and a later fresh capture showed playback.
- Google 跨站字段回归：聚焦、输入 bilibili、Enter 到结果页通过。/ Google focus/type/search also passed.
- 字段识别耗时：B 站首页 8.84 秒、结果页 12.40/11.46 秒、Google 6.15 秒；填写各约 2.51–2.59 秒。包含本轮观察等待，不是裸模型延迟。/ Field-click command durations include observation waits, not just inference.
- 本轮有限样本字段聚焦和文字输入 4/4；不是总体成功率估计，也不是新包独立验收。/ Four of four tested field interactions passed; this is not a population reliability estimate or independent release acceptance.

## 另外发现的问题 / Separate outstanding observation

关闭 B 站后立即启动 Google，首次返回 `launched_window_unavailable`，但后续 discover 找到了新窗口。显式 select 后回归通过。因启动回执未登记窗口，`close_launched_window` 报不属于本协调器；最终通过框架识别 X 关闭，并用 discover 确认消失。该启动/归属问题没有在此输入提示修复中解决，不能把整轮记为无错误。/ Immediate relaunch returned unavailable although a new window existed; explicit discovery/selection recovered it. The unregistered launch also prevented owned-window closure, so framework recognition clicked the verified test-window X. This separate launch/ownership issue remains open; do not report an error-free overall run.

两个测试窗口均确认消失，宿主停止，`cleanup_verified=true`、`host_alive=false`、无 pending/errors。/ Both test windows disappeared and host cleanup completed without pending requests or cleanup errors.

原始截图与请求回执只保存在本机 reports 目录，不随公开源码上传。本轮不打包、不发布，也未要求 AionUi 代替 Codex 做回归。/ Raw screenshots and receipts stay local; no packaging, publication or outsourced Codex regression in this slice.
