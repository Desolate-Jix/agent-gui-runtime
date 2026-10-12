# 2026-10-10 全流程性能审计 / End-to-end performance audit

## 范围与结论 / Scope and conclusion

本次按“用户指令→调用入口→模型准备→截图与定位→输入→结果核验→自动下一步”审查当前源码及既有原始计时。工作树为 `codex/dev-decision-api`，HEAD `5689d33738e75b722de7433454b2cc2661fd07da`，含尚未提交的修改；不是已安装候选的性能证明。CodeGraph 未初始化，本次使用定点源码查阅。没有新增桌面操作、模型推理或付费 API 调用，没有修改产品源码。 / This audit inspects current dirty source and historical measurements, not installed-candidate performance. CodeGraph was unavailable; scoped source inspection was used. No new desktop action, inference, paid API call or production-code change.

用户已决定保留控件扫描。提速重点是固定调用入口、按实际路线准备模型、批量采集必要控件、让常规步骤自动连续执行，以及缩短无条件等待。先闭合真实输入契约，不能以减少输入前核验来换速度。 / Retain control scanning. Prioritize a stable caller, route-specific model preparation, bulk control acquisition, ordinary-step continuation and condition-driven waiting. Repair the real input contract first and retain input-time validation.

## 已有计时及适用边界 / Existing measurements and limits

| 环节 / Stage | 既有证据 / Evidence | 解释 / Interpretation |
| --- | --- | --- |
| 用户请求至浏览器启动回执 / Request to launch receipt | 280.424s；成功 launch 本身 4.115s | 临时探查、桥接脚本及编排间隔显著；不能全算成模型推理。旧会话已复用宿主，并非每步重启。 / Preparation and orchestration were substantial; not all model reasoning or host restarts. |
| 失败的地址栏命令 / Failed address-bar command | 53.931s，其中模型准备34.794s、两次 UIA 扫描14.282s | 两项约占91%；此次实际视觉推理0、Decision请求0。新视觉路线确实需要模型，不能把全部冷加载算成可省时间。 / Zero actual inference and Decision requests in this failed run; the new visual route still needs a model. |
| 严格 UIA 属性对照 / Strict UIA property comparison | 770节点、24属性、4对；中位1763.70→223.91ms，约7.88倍 | 仅属性采集；完整 scanner 文本、pattern、图关系和弹窗合同待接入。严格公开页末轮 COM 失败保留。 / Property acquisition only; full scanner integration and the public-page COM failure remain open. |
| R2 Enter 后观察 / R2 post-Enter observation | 2092.149ms | 与无条件导航默认等待2000ms吻合；聚焦/填写显式等待0，不能每段都加2秒。 / Consistent with the 2s navigation grace; focus/type override it to zero. |
| R2 Decision | wrapper2501.262ms；service2490.9992ms；HTTP1504.4839ms；provider header596ms | 各层嵌套，不能相加。service减HTTP约986.515ms尚未细分，不能都称模型或图片编码耗时。 / Nested timings, not additive; residual local work is unclassified. |
| 截图与保存 / Capture and save | 旧慢调用中的单图约53–62ms；另一现场样本87.012ms | 已有活动窗跳过重复聚焦和PNG压缩优化；截图不是此前分钟级等待的主要来源。 / Active-window focus skipping and PNG settings are already optimized. |

原始记录 / Evidence: [慢速事故审计](EXECUTION_LATENCY_REAUDIT_20261010.md)、[UIA 对照](UIA_CACHE_BENCHMARK_20261010.md)、[R2 计时](../../.superpowers/sdd/2026-10-09-adaptive-live/LIVE_TIMING_BASELINE.md)。这些来自不同阶段，不能拼成同一次当前运行或发布收益。

## 按优先级的修改建议 / Prioritized recommendations

### P0：输入契约与固定调用入口 / Input contract and stable caller

- `app/api/action.py:3004` 传入 `pre_input_validator`，但 `app/core/input_controller.py:182` 的真实 `click_point` 不接受该参数。本轮纯离线签名绑定再次得到 `TypeError`；这是当前正确性阻断。应在真正落下鼠标前执行所需校验，并补真实签名契约回归，不能通过删除参数掩盖缺失。 / The real click signature rejects the caller's validator. Fix the common contract and validate before mouse-down; do not simply discard the validator.
- `scripts/execution_client.py` 已有持久 JSONL 调用能力，但未纳入交付入口和正式使用说明。当前会话也未提供项目的 `instant_*` 工具。应固定可复用的调用方式，避免临时搜索、生成桥接、等待 Main 编排。**MCP 配置继续指向 MCP server 是正确的；JSONL 客户端不能替代 MCP server。** / Formalize a reusable caller without confusing its JSONL protocol with the MCP server protocol.
- `validate_task_plan_dispatch_capture` 当前验证原图文件哈希和窗口身份/几何，不证明当前像素仍与旧图相同。减少抓图或增加缓存时，必须单独保持当前目标新鲜度。 / Old-file hashes and current window geometry do not prove unchanged current pixels.

### P1：准备与连续执行 / Preparation and continuation

- 在准备模型前确定路线，只准备本次真正使用的模型。现有驻留池和 `reuse_ready` 已存在；保留连续宿主，避免无用 OCR/视觉服务启动。冷启动单列，预热只是移动首笔成本。 / Resolve the route before preparing only required models; residency already exists, and prewarming shifts rather than removes cold-start cost.
- 使用既有 `task_plan` 的 `until_wait` 和 `input_sequence`：聚焦→输入→回读→Enter作为一项，已明确的后续步骤交运行时连续推进。当前计划支持1–8步，不支持动态输出变量；未知结果仍需真实观察/审核，不能假装预先知道。 / Use existing short plans and grouped input; unsupported dynamic outputs require observation or review.
- 保留原 `wait_id` 审核续接、部分输入回执和禁止整项重放。正常成功不会必然经历“本地→Decision→Main”三审；原生完整证明或已认证 Decision continue 已能直接采用。 / Preserve review identity and partial-input handling; successful local/Decision proof already avoids mandatory Main review.

### P1：控件与视觉定位 / Control acquisition and visual grounding

- 将必要控件属性逐项COM读取改为原生批量快照，同一新鲜快照内建索引并去重。先验证完整 scanner 等价性，尤其 rich_text 与 UIA Name 的差异、实际 pattern、图关系及 popup；不要一开始建立跨帧长期缓存。普通执行仍由模型定位，控件信息服务明确需要它的校验/学习路线。 / Integrate equivalent bulk acquisition and same-snapshot indexing before long-lived caches; preserve visual grounding as ordinary execution's role.
- **新发现：direct 视觉分支未应用初次图片缩放参数。** `action.py:897` 配置 `max_edge=640/1024`，`vision.py:8770` 却直接传原图，未调用现成 `_prepare_vista_direct_image`。应接通缩放及回原图坐标映射，检查小字、小目标和不同DPI。可能减少推理负担，但目前无收益实测，模型内部也可能再次缩放。 / Initial direct-image resizing is not wired; verify transforms and small-target accuracy before claiming gains.
- `refine=False` 在普通 direct 中已经生效；不要把它列作下一轮新增收益。 / Ordinary direct inference already defaults to no refinement.

### P1：结果等待与异常尾延迟 / Observation and failure latency

- 有可靠结果条件时，用现有有上限的条件观察替代无条件2秒等待，条件满足立即结束；加载中只追加观察，不重放输入。Decision既有0.5/1.5秒观察槽和最多两次评估，应评估是否减少真正的Main往返，不提高调用次数来制造进展。 / Prefer bounded condition-driven observation and never replay input while waiting.
- point服务默认45秒预算，客户端另加宽限可达105秒；通用provider格式失败另有多次尝试。分别审计各路线，统一总deadline、取消和明确错误，保留坏协议根因。此项针对失败尾延迟，不是健康请求收益。 / Audit route-specific total deadlines and cancellation; format retries and point-client grace are distinct mechanisms.

### P2：同一帧内的重复工作与输出 / Same-frame duplicate work and output

- `input_sequence` 每个子动作外层有前后采图，内层action还会抓取执行证据。量化后只合并同一观察边界的重复采集，不跨输入或模型等待复用旧图。现有字段回读样本约10ms，不能为节省小量时间删除。 / Deduplicate acquisition only within the same observation boundary; retain inexpensive authoritative field readback.
- Decision `evaluate` 与 `validate_result` 都走 `_prepare`，认证重验也会读图、校验并生成Base64。可将“验证原绑定/哈希”与“生成上传载荷”分开；学习图像重复解码/匹配同样先计时，保留最终采用认证。 / Separate evidence authentication from upload encoding and measure repeated image decoding/matching.
- 正常进度只返回紧凑状态及证据引用，失败或审核再取完整回执。旧失败报告落盘约2.60MB，response段紧凑JSON仍约1.14MB；保留原始证据，但避免重复进入Main上下文。已有 `run_plan` 紧凑输出可复用。 / Keep complete disk evidence while returning compact normal progress.
- overlay、重复JSON编码、轮询和实例枚举后置。旧overlay约86ms，落盘约52ms；25秒是提前返回的等待上限，不是固定sleep。Decision连接池已经复用并禁重试，无需重复实现。 / Lower-priority work includes overlays and serialization; existing early-return waits and pooled Decision connections should be retained.

## 下一轮验收 / Next verification

先修P0并通过共同输入契约回归，再按用户授权范围做同一冻结源码、同一真实任务的冷/暖分开对照。记录用户提交至首次可见动作、每步截图/模型/控件/输入/等待/Decision分段、Main往返次数、首遍成功率、错误点击及恢复完成率。延迟分布与样本数同时报告，不能把失败提前退出算提速。控件属性原型、源码单测和历史R2均不能替代整链验证。 / Repair P0 before cold/warm end-to-end comparisons; measure user-visible latency, stage timings, Main turns, first-pass success and recovery. Report sample counts and latency distributions, excluding premature failures from speed claims.

本次结论是优化顺序与源码缺口，不是已完成提速。README公共行为未因本轮审计改变；状态和后续计划同步此报告。 / This is an audit, not a completed optimization or new release; public README behavior is unchanged.
