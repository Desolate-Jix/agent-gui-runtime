## 第五批：单步与恢复观察 / Slice 5: local step and recovery observation

2026-10-01，权威开发工作树分支 `codex/dev-workflow-editor`。`app/execution/local_direct_step.py` 与 `post_action_recovery.py` 是维护实现；两个 desktop_review 旧文件是 sys.modules 同对象别名。两个实现与本批迁移前备份逐字节一致，coordinator 增量只改 LocalDirectStepMixin 的导入。/ The canonical execution implementations match the slice backups byte for byte; legacy paths are same-object aliases and the coordinator delta only redirects its mixin import.

保留 `_execute_local_step_on_owner(..., learning_context=None)`、原窗口/截图/坐标验证及原 `_post_action` 门控路由。学习 scope 仍在 owner 中惰性进入；默认普通执行不进入该 scope，异常退出恢复 ContextVar。Jobs 原票据冻结、持久化 attempt 与回执保存顺序未改。只读恢复候选不授予输入、不自动重试。/ The original owner, input gate, window/capture validation and optional learning scope remain. Context cleanup and original durable receipt semantics are retained; recovery observation remains advisory.

可选决策 API 继续复用 core/outcome_judgment；接线边界见 [OPTIONAL_JUDGMENT_AND_MODEL_USAGE.md](OPTIONAL_JUDGMENT_AND_MODEL_USAGE.md)。预检明确导入并核对 canonical/alias 实际来源及判断合同，不创建 provider、不求值。没有新增执行器、设置 UI、公共 API 或供应商。/ Preflight verifies actual canonical/alias origins and the existing judgment contract without evaluation or a provider; no executor, settings or public endpoint is added.

验证：原相关基线 84 passed；新增边界迁移前 15 failed/13 passed，迁移后 28 passed；学习基线 1 failed/9 passed（旧 manager test double 未跟随 durable attempt），修正后 11 passed；Main 合并 352 passed。集合重叠。原失败与修复证据保留，不算首次通过。/ Baseline and overlapping regression sets are recorded separately, preserving first failures.

隔离源码目录含 885 个文件，python -I 与临时 cwd 检查 192 个本地模块来源，全部位于该目录；输入/截图/模型推理均 false。未生成 ZIP/安装器、改版本或发布。此检查不证明真实动作或供应商连通。证据根：D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261001-execution-extension-ports-01。host/coordinator 其他共享职责仍未全部整理。/ Isolated source/entrypoint validation passes without input, inference or release; live acceptance and remaining host/coordinator layering are separate work.

## 2026-10-01 中断事实修复 / Durable interruption facts

共同 AgentCommandJobs 现在拥有原调用 attempt 的持久化；此修复未迁移其物理目录、复制执行器或改动作权限。Instant/Qt 分别只读诊断与显示。剩余 host/coordinator 共享依赖仍需按调用链收拢。/ Durable attempts remain in the maintained shared command layer; no executor copy or authority change. Broader host/coordinator boundaries remain unfinished.

详见 [WORKFLOW_INTERRUPTION_CONTRACT.md](WORKFLOW_INTERRUPTION_CONTRACT.md)。/ See the interruption contract.

## 2026-10-01 学习连接的职责收拢 / Learning client responsibility boundary

`WorkflowRunClient` 现分离只读 attachment 核验与派发前 live gate。宿主实际退出后，新客户端及新开的普通 main 可读取本轮原结果、输出和回执，执行/继续/取消按钮禁用，账本与命令字节未变。活宿主仍完整验证 PID、创建时间及 runner；`control`、原回执绑定和动作门控保持原实现。 / Validated read-only attachment now works after the original host exits; dispatch still requires the original live identity and gate. Ordinary reopening preserves the ledger and disables action controls.

这只证明退出后的只读重连，不是原宿主进程重启续跑。活动 workflow 切换独立顶层弹窗仍不支持：admit 只放行原 ticket 的确切 EID/command，不能放宽竞争 select 代替窗口迁移合同。死宿主的原 worker 仍不能从磁盘自动恢复，未知结果不能当作未输入而重放。 / Read-only reconnection does not restore a dead worker or permit competing window selection; active dialogs and process restart remain open.
没有移动 host/coordinator 或删除共享历史维护依赖。此小片把原客户端的只读读取与存活派发核验分开，继续使用同一个 Instant、runner、Trial 与原 action gate；Main AST 核验 control/result/marker/receipt/recovery/runner 身份方法未改。 / This bounded separation retains the original runtime and shared maintained dependencies, with unchanged dispatch and receipt methods.

验证：目标编辑预检 31 passed；Main 合并检查 93 passed；只读恢复相关 worker 回归 250 passed。集合重叠，不相加。只读修复首次红阶段 5 failed / 41 passed 保留；实际输入首次完成两轮。审计先把 runner 投影误当原 trial、随后构造器参数写错，两个失败报告保留；改为原 public runner.status 全量核对后通过，未重放输入。 / Overlapping checks are reported separately. First failures remain retained; audit repairs required no input replay.

证据 / Evidence：`D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261001-learning-target-rule-edit-01/main-live-audit-final.json`、`live-01/dead-host-reopened.json`、`D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261001-learning-recovery-boundary-01/main-integrated.xml`。未改版本、打包、发布或替换安装候选。 / No version, build, publication or installed-candidate replacement.

# 执行模块边界整理 / Execution module boundary cleanup

## 目标与范围 / Goal and scope

2026-10-01：按用户要求梳理正式版源码，暂不发布；学习工作流继续沿既定计划开发。目录名称应表达真实职责，整理不得改变动作授权、窗口绑定、结果核验或模型路线。

Clean up maintained execution source without publishing. Continue the learning-workflow plan. Physical layout should reflect ownership; cleanup must preserve action authorization, window binding, verification and model routing.

## 已核对的依赖 / Verified dependencies

整理前，MCP 请求校验、视觉作业和本地宿主均直接引用 `app/desktop_review/input_sequence.py` 与 `form_fill.py`。两者是共用执行服务，没有审核 UI 职责；条件观察也是执行期只读能力。它们继续依赖现有 coordinator，不能另建执行器来解除目录耦合。

Before cleanup, MCP validation, visual jobs and the local host directly used services under desktop_review. These services and conditional observation are runtime capabilities, not review UI; the original coordinator remains authoritative.

## 本批计划与完成检查 / This slice and completion checks

1. 将填写编排与条件观察的唯一实现迁入 `app/execution/`；保留旧路径为同一模块对象的兼容入口，防止旧调用方、测试替换和异常类型发生分叉。 / Move the single implementations into app/execution; old imports must resolve to the same module objects.
2. MCP、视觉调度、宿主和依赖预检改用新入口；现有 direct-step 条件观察调用也改用新入口。不迁移巨型 coordinator、学习编辑器或历史数据。 / Update maintained callers and preflight; keep coordinator, learning editor and historical data in place.
3. 验证新旧导入身份、替换行为、输入与表单合同、条件观察和原请求回执；在隔离源码目录检查真实功能入口的依赖。该检查不得派发输入或调用模型。 / Verify identity, patch propagation, execution contracts, observation and receipts; check functional imports in an isolated source bundle without input/model calls.
4. 同步 README、架构与当前状态，明确源码整理不代表已发布包更新。记录首次失败和复测，保留原备份。 / Sync docs, retain failures and backups, and distinguish source changes from published packages.

## 后续边界 / Remaining boundaries

`desktop_review` 中的 host、coordinator 与审核数据仍有共享职责；`app/learn` 下部分历史模块仍是维护依赖。本批只关闭已核实的小范围耦合，不宣称全项目分层完成。下一批先依据调用链归属再迁移；只有核实无当前引用、远端备份和唯一数据后才考虑退役。

Host, coordinator and review data still share responsibilities; some historical app/learn modules remain maintained dependencies. This slice does not complete the full layering effort. Further moves require call-chain evidence; retirement also requires dependency, backup and unique-data checks.

## 本批结果 / Slice result

三个新模块与原文件备份逐字节一致，五个维护调用入口仅替换导入；原输入检查、流程和错误处理没有改写。新旧入口使用同一模块对象，保留替换传播和异常身份。首轮新增边界测试 8 failed；第一次相关回归 2 failed / 400 passed，原因是依赖预检漏掉旧兼容入口的来源与缺失检查；补齐后 403 passed。主 Agent 核对备份增量并扩展至 API、记忆目标和工作流接线，477 passed。

The three canonical implementations match the original backups byte for byte. Consumer changes only redirect imports. Initial tests failed as expected; the first regression exposed omitted compatibility preflight checks, which were restored. The worker rerun passes 403 checks; main-agent integration rerun passes 477.

独立源码目录包含 865 个维护文件（约 16.2 MB），使用 `python -I` 和临时工作目录检查真实输入/读取入口、请求校验及模块来源，结果 passed=true；input_executed/screenshots_taken/model_inference_tested 均为 false。未生成 ZIP/安装器或更新已发布包。证据、备份与首次失败均在 `D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261001-learning-acceptance-01`。

An isolated source directory passes real entrypoint dependency/request/source checks using isolated Python and a separate working directory. No input, screenshots or inference were executed by preflight, and no ZIP/installer or published package was produced.

第二批将 LocalKeyRequest、LocalActionFieldsError 和字段校验函数归入 execution；旧合同仍为模块别名，原 keyboard handler 保留、导出同一请求类型。主 Agent 核对模型/错误类 AST、校验 AST（仅移除原模型导入）与 handler 函数字节保持，相关 worker 回归 307 passed；两批与学习 UI、评分、API/运行接线最终合并 774 passed。白名单同步包含当前 README 引用的维护说明，文档漏包检查先失败后 10 passed。

The second slice moves action-field contracts and the keyboard request type while retaining the original handler and aliases. Main checks preserve AST/handler semantics. The final combined run passes 774 tests; the documentation selection regression is fixed and its ten checks pass.

最后复用同一隔离源码目录更新本批改动和说明，包含 874 个维护文件；执行入口预检再次通过。另用 python -I 从该目录启动实际学习工作台的全新空状态，Qt 离屏检查三个普通入口、定义摘要和关闭，93 个本地模块全部来自隔离目录；没有启动执行宿主或派发输入。学习工作台入口依赖检查也与真实动作验收分开记录。

The same isolated source directory is refreshed to 874 files. Execution preflight passes again; a separate isolated Python process opens and closes the actual offscreen learning workbench on fresh empty data. All 93 local modules originate in the bundle, with no host or input dispatch. This is dependency/startup coverage, not physical acceptance.

首次隔离离屏截图缺中文字体，启动/依赖检查通过但布局未计通过。补测试进程的系统字体注册后，新空目录重跑和中文原图核对通过；产品源码与字体配置没有改动，首次图和字体探针证据保留。 / Initial startup passes but a fontless offscreen capture is not layout acceptance. Registering the existing system font in the test process produces a verified fresh rerun; product source/settings remain unchanged.

## 第三批键盘派发 / Third slice: keyboard dispatch

press_local_key 的唯一完整模块迁入 app/execution/local_keyboard_action.py，与 keyboard-before 备份逐字节一致；原模块改为同对象别名。direct-step 与预检改用 canonical handler，仍验证旧入口和请求类身份。初始新增检查 5 failed / 10 passed；首次回归 2 failed / 308 passed 是新增测试把 dict 当对象访问，修正断言后 310 passed。原件、首次结果、最终结果与离线预检在 20261001-learning-provenance-01；没有真实输入、截图或模型推理。

The entire keyboard handler module moves byte for byte, retaining alias identity and original behavior. Initial failures and a test-only assertion defect are preserved; the scoped rerun passes 310. Evidence includes the original bytes and dependency preflight, separately from physical acceptance.

## 第四批单步线程所有者 / Fourth slice: single-step runtime owner

SerialRuntimeOwner、RuntimeOwnerProxy 与 RuntimeOwnerError 的唯一模块逐字节迁入 app/execution/single_step_runtime_owner.py；旧入口保持 sys.modules 同对象别名，coordinator 只改 owner/proxy 导入。惰性启动、串行线程、COM 生命周期、重入、操作范围、输出目录与错误传播没有改写，也没有新建执行器。依赖预检显式检查新旧模块、类、异常、停止哨兵与初始化/释放函数身份和 callable，不启动线程或 COM。

The owner module moves byte for byte to app/execution; its legacy import remains a same-object sys.modules alias. The coordinator only redirects owner/proxy imports. Lazy startup, serialization, COM lifecycle, reentry, scopes, output roots and errors remain unchanged. Dependency preflight verifies module/symbol identity and callability without starting owner threads or COM.

新增合同首轮 5 failed，均因迁移前 canonical 模块缺失；迁移后相关回归首轮 110 passed。补充代理方法同线程和缺失 canonical 拒绝检查后，最终 113 passed；python -I 入口依赖预检通过，input_executed/screenshots_taken/model_inference_tested 均为 false。原件、SHA256、首次失败、JUnit 与预检证据保存在 D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261001-learning-runtime-owner-01。没有发布、打包或实机动作验收。

The initial five contract failures record the absent canonical module before migration. The first scoped regression passes 110 tests; the final regression with proxy-thread and missing-module checks passes 113. Isolated-Python entrypoint preflight passes without input, captures or inference. Backups, SHA256, first failures, JUnit and preflight evidence are retained in the runtime-owner evidence directory. This is source/dependency verification, not release or physical acceptance.

主 Agent 核对迁移字节、coordinator 唯一导入变化及原预检语句保持，扩展原工作流接线回归 166 passed；新独立源码目录 880 个文件、188 个本地导入来源的预检通过。随后普通学习运行页能力声明修复与 owner 合并回归 255 passed；集合重叠不相加。目标消失/重复实机负例及清理见学习验收记录，不能代替完整 R3 或收益验证。 / Main checks confirm unchanged bytes and original preflight statements, then pass 166 scoped tests and isolated dependencies. The combined owner/declaration run passes 255 overlapping tests; bounded physical negatives do not close full recovery or benefit gates.
