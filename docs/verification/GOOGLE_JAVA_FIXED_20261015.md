# 修复后的Google→java完整实测 / Fixed Google-to-Java live check

2026-10-15（Pacific/Auckland），未发布源码，单轮用户体感测试。 / One user-requested live round on unreleased source.

结果：打开原保留profile的新Edge窗口，地址栏输入Google网址，网页搜索框填写java，打开第一个普通结果 **Java | Oracle**。最终原图为 `https://www.java.com/zh-CN/`，三步completed、3/3成功，无执行中Main接管。 / The three-step plan completed automatically and reached the first ordinary result, Java's official page.

## 时间与判断 / Timing and decisions

- 自动三步调用方墙钟53.544秒，含该计划内定位、输入、复核、跳转及结算。 / The submitted plan took53.544s.
- 新窗口就绪至最终原图约93.061秒；计划外初始观察、Main读图及工具调度间隔包含在此范围。不能把53.544秒当作用户从打开窗口开始的全部等待。 / Window-ready to final capture was93.061s, including initial inspection and caller orchestration outside the plan.
- 10次Decision、2次普通Luna复核、3次定位，合计15个有返回的API请求。两次复核均在地址栏阶段将condition_not_met纠正为condition_met，HTTP3.939秒和1.933秒；没有超时。 / Two secondary reviews corrected address-bar rejections; all model requests returned.
- 已知总用量27,255输入/1,193输出，28,448 token。Decision顶层usage已包含二层，不重复相加；HTTP分别为定位15.904秒、首层5.367秒、二层5.873秒。 / Usage and HTTP scopes are separate and non-overlapping.

使用新short_question、8秒primary/12秒ordinary、原阈值及原裁剪。测试profile原样保留在证据目录，cap=60；实际Decision预算used=12，未用尽。 / The fixed profile, prompt and source remained frozen; thresholds and cropping were unchanged.

## 证据与收尾 / Evidence and cleanup

证据根 / Evidence root: `D:/AgentGUI-Projects/evidence/google-java-fixed-20261015-01`。

- `responses/10-plan.json`为原completed回执，`10-plan-timing.json`为调用方计时。 / Original task receipt and wall timer.
- `live-ledger-judgments.json`、`grounding-calls.json`及`live-metrics.json`保留实际判断、用量与计时。 / Read-only model ledger exports.
- Main及Sol只读审计查看Google结果原图和点击前图：第一个普通结果确为Java | Oracle，其上没有可见广告；点 `(348,400)` 在标题链接内。 / The selected point was inside the first ordinary result.
- 最终PNG位于session `runtime-output/local-direct-steps/local-step-d03ded7fb5f74abca0b983ab477386b2/observations/`，SHA256 `5f9ad11c53cebaa3d1521830b2c0eab422bde364e40114e7ce59ae329acd22ed`。 / Final screenshot retained.
- 18项history引用及36项冻结源码摘要均一致。 / All referenced evidence and selected source hashes match.
- `responses/99-finish.json`为cleanup_verified=true，runner退出0。未发送单独关窗命令；结束宿主后只读检查本轮测试浏览器进程已退出，页面没有保持打开，已向用户更正。 / Host cleanup completed; the test browser had exited afterwards, and the earlier intention to leave it visible was corrected.
- `D:/AgentGUI-Projects/test-profiles/amadeus-codex-runtime-edge`继续保留；本轮无缓存/资料删除、无日常profile或原标签修改命令。 / The existing named test profile and data were retained.

只证明这一次完整任务通过；不是连续多轮稳定性、独立实机验收或已安装版本已更新。没有为本轮改源码、重打包、提交或发布。 / One complete pass does not establish continuous reliability or installed acceptance; no production changes or release were made for this run.

## 只读延迟审计 / Read-only latency audit

用户反馈仍慢后，Main与两个Sol只读核对原回执和当前调用路径；未新增真实API/桌面测试，未改运行逻辑。 / Following the latency feedback, Main and two Sol workers inspected the original receipts and current call paths without new API/desktop tests or runtime changes.

窗口就绪至计划接收约40.807秒，其中初始截图自身约0.178秒。其余主要是计划外Main读图与工具调度间隔，不能记为Decision推理或运行时冷启动。优先在调用端预先准备计划，使用同一连接连续启动、绑定窗口并提交门禁计划，正常步骤不往返Main。 / About40.807s elapsed between window readiness and plan admission, including a0.178s initial capture. The main opportunity is caller orchestration: prepare the plan before launch and continue through the existing gated plan on one connection.

以下为计划53.544秒的非重叠分解，取整误差不足0.001毫秒；不能把嵌套的route/click/assessment计时再相加。 / The following categories partition the53.544s plan; inclusive nested timings must not be added again.

| 类别 / Category | 秒 / Seconds |
| --- | ---: |
| HTTP：3次定位15.904、10次首层5.367、2次普通复核5.873 / All model HTTP | 27.143325 |
| Decision服务非HTTP / Decision service excluding HTTP | 3.480319 |
| 定位服务非HTTP / Grounding service excluding HTTP | 0.423093 |
| 有独立计时的23次截图 / Individually timed captures | 5.317627 |
| 动作前截图包络 / Pre-action capture envelopes | 0.894577 |
| 派发前截图与目标区重验包络 / Dispatch capture and region recheck envelopes | 1.544525 |
| 本地后观察扣除截图 / Settled observation excluding capture | 6.056108 |
| 点击输入扣除场景截图和目标审核 / Click and typing excluding scene and target review | 2.746285 |
| 即时动作后核验扣除截图 / Immediate post-action verification excluding capture | 2.213300 |
| 本地计划构造、报告保存、身份绑定 / Local construction, report persistence and identity binding | 0.285751 |
| 尚未细分 / Unclassified remainder | 3.439158 |

后续顺序 / Recommended order:

1. **调用端连续调度**：先解决上述40.807秒间隔，保留运行时新截图、窗口绑定和门禁；不另建执行器。 / Remove caller round trips while retaining fresh evidence and gates in the maintained executor.
2. **同一阶段共享截图与核验结果**：33个不同原图路径只有14种PNG字节内容；截图及前置重验包络共7.757秒。但相同像素不等于不同时间的截图可以直接删除，须保留动作前新鲜证据，先合并同阶段重复采集和PNG落盘。 / Consolidate same-phase capture work; duplicate pixels alone do not justify reusing stale action evidence.
3. **统一动作后观察**：3次跳转各固定等待2秒，另有5次即时核验各等待250毫秒；统一采样与结果判断，页面已满足当前步骤条件时提前结束。不能仅凭画面变化认定跳转成功。 / Unify immediate and settled observation; finish on the current step's actual condition rather than a fixed delay or generic pixel change.
4. **定位单变量实验**：Luna定位HTTP15.904秒，实际输出1181token中含289推理token。当前未显式指定推理强度；可比较reasoning_effort=none，保持图片、坐标映射、原任务及返回契约不变，准确率合格才采用。连接池已复用，不把已有能力再算新优化。 / Compare non-reasoning grounding with identical evidence and mapping before adoption; connection reuse is already implemented.
5. **补足本地计时**：先定位Decision非HTTP3.480秒和未分类3.439秒，再决定是否优化图像准备或持久化；没有证据证明大JSON或轮询是主要瓶颈。 / Instrument the remaining local categories before assigning them to encoding, persistence or polling.

本轮没有实测优化后收益；上述耗时是现状，不是可全部消除的时间。保留Decision非通过→普通Luna→Main路线、现有阈值和浏览器资料。 / No speedup has been measured yet, and these costs are not all removable. Preserve the review cascade, thresholds and browser data.
