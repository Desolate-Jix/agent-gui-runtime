# Unified settled observation / 统一动作后观察

2026-10-15，未发布源码。 / Unreleased source.

用户要求先优化执行流程，真实截图benchmark随后进行。现有单次Google→java计划耗时53.544秒，窗口就绪至最终图93.061秒；调用方计划外调度和重复本地观察分别处理，不把它们算成模型推理。 / Pipeline speed comes first; the real-screenshot benchmark follows. Caller gaps and local observation costs are tracked separately from inference.

## Scope / 范围

`LocalDirectStepMixin` 的纯视觉 `execute_recognition_plan` 在明确要求最终观察、无原生condition、无独立decision_check、无学习/记忆/原生控件目标时，安装一次内部承接能力。 / Eligible visual local steps install a one-shot internal capability only when the enclosing step will collect settled evidence.

能力绑定owner、线程、step、完整进程身份、窗口几何、原请求摘要、caller与Verifier实例。不可从JSON启用，不跨步骤、线程或异常退出保留；同能力只领取、消费一次。 / The capability is bound to the execution owner and exact current call, is not a public JSON switch and is revoked on exit.

公共动作路由仍验证派发前截图、目标与Decision结果。只有原本属于 `diagnostic_not_agent_review` 的泛用即时诊断交由最终观察承接；原生/特殊语义/学习验证与独立公共API调用保持原行为。 / Fresh pre-dispatch evidence and model review remain mandatory. Only the redundant generic diagnostic is delegated; semantic and standalone verification remain intact.

## Receipt / 回执

### Same-invocation before image / 同次前图

仅既有scope合格、正式resolver解析为`direct_visual`、当前内部目标精确为`AgentGroundingTarget`或`VisualSubmitTarget`、实时全窗、单击且带最终观察的普通执行步骤，可省去外层仅供报告的前图采集。默认`metadata={}`也命中，不信任调用方声明的路由开关。独立API、无内部目标的本地模型、dry run、ROI、学习/记忆及保存图路线保留原行为。内部路由刚完成实时采图后，经同owner、线程、请求、caller、Verifier、进程身份及窗口几何绑定的单次回调，先将原PNG字节复制到本step的`captures/`，验证坐标和摘要并落盘报告，再继续定位和派发。源文件被公共目录保留策略淘汰时，独立副本仍存在。 / Sharing requires the formal effective visual route and an existing exact internal grounding or submit target. Default requests qualify without a public switch. The same-invocation PNG and report are persisted before further execution; other routes retain their original behavior.

回执以`before_capture_status`区分pending、captured与unavailable。`capture.source= same_invocation_live_capture`和`source_image_path`记录来源；副本不是又一次桌面采集。内部新鲜截图、候选审核、派发前区域校验和最终后图均保留。采图、复制、坐标或落盘失败不能从响应JSON补造前图；成功响应缺少内部发布时，保留可能已派发事实并以结果未知退出，不重放输入。 / The receipt records capture availability and lineage. A durable copy is not an additional desktop capture. Missing internal publication cannot be replaced by response JSON or converted into effect success.

截图像素现直接由原生BGRA解码为RGB，忽略未使用的alpha通道；截图前后窗口、遮挡和坐标校验、遮罩及PNG编码参数保持不变。三张历史2560×1400图的预热交错采样中，此阶段约13–14→6–7毫秒，输出与原PNG逐字节一致；这不是端到端提速比例。 / Direct BGRA decoding removes an intermediate RGB buffer while preserving capture validation and exact PNG output. The isolated local measurement is not an end-to-end gain.

内部即时诊断返回 `verified=None`、`verification_status=awaiting_agent_review`、`diagnostic_status=deferred_to_settled_observation`，并通过 `observation_ref` 指向同step的 `observation.capture`。不伪造after路径，不把deferred视为成功。 / A deferred diagnostic remains unverified and references the enclosing step's final observation.

外层继续原有取消感知等待和采集前后身份校验，使用实际新after完成值/页面审核。最终图不可用时保留已派发事实，返回 `returned_observation_unavailable`，效果未知且不自动重放。 / The original settled capture and effect review remain. A missing final image preserves dispatch facts without claiming success or replaying input.

## Measured baseline and acceptance / 基线与验收

历史五次即时诊断共4.031秒，包括250毫秒固定等待×5、截图1.818秒和其余图像处理。源码改动拟移除这五次冗余诊断；实际净速度、成功率及图片数量必须从新实测读取，不能把历史包络当已实现收益。原三次跳转2秒等待本次保留。 / The previous five diagnostics cost4.031s; this is a historical removable envelope, not a measured new speedup. Navigation grace periods are unchanged.

相关回归包括scope隔离、审核先于输入、primary拒绝后普通复核、拒绝零输入、新after失败与独立路线兼容。两个旧dry_run失败已定位为夹具引用不存在的capture.png；仅补真实PNG和当前元数据，原40条断言保留。 / Tests cover capability isolation, cascade ordering and missing final evidence. The two pre-existing dry-run failures were missing fixture files rather than a weakened capture contract.

## Input-field precheck detail / 输入框前置核验细节

首轮实测保留了Enter回锚前两层拒绝，未派发Enter。原点位于真实输入框内，但旧全长框Detail把34像素框高缩至约11.06像素；该证据支持修复预处理细节损失，不证明模型拒绝的唯一原因。 / The first live attempt retained both pre-Enter refusals and dispatched no Enter. The original point was inside the field, while the previous full-length detail reduced its 34-pixel height to about 11.06 pixels. This establishes a preprocessing detail loss without proving it was the sole cause of rejection.

仅 `target_check.kind=input_field` 的候选前置核验使用点中心最多384×160原像素、最多2倍放大的局部Detail，完整Overview保留。新图为768×320 Detail，首败原图中的框高恢复至68像素；远端框可被裁断，映射明确记录不完整bbox和非UI裁剪边。`decision_candidate_view.v2`、recipe `overview_input_field_point384x160_zoom2.v1` 与认证策略版本隔离旧账本；两层使用同图，graphic与输入值整框视图保持原字节，动作前后证据、原坐标、问题、选项、阈值及等待不变。 / Only normalized input-field candidate prechecks use the point-centered crop of at most 384×160 source pixels with at most 2× enlargement and a complete overview. The 768×320 detail restores the original failure image's field height to 68 pixels; mapping truthfully reports omitted field ends and non-UI crop edges. Mapping v2, the named recipe and authenticated policy version isolate old ledger entries. Both review layers share the image; graphic and whole-field value views remain byte-identical, and evidence collection, original coordinates, questions, choices, thresholds and waits are unchanged.

相关四组离线回归101项通过，包括6个既有完整wire SHA不变。这里只确认几何、认证、路由和字节兼容；真实准确率与净速度收益尚未验收。 / All 101 related offline tests pass, including six unchanged full-wire hashes. These checks establish geometry, authentication, routing and byte compatibility; live accuracy and net speed gains remain unverified. See [当前目标核验 / Target checks](TARGET_CHECK.md).

## Window enumeration incident / 窗口枚举故障

- **Failure / 故障：** 新采图会话正常关闭MDN窗口后，下次启动在23.78毫秒失败 `InvalidWindowHandle`，未进入真正启动。
- **Invariant / 合同：** 枚举快照中单个已消失HWND不得中断有效候选的发现；全局枚举失败不能伪装为空清单。
- **Fix / 修复：** `WindowManager` 使用原生 `EnumWindows` 快照逐句柄包装，只跳过明确失效窗口；未知查询或全局错误明确上抛。
- **Generality / 通用性：** 同一共享逻辑服务窗口发现、启动前清单和窗口匹配，不是针对MDN或NumPy。
- **Regression / 回归：** 构造前消失、标题读取时消失、全局错误零启动和关闭后再次启动；真实连续复测另行记录。
- **Safety / 权限：** PID、创建时间、exe及唯一性绑定不变；不增加sleep、启动重试或UIA扫描。

现场没有完整堆栈，故障句柄不同于MDN主窗，不能确定它属于哪个进程；离线已复现能够解释该回执的公共失败路径。全局Shell查询失败现在明确报错，不再返回部分清单。 / The disappearing handle's owner is unknown; offline reproduction identifies a matching shared failure path. Global Shell query failures now remain explicit.

Browser profile: `D:/AgentGUI-Projects/test-profiles/amadeus-codex-runtime-edge`, retained without cache reset. / 原浏览器资料保留。

## Candidate encoding / 候选图编码

`prepare_request`内部候选帧只携带闭合annotation metadata，不再提前编码整窗标注PNG。单帧current Choice继续从已校验原图生成原有composite；需要整窗标注的legacy、predicate与freshness路线延迟调用原渲染器，兼容旧metadata＋data_url。binding、原图重读/哈希、格式尺寸、完整像素解码及认证均保留，坏像素仍在派发账本前拒绝。不新增跨截图缓存或公共跳过开关。 / Candidate preparation carries metadata only. Current Choice renders its existing composite directly, while compatibility routes lazily render the original full-window annotation. Existing source checks and authentication remain; malformed pixels are rejected before dispatch accounting. There is no cross-capture cache or public bypass flag.

Main17文件333项回归通过，8条实际HTTP body冻结摘要及4条新旧格式全字节比较通过；该改动不减少token或API次数。worker原始CPU采样准备＋provider约323.1→163.7毫秒；Main随后在真实原图预热后交错5对独立复测为321.571→163.301毫秒，source、binding、完整HTTP body及上传图摘要一致、网络调用0。只反映本地处理，不能外推整条任务收益。原始值、脚本及Main结果保存在02证据目录`encoding-cpu/`。 / Main passed333 related tests and independently reproduced the same-image CPU comparison with five interleaved pairs after warmup. Source, binding, complete body and image hashes match; there were no network calls. The321.571→163.301ms local measurement does not establish end-to-end gains.
