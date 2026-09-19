# test.3 跨网站测试状态 / Cross-site test status

2026-09-20。使用已经发布的 test.3，运行时不变，不新增 ZIP。 / Published test.3 runtime unchanged; no new ZIP.

## 已由 Codex 复核 / Reviewed by Codex

Wikipedia 首页搜索 Wellington，进入 `/wiki/Wellington` 文章，读取当前可见正文、下滚后重读、验证旧请求截图保持不变、上滚返回顶部，关闭本次启动的浏览器窗口并停止宿主。所有输入来自框架 `instant_*`，没有自建测试界面或替代输入后端。13 条命令回执、26 项图像摘要通过核对；文章标题、URL、正文及滚动变化已看图确认。清理返回 `cleanup_verified=true`，宿主退出。

Search and article navigation, fresh visible-text reads, scrolling, immutable old-request images and session-owned window cleanup were reviewed. All input used the framework on the real website; no mock UI or substitute input backend. Codex checked 13 command receipts and 26 image hashes and visually confirmed the article and scrolling effects, with verified host cleanup.

| 操作 / Operation | 本轮耗时 / Measured command latency |
| --- | --- |
| 识别点击 / Recognition click | 16.717 s |
| 填写 / Type | 0.507 s |
| Enter | 2.449 s |
| 读文 / Visible text read | 6.068–9.986 s |
| 滚动 / Scroll | 2.101–2.169 s |
| 关闭 / Close | 0.063 s |

不包含全部 Agent 编排时间，不代表普遍性能。 / Excludes full Agent orchestration; not a general performance guarantee.

## 外部 Agent 的报告 / Independent Agent report

AionUi 的独立 Wikipedia 完整流程最终报告 19 项通过、关窗和宿主清理完成、测试包清单未改变。维护者已读取最终报告，**尚未独立复核这轮全部原始回执和截图**；因此公开状态为“外部报告完成、证据复核待完成”。这与此前已经复核的 Google 22 项验收是不同轮次。

AionUi reports 19 final passing checks, owned-window/host cleanup and an unchanged package manifest. The maintainer has read its final report but **has not yet independently audited all raw receipts and images for this round**. This is reported completion pending evidence review, separate from the already-reviewed 22-check Google acceptance.

## 必须保留的失败 / Failures retained

- Codex：实际启动的两次任务尝试中，一次客户端误传 2500 ms（允许范围 0–2000）导致 Enter 被拒，另一次修正后完整通过；此前两次驱动空闲超时发生在宿主启动前，不算实际 UI 样本。 / Two started attempts: one invalid tester parameter and one corrected complete run. Two earlier pre-host idle expirations are not GUI samples.
- AionUi：首次因自身坐标字段解析错误中止；完成轮的关闭窗口结果曾读错层级，最终纠正。不能把最终检查项全通过写成所有尝试首次通过。 / An initial client coordinate-parsing failure and later close-result interpretation correction must not be presented as first-attempt success.
- AionUi 证据运行中超出 30 MiB，报告去除同摘要重复 PNG 后约 23.4 MiB；这不是自始至终满足空间上限，也不代表整个项目已清理。 / Evidence temporarily exceeded 30 MiB; reported deduplication reduced it to about 23.4 MiB. This does not establish a continuously enforced or project-wide storage cap.

## 尚未完成 / Remaining

这是一个新增真实站点案例，不是长期稳定性结论；未达到 50 任务样本门槛，未关闭历史偶发双击/缺帧根因。接下来复核外部原始证据，继续原生应用、异常恢复、操作覆盖和重复运行。先稳定性/操作，再速度，最后学习模式；不新增安全功能。

One additional real-site case does not prove sustained reliability or meet the 50-task target. Historical intermittent double-click/missing-frame causes remain open. Audit external evidence, then extend native-app, recovery, operation and repeated-run coverage. Stability/operations first, speed second, learning later; no new safety features.
