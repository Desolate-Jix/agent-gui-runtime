# UIA 批量缓存可行性测试 / UIA bulk-cache feasibility

日期 / Date: 2026-10-10. 用户批准“测试一下”。本轮只读测量真实 Windows UIA；测试页面自身按受控状态更新，没有鼠标点击、键盘输入、模型推理或付费 API 请求。正式执行源码未在本轮修改。 / User-authorized, read-only Windows UIA measurements. The fixture changes its own state; no clicks, typing, inference or paid calls. Production execution code is unchanged in this slice.

## 结论 / Conclusion

**可以保留控件扫描能力，原生批量采集值得接入验证；不能据此保留当前每步数秒的扫描实现。** 最新严格对照在 770 个节点上完成 4 对相同范围、相同 24 项属性的检查，中位数 1,763.70 → 223.91 ms（约 7.88 倍），无字段差异。公开文档初测有提速，但最后一次严格复测在逐属性读取时发生 COM 异常，未计通过。当前完整 scanner 和整条执行速度仍未验收。 / Retain the capability and validate bulk integration. Four strict pairs on 770 nodes show 1,763.70 → 223.91 ms with equal values (7.88×). The final strict public-page run failed during a current-property COM read and is not a pass. No full-scanner or action-pipeline acceptance is claimed.

## 最新严格复核与失败保留 / Strict follow-up and retained failure

独立审查发现初版把未知 COM 对象仅归一化为类型名；因此下表第三轮的“24 项一致”仅指归一化输出一致，不能证明原始对象值相同。第四轮 `run-20261010-211925` 改为调用 UIA `CheckNotSupported` 明确认定保留值，其他未知对象抛错，并交替 cache→current / current→cache 顺序。 / Initial opaque COM objects were compared only by type. The fourth run uses `CheckNotSupported`, rejects unknown objects, and alternates measurement order.

受控页面 4 对均为 770 个唯一 RID、24 项属性、缺失/额外 RID 0、差异 0；每份 7,549 个不支持值均经 UIA 明确确认，非类型占位。缓存中位 223.91 ms，范围 205.26–312.51 ms；逐属性中位 1,763.70 ms，范围 1,638.49–1,975.24 ms。 / Four controlled pairs pass strict value, sentinel and ID checks.

同轮公开页在 `flat_snapshot` 的 `GetCurrentPropertyValueEx` 抛出 COMError `-2147220991`（“事件无法调用任何订户”），子进程和该轮 runner exit 1；未输出完整配对结果，故不计严格公开页通过。确切 provider 内部原因、具体字段与发生于第几对未记录，不猜作缓存错误或页面错误，不以此前通过抹掉本次失败；原有 3 对归一化初测仍保留其有限证据。两个本轮窗口均正常关闭。 / The public-page current-property read failed with COMError -2147220991. The provider cause/property/pair number is unknown; this remains a failed follow-up, not a cache success. Both owned windows closed normally.

## 同范围对照 / Matched-scope comparison

第三轮范围纠正运行 `run-20261010-211434`，每场 3 对样本，以下仅为初测。双方使用 `TreeScope_Subtree` 和 `ControlViewCondition`；缓存使用 element scope 和相同 tree filter。计时包含获取根、FindAll/FindAllBuildCache、读取属性和建立名称/类型索引；不含 Python 导入、启动浏览器和网络加载。固定先 cache 后 current，属于预热对照。 / Third-run preliminary results, three pairs per case. Timings include acquisition, enumeration, reads and indexing, excluding imports, launch and page loading; order was cache then current, after warm-up.

| 场景 / Case | 节点 / Nodes | 逐属性读取中位数 / Current properties | 批量缓存中位数 / Bulk cache | 比率 / Ratio |
|---|---:|---:|---:|---:|
| Edge 受控 180 条记录页面 / Controlled 180-record page | 770 | 1,702.48 ms | 265.95 ms | 6.40× |
| Edge 真实 Microsoft Learn 文档 / Real public documentation | 354 | 682.17 ms | 96.11 ms | 7.10× |

受控页面缓存范围 193.97–307.52 ms，逐属性 1,519.83–1,977.63 ms；公开页面缓存 95.36–101.44 ms，逐属性 660.72–689.22 ms。6 对均无缺失/额外 RID，基础值及未知 COM 对象的类型占位相同。每份分别有 7,549 / 3,510 个类型占位，不能声称其原始值已经核对；严格复核见上节。 / All six pairs have equal IDs, primitive values and opaque object-type placeholders; 7,549 / 3,510 placeholders per sample were not raw-value equivalence evidence. See the strict follow-up above.

24 项为 RID、PID、framework、HWND、Name、type、automation ID、class、rectangle、enabled、offscreen、password、focusable、focus、两个 scroll 属性及 8 项 pattern 可用标记。缓存设为 `AutomationElementMode_None`，读取不会暗中转为 Current 属性访问。 / Twenty-four identity, geometry, state and pattern-availability properties; cached-only mode prevents hidden current-property fallback.

## 树缓存、索引与变化 / Tree cache, index and changes

`ElementFromHandleBuildCache(Subtree, true filter)` 连同缓存父子树解码与建索引，最新一轮受控页面约 1,524 节点：首次 232.30 ms，7 次中位 226.35 ms，范围 200.25–243.03 ms。公开文档约 801 节点：首次 112.04 ms，中位 108.80 ms，范围 100.12–119.19 ms。上一轮受控首次为 381.17 ms，应保留该抖动。不是 OS 冷启动测试，也不是截屏到点击的总耗时。 / Whole raw cached tree, decoding and indexing are roughly 0.1–0.24 s in the final run; a previous first call took 0.381 s. These are not OS-cold or screenshot-to-click timings.

索引建立通常不到 2 ms；本地字典命中/未命中查询处于亚微秒量级，接近微测量分辨率。它不含新鲜度验证，不能成为主要速度宣传。主要收益来自减少跨进程逐项读取。 / Index construction is usually below 2 ms and dictionary lookup is sub-microsecond; neither includes freshness validation. Bulk acquisition is the material improvement.

三个受控变化阶段各读取 7 次新快照，三轮均符合预期： / Seven fresh snapshots per changed state, verified in all three runs:

- 新增同名按钮：数量 1 → 2；索引保留歧义，不取第一个冒充唯一。 / Duplicate target: 1 → 2, preserving ambiguity.
- 删除目标：数量 → 0。 / Removed target: zero matches.
- 滚动 500 px：同 RID 的 `Value 0` 框 y 从 272 → -228；刷新读到变化，旧坐标仍留在旧快照。 / Scroll: same ID moves by 500 px; a fresh snapshot sees the new geometry.

最终变化阶段完整 raw 树刷新中位数分别为 186.22、188.91、189.76 ms。由测试页确认状态已应用后再刷新；**没有实现或验证生产事件失效、局部增量更新或跨帧执行授权**。扫描如此快时，可以先验证每步新批量快照，避免过早引入复杂的长期索引。 / Changed-state refresh medians are about 0.19 s. Automatic invalidation, incremental refresh and cross-frame action authorization remain unimplemented. Fresh bulk snapshots may be the simpler first integration.

## 与现有完整扫描的差异 / Full-scanner limitations

有效对照运行 `run-20261010-211228` 中，生产 `snapshot_window(max_controls=4000)` 完整返回：受控页面 14.85 / 16.65 s，公开文档 8.60 / 8.24 s。批量 raw 树包含全部生产输出 RID，但节点范围更宽，不能直接相除宣传“整体快 80 倍”。 / Production snapshots took 8–17 s in these cases; raw cached trees contain all output IDs but have a broader node view. An overall 80× claim would be invalid.

公开文档的 346 个生产控件中，48 个名称与纯 UIA Name 不同：46 Text、1 ComboBox、1 ListItem。现有实现会读 `TextPattern.DocumentRange.GetText(-1)`；仅缓存 Name 不能等价替代。原型还未覆盖实际 pattern 接口探测、canonical parent/alias/cycle 校验、独立弹窗/菜单、原生 Edit 客户区与表单标签关联。 / Forty-eight production names differ from UIA Name; rich text and the remaining graph/pattern/popup/native-edit contracts require separate integration and verification.

首轮公开页面被启动期间的扩展引导页切换污染，扫描节点和页面不稳定，包含一次不完整扫描。该场原件保留、排除性能结论；后两轮使用新的临时 profile、InPrivate、禁扩展/同步，并等待匹配的 Document 和内容树后采样。 / First public-page measurements were contaminated by startup extension pages and are excluded; corrected runs retained fresh isolated profiles and verified document readiness.

项目截图接口有一次早期白帧，后续公开页截图因遮挡被门禁拒绝；没有绕过门禁。UIA 属性读取不要求前台，因此本报告仅证明只读采集，不能充当可点击性、视觉核验或完整动作验收。 / An early white screenshot and later occlusion rejection are retained. UIA read timings are not visual or action acceptance.

## 证据与复现 / Evidence and reproduction

- 目录 / Directory: `.superpowers/sdd/2026-10-10-uia-cache-benchmark/`。
- `probe.py`：新建临时页面/浏览器、生产扫描、原生缓存及清理窗口。`analyze.py`：RID/字段集合对照、目标数量与滚动检查。 / Probe and analysis scripts.
- `analysis.json`、四轮 `manifest.json` 和逐样本 JSON 保留原始时间与控件字段；后两轮保存确切 `probe-source.py`。 / Raw timings, fields, manifests and the later exact source snapshots.
- 实际命令 / Executed: `D:/agent-gui-runtime/.venv/Scripts/python.exe -B -X utf8 .superpowers/sdd/2026-10-10-uia-cache-benchmark/probe.py` 两轮，以及同命令 `--quick` 一轮，前三轮 exit 0（包含上文排除的污染样本）；第四轮 `--quick --paired-only` 因公开页 COM 异常 exit 1。分析命令 `.../analyze.py` exit 0，只表示已保存结果的断言通过，不将第四轮改记为完整成功。 / First three runners exit zero, strict fourth runner exits one; analyzer success does not erase the failed live run.
- 四轮各自创建的两个窗口均按 HWND/PID 核对后正常关闭，未关闭原有应用。临时 profile 删除命令被自动审批以 `blocked by policy` 拒绝，未执行删除；原件和临时 profile 保留在上述单一实验目录。 / Eight owned windows closed; automatic approval blocked temporary-profile deletion, which was not performed.

下一步：先闭合已知 `pre_input_validator` 真实方法签名问题；将批量采集接入当前字段/安全合同并保留失败信号，再测完整截图→定位→输入→Decision→下一步。保留控件能力的决定不改变普通执行模型定位的默认职责，也不自动重新启用每步旧式整树扫描。 / Next fix the known input signature gap, integrate bulk acquisition without dropping contracts, then benchmark the whole execution chain. Retaining the capability does not silently restore slow mandatory scans.

参考 / Reference: [Microsoft UIA caching contract](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-cachingforclients).
