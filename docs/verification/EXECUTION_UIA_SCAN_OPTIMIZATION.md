# UIA 同帧父链查询优化 / Snapshot-local ancestry optimization

2026-09-21，源码未发布 / Source-only, unreleased.

## 问题与修改 / Problem and change

- 上轮聚焦耗时中 UIA 扫描最高 4.735s。公共 `_confirmed_ancestor_control_ids` 为各控件重复调用共享祖先的 COM `parent()`，并非只有 Google 才有的路径。 / Prior focus UIA scan reached 4.735s. Shared ancestor COM reads were repeated for each control in the common provider, not a Google-specific adapter.
- 在一次函数调用内按现有 wrapper 身份复用已读取的父 runtime ID，失败也仅在本帧复用未知结果。函数结束即释放；下一快照重新读，不保留坐标或跨帧拓扑。 / Memoize parent runtime IDs by wrapper identity for one invocation only, including unknown reads. The next snapshot reads again; no cross-frame geometry or topology cache.
- 不减少遍历控件，不更改重复身份、环、零面积结构桥及失败前缀规则；不新增或放宽自动策略，不改变模型、输入路由和末帧等待。 / Traversal coverage, duplicate/cycle/structural-bridge handling, policy, model, input path and final-frame wait are unchanged.

## 验证 / Verification

1. 新增 6 项公共回归：共享读取、下一帧重读、重复身份、环、结构桥、读取失败。优化前 2 项失败（303 vs 102 次父级读取；失败节点读 3 次而非 1 次），优化后定向 43 项通过。 / Six regressions, with two confirmed red tests before the fix; 43 targeted tests passed afterward.
2. `python -m pytest -q`：**791 passed in 27.09s**。
3. 真实 Edge/Google，同一模型驻留会话连续三轮组合搜索；逐张复核框架原图，均显示对应关键词及结果。 / Three continuous searches in the same real browser session, each verified from the framework's original after image.

| 查询 / Query | 工具调用 / Tool seconds | UIA scan ms | 聚焦 / Focus ms | 输入 / Type ms | Enter + observation ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| Wellington museum | 7.753 | 270.809 | 4347.946 | 445.500 | 2258.205 |
| Auckland museum | 8.239 | 757.217 | 4149.272 | 467.521 | 2676.629 |
| Google Maps | 9.425 | 1336.881 | 5403.977 | 468.450 | 2246.887 |

工具平均 **8.472s**，上轮组合平均 9.691s；这是不同时间动态网页的小样本对比，不能把约 12.6% 的观察降幅认定为稳定因果提速。时间不含模型冷启动和 Agent 阅读间隔；本轮准备模型约 17.05s。 / Mean tool latency is 8.472s versus the prior 9.691s. This small, non-interleaved dynamic-page comparison does not establish a stable 12.6% causal gain. Cold startup and agent review gaps are excluded; model preparation took about 17.05s.

更强的局部对照：在同一批真实 UIA wrappers 上交替运行旧函数与新函数各三次，输出逐项相等： / Stronger component evidence: alternate old/new functions three times on the same real wrappers; all outputs equal.

| 快照 / Snapshot | 可见输出 / Traversed controls | 旧父链平均 / Old mean | 新父链平均 / New mean |
| --- | ---: | ---: | ---: |
| 完整窗口 / Full window | 237 / 250 | 866.016ms | 98.536ms |
| 浏览器外壳 / Browser chrome | 44 / 52 | 112.384ms | 36.208ms |

完整窗口的**父链计算**减少约 88.6%，不是整次 UIA 扫描或整个任务减少 88.6%。 / The 88.6% reduction applies only to ancestry computation, not the entire scan or task.

## 证据与边界 / Evidence and limits

`D:\agent-gui-runtime\reports\ancestry-optimization-20260921-1789967120861`

- `responses/005–007.json/png`：组合及原图；`008–010.json`：完整回执。 / Sequences, original images and full receipts.
- `ancestry_probe.py`、`baseline_ancestry.py`、`ancestry_probe.json`：只读同批控件对照；`summary.json`：汇总。 / Read-only paired benchmark and summary.
- `011.json` 确认本轮浏览器关闭；`013.json` 和 `cleanup.json`：host stopped、无 pending、cleanup verified，客户端退出 0。 / Owned browser closed; host and client cleanup verified.
- 首轮 Wellington 主结果已出现，但 AI Overview 仍显示加载占位；不据此声称整页所有异步内容都就绪。 / Wellington's primary result was visible while AI Overview still had placeholders; full-page asynchronous readiness is not claimed.
- 本轮无输入失败；3/3 不是总体准确率。未打包、推送或交 AionUi，跨站点/弹窗/长时运行与冻结包独立验收仍待补齐。 / No input failure in this slice; 3/3 is not a population accuracy estimate. No build, push or independent acceptance; broader coverage remains pending.
