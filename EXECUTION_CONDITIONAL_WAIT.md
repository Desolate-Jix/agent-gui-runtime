# 显式条件等待 / Explicit conditional observation

2026-09-21：源码已验证，未发布；test.4 下载不含此接口。 / Verified in source only; not included in the published test.4 download.

## 接口与边界 / API and boundaries

`instant_run` / `instant_submit` 的 `step` 或 `input_sequence` 命令可增加： / Add to a step or input-sequence command:

```json
{
  "kind": "input_sequence",
  "request": {
    "field_goal": "Click the search input field at the top of the results page",
    "text": "Auckland museum",
    "clear_existing": true,
    "submit_search": true
  },
  "observation_wait_ms": 2000,
  "observation_condition": {
    "text": "Auckland Museum - Auckland Museum",
    "control_type": "Text"
  }
}
```

- `text` 是准确的 UIA 可访问名称，大小写、空白均不自动改写；`control_type` 必填，支持 `Text/Hyperlink/Button/Document`。不是模糊自然语言目标。没有可靠标志时省略条件，保留原有默认等待；条件等待没有被自动强加到全部动作。 / Exact accessible name and explicit type are required; this is not fuzzy goal matching. Omit when no reliable marker is known; unchanged defaults remain.
- 先读取动作前状态，再通过当前窗口的原生精确条件查询观察。必须先确认不存在，再新出现唯一可见目标；同一 runtime ID 与位置连续两次一致，间隔至少 100ms，截图后再次核对。既有匹配不能直接结束等待。 / Require observed absence followed by a newly appearing unique visible target, two consistent identity/geometry samples at least 100ms apart and a post-capture recheck. Existing matches cannot end the wait directly.
- 组合只在最后 Enter 的观察中使用条件；聚焦和填写不增加条件轮询。每次查询重新核对 HWND/PID/进程创建时间/路径与窗口几何，不缓存跨帧坐标或整个 UIA 树。 / Conditions apply only to final Enter observation. Queries validate current window/process identity and geometry without cross-frame coordinate/tree caching.
- `observation.condition.status=condition_met|timed_out`，精简回执也保留。`after_sha256` 绑定实际回传原图，详细采样记录保留在完整回执。取消或身份变化以结构化错误返回；不重放输入。 / Compact receipts retain condition status and the exact after-image hash; full receipts retain samples. Cancellation/identity errors never replay input.
- `completed` / `operation_succeeded` 仍只描述输入链，不意味着条件成立；`condition_met` 只证明指定 UIA 标志的出现，**不证明任务成功、整页加载完毕或目标可点击**。 / Input completion is not condition success, and a condition match is not task verification, complete page readiness or clickability.
- 等待预算必须为正数且不超过 2000ms；导航默认 2000ms。这是轮询预算，不是同步 UIA/截图 I/O 的硬超时。超时仍采集当前原图，实际耗时可能超过预算；回执明确 `deadline_scope=polling_budget_not_io_timeout`、`deadline_exceeded`、`capture_elapsed_ms`。 / Positive polling budget up to 2000ms; synchronous reads/capture may exceed it and are reported explicitly. A timeout still returns a current image, not a fabricated success.

## 验证 / Verification

- 新增 35 项回归；首次缺少功能和诊断字段的失败已实际运行后修复。定向 89 项通过；完整 `python -m pytest -q`：**826 passed in 26.66s**（最终同步后重跑，`final-pytest.log`）。 / 35 new regressions; confirmed failures preceded implementation/diagnostic fixes. 89 targeted tests and 826 full-suite tests passed; final rerun is also logged.
- 源码功能入口导入及七工具真实 stdio smoke 通过：非法参数后恢复、同 ID 取回、停止与重连；这两项本身不派发输入。 / Source entrypoint and seven-tool stdio smoke passed without input.
- 最终源码宿主，同一真实 Edge/Google 窗口 **9 次连续搜索 + 1 次 Escape 负向验证**，通过框架输入、核对和原图复核；两种条件类型（Text/Hyperlink）、条件超时与超时后恢复。10 张回传 PNG 与内部原图逐字节一致，摘要也与条件记录一致。 / Same-session real browser run: nine searches and one Escape negative control, using framework input and image review. Ten returned PNGs exactly match original files and condition hashes.

| 回执 / Receipt | 测试 / Case | 工具秒数 / Tool s | Enter + observation ms | 条件结果 / Condition |
| --- | --- | ---: | ---: | --- |
| 013 | Wellington 条件 / condition | 6.110 | 1151.838 | condition_met |
| 014 | Auckland 固定等待 / fixed | 6.189 | 2169.669 | 未启用 / none |
| 015 | Wellington 重复 / repeat | 6.131 | 1454.896 | condition_met |
| 016 | Auckland，不存在的标志 / missing marker | 5.776 | 2186.778 | timed_out，符合预期 / expected |
| 017 | Wellington，超时后恢复 / recovery | 5.626 | 1042.605 | condition_met |
| 018 | Auckland，Text 条件 / text marker | 5.349 | 1497.699 | condition_met |
| 019 | Wellington 固定等待 / fixed | 6.836 | 2307.026 | 未启用 / none |
| 020 | Escape，原本已有标志 / existing marker | 0.744 | — | timed_out，符合预期 / expected |
| 021 | Auckland，负控后恢复 / recovery | 4.701 | 761.447 | condition_met |
| 022 | Wellington 固定等待复测 / fixed repeat | 6.731 | 2170.945 | 未启用 / none |

五次条件命中的 Enter＋后图为 **0.76–1.50s**；三次固定等待为 **2.17–2.31s**。同目标 Wellington 条件平均 1.216s，对照 2.239s，观察减少约 1.02s。这是小样本组件测量，网络、页面和模型时间仍有波动，不能宣称总体速度/准确率保证。 / Successful condition waits took 0.76–1.50s versus fixed 2.17–2.31s. Wellington means were 1.216s and 2.239s, about 1.02s less. Small samples and varying network/page/model costs prevent overall speed or accuracy guarantees.

第一次单项 `005` 未提前结束：把截图标题 `Wellington Museum` 当成 Hyperlink 完整名称，实际主结果名称还带站点和 URL。框架如实返回 timed_out，搜索本身完成。只读探针记录实际名称后再测，不扩大匹配、不硬编码站点规则、不将原结果改记为提前结束成功。 / Initial test 005 timed out because its exact accessible-name condition was incomplete; the search itself worked. The observed full name was used afterward without loosening matching or rewriting the initial outcome.

## 证据、清理与限制 / Evidence, cleanup and limits

证据根目录 / Evidence root:
`D:\agent-gui-runtime\reports\conditional-wait-20260921-1789968200244`

- `responses/013–022.json/png`：最终连续测试；`023–032.json`：相应完整回执。 / Final continuous receipts/images and full counterparts.
- `005/006.json`、`probe_condition.py/json`：首次名称不匹配及只读诊断。 / Original mismatch and read-only diagnosis.
- `033.json`：本轮窗口正常关闭；`035.json`、`cleanup.json`：host stopped、pending 为空、cleanup verified；客户端退出 0。 / Owned-window close and host/client cleanup verified.
- `summary.json`、`timeline.json`、`entrypoints.json`、`smoke.json`：指标、原图一致性、调用时序与协议验证。 / Metrics, image equality, timing and protocol verification.
- 本轮没有输入误操作或崩溃，但这不是总体成功率；取消、身份变化、重复目标、UIA 失败、慢 I/O 分支由契约测试覆盖，未全部在真实桌面制造。 / No input misoperation or crash in this slice; this is not population reliability. Some fault cases are contract-tested, not all induced on the real desktop.
- 后图中主结果已出现，AI 概览/其他图片仍可能继续加载。若后续目标是这些区域，应指定对应可靠标志或继续观察，不能拿主结果条件替代全页就绪。 / Primary results were visible while AI Overview or other images could still load. Conditions must match the next required region.
- 尚未跨站点长时间稳定性验证、冻结包或 AionUi 独立验收；本轮未打包、提交、推送。 / Cross-site longevity, frozen-package and independent AionUi acceptance remain; no build, commit or push.

## 独立验收后续 / Independent follow-up

AionUi限定连续验收与两项回执修复已完成，当前836项回归通过；详见 [完整验收边界](EXECUTION_AIONUI_ACCEPTANCE_20260921.md)。前文未独立验收是本记录原始时间点；跨站点与长时覆盖仍未完成。 / Independent bounded acceptance and receipt fixes are complete; earlier pending statements describe the original checkpoint. Cross-site longevity remains unverified.
