# Luna API 执行提速源码检查点 / Luna API execution source checkpoint

日期 / Date: 2026-10-10. 工作树 / Worktree: `codex/dev-decision-api`.

## 范围和状态 / Scope and status

用户要求直接采用 Luna API 识图，继续全流程提速，测试先申请。本检查点最初记录源码及静态审阅；随后用户批准离线测试，Main组合577通过，1项完整载荷构建未选入。详见[离线证据](LUNA_EXECUTION_OFFLINE_20261010.md)。真实API、桌面动作及性能对照仍未执行；未安装、完整打包、提交或发布。 / The original source checkpoint is followed by approved offline verification: 577 passed, one full-payload build deselected. Live/API performance, installation and release remain unverified.

## 本轮源码 / Source changes

- 固定 `scripts/execution_client.py --luna-api` 选择现有 `external_api` 和 `gpt-6-luna` 配置，在同一宿主会话使用已有 `input_sequence`、`task_plan` 和 `until_wait`。冲突参数拒绝，无密钥明确报错。该标志不启用 Decision；Decision 仍需独立配置及已批准条件。不改变所有用户的默认模型或已安装宿主。 / An explicit persistent Luna caller reuses existing runtime continuation. No implicit Decision or local fallback, and no global paid default.
- API复用连接池，零重试，响应大小受限，总时间预算覆盖预处理至结果验证。CPU处理在阶段边界检查预算，不承诺中途强制中断。默认发送原尺寸；可选缩放回映原图坐标并保留原始证据绑定。本地可选direct路径也接上既有 `max_edge`。 / Pooling, bounded responses and total request deadlines; optional resizing preserves original coordinates and evidence. CPU boundaries are checked rather than forcibly interrupted.
- `click_point` 支持实际调用链已有的 `pre_input_validator`，每次鼠标按下前验证，包括双击第二次；拒绝阻止本次输入，并保留已经发生的部分动作证据。 / Validator runs before each actual mouse-down, retaining partial-action evidence.
- UIA采用每个父节点的原生批量属性采集，同次扫描建立名称/类型和 RuntimeId 索引。保留预算、Document裁剪、真实pattern、rich_text及规范图检查；失效或COM错误明确不完整，不退回旧快照。真实pattern和图身份仍可能发生跨进程读取，因此历史属性微基准不能代表完整扫描收益。 / Per-parent bulk property reads and scan-local indices retain traversal and graph semantics. Live pattern/identity reads remain; earlier property benchmarks are not end-to-end results.
- 普通客户端回执紧凑化，保留原请求、完整回执/图像引用及审核包；结果认证继续验证原图及绑定，但省去重复Base64编码。 / Compact receipts retain references and review packets; authentication omits redundant upload encoding while preserving validation.
- v2语义核验可在明确加载合同下，为点击或提交搜索设置 `render_grace_ms=0..2000`。仅提前采图，不判成功；慢页面仍需观察或审核，可能增加请求。未设置时保留旧等待。 / Explicit loading-aware early capture preserves settlement and may add observations on slow pages; omission retains old waits.

## 已做与未做 / Evidence and limits

源码阶段完成Main及Sol逐段源码/调用链审阅及静态diff检查。后续获批的pytest组合已完成，组件过期shadow断言的首败和复测分别保留；不借用历史通过数。未做真实宿主、UIA/API或准确率/用时验收。 / Source review is followed by fresh approved pytest evidence, with the obsolete assertion failure retained separately. No live-host, Windows provider, real-API or performance acceptance.

尚未扩大截图去重、覆盖层或落盘策略，以免跨越新鲜度边界；测试后根据真实分段用时决定。现有会话复用、组合输入和自动结算并非本轮新发明，关键是核验固定入口确实走到它们。 / Screenshot/overlay/storage changes are deferred pending measured need. Existing session reuse and continuation require integrated verification.

## 已批准并执行的验证范围 / Approved and executed verification scope

离线合成数据、模拟UIA、MockTransport及本机回环HTTP服务；不操作桌面、不调用外部API、不安装。 / Synthetic data, fake UIA, mocked HTTP and loopback-only HTTP; no desktop, paid calls or installation.

1. `tests/test_input_pre_validator.py`, `test_mouse_click_sequence.py`, `test_execution_client.py`, `test_task_plan_client.py`, `test_learning_benchmark_client.py`.
2. `tests/test_external_grounding_api.py`, `test_execution_direct_visual.py`, `test_agent_command_jobs.py`, `test_agent_grounding_target.py`, `test_vision_grounding_contract.py`.
3. `tests/test_uia_native_property_cache.py`, `test_uia_provider_pinned_snapshot.py`, `test_execution_browser_chrome_scope.py`, `test_task_plan_canonical_graph.py`.
4. `tests/test_decision_evidence_encoding.py`, `test_decision_http_deadline.py`, `test_decision_service.py`, `test_task_plan_render_grace.py`, `test_task_plan_observation.py`.
5. 与固定客户端有关的 `tests/test_execution_component.py -k "not real_payload"` 依赖收集回归，排除完整载荷构建，不生成安装器。 / Component dependency regression excluding full payload builds and installers.
6. 组件旧断言修正后加入 `tests/test_decision_default_routing.py`，验证当前默认策略的实际运行分支。 / Functional default routing added after correcting the obsolete copy-test expectation.

已核对隔离边界并完成上述组合，首次失败和修复后结果分别留存。下一步另行申请有明确动作范围及付费上限的真实Luna/Decision与连续桌面比较。 / Isolation was inspected and the combined group passed, with first failures retained. Bounded live/API comparison still requires separate approval.
