# 组合动作验收记录 / Input-sequence verification

2026-09-21，源码工作树 `execution-publish-docs`，未构建、未发布。 / Source worktree only; no build or release.

## 结果 / Results

- `python -m pytest tests -q`：**785 passed in 26.57s**。 / Full current tests passed.
- `check_instant_entrypoints.py`：真实功能入口导入与参数校验通过；不是隔离交付包或真实输入验收。 / Source entrypoint imports/validation passed; not a frozen bundle or live-input test.
- `smoke_instant_mcp.py`：七个工具、非法参数后恢复、同 ID 回执、停止、重连读取均通过；`cleanup_verified=true`。 / Seven-tool stdio smoke, recovery, ID handling, stop and reconnect passed.
- 最新源码宿主：同一真实 Edge/Google 窗口，连续搜索 **3/3**，只填写不提交 **1/1**；拆分调用对照 **3/3**。逐张查看框架返回的原图，搜索词和相应结果一致；只填写仍保留原结果 URL，未回车。 / Latest host: three consecutive searches, one fill-only and three split-call controls passed, with original-image review. Fill-only retained the previous results URL.
- 正常关闭本轮创建的窗口；所有宿主与两条测试客户端完成清理。最终状态 `stopped`、`host_alive=false`、`pending_ids=[]`、`cleanup_verified=true`。 / Owned-window close and host/client cleanup verified.

## 耗时与体积 / Timing and size

均为模型已驻留后的实测，不含启动和人工/Agent 阅读间隔。 / Resident-model measurements, excluding startup and human/agent review gaps.

| 方式 / Mode | 单次秒数 / Seconds | 平均 / Mean |
| --- | --- | --- |
| 组合 / Grouped, 1 call | 7.444 / 9.694 / 11.936 | 9.691 |
| 拆分 / Split, 3 calls, summed tool time | 8.102 / 11.438 / 8.470 | 9.336 |

**未证明本地执行提速。** 小样本、页面动态不同、组合多了 UIA 内容核对，对照也主动消除了中间 Agent 思考间隔；不可由此宣称准确率 100% 或整体快几倍。已确认是三次外部调用合为一次，减少两次重新规划机会。 / No stable local speedup established. Small samples, dynamic pages and the grouped UIA checks prevent strong causal claims; the scripted baseline also excluded agent thinking gaps. Three calls become one, removing two intermediate planning round trips.

- 组合的聚焦约 4.30–8.07s，填写 0.44–0.45s，两次字段读取合计约 0.10–0.13s，Enter 与末帧观察约 2.24–2.26s。 / Focus dominates; checks and typing are small. Final observation retains the render grace.
- 同一 `final-003` 完整 JSON **894,570 bytes**；精简 JSON（含图片交付元数据）**4,152 bytes**，减少 **99.54%**。PNG 不计入 JSON 体积，未缩放；SHA-256 与交付元数据一致。完整诊断仍留磁盘。 / Same-receipt JSON reduced 99.54%; PNG bytes excluded, unchanged and hash-verified. Full diagnostics remain on disk.
- `wait_ms=0` 在 7.39ms 返回 pending，之后原 ID 取回只填写结果；没有重新提交。 / Zero wait returned pending in 7.39ms; completion was fetched under the same ID without replay.

## 首次失败与公共修复 / Initial failures and common fixes

首次失败原样保留，不改记为首次成功。 / Initial failures remain failures, separately from reruns.

| 失败 / Failure | 破坏的公共约定 / Invariant | 修复位置与回归 / Fix and regression |
| --- | --- | --- |
| `group-001`：点击被错误标为严格填写，未派发 / Focus mislabeled as fill | 聚焦点击不是填写操作 / Focus is not fill | `input_sequence.py` 复用普通单击；参数契约回归 / Plain-click contract |
| `group-002`：点击已发生，UIA 焦点暂未发布 / Focus publication lag | 瞬时只读未就绪不等于失焦，不能重放输入 / Read lag must not replay input | 同模块仅焦点未就绪时限时重读；身份错误不重试 / Bounded read-only retry |
| `group-003`：搜索发生，但进度 JSON 发布报 WinError 5 / Progress publication race | 文件读取不能让已执行动作丢失完成回执 / Readers must not break receipt publication | `core/json_snapshot.py`；持有读取句柄的真实 Windows 竞争测试 / Windows sharing-conflict regression |
| `continuous-003`、`fixed-001`：粗点在搜索框，裁图细化改点地址栏；未继续填写 / ROI refinement retargeted | 整图的位置描述不能直接重解释为局部裁图中的另一个控件 / Spatial intent must retain image context | `vision.py` 普通字段聚焦保留整图定位，不重复裁图；有/无网页 UIA 两条识别管线回归 / Full-context focus with/without document UIA |

第一轮定位修复仅依赖 UIA 字段几何，`fixed-001` 证明浏览器首次树尚无 Document 时不够；最终修复在普通字段聚焦的推理策略层保留完整语境。不是添加站点坐标、忽略字段读取错误或新安全策略。单词、按钮与严格填写路径保持原有语义；是否命中正确目标仍由 Agent 判读，不能把粗点当已验证。 / An initial geometry-only fix did not cover lazy browser UIA. The final plain-focus inference policy retains full context without site coordinates, ignored read errors or new risk policies. Word/button/strict-fill semantics remain; target correctness is still agent-judged.

另有测试驱动给 `maximize` 多传 handle/process_id，一次参数拒绝；修正驱动后原连接继续，非运行时崩溃。 / One driver-only invalid maximize request was rejected; the same connection continued.

## 证据与边界 / Evidence and limits

本机证据根目录 / Local evidence root:
`D:\agent-gui-runtime\reports\input-sequence-20260921-1789964805844`

- 早期失败：根目录 `responses/007,016,024.json`；早期跑通 `034.json`。 / Initial failures and early pass.
- `verified-run/responses/007,015.json`：两次裁图失败；`023–025.json/png`：最终连续组合；`026–034.json`：拆分对照；`035–036.json`：零等待与只填写；`038–040.json`：关闭及清理。 / Final continuous, split, fill-only and cleanup records.
- `entrypoints.json`、`mcp-smoke.json`、`verified-run/receipt-size.json`、`verified-run/timeline.json` 保留入口、协议、体积与每步时序。 / Import, protocol, size and timing evidence.

本轮不是学习模式、Google Maps 站内流程或整个执行模式的完整发布验收。跨站点、真实选区插入、弹窗干扰、长时间运行、冻结包与 AionUi 独立复测仍待完成；不能用本轮 3/3 代替总体稳定性指标。 / This is not learning-mode, in-Maps or full-release acceptance. Cross-site, live insertion, dialog interference, longevity, frozen-package and AionUi independent checks remain.

## 后续优化 / Follow-up optimization

2026-09-21：单次 UIA 快照内共享父链查询去重；791 项回归、三次新连续搜索与同批真实控件旧/新对照通过。原始上轮数据不改写，详见 [UIA 优化记录 / UIA optimization](EXECUTION_UIA_SCAN_OPTIMIZATION.md)。 / Snapshot-local ancestry deduplication passed 791 regressions, three new continuous searches and paired real-control comparisons. Earlier measurements above are preserved.
