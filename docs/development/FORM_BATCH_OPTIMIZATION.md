# 组合填写优化（源码，待实测） / Batch-fill optimization (source, live tests pending)

## 范围与证据 / Scope and evidence

2026-09-26 初始要求“尝试优化先不测试”；后续用户恢复开发测试目标，现已执行相关四文件，130 项通过。第一次环境缺少已声明的 mcp==2.1.1 导致 16 项不能执行，安装到维护工作树虚拟环境后重跑通过，保留首次记录。未启动 GUI、模型或实机宿主，不构建、不发布。旧 test.7 包保持不变。 / Testing resumed under the updated goal: 130 focused checks pass after installing the declared MCP dependency into the development environment. Initial environment failures are retained; no live test, build or publication.

既有真实表单日志：三批框架执行 57.518 s，首批输入至末批完成 250.749 s，其中批间 193.231 s。后者包含 Agent 调度、取图及补充资料等待，不能全归为框架或用户等待。内部聚焦 23.755 s、下拉展开/选择 14.163 s、输入文字 3.011 s、Tab 0.439 s，其他 16.150 s 尚未完整拆分。 / Existing real-form logs show 57.518 s of execution within 250.749 s elapsed; gaps include orchestration, image review and missing-fact collection. Timing is evidence of cost, not proof of a single model bottleneck.

## 通用修改 / General changes

1. **显式混合分组**：`text_navigation=tab_groups` 与文本字段 `tab_group` 允许一个 1–32 字段请求包含多个连续文本组及其他控件。组首重新识别，同组相邻项才复用已检查的 Tab 路径；换组、非文本和未分组项断开继承。分组需精确标签，组内重名提前拒绝；原 recognize_each/tab_sequence 行为保留。 / Explicit groups compose multiple checked text runs and controls in one request. Boundaries reset recognition; exact labels and unique names per run remain mandatory.
2. **按需标签索引**：表单控件读取始终先完整检查有界 UIA 树和重名；已直接按名称命中时不再为无关控件读取可见性、几何、LabeledBy 和重复父边。无名控件仍构建原标签几何索引。不缓存跨动作 COM 对象、旧坐标或截图。 / Complete bounded-tree and duplicate checks remain; named matches avoid the unrelated geometric-label index. Unnamed controls keep existing label binding, without cross-action caching.
3. **回执等待预算**：`instant_run` 未指定 wait_ms 时，form_fill 为 45000 ms，其他仍为 25000 ms；显式预算 0–120000 ms。轮询到结果立即返回，超时仍读同 ID，不取消、不重放。客户端超时需大于等待预算和传输时间。 / Form calls receive a longer default maximum receipt wait, not an action sleep; ready responses return immediately and timeout never replays input.
4. **逐字段耗时**：compact 回执增加 `timings`，区分 field_total_ms、action_ms、read_ms、other_ms。下拉动作内的控件复验耗时另存在完整回执 `action_read_timings`，已计入 action_ms，不重复相加。用于后续定位剩余开销，不输出真实填写值。 / Compact aggregate timing distinguishes actions, external reads and residual overhead; nested control rereads remain in full traces without double counting.
5. **调用指南**：已知字段一次准备、批间不做无关调查、默认读取同次返回的 compact+after；缺失事实独立补充，不用猜值缩短时间。 / Caller guidance reduces avoidable orchestration gaps without guessing missing facts.

## 契约复盘 / Runtime contract review

- Failure：组合虽填对，但重复定位与调用空档过长。 / Correct filling with excessive localization/orchestration overhead.
- Root invariant：同一已声明组合应在本地顺序编排；精确名称命中不应无条件重建未使用的几何索引；任务耗时必须区分执行和调用空档。 / Local batches should not require unnecessary agent turns or unused geometric indexing; report elapsed and executor time separately.
- Fix location：公共 form_fill、控件读取器、MCP 回执边界及 Agent 指南；无站点专用坐标或标签。 / Shared orchestration, UIA reader, MCP boundary and caller guide, not a site adapter.
- Safety impact：未删除输入前身份、唯一性、焦点、选项归属或输入后读回；未新增最终提交、不扩大点击框、不允许自动重放。 / Identity, uniqueness, focus, ownership and readback checks remain; no final submission or blind replay.
- Regression：相关单元/契约 130 项通过；尚无真实填写提速证据。 / 130 focused checks pass; no measured live speedup yet.

## 验证状态与剩余 / Verification and remaining work

- 已跑单元/契约：混合分组、跨控件/未分组/同名重用断组、错焦点中断；精确标签避免无关几何、晚到重名仍拒绝、无名控件继续绑定；45秒默认和显式等待、幂等、partial/after证据不变；耗时投影无重复相加。 / Relevant unit/contract checks executed.
- 真实同页 A/B：相同字段、相同窗口、完整数据先准备，保留原失败；至少两轮连续填写及清理。分开记录外层时钟、框架时钟、用户补充资料时间。 / Use a same-page controlled A/B and repeated continuous runs with cleanup, retaining first failures and separating clocks.
- 本方完成单项和连续回归后，才冻结同版本交 AionUi 独立验收。 / Independent acceptance follows successful local single-operation and continuous checks.

不在此次修改范围：共享点击识别管线重写、删安全校验、减少必须的失败证据、盲目降低等待、自动提交。 / Out of scope: rewriting recognition, removing checks/evidence, blindly shortening waits or auto-submission.
