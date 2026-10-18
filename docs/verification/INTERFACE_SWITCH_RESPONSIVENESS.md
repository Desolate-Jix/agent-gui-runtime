# 独立界面切换响应 / Standalone interface switching

2026-10-02，开发分支 `codex/dev-workflow-editor`，源码候选 v12。产品版本、正式版工作树和安装包未更新。 / Source candidate v12; no release or package update.

## 故障与公共契约 / Failure and common contract

- 故障：选择独立界面时 Qt 主线程停顿约 1 秒；连续点击会顺序扫描每个选择。 / Standalone selection blocked the Qt UI thread for about one second.
- 根契约：证据校验和文件锁等待不能占用交互线程；结果只能装入发起它的选择。 / Evidence I/O and lock waits must run outside the interaction thread, with results bound to the requesting selection.
- 根因：`InterfaceReviewPane.set_snapshot` 同步恢复历史标注并扫描当前工作流目标，还重复读取/绘制截图。实测恢复约 110ms，目标链接约 748–874ms。仅移动面板工作不够，`InterfaceContentLibrary._selected` 的同步头版本读取仍会等待同一客户端 RLock；争用实测约 851ms。 / Synchronous recovery, target-link validation and redundant image reads dominated; a remaining UI head read also waited for the client lock.
- 修复位置：通用界面面板、独立内容库和线程安全的编辑门面；工作台/流程项目关闭时纳入子面板线程生命周期。没有 Record Desk 专用条件。 / The display/job contract is application independent; parent close includes child-job lifetime.

## 实现 / Implementation

`MemoryEditorClient.background_interface_loading` 启用整批后台显示读取，包含头版本、原始证据、恢复框、目标关联和动作图字节。每面板一个活动任务和一个最后待选；新选择立即清除旧图/框并禁编辑，选择序列使旧结果失效。标题与文本立即跟随新选择。 / The editor client opts into a complete background display read, one active job and the latest pending selection. Text updates immediately; old images/results cannot contaminate the new selection.

原证据校验保留，读入字节再核对 SHA。当前选择内切换已学动作使用这次载入的图字节；更换或重读快照重新验证，不用跨快照缓存。失败清图、禁保存/审核/动作并显示错误，可重新加载。普通同步 façade 保留原契约；正常关闭和 DeferredDelete 等待在途任务结束。 / Validation and byte hashes remain intact. Images are reused only inside the loaded selection; reload validates again. Failures are explicit and uneditable, and close/deletion guard active jobs.

## 同库测量 / Same-library measurement

测量脚本使用普通 `run_learning_memory_workbench.main` 入口，在离屏 Qt 中读取当前 P4 归档库。基线从修改前备份载入 5 个模块，记录它们的 SHA；修复后载入当前源码。没有模型调用或外部输入。 / The ordinary entry was measured offscreen; the baseline loads five saved pre-change modules with recorded digests. No model calls or external input occurred.

| 指标 / Metric | 基线 / Baseline | 修复后 / Fixed |
| --- | ---: | ---: |
| 12 次逐个选择回调 / Sequential dispatch | 881–1041ms | 0.416–0.514ms |
| 逐个选择的最大 UI 心跳间隔 / Maximum event-loop gap | 1041.825ms | 8.160ms |
| 连续 12 个选择的回调总耗时 / Twelve rapid dispatches | 11400.897ms | 2.153ms |
| 连续选择的最后证据就绪 / Final rapid evidence ready | 11404.614ms | 2121.997ms |
| 逐个选择完整证据就绪 / Sequential evidence ready | 885–1045ms | 951–1122ms |

后台化修复的是卡住界面的等待；单个完整证据扫描仍约 1 秒，本轮没有声称扫描本身、模型推理或工作流收益加速。两轮测量均核对 49 个原资产 SHA 未变。 / Background loading improves interaction responsiveness. Complete evidence still takes about one second; no model or workflow gains are claimed. Both runs preserve 49 asset digests.

## 检查与首次失败 / Checks and first failures

新增响应测试先 4 failed，补充头版本线程及图字节范围测试先 2 failed。审阅发现同步清空后重选禁用残留，复现 1 failed；加载中字段需立即跟随新选择，复现 1 failed。非法图片报错与重读恢复也有覆盖。 / The new contracts were observed failing before repair; review also caught synchronous reload state and stale display text. Invalid-image failure and recovery are covered.

子任务首轮旧 UI 断言未等待异步完成，留下活动任务并退出；随后 1 failed 证实加载完成信号覆盖了“固定版本需明确更新”的说明，已修复。子任务最终 19 passed；这是与主回归重叠的源码检查，不是独立实机验收。 / Initial UI timing and message-preservation failures were repaired. The worker's 19 checks overlap the main run and are not independent physical acceptance.

主 Agent 扩展到 v11 原有相关集合时，旧 UI 测试尚未等待加载就编辑，先出现 6 个失败标记，进程在结算阶段以 Windows `0xC0000409` 退出，未产出完整 JUnit。单独复现定位到画布未就绪；为 3 个既有 UI 旅程增加条件等待、实际界面库标签选择和明确结束清理后，3 passed。没有删减保存、重开、旧版本、固定引用或重学采用断言。 / The first expanded run aborted after six failure markers. An isolated replay identified premature UI actions; three existing journeys now wait for readiness and perform complete cleanup without weakening persistence assertions.

最终主 Agent 用 `run_main_tests.py` 运行新增响应及 v11 相关 17 份测试文件，结果 **176 passed in 91.07s**，失败/错误/跳过均为 0；原始命令、输出和 JUnit 均保存。 / The final main-agent run passed 176 checks in 91.07 seconds across 17 relevant files, with no failures, errors or skips.

## 证据与限制 / Evidence and limits

证据目录 / Evidence directory:
`D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261002-learning-mainline-01/interface-switch-fix`

- `profile-sol/results.json`、`profile-sol/client-results.json`：路径耗时与锁争用；只读 workspace 工厂不包含真实跨进程 owner 锁等待。 / Service profile and same-client contention; cross-process owner waits were not measured.
- `before-sol/`、`baseline-measurement.json`、`fixed-measurement.json`、`measure_workbench.py`：基线及普通入口对比。 / Saved baseline and repeatable entry measurement.
- `main-red.xml`、`main-extra-red.xml`、`review-red.xml`、`main-field-red.xml`：首次契约失败；`main-debug-v1.xml`、`main-v1-rerun.xml`：UI 旅程定位及复测。 / Initial failures and isolated UI reruns.
- `main-first-aborted-main-final-output.txt`、`main-first-aborted-main-test-command.json`：保留主回归退出的原始输出和状态。 / Original aborted output and exit status.
- `sol-second-regression.xml`、`sol-verified.xml`：中间失败及子任务最终检查；与主检查不相加。 / Worker checks overlap the main run.

旧进程不会热更新；新源码需从新预览加载。流程项目 `node_selected` 自身同步版本读取未在本批优化。当前测量读取归档内容，只证明显示响应和资产完整性，不替代全新内容的真实连续执行、恢复与清理验收。 / Existing processes require a new preview. Project-node head reads were not optimized. Archived-data UI measurements do not substitute for fresh physical continuity/recovery acceptance.

安全影响：未改变输入门控、目标歧义拒绝、freshness 或最终提交限制；归档截图和界面框仍不构成执行授权。 / Input gates, ambiguity, freshness and final-submit restrictions remain intact; displayed evidence grants no input authority.
