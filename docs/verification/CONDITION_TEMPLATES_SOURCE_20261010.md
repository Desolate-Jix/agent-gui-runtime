# Condition templates, source checkpoint / 条件模板源码检查点

This is unpublished source work under the approved adaptive-review P2 plan. The earlier manual-observation freeze passed 1008 tests with one permission skip; that result does not cover changes made after the freeze. No desktop action, paid API call, build, version bump or publication is part of this checkpoint. / 本页记录已批准 P2 的未发布源码；此前人工观察冻结点的 1008 通过、1 权限跳过不覆盖本次后续修改。本检查点无桌面动作、付费 API、构建、版本升级或发布。

## Implemented slices / 已实现切片

- Pure record-ID templates validate complete template, binding and concrete snapshots. Parameter text is inserted as JSON string data; model yes/no answers do not produce new dynamic output values. / 纯合同校验模板、绑定与实际快照；参数作为 JSON 字符串数据插入，是／否判断不生成动态输出。
- Shared v2 profile/evidence/service wiring supports an exact ID/revision/SHA allowlist and authenticated concrete snapshots. Empty lists preserve old hashes. Unknown templates in auto mode make zero calls; string allowlists cannot approve a template. Shadow does not adopt. / 共用 v2 配置、证据、服务按确切身份批准，完整快照参与认证；空列表保留旧摘要，未批准模板零调用，不能借字符串允许列表绕过，shadow 不采用。
- The source editor supports an input reference or literal record ID, read-only preview and template identity. Advanced rule/scope/policy editing is collapsed initially; editing an existing template's semantics generates one new revision. English/Chinese switching preserves user text and bindings. / 源码编辑器支持输入或常量、只读预览和模板身份；高级规则默认收起，已有模板语义变化产生一个新修订；中英切换不改用户文字或绑定。
- Execution v2 freezes concrete snapshots from plan inputs and independently rebuilds them before dispatch and final adoption. Native UIA conditions remain intact; automatic observation and manual v3 preserve the original binding. / 执行 v2 从原计划输入冻结具体快照，发送和最终采用分别重建；原 UIA 条件保留，自动观察及手动 v3 沿用原绑定。
- Learning saves full bindings in reviewed programs, invalidates changed input dependencies, authenticates original start inputs and preserves them through recovery/import. Ordinary editor save/review/reopen and starts with two different record IDs are covered. / 学习程序保存完整绑定，相关输入声明变更重新待审，认证原始启动参数并贯穿恢复导入；已覆盖普通编辑保存审核、重开及两组记录号启动。
- Runtime and final settlement enforce template/step/enabled-host `always_main`; recovery additionally rejects rule-derived history that violates its pinned template/step policy. Recovery does not invent a historical host profile from today's configuration. Adaptive image success and valid legacy paths remain available without API calls. / 运行和最终结算执行模板、步骤及已启用宿主的审核策略；恢复拒绝违反固定模板/步骤策略的规则来源历史，不用当前配置虚构历史宿主策略；普通图像成功及合法旧路径仍保留零 API 路径。

## Evidence / 验证

All paths below are under `.superpowers/sdd/2026-10-09-adaptive-live`. Overlapping groups are not summed. / 以下证据都位于该目录，重叠组不累加。

| Evidence / 证据 | Actual result / 实际结果 | Scope / 范围 |
| --- | --- | --- |
| `template-pure-red.xml`, `template-pure-green.xml` | Missing-module RED, then 96 passed / 缺模块首败后 96 通过 | Pure contracts, included in Main's earlier 1008 group / 纯合同，已纳入此前 Main 联调 |
| `template-service-red.xml`, `template-service-green.xml` | 27 failed/18 passed, then 45 passed | Worker shared service integration / 子 Agent 共用服务 |
| `template-service-related.xml` | 337 passed, 4.61s | Worker profile/evidence/service/adaptive/deadline group / 子 Agent 相关回归 |
| `template-editor-red.xml` | Missing-module collection error / 缺模块收集失败 | Before editor implementation / 编辑器实现前 |
| `template-editor-compact-green.xml` | 34 passed, 1.07s | Main editor/rules/i18n offscreen group / Main 编辑器、规则、中英离屏 |
| `template-editor-boundary-red.xml`, `template-editor-final-green.xml` | 3 boundary failures retained; 37 passed, 1.11s after repair / 边界首败保留，修复后37通过 | Missing/renamed inputs remain editable; incompatible action kinds require removing the binding / 缺失引用可打开改绑，不兼容动作须移除绑定 |
| `template-editor-program-first.xml` | 1 passed, 0.72s | Ordinary editor → program save/review/reopen → parameterized trial start / 普通编辑器与真实程序服务、试运行入口 |
| `template-execution-final.xml` | 325 passed, 52.17s | Execution wiring before the later host-policy correction / 执行接线，早于宿主策略修复 |
| `template-execution-host-policy-red.xml`, `template-execution-host-policy-green.xml` | 2 failed/2 passed RED; 205 passed, 23.43s GREEN | Enabled host policy enforced at final backend; disabled service unchanged / 最终后端执行已启用宿主策略，关闭服务不变 |
| `template-learning-backend-policy-red.xml`, `template-learning-history-policy-red.xml` | 3 failed; 2 failed/1 passed | Preserved final-settlement and recovery-history omissions / 最终结算及恢复历史遗漏首败保留 |
| `template-learning-core-policy-closed.xml` | 235 passed, 24.50s | Learning core, recovery and policy repairs / 学习核心、恢复及策略修复 |
| `template-source-integration/result.json`, `template-source-integration/pytest.xml` | **1319 passed, 1 skipped out of1320; zero failures/errors; XML129.131s, stdout129.19s, outer130.063s** | Main frozen integration of all slices and both source dependency closures / Main 完整接线及两组件源码依赖闭合 |

Main ran `D:/agent-gui-runtime/.venv/Scripts/python.exe -B -X utf8 .superpowers/sdd/2026-10-09-adaptive-live/check_template_source_integration.py`. Its saved command runs 44 relevant test files and two actual source-collection cases. Before/after manifests match for **1059** Python and translation files. The sole skip is `test_task_plan_observation_capture::test_redirected_observation_directory_is_rejected_before_capture`, because this environment cannot create symbolic links. The editor/program integration is included in this final freeze. / Main 实际执行上述脚本，原件记录44个相关测试文件及2个真实源码收集用例；1059个源码与翻译文件前后SHA一致。唯一跳过是无符号链接创建权限，编辑器与程序普通入口也已纳入最终冻结。

Independent read-only review closed the execution-host final gate, learning final rule gate and pinned-policy recovery-history findings. Main inspected the changes, verified both eight-file manifests and ran the integration itself. Worker counts overlap and must not be summed. / 独立只读复审关闭执行宿主最终门禁、学习最终规则门禁及固定策略恢复历史缺口；Main 核对实际改动和两组8文件清单，并亲自运行完整组合。各组重叠，不累加。

The initial standalone render omitted the maintained offscreen font initialization and displayed missing glyphs. Those images remain as `template-editor-font-missing-*.png`; the render script now calls the existing `ensure_application` and workbench typography/theme helpers. Main inspected the new English and Chinese renderings. This is offscreen layout inspection, not an installed desktop acceptance. / 首次独立渲染脚本遗漏维护的离屏字体初始化，原缺字图保留；修正脚本复用既有初始化后，Main 已查看新版中英截图。这属于离屏检查，不是安装实机验收。

## Still open / 未完成

Source wiring, ordinary save/reopen, recovery authentication and the final offline integration are complete at this checkpoint. A new frozen candidate still needs fresh real single-operation/continuous/recovery/cleanup acceptance, followed by independent acceptance of that same candidate. Candidate01 evidence cannot establish these later changes. / 本检查点已完成源码接线、普通保存重开、恢复认证和最终离线组合；新冻结候选仍须使用全新内容进行实机单项、连续、恢复及收尾，再做同候选独立验收。Candidate01不能证明后续改动。

The literal-only direct `decision_check` command has not been expanded to templates. Source work does not establish accuracy, speed or Main-involvement benefits. / 直连 `decision_check` 仍只接受现有字符串条件，未扩大为模板；源码结果不证明准确率、速度或主 Agent 介入收益。
