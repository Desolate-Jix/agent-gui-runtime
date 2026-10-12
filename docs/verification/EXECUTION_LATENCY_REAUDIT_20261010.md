# 执行慢速复查 / Execution latency re-audit

Date: 2026-10-10. Scope: the failed Google → Bilibili request in this conversation. Read-only investigation of the recorded run plus one offline signature check; no desktop input, capture, model startup or paid API request.

范围：复查本对话中失败的 Google → 哔哩哔哩执行。只读核对原始记录并检查一次真实输入方法签名，本轮没有操作桌面、截图、启动模型或调用付费 API。

## 结论 / Finding

分钟级等待的主因是执行前的 Agent 编排，以及首次动作中未使用的模型加载和两次控件树扫描。索引实验不解释这些耗时。旧执行已经使用同一个 MCP/宿主会话，不能将其误诊为每次动作都重启宿主。源码优化尚未完成正式入口接线与验收，还发现一个真实方法参数不匹配。

The minute-scale delay came from pre-execution orchestration, followed by loading an unused model and two control-tree scans inside the first action. Indexing does not explain those costs. The old run already reused one MCP/host session. The source optimization has not completed entrypoint integration or acceptance, and an input-method argument mismatch remains.

## 时间账 / Timeline

原始对话记录 / Transcript:

`C:/Users/DesolateJix/.codex/sessions/2026/10/01/rollout-2026-10-01T15-38-17-01a0ddbb-424f-7e63-8679-cec2726239cb_01a0f553-af80-7071-b8d9-54c31e8a227b.jsonl`

| UTC 时间 / Time | 事件 / Event | 证据 / Evidence |
|---|---|---|
| 06:52:11.175 | 用户要求直接执行浏览任务 / User requests execution | Transcript line 94005 |
| 06:52:37–06:53:35 | 搜索工具、脚本并读取旧桥接代码 / Tool/script discovery and old bridge reads | Lines 94011–94042 |
| 06:53:35.945–06:55:28.891 | 约 112.95 秒无项目工具执行，期间记录上下文压缩 / No project tool execution; a compaction is recorded | Lines 94042–94046 |
| 06:55:33–06:56:22 | 继续读客户端、编写临时 session.py / More client reads and an ad hoc session script | Lines 94052–94079 |
| 06:56:25.999773–06:56:29.074690 | 第一次 launch 因 about:blank 不符合 HTTP(S) 契约被拒绝 / First launch rejected by URL contract | `session/launch.json` |
| 06:56:47.484732–06:56:51.598961 | 修正参数后启动 Edge / Corrected Edge launch | `session02/launch.json` |
| 06:57:28.997648–06:58:22.929557 | 首次地址栏动作，最终中断 / First address-bar command, interrupted | Runtime response for `trial-exec-5b49d46a5aef45eea0c99f93f618c872` |

从用户请求到启动回执约 **280.42 秒**，成功启动命令自身只有 **4.115 秒**。这不是浏览器启动四分钟。工具空档包含上下文处理，但没有足够遥测把它准确拆成推理、压缩服务等待或网络时间；不把整段 112.95 秒全部宣称为压缩计算。

Request-to-launch-receipt time was **280.42 s**, while the successful launch command took **4.115 s**. Browser startup itself did not take four minutes. The tool-free interval contains context handling, but telemetry does not separate inference, compaction-service waiting and network time.

运行证据目录 / Run evidence root (relative to repository):

`.superpowers/sdd/2026-10-10-bilibili-usability/session02/runtime/session-98c48382ab794159a81d495d87dc23d3/`

| 地址栏动作内部 / Inside first address-bar command | 耗时 / Time | 说明 / Interpretation |
|---|---:|---|
| Command wall time | 53.931 s | Sequence sub-timer is 53.864 s; scopes differ |
| `model_prepare_or_reuse` | 34.794 s | Cold preparation; owner queue wait only 0.069 ms |
| `browser_content_preparation` | 7.208 s | First whole-tree UIA sample |
| `browser_content_capture_binding` | 7.074 s | Second whole-tree UIA sample after capture |
| `capture_live_window` | 0.055 s | Actual screenshot slice |
| `recognition_plan` outer span | 0.128 s | Unique structured UIA target selected |
| `click_point` | 3.236 s | Rejected before mouse-down due to cursor drift |

模型准备和两次串行 UIA 共 **49.077 秒**，约占该命令 **91%**。两次 UIA 都包含在 `owner_dispatch=18.947秒` 内，不能再把 owner 总计加一次；其他累计采样也不得重复相加。

Model preparation and the two sequential UIA scans total **49.077 s**, approximately **91%** of the command. Both UIA scans are nested within the **18.947 s** owner dispatch; these inclusive timers must not be summed again.

## 实际走了什么 / Actual route

- VISTA 服务确实启动、加载权重并接受健康/模型身份查询。但识别 trace 是 `model_io.status=skipped`, `reason=current_unique_structured_uia_target`, `attempt_count=0`, `vision_model_used=false`, `coordinate_source=windows_uia`。加载模型后没有进行视觉推理。/ VISTA was started and checked, but actual grounding skipped model inference and selected UIA coordinates.
- `decision_service.used=0`, `remaining=8`, `unknown_dispatches=0`。流程没进入 Decision 审核，不能归因于 Decision 延迟。/ No Decision request was made; this run cannot establish Decision latency.
- 模型准备计时没有完整细分。模型日志中的权重加载约 8.98 秒，不能把剩余约 25 秒全部叫权重加载、OCR 或 GPU 初始化。该轮没有显式 `prepare_models` 命令或 OCR 预热计时。/ Weight loading accounts for about 8.98 s of the preparation log; the remainder is not fully instrumented. No explicit model-preparation/OCR-warmup command was issued.
- 旧 `session.py:53–78` 一次 `async with client` 覆盖 inbox 循环。两次额外 `targets` 是调试桥接观察，不能称每动作重启。/ One persistent client covered the inbox loop; extra target observations were debugging calls, not host restarts.
- 光标移动后，在 mouse-down 前检查中从预期 `(1455,267)` 变为 `(1444,185)`，代码先抛错，后续输入和导航未完成。收据仍保守记录未知；没有独立 OS 事件审计，也没有证据确定谁移动了鼠标。/ The cursor drifted before mouse-down. The code rejected input; there is no independent OS-level audit or evidence identifying the source of cursor movement.

主要原件 / Primary evidence:

- `runtime-output/local-direct-steps/local-step-2ef6169e0d04414597e447947aba1128/report.json`: `invocation_timings`, `local_step_timings`, `response.data.timings`, `response.data.recognition_plan`, `response.error`.
- `sequence-progress/trial-exec-5b49d46a5aef45eea0c99f93f618c872.json`: first step only, no completed steps, `focus_input_not_confirmed`.
- `runtime-output/model-services/88dcca54c99d485d9eff4e591305de93/logs/local-vision-server-vista_4b_transformers-20261010-195729.log`.
- `report.json`: session configuration and Decision counters.

## 当前源码缺口 / Current source gaps

1. `scripts/execution_client.py` 已有持久连接入口和离线覆盖，但尚未成为本轮正式操作入口；旧实机任务没有使用它。增加脚本不等于消除 Main 临时查源码、造命令的交互过程。/ The persistent client exists with offline coverage but did not drive the observed run. Adding a script does not by itself remove Main's ad hoc orchestration.
2. 新 `direct_visual` 分支跳过旧浏览器准备，但 `input_sequence` 的显式 `target.name` 仍进入 `LocalTextFocusTarget(expected_label=...)`，继而可能到 `_verify_named_focus_hit` / `_scan_controls`。不能仅凭视觉分支测试宣称所有输入路径不扫树。/ Direct visual grounding skips old preparation, but named input-focus checks can still reach a control-tree scan.
3. `app/api/action.py:3004` 把 `pre_input_validator` 放入传给 `click_point` 的关键字参数；`app/core/input_controller.py:182` 的真实签名不接收它。已运行 `inspect.signature(InputController.click_point).bind(None, 1, 1, pre_input_validator=lambda: None)`，得到 `TypeError: got an unexpected keyword argument 'pre_input_validator'`。这只是离线签名绑定，没有调用输入方法。/ A real signature mismatch was reproduced offline without calling the input method.

该缺口违反公共输入入口契约，宽松 fake 接受额外关键字造成离线覆盖遗漏。所需修复应在共用 action/controller 边界，适用于所有应用；需要真实方法签名约束和输入前回调顺序的离线回归。当前未修复，不允许用旧测试通过数宣称新路径可用。保持窗口、坐标、证据新鲜度与危险动作门禁，不以删除校验换速度。

The mismatch violates the common input-boundary contract and was hidden by permissive test doubles. Repair belongs at the shared action/controller boundary with signature-bound and pre-input ordering coverage. It remains unresolved; earlier test counts do not prove the new path usable. Preserve window, coordinate, freshness and dangerous-action checks.

## 调整后的优先顺序 / Revised priorities

1. **P0：固定正常入口并闭合真实调用契约。** Main 通过已知持久入口提交任务，不现场查代码编写桥接；先消除上述参数不匹配和假测试遗漏。/ Integrate the fixed entrypoint and repair the actual invocation contract first.
2. **P0：落实普通执行的直接视觉路径。** 定位不用整树控件检索；输入字段必要的当前目标/可写性校验单独保留并约束范围。模型按选定路线准备、同会话复用。/ Use direct visual grounding for ordinary execution; retain bounded current-field/writability checks and reuse only the selected model service.
3. **P0：按完整链验证。** 截图→模型定位→门禁输入→Decision 判定→自动下一步；异常返回现有 Main，不重新执行结果未知的输入。分别记录从用户提交开始的总时间、首次冷启动、暖态与 Main 往返；不要只测内核毫秒数。/ Verify the full route and distinguish user-visible elapsed time, cold/warm model state and Main round trips.
4. **P1：再评估自动学习复用索引。** 索引是后续分流优化，不阻挡直接执行主链，也不作为本次慢速修复的完成依据。/ Evaluate automatic learned reuse later; indexing is not the fix or acceptance criterion for this incident.

本地视觉首次调用确实可能需要加载模型；提前准备只移动成本，不代表成本消失。旧版本有驻留复用代码，但本次首步失败后没有第二次成功运行，因此没有暖态收益证据。本轮没有执行新的实机或 API 验收。

The first local visual call can still require loading. Preloading moves that cost; it does not remove it. Residency/reuse code exists, but this failed first action provides no warm-run benefit evidence. No new live or API acceptance was performed in this audit.

## 后续：控件扫描职责审计 / Follow-up: control-scan responsibility audit

用户要求进一步审核扫描为什么慢，以及它在普通执行中的职责。本轮仍未修改生产行为，也未做桌面/API测试。/ The follow-up reviews scanner cost and its role in ordinary execution. Production behavior remains unchanged; no desktop/API test was run.

### 已确认的问题 / Confirmed findings

1. **P0，控件扫描替代了普通视觉定位。** 旧调用把 `target={control_type: Edit, name: 地址和搜索栏}` 传入组合输入；`task_plan_target` 进入结构化 UIA 主路径，`vision.py:3341–3343,4051–4055,4263–4265` 直接选择控件坐标并记录模型跳过。这是定位通路，不仅是执行后审核。当前直接视觉分支已尝试切断旧主路径，但尚有前述接口缺口。/ The observed structured UIA route supplied coordinates and skipped vision. It was a grounding path, not merely post-action review. The newer direct-visual branch is still incompletely integrated.
2. **P1，扫描范围和工作量远超地址栏所需。** 原始两轮均遍历510个节点，输出487个控件，其中439个属于网页正文；每轮还生成56节点/47控件的浏览器外壳子快照。预算4000节点、无截断、无别名、无环；不是撞到上限、循环遍历或空页面等待。`uia_provider.py:283–325` 先整窗遍历和建模，再生成浏览器外壳快照。/ Each scan visited 510 nodes and emitted 487 controls, with 439 in the document; a separate chrome snapshot visited 56 nodes and emitted 47 controls. Neither scan was truncated or cyclic. A full browser snapshot also constructs a separate chrome view.
3. **P1，触发条件依赖语言，中文地址栏被当成网页字段。** `browser_content_readiness.py:139–153` 因存在组合输入上下文进入准备，但排除式只检查英文 `browser/address bar/toolbar/omnibox`。离线直接调用 helper 证实：相同上下文下“Microsoft Edge 顶部地址和搜索栏”进入准备，`Microsoft Edge address bar` 跳过。修正应依据显式目标范围和执行路线；仅补中文词不解决视觉路径不该整树扫描的职责问题。/ A local text-focus context enabled preparation, while the exclusion regex only recognized English browser-chrome wording. The Chinese address-bar goal entered preparation; the English equivalent skipped it. Route/scope should determine this behavior, not a language-dependent keyword patch.
4. **P1，节点预算不等于时间预算。** `_bounded_uia_walk` 仅限制访问数量，同步属性/父链调用无本函数层面的墙钟截止。`prepare()` 首次扫描后才开始1.5秒轮询预算；`capture_snapshot()` 又同步扫描一次。本轮两次初始采样都已有Document，根本没有轮询等待。离线模拟每次扫描7秒，实际控制流仍走完两轮、累计14秒、sleep调用0。/ The traversal is count-bounded, not elapsed-time-bounded. Readiness polling starts its 1.5-second budget after the first scan; capture binding performs another synchronous scan. The observed run already had a Document and did not poll.
5. **P1，视觉输入分支仍可能隐式全窗核验。** `input_sequence.py:204–208,341–342` 把声明的目标名称带入 `LocalTextFocusTarget.expected_label`；`windows_text_field_reader.py:963–980,1171–1172` 在坐标命中后再做全窗唯一名称扫描。此段不生成坐标，但仍有整树成本，不能误称所有剩余 UIA 都只是点查询。/ Named input focus can still perform a whole-window uniqueness scan after visual coordinate selection. It does not generate the point, but it remains a full-tree cost.

### 为什么一轮有这么多工作 / Why one scan does substantial work

命名字段扫描还有 `form_fill.py:327–332` 逐字段传入label的入口，不能只检查单次input_sequence。另显式 `native_condition` 使用按名称/类型的原生结果断言，与Decision截图判断分离；它不是坐标定位，也没有本轮独立耗时。底层 `vision.recognition_plan` 未携 `direct_visual` 时仍有旧分支，本次未证实普通动作会绕过 `/action` 默认策略调用它。/ Form-fill also supplies labels per field. Explicit native conditions are separate outcome assertions, not coordinate grounding, and were not timed separately. The lower-level recognition API retains legacy branches without the direct-visual marker; this audit has not established a normal-action bypass of the action defaults.

`_bounded_uia_walk` 逐节点读取子元素并验证身份、父边；`CanonicalUIAGraph.tree_identity` 读取所属进程、顶层父窗等信息；`_control_from_wrapper` 读取几何、名称、类型、类名、可用/可见状态及多个 UIA pattern，再投影祖先关系。全浏览器快照还生成外壳快照。它不是一次按名称查询，而是建立整个界面的详细结构。

The scanner enumerates children, verifies identities and parent edges, reads top-level ownership, materializes geometry/name/type/state/pattern properties, reconstructs ancestry, then builds a chrome view. It constructs a detailed interface model rather than issuing one target-name lookup.

已测到的是每轮整体约7秒，没有逐COM调用计时，不能精确声称某个属性、父链或模式查询独占多少秒。扫描两次是旧设计为了先观察可访问性、再把新树绑定到新截图；保留旧树直接点击不是解决办法，应让普通视觉执行根本不进入此定位通路。两次报告的 `page_ready_verified` 都是null，扫描到Document不代表已完成任务语义判断。

Only whole-scan latency is measured; no per-COM timing attributes exact cost to a particular property. The old two-scan design first observed accessibility, then bound a new tree to a fresh capture. Reusing stale tree coordinates is not the remedy; ordinary visual execution should avoid that grounding route. Both reports leave `page_ready_verified=null`, so Document presence does not establish semantic task success.

### 职责边界 / Intended boundaries

| 场景 / Scenario | 控件读取的职责 / Role of control access |
|---|---|
| 普通执行定位 / Ordinary grounding | 视觉模型输出当前截图坐标，不默认扫描完整控件树 / Vision selects current-image coordinates; no default full-tree scan |
| 普通输入保护 / Input protection | 当前窗口、命中点、焦点身份与可写性等有界检查；不能暗中升级为全窗唯一名称检索 / Bounded window, hit-point, focus-identity and writability checks; no hidden promotion into global name search |
| 已批准学习复用 / Approved learned reuse | 若资产明确指定UIA规则，可用其范围内的控件定位；与图像模板路线区分 / Explicit UIA recipes may resolve within their declared scope; keep image-template routes distinct |
| 动作结果判断 / Outcome checking | 按已选核验策略用图像/Decision，异常回Main；填写值的确定性回读是独立检查 / Use the selected image/Decision policy and escalate exceptions; deterministic text readback is a separate check |

### 本轮验证 / Follow-up verification

```powershell
& D:/agent-gui-runtime/.venv/Scripts/python.exe -B -X utf8 .superpowers/sdd/2026-10-10-control-scan-audit/probe.py
```

退出码0，复现两个现有问题：中英文触发差异、1.5秒预算未涵盖扫描总时长。使用替代采集器与模拟时钟，不访问真实窗口或图片，也不将模拟14秒当作新的真实性能数据。原件计时仍是7.208/7.074秒。本轮只定位问题，没有宣称修复。/ Exit 0 reproduces the language-dependent helper gate and missing end-to-end scan deadline using substituted snapshots and a simulated clock. It does not perform live capture or produce new provider performance data. The measured scan times remain 7.208/7.074 seconds; no fix is claimed.
