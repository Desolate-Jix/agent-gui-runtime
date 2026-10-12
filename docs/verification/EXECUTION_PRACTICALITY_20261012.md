# 执行链路计时与实用化方向 / Execution timing and practicality

本轮计时从目标创建 2026-10-11 13:31:29 UTC 开始，包含诊断、修复、离线测试、工具调用和 Main 等待；不得当成单次模型或 Runtime 延迟。最终任务回执2026-10-11 17:01:34.243 UTC：共3小时30分5.243秒。宿主和窗口随后正常清理；文档收尾另计。 / The task clock starts at goal creation and includes investigation, implementation, tests and caller gaps; it is not single-run runtime latency.

## 已测数据 / Measurements

| 范围 / Scope | 实测 / Observed | 口径 / Boundary |
|---|---:|---|
| Google 首页完整首步 / URL-to-home step | 19.605 s | target-outside-complete: 19.307148 s sequence + 0.297975 s final assessment wrapper |
| 上一成功首步的 Luna 定位 / Earlier successful grounding | 4.918 s | keyboard-freshness-fixed，包含在该步序列内 / nested |
| 同一 focus 动作本地调用 / Same focus local invocation | 7.961 s | 包含候选与变化审核，不能再与其子耗时相加 / includes nested reviews |
| 最终原计划 / Final initial plan | 14.482 s | Enter前已知拒绝 / known pre-Enter failure |
| 最终恢复四动作 / Final four recovery actions | 38.336 s | 已有URL输入后的恢复计划，到末步审核等待；非完整任务 / recovery only, to review wait |
| 恢复加Main确认 / Recovery plus Main settlement | 74.558 s | 上述38.336s已包含在内，不得相加 / includes38.336s; do not add |
| 本轮浏览器启动 / Observed browser launch | 4.031 s | native-value-full；宿主准备加启动6.222s，包含launch / host plus launch6.222s |
| 一次窗口截图 / One window capture | 0.13–0.15 s | 本轮样本，不是广泛基准 / observed sample |
| 已记录 Main 诊断空档 / Recorded caller diagnostic gap | 323.919 s | 两次 search 失败之间；不是模型推理 / between failed attempts |

最终已通过真实浏览器到达Java官网，恢复计划4/4结算。原始完整计划在Enter前失败，Main改用可见导航建议及页面搜索按钮；最后Decision仍不确定（condition=.68/review=.83），由Main查阅绑定截图后review/continue。全自动、免接管及连续稳定均未通过；不得把重新规划后的成功记为首次成功。 / The live task reached Java and the recovery plan settled4/4 after Main replanning and final review. Automatic intervention-free continuous acceptance did not pass; original failures remain.

## 优先顺序 / Priorities

1. 先对保存的真实正负截图验证Decision条件和证据范围：最终已加载Java页面仍被送Main，字段复核也出现.76/.06误拒，不能用盲降阈值或重复抽样掩盖。先消除错误停机与结果归类矛盾：同图不等于同次采集；异步failed终态不能丢掉已证明未输入的事实；字段光标变化不能触发多轮Main解释。此次已针对这些合同修复和验证，具体现场结果见审查记录。 / Remove false halts and receipt contradictions first; see the audit for exact validated behavior.
2. 减少串行模型调用：保留Luna定位和目标/可行性Decision，将已由同一字段的身份、值、选区事实确切证明的部分交给程序。空字段已实现免选区模型检查；其他重复检查只是后续方向，尚未删除。局部图在同次请求内供模型看清微小变化。 / Reduce serial calls; only eliminate checks where exact bound facts suffice. Empty-field selection is implemented; other consolidation remains future work. [OpenAI latency guide](https://developers.openai.com/api/docs/guides/latency-optimization)
3. 持续复用宿主、模型HTTP连接与工作会话；仅把相互独立的截图准备、候选预处理等并行，不能并行会改变焦点或输入状态的动作。 / Reuse hosts and connections; parallelize independent work rather than state-changing inputs. [OpenAI latency guide](https://developers.openai.com/api/docs/guides/latency-optimization)
4. 使用焦点直读和有限属性批量读取，避免桌面整树扫描。缓存用于读取提速，不缓存动作授权或把旧坐标当新证据。 / Use direct focused-element reads and bounded property caching; never cache authority or stale coordinates. [UI Automation element retrieval](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-obtainingelements), [UI Automation caching](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-cachingforclients)
5. 后续实用性验收按同会话重复成功率、无需Main接管比例、端到端中位数/尾延迟及错误动作数报告；同时列Luna、Decision、截图/派发、等待、Main空档，禁止把嵌套时间重复累加。当前少量调试样本不足以宣称泛化准确率或性能提升百分比。 / Report repeated success, intervention rate, median/tail latency and incorrect actions with exclusive timing categories; current debugging samples do not establish generalized accuracy or percentage gains.
